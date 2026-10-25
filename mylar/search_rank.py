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

"""'Best match' order for Add series results.

ComicVine returns volumes in no useful order, so a search for "Saga" shows
dozens of one-shots and foreign editions around the series people mean. Each
result gets a score from how close its name is to what was typed, whether a
typed year matches, whether its publisher is one you already collect (or a
big one), and how long and recent the run is. The name counts most.
"""

import datetime
import difflib
import math
import re

# Publishers most people mean when they don't say. Kept short on purpose:
# publishers already in your library count for more.
WELL_KNOWN = {'marvel', 'dc comics', 'image', 'dark horse comics', 'idw publishing',
              'boom! studios', 'dynamite entertainment', 'oni press', 'valiant'}

YEAR = re.compile(r'\b(19[3-9]\d|20\d\d)\b')


def _norm(text):
    text = str(text or '').lower().replace('&', ' and ')
    text = re.sub(r"['’]", '', text)
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    words = [w for w in text.split() if w not in ('the', 'a', 'an')]
    return ' '.join(words)


def split_query(query):
    """The typed name without any year in it, and that year (or None)."""
    query = str(query or '')
    m = YEAR.search(query)
    year = int(m.group(1)) if m else None
    name = YEAR.sub(' ', query).replace('(', ' ').replace(')', ' ')
    return _norm(name), year


def name_score(query_name, title):
    """0..1: 1 for the same name, high when the title starts with or holds
    every typed word, otherwise how alike the two strings are."""
    title = _norm(title)
    if not query_name or not title:
        return 0.0
    if title == query_name:
        return 1.0
    ratio = difflib.SequenceMatcher(None, query_name, title).ratio()
    qwords, twords = query_name.split(), title.split()
    if set(qwords) <= set(twords):
        # every typed word is there; fewer extra words is closer
        cover = len(qwords) / len(twords)
        start = 0.1 if twords[:len(qwords)] == qwords else 0.0
        ratio = max(ratio, 0.55 + 0.3 * cover + start)
    return min(ratio, 0.99)


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def score(result, query_name, query_year, library_publishers, this_year=None):
    this_year = this_year or datetime.date.today().year
    s = 0.6 * name_score(query_name, result.get('comicname'))

    year = _int(result.get('comicyear'))
    if query_year and year:
        s += 0.2 if year == query_year else (0.08 if abs(year - query_year) == 1 else 0.0)

    pub = str(result.get('publisher') or '').strip().lower()
    if pub and pub in library_publishers:
        s += 0.12
    elif pub in WELL_KNOWN:
        s += 0.06

    issues = _int(result.get('issues')) or 0
    s += 0.08 * min(math.log10(issues + 1) / 2, 1.0)     # 99+ issues gets it all

    if year and not query_year:
        s += 0.04 * max(0.0, 1 - (this_year - year) / 40.0)

    if (result.get('type') or '').upper() in ('TPB', 'HC', 'GN'):
        s -= 0.03     # collected editions rarely the series meant
    return s


def rank(results, query, library_publishers=(), this_year=None):
    """results sorted best first. library_publishers: names of publishers
    already in the library, any case."""
    query_name, query_year = split_query(query)
    pubs = {str(p).strip().lower() for p in library_publishers if p}
    scored = [(score(r, query_name, query_year, pubs, this_year), i, r) for i, r in enumerate(results)]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [r for _, _, r in scored]


def library_publishers(myDB):
    try:
        rows = myDB.select("SELECT DISTINCT ComicPublisher FROM comics WHERE ComicPublisher IS NOT NULL AND ComicPublisher != ''")
    except Exception:
        return []
    return [r['ComicPublisher'] for r in rows]
