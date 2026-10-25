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

"""Files in a series folder that probably belong to another series.

Two ways a file ends up in the wrong place:

- another volume: its number is past the last issue of this series (Batman #713
  in Batman (2016), which ends at #150). When most files are like that, the
  whole series was likely added as the wrong ComicVine volume.
- a collected edition in a series of single issues: its name says TPB, HC,
  Omnibus and so on, or it is far bigger than the series' other files
  (a two-volume collection read as issue #2).

Nothing is moved here; the series page lists what was found.
"""

import os
import statistics
import re
import threading

from mylar import db, editions, logger

SIZE_FACTOR = 3                 # this many times the series' typical file size
SIZE_FLOOR = 50 * 1048576       # and at least this big, so small series aren't flagged
SIZE_MIN_FILES = 5              # need this many files to know what typical is
PAST_MARGIN = 2                 # a couple of issues past the end may just be new ones ComicVine lacks yet
WHOLE_SHARE = 0.5               # this share of the files past the end: the series is likely wrong

_CACHE = {}                     # comicid -> (folder signature, result)
_LOCK = threading.Lock()


def _num(number):
    """The issue number as a number ("12", "12.1", "#012"), or None for "Annual" and the like."""
    m = re.match(r'^\s*#?(\d+(?:\.\d+)?)', str(number or ''))
    return float(m.group(1)) if m else None


def _show(n):
    return str(int(n)) if n == int(n) else str(n)


def _key(number):
    return str(number or '').strip().lstrip('0').lower() or '0'


def suspects(files, numbers, series_name, singles=True):
    """files: dicts with name, size, number (the issue it's matched to, or None) and
    reads_as (the issue number its name reads as). numbers: the series' issue numbers.
    Returns {name: {'kind': 'volume'|'collected'|'size', 'note': str}} and whether the
    whole series looks like the wrong volume."""
    found = {}
    nums = [n for n in (_num(x) for x in numbers) if n is not None]
    last = max(nums) if nums else None
    known = {_key(x) for x in numbers}
    past = 0
    for f in files:
        if f.get('number') is None and f.get('reads_as') not in (None, '') and last is not None:
            n = _num(f['reads_as'])
            if n is not None and n > last + PAST_MARGIN and _key(f['reads_as']) not in known:
                past += 1
                found[f['name']] = {'kind': 'volume',
                                    'note': 'Reads as #%s, but this series ends at #%s. It may be another volume.' % (f['reads_as'], _show(last))}

    if singles:
        sizes = [f['size'] for f in files if f.get('size')]
        typical = statistics.median(sizes) if len(sizes) >= SIZE_MIN_FILES else None
        for f in files:
            if f['name'] in found:
                continue
            if editions.collected(f['name'], series_name):
                found[f['name']] = {'kind': 'collected',
                                    'note': 'The name says it\'s a collected edition, but this is a series of single issues.'}
            elif typical and f.get('size') and f['size'] >= max(SIZE_FLOOR, SIZE_FACTOR * typical):
                found[f['name']] = {'kind': 'size',
                                    'note': '%d MB, about %d times this series\' typical %d MB. It may be a collected edition.'
                                            % (f['size'] // 1048576, round(f['size'] / typical), typical // 1048576)}
    whole = len(files) >= 3 and past >= WHOLE_SHARE * len(files)
    return found, whole


def _claimed_by_others(myDB, comic):
    """File names other series in the same folder count as theirs (a series and its trades
    can share one folder), so they're never flagged here."""
    rows = myDB.select('SELECT i.Location FROM issues i JOIN comics c ON c.ComicID=i.ComicID '
                       "WHERE c.ComicLocation=? AND c.ComicID!=? AND i.Location IS NOT NULL AND i.Status='Downloaded'",
                       [comic['ComicLocation'], comic['ComicID']])
    return {r['Location'] for r in rows}


def check(comicid):
    """The suspect files of a series, for the series page. Cached until the folder changes."""
    from mylar import attention, matching
    myDB = db.DBConnection()
    comic = myDB.selectone('SELECT * FROM comics WHERE ComicID=?', [comicid]).fetchone()
    if comic is None:
        return {'ok': False, 'note': 'That series isn\'t on your watchlist.'}
    found_files = matching.walk(matching.series_dirs(comic))
    sig = tuple(sorted((f['name'], f['size']) for f in found_files))
    with _LOCK:
        hit = _CACHE.get(str(comicid))
    if hit and hit[0] == sig:
        return hit[1]

    issues = myDB.select('SELECT Issue_Number, Location, Status FROM issues WHERE ComicID=?', [comicid])
    linked = {i['Location']: i['Issue_Number'] for i in issues if i['Location'] and i['Status'] == 'Downloaded'}
    others = _claimed_by_others(myDB, comic)
    files = []
    for f in found_files:
        if f['name'] in others:
            continue
        number = linked.get(f['name'])
        # only unmatched files need their name read; matched ones have a number
        reads_as = attention.parse(f['path']).get('issue') if number is None else None
        files.append({'name': f['name'], 'sub': f['sub'], 'size': f['size'], 'number': number, 'reads_as': reads_as})
    found, whole = suspects(files, [i['Issue_Number'] for i in issues], comic['ComicName'],
                            editions.singles(comic['Type'], comic['Corrected_Type']))
    out = {'ok': True, 'whole': whole,
           'files': [dict(f, **found[f['name']]) for f in files if f['name'] in found]}
    if out['files']:
        logger.fdebug('[VOLUME-CHECK] %s: %s file(s) may belong to another series.' % (comic['ComicName'], len(out['files'])))
    with _LOCK:
        _CACHE[str(comicid)] = (sig, out)
    return out


def send_away(comicid, name):
    """Move a flagged file out of the series folder into Needs attention, where File as can put
    it in the series it belongs to."""
    from mylar import attention, matching
    import shutil
    myDB = db.DBConnection()
    comic = myDB.selectone('SELECT * FROM comics WHERE ComicID=?', [comicid]).fetchone()
    if comic is None:
        return {'ok': False, 'note': 'That series isn\'t on your watchlist.'}
    flagged = {f['name']: f for f in check(comicid).get('files', [])}
    if name not in flagged:
        return {'ok': False, 'note': 'That file isn\'t one flagged here any more.'}
    src = next((f['path'] for f in matching.walk(matching.series_dirs(comic)) if f['name'] == name), None)
    if src is None:
        return {'ok': False, 'note': 'That file isn\'t in the series folder any more.'}
    dest_dir = attention.review_dir()
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    if os.path.exists(dest):
        return {'ok': False, 'note': 'Needs attention already has a file called %s.' % name}
    shutil.move(src, dest)
    attention.record(dest, 'volume', 'Moved from %s (%s): %s' % (comic['ComicName'], comic['ComicYear'], flagged[name]['note']))
    logger.info('[VOLUME-CHECK] Moved %s out of %s into Needs attention.' % (name, comic['ComicName']))
    with _LOCK:
        _CACHE.pop(str(comicid), None)
    matching._rescan(comicid)
    return {'ok': True, 'note': '%s is in Needs attention now. Use File as there to put it in the right series.' % name}
