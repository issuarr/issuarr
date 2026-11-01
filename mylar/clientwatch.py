#  This file is part of Issuarr.
#
#  Issuarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Issuarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Issuarr.  If not, see <http://www.gnu.org/licenses/>.

"""Watching download clients: everything in Issuarr's category, not only what Issuarr sent.

Every minute (or on Refresh) each download client is asked what it holds in Issuarr's
category: qBittorrent, Deluge, rTorrent and uTorrent by their label, Transmission by its
download folder, SABnzbd and NZBGet by their category. Downloads you added yourself show in the Downloads queue, and once they
finish, each comic file whose name matches an issue on the watchlist is filed as that issue.
A download nothing matches waits in the queue as "Needs a choice". Torrent grabs Issuarr
sent itself are filed the same way, as the issue they were grabbed for; SABnzbd and NZBGet
grabs are left to their completed download handling.
"""

import os
import posixpath
import queue
import threading
import time
import xmlrpc.client

import requests

import mylar
from mylar import db, helpers, logger

JOB_NAME = 'Check download clients'
TICK = 1              # minutes between the scheduler's looks; the interval setting decides when a check runs
SETTLE = 50           # seconds a finished download is left alone first, so a client script or unpack can finish
MATCH_TTL = 1800      # seconds a name's watchlist match is remembered
COMIC_FILES = ('.cbz', '.cbr', '.cb7', '.cbt', '.pdf')

CLIENT_NAMES = {'sabnzbd': 'SABnzbd', 'nzbget': 'NZBGet', 'qbittorrent': 'qBittorrent', 'deluge': 'Deluge',
                'transmission': 'Transmission', 'rtorrent': 'rTorrent', 'utorrent': 'uTorrent'}
TORRENT_CLIENTS = ('qbittorrent', 'deluge', 'transmission', 'rtorrent', 'utorrent')

LAST = {}             # client -> {'at': epoch, 'error': text or None, 'items': [item, ...]}
NOTES = {}            # (client, id) -> {'state': ..., 'note': ...} for downloads you added
FINISHED_AT = {}      # (client, id) -> when it was first seen finished
MATCHES = {}          # path or name -> (at, match or None)
WARNED = set()
MISSING = []          # finished downloads first found missing during this check, logged once together
RUN = {'busy': False, 'last': 0.0}
_LOCK = threading.Lock()


def _set(value):
    return value not in (None, '', 'None')


def enabled():
    return bool(getattr(mylar.CONFIG, 'CLIENT_WATCH', True)) and bool(getattr(mylar.CONFIG, 'POST_PROCESSING', False))


def interval():
    try:
        return max(1, int(getattr(mylar.CONFIG, 'CLIENT_WATCH_INTERVAL', 1) or 1))
    except (TypeError, ValueError):
        return 1


def watched():
    """[(client, category)] for each client that is on and has a category for Issuarr."""
    out = []
    cfg = mylar.CONFIG
    if getattr(mylar, 'USE_SABNZBD', False) and _set(getattr(cfg, 'SAB_HOST', None)) and _set(getattr(cfg, 'SAB_CATEGORY', None)):
        out.append(('sabnzbd', cfg.SAB_CATEGORY))
    if getattr(mylar, 'USE_NZBGET', False) and _set(getattr(cfg, 'NZBGET_HOST', None)) and _set(getattr(cfg, 'NZBGET_CATEGORY', None)):
        out.append(('nzbget', cfg.NZBGET_CATEGORY))
    if getattr(cfg, 'ENABLE_TORRENTS', True) and getattr(mylar, 'USE_QBITTORRENT', False) and \
            _set(getattr(cfg, 'QBITTORRENT_HOST', None)) and _set(getattr(cfg, 'QBITTORRENT_LABEL', None)):
        out.append(('qbittorrent', cfg.QBITTORRENT_LABEL))
    if getattr(cfg, 'ENABLE_TORRENTS', True):
        for client, flag, host, label in (('deluge', 'USE_DELUGE', 'DELUGE_HOST', 'DELUGE_LABEL'),
                                          ('transmission', 'USE_TRANSMISSION', 'TRANSMISSION_HOST', 'TRANSMISSION_DIRECTORY'),
                                          ('rtorrent', 'USE_RTORRENT', 'RTORRENT_HOST', 'RTORRENT_LABEL'),
                                          ('utorrent', 'USE_UTORRENT', 'UTORRENT_HOST', 'UTORRENT_LABEL')):
            if getattr(mylar, flag, False) and _set(getattr(cfg, host, None)) and _set(getattr(cfg, label, None)):
                out.append((client, getattr(cfg, label)))
    return out


# ---- what each client holds ------------------------------------------------

def _item(client, jobid, name, state, done=None, total=None, speed=None, eta=None, path=None, message=None):
    pct = None
    if total:
        pct = max(0, min(100, int(round(float(done or 0) * 100 / float(total)))))
    return {'client': client, 'id': str(jobid), 'name': name, 'state': state, 'percent': pct, 'done': done,
            'total': total, 'speed': speed, 'eta': eta, 'path': path or None, 'message': message}


def _same(a, b):
    return str(a or '').strip().lower() == str(b or '').strip().lower()


def sab_items(queue_json, history_json, category):
    """SABnzbd's queue and history -> items in the category. 'Finished' means unpacked and moved."""
    out = {}
    for s in (queue_json or {}).get('queue', {}).get('slots', []) or []:
        if not _same(s.get('cat'), category):
            continue
        total = float(s.get('mb') or 0) * 1048576
        left = float(s.get('mbleft') or 0) * 1048576
        state = {'Downloading': 'Downloading', 'Paused': 'Paused'}.get(s.get('status'), 'Queued')
        out[s.get('nzo_id')] = _item('sabnzbd', s.get('nzo_id'), s.get('filename'), state, total - left, total)
    for s in (history_json or {}).get('history', {}).get('slots', []) or []:
        if not _same(s.get('category'), category) or s.get('nzo_id') in out:
            continue
        st = s.get('status', '')
        total = s.get('bytes') or None
        if st == 'Completed':
            item = _item('sabnzbd', s.get('nzo_id'), s.get('name'), 'Finished', total, total, path=s.get('storage'))
        elif st == 'Failed':
            item = _item('sabnzbd', s.get('nzo_id'), s.get('name'), 'Failed', message=s.get('fail_message') or None)
        else:
            item = _item('sabnzbd', s.get('nzo_id'), s.get('name'), 'Processing', total, total, message='%s in SABnzbd' % st)
        out[s.get('nzo_id')] = item
    return list(out.values())


def nzbget_items(groups, history, category):
    out = {}
    for g in groups or []:
        if not _same(g.get('Category'), category):
            continue
        st = str(g.get('Status', ''))
        total = float(g.get('FileSizeMB') or 0) * 1048576
        left = float(g.get('RemainingSizeMB') or 0) * 1048576
        state = 'Downloading' if st == 'DOWNLOADING' else 'Paused' if st == 'PAUSED' else \
            'Queued' if st in ('QUEUED', 'FETCHING') else 'Processing'
        out[str(g.get('NZBID'))] = _item('nzbget', g.get('NZBID'), g.get('NZBName'), state, total - left, total)
    for g in history or []:
        if not _same(g.get('Category'), category) or str(g.get('NZBID')) in out or g.get('Kind', 'NZB') != 'NZB':
            continue
        st = str(g.get('Status', ''))
        total = float(g.get('FileSizeMB') or 0) * 1048576 or None
        if st.startswith('SUCCESS') or st.startswith('WARNING'):
            item = _item('nzbget', g.get('NZBID'), g.get('Name'), 'Finished', total, total,
                         path=g.get('FinalDir') or g.get('DestDir'))
        elif st.startswith('FAILURE'):
            item = _item('nzbget', g.get('NZBID'), g.get('Name'), 'Failed', message='NZBGet reported %s' % st.lower().replace('/', ': '))
        else:
            continue   # deleted from NZBGet's list by hand
        out[str(g.get('NZBID'))] = item
    return list(out.values())


SEEDING = ('uploading', 'stalledUP', 'queuedUP', 'forcedUP', 'pausedUP', 'stoppedUP', 'checkingUP')


def qbit_items(torrents, category):
    out = []
    for t in torrents or []:
        if not _same(t.get('category'), category):
            continue
        st = str(t.get('state', ''))
        progress = float(t.get('progress') or 0)
        total = t.get('size') or None
        if st in ('error', 'missingFiles'):
            state = 'Failed'
        elif progress >= 1 or st in SEEDING:
            state = 'Finished'
        elif st.startswith('paused') or st.startswith('stopped'):
            state = 'Paused'
        elif st.startswith('queued'):
            state = 'Queued'
        elif st.startswith('checking') or st == 'metaDL':
            state = 'Checking'
        else:
            state = 'Downloading'
        path = t.get('content_path') or (posixpath.join(t['save_path'], t['name']) if t.get('save_path') and t.get('name') else None)
        eta = t.get('eta') if state == 'Downloading' and 0 <= int(t.get('eta') or 0) < 8640000 else None
        out.append(_item('qbittorrent', str(t.get('hash', '')).lower(), t.get('name'), state,
                         (total or 0) * progress if total else None, total,
                         t.get('dlspeed') if state == 'Downloading' else None, eta, path,
                         'qBittorrent can\'t find its files' if st == 'missingFiles' else None))
    return out


def _same_dir(a, b):
    norm = lambda p: str(p or '').replace('\\', '/').rstrip('/').lower()
    return bool(norm(a)) and norm(a) == norm(b)


def torrent_items(client, rows, category, by_folder=False):
    """Torrents read from Deluge, Transmission, rTorrent or uTorrent, already turned into plain
    dicts (hash, name, label, folder, path, progress 0-1, total, speed, eta, paused, queued,
    checking, error, seeding), -> items in Issuarr's label, or download folder for Transmission."""
    out = []
    for t in rows or []:
        if not (_same_dir(t.get('folder'), category) if by_folder else _same(t.get('label'), category)):
            continue
        progress = float(t.get('progress') or 0)
        if t.get('error'):
            state = 'Failed'
        elif progress >= 1 or t.get('seeding'):
            state = 'Finished'
        elif t.get('paused'):
            state = 'Paused'
        elif t.get('queued'):
            state = 'Queued'
        elif t.get('checking'):
            state = 'Checking'
        else:
            state = 'Downloading'
        total = t.get('total') or None
        eta = t.get('eta')
        eta = int(eta) if state == 'Downloading' and eta is not None and 0 <= int(eta) < 8640000 else None
        out.append(_item(client, str(t.get('hash', '')).lower(), t.get('name'), state,
                         total * progress if total else None, total,
                         t.get('speed') if state == 'Downloading' else None, eta, t.get('path'),
                         t.get('error') if isinstance(t.get('error'), str) else None))
    return out


def _dec(v):
    return v.decode('utf-8', 'replace') if isinstance(v, bytes) else v


def _fetch_deluge(label):
    from mylar.torrent.clients import deluge
    client = deluge.TorrentClient().connect(mylar.CONFIG.DELUGE_HOST, mylar.CONFIG.DELUGE_USERNAME, mylar.CONFIG.DELUGE_PASSWORD)
    if isinstance(client, dict):
        raise Exception(client.get('error'))
    res = client.call('core.get_torrents_status', {'label': label},
                      ['name', 'progress', 'state', 'total_wanted', 'download_payload_rate', 'eta', 'save_path', 'label', 'message'])
    rows = []
    for h, t in (res or {}).items():
        t = {_dec(k): _dec(v) for k, v in t.items()}
        st = str(t.get('state', ''))
        rows.append({'hash': _dec(h), 'name': t.get('name'), 'label': t.get('label'), 'progress': float(t.get('progress') or 0) / 100.0,
                     'total': t.get('total_wanted'), 'speed': t.get('download_payload_rate'), 'eta': t.get('eta'),
                     'path': posixpath.join(t['save_path'], t['name']) if t.get('save_path') and t.get('name') else None,
                     'paused': st == 'Paused', 'queued': st == 'Queued', 'checking': st in ('Checking', 'Allocating', 'Moving'),
                     'seeding': st == 'Seeding', 'error': (t.get('message') or 'Deluge reported an error') if st == 'Error' else None})
    return torrent_items('deluge', rows, label)


def _fetch_transmission(folder):
    from mylar.torrent.clients import transmission
    conn = transmission.TorrentClient().connect(mylar.CONFIG.TRANSMISSION_HOST, mylar.CONFIG.TRANSMISSION_USERNAME,
                                                mylar.CONFIG.TRANSMISSION_PASSWORD)
    if not conn:
        raise Exception('could not connect')
    rows = []
    for t in conn.get_torrents():
        st = str(getattr(t, 'status', ''))
        try:
            eta = int(t.eta.total_seconds())
        except Exception:
            eta = None
        err = getattr(t, 'errorString', '') if getattr(t, 'error', 0) else None
        rows.append({'hash': t.hashString, 'name': t.name, 'folder': t.downloadDir, 'progress': float(t.progress or 0) / 100.0,
                     'total': getattr(t, 'sizeWhenDone', None), 'speed': getattr(t, 'rateDownload', None), 'eta': eta,
                     'path': posixpath.join(t.downloadDir, t.name), 'paused': st == 'stopped',
                     'queued': st in ('download pending', 'check pending'), 'checking': st == 'checking',
                     'seeding': st in ('seeding', 'seed pending'), 'error': err or None})
    return torrent_items('transmission', rows, folder, by_folder=True)


def _rt(t, name):
    v = getattr(t, name, None)
    if v is None and callable(getattr(t, 'get_' + name, None)):
        v = getattr(t, 'get_' + name)()
    return v


def _fetch_rtorrent(label):
    from mylar.torrent.clients import rtorrent
    cfg = mylar.CONFIG
    conn = rtorrent.TorrentClient().connect(cfg.RTORRENT_HOST, cfg.RTORRENT_USERNAME, cfg.RTORRENT_PASSWORD,
                                            cfg.RTORRENT_AUTHENTICATION, cfg.RTORRENT_VERIFY, cfg.RTORRENT_RPC_URL,
                                            cfg.RTORRENT_CA_BUNDLE)
    if isinstance(conn, dict):
        raise Exception(conn.get('error'))
    rows = []
    for t in conn.get_torrents():
        total = _rt(t, 'size_bytes') or 0
        done = _rt(t, 'completed_bytes') or 0
        speed = _rt(t, 'down_rate') or 0
        rows.append({'hash': t.info_hash, 'name': _rt(t, 'name'), 'label': _rt(t, 'custom1'),
                     'progress': done / float(total) if total else 0, 'total': total, 'speed': speed,
                     'eta': int((total - done) / speed) if speed else None,
                     'path': _rt(t, 'base_path') or None, 'paused': not _rt(t, 'active'),
                     'checking': bool(_rt(t, 'hashing')), 'seeding': bool(_rt(t, 'complete'))})
    return torrent_items('rtorrent', rows, label)


def _fetch_utorrent(label):
    from mylar.torrent.clients import utorrent
    conn = utorrent.TorrentClient().connect(mylar.CONFIG.UTORRENT_HOST, mylar.CONFIG.UTORRENT_USERNAME,
                                            mylar.CONFIG.UTORRENT_PASSWORD)
    if not conn:
        raise Exception('could not connect')
    rows = []
    for t in conn.list()[1].get('torrents', []):
        bits = int(t[1] or 0)
        rows.append({'hash': t[0], 'name': t[2], 'label': t[11], 'progress': (t[4] or 0) / 1000.0, 'total': t[3],
                     'speed': t[9], 'eta': t[10], 'path': t[26] if len(t) > 26 else None,
                     'paused': bool(bits & 32), 'queued': not bits & 1, 'checking': bool(bits & 2),
                     'error': 'uTorrent reported an error' if bits & 16 else None})
    return torrent_items('utorrent', rows, label)


class _Timeout(xmlrpc.client.Transport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = 10
        return conn


class _SafeTimeout(xmlrpc.client.SafeTransport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = 10
        return conn


def _fetch_sab(category):
    base = mylar.CONFIG.SAB_HOST.rstrip('/') + '/api'
    params = {'apikey': mylar.CONFIG.SAB_APIKEY, 'output': 'json', 'category': category}
    q = requests.get(base, params=dict(params, mode='queue', limit=500), timeout=10, verify=False).json()
    h = requests.get(base, params=dict(params, mode='history', limit=200), timeout=10, verify=False).json()
    return sab_items(q, h, category)


def _fetch_nzbget(category):
    from mylar import nzbget
    url = nzbget.NZBGet().nzb_url
    server = xmlrpc.client.ServerProxy(url, transport=_SafeTimeout() if url.startswith('https') else _Timeout())
    return nzbget_items(server.listgroups(), server.history(False), category)


def _fetch_qbit(category):
    from mylar.torrent.clients import qbittorrent
    client = qbittorrent.TorrentClient().connect(mylar.CONFIG.QBITTORRENT_HOST, mylar.CONFIG.QBITTORRENT_USERNAME,
                                                 mylar.CONFIG.QBITTORRENT_PASSWORD)
    if isinstance(client, dict):
        raise Exception(client.get('error'))
    return qbit_items(client.torrents(category=category), category)


FETCHERS = {'sabnzbd': _fetch_sab, 'nzbget': _fetch_nzbget, 'qbittorrent': _fetch_qbit, 'deluge': _fetch_deluge,
            'transmission': _fetch_transmission, 'rtorrent': _fetch_rtorrent, 'utorrent': _fetch_utorrent}


# ---- finding the files -------------------------------------------------------

def _parts(path):
    p = str(path).replace('\\', '/')
    return [x for x in p.split('/') if x and not x.endswith(':')]


def local_path(client, path):
    """Where Issuarr sees a client's download. The client's own path when Issuarr can reach it,
    otherwise its last folder names under a folder Issuarr knows: the client's download folder
    setting, the monitored folder, or the direct download folder."""
    if not _set(path):
        return None
    if os.path.exists(path):
        return path
    cfg = mylar.CONFIG
    roots = []
    if client == 'sabnzbd':
        roots.append(getattr(cfg, 'SAB_DIRECTORY', None))
    elif client == 'nzbget':
        roots.append(getattr(cfg, 'NZBGET_DIRECTORY', None))
    elif client == 'qbittorrent':
        roots.append(getattr(cfg, 'QBITTORRENT_FOLDER', None))
    elif client == 'deluge':
        roots += [getattr(cfg, 'DELUGE_DONE_DIRECTORY', None), getattr(cfg, 'DELUGE_DOWNLOAD_DIRECTORY', None)]
    elif client == 'transmission':
        roots.append(getattr(cfg, 'TRANSMISSION_DIRECTORY', None))
    elif client == 'rtorrent':
        roots.append(getattr(cfg, 'RTORRENT_DIRECTORY', None))
    roots += [getattr(cfg, 'CHECK_FOLDER', None), getattr(cfg, 'DDL_LOCATION', None)]
    parts = _parts(path)
    for root in [r for r in roots if _set(r) and os.path.isdir(r)]:
        for k in range(min(4, len(parts)), 0, -1):
            cand = os.path.join(root, *parts[-k:])
            if os.path.exists(cand):
                return cand
    return None


def comic_files(path):
    if os.path.isfile(path):
        return [path] if path.lower().endswith(COMIC_FILES) else []
    out = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(('_UNPACK_', '_FAILED_', '.'))]
        out += [os.path.join(root, f) for f in files if f.lower().endswith(COMIC_FILES)]
    return sorted(out)


# ---- which issue a file is ----------------------------------------------------

def identify(name):
    """The watchlist issue a file or download name is, when its series and issue number agree and
    neither its year nor its format says otherwise. None when nothing is that sure."""
    from mylar import attention
    now = time.time()
    hit = MATCHES.get(name)
    if hit and now - hit[0] < MATCH_TTL:
        return hit[1]
    found = None
    try:
        best = attention.suggest(attention.parse(name), limit=1)
    except Exception as e:
        logger.fdebug('[CLIENT-WATCH] Could not match %s to the watchlist: %s' % (name, e))
        best = []
    if best:
        b = best[0]
        a = b['agree']
        if a.get('series') and a.get('issue') and b.get('issueid') and a.get('year') is not False and a.get('format') is not False:
            found = {'comicid': b['comicid'], 'issueid': b['issueid'], 'series': b['name'], 'year': b['year'],
                     'number': b['number'], 'owned': bool(b.get('owned'))}
    if len(MATCHES) > 5000:
        MATCHES.clear()
    MATCHES[name] = (now, found)
    return found


def label(match):
    return '%s%s #%s' % (match['series'], ' (%s)' % match['year'] if match.get('year') else '', match['number'])


def _issue(myDB, comicid, issueid):
    row = myDB.selectone('SELECT i.IssueID, i.Issue_Number, i.ComicID, i.Status, c.ComicName, c.ComicYear FROM issues i '
                         'JOIN comics c ON c.ComicID=i.ComicID WHERE i.IssueID=? AND i.ComicID=?', [issueid, comicid]).fetchone()
    return dict(row) if row is not None else None


def file_as(path, issue):
    """File one comic file as one issue, the way a Needs attention pick is filed. True when the
    issue ends up Downloaded or Archived. The source file is left to the filing setting (move or copy)."""
    from mylar import PostProcessor, attention
    pp = PostProcessor.PostProcessor('Manual Run', os.path.dirname(path), queue=queue.Queue())
    with PostProcessor.PP_LOCK:
        pp.nzb_or_oneoff_pp(manual=[attention.entry_for(path, issue)])
    row = db.DBConnection().selectone('SELECT Status FROM issues WHERE IssueID=?', [issue['IssueID']]).fetchone()
    return row is not None and row['Status'] in ('Downloaded', 'Archived')


def cover_ok(path, issue):
    """The cover check filing does for the monitored folder and client downloads (Settings >
    Post-processing). A file that fails it is listed in Needs attention."""
    from mylar import PostProcessor, attention
    pp = PostProcessor.PostProcessor('Manual Run', os.path.dirname(path), queue=queue.Queue())
    return pp._cover_ok(dict(attention.entry_for(path, issue), ForcedMatch=False))


def _auto_add(files):
    """Hand unmatched files to auto-add (Settings > Post-processing). True while that's under way."""
    from mylar import autoadd
    if not autoadd.enabled():
        return False
    fresh = [f for f in files if not autoadd.attempted(f)]
    if not fresh:
        return False
    autoadd.queue(fresh, refile=False)
    return True


# ---- remembering what was filed ---------------------------------------------

def _ensure(myDB):
    myDB.action('CREATE TABLE IF NOT EXISTS client_watch (Client TEXT, JobID TEXT, Name TEXT, Handled TEXT, Note TEXT, '
                'PRIMARY KEY (Client, JobID))')


def handled(myDB):
    try:
        _ensure(myDB)
        return {(r['Client'], r['JobID']) for r in myDB.select('SELECT Client, JobID FROM client_watch')}
    except Exception as e:
        logger.fdebug('[CLIENT-WATCH] Could not read which downloads were filed: %s' % e)
        return set()


def _done(myDB, item, note):
    try:
        _ensure(myDB)
        myDB.upsert('client_watch', {'Name': item['name'], 'Handled': helpers.now(), 'Note': note},
                    {'Client': item['client'], 'JobID': item['id'].lower()})
    except Exception as e:
        logger.warn('[CLIENT-WATCH] Could not remember that %s was dealt with: %s' % (item['name'], e))


def own_jobs(myDB):
    """{(client, job id): {'issueid', 'comicid'}} for grabs Issuarr sent itself."""
    out = {}
    try:
        for r in myDB.select('SELECT IssueID, ComicID, Client, JobID FROM client_jobs'):
            if r['Client'] in CLIENT_NAMES and r['JobID']:
                out[(r['Client'], str(r['JobID']).lower())] = {'issueid': r['IssueID'], 'comicid': r['ComicID']}
    except Exception:
        pass
    return out


# ---- the check ---------------------------------------------------------------

def _ours_to_file(client):
    """Whether Issuarr's own grabs at this client are filed here. SABnzbd and NZBGet have completed
    download handling, and rTorrent and Deluge grabs are fetched by Auto-snatch or local torrent
    post-processing when either is on."""
    if client not in TORRENT_CLIENTS:
        return False
    if client in ('rtorrent', 'deluge'):
        cfg = mylar.CONFIG
        return not (getattr(cfg, 'AUTO_SNATCH', False) or getattr(cfg, 'LOCAL_TORRENT_PP', False))
    return True


def _note(key, state, note=None):
    NOTES[key] = {'state': state, 'note': note}


def _settled(key, now):
    first = FINISHED_AT.setdefault(key, now)
    return now - first >= SETTLE


def _file_finished(myDB, item, own):
    """File a finished download. Returns the note to keep once it's dealt with, or None to look again next time."""
    key = (item['client'], item['id'].lower())
    where = local_path(item['client'], item['path'])
    if not where:
        m = identify(item['name'] or '')
        if m and m['owned']:
            return 'Already in your library.'
        if key not in WARNED:
            WARNED.add(key)
            MISSING.append('%s (%s)' % (item['name'], item['path']))
        _note(key, 'Not filed', 'Finished, but Issuarr can\'t find its files at %s.' % (item['path'] or 'the path the client gave'))
        return None
    files = comic_files(where)
    if not files:
        _note(key, 'Needs a choice', 'Finished, but it holds no comic files Issuarr can file (.cbz, .cbr, .cb7, .cbt or .pdf).')
        return None

    if own:
        issue = _issue(myDB, own['comicid'], own['issueid']) if own.get('issueid') and own.get('comicid') else None
        if issue is None:
            return 'Grabbed for an issue that is no longer on the watchlist.'
        if issue['Status'] != 'Snatched':
            return 'Already filed.'
        if len(files) == 1:
            if not cover_ok(files[0], issue):
                return 'Its cover doesn\'t match %s #%s. It\'s in Needs attention.' % (issue['ComicName'], issue['Issue_Number'])
            _note(key, 'Filing', 'Filing as %s #%s' % (issue['ComicName'], issue['Issue_Number']))
            ok = file_as(files[0], issue)
            logger.info('[CLIENT-WATCH] %s finished %s: %s %s #%s.' % (
                CLIENT_NAMES[item['client']], item['name'], 'filed it as' if ok else 'filing didn\'t finish for', issue['ComicName'], issue['Issue_Number']))
            return 'Filed.' if ok else 'Filing didn\'t finish. The log has the details.'

    picks, owned, unknown = [], 0, []
    for f in files:
        m = identify(os.path.basename(f))
        if m is None:
            unknown.append(f)
        elif m['owned']:
            owned += 1
        else:
            picks.append((f, m))
    if unknown and _auto_add(unknown):
        _note(key, 'Waiting to file', 'Auto-add is looking up the series of %s on ComicVine.' % ('it' if len(files) == 1 else '%s of its files' % len(unknown)))
        return None
    if not picks:
        if owned and not unknown:
            return 'Already in your library.'
        _note(key, 'Needs a choice', 'No issue on your watchlist matches %s.' % ('this name' if len(files) == 1 else 'these files'))
        return None
    filed, covers = 0, 0
    for f, m in picks:
        issue = _issue(myDB, m['comicid'], m['issueid'])
        if issue is None:
            continue
        if not cover_ok(f, issue):
            covers += 1
            continue
        _note(key, 'Filing', 'Filing as %s' % label(m))
        try:
            filed += 1 if file_as(f, issue) else 0
        except Exception as e:
            logger.warn('[CLIENT-WATCH] Filing %s as %s failed: %s' % (f, label(m), e))
    left = len(files) - filed
    logger.info('[CLIENT-WATCH] %s finished %s: filed %s of %s comic files.%s' % (
        CLIENT_NAMES[item['client']], item['name'], filed, len(files),
        ' The rest matched nothing on the watchlist or were already in the library.' if left else ''))
    cover = ' %s didn\'t match by cover and %s in Needs attention.' % (covers, 'is' if covers == 1 else 'are') if covers else ''
    if len(files) == 1 and covers:
        return 'Its cover doesn\'t match the issue it\'s named as. It\'s in Needs attention.'
    return ('Filed %s of %s files.' % (filed, len(files)) if left else 'Filed.') + cover


def check(force=False):
    """Ask each watched client what it holds, and file what finished. Returns the summary."""
    if not enabled():
        return summary()
    now = time.time()
    if not force and now - RUN['last'] < interval() * 60 - 20:
        return summary()
    with _LOCK:
        if RUN['busy']:
            return summary()
        RUN['busy'] = True
    try:
        RUN['last'] = now
        myDB = db.DBConnection()
        mine = own_jobs(myDB)
        done = handled(myDB)
        for client, category in watched():
            try:
                items = FETCHERS[client](category)
                LAST[client] = {'at': time.time(), 'error': None, 'items': items}
            except Exception as e:
                LAST[client] = {'at': time.time(), 'error': str(e) or e.__class__.__name__,
                                'items': (LAST.get(client) or {}).get('items', [])}
                logger.fdebug('[CLIENT-WATCH] Could not read %s: %s' % (CLIENT_NAMES[client], e))
                continue
            for item in items:
                key = (client, item['id'].lower())
                own = mine.get(key)
                item['own'] = own is not None
                if key in done or (own and not _ours_to_file(client)):
                    continue
                if item['state'] != 'Finished':
                    FINISHED_AT.pop(key, None)
                    if not own and item['state'] not in ('Failed',):
                        m = identify(item['name'] or '')
                        _note(key, item['state'], 'Matches %s' % label(m) if m else None)
                    continue
                if not _settled(key, time.time()):
                    _note(key, 'Waiting to file', 'Finished. Matched against your watchlist on the next check.')
                    continue
                try:
                    note = _file_finished(myDB, item, own)
                except Exception as e:
                    logger.warn('[CLIENT-WATCH] Could not file %s: %s' % (item['name'], e))
                    note = None
                    _note(key, 'Not filed', 'Filing failed: %s' % e)
                if note is not None:
                    _done(myDB, item, note)
                    done.add(key)
                    NOTES.pop(key, None)
        if MISSING:
            logger.warn('[CLIENT-WATCH] %s finished %s in Issuarr\'s category can\'t be found from Issuarr: %s. Map the client\'s download folder into '
                        'Issuarr at the same path, or for SABnzbd and NZBGet set the download folder as Issuarr sees it in '
                        'Settings > Download clients.' % (len(MISSING), 'download' if len(MISSING) == 1 else 'downloads',
                                                                     '; '.join(MISSING[:5]) + (' and more' if len(MISSING) > 5 else '')))
            del MISSING[:]
        for client in list(LAST):
            if client not in dict(watched()):
                LAST.pop(client, None)
    finally:
        RUN['busy'] = False
    return summary()


def tick():
    try:
        check()
    except Exception as e:
        logger.warn('[CLIENT-WATCH] Checking the download clients failed: %s' % e)


def summary():
    """[{'name', 'at', 'error'}] per watched client, for the Downloads page."""
    if not enabled():
        return []
    return [{'name': CLIENT_NAMES[c], 'at': (LAST.get(c) or {}).get('at'), 'error': (LAST.get(c) or {}).get('error')}
            for c, _ in watched()]


def next_run():
    if not enabled():
        return None
    return (RUN['last'] or time.time()) + interval() * 60


# ---- the queue's rows ----------------------------------------------------------

def queue_rows(myDB):
    """Downloads you added yourself, for the Downloads queue. Issuarr's own grabs are already listed."""
    if not enabled() or not LAST:
        return []
    from mylar import downloadqueue as dq
    done = handled(myDB)
    rows = []
    for client, info in list(LAST.items()):
        for item in info.get('items') or []:
            key = (client, item['id'].lower())
            if item.get('own') or key in done:
                continue
            n = NOTES.get(key) or {}
            state = n.get('state') or item['state']
            if state == 'Finished':
                state = 'Waiting to file'
            rows.append({'key': 'watch-%s-%s' % (client, item['id']), 'kind': 'watch', 'queueid': None,
                         'title': item['name'] or item['id'], 'comicid': None, 'issueid': None,
                         'source': CLIENT_NAMES[client], 'via': 'Added by you', 'status': state,
                         'percent': item['percent'],
                         'size': dq._human(item['total']) if item.get('total') else None,
                         'speed': '%s/s' % dq._human(item['speed']) if item.get('speed') else None,
                         'eta': dq._eta(item['eta']) if item.get('eta') is not None else None,
                         'progress': '%s of %s' % (dq._human(item['done'] or 0), dq._human(item['total']))
                                     if item.get('total') and item['state'] in ('Downloading', 'Paused') else None,
                         'message': n.get('note') or item.get('message'), 'detail': None,
                         'updated': helpers.now() if not info.get('at') else
                         time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(info['at']))})
    return rows
