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

"""Tools > Library check: comic files in the library that are damaged, or that hold another
archive instead of pages.

Every file in every series folder is opened and each entry read back (zip CRCs; rar
through unrar when it's installed). A file is listed when it won't open, isn't a comic
archive at all (an error page saved as .cbz, say), has no pages, or wraps a single .cbz
or .cbr in place of its pages. Results are remembered per file, so a second run only
opens files that changed.

From the list a wrapped file can be unwrapped in place (its own ComicInfo.xml kept), and
a damaged one can be swapped for a new download: the file goes to the trash and the
issue is marked Wanted. Nothing happens to a file until you choose.

The check also notes which issue files have no ComicInfo.xml. Readers that group by it
(Kavita, Komga) list those apart from the series' tagged issues. Tag untagged files writes
one into each from the stored issue info (mylar.quicktag), without asking ComicVine. A .cbr
is made a .cbz first, since only a zip can hold one.
"""

import datetime
import os
import shutil
import threading
import zipfile

# Issuarr puts lib/ ahead of site-packages, so a bare "import rarfile" finds the empty lib/rarfile package
from lib.rarfile import rarfile

import mylar
from mylar import db, logger, quicktag

STATE = {'state': 'idle', 'done': 0, 'total': 0, 'opened': 0, 'trusted': 0, 'finished': None, 'stop': False, 'error': None}
TAGGING = {'state': 'idle', 'done': 0, 'total': 0, 'tagged': 0, 'failed': 0, 'finished': None, 'stop': False}
_LOCK = threading.Lock()

IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif', '.jxl')
COMIC_EXT = ('.cbz', '.cbr', '.cb7', '.zip', '.rar')
MIN_PAGES = 3
ZIP_MAGIC = b'PK\x03\x04'
RAR_MAGIC = b'Rar!\x1a\x07'
OTHER_MAGIC = (b'%PDF', b'7z\xbc\xaf\x27\x1c')


def ensure(myDB=None):
    myDB = myDB or db.DBConnection()
    myDB.action('CREATE TABLE IF NOT EXISTS library_check (path TEXT PRIMARY KEY, size INTEGER, mtime REAL, status TEXT, '
                'detail TEXT, comicid TEXT, issueid TEXT, inner TEXT, checked TEXT)')
    if 'tagged' not in [r['name'] for r in myDB.select('PRAGMA table_info(library_check)')]:
        myDB.action('ALTER TABLE library_check ADD COLUMN tagged INTEGER')


def _entries(arc):
    test = lambda i: bool((getattr(i, 'is_dir', None) or getattr(i, 'isdir'))())
    return [i for i in arc.infolist() if not test(i)]


def check_file(path):
    """(status, detail, inner): status is 'ok', 'damaged', 'nested' or 'unchecked'; inner is
    the wrapped archive's name for a nested file."""
    try:
        with open(path, 'rb') as f:
            head = f.read(8)
    except OSError as e:
        return 'damaged', 'Can\'t be read: %s' % e, None
    if head.startswith(OTHER_MAGIC):
        return 'ok', '', None    # PDF and 7z aren't checked
    try:
        if head.startswith(ZIP_MAGIC):
            arc = zipfile.ZipFile(path)
            with arc:
                bad = arc.testzip()
                if bad is not None:
                    return 'damaged', 'Damaged inside (%s).' % bad, None
                entries = _entries(arc)
        elif head.startswith(RAR_MAGIC):
            arc = rarfile.RarFile(path)
            with arc:
                arc.testrar()
                entries = _entries(arc)
        else:
            return 'damaged', 'Not a comic archive (it may be an error page saved under a comic name).', None
    except rarfile.RarCannotExec:
        return 'unchecked', 'A .cbr can only be checked when unrar is installed.', None
    except (zipfile.BadZipFile, rarfile.Error, EOFError, OSError, RuntimeError, ValueError) as e:
        return 'damaged', 'Won\'t open: %s' % e, None
    names = [e.filename for e in entries]
    pages = [n for n in names if n.lower().endswith(IMAGE_EXT)]
    inner = [n for n in names if n.lower().endswith(COMIC_EXT)]
    if inner and len(pages) < MIN_PAGES:
        if len(inner) == 1:
            return 'nested', 'Holds %s instead of pages.' % os.path.basename(inner[0]), inner[0]
        return 'nested', 'Holds %s comic files instead of pages, so it may be a pack.' % len(inner), None
    if len(pages) < MIN_PAGES:
        return 'damaged', 'Has %s page%s.' % (len(pages), '' if len(pages) == 1 else 's'), None
    return 'ok', '', None


def _stat(path):
    st = os.stat(path)
    return st.st_size, st.st_mtime


def scan():
    with _LOCK:
        if STATE['state'] == 'running' or TAGGING['state'] == 'running':
            return False
        STATE.update(state='running', done=0, total=0, opened=0, trusted=0, finished=None, stop=False, error=None)
    threading.Thread(target=_scan, name='LIBRARY-CHECK', daemon=True).start()
    return True


# WebP conversion reads every entry of a zip (which checks each CRC) when it converts it, or
# when it tries and finds nothing worth saving. While the file is unchanged since, that read
# stands in for opening it again here. Files skipped as already WebP or with no pages weren't read.
WEBP_READ = ('nothing to gain',)
WEBP_READ_REASONS = ('nothing to gain', 'saves less than')


def _webp_reads(myDB):
    """{path: (size, mtime, status, detail)} for files WebP read through, or found damaged."""
    from mylar import webp
    out = {}
    try:
        rows = webp.remembered(myDB)
    except Exception as e:
        logger.fdebug('[LIBRARY-CHECK] Unable to read what WebP remembers: %s' % e)
        return out
    for path, r in rows.items():
        reason = r.get('reason') or ''
        if r['status'] == 'converted' or (r['status'] in WEBP_READ and reason.startswith(WEBP_READ_REASONS)):
            out[path] = (r['size'], r['mtime'], 'ok', '')
        elif r['status'] == 'damaged':
            out[path] = (r['size'], r['mtime'], 'damaged', 'Found while converting to WebP: %s.' % (reason or 'damaged'))
    return out


def _scan():
    from mylar import matching
    try:
        myDB = db.DBConnection()
        ensure(myDB)
        known = {r['path']: r for r in myDB.select('SELECT path, size, mtime, status, tagged FROM library_check')}
        webp_read = _webp_reads(myDB)
        comics = myDB.select('SELECT * FROM comics WHERE ComicLocation IS NOT NULL ORDER BY ComicSortName')
        work = []
        for c in comics:
            linked = {r['Location']: r['IssueID'] for r in myDB.select(
                "SELECT IssueID, Location FROM issues WHERE ComicID=? AND Location IS NOT NULL AND Status='Downloaded'", [c['ComicID']])}
            for f in matching.walk(matching.series_dirs(c)):
                work.append((f['path'], c['ComicID'], linked.get(f['name'])))
        STATE['total'] = len(work)
        seen = set()
        for path, comicid, issueid in work:
            if STATE['stop']:
                break
            seen.add(path)
            STATE['done'] += 1
            try:
                size, mtime = _stat(path)
            except OSError:
                continue
            row = known.get(path)
            if row and row['size'] == size and row['mtime'] == mtime:
                tagged = row['tagged']
                if tagged is None and row['status'] == 'ok':
                    tagged = int(quicktag.tagged(path))   # checked before tags were noted
                myDB.action('UPDATE library_check SET comicid=?, issueid=?, tagged=? WHERE path=?', [comicid, issueid, tagged, path])
                continue
            read = webp_read.get(path)
            if read and read[:2] == (size, mtime):
                status, detail, inner = read[2], read[3], None
                STATE['trusted'] += 1
            else:
                try:
                    status, detail, inner = check_file(path)
                except Exception as e:
                    logger.warn('[LIBRARY-CHECK] Unable to check %s: %s' % (path, e))
                    status, detail, inner = 'unchecked', 'Couldn\'t be checked: %s' % e, None
                STATE['opened'] += 1
            myDB.upsert('library_check', {'size': size, 'mtime': mtime, 'status': status, 'detail': detail, 'inner': inner,
                                          'comicid': comicid, 'issueid': issueid,
                                          'tagged': int(quicktag.tagged(path)) if status == 'ok' else None,
                                          'checked': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}, {'path': path})
        if not STATE['stop']:
            for path in set(known) - seen:
                myDB.action('DELETE FROM library_check WHERE path=?', [path])
        logger.info('[LIBRARY-CHECK] Checked %s files (%s opened, %s already read through by WebP).' % (
            STATE['done'], STATE['opened'], STATE['trusted']))
    except Exception as e:
        logger.warn('[LIBRARY-CHECK] Stopped: %s' % e)
        STATE['error'] = '%s: %s' % (type(e).__name__, e)
    finally:
        STATE.update(state='done', finished=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))


def stop():
    STATE['stop'] = True


def status():
    out = {k: STATE[k] for k in ('state', 'done', 'total', 'opened', 'trusted', 'finished', 'error')}
    myDB = db.DBConnection()
    ensure(myDB)
    rows = myDB.select("SELECT l.*, c.ComicName, c.ComicYear, i.Issue_Number FROM library_check l "
                       "LEFT JOIN comics c ON c.ComicID=l.comicid LEFT JOIN issues i ON i.IssueID=l.issueid "
                       "WHERE l.status IN ('damaged', 'nested') ORDER BY c.ComicSortName, l.path")
    out['files'] = [{'path': r['path'], 'name': os.path.basename(r['path']), 'status': r['status'], 'detail': r['detail'],
                     'comicid': r['comicid'], 'issueid': r['issueid'], 'series': r['ComicName'], 'year': r['ComicYear'],
                     'number': r['Issue_Number'], 'unwrap': r['status'] == 'nested' and bool(r['inner']),
                     'size': r['size']} for r in rows if os.path.isfile(r['path'])]
    out['unchecked'] = myDB.select("SELECT COUNT(*) AS n FROM library_check WHERE status='unchecked'")[0]['n']
    out['checked'] = myDB.select('SELECT COUNT(*) AS n FROM library_check')[0]['n']
    out['untagged'] = myDB.select("SELECT COUNT(*) AS n FROM library_check WHERE status='ok' AND tagged=0 AND issueid IS NOT NULL")[0]['n']
    out['untagged_series'] = myDB.select("SELECT COUNT(DISTINCT comicid) AS n FROM library_check WHERE status='ok' AND tagged=0 AND issueid IS NOT NULL")[0]['n']
    out['tagging'] = {k: TAGGING[k] for k in ('state', 'done', 'total', 'tagged', 'failed', 'finished')}
    return out


def tag_untagged():
    """Start writing a ComicInfo.xml into every checked issue file that has none."""
    with _LOCK:
        if TAGGING['state'] == 'running' or STATE['state'] == 'running':
            return False
        TAGGING.update(state='running', done=0, total=0, tagged=0, failed=0, finished=None, stop=False)
    threading.Thread(target=_tag, name='TAG-UNTAGGED', daemon=True).start()
    return True


def stop_tagging():
    TAGGING['stop'] = True


def _tag():
    from mylar import webp
    try:
        myDB = db.DBConnection()
        ensure(myDB)
        rows = myDB.select("SELECT path, size, mtime FROM library_check WHERE status='ok' AND tagged=0 AND issueid IS NOT NULL ORDER BY path")
        TAGGING['total'] = len(rows)
        for row in rows:
            if TAGGING['stop']:
                break
            TAGGING['done'] += 1
            path = row['path']
            try:
                if _stat(path) != (row['size'], row['mtime']):
                    continue    # changed since the check; the next check looks again
            except OSError:
                continue
            new = quicktag.fill(path, myDB, force=True)   # a .cbr comes back as its new .cbz
            ok = new is not None
            if ok and new != path:
                myDB.action('DELETE FROM library_check WHERE path=?', [new])
                myDB.action('UPDATE library_check SET path=? WHERE path=?', [new, path])
                path = new
            if ok:
                size, mtime = _stat(path)
                myDB.action('UPDATE library_check SET size=?, mtime=?, tagged=1 WHERE path=?', [size, mtime, path])
                webp._update_size(path, size)
                TAGGING['tagged'] += 1
            else:
                TAGGING['failed'] += 1
        logger.info('[LIBRARY-CHECK] Tagged %s of %s untagged files (%s couldn\'t be tagged).' % (
            TAGGING['tagged'], TAGGING['total'], TAGGING['failed']))
    except Exception as e:
        logger.warn('[LIBRARY-CHECK] Tagging stopped: %s' % e)
    finally:
        TAGGING.update(state='done', finished=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))


def _row(myDB, path):
    ensure(myDB)
    return myDB.selectone('SELECT * FROM library_check WHERE path=?', [path]).fetchone()


def _trash(path):
    from mylar import attention
    dest_dir = os.path.join(attention.trash_dir(), datetime.date.today().isoformat())
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(path))
    if os.path.exists(dest):
        stem, ext = os.path.splitext(dest)
        dest = '%s (%s)%s' % (stem, int(datetime.datetime.now().timestamp()), ext)
    shutil.move(path, dest)
    return dest


def unwrap(path):
    """Replace a file that wraps one comic archive with that comic's pages, as a .cbz. Its own
    ComicInfo.xml is kept when the inner comic has none. The original goes to the trash."""
    from mylar import matching
    myDB = db.DBConnection()
    row = _row(myDB, path)
    if row is None or row['status'] != 'nested' or not row['inner'] or not os.path.isfile(path):
        return {'ok': False, 'note': 'That file isn\'t one listed to unwrap.'}
    folder = os.path.dirname(path)
    inner_tmp = os.path.join(folder, '.issuarr-unwrap-inner')
    out_tmp = os.path.join(folder, '.issuarr-unwrap.cbz')
    try:
        outer = zipfile.ZipFile(path) if zipfile.is_zipfile(path) else rarfile.RarFile(path)
        with outer:
            outer_names = [e.filename for e in _entries(outer)]
            info = next((n for n in outer_names if os.path.basename(n).lower() == 'comicinfo.xml'), None)
            outer_info = outer.read(info) if info else None
            with outer.open(row['inner']) as src, open(inner_tmp, 'wb') as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
        inner = zipfile.ZipFile(inner_tmp) if zipfile.is_zipfile(inner_tmp) else rarfile.RarFile(inner_tmp)
        with inner, zipfile.ZipFile(out_tmp, 'w') as out:
            names = []
            for e in _entries(inner):
                kind = zipfile.ZIP_DEFLATED if e.filename.lower().endswith('.xml') else zipfile.ZIP_STORED
                stamp = tuple(getattr(e, 'date_time', None) or ())[:6]
                if len(stamp) < 6 or stamp[0] < 1980:
                    stamp = (1980, 1, 1, 0, 0, 0)
                out.writestr(zipfile.ZipInfo(e.filename, date_time=stamp), inner.read(e.filename), compress_type=kind)
                names.append(os.path.basename(e.filename).lower())
            if outer_info and 'comicinfo.xml' not in names:
                out.writestr('ComicInfo.xml', outer_info, compress_type=zipfile.ZIP_DEFLATED)
        status, detail, _ = check_file(out_tmp)
        if status != 'ok':
            raise ValueError('the unwrapped comic didn\'t check out: %s' % detail)
    except Exception as e:
        if os.path.exists(out_tmp):
            os.remove(out_tmp)
        if isinstance(e, rarfile.RarCannotExec):
            return {'ok': False, 'note': 'This one needs unrar, which isn\'t installed.'}
        logger.warn('[LIBRARY-CHECK] Could not unwrap %s: %s' % (path, e))
        return {'ok': False, 'note': 'Couldn\'t unwrap it: %s' % e}
    finally:
        if os.path.exists(inner_tmp):
            os.remove(inner_tmp)
    final = os.path.splitext(path)[0] + '.cbz'
    if final != path and os.path.exists(final):
        os.remove(out_tmp)
        return {'ok': False, 'note': '%s already exists next to it.' % os.path.basename(final)}
    trashed = _trash(path)
    os.replace(out_tmp, final)
    if final != path and row['comicid']:
        myDB.action('UPDATE issues SET Location=? WHERE ComicID=? AND Location=?',
                    [os.path.basename(final), row['comicid'], os.path.basename(path)])
    myDB.action('DELETE FROM library_check WHERE path=?', [path])
    logger.info('[LIBRARY-CHECK] Unwrapped %s (original in %s).' % (os.path.basename(final), trashed))
    if row['comicid']:
        matching._rescan(row['comicid'])
    return {'ok': True, 'note': 'Unwrapped %s. The original is in the trash.' % os.path.basename(final)}


def redownload(path):
    """Send a damaged file to the trash and mark its issue Wanted so it's searched for again."""
    from mylar import matching
    myDB = db.DBConnection()
    row = _row(myDB, path)
    if row is None or row['status'] not in ('damaged', 'nested') or not os.path.isfile(path):
        return {'ok': False, 'note': 'That file isn\'t one listed here.'}
    if not row['issueid']:
        return {'ok': False, 'note': 'That file isn\'t matched to an issue, so there\'s nothing to search for. Use Remove instead.'}
    _trash(path)
    myDB.action('DELETE FROM library_check WHERE path=?', [path])
    if row['comicid']:
        matching._rescan(row['comicid'])
    myDB.upsert('issues', {'Status': 'Wanted'}, {'IssueID': row['issueid']})
    logger.info('[LIBRARY-CHECK] %s went to the trash; issue %s is Wanted again.' % (os.path.basename(path), row['issueid']))
    return {'ok': True, 'note': '%s is in the trash and the issue is Wanted, so the next search looks for it.' % os.path.basename(path)}


def remove(path):
    """Send a listed file to the trash without searching again."""
    from mylar import matching
    myDB = db.DBConnection()
    row = _row(myDB, path)
    if row is None or row['status'] not in ('damaged', 'nested') or not os.path.isfile(path):
        return {'ok': False, 'note': 'That file isn\'t one listed here.'}
    _trash(path)
    myDB.action('DELETE FROM library_check WHERE path=?', [path])
    if row['comicid']:
        matching._rescan(row['comicid'])
    return {'ok': True, 'note': '%s is in the trash.' % os.path.basename(path)}
