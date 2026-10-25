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

"""Tools > Duplicates: issues with more than one file in the library, and which copy to keep.

A file counts for an issue when the series has it matched to that issue, or when its name
reads as that issue's number and nothing else claims it. For each issue with two or more
files the best copy is kept: one that opens, then one with ComicInfo tags, then more pages,
then the bigger file. Nothing moves until the extra copies are confirmed (another copy can be
kept instead), and they go to the Duplicates folder from Settings when one is set, otherwise
to the trash, where they stay for a while before being deleted.

Files that another series sharing the folder counts as its own, annuals, and collected
editions are left out, so a series and its trades in one folder are never mixed up.
"""

import datetime
import os
import shutil
import threading
import zipfile

import mylar
from mylar import db, editions, logger

STATE = {'state': 'idle', 'done': 0, 'total': 0, 'groups': [], 'finished': None, 'stop': False}
_LOCK = threading.Lock()


def _key(number):
    return str(number or '').strip().lstrip('0').lower() or '0'


def file_info(path):
    """Whether the file opens, has ComicInfo tags, and how many pages it has."""
    from mylar import archives
    out = {'readable': False, 'tagged': False, 'pages': 0}
    try:
        arc = archives._open(path)
        if arc is None:
            return out
        with arc:
            names = [i.filename for i in arc.infolist() if not archives._is_dir(i)]
            if isinstance(arc, zipfile.ZipFile) and arc.testzip() is not None:
                return out
    except Exception as e:
        logger.fdebug('[DUPLICATES] Could not open %s: %s' % (path, e))
        return out
    base = [os.path.basename(n).lower() for n in names]
    out.update(readable=True, tagged='comicinfo.xml' in base,
               pages=sum(1 for n in base if n.endswith(archives.IMAGE_EXT)))
    return out


def rank(files):
    """Best copy first: opens, tagged, more pages, bigger."""
    return sorted(files, key=lambda f: (f['readable'], f['tagged'], f['pages'], f['size']), reverse=True)


def _claimed_by_others(myDB, comic):
    rows = myDB.select('SELECT i.Location FROM issues i JOIN comics c ON c.ComicID=i.ComicID '
                       "WHERE c.ComicLocation=? AND c.ComicID!=? AND i.Location IS NOT NULL AND i.Status='Downloaded'",
                       [comic['ComicLocation'], comic['ComicID']])
    return {r['Location'] for r in rows}


def series_groups(myDB, comic):
    """The issues of one series with more than one file, best copy first in each."""
    from mylar import attention, matching
    found = matching.walk(matching.series_dirs(comic))
    if len(found) < 2:
        return []
    issues = [dict(r) for r in myDB.select('SELECT IssueID, Issue_Number, Location, Status FROM issues WHERE ComicID=?', [comic['ComicID']])]
    try:
        annual_files = {r['Location'] for r in myDB.select('SELECT Location FROM annuals WHERE ComicID=? AND Location IS NOT NULL', [comic['ComicID']])}
    except Exception:
        annual_files = set()
    linked = {i['Location']: i for i in issues if i['Location'] and i['Status'] == 'Downloaded'}
    by_number = {}
    for i in issues:
        by_number.setdefault(_key(i['Issue_Number']), i)
    skip = _claimed_by_others(myDB, comic) | annual_files
    series_annual = 'annual' in (comic['ComicName'] or '').lower()
    groups = {}
    for f in found:
        name = f['name']
        if name in skip or editions.collected(name, comic['ComicName']):
            continue
        issue = linked.get(name)
        matched = issue is not None
        if not matched:
            if 'annual' in name.lower() and not series_annual:
                continue
            reads_as = attention.parse(f['path']).get('issue')
            issue = by_number.get(_key(reads_as)) if reads_as not in (None, '') else None
        if issue is None:
            continue
        groups.setdefault(issue['IssueID'], {'issue': issue, 'files': []})['files'].append(dict(f, matched=matched))
    out = []
    for issueid, g in groups.items():
        if len(g['files']) < 2:
            continue
        for f in g['files']:
            f.update(file_info(f['path']))
        files = rank(g['files'])
        for n, f in enumerate(files):
            f['keep'] = n == 0
        out.append({'comicid': comic['ComicID'], 'series': comic['ComicName'], 'year': comic['ComicYear'],
                    'issueid': issueid, 'number': g['issue']['Issue_Number'], 'files': files})
    out.sort(key=lambda g: (str(g['number']).zfill(6)))
    return out


def scan():
    """Look through every series on the watchlist, in the background."""
    with _LOCK:
        if STATE['state'] == 'running':
            return False
        STATE.update(state='running', done=0, total=0, groups=[], finished=None, stop=False)
    threading.Thread(target=_scan, name='DUPLICATES', daemon=True).start()
    return True


def _scan():
    groups = []
    try:
        myDB = db.DBConnection()
        comics = myDB.select('SELECT ComicID, ComicName, ComicYear, ComicLocation FROM comics WHERE ComicLocation IS NOT NULL ORDER BY ComicSortName')
        STATE['total'] = len(comics)
        for c in comics:
            if STATE['stop']:
                break
            try:
                groups += series_groups(myDB, c)
            except Exception as e:
                logger.warn('[DUPLICATES] Could not check %s: %s' % (c['ComicName'], e))
            STATE['done'] += 1
            STATE['groups'] = list(groups)
        logger.info('[DUPLICATES] %s issue%s with more than one file.' % (len(groups), '' if len(groups) == 1 else 's'))
    finally:
        STATE.update(state='done', groups=groups, finished=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))


def status():
    return {k: STATE[k] for k in ('state', 'done', 'total', 'groups', 'finished')}


def stop():
    STATE['stop'] = True


def _dest_dir():
    dump = getattr(mylar.CONFIG, 'DUPLICATE_DUMP', None)
    if getattr(mylar.CONFIG, 'DDUMP', False) and dump and dump != 'None':
        return dump, 'the Duplicates folder'
    from mylar import attention
    return os.path.join(attention.trash_dir(), datetime.date.today().isoformat()), 'the trash'


def remove(paths):
    """Move the chosen copies out of the library. Only files from the last scan can be moved,
    and never every copy of an issue: one not chosen must still be there."""
    from mylar import matching
    wanted = set(paths)
    allowed, series = {}, set()
    for g in STATE['groups']:
        keep = next((f for f in g['files'] if f['path'] not in wanted and os.path.isfile(f['path'])), None)
        if keep is None:
            continue
        for f in g['files']:
            if f['path'] in wanted:
                allowed[f['path']] = (g, keep)
    dest, where = _dest_dir()
    moved, refused = 0, 0
    for path in paths:
        if path not in allowed or not os.path.isfile(path) or not os.path.isfile(allowed[path][1]['path']):
            refused += 1
            continue
        os.makedirs(dest, exist_ok=True)
        target = os.path.join(dest, os.path.basename(path))
        if os.path.exists(target):
            stem, ext = os.path.splitext(target)
            target = '%s (%s)%s' % (stem, int(datetime.datetime.now().timestamp()), ext)
        shutil.move(path, target)
        logger.info('[DUPLICATES] Moved %s to %s (kept %s).' % (os.path.basename(path), dest, allowed[path][1]['name']))
        moved += 1
        series.add(allowed[path][0]['comicid'])
    gone = {p for p in allowed if not os.path.exists(p)}
    for g in STATE['groups']:
        g['files'] = [f for f in g['files'] if f['path'] not in gone]
    STATE['groups'] = [g for g in STATE['groups'] if len(g['files']) > 1]
    for comicid in series:
        try:
            matching._rescan(comicid)
        except Exception as e:
            logger.warn('[DUPLICATES] Could not recheck series %s: %s' % (comicid, e))
    note = 'Moved %s cop%s to %s.' % (moved, 'y' if moved == 1 else 'ies', where)
    if refused:
        note += ' %s couldn\'t be moved (gone, kept copy missing, or not from this scan).' % refused
    return {'ok': moved > 0 or not refused, 'moved': moved, 'note': note}
