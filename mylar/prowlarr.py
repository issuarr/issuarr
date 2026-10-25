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

"""Indexers from Prowlarr, added as Newznab and Torznab indexers.

Prowlarr serves each of its indexers at <prowlarr>/<id>/api with Prowlarr's own API
key, so its Usenet indexers become Newznab entries and its torrent indexers Torznab
entries. Settings > Search providers lists them to add; with "Keep in sync" on,
indexers turned on in Prowlarr later are added on their own every few hours, and
ones removed or turned off there are turned off here.

Indexers already offered once are remembered (PROWLARR_KNOWN), so one you removed
here isn't added back.
"""

import threading

import requests

import mylar
from mylar import logger

COMICS = 7030           # Newznab/Torznab "Books > Comics"
SYNC_HOURS = 6
SUFFIX = ' (Prowlarr)'

_LOCK = threading.Lock()


def base(url):
    return str(url or '').strip().rstrip('/')


def feed_url(url, indexer_id):
    """The Newznab/Torznab address Prowlarr serves for one indexer."""
    return '%s/%s/api' % (base(url), indexer_id)


def _has_comics(categories):
    for c in categories or []:
        if c.get('id') == COMICS or any(s.get('id') == COMICS for s in c.get('subCategories') or []):
            return True
    return False


def fetch(url, apikey):
    """Prowlarr's indexers: [{'id', 'name', 'protocol' ('usenet'|'torrent'), 'enabled', 'comics'}]."""
    r = requests.get(base(url) + '/api/v1/indexer', headers={'X-Api-Key': apikey or '', 'User-Agent': 'Issuarr'},
                     timeout=30, verify=base(url).startswith('https'))
    r.raise_for_status()
    out = []
    for ix in r.json():
        if ix.get('protocol') not in ('usenet', 'torrent'):
            continue
        out.append({'id': ix['id'], 'name': ix.get('name') or 'Indexer %s' % ix['id'], 'protocol': ix['protocol'],
                    'enabled': bool(ix.get('enable')), 'comics': _has_comics((ix.get('capabilities') or {}).get('categories'))})
    out.sort(key=lambda x: x['name'].lower())
    return out


def _entries(protocol):
    return mylar.CONFIG.EXTRA_NEWZNABS if protocol == 'usenet' else mylar.CONFIG.EXTRA_TORZNABS


def _find(url, indexer_id, protocol):
    want = feed_url(url, indexer_id).lower()
    for n, e in enumerate(_entries(protocol)):
        if base(e[1]).lower() == want:
            return n
    return None


def _known():
    return {x for x in str(getattr(mylar.CONFIG, 'PROWLARR_KNOWN', '') or '').split(',') if x}


def _remember(ids):
    mylar.CONFIG.PROWLARR_KNOWN = ','.join(sorted(_known() | {str(i) for i in ids}, key=lambda x: int(x) if x.isdigit() else 0))


def entry(url, apikey, ix):
    """A provider line for Issuarr's indexer lists: (name, host, verify, apikey, category, enabled, id)."""
    mylar.PROVIDER_START_ID += 1
    verify = '1' if base(url).startswith('https') else '0'
    category = '#%s' % COMICS if ix['protocol'] == 'usenet' else str(COMICS)   # Newznab keeps "uid#categories"
    return (ix['name'] + SUFFIX, feed_url(url, ix['id']), verify, apikey, category, '1', mylar.PROVIDER_START_ID)


def listing(url, apikey):
    """Prowlarr's indexers for Settings, each marked when it's already added here."""
    try:
        indexers = fetch(url, apikey)
    except (requests.exceptions.RequestException, ValueError, KeyError) as e:
        logger.warn('[PROWLARR] Could not list the indexers at %s: %s' % (base(url), e))
        return {'ok': False, 'note': 'Couldn\'t reach Prowlarr at that address with that API key. Check the log.'}
    for ix in indexers:
        ix['added'] = _find(url, ix['id'], ix['protocol']) is not None
    return {'ok': True, 'indexers': indexers}


def add(url, apikey, ids, sync=False):
    """Add the chosen Prowlarr indexers, remember every listed one, and keep the address and key
    for syncing."""
    with _LOCK:
        try:
            indexers = fetch(url, apikey)
        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            logger.warn('[PROWLARR] Could not list the indexers at %s: %s' % (base(url), e))
            return {'ok': False, 'note': 'Couldn\'t reach Prowlarr at that address with that API key. Check the log.'}
        ids = {str(i) for i in ids}
        added = []
        for ix in indexers:
            if str(ix['id']) in ids and _find(url, ix['id'], ix['protocol']) is None:
                _entries(ix['protocol']).append(entry(url, apikey, ix))
                added.append(ix)
        if any(ix['protocol'] == 'usenet' for ix in added):
            mylar.CONFIG.NEWZNAB = True
        if any(ix['protocol'] == 'torrent' for ix in added):
            mylar.CONFIG.ENABLE_TORZNAB = True
        mylar.CONFIG.PROWLARR_URL = base(url)
        mylar.CONFIG.PROWLARR_APIKEY = apikey
        mylar.CONFIG.PROWLARR_SYNC = bool(sync)
        _remember(ix['id'] for ix in indexers)
        mylar.CONFIG.writeconfig()
    logger.info('[PROWLARR] Added %s indexer(s) from Prowlarr: %s' % (len(added), ', '.join(ix['name'] for ix in added) or 'none'))
    return {'ok': True, 'added': len(added),
            'note': 'Added %s indexer%s from Prowlarr.' % (len(added), '' if len(added) == 1 else 's') if added else 'Nothing new to add.'}


def plan(url, apikey, indexers, known):
    """What a sync changes: (indexers to add, entries to turn off as (protocol, position),
    entries whose API key to update as (protocol, position))."""
    to_add, off, rekey = [], [], []
    live = {}
    for ix in indexers:
        pos = _find(url, ix['id'], ix['protocol'])
        live[(ix['protocol'], pos)] = ix
        if pos is None:
            if ix['enabled'] and str(ix['id']) not in known:
                to_add.append(ix)
        elif not ix['enabled'] and str(_entries(ix['protocol'])[pos][5]) == '1':
            off.append((ix['protocol'], pos))
        elif _entries(ix['protocol'])[pos][3] != apikey:
            rekey.append((ix['protocol'], pos))
    prefix = base(url).lower() + '/'
    for protocol in ('usenet', 'torrent'):
        for pos, e in enumerate(_entries(protocol)):
            if base(e[1]).lower().startswith(prefix) and (protocol, pos) not in live and str(e[5]) == '1':
                off.append((protocol, pos))   # gone from Prowlarr
    return to_add, off, rekey


def sync():
    """Bring the Prowlarr indexers here up to date. Runs every few hours while Keep in sync is on."""
    url, apikey = getattr(mylar.CONFIG, 'PROWLARR_URL', None), getattr(mylar.CONFIG, 'PROWLARR_APIKEY', None)
    if not (getattr(mylar.CONFIG, 'PROWLARR_SYNC', False) and url and apikey):
        return None
    with _LOCK:
        try:
            indexers = fetch(url, apikey)
        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            logger.warn('[PROWLARR] Could not sync the indexers from %s: %s' % (base(url), e))
            return None
        to_add, off, rekey = plan(url, apikey, indexers, _known())
        for protocol, pos in rekey:
            e = list(_entries(protocol)[pos])
            e[3] = apikey
            _entries(protocol)[pos] = tuple(e)
        for protocol, pos in off:
            e = list(_entries(protocol)[pos])
            e[5] = '0'
            _entries(protocol)[pos] = tuple(e)
        for ix in to_add:
            _entries(ix['protocol']).append(entry(url, apikey, ix))
        _remember(ix['id'] for ix in indexers)
        if to_add or off or rekey:
            mylar.CONFIG.writeconfig()
            logger.info('[PROWLARR] Synced: %s added, %s turned off, %s with a new API key.' % (len(to_add), len(off), len(rekey)))
    return {'added': len(to_add), 'off': len(off), 'rekey': len(rekey)}
