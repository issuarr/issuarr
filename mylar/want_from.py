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

"""Want a series from issue #N onward (comics.WantFrom).

For picking up a long run late: issues from #N on are Wanted and earlier ones Skipped,
whatever "Mark all issues as wanted" and "Mark upcoming issues as wanted" say. Setting it
changes the Wanted/Skipped issues once; after that, refreshes use it for each issue
ComicVine adds, and for Skipped issues a refresh looks at again. Issues you have, have
snatched, archived or ignored are never touched, and neither is a paused series.
"""

import re
import time

from mylar import db, logger

_CACHE = {}         # comicid -> (looked up at, start number or None)
CACHE_SECONDS = 30


def number(value):
    """An issue number as a number ("12", "12.1", "#012"), or None for "Annual" and the like."""
    m = re.match(r'^\s*#?(-?\d+(?:\.\d+)?)', str(value or ''))
    return float(m.group(1)) if m else None


def start(comicid):
    hit = _CACHE.get(str(comicid))
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        row = db.DBConnection().selectone('SELECT WantFrom FROM comics WHERE ComicID=?', [comicid]).fetchone()
        value = number(row['WantFrom']) if row else None
    except Exception:
        value = None
    _CACHE[str(comicid)] = (time.time(), value)
    return value


def decide(first, issue_number, status):
    """The status for an issue given the series' first wanted number, for a status the
    refresh rules picked (only Wanted and Skipped are changed)."""
    if first is None or status not in ('Wanted', 'Skipped'):
        return status
    n = number(issue_number)
    if n is None:
        return status
    return 'Wanted' if n >= first else 'Skipped'


def adjust(comicid, issue_number, status):
    return decide(start(comicid), issue_number, status)


def set_from(comicid, value):
    """Store #N (or clear it with a blank value) and change the series' Wanted/Skipped issues
    to match. Returns how many issues changed."""
    myDB = db.DBConnection()
    comic = myDB.selectone('SELECT ComicName FROM comics WHERE ComicID=?', [comicid]).fetchone()
    if comic is None:
        return {'ok': False, 'note': 'That series isn\'t on your watchlist.'}
    value = str(value or '').strip().lstrip('#').strip()
    if not value:
        myDB.upsert('comics', {'WantFrom': None}, {'ComicID': comicid})
        _CACHE.pop(str(comicid), None)
        logger.info('[WANT-FROM] %s: back to the usual rules for new issues.' % comic['ComicName'])
        return {'ok': True, 'changed': 0, 'note': 'New issues of %s follow your usual settings again. Nothing was changed.' % comic['ComicName']}
    first = number(value)
    if first is None:
        return {'ok': False, 'note': 'Give an issue number, like 25.'}
    myDB.upsert('comics', {'WantFrom': value}, {'ComicID': comicid})
    _CACHE.pop(str(comicid), None)
    changed = 0
    for i in myDB.select("SELECT IssueID, Issue_Number, Status FROM issues WHERE ComicID=? AND Status IN ('Wanted', 'Skipped')", [comicid]):
        new = decide(first, i['Issue_Number'], i['Status'])
        if new != i['Status']:
            myDB.upsert('issues', {'Status': new}, {'IssueID': i['IssueID']})
            changed += 1
    logger.info('[WANT-FROM] %s: wanting from #%s, %s issue(s) changed.' % (comic['ComicName'], value, changed))
    return {'ok': True, 'changed': changed,
            'note': 'Wanting %s from #%s on. %s issue%s changed between Wanted and Skipped.' % (comic['ComicName'], value, changed, '' if changed == 1 else 's')}
