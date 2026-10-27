import datetime
import json
import os
import re
import threading
import time
import urllib.parse
import zipfile

import mylar
from mylar import db, logger

_lock = threading.Lock()
_running = threading.Event()


def enabled():
    return bool(getattr(mylar.CONFIG, 'ARCHIVE_AUTO_ADD', False)) and bool(mylar.CONFIG.COMICVINE_API)


def _registry_path():
    return os.path.join(mylar.CONFIG.CACHE_DIR or mylar.DATA_DIR, 'autoadd_attempts.json')


def _load():
    try:
        with open(_registry_path()) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(reg):
    cutoff = time.time() - 30 * 86400
    reg = {k: v for k, v in reg.items() if v.get('at', 0) > cutoff}
    try:
        with open(_registry_path(), 'w') as f:
            json.dump(reg, f)
    except Exception as e:
        logger.warn('[AUTO-ADD] Unable to save the attempt list: %s' % e)


def running():
    return _running.is_set()


def attempted(path):
    return path in _load()


def _norm(name):
    name = (name or '').lower().replace('&', 'and')
    name = re.sub(r'\bversus\b|\bvs\b\.?', 'vs', name)
    name = re.sub(r'\(\d{4}\)', '', name)
    name = re.sub(r'\bthe\b', ' ', name)   # "Silver Surfer: The Enslavers" is "Silver Surfer Enslavers"
    return re.sub(r'[^a-z0-9]', '', name)


def _pack_date(path):
    for part in reversed(os.path.normpath(path).split(os.sep)[:-1]):
        m = re.match(r'(\d{4})[.\-_](\d{2})[.\-_](\d{2})', part)
        if m:
            try:
                return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def _comicinfo_issueid(path):
    try:
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().rsplit('/', 1)[-1] == 'comicinfo.xml'), None)
            if not name:
                return None
            text = z.read(name).decode('utf-8', 'ignore')
    except Exception:
        return None
    m = re.search(r'CVDB(\d+)|comicvine\.gamespot\.com/[^<]*?4000-(\d+)', text, re.I)
    return (m.group(1) or m.group(2)) if m else None


def _parse(path):
    from mylar import filechecker
    try:
        res = filechecker.FileChecker(dir=os.path.dirname(path), file=os.path.basename(path)).listFiles()
    except Exception:
        return None
    if not res or res.get('parse_status') != 'success' or not res.get('series_name'):
        return None
    issue = str(res['issue_number']).lstrip('0') or '0' if res.get('issue_number') else None
    year = res.get('issue_year')
    # "X-Men Annual 1995": the year may be the series' name (ComicVine's X-Men '95, also called
    # X-Men Annual 1995), whether the name was read as no issue number or as issue #1995
    name_year = bool(res.get('name_year')) or bool(re.search(r'\bannual$', res['series_name'].strip(), re.I) and year and issue in (None, year))
    return {'series': res['series_name'], 'issue': None if name_year else issue, 'year': year, 'name_year': name_year}


def _cv(resource, params):
    from mylar import cv
    params = dict(params, api_key=mylar.CONFIG.COMICVINE_API, format='json')
    url = '%s%s/?%s' % (mylar.CVURL, resource, urllib.parse.urlencode(params, safe=':|,'))
    r = cv.cv_request(url, timeout=60)
    return (r.json() or {}).get('results') or []


def _date(s):
    try:
        return datetime.date.fromisoformat((s or '')[:10])
    except ValueError:
        return None


def _volume_for_issue(issueid):
    res = _cv('issue/4000-%s' % issueid, {'field_list': 'volume'})
    vol = res.get('volume') if isinstance(res, dict) else None
    return str(vol['id']) if vol and vol.get('id') else None


def _names(v):
    """A ComicVine volume's name and its aliases, one per line on ComicVine."""
    return [v.get('name')] + [a for a in re.split(r'[\r\n]+', v.get('aliases') or '') if a.strip()]


def _single(vols, year):
    """The one single-issue volume from about that year, for a file with no issue number (a one-shot,
    a graphic novel, "X-Men Annual 1995"). None when there's none, or more than one to choose from."""
    ones = [v for v in vols if v.get('count_of_issues') == 1]
    if year and str(year).isdigit():
        ones = [v for v in ones if str(v.get('start_year') or '').isdigit() and abs(int(v['start_year']) - int(year)) <= 1]
    return str(ones[0]['id']) if len(ones) == 1 else None


def _find_volume(series, issue, year, packdate, name_year=False):
    """The ComicVine volume a file belongs to. Its name or one of its aliases has to be the file's
    series ("X-Men '95" is also called "X-Men Annual 1995"); then the issue number has to be on it,
    or, with no number, it has to be the one single-issue volume from that year."""
    wants = {_norm(series)}
    query = series
    if name_year and year:
        query = '%s %s' % (series, year)
        wants = {_norm(query)}
    vols = [v for v in _cv('search', {'resources': 'volume', 'query': query, 'limit': 20,
                                      'field_list': 'id,name,start_year,count_of_issues,aliases'})
            if any(_norm(n) in wants for n in _names(v))]
    if not vols:
        return None
    if issue is None:
        return _single(vols, year)
    issues = _cv('issues', {'filter': 'volume:%s,issue_number:%s' % ('|'.join(str(v['id']) for v in vols), issue),
                            'field_list': 'id,volume,store_date,cover_date', 'limit': 100})
    best = None
    for i in issues:
        store, cover = _date(i.get('store_date')), _date(i.get('cover_date'))
        if packdate:
            if store:
                gap = abs((store - packdate).days)
                ok = gap <= 21
            elif cover:
                gap = abs((cover - packdate).days)
                ok = gap <= 120
            else:
                continue
        else:
            when = store or cover
            if not when or not year:
                continue
            gap = abs(when.year - int(year)) * 365
            ok = gap <= 365
        if ok and (best is None or gap < best[0]):
            best = (gap, str(i['volume']['id']))
    return best[1] if best else None


def queue(paths, force=False, folder=None):
    """Find and add the series of these unclaimed files, in the background. force: the user asked,
    from Needs attention, so it runs with auto-add switched off and tries files tried before; then
    files folder again. Returns why it couldn't start, or None."""
    if not paths:
        return 'There are no files to look up.'
    if force:
        if not mylar.CONFIG.COMICVINE_API:
            return 'Adding series needs a ComicVine API key (Settings).'
        fresh = list(paths)
    else:
        if not enabled():
            return 'Auto-add is off.'
        reg = _load()
        fresh = [p for p in paths if p not in reg]
    if not fresh:
        return 'Those files were looked up already.'
    if _running.is_set():
        return 'Series are already being added. Try again when that finishes.'
    threading.Thread(target=_run, args=(fresh, folder), name='AUTO-ADD', daemon=True).start()
    return None


def _run(paths, folder=None, refile=True):
    """Look up and add the series of these files. refile: then file folder (or the monitored folder)
    again; Try filing again files its folders itself."""
    from mylar import importer, archives
    with _lock:
        _running.set()
        try:
            myDB = db.DBConnection()
            watched = {str(r['ComicID']) for r in myDB.select('SELECT ComicID FROM comics')}
            from mylar.PostProcessor import PP_LOCK
            reg = _load()
            groups = {}
            unknown = []
            with PP_LOCK:
                for p in paths:
                    reg[p] = {'at': time.time()}
                    if not os.path.isfile(p):
                        continue
                    info = _parse(p)
                    if not info:
                        unknown.append(os.path.basename(p))   # can't even read a series name
                        continue
                    key = (_norm(info['series']), info['year'], _pack_date(p))
                    groups.setdefault(key, {'info': info, 'files': [], 'cvid': None})['files'].append(p)
                    if not groups[key]['cvid']:
                        groups[key]['cvid'] = _comicinfo_issueid(p)
            added = []
            archives.busy('Finding series for %s unclaimed issues' % len(paths))
            for (nm, year, packdate), g in groups.items():
                try:
                    volid = _volume_for_issue(g['cvid']) if g['cvid'] else None
                    if volid is None:
                        volid = _find_volume(g['info']['series'], g['info']['issue'], year, packdate, g['info'].get('name_year'))
                except Exception as e:
                    logger.warn('[AUTO-ADD] ComicVine lookup failed for %s: %s' % (g['info']['series'], e))
                    volid = None
                if volid is None:
                    unknown.append(g['info']['series'])
                    continue
                if volid in watched:
                    continue
                logger.info('[AUTO-ADD] Adding %s (ComicVine %s) for %s file(s) found in the monitored folder.' % (g['info']['series'], volid, len(g['files'])))
                try:
                    importer.addComictoDB(volid, 'no')
                    watched.add(volid)
                    added.append(g['info']['series'])
                except Exception as e:
                    logger.warn('[AUTO-ADD] Unable to add %s: %s' % (g['info']['series'], e))
            _save(reg)
            if added:
                archives.note('added %s series: %s' % (len(added), ', '.join(sorted(set(added)))))
            if unknown:
                archives.note('could not identify %s series' % len(set(unknown)))
            logger.info('[AUTO-ADD] Added %s series; %s could not be identified%s.' % (
                len(added), len(set(unknown)), ': %s' % ', '.join(sorted(set(unknown))) if unknown else ''))
            refile = refile and (folder or mylar.CONFIG.CHECK_FOLDER)
            if added and refile:
                logger.info('[AUTO-ADD] Filing the issues of the new series now (%s).' % refile)
                mylar.PP_QUEUE.put({'nzb_name': 'Manual Run', 'nzb_folder': refile, 'failed': False, 'issueid': None,
                                    'comicid': None, 'apicall': False, 'ddl': False, 'download_info': None})
            archives.done('Auto-add finished.')
        finally:
            archives.done('Auto-add stopped early - check the log.')
            _running.clear()
