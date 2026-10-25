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

import re

from mylar import db

# A search that found hundreds of series only shows the closest ones; the search box finds others.
MAX_CANDIDATES = 40


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


def choice(dynamicname, volume=None):
    """The scanned series (name, year, files) and its possible ComicVine series, closest first."""
    myDB = db.DBConnection()
    rows = _rows(myDB, dynamicname, volume)
    if not rows:
        return {'ok': False, 'note': 'That series isn\'t in the import results any more.'}
    first = rows[0]
    files = sorted(({'id': r['impID'], 'name': r['ComicFilename'], 'number': r['IssueNumber']} for r in rows),
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
    cyear = lambda c: _year(c['year'])
    want = _norm(first['ComicName'])
    candidates.sort(key=lambda c: (not c['fits'], _norm(c['name']) != want,
                                   abs(cyear(c) - year) if year and cyear(c) else 999,
                                   not c['watched'], c['name'] or ''))
    return {'ok': True,
            'series': {'name': first['DisplayName'] or first['ComicName'], 'comicname': first['ComicName'],
                       'dynamicname': first['DynamicName'], 'volume': first['Volume'], 'year': first['ComicYear'],
                       'status': first['Status'], 'files': files, 'top': top},
            'candidates': candidates[:MAX_CANDIDATES], 'total': len(candidates)}


def file_path(impid):
    """The scanned file behind an import result, for its cover."""
    row = db.DBConnection().selectone('SELECT ComicLocation FROM importresults WHERE impID=?', [impid]).fetchone()
    return row['ComicLocation'] if row else None
