#  This file is part of Issuarr.
#
#  Issuarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Issuarr is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the
#  implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public
#  License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Issuarr.  If not, see <http://www.gnu.org/licenses/>.

# Import results > Needs a choice: what the Choose match window shows for one scanned series,
# its files and the ComicVine series the import found for it (the searchresults table).

import os
import re
import time

import mylar
from mylar import db, logger, navcounts

# A search that found hundreds of series only shows the closest ones; the search box finds others.
MAX_CANDIDATES = 40


COMIC_EXTS = ('.cbz', '.cbr', '.cb7')


def _live(path):
    """Where a scanned file is now. A .cbr converted to .cbz since the scan (CBR to CBZ, WebP)
    is found under its new name; None when neither is there."""
    if not path:
        return None
    if os.path.isfile(path):
        return path
    stem = os.path.splitext(path)[0]
    return next((stem + ext for ext in COMIC_EXTS if os.path.isfile(stem + ext)), None)


def _gone(path):
    """The file is gone for good: not there under any comic extension, while the folder two levels up is
    (a library share that isn't mounted right now leaves its import results alone)."""
    return _live(path) is None and bool(path) and os.path.isdir(os.path.dirname(os.path.dirname(path)))


def _forget(myDB, paths):
    for path in paths:
        myDB.action("DELETE FROM importresults WHERE ComicLocation=? AND Status NOT IN ('Imported', 'Importing')", [path])


# how often the Import results page looks for files that are gone
DROP_EVERY = 60
_dropped_at = [0]


def drop_gone(force=False):
    """Forget import results whose file is gone (moved, deleted or imported elsewhere since the scan):
    there's nothing left to match or import. Returns how many files were forgotten."""
    if not force and time.time() - _dropped_at[0] < DROP_EVERY:
        return 0
    _dropped_at[0] = time.time()
    myDB = db.DBConnection()
    rows = myDB.select("SELECT DISTINCT ComicLocation FROM importresults WHERE Status NOT IN ('Imported', 'Importing') AND ComicLocation IS NOT NULL")
    gone = [r['ComicLocation'] for r in rows if _gone(r['ComicLocation'])]
    if gone:
        _forget(myDB, gone)
        logger.info('[IMPORT] Removed %s file(s) from Import results that are no longer on disk.' % len(gone))
        navcounts.clear()
    return len(gone)


# Imported files the recheck tied to no issue (a TPB, a number the series lacks, a folder no series owns)
NO_ISSUE = 'No Issue'
_untied_at = [0]


def _tied_paths(myDB):
    tied = set()
    for table in ('issues', 'annuals'):
        for r in myDB.select("SELECT c.ComicLocation, i.Location FROM %s i JOIN comics c ON c.ComicID = i.ComicID "
                             "WHERE i.Location IS NOT NULL AND i.Location != ''" % table):
            if r['ComicLocation']:
                tied.add(os.path.normpath(os.path.join(r['ComicLocation'], r['Location'])))
    return tied


def mark_untied(comicid=None, force=True):
    """Imported files no issue points to say No Issue, and say Imported again once one does.
    Returns how many rows changed."""
    if not force and time.time() - _untied_at[0] < DROP_EVERY:
        return 0
    _untied_at[0] = time.time()
    myDB = db.DBConnection()
    query = "SELECT impID, ComicLocation, Status FROM importresults WHERE Status IN ('Imported', ?) AND ComicLocation IS NOT NULL"
    args = [NO_ISSUE]
    if comicid is not None:
        query += ' AND ComicID=?'
        args.append(str(comicid))
    rows = myDB.select(query, args)
    if not rows:
        return 0
    tied = _tied_paths(myDB)
    changed = 0
    for r in rows:
        live = _live(r['ComicLocation'])
        if live is None:
            continue
        status = 'Imported' if os.path.normpath(live) in tied else NO_ISSUE
        if status != r['Status']:
            myDB.action('UPDATE importresults SET Status=? WHERE impID=? AND ComicLocation=?', [status, r['impID'], r['ComicLocation']])
            changed += 1
    if changed:
        navcounts.clear()
    return changed


def _number(text):
    m = re.search(r'\d+(?:\.\d+)?', str(text or ''))
    return float(m.group(0)) if m else None


def _year(text):
    m = re.search(r'\b(19|20)\d\d\b', str(text or ''))
    return int(m.group(0)) if m else None


def _norm(name):
    return re.sub(r'[^a-z0-9]+', '', re.sub(r'^the\s+', '', str(name or '').lower()))


def _rows(myDB, dynamicname, volume):
    sql = "SELECT * FROM importresults WHERE (WatchMatch IS NULL OR WatchMatch LIKE 'C%') AND DynamicName=? AND "
    if volume in (None, '', 'None'):
        return myDB.select(sql + "Volume IS NULL", [dynamicname])
    return myDB.select(sql + "Volume=?", [dynamicname, volume])


def _text(desc, limit=320):
    desc = re.sub(r'\s+', ' ', str(desc or '')).strip()
    if desc in ('', 'None'):
        return None
    return desc if len(desc) <= limit else desc[:limit].rsplit(' ', 1)[0] + '…'


# Words a publisher's name may or may not carry: "DC" and "DC Comics" are one publisher.
_PUB_WORDS = {'the', 'comics', 'comic', 'publishing', 'publications', 'entertainment', 'press', 'books',
              'studios', 'group', 'inc', 'llc', 'ltd', 'co'}
# how many folders above a file can name its publisher
_PUB_DEPTH = 3


def _pub(name):
    words = re.findall(r'[a-z0-9]+', str(name or '').lower().replace('&', ' and '))
    return ''.join(w for w in words if w not in _PUB_WORDS) or None


def _publisher_groups(extra=()):
    """Each known publisher with its imprints (Vertigo is DC), keyed by every name in the group."""
    groups = {}
    listing = mylar.PUBLISHER_IMPRINTS
    if listing is None:
        try:
            from mylar import imprints
            listing = imprints.load(None, mylar.PROG_DIR, download=False)
        except Exception:
            listing = None
    for entry in (listing or {}).get('publishers', []):
        for parent, imps in entry.items():
            group = {_pub(parent)} | {_pub(i.get('name')) for i in imps if isinstance(i, dict)}
            group.discard(None)
            for key in group:
                groups.setdefault(key, set()).update(group)
    try:
        known = [r['ComicPublisher'] for r in db.DBConnection().select('SELECT DISTINCT ComicPublisher FROM comics')]
    except Exception:
        known = []
    for name in list(known) + list(extra):
        key = _pub(name)
        if key:
            groups.setdefault(key, {key})
    return groups


def folder_publisher(paths, extra=(), series=None):
    """The publisher a folder above the files names (DC, Marvel, Image, or one of their imprints), as
    {'folder': its name, 'names': the publisher's names}, or None. extra: more publisher names to know.
    A folder named like the series itself ("Impact", also a DC imprint) isn't a publisher folder."""
    groups = _publisher_groups(extra)
    own = _pub(series)
    for path in paths:
        folder = os.path.dirname(path or '')
        for _ in range(_PUB_DEPTH):
            name = os.path.basename(folder)
            if not name:
                break
            key = _pub(name)
            if key in groups and key != own:
                return {'folder': name, 'names': groups[key]}
            folder = os.path.dirname(folder)
    return None


def publisher_fits(hint, publisher):
    return bool(hint) and _pub(publisher) in hint['names']


def by_folder(matches, paths, series=None):
    """The search matches an import may pick from: only the folder's publisher's, when the files sit
    under a publisher folder, so a series in a DC folder isn't matched to Panini."""
    hint = folder_publisher(paths, [m.get('publisher') for m in matches], series)
    if not hint:
        return matches
    same = [m for m in matches if publisher_fits(hint, m.get('publisher'))]
    if len(same) != len(matches):
        logger.fdebug('[IMPORT] The files are in a %s folder: %s of %s matches are from that publisher.'
                      % (hint['folder'], len(same), len(matches)))
    return same


def choice(dynamicname, volume=None):
    """The scanned series (name, year, files) and its possible ComicVine series, closest first."""
    myDB = db.DBConnection()
    rows = _rows(myDB, dynamicname, volume)
    if not rows:
        return {'ok': False, 'note': 'That series isn\'t in the import results any more.'}
    first = rows[0]
    files, seen, moved = [], set(), {}
    for r in rows:
        was = r['ComicLocation']
        if was not in moved:
            moved[was] = _live(was)
            if moved[was] and moved[was] != was:
                # renamed since the scan: point the results at the new name, so the import finds it too
                myDB.action('UPDATE importresults SET ComicLocation=?, ComicFilename=? WHERE ComicLocation=?',
                            [moved[was], os.path.basename(moved[was]), was])
                logger.fdebug('[IMPORT] %s is now %s' % (was, moved[was]))
        now = moved[was]
        # one entry per file: earlier scans (or a .cbr and the .cbz it became) can list a file more than once
        key = now or was or r['impID']
        if key in seen:
            continue
        seen.add(key)
        files.append({'id': r['impID'], 'name': os.path.basename(now) if now else r['ComicFilename'],
                      'path': now or was, 'number': r['IssueNumber'], 'missing': now is None})
    if files and all(f['missing'] for f in files) and all(_gone(f['path']) for f in files):
        _forget(myDB, [f['path'] for f in files])
        navcounts.clear()
        logger.info('[IMPORT] %s: its files are no longer on disk, so it was removed from Import results.' % (first['DisplayName'] or first['ComicName']))
        return {'ok': False, 'gone': True, 'note': 'This series\' files are no longer on disk, so it was removed from Import results.'}
    files = sorted(files,
                   key=lambda f: (_number(f['number']) is None, _number(f['number']) or 0, f['name'] or ''))
    numbers = [n for n in (_number(f['number']) for f in files) if n is not None]
    top = max(numbers) if numbers else None
    year = _year(first['ComicYear'])
    srid = next((r['SRID'] for r in rows if r['SRID']), None)
    watched = {str(r['ComicID']) for r in myDB.select('SELECT ComicID FROM comics')}
    found = myDB.select('SELECT * FROM searchresults WHERE SRID=?', [srid]) if srid else []
    seen, candidates = set(), []
    for s in found:
        cid = str(s['comicid'])
        if cid in seen:
            continue
        seen.add(cid)
        issues = _number(s['issues'])
        candidates.append({'comicid': cid, 'name': s['name'], 'year': s['comicyear'], 'publisher': s['publisher'],
                           'issues': int(issues) if issues is not None else None, 'thumb': s['comicimage'],
                           'url': s['url'], 'about': _text(s['deck']) or _text(s['description']),
                           'watched': cid in watched or str(s['haveit'] or 'No') not in ('No', 'None', ''),
                           'fits': issues is None or top is None or top <= issues})
    paths = [f['path'] for f in files if f['path']]
    folders = sorted({os.path.dirname(p) for p in paths})
    hint = folder_publisher(paths, [c['publisher'] for c in candidates], first['ComicName'])
    for c in candidates:
        c['samepub'] = publisher_fits(hint, c['publisher']) if hint else None
    cyear = lambda c: _year(c['year'])
    want = _norm(first['ComicName'])
    candidates.sort(key=lambda c: (not c['fits'], c['samepub'] is False, _norm(c['name']) != want,
                                   abs(cyear(c) - year) if year and cyear(c) else 999,
                                   not c['watched'], c['name'] or ''))
    return {'ok': True,
            'series': {'name': first['DisplayName'] or first['ComicName'], 'comicname': first['ComicName'],
                       'dynamicname': first['DynamicName'], 'volume': first['Volume'], 'year': first['ComicYear'],
                       'status': first['Status'], 'files': files, 'top': top, 'folders': folders,
                       'publisher_folder': hint['folder'] if hint else None},
            'candidates': candidates[:MAX_CANDIDATES], 'total': len(candidates)}


def file_path(impid):
    """The scanned file behind an import result, for its cover."""
    row = db.DBConnection().selectone('SELECT ComicLocation FROM importresults WHERE impID=?', [impid]).fetchone()
    return _live(row['ComicLocation']) if row else None
