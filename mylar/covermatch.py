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

"""Telling whether a comic is the issue it's taken for by its front cover, the way ComicTagger's
automatic identification does. Each cover is shrunk to an 8x8 grey average hash, and the number
of its 64 bits that differ from another cover's is their distance: 0 is the same picture, and
unrelated covers are around 32 apart. ComicTagger calls 16 or less a match and 8 or less almost
certainly the same image.

Covers come from the caches Needs attention already keeps (the file's own cover, and the issue's
cover URL stored with the series), so checking an issue Issuarr already picked costs no
ComicVine API request, only the image download the first time.
"""

import os
import threading

import mylar
from mylar import logger

DEFAULT_SCORE = 16
STRONG = 8            # almost certainly the same image
GAP = 4               # how far the best cover must be ahead of the next one to stand alone
MISMATCH_MARGIN = 8   # this far past the pass score, the cover is another issue's
BORDER_CROP = 10      # percent of black border worth cropping off, as ComicTagger
BUSY_TRIES = 6

_HASHES = {}          # (image path, size, mtime) -> [hash, ...]
_SCORED = {}          # (file path, size, mtime, issueid) -> distance or None
_LOCK = threading.Lock()


def pass_score():
    """The largest distance that still counts as a match (Settings > Post-processing)."""
    try:
        v = int(getattr(mylar.CONFIG, 'COVER_MATCH_SCORE', DEFAULT_SCORE))
    except (TypeError, ValueError):
        v = DEFAULT_SCORE
    return max(4, min(v, 32))


def strict():
    return bool(getattr(mylar.CONFIG, 'COVER_MATCH_STRICT', False))


def average_hash(im):
    """ComicTagger's average hash, so its thresholds mean the same here."""
    from PIL import Image
    im = im.resize((8, 8), Image.Resampling.LANCZOS).convert('L')
    px = list(im.tobytes())
    avg = sum(px) / float(len(px))
    h = 0
    for i, p in enumerate(px):
        if p > avg:
            h |= 1 << (len(px) - 1 - i)
    return h


def distance(a, b):
    return bin(a ^ b).count('1')


def _crop_border(im):
    from PIL import Image, ImageChops
    rgb = im.convert('RGB')
    diff = ImageChops.difference(rgb, Image.new('RGB', rgb.size, 'black'))
    bbox = ImageChops.add(diff, diff, 2.0, -100).getbbox()
    if not bbox:
        return None
    wide = int(100 - (bbox[2] - bbox[0]) * 100.0 / im.width)
    high = int(100 - (bbox[3] - bbox[1]) * 100.0 / im.height)
    return im.crop(bbox) if wide > BORDER_CROP or high > BORDER_CROP else None


def image_hashes(path, local=False):
    """Hashes of the image at path. A file's own cover (local) also gets its right half when it's
    a two-page spread, and a copy without its black border, as ComicTagger tries."""
    try:
        st = os.stat(path)
    except OSError:
        return []
    key = (path, st.st_size, st.st_mtime, local)
    if key in _HASHES:
        return _HASHES[key]
    from PIL import Image
    try:
        with Image.open(path) as im:
            im.load()
            images = [im]
            if local:
                if im.width > im.height:
                    images.append(im.crop((im.width // 2, 0, im.width, im.height)))
                cropped = _crop_border(im)
                if cropped is not None:
                    images.append(cropped)
            out = [average_hash(i) for i in images]
    except Exception as e:
        logger.fdebug('[COVER-MATCH] Could not read the image %s: %s' % (path, e))
        out = []
    with _LOCK:
        if len(_HASHES) > 5000:
            _HASHES.clear()
        _HASHES[key] = out
    return out


def _wait(fn, *args):
    """A cover from the Needs attention caches, waiting for a free slot when they're busy."""
    from mylar import attention
    for _ in range(BUSY_TRIES):
        out = fn(*args)
        if out != attention.BUSY:
            return out
    return None


def _file_key(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (path, st.st_size, st.st_mtime)


def issue_distance(path, issueid, fetch=True):
    """How far the file's front cover is from the issue's cover on ComicVine, or None when either
    cover can't be had. Without fetch, only what's been worked out before."""
    fkey = _file_key(path)
    if fkey is None or not issueid:
        return None
    key = fkey + (str(issueid),)
    if key in _SCORED or not fetch:
        return _SCORED.get(key)
    from mylar import attention
    d = None
    mine = _wait(attention.cover_of, path)
    theirs = _wait(attention.issue_cover, issueid) if mine else None
    if mine and theirs:
        local, remote = image_hashes(mine, local=True), image_hashes(theirs)
        if local and remote:
            d = min(distance(a, b) for a in local for b in remote)
    if d is not None:
        # a missing cover isn't kept: the caches remember those themselves, and may get it later
        with _LOCK:
            if len(_SCORED) > 20000:
                _SCORED.clear()
            _SCORED[key] = d
    return d


def verdict(d):
    """'match', 'mismatch', 'unsure' (close, not close enough) or 'unknown' (no cover to compare)."""
    if d is None:
        return 'unknown'
    if d <= pass_score():
        return 'match'
    if d >= pass_score() + MISMATCH_MARGIN:
        return 'mismatch'
    return 'unsure'


def check(path, issueid):
    d = issue_distance(path, issueid)
    return {'distance': d, 'verdict': verdict(d)}


def may_file(result):
    """Whether filing goes ahead after a cover check. Normally only a clear mismatch stops it;
    with "Issues must match by cover" on, anything short of a match does."""
    v = result['verdict']
    return v == 'match' if strict() else v != 'mismatch'


def annotate(path, matches, fetch=False):
    """The candidate issues with how each one's cover compares ('cover': {distance, verdict}),
    those whose cover matches first. Without fetch, only covers compared before are used, so a
    page can show them without waiting on downloads."""
    out = []
    for m in matches or []:
        m = dict(m)
        if m.get('issueid'):
            d = issue_distance(path, m['issueid'], fetch=fetch)
            m['cover'] = {'distance': d, 'verdict': verdict(d)}
        out.append(m)
    bonus = {'match': 1.0, 'mismatch': -0.5}
    out.sort(key=lambda m: -((m.get('rank') or 0) + bonus.get((m.get('cover') or {}).get('verdict'), 0)
                             + (0.2 if ((m.get('cover') or {}).get('distance') or 99) <= STRONG else 0)))
    return out


def winner(matches):
    """The one candidate whose cover matches, with no other candidate's cover within GAP of it,
    or None."""
    scored = sorted((m for m in matches if (m.get('cover') or {}).get('distance') is not None),
                    key=lambda m: m['cover']['distance'])
    if not scored or scored[0]['cover']['verdict'] != 'match':
        return None
    best = scored[0]['cover']['distance']
    if any(m['cover']['distance'] <= best + GAP for m in scored[1:]):
        return None
    return scored[0]
