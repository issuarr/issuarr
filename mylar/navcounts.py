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

# Counts for the sidebar badges. Each is cached for a minute, since every page asks.

import time

import mylar
from mylar import db, logger

CACHE_SECONDS = 60
_cache = {}


def _cached(key, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        n = fn(db.DBConnection())
    except Exception as e:
        logger.fdebug('[NAV] Could not count %s: %s' % (key, e))
        n = 0
    _cache[key] = (time.time(), n)
    return n


def clear():
    _cache.clear()


def _wanted(myDB):
    # The same issues the Wanted page lists under All (webserve.loadupcoming).
    statuses = ['Wanted']
    if mylar.CONFIG.UPCOMING_SNATCHED:
        statuses.append('Snatched')
    if mylar.CONFIG.FAILED_DOWNLOAD_HANDLING:
        statuses.append('Failed')
    marks = ','.join('?' * len(statuses))
    parts = ['SELECT IssueID FROM issues WHERE Status IN (%s)' % marks]
    args = list(statuses)
    if mylar.CONFIG.ANNUALS_ON:
        parts.append('SELECT IssueID FROM annuals WHERE NOT Deleted AND Status IN (%s)' % marks)
        args += statuses
    n = myDB.selectone('SELECT count(*) AS n FROM (%s)' % ' UNION ALL '.join(parts), args).fetchone()['n']
    if mylar.CONFIG.UPCOMING_STORYARCS:
        # arc issues that aren't already counted as a series issue
        n += myDB.selectone('SELECT count(DISTINCT IssueID) AS n FROM storyarcs WHERE Status IN (%s) AND IssueID NOT IN (%s)' % (marks, ' UNION '.join(parts)),
                            statuses + args).fetchone()['n']
    return n


def wanted():
    """Issues on the Wanted page (its All tab)."""
    return _cached('wanted', _wanted)


def _import_choices(myDB):
    return myDB.selectone("SELECT count(DISTINCT DynamicName || '|' || IFNULL(Volume, '')) AS n FROM importresults "
                          "WHERE Status='Manual Intervention' AND (WatchMatch IS NULL OR WatchMatch LIKE 'C%')").fetchone()['n']


def import_choices():
    """Series on Import results waiting for you to choose their ComicVine match."""
    return _cached('import_choices', _import_choices)
