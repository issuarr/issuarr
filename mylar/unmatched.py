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

"""Comic files in the library that no issue points to, for the Library's Unmatched tab.

Built from the files library scans saw (the library_files table), so it is as fresh as the
last scan. Files in work folders (_*, .*, the duplicates dump, review and trash), story arc and
Grabbag folders are left out, and so are files you ignore until they change.
"""

import os
import threading
import time

import mylar
from mylar import db, importchoice, logger

CHECK_EVERY = 60        # seconds the list is reused before the database and disk are read again
_CACHE = {'at': 0, 'files': None}
_LOCK = threading.Lock()


def _norm(path):
    return os.path.normpath(path) if path and path != 'None' else None


def roots():
    """The library folder and the second library folder, when set."""
    out = []
    for p in (mylar.CONFIG.DESTINATION_DIR, mylar.CONFIG.MULTIPLE_DEST_DIRS):
        p = _norm(p)
        if p and p not in out:
            out.append(p)
    return out


def left_out():
    """Folders no series is meant to own: work folders, story arcs and Grabbag."""
    from mylar import librarysync
    out = list(librarysync.work_folders())
    out.append(_norm(mylar.CONFIG.STORYARC_LOCATION))
    out.append(_norm(mylar.CONFIG.GRABBAG_DIR))
    return [p for p in out if p]


def _under(path, folder):
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def _root_of(path, tops):
    return next((t for t in tops if _under(path, t)), None)


def skipped(path, root, out):
    """True when the file sits in a folder the Unmatched tab leaves out."""
    rel = os.path.relpath(os.path.dirname(path), root)
    if rel != '.' and any(part.startswith(('_', '.')) for part in rel.split(os.sep)):
        return True
    return any(_under(path, o) for o in out)


def _ignored(myDB):
    return dict((r['Path'], (r['Size'], r['Mtime'])) for r in myDB.select('SELECT Path, Size, Mtime FROM unmatched_ignored'))


def _extensions():
    return tuple('.' + x.lower() for x in ('cbz', 'cbr', 'cb7', 'cbt', 'pdf'))


def files(force=False):
    """Every unmatched file still on disk: path, folder, name, size and modified time."""
    with _LOCK:
        if not force and _CACHE['files'] is not None and time.time() - _CACHE['at'] < CHECK_EVERY:
            return _CACHE['files']
    tops = roots()
    out_dirs = left_out()
    myDB = db.DBConnection()
    tied = importchoice._tied_paths(myDB)
    ignored = _ignored(myDB)
    ext = _extensions()
    found = []
    for r in myDB.select('SELECT Path FROM library_files'):
        path = os.path.normpath(r['Path'])
        if path in tied or not path.lower().endswith(ext):
            continue
        root = _root_of(path, tops)
        if root is None or skipped(path, root, out_dirs):
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        if ignored.get(path) == (st.st_size, st.st_mtime):
            continue
        found.append({'path': path, 'folder': os.path.dirname(path), 'name': os.path.basename(path),
                      'root': root, 'size': st.st_size, 'mtime': st.st_mtime})
    with _LOCK:
        _CACHE.update(at=time.time(), files=found)
    return found


def forget():
    with _LOCK:
        _CACHE.update(at=0, files=None)


def _owners(myDB):
    owners = {}
    for r in myDB.select('SELECT ComicID, ComicName, ComicYear, ComicLocation FROM comics WHERE ComicLocation IS NOT NULL'):
        loc = _norm(r['ComicLocation'])
        if loc:
            owners.setdefault(loc, []).append({'id': r['ComicID'], 'name': r['ComicName'], 'year': r['ComicYear']})
    return owners


def owner_of(folder, owners, root):
    """The series whose folder this is, or the nearest series folder above it."""
    here = folder
    while here and _under(here, root):
        if here in owners:
            return owners[here], here != folder
        if here == root:
            break
        here = os.path.dirname(here)
    return [], False


def folders():
    """One entry per folder with unmatched files, for the Library cards."""
    myDB = db.DBConnection()
    owners = _owners(myDB)
    groups = {}
    for f in files():
        groups.setdefault(f['folder'], []).append(f)
    out = []
    for folder, fs in groups.items():
        root = fs[0]['root']
        rel = os.path.relpath(folder, root)
        series, above = owner_of(folder, owners, root)
        fs.sort(key=lambda f: f['name'].lower())
        out.append({'folder': folder, 'rel': '' if rel == '.' else rel.replace(os.sep, '/'),
                    'count': len(fs), 'size': sum(f['size'] for f in fs), 'first': fs[0]['path'],
                    'publisher': rel.split(os.sep)[0] if rel != '.' and os.sep in rel else '',
                    'series': series, 'series_above': above})
    out.sort(key=lambda g: g['rel'].lower())
    return out


def _import_rows(myDB, paths):
    rows = {}
    for path in paths:
        r = myDB.selectone('SELECT Status, ComicID, DynamicName, Volume, SRID FROM importresults WHERE ComicLocation=?', [path]).fetchone()
        if r is not None:
            rows[path] = dict(r)
    return rows


def folder(path):
    """The unmatched files of one folder, each with what its name reads as, the closest
    watchlist series and what Import results knows about it. None when the folder has none."""
    from mylar import attention
    path = _norm(path)
    fs = sorted([f for f in files() if f['folder'] == path], key=lambda f: f['name'].lower())
    if not fs:
        return None
    myDB = db.DBConnection()
    root = fs[0]['root']
    series, above = owner_of(path, _owners(myDB), root)
    imports = _import_rows(myDB, [f['path'] for f in fs])
    items = []
    for f in fs:
        parsed = attention.parse(f['path'])
        try:
            near = attention.suggest(parsed, limit=1)
        except Exception as e:
            logger.fdebug('[UNMATCHED] No suggestion for %s: %s' % (f['name'], e))
            near = []
        items.append({'path': f['path'], 'name': f['name'], 'size': f['size'], 'mtime': round(f['mtime']),
                      'reads_as': {'series': parsed.get('series'), 'issue': parsed.get('issue'), 'year': parsed.get('year'),
                                   'collected': bool(parsed.get('collected'))},
                      'near': near[0] if near else None,
                      'import': imports.get(f['path'])})
    rel = os.path.relpath(path, root)
    return {'folder': path, 'rel': '' if rel == '.' else rel.replace(os.sep, '/'), 'series': series,
            'series_above': above, 'files': items}


def is_unmatched(path):
    path = _norm(path)
    return any(f['path'] == path for f in files())


def ignore(path, on=True):
    """Hide a file from the Unmatched tab until its size or time changes, or show it again."""
    path = _norm(path)
    myDB = db.DBConnection()
    if not on:
        myDB.action('DELETE FROM unmatched_ignored WHERE Path=?', [path])
        forget()
        return {'ok': True}
    if not is_unmatched(path):
        return {'ok': False, 'note': 'That file isn\'t on the Unmatched list.'}
    st = os.stat(path)
    myDB.action('INSERT OR REPLACE INTO unmatched_ignored (Path, Size, Mtime) VALUES (?, ?, ?)', [path, st.st_size, st.st_mtime])
    forget()
    return {'ok': True}


def cover(path):
    """The front cover of an unmatched file (see attention.cover_of), or None."""
    from mylar import attention
    return attention.cover_of(_norm(path)) if is_unmatched(path) else None


def _comic(comicid):
    return db.DBConnection().selectone('SELECT ComicID, ComicName, ComicYear, ComicLocation FROM comics WHERE ComicID=?', [comicid]).fetchone()


def _work_place(folder):
    """True for a folder nothing may be matched or moved into: a work folder, story arcs or Grabbag."""
    folder = _norm(folder)
    root = _root_of(folder, roots())
    if root is not None and folder != root:
        if any(part.startswith(('_', '.')) for part in os.path.relpath(folder, root).split(os.sep)):
            return True
    return any(_under(folder, o) for o in left_out())


def plan(paths, comicid):
    """What matching these unmatched files to a series does before anything moves: the files
    that move into its folder, the ones already there, and the ones that can't."""
    from mylar import matching
    comic = _comic(comicid)
    if comic is None or not comic['ComicLocation']:
        return {'ok': False, 'note': 'That series isn\'t on your watchlist, or has no folder yet.'}
    dest = _norm(comic['ComicLocation'])
    if _work_place(dest):
        return {'ok': False, 'note': '%s\'s folder is a work folder (%s). Nothing is matched into it; fix the series\' folder first.' % (comic['ComicName'], dest)}
    listed = {f['path'] for f in files(force=True)}
    here = {_norm(d) for d in matching.series_dirs(comic)}
    move, stay, blocked = [], [], []
    for p in paths:
        p = _norm(p)
        if p not in listed:
            blocked.append({'path': p, 'note': 'Not on the Unmatched list any more.'})
        elif os.path.dirname(p) in here:
            stay.append(p)
        elif os.path.exists(os.path.join(dest, os.path.basename(p))):
            blocked.append({'path': p, 'note': 'A file with this name is already in %s.' % dest})
        else:
            move.append(p)
    return {'ok': True, 'comicid': comic['ComicID'], 'series': comic['ComicName'], 'year': comic['ComicYear'],
            'dest': dest, 'move': move, 'stay': stay, 'blocked': blocked}


def _move(path, dest):
    """Move a file into a series folder, keeping its name, and carry its scan and Import results rows along."""
    import shutil
    os.makedirs(dest, exist_ok=True)
    target = os.path.join(dest, os.path.basename(path))
    shutil.move(path, target)
    st = os.stat(target)
    myDB = db.DBConnection()
    myDB.action('DELETE FROM library_files WHERE Path=?', [path])
    myDB.action('INSERT OR REPLACE INTO library_files (Path, Size, Mtime) VALUES (?, ?, ?)', [target, st.st_size, st.st_mtime])
    myDB.action('UPDATE importresults SET ComicLocation=? WHERE ComicLocation=?', [target, path])
    logger.info('[UNMATCHED] Moved %s into %s.' % (os.path.basename(path), dest))
    return target


def match_file(path, comicid, issueid):
    """Match one unmatched file to an issue by hand, moving it into the series' folder first
    when it sits elsewhere. The match holds through rechecks (see matching.match)."""
    from mylar import matching
    p = plan([path], comicid)
    if not p['ok']:
        return p
    if p['blocked']:
        return {'ok': False, 'note': p['blocked'][0]['note']}
    if not db.DBConnection().selectone('SELECT IssueID FROM issues WHERE IssueID=? AND ComicID=?', [issueid, comicid]).fetchone():
        return {'ok': False, 'note': 'That issue isn\'t part of %s.' % p['series']}
    try:
        target = _move(p['move'][0], p['dest']) if p['move'] else p['stay'][0]
    except OSError as e:
        logger.warn('[UNMATCHED] Could not move %s: %s' % (path, e))
        return {'ok': False, 'note': 'Couldn\'t move the file: %s' % e}
    res = matching.match(comicid, issueid, os.path.basename(target))
    forget()
    if p['move'] and res.get('ok'):
        res['note'] = 'Moved into %s. %s' % (p['dest'], res['note'])
    return res


def match_folder(folder, comicid):
    """Match a folder's unmatched files to a series: move the ones elsewhere into its folder,
    then recheck the series so each file is tied to the issue its name says."""
    from mylar import matching
    folder = _norm(folder)
    fs = [f['path'] for f in files(force=True) if f['folder'] == folder]
    if not fs:
        return {'ok': False, 'note': 'This folder has no unmatched files now.'}
    p = plan(fs, comicid)
    if not p['ok']:
        return p
    moved, failed = [], []
    for path in p['move']:
        try:
            moved.append(_move(path, p['dest']))
        except OSError as e:
            logger.warn('[UNMATCHED] Could not move %s: %s' % (path, e))
            failed.append(path)
    matching._rescan(comicid)
    forget()
    tied = importchoice._tied_paths(db.DBConnection())
    mine = moved + p['stay']
    n_tied = sum(1 for x in mine if x in tied)
    note = '%s of %s file%s now count as issues of %s.' % (n_tied, len(mine), '' if len(mine) == 1 else 's', p['series'])
    if moved:
        note = 'Moved %s into %s. ' % (len(moved), p['dest']) + note
    left = len(mine) - n_tied + len(p['blocked']) + len(failed)
    if left:
        note += ' %s still unmatched; match them one by one.' % left
    return {'ok': True, 'moved': len(moved), 'tied': n_tied, 'left': left, 'note': note}


def series_others(comicid):
    """Files in a series' folder that aren't its own issues: those another series in the same
    folder counts as its own, and those no issue points to. For the series page."""
    from mylar import attention, matching, volume_check
    myDB = db.DBConnection()
    comic = myDB.selectone('SELECT * FROM comics WHERE ComicID=?', [comicid]).fetchone()
    if comic is None:
        return {'ok': False, 'files': []}
    dirs = [d for d in (_norm(x) for x in matching.series_dirs(comic)) if d]
    own, others = set(), {}
    for table in ('issues', 'annuals'):
        for r in myDB.select("SELECT c.ComicID, c.ComicName, c.ComicYear, c.ComicLocation, i.Location, i.Issue_Number FROM %s i "
                             "JOIN comics c ON c.ComicID = i.ComicID WHERE i.Location IS NOT NULL AND i.Location != '' "
                             "AND (c.ComicID=? OR c.ComicLocation IN (%s))" % (table, ','.join('?' * len(dirs))), [comicid] + dirs):
            if str(r['ComicID']) == str(comicid):
                own.add(r['Location'])
            else:
                others[os.path.normpath(os.path.join(r['ComicLocation'], r['Location']))] = {
                    'id': r['ComicID'], 'name': r['ComicName'], 'year': r['ComicYear'], 'number': r['Issue_Number']}
    try:
        flagged = {f['name']: f['note'] for f in volume_check.check(comicid).get('files', [])}
    except Exception as e:
        logger.fdebug('[UNMATCHED] No volume check for %s: %s' % (comicid, e))
        flagged = {}
    out = []
    for f in matching.walk(dirs):
        if f['name'] in own:
            continue
        path = os.path.normpath(f['path'])
        row = {'name': f['name'], 'sub': f['sub'], 'size': f['size'], 'path': path, 'folder': os.path.dirname(path),
               'series': others.get(path), 'note': flagged.get(f['name'])}
        if row['series'] is None:
            parsed = attention.parse(path)
            row['reads_as'] = {'series': parsed.get('series'), 'issue': parsed.get('issue'), 'year': parsed.get('year')}
        out.append(row)
    out.sort(key=lambda r: (r['series'] is not None, (r['sub'] or '').lower(), r['name'].lower()))
    return {'ok': True, 'files': out}
