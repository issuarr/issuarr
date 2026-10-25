# -*- coding: utf-8 -*-
# This file is part of Issuarr.
#
# Issuarr is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Issuarr is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Issuarr. If not, see <http://www.gnu.org/licenses/>.

"""
Folder packs for AirDC++.

Hubs rarely answer folder searches, but every file hit says which peer shares it and in
which folder. After an issue downloads from AirDC++, this opens that one folder of the
peer's share (a partial filelist: a direct peer connection, no hub search) and queues the
series' other Wanted issues it finds there, one file per issue, by TTH. Each file then goes
through post-processing like any other AirDC++ download.
"""

import os
import re
import threading
import time

import mylar
from mylar import db, logger, updater
from mylar.downloaders import airdcpp

MIN_BYTES = 1024 * 1024        # smaller than this is a fake or a placeholder
MAX_FILES = 100                # one folder never queues more than this
LIST_WAIT = 60                 # seconds to wait for the peer's folder listing
STALL_LIMIT = 30 * 60          # give up on the rest when nothing moves for this long
POLL = 10

NOT_ISSUES = re.compile(r'\b(tpb|hc|trade|trade paperback|omnibus|annual)\b')


def normalize(text):
    text = (text or '').lower().replace('&', ' and ')
    text = re.sub(r"['’]", '', text)
    text = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', text)   # keep 1.5, drop Mr.
    return ' '.join(re.sub(r'[^a-z0-9.]+', ' ', text).split())


def number_key(number):
    """'001' and '1' and '1.0' are the same issue; None when it isn't a plain issue number."""
    m = re.match(r'^0*(\d+)(?:\.(\d+))?([a-z]?)$', (number or '').strip().lower())
    if m is None:
        return None
    whole, part, letter = m.groups()
    part = (part or '').rstrip('0')
    return whole + ('.' + part if part else '') + letter


def parse_name(filename):
    """(series, number key, year or None) from a plain single-issue file name, or None."""
    stem, ext = os.path.splitext(filename or '')
    if ext.lower() not in ('.cbz', '.cbr'):
        return None
    brackets = ' '.join(re.findall(r'[\(\[]([^\)\]]*)[\)\]]', stem))
    if NOT_ISSUES.search(normalize(brackets)):
        return None
    years = re.findall(r'[\(\[]((?:19|20)\d\d)[\)\]]', stem)
    bare = re.sub(r'[\(\[][^\)\]]*[\)\]]', ' ', stem)
    bare = re.sub(r'\bof\s+\d+\s*$', '', normalize(bare.replace('_', ' '))).strip()
    m = re.match(r'^(.*?)\s*#?\s*(\d+(?:\.\d+)?[a-z]?)$', bare)
    if m is None or not m.group(1):
        return None
    # "Batman v3 012 (2016)": the volume goes, the year check picks the run
    series = re.sub(r'\s+v\d+$', '', m.group(1).strip())
    return series, number_key(m.group(2)), int(years[0]) if years else None


def pick_files(items, series_names, wanted, series_year=None):
    """
    The folder files worth queueing: at most one per Wanted issue of this series.

    items are AirDC++ filelist items; wanted maps a number key to
    {'issueid':, 'year':}. A file whose name carries a year must fall between the series'
    first year and the issue's year plus one. Of several copies, the biggest wins.
    """
    names = {normalize(n) for n in series_names if n}
    best = {}
    for item in items or []:
        if (item.get('type') or {}).get('id') == 'directory' or not item.get('tth'):
            continue
        size = item.get('size') or 0
        if size < MIN_BYTES:
            continue
        parsed = parse_name(item.get('name'))
        if parsed is None:
            continue
        series, key, year = parsed
        if series not in names or key not in wanted:
            continue
        if year is not None:
            issue_year = wanted[key].get('year')
            if series_year and year < int(series_year):
                continue
            if issue_year and year > int(issue_year) + 1:
                continue
        if key not in best or size > best[key]['size']:
            best[key] = item
    picked = [dict(best[k], issueid=wanted[k]['issueid']) for k in best]
    return picked[:MAX_FILES]


def wanted_issues(comicid, skip_issueid=None):
    """This series' Wanted issues as {number key: {'issueid':, 'year':}}."""
    myDB = db.DBConnection()
    rows = myDB.select("SELECT IssueID, Issue_Number, IssueDate FROM issues WHERE ComicID=? AND Status='Wanted'", [comicid])
    wanted = {}
    for row in rows:
        if row['IssueID'] == skip_issueid:
            continue
        key = number_key(row['Issue_Number'])
        if key is None or key in wanted:
            continue
        date = row['IssueDate'] or ''
        wanted[key] = {'issueid': row['IssueID'], 'year': int(date[:4]) if date[:4].isdigit() else None}
    return wanted


def series_names(comic):
    names = [comic['ComicName']]
    for alt in (comic['AlternateSearch'] or '').split('##'):
        if alt.strip() and alt.strip() != 'None':
            names.append(alt.strip())
    return names


class FolderPack(object):
    def __init__(self, dl):
        self.dl = dl      # an airdcpp.AirDCPP, for its session, headers and api_url

    def call(self, method, path, payload=None):
        url = self.dl.api_url + path
        if method == 'GET':
            r = self.dl.session.get(url, headers=self.dl.headers, timeout=30)
        elif method == 'DELETE':
            r = self.dl.session.delete(url, headers=self.dl.headers, timeout=30)
        else:
            r = self.dl.session.post(url, json=payload, headers=self.dl.headers, timeout=30)
        if r.status_code not in (200, 204):
            raise IOError('%s %s answered %s: %s' % (method, path, r.status_code, r.text))
        return r.json() if r.status_code == 200 and r.text else None

    def list_folder(self, user, folder):
        """The items in one folder of a peer's share."""
        opened = self.call('POST', '/filelists', {'user': {'cid': user['cid'], 'hub_url': user['hub_url']},
                                                  'directory': folder})
        session = (opened or {}).get('id') or user['cid']
        try:
            deadline = time.time() + LIST_WAIT
            while True:
                time.sleep(2)
                info = self.call('GET', '/filelists/%s' % session) or {}
                if (info.get('state') or {}).get('id') == 'loaded':
                    break
                if time.time() > deadline:
                    raise IOError('the peer\'s folder listing didn\'t arrive (peer offline?)')
            items = []
            while len(items) % 500 == 0 and len(items) < 5000:
                page = (self.call('GET', '/filelists/%s/items/%s/500' % (session, len(items))) or {}).get('items') or []
                if not page:
                    break
                items.extend(page)
            return items
        finally:
            try:
                self.call('DELETE', '/filelists/%s' % session)
            except Exception:
                pass

    def target_folder(self):
        """Where AirDC++ should save, as AirDC++ sees it, ending in '/'; None when unknown."""
        if not airdcpp.use_own_folder():
            return airdcpp.download_location()
        folder = mylar.CONFIG.AIRDCPP_REMOTE_DIR
        if not folder:
            try:
                folder = (self.call('POST', '/settings/get', {'keys': ['download_directory']}) or {}).get('download_directory')
            except Exception as e:
                logger.fdebug('[AIRDCPP-PACK] Couldn\'t read AirDC++\'s download folder: %s' % e)
        if not folder:
            return None
        return folder.replace('\\', '/').rstrip('/') + '/'

    def queue(self, item, target):
        data = self.call('POST', '/queue/bundles/file', {'target_directory': target, 'target_name': item['name'],
                                                         'size': item['size'], 'tth': item['tth'], 'priority': 3})
        return ((data or {}).get('bundle_info') or {}).get('id') or (data or {}).get('id')

    def watch(self, bundles):
        """Wait on the queued bundles; yields (item, bundle data) for each that completes."""
        pending = dict(bundles)
        last_change = time.time()
        progress = {}
        failed = []
        while pending:
            time.sleep(POLL)
            for bid in list(pending):
                try:
                    data = self.call('GET', '/queue/bundles/%s' % bid) or {}
                except Exception:
                    continue
                status = data.get('status') or {}
                done = data.get('downloaded_bytes') or 0
                if done != progress.get(bid):
                    progress[bid] = done
                    last_change = time.time()
                if status.get('completed'):
                    yield pending.pop(bid), data
                elif status.get('failed'):
                    logger.warn('[AIRDCPP-PACK] AirDC++ gave up on %s' % pending[bid]['name'])
                    failed.append(pending.pop(bid))
            if pending and time.time() - last_change > STALL_LIMIT:
                logger.warn('[AIRDCPP-PACK] Nothing moved for %s minutes; leaving %s file(s) to AirDC++ and putting them back to Wanted.'
                            % (STALL_LIMIT // 60, len(pending)))
                break
        self.left_over = failed + list(pending.values())


def grab_folder(comicid, issueid, entry):
    """Queue the series' other Wanted issues from the peer folder `entry` was found in."""
    user = entry.get('peer')
    folder = entry.get('folder')
    if not user or not user.get('cid') or not folder:
        return
    myDB = db.DBConnection()
    comic = myDB.selectone('SELECT * FROM comics WHERE ComicID=?', [comicid]).fetchone()
    if comic is None:
        return
    wanted = wanted_issues(comicid, skip_issueid=issueid)
    if not wanted:
        return

    pack = FolderPack(airdcpp.AirDCPP(comicid=comicid))
    try:
        items = pack.list_folder(user, folder)
    except Exception as e:
        logger.info('[AIRDCPP-PACK] Couldn\'t open %s on %s: %s' % (folder, user.get('nicks') or 'the peer', e))
        return
    files = pick_files(items, series_names(comic), wanted, comic['ComicYear'])
    logger.info('[AIRDCPP-PACK] %s holds %s of the %s Wanted issue(s) of %s.' % (folder, len(files), len(wanted), comic['ComicName']))
    if not files:
        return
    target = pack.target_folder()
    if target is None:
        logger.warn('[AIRDCPP-PACK] Set "AirDC++ download folder, as AirDC++ sees it" in Settings so folder packs know where to save.')
        return

    bundles = {}
    for item in files:
        try:
            bid = pack.queue(item, target)
        except Exception as e:
            logger.warn('[AIRDCPP-PACK] Couldn\'t queue %s: %s' % (item['name'], e))
            continue
        if bid is None:
            continue
        bundles[bid] = item
        updater.nzblog(item['issueid'], item['name'], comic['ComicName'], id=item['tth'], prov='AirDCPP')
        updater.foundsearch(comicid, item['issueid'], mode='series', provider='AirDCPP')

    local_dir = airdcpp.download_location()
    for item, data in pack.watch(bundles):
        if airdcpp.use_own_folder():
            path = airdcpp.local_path(data.get('target'), mylar.CONFIG.AIRDCPP_REMOTE_DIR, local_dir, item['name'])
        else:
            path = local_dir + item['name']
        if not os.path.exists(path):
            logger.warn('[AIRDCPP-PACK] %s finished but isn\'t at %s' % (item['name'], path))
            continue
        stem, ext = os.path.splitext(item['name'])
        tagged = path[:len(path) - len(item['name'])] + '%s[__%s__]%s' % (stem, item['issueid'], ext)
        try:
            os.rename(path, tagged)
            path = tagged
        except OSError as e:
            logger.warn('[AIRDCPP-PACK] Unable to rename %s: %s' % (path, e))
        if mylar.CONFIG.POST_PROCESSING is True:
            mylar.PP_QUEUE.put({'nzb_name': os.path.basename(path), 'nzb_folder': os.path.dirname(path),
                                'issueid': item['issueid'], 'comicid': comicid, 'failed': False,
                                'apicall': True, 'ddl': False})
            logger.info('[AIRDCPP-PACK] Added %s to post-processing queue.' % os.path.basename(path))

    for item in getattr(pack, 'left_over', []):
        myDB.action("UPDATE issues SET Status='Wanted' WHERE IssueID=? AND Status='Snatched'", [item['issueid']])


def start(comicid, issueid, entry):
    """Run grab_folder in the background when the setting is on and the hit carried its peer folder."""
    if not getattr(mylar.CONFIG, 'AIRDCPP_FOLDER_PACKS', False) or not comicid:
        return False
    if not (entry or {}).get('peer') or not (entry or {}).get('folder'):
        return False

    def run():
        try:
            grab_folder(comicid, issueid, entry)
        except Exception as e:
            logger.error('[AIRDCPP-PACK] Folder pack failed: %s' % e)

    threading.Thread(target=run, name='AIRDCPP-PACK', daemon=True).start()
    return True
