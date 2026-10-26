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

"""Discover: new and notable series to add, built from the weekly pull lists Issuarr already
keeps (the weekly table). Those rows carry ComicVine volume and issue ids, so building the feeds
costs no ComicVine calls. Covers are looked up 100 issues per call and cached on disk.

Feeds:
  new     - issue #1s that shipped in the window, one card per series, newest first
  latest  - any issue in the window, one card per series, keeping its newest issue
  foryou  - the new #1s from the publishers you have the most series from
"""

import datetime
import json
import os
import re
import threading

import mylar
from mylar import db, helpers, logger

WEEK_CHOICES = (4, 6, 8, 12)
DEFAULT_WEEKS = 6
FOR_YOU_PUBLISHERS = 8
LATEST_LIMIT = 120
COVER_BATCH = 100       # ComicVine's most ids in one filter

# The pull's format column and series names mark collected editions; Discover is for series to follow.
COLLECTED = re.compile(r'trade|hard ?cover|omnibus|collect|graphic novel|\btpb?\b|\bhc\b|paperback|compendium|\bgn\b|box set', re.I)

_fetch_lock = threading.Lock()
_fetching = set()        # weeks being fetched now, as (year, week)
_failed = {}             # (year, week) -> time it failed, so a dead backend isn't asked on every visit
FAIL_RETRY = 3600

_cover_lock = threading.Lock()
_cover_running = [False]


def recent_weeks(count, today=None):
    """The last count pull weeks, newest first, as (week, year)."""
    day = today or datetime.date.today()
    out = []
    for i in range(count):
        wk = helpers.release_week(day - datetime.timedelta(weeks=i))
        if wk not in out:
            out.append(wk)
    return out


def missing_weeks(myDB, weeks):
    have = set()
    try:
        rows = myDB.select('SELECT DISTINCT weeknumber, year FROM weekly')
    except Exception:
        rows = []
    for row in rows:
        try:
            have.add((int(row['weeknumber']), int(row['year'])))
        except (TypeError, ValueError):
            pass
    return [(w, y) for w, y in weeks if (int(w), int(y)) not in have]


def fill_weeks(weeks):
    """Fetch the pull lists Discover needs but the database doesn't have yet, in the background.
    Returns True while any of them are still being fetched."""
    if mylar.CONFIG.ALT_PULL != 2:
        return False   # only the default pull source can be asked for a given week
    now = datetime.datetime.now().timestamp()
    todo = []
    with _fetch_lock:
        for w, y in missing_weeks(db.DBConnection(), weeks):
            key = (int(y), int(w))
            if key in _fetching or now - _failed.get(key, 0) < FAIL_RETRY:
                continue
            _fetching.add(key)
            todo.append(key)
        busy = bool(_fetching)
    if todo:
        threading.Thread(target=_fetch, args=(todo,), name='DISCOVER-PULL', daemon=True).start()
    return busy or bool(todo)


def _fetch(todo):
    from mylar import locg
    for y, w in todo:
        try:
            res = locg.locg(weeknumber=w, year=y)
            if (res or {}).get('status') not in ('success', 'up2date'):
                _failed[(y, w)] = datetime.datetime.now().timestamp()
        except Exception as e:
            logger.warn('[DISCOVER] Could not get the pull list for week %s, %s: %s' % (w, y, e))
            _failed[(y, w)] = datetime.datetime.now().timestamp()
        finally:
            with _fetch_lock:
                _fetching.discard((y, w))


def _number(issue):
    try:
        return float(re.sub(r'^#', '', str(issue or '').strip()))
    except ValueError:
        return None


def collected(row):
    return bool(COLLECTED.search(str(row['FORMAT'] or '')) or COLLECTED.search(str(row['COMIC'] or '')))


def _card(row, owned):
    return {
        'comicid': row['ComicID'] or None,
        'issueid': row['IssueID'] or None,
        'series': row['COMIC'],
        'issue': row['ISSUE'],
        'publisher': row['PUBLISHER'],
        'shipdate': row['SHIPDATE'],
        'year': row['seriesyear'] or (str(row['SHIPDATE'] or '')[:4] or None),
        'owned': bool(row['ComicID']) and row['ComicID'] in owned,
    }


def top_publishers(myDB, count=FOR_YOU_PUBLISHERS):
    rows = myDB.select("SELECT ComicPublisher, COUNT(*) AS n FROM comics WHERE ComicPublisher IS NOT NULL AND ComicPublisher != '' "
                       "GROUP BY lower(ComicPublisher) ORDER BY n DESC LIMIT ?", [count])
    return [r['ComicPublisher'] for r in rows]


def feeds(myDB, weeks):
    """The three feeds from the pull rows of the given weeks."""
    if not weeks:
        return {'new': [], 'latest': [], 'foryou': [], 'publishers': []}
    # weeknumber and year are text in some databases and numbers in others
    where = ' OR '.join(['(CAST(weeknumber AS INTEGER)=? AND CAST(year AS INTEGER)=?)'] * len(weeks))
    args = []
    for w, y in weeks:
        args += [int(w), int(y)]
    try:
        rows = myDB.select('SELECT * FROM weekly WHERE ' + where, args)
    except Exception:
        rows = []   # no weekly table yet
    owned = set(helpers.listLibrary().keys())

    first, newest = {}, {}
    for row in rows:
        if collected(row) or not row['COMIC']:
            continue
        key = row['ComicID'] or ('name:' + str(row['COMIC']).lower())
        card = _card(row, owned)
        shipped = str(row['SHIPDATE'] or '')
        if _number(row['ISSUE']) == 1 and (key not in first or shipped < first[key]['shipdate']):
            first[key] = card
        if key not in newest or shipped > str(newest[key]['shipdate'] or ''):
            newest[key] = card

    new = sorted(first.values(), key=lambda c: (str(c['shipdate'] or ''), c['series'].lower()), reverse=True)
    latest = sorted(newest.values(), key=lambda c: (str(c['shipdate'] or ''), c['series'].lower()), reverse=True)[:LATEST_LIMIT]
    publishers = top_publishers(myDB)
    mine = set(p.lower() for p in publishers)
    foryou = [c for c in new if str(c['publisher'] or '').lower() in mine]
    return {'new': new, 'latest': latest, 'foryou': foryou, 'publishers': publishers}


# ---- covers ------------------------------------------------------------------------------

def _cover_map_path():
    from mylar import attention
    return os.path.join(attention._cover_dir(), 'discover-urls.json')


def _load_map():
    try:
        with open(_cover_map_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_map(urls):
    path = _cover_map_path()
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(urls, f)
    os.replace(tmp, path)


def cover_url(issueid):
    """The ComicVine cover URL of a pull-list issue: a URL, '' when ComicVine has none, or None
    when it hasn't been looked up yet."""
    return _load_map().get(str(issueid))


def want_covers(issueids):
    """Look up the cover URLs of these issues in the background, 100 per ComicVine call."""
    if mylar.CONFIG.COMICVINE_API in (None, '', 'None'):
        return
    known = _load_map()
    todo = [str(i) for i in dict.fromkeys(issueids) if i and str(i).isdigit() and str(i) not in known]
    if not todo:
        return
    with _cover_lock:
        if _cover_running[0]:
            return
        _cover_running[0] = True
    threading.Thread(target=_lookup_covers, args=(todo,), name='DISCOVER-COVERS', daemon=True).start()


def _lookup_covers(todo):
    from mylar import cv
    try:
        for i in range(0, len(todo), COVER_BATCH):
            batch = todo[i:i + COVER_BATCH]
            url = '%sissues/' % mylar.CVURL
            params = {'api_key': mylar.CONFIG.COMICVINE_API, 'format': 'json', 'limit': COVER_BATCH,
                      'filter': 'id:%s' % '|'.join(batch), 'field_list': 'id,image'}
            try:
                r = cv.cv_request(url, params=params, timeout=30)
                results = r.json().get('results') or []
            except Exception as e:
                logger.warn('[DISCOVER] Cover lookup failed: %s' % e)
                return
            found = {}
            for res in results:
                img = res.get('image') or {}
                found[str(res.get('id'))] = img.get('medium_url') or img.get('small_url') or img.get('original_url') or ''
            urls = _load_map()
            for issueid in batch:
                urls[issueid] = found.get(issueid, '')
            _save_map(urls)
    finally:
        with _cover_lock:
            _cover_running[0] = False


def cover(issueid):
    """The cached cover image path, attention.BUSY while it's still being looked up, or None."""
    from mylar import attention
    url = cover_url(issueid)
    if url is None:
        return attention.BUSY if _cover_running[0] else None
    if not url:
        return None
    return attention.url_cover('issue-%s' % re.sub(r'[^0-9]', '', str(issueid)), url)
