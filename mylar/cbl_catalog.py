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

"""The reading lists in DieselTech/CBL-ReadingLists, to pick from on the CBL import page
instead of downloading a .cbl file first.

The list of files comes from one GitHub API call and is kept for a day; a list itself
is fetched when it's opened. Only paths from that list can be fetched.
"""

import json
import os
import threading
import time
import urllib.parse

import requests

import mylar
from mylar import logger

REPO = 'DieselTech/CBL-ReadingLists'
BRANCH = 'main'
TREE_URL = 'https://api.github.com/repos/%s/git/trees/%s?recursive=1' % (REPO, BRANCH)
RAW_URL = 'https://raw.githubusercontent.com/%s/%s/' % (REPO, BRANCH)
PAGE_URL = 'https://github.com/%s/blob/%s/' % (REPO, BRANCH)
KEEP_SECONDS = 24 * 3600
MAX_LIST_BYTES = 5 * 1048576

_LOCK = threading.Lock()


def _cache_file():
    return os.path.join(mylar.CONFIG.CACHE_DIR or '.', 'cbl-catalog.json')


def lists_from_tree(tree):
    """The .cbl files in a git tree answer, each with its folder and a readable name."""
    out = []
    for e in tree.get('tree', []):
        path = e.get('path') or ''
        if e.get('type') != 'blob' or not path.lower().endswith('.cbl'):
            continue
        folder, name = os.path.split(path)
        out.append({'path': path, 'folder': folder, 'name': os.path.splitext(name)[0], 'size': e.get('size')})
    out.sort(key=lambda x: (x['folder'].lower(), x['name'].lower()))
    return out


def _read_cache():
    try:
        with open(_cache_file()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def catalog(refresh=False):
    """{'ok', 'lists', 'fetched', 'note'}: the catalog, from the day-old copy unless it's
    older or refresh is asked for. A failed fetch falls back to the old copy."""
    with _LOCK:
        cached = _read_cache()
        if cached and not refresh and time.time() - cached.get('fetched', 0) < KEEP_SECONDS:
            return dict(cached, ok=True)
        try:
            r = requests.get(TREE_URL, timeout=30, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'Issuarr'})
            r.raise_for_status()
            data = r.json()
            lists = lists_from_tree(data)
            if not lists:
                raise ValueError('no .cbl files in the answer')
            out = {'lists': lists, 'fetched': time.time(), 'truncated': bool(data.get('truncated'))}
            try:
                with open(_cache_file(), 'w') as f:
                    json.dump(out, f)
            except OSError as e:
                logger.fdebug('[CBL-CATALOG] Could not keep the catalog: %s' % e)
            logger.info('[CBL-CATALOG] %s reading lists in %s.' % (len(lists), REPO))
            return dict(out, ok=True)
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.warn('[CBL-CATALOG] Could not get the reading lists from GitHub: %s' % e)
            if cached:
                return dict(cached, ok=True, note='Couldn\'t reach GitHub, so this is the copy from earlier.')
            return {'ok': False, 'lists': [], 'note': 'Couldn\'t get the reading lists from GitHub. Check the log.'}


def fetch(path):
    """(filename, bytes) of one list from the catalog, or (None, note)."""
    known = {x['path'] for x in (_read_cache() or {}).get('lists', [])}
    if path not in known:
        return None, 'That isn\'t a list in the catalog.'
    try:
        r = requests.get(RAW_URL + urllib.parse.quote(path), timeout=30, headers={'User-Agent': 'Issuarr'})
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.warn('[CBL-CATALOG] Could not get %s: %s' % (path, e))
        return None, 'Couldn\'t get that list from GitHub. Check the log.'
    if len(r.content) > MAX_LIST_BYTES:
        return None, 'That list is too big to read.'
    return os.path.basename(path), r.content
