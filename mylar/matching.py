"""Matching the files in a series folder to its issues: matches made by hand on the series page,
and files whose ComicInfo tags carry a ComicVine issue ID of the series."""
import os
import shutil
import threading

import mylar
from mylar import comicinfo, db, logger

_TAGS = {}   # (path, size, mtime) -> ComicVine issue ID, so a rescan doesn't reopen unchanged files
_LOCK = threading.Lock()


def _extensions():
    return tuple(x for x in ('.cbr', '.cbz', '.cb7', '.pdf') if x not in (mylar.CONFIG.IGNORE_SEARCH_WORDS or []))


def series_dirs(comic):
    """The series folder, and its copy under the second library folder when there is one."""
    if not comic or not comic['ComicLocation']:
        return []
    dirs = [comic['ComicLocation']]
    extra = mylar.CONFIG.MULTIPLE_DEST_DIRS
    if extra and extra != 'None':
        try:
            alt = os.path.join(extra, os.path.basename(comic['ComicLocation']))
            if not os.path.exists(alt):
                alt = mylar.filers.FileHandlers(ComicID=comic['ComicID']).secondary_folders(comic['ComicLocation'])
            if alt and alt not in dirs:
                dirs.append(alt)
        except Exception as e:
            logger.fdebug('[MATCHING] No second folder for %s: %s' % (comic['ComicLocation'], e))
    return dirs


def walk(dirs):
    """Every comic file in the folders, the way a rescan sees them."""
    ext = _extensions()
    out = []
    for top in dirs:
        if not os.path.isdir(top):
            continue
        for here, subs, names in os.walk(top):
            if '.AppleDouble' in here:
                continue
            for name in names:
                if name.startswith('.') or not name.lower().endswith(ext):
                    continue
                path = os.path.join(here, name)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                if size:
                    sub = os.path.relpath(here, top)
                    out.append({'path': path, 'name': name, 'sub': None if sub == '.' else sub, 'size': size})
    return out


def pins(comicid, dirs):
    """The files matched by hand, by name, each with its issue. A match whose file is gone is dropped,
    so the issue is matched by name again."""
    myDB = db.DBConnection()
    rows = myDB.select('SELECT IssueID, Location FROM issues WHERE ComicID=? AND forced_file=1', [comicid])
    if not rows:
        return {}
    found = {}
    names = None
    for r in rows:
        name = r['Location']
        here = name and any(os.path.isfile(os.path.join(d, name)) for d in dirs)
        if name and not here:
            if names is None:
                names = {f['name'] for f in walk(dirs)}
            here = name in names
        if here:
            found[name] = r['IssueID']
        else:
            logger.info('[MATCHING] The file matched by hand to issue %s is gone - matching it by name again.' % r['IssueID'])
            myDB.action('UPDATE issues SET forced_file=0 WHERE IssueID=?', [r['IssueID']])
    return found


def tagged_id(path, size=None):
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_size, st.st_mtime)
    with _LOCK:
        if key in _TAGS:
            return _TAGS[key]
    cvid = comicinfo.cv_issue_id(path)
    with _LOCK:
        if len(_TAGS) > 20000:
            _TAGS.clear()
        _TAGS[key] = cvid
    return cvid


def by_tags(comicid, files, pinned, taken):
    """Of files the name didn't place, those whose tags name an issue (or annual) of this series
    that no other file has. files: (folder, subfolder, name, size)."""
    myDB = db.DBConnection()
    taken = set(str(t) for t in taken) | set(str(i) for i in pinned.values())
    seen = set()
    out = []
    for folder, sub, name, size in files:
        if not name or name in pinned:
            continue
        path = os.path.join(folder, sub or '', name)
        if path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        cvid = tagged_id(path)
        if not cvid or cvid in taken:
            continue
        row = myDB.selectone('SELECT Issue_Number FROM issues WHERE ComicID=? AND IssueID=?', [comicid, cvid]).fetchone()
        annual = False
        if row is None and mylar.CONFIG.ANNUALS_ON:
            row = myDB.selectone('SELECT Issue_Number FROM annuals WHERE ComicID=? AND IssueID=? AND NOT Deleted', [comicid, cvid]).fetchone()
            annual = row is not None
        if row is None:
            continue
        taken.add(cvid)
        if size is None:
            size = os.path.getsize(path)
        out.append({'issueid': cvid, 'number': row['Issue_Number'], 'name': name, 'size': str(size), 'annual': annual})
    return out


def _comic(comicid):
    return db.DBConnection().selectone('SELECT ComicID, ComicName, ComicYear, ComicLocation FROM comics WHERE ComicID=?', [comicid]).fetchone()


def files(comicid):
    """The series' files, each with the issue it counts as now and the issue number its name reads as,
    and the series' issues to choose from."""
    from mylar import attention
    comic = _comic(comicid)
    if comic is None:
        return {'ok': False, 'note': 'That series isn\'t on your watchlist.'}
    myDB = db.DBConnection()
    issues = [dict(r) for r in myDB.select('SELECT IssueID, Issue_Number, IssueName, Status, Location, forced_file, ImageURL, ImageURL_ALT FROM issues '
                                            'WHERE ComicID=? ORDER BY Int_IssueNumber', [comicid])]
    # Archived issues keep the name of a file that has gone, so only Downloaded ones count as having one
    linked = {i['Location']: i for i in issues if i['Location'] and i['Status'] == 'Downloaded'}
    out = []
    for f in walk(series_dirs(comic)):
        i = linked.get(f['name'])
        out.append({'name': f['name'], 'sub': f['sub'], 'size': f['size'],
                    'issueid': i['IssueID'] if i else None, 'number': i['Issue_Number'] if i else None,
                    'pinned': bool(i and i['forced_file']), 'reads_as': attention.parse(f['path']).get('issue')})
    out.sort(key=lambda f: (f['issueid'] is not None, (f['sub'] or '').lower(), f['name'].lower()))
    return {'ok': True, 'folder': comic['ComicLocation'], 'files': out, 'waiting': waiting(comicid),
            'issues': [{'issueid': i['IssueID'], 'number': i['Issue_Number'], 'name': i['IssueName'], 'status': i['Status'],
                        'file': i['Location'] if i['Status'] == 'Downloaded' else None,
                        'pinned': bool(i['forced_file']), 'cover': bool(i['ImageURL'] or i['ImageURL_ALT'])} for i in issues]}


def waiting(comicid):
    """Files in Needs attention that look like this series, each with the issue its name points to."""
    from mylar import attention
    out = []
    try:
        listed = attention.items()
    except Exception as e:
        logger.fdebug('[MATCHING] Could not read Needs attention: %s' % e)
        return out
    for i in listed:
        if i['in_library'] or (i.get('job') or {}).get('state') in ('waiting', 'filing'):
            continue
        m = next((m for m in i['matches'] if str(m['comicid']) == str(comicid)), None)
        if m is None:
            continue
        out.append({'path': i['path'], 'name': i['name'], 'size': i['size'], 'modified': round(i['modified']),
                    'reads_as': (i['parsed'] or {}).get('issue'), 'issueid': m.get('issueid'), 'number': m.get('number')})
    return out


def cover(comicid, name):
    """The front cover of a file in the series folder (see attention.cover_of), or None."""
    from mylar import attention
    comic = _comic(comicid)
    f = next((f for f in walk(series_dirs(comic)) if f['name'] == name), None) if comic else None
    return attention.cover_of(f['path']) if f else None


def _rescan(comicid):
    from mylar import updater
    updater.forceRescan(comicid, module='[MATCHING]')


def match(comicid, issueid, name):
    """Make a file in the series folder count as this issue, whatever its name says. The match
    holds through later rechecks until it is undone or the file goes."""
    comic = _comic(comicid)
    if comic is None:
        return {'ok': False, 'note': 'That series isn\'t on your watchlist.'}
    myDB = db.DBConnection()
    issue = myDB.selectone('SELECT IssueID, Issue_Number FROM issues WHERE IssueID=? AND ComicID=?', [issueid, comicid]).fetchone()
    if issue is None:
        return {'ok': False, 'note': 'That issue isn\'t part of this series.'}
    f = next((f for f in walk(series_dirs(comic)) if f['name'] == name), None)
    if f is None:
        return {'ok': False, 'note': 'That file isn\'t in the series folder any more.'}
    myDB.action('UPDATE issues SET forced_file=0 WHERE ComicID=? AND Location=? AND IssueID!=?', [comicid, name, issueid])
    myDB.action("UPDATE issues SET forced_file=1, Location=?, ComicSize=?, Status='Downloaded' WHERE IssueID=?",
                [name, str(f['size']), issueid])
    logger.info('[MATCHING] %s is now #%s of %s, matched by hand.' % (name, issue['Issue_Number'], comic['ComicName']))
    _rescan(comicid)
    return {'ok': True, 'note': '%s is now #%s.' % (name, issue['Issue_Number'])}


def unmatch(comicid, issueid):
    """Undo a match made by hand: the file is matched by its name again."""
    myDB = db.DBConnection()
    issue = myDB.selectone('SELECT Issue_Number, forced_file FROM issues WHERE IssueID=? AND ComicID=?', [issueid, comicid]).fetchone()
    if issue is None:
        return {'ok': False, 'note': 'That issue isn\'t part of this series.'}
    if issue['forced_file']:
        myDB.action('UPDATE issues SET forced_file=0 WHERE IssueID=?', [issueid])
        logger.info('[MATCHING] Undid the match made by hand for issue %s.' % issueid)
        _rescan(comicid)
    return {'ok': True, 'note': '#%s is matched by file name again.' % issue['Issue_Number']}


def move_to(comicid, newid):
    """Wrong series: move the files of a series added as the wrong ComicVine series into the right
    one's folder, then recheck both so the files match the right series' issues. The wrong series
    stays on the watchlist until it is removed."""
    from mylar import attention
    old, new = _comic(comicid), _comic(newid)
    if old is None:
        return {'ok': False, 'note': 'That series isn\'t on your watchlist.'}
    if new is None or str(newid) == str(comicid):
        return {'ok': False, 'note': 'Pick a different series to move the files to.'}
    if attention.series_state(newid)['state'] != 'ready':
        return {'ok': False, 'note': '%s is still being added. Try again when its issues have loaded.' % new['ComicName']}
    if not new['ComicLocation']:
        return {'ok': False, 'note': '%s has no series folder.' % new['ComicName']}
    moved, kept = 0, []
    for top in series_dirs(old):
        if os.path.normpath(top) == os.path.normpath(new['ComicLocation']):
            continue
        for f in walk([top]):
            if f['path'].startswith(os.path.join(new['ComicLocation'], '')):
                continue   # already in the right series' folder (it sits inside this one)
            dest_dir = os.path.join(new['ComicLocation'], f['sub']) if f['sub'] else new['ComicLocation']
            dest = os.path.join(dest_dir, f['name'])
            if os.path.exists(dest):
                kept.append(f['name'])
                continue
            try:
                os.makedirs(dest_dir, exist_ok=True)
                shutil.move(f['path'], dest)
                moved += 1
            except OSError as e:
                logger.warn('[MATCHING] Could not move %s to %s: %s' % (f['path'], dest_dir, e))
                kept.append(f['name'])
    logger.info('[MATCHING] Moved %s file(s) from %s [%s] to %s [%s].' % (moved, old['ComicName'], comicid, new['ComicName'], newid))
    _rescan(comicid)
    _rescan(newid)
    have = db.DBConnection().selectone("SELECT COUNT(*) AS n FROM issues WHERE ComicID=? AND Status='Downloaded'", [newid]).fetchone()['n']
    label = '%s (%s)' % (new['ComicName'], new['ComicYear']) if new['ComicYear'] else new['ComicName']
    note = 'Moved %s file%s to %s. %s of its issues have a file now.' % (moved, '' if moved == 1 else 's', label, have)
    if kept:
        note += ' %s file%s stayed where %s, because a file with the same name is already there or it couldn\'t be moved.' % (
            len(kept), '' if len(kept) == 1 else 's', 'it was' if len(kept) == 1 else 'they were')
    return {'ok': True, 'moved': moved, 'kept': kept, 'have': have, 'note': note,
            'series': {'comicid': str(newid), 'name': new['ComicName']}}
