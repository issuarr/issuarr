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
import re
import shutil
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
STUCK = set()         # (client, id) whose filing didn't finish: not tried again until a match is chosen
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

def _item(client, jobid, name, state, done=None, total=None, speed=None, eta=None, path=None, message=None, stopped=False):
    pct = None
    if total:
        pct = max(0, min(100, int(round(float(done or 0) * 100 / float(total)))))
    return {'client': client, 'id': str(jobid), 'name': name, 'state': state, 'percent': pct, 'done': done,
            'total': total, 'speed': speed, 'eta': eta, 'path': path or None, 'message': message,
            'stopped': bool(stopped) and state == 'Finished'}


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
                         'qBittorrent can\'t find its files' if st == 'missingFiles' else None,
                         stopped=st.startswith('paused') or st.startswith('stopped')))
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
                         t.get('error') if isinstance(t.get('error'), str) else None, stopped=t.get('stopped')))
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
                     'seeding': st == 'Seeding', 'stopped': st == 'Paused',
                     'error': (t.get('message') or 'Deluge reported an error') if st == 'Error' else None})
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
                     'seeding': st in ('seeding', 'seed pending'), 'stopped': st == 'stopped', 'error': err or None})
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
                     'checking': bool(_rt(t, 'hashing')), 'seeding': bool(_rt(t, 'complete')), 'stopped': not _rt(t, 'active')})
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
                     'stopped': bool(bits & 32) or not bits & 1,
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
                'Complete INTEGER, Cleared TEXT, PRIMARY KEY (Client, JobID))')
    have = {r['name'] for r in myDB.select('PRAGMA table_info(client_watch)')}
    for col, kind in (('Complete', 'INTEGER'), ('Cleared', 'TEXT')):
        if col not in have:
            myDB.action('ALTER TABLE client_watch ADD COLUMN %s %s' % (col, kind))
    myDB.action('CREATE TABLE IF NOT EXISTS client_watch_choice (Client TEXT, JobID TEXT, ComicID TEXT, ComicName TEXT, '
                'Chosen TEXT, PRIMARY KEY (Client, JobID))')


# ---- Choose match: the series a download you added belongs to ------------------

def choices(myDB):
    """{(client, job id): {'comicid', 'name'}} for downloads given a series with Choose match."""
    try:
        _ensure(myDB)
        return {(r['Client'], r['JobID']): {'comicid': r['ComicID'], 'name': r['ComicName']}
                for r in myDB.select('SELECT Client, JobID, ComicID, ComicName FROM client_watch_choice')}
    except Exception as e:
        logger.fdebug('[CLIENT-WATCH] Could not read the chosen matches: %s' % e)
        return {}


def find_item(client, jobid):
    for item in (LAST.get(client) or {}).get('items') or []:
        if item['id'].lower() == str(jobid).lower():
            return item
    return None


def _ready(myDB, comicid):
    row = myDB.selectone('SELECT Status, (SELECT COUNT(*) FROM issues WHERE ComicID=?) AS n FROM comics WHERE ComicID=?',
                         [comicid, comicid]).fetchone()
    return row is not None and row['Status'] != 'Loading' and row['n'] > 0


def chosen_issue(myDB, comicid, name):
    """The issue of the chosen series that a file or download name's number says, or None."""
    from mylar import attention
    try:
        found = attention.suggest(attention.parse(name), limit=10, comicid=comicid)
    except Exception as e:
        logger.fdebug('[CLIENT-WATCH] Could not read the issue number of %s: %s' % (name, e))
        return None
    mine = [b for b in found if str(b.get('comicid')) == str(comicid) and b['agree'].get('issue') and b.get('issueid')]
    return _issue(myDB, comicid, mine[0]['issueid']) if mine else None


def _hold_issue(myDB, issue):
    # a chosen download is on its way, so search doesn't grab the issue again
    if issue and issue['Status'] == 'Wanted':
        myDB.upsert('issues', {'Status': 'Snatched'}, {'IssueID': issue['IssueID']})
        logger.info('[CLIENT-WATCH] Marked %s #%s Snatched: a download you chose it for is on its way.' % (issue['ComicName'], issue['Issue_Number']))


def choose(client, jobid, comicid, name=None, year=None):
    """Choose match: file this download you added as issues of a series, adding the series to the
    watchlist first when it isn't there."""
    from mylar import attention
    item = find_item(client, jobid)
    if item is None:
        return {'ok': False, 'note': 'That download isn\'t in the client\'s list any more. Refresh and try again.'}
    myDB = db.DBConnection()
    if (client, item['id'].lower()) in own_jobs(myDB):
        return {'ok': False, 'note': 'Issuarr grabbed this one itself, so it already knows which issue it is.'}
    if (client, item['id'].lower()) in handled(myDB):
        return {'ok': False, 'note': 'That download was already dealt with. Refresh to see the queue now.'}
    comicid = re.sub(r'^4050-', '', str(comicid or '')).strip()
    if not comicid.isdigit():
        return {'ok': False, 'note': 'That isn\'t a ComicVine series.'}
    added = attention.add_series(comicid, name, year)
    if not added.get('ok'):
        return added
    row = myDB.selectone('SELECT ComicName, ComicYear FROM comics WHERE ComicID=?', [comicid]).fetchone()
    label_ = name or (row['ComicName'] if row else comicid)
    if row is not None and row['ComicYear'] and not name:
        label_ = '%s (%s)' % (row['ComicName'], row['ComicYear'])
    elif year and name:
        label_ = '%s (%s)' % (name, year)
    _ensure(myDB)
    key = (client, item['id'].lower())
    myDB.upsert('client_watch_choice', {'ComicID': comicid, 'ComicName': label_, 'Chosen': helpers.now()},
                {'Client': client, 'JobID': key[1]})
    MATCHES.clear()
    issue = chosen_issue(myDB, comicid, item['name'] or '') if _ready(myDB, comicid) else None
    _hold_issue(myDB, issue)
    _note(key, 'Waiting to file' if item['state'] == 'Finished' else item['state'],
          'Chosen: %s' % (('%s #%s' % (issue['ComicName'], issue['Issue_Number'])) if issue else label_))
    logger.info('[CLIENT-WATCH] %s will be filed as %s.' % (item['name'], label_))
    STUCK.discard(key)
    FINISHED_AT.pop(key, None)
    RUN['last'] = 0.0   # the next tick files it
    if added.get('state') == 'adding':
        return {'ok': True, 'note': 'Adding %s to your watchlist. %s is filed as its issues once they load.' % (label_, item['name'])}
    return {'ok': True, 'note': '%s will be filed as %s.' % (item['name'], ('%s #%s' % (issue['ComicName'], issue['Issue_Number'])) if issue else label_)}


def choice_info(client, jobid):
    """What the Choose match window shows: the download, its files and the watchlist series its name is closest to."""
    from mylar import attention
    item = find_item(client, jobid)
    if item is None:
        return {'ok': False, 'note': 'That download isn\'t in the client\'s list any more. Refresh and try again.'}
    myDB = db.DBConnection()
    where = local_path(client, item['path']) if item.get('path') else None
    files = [os.path.basename(f) for f in comic_files(where)] if where else []
    parsed = attention.parse(item['name'] or '')
    try:
        near = attention.suggest(parsed, limit=5)
    except Exception:
        near = []
    seen, cands = set(), []
    for b in near:
        if b['comicid'] in seen:
            continue
        seen.add(b['comicid'])
        cands.append({'comicid': b['comicid'], 'name': b['name'], 'year': b['year'], 'watched': True,
                      'issue': b.get('number') if b.get('issueid') else None})
    pick = choices(myDB).get((client, item['id'].lower()))
    return {'ok': True, 'download': {'client': client, 'id': item['id'], 'name': item['name'], 'source': CLIENT_NAMES[client],
                                     'state': item['state'], 'files': files[:200], 'more': max(0, len(files) - 200),
                                     'series': parsed.get('series'), 'issue': parsed.get('issue'), 'year': parsed.get('year')},
            'candidates': cands, 'chosen': pick}


def handled(myDB):
    try:
        _ensure(myDB)
        return {(r['Client'], r['JobID']) for r in myDB.select('SELECT Client, JobID FROM client_watch')}
    except Exception as e:
        logger.fdebug('[CLIENT-WATCH] Could not read which downloads were filed: %s' % e)
        return set()


def _complete(note):
    """Every comic in the download is in the library, so the client may let go of it."""
    return note in ('Filed.', 'Already in your library.', 'Already filed.', 'Filed by completed download handling.') or \
        (note.startswith('Filed as ') and 'No issue matched' not in note)


def _done(myDB, item, note):
    try:
        _ensure(myDB)
        myDB.upsert('client_watch', {'Name': item['name'], 'Handled': helpers.now(), 'Note': note, 'Complete': 1 if _complete(note) else 0},
                    {'Client': item['client'], 'JobID': item['id'].lower()})
    except Exception as e:
        logger.warn('[CLIENT-WATCH] Could not remember that %s was dealt with: %s' % (item['name'], e))


def uncleared(myDB):
    """Downloads filed in full that are still to be removed from their client or relabelled."""
    try:
        _ensure(myDB)
        return {(r['Client'], r['JobID']) for r in myDB.select('SELECT Client, JobID FROM client_watch WHERE Complete=1 AND Cleared IS NULL')}
    except Exception as e:
        logger.fdebug('[CLIENT-WATCH] Could not read which downloads to clear: %s' % e)
        return set()


# ---- after import: remove from the client, or give it the post-import label ---------

def _remove_wanted(client):
    cfg = mylar.CONFIG
    if client == 'sabnzbd':
        return bool(getattr(cfg, 'SAB_REMOVE_COMPLETED', False))
    if client == 'nzbget':
        return bool(getattr(cfg, 'NZBGET_REMOVE_COMPLETED', False))
    return bool(getattr(cfg, 'TORRENT_REMOVE_COMPLETED', False))


def post_import_label(client):
    """The label a filed torrent moves to (Settings > Torrents). Transmission has no labels."""
    if client not in TORRENT_CLIENTS or client == 'transmission':
        return None
    v = getattr(mylar.CONFIG, 'TORRENT_POST_IMPORT_LABEL', None)
    return v.strip() if _set(v) and v.strip() else None


def _keep_data():
    # soft links in the library point at the download, so its files have to stay
    return (getattr(mylar.CONFIG, 'FILE_OPTS', None) or 'move') == 'softlink'


def _protected():
    cfg = mylar.CONFIG
    names = ('SAB_DIRECTORY', 'NZBGET_DIRECTORY', 'QBITTORRENT_FOLDER', 'DELUGE_DONE_DIRECTORY', 'DELUGE_DOWNLOAD_DIRECTORY',
             'TRANSMISSION_DIRECTORY', 'RTORRENT_DIRECTORY', 'CHECK_FOLDER', 'DDL_LOCATION', 'COMIC_DIR', 'DESTINATION_DIR')
    return [os.path.normpath(getattr(cfg, n)) for n in names if _set(getattr(cfg, n, None))]


def _delete_local(client, path):
    """Delete a finished download's own file or folder, never a download or library folder itself."""
    where = local_path(client, path)
    if not where:
        return False
    where = os.path.normpath(where)
    for root in _protected():
        if where == root or root.startswith(where + os.sep):
            logger.warn('[CLIENT-WATCH] Not deleting %s: it is (or holds) a folder Issuarr uses.' % where)
            return False
    if os.path.isdir(where):
        shutil.rmtree(where)
    elif os.path.isfile(where):
        os.remove(where)
    return True


def _qbit():
    from mylar.torrent.clients import qbittorrent
    client = qbittorrent.TorrentClient().connect(mylar.CONFIG.QBITTORRENT_HOST, mylar.CONFIG.QBITTORRENT_USERNAME,
                                                 mylar.CONFIG.QBITTORRENT_PASSWORD)
    if isinstance(client, dict):
        raise Exception(client.get('error'))
    return client


def _deluge():
    from mylar.torrent.clients import deluge
    client = deluge.TorrentClient().connect(mylar.CONFIG.DELUGE_HOST, mylar.CONFIG.DELUGE_USERNAME, mylar.CONFIG.DELUGE_PASSWORD)
    if isinstance(client, dict):
        raise Exception(client.get('error'))
    return client


def _rtorrent_find(h):
    from mylar.torrent.clients import rtorrent
    cfg = mylar.CONFIG
    conn = rtorrent.TorrentClient().connect(cfg.RTORRENT_HOST, cfg.RTORRENT_USERNAME, cfg.RTORRENT_PASSWORD,
                                            cfg.RTORRENT_AUTHENTICATION, cfg.RTORRENT_VERIFY, cfg.RTORRENT_RPC_URL,
                                            cfg.RTORRENT_CA_BUNDLE)
    if isinstance(conn, dict):
        raise Exception(conn.get('error'))
    for t in conn.get_torrents():
        if str(t.info_hash).lower() == h:
            return t
    raise Exception('rTorrent no longer has it')


def _utorrent():
    from mylar.torrent.clients import utorrent
    conn = utorrent.TorrentClient().connect(mylar.CONFIG.UTORRENT_HOST, mylar.CONFIG.UTORRENT_USERNAME, mylar.CONFIG.UTORRENT_PASSWORD)
    if not conn:
        raise Exception('could not connect')
    return conn


def _relabel(client, item, label_):
    h = item['id'].lower()
    if client == 'qbittorrent':
        c = _qbit()
        try:
            c._post('api/v2/torrents/createCategory', data={'category': label_})
        except Exception:
            pass   # it's there already
        c.set_category([h], label_)
    elif client == 'deluge':
        c = _deluge()
        try:
            c.call('label.add', label_.lower())
        except Exception:
            pass
        c.call('label.set_torrent', h, label_.lower())
    elif client == 'rtorrent':
        _rtorrent_find(h).set_custom(1, label_)
    elif client == 'utorrent':
        _utorrent()._action([('action', 'setprops'), ('hash', item['id']), ('s', 'label'), ('v', label_)])


def _remove(client, item, keep):
    h = item['id'].lower()
    if client == 'qbittorrent':
        c = _qbit()
        (c.delete if keep else c.delete_permanently)([h])
    elif client == 'deluge':
        _deluge().call('core.remove_torrent', h, not keep)
    elif client == 'transmission':
        from mylar.torrent.clients import transmission
        conn = transmission.TorrentClient().connect(mylar.CONFIG.TRANSMISSION_HOST, mylar.CONFIG.TRANSMISSION_USERNAME,
                                                    mylar.CONFIG.TRANSMISSION_PASSWORD)
        conn.remove_torrent(h, delete_data=not keep)
    elif client == 'utorrent':
        c = _utorrent()
        (c.remove if keep else c.removedata)(item['id'])
    elif client == 'rtorrent':
        _rtorrent_find(h).erase()
        if not keep:
            _delete_local(client, item['path'])
    elif client == 'sabnzbd':
        params = {'mode': 'history', 'name': 'delete', 'value': item['id'], 'output': 'json', 'apikey': mylar.CONFIG.SAB_APIKEY}
        if not keep:
            params['del_files'] = 1
        base = mylar.CONFIG.SAB_HOST.rstrip('/') + '/api'
        r = requests.get(base, params=params, timeout=10, verify=False).json()
        if r.get('status') is not True:
            raise Exception('SABnzbd said no')
    elif client == 'nzbget':
        from mylar import nzbget
        url = nzbget.NZBGet().nzb_url
        server = xmlrpc.client.ServerProxy(url, transport=_SafeTimeout() if url.startswith('https') else _Timeout())
        if not server.editqueue('HistoryDelete', '', [int(item['id'])]):
            raise Exception('NZBGet said no')
        if not keep:
            _delete_local(client, item['path'])


def _filed_by_cdh(myDB, own):
    # an NZBGet grab Issuarr sent is filed by completed download handling; once its issue is in the library it's done
    if not own.get('issueid'):
        return False
    row = myDB.selectone('SELECT Status FROM issues WHERE IssueID=?', [own['issueid']]).fetchone()
    return row is not None and row['Status'] in ('Downloaded', 'Archived')


def after_import(myDB, item):
    """Once a download is filed in full: give a torrent the post-import label, or remove the download
    from its client when that's on. A torrent is only removed once the client has stopped it, which it
    does when it reaches its seeding goal. Returns what was done, or None to look again next check."""
    client = item['client']
    label_ = post_import_label(client)
    try:
        if label_:
            _relabel(client, item, label_)
            done = 'Moved to the %s label.' % label_
        elif not _remove_wanted(client):
            done = 'Left in the client.'
        elif client in TORRENT_CLIENTS and not item.get('stopped'):
            return None   # still seeding
        else:
            keep = _keep_data()
            _remove(client, item, keep)
            done = 'Removed from %s%s.' % (CLIENT_NAMES[client], '' if keep else ' with its files')
    except Exception as e:
        logger.warn('[CLIENT-WATCH] Could not clear %s from %s: %s' % (item['name'], CLIENT_NAMES[client], e))
        return None
    myDB.upsert('client_watch', {'Cleared': done}, {'Client': client, 'JobID': item['id'].lower()})
    if done != 'Left in the client.':
        logger.info('[CLIENT-WATCH] %s: %s' % (item['name'], done))
    return done


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


def _file_chosen(myDB, item, pick, files):
    """File a finished download as issues of the series chosen for it."""
    key = (item['client'], item['id'].lower())
    if not _ready(myDB, pick['comicid']):
        _note(key, 'Waiting to file', 'Chosen: %s. Waiting for its issues to load from ComicVine.' % pick['name'])
        return None
    whole = chosen_issue(myDB, pick['comicid'], item['name'] or '') if len(files) == 1 else None
    filed, missed, had = 0, [], 0
    for f in files:
        issue = whole or chosen_issue(myDB, pick['comicid'], os.path.basename(f))
        if issue is None:
            missed.append(os.path.basename(f))
            continue
        if issue['Status'] in ('Downloaded', 'Archived'):
            had += 1
            continue
        _note(key, 'Filing', 'Filing as %s #%s' % (issue['ComicName'], issue['Issue_Number']))
        try:
            filed += 1 if file_as(f, issue) else 0
        except Exception as e:
            logger.warn('[CLIENT-WATCH] Filing %s as %s #%s failed: %s' % (f, issue['ComicName'], issue['Issue_Number'], e))
    logger.info('[CLIENT-WATCH] %s finished %s (chosen as %s): filed %s of %s comic files.' % (
        CLIENT_NAMES[item['client']], item['name'], pick['name'], filed, len(files)))
    if not filed and not had:
        if len(missed) < len(files):
            STUCK.add(key)
            _note(key, 'Not filed', 'Filing as %s didn\'t finish. The log has the details. Choose match tries again.' % pick['name'])
            return None
        _note(key, 'Needs a choice', 'No issue of %s matches the number in %s. Choose another series.' % (
            pick['name'], 'its name' if len(files) == 1 else 'its file names'))
        return None
    if missed:
        return 'Filed %s of %s files as %s. No issue matched: %s.' % (filed, len(files), pick['name'], ', '.join(missed[:5]) + (' and more' if len(missed) > 5 else ''))
    return 'Filed as %s.' % pick['name'] if filed else 'Already in your library.'


def _file_finished(myDB, item, own, pick=None):
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
    if pick and not own:
        return _file_chosen(myDB, item, pick, files)

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
    if not filed and not covers:
        STUCK.add(key)
        _note(key, 'Not filed', 'Filing didn\'t finish. The log has the details. Choose match tries again.')
        return None
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
        picked = choices(myDB)
        clear = uncleared(myDB)
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
                if key in clear:
                    if after_import(myDB, item):
                        clear.discard(key)
                    continue
                if own and client == 'nzbget' and key not in done and item['state'] == 'Finished' and _filed_by_cdh(myDB, own):
                    _done(myDB, item, 'Filed by completed download handling.')
                    done.add(key)
                    clear.add(key)
                    continue
                if key in done or key in STUCK or (own and not _ours_to_file(client)):
                    continue
                pick = None if own else picked.get(key)
                if item['state'] != 'Finished':
                    FINISHED_AT.pop(key, None)
                    if pick and item['state'] not in ('Failed',):
                        issue = chosen_issue(myDB, pick['comicid'], item['name'] or '') if _ready(myDB, pick['comicid']) else None
                        _hold_issue(myDB, issue)
                        _note(key, item['state'], 'Chosen: %s' % (('%s #%s' % (issue['ComicName'], issue['Issue_Number'])) if issue else pick['name']))
                    elif not own and item['state'] not in ('Failed',):
                        m = identify(item['name'] or '')
                        _note(key, item['state'], 'Matches %s' % label(m) if m else None)
                    continue
                if not _settled(key, time.time()):
                    _note(key, 'Waiting to file', 'Finished. Matched against your watchlist on the next check.')
                    continue
                try:
                    note = _file_finished(myDB, item, own, pick)
                except Exception as e:
                    logger.warn('[CLIENT-WATCH] Could not file %s: %s' % (item['name'], e))
                    note = None
                    _note(key, 'Not filed', 'Filing failed: %s' % e)
                if note is not None:
                    _done(myDB, item, note)
                    done.add(key)
                    NOTES.pop(key, None)
                    if _complete(note) and after_import(myDB, item) is None:
                        clear.add(key)
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
                         'client': client, 'jobid': item['id'], 'choose': state not in ('Failed', 'Filing'),
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
