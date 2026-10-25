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

"""ComicVine links pasted into a search box, like
https://comicvine.gamespot.com/kissmas/4050-54999/ (a series) or
https://comicvine.gamespot.com/kissmas-1-merry-kissmas/4000-374290/ (an issue).
A bare 4050-54999 or 4000-374290 works too. An issue link stands for its series, plus that
issue where one is being picked."""

import re

import mylar
from mylar import db, logger

KINDS = {'4050': 'volume', '4000': 'issue'}

_URL = re.compile(r'^(?:https?://)?(?:www\.)?comicvine(?:\.gamespot)?\.com/\S*?(?<![\d-])(4050|4000)-(\d+)(?:[/?#]\S*)?$', re.I)
_BARE = re.compile(r'^(4050|4000)-(\d+)$')


def parse(text):
    """('volume', id) or ('issue', id) for a ComicVine link, otherwise None."""
    text = (text or '').strip()
    m = _URL.match(text) or _BARE.match(text)
    if not m:
        return None
    return KINDS[m.group(1)], m.group(2)


def local_issue(issueid):
    """The issue from the watchlist, without asking ComicVine, or None."""
    row = db.DBConnection().selectone('SELECT IssueID, ComicID, Issue_Number, IssueName FROM issues WHERE IssueID=?', [str(issueid)]).fetchone()
    if row is None:
        return None
    return {'issueid': str(row['IssueID']), 'comicid': str(row['ComicID']), 'number': row['Issue_Number'], 'name': row['IssueName']}


def cv_issue(issueid):
    """The issue and its series from ComicVine, or None. Goes through the shared ComicVine schedule."""
    from mylar import cv
    key = mylar.CONFIG.COMICVINE_API
    if not key or key == 'None':
        return None
    url = mylar.CVURL + 'issues/?api_key=' + str(key) + '&format=json&filter=id:' + str(issueid) + '&field_list=id,issue_number,name,volume'
    try:
        found = (cv.cv_request(url).json() or {}).get('results') or []
    except Exception as e:
        logger.warn('[COMICVINE] Couldn\'t look up issue %s: %s' % (issueid, e))
        return None
    for x in found:
        vol = x.get('volume') or {}
        if str(x.get('id')) == str(issueid) and vol.get('id'):
            return {'issueid': str(issueid), 'comicid': str(vol['id']), 'number': x.get('issue_number'), 'name': x.get('name'),
                    'series': vol.get('name')}
    return None


def resolve(text, ask_cv=True):
    """None when text isn't a ComicVine link. Otherwise a dict with kind, comicid (the series)
    and, for an issue link, issueid and number; comicid is None when the issue couldn't be
    found (ask_cv=False only looks on the watchlist)."""
    link = parse(text)
    if link is None:
        return None
    kind, cvid = link
    if kind == 'volume':
        return {'kind': kind, 'comicid': cvid, 'issueid': None}
    issue = local_issue(cvid) or (cv_issue(cvid) if ask_cv else None)
    if issue is None:
        return {'kind': kind, 'comicid': None, 'issueid': cvid}
    return dict(issue, kind=kind)


def cv_series(comicid):
    """True when ComicVine has a series with this ID, False when it hasn't, None when it couldn't
    be asked. Goes through the shared ComicVine schedule."""
    from mylar import cv
    key = mylar.CONFIG.COMICVINE_API
    if not key or key == 'None':
        return None
    url = mylar.CVURL + 'volumes/?api_key=' + str(key) + '&format=json&filter=id:' + str(comicid) + '&field_list=id,name'
    try:
        found = (cv.cv_request(url).json() or {}).get('results') or []
    except Exception as e:
        logger.warn('[COMICVINE] Couldn\'t look up series %s: %s' % (comicid, e))
        return None
    return any(str(x.get('id')) == str(comicid) for x in found)


def series_for_number(number):
    """The series a bare ComicVine number stands for: the number itself when it's a series ID,
    the issue's series when it's an issue ID. Looks on the watchlist first, then asks ComicVine
    (a series ID wins when both exist). None when ComicVine has neither; the number itself when
    ComicVine can't be asked."""
    number = str(number)
    if db.DBConnection().selectone('SELECT ComicID FROM comics WHERE ComicID=?', [number]).fetchone():
        return number
    issue = local_issue(number)
    if issue:
        return issue['comicid']
    series = cv_series(number)
    if series is None:
        return number
    if series:
        return number
    issue = cv_issue(number)
    return issue['comicid'] if issue else None
