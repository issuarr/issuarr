"""Tag the library's untagged issue files on their own, while "Write metadata into files" is on.

Imports and WebP conversion tag a file as they handle it. This catches the rest: files that were
already in the library, put there by hand, or tagged with tagging off. The scheduler looks in
every hour; a pass goes over every issue file, reading only each zip's list of contents, and
writes a ComicInfo.xml from the stored issue info into the ones that have none (mylar.quicktag,
no ComicVine requests). Files are remembered by size and time, so later passes only open files
that changed. A pass gives way to filing and on-import conversion, and picks up next time.
"""

import datetime
import os
import threading

import mylar
from mylar import db, logger, quicktag

TICK = 60      # minutes between the scheduler's looks
STATE = {'state': 'idle', 'done': 0, 'total': 0, 'opened': 0, 'tagged': 0, 'failed': 0, 'finished': None}
_LOCK = threading.Lock()


def ensure(myDB=None):
    myDB = myDB or db.DBConnection()
    myDB.action('CREATE TABLE IF NOT EXISTS autotag_files (path TEXT PRIMARY KEY, size INTEGER, mtime REAL, status TEXT)')
    return myDB


def tick():
    """The scheduler's look-in: starts a pass in the background when tagging is on."""
    if not mylar.CONFIG.ENABLE_META:
        return False
    with _LOCK:
        if STATE['state'] == 'running':
            return False
        STATE['state'] = 'running'
    threading.Thread(target=run, name='AUTO-TAG', daemon=True).start()
    return True


def _busy():
    from mylar import webp
    try:
        return webp.busy_elsewhere()
    except Exception:
        return ''


def _remember(myDB, path, status):
    try:
        st = os.stat(path)
    except OSError:
        return
    myDB.upsert('autotag_files', {'size': st.st_size, 'mtime': st.st_mtime, 'status': status}, {'path': path})


def run(busy=None):
    """One pass over every issue file. Returns why it stopped (for the log and tests)."""
    busy = busy or _busy
    why = 'finished'
    STATE.update(state='running', done=0, total=0, opened=0, tagged=0, failed=0)
    try:
        myDB = ensure()
        known = {r['path']: r for r in myDB.select('SELECT * FROM autotag_files')}
        files = myDB.select("SELECT c.ComicLocation, i.Location FROM issues i JOIN comics c ON c.ComicID=i.ComicID "
                            "WHERE i.Location IS NOT NULL AND c.ComicLocation IS NOT NULL ORDER BY c.ComicSortName, i.Location")
        STATE['total'] = len(files)
        for f in files:
            if not mylar.CONFIG.ENABLE_META:
                why = 'tagging was turned off'
                break
            elsewhere = busy()
            if elsewhere:
                why = 'gave way: %s' % elsewhere
                break
            STATE['done'] += 1
            path = os.path.join(f['ComicLocation'], f['Location'])
            try:
                st = os.stat(path)
            except OSError:
                continue
            row = known.get(path)
            if row and (row['size'], row['mtime']) == (st.st_size, st.st_mtime):
                continue
            STATE['opened'] += 1
            if quicktag.tagged(path):
                _remember(myDB, path, 'tagged')
                continue
            new = quicktag.fill(path, myDB)
            if new:
                STATE['tagged'] += 1
                _remember(myDB, new, 'tagged')
                from mylar import webp
                webp._update_size(new, os.path.getsize(new))
            else:
                STATE['failed'] += 1
                _remember(myDB, path, 'not tagged')   # tried again once the file changes
        logger.info('[AUTO-TAG] Looked at %s of %s issue files (%s opened): %s tagged, %s couldn\'t be tagged. %s.' % (
            STATE['done'], STATE['total'], STATE['opened'], STATE['tagged'], STATE['failed'], why.capitalize()))
    except Exception as e:
        why = 'stopped: %s' % e
        logger.warn('[AUTO-TAG] Stopped: %s' % e)
    finally:
        STATE.update(state='idle', finished=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))
    return why
