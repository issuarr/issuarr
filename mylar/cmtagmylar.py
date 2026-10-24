# This script was initially based from Manders2600 Script with the use of the awesome ComicTagger.
# Modified, so Mylar just can pass in relevant information instead of querying CV for it to do it's magic.


import datetime
import json
import os
import pathlib
import sys
import re
import shutil
import sqlite3
import time
import zipfile
import subprocess
import mylar

from mylar import logger, notifiers, comicinfo, importstatus


def run(dirName, nzbName=None, issueid=None, comversion=None, manual=None, filename=None, module=None, manualmeta=False, readingorder=None, agerating=None):
    if module is None:
        module = ''
    module += '[META-TAGGER]'

    logger.fdebug(module + ' dirName:' + dirName)

    logger.fdebug(module + ' Filename is : ' + filename)

    filepath = filename
    og_filepath = filepath
    try:
        filename = os.path.split(filename)[1]   # just the filename itself
    except:
        logger.warn('Unable to detect filename within directory - I am aborting the tagging. You best check things out.')
        sendnotify("Error - Unable to detect filename within directory. Tagging aborted.", filename, module)
        return "fail"

    #make use of temporary file location in order to post-process this to ensure that things don't get hammered when converting
    new_filepath = None
    new_folder = None
    try:
        import tempfile
        logger.fdebug('Filepath: %s' %filepath)
        logger.fdebug('Filename: %s' %filename)
        new_folder = tempfile.mkdtemp(prefix='mylar_', dir=mylar.CONFIG.CACHE_DIR) #prefix, suffix, dir
        os.chmod(new_folder, 0o777)
        logger.fdebug('New_Folder: %s' % new_folder)
        new_filepath = os.path.join(new_folder, filename)
        logger.fdebug('New_Filepath: %s' % new_filepath)
        if mylar.CONFIG.FILE_OPTS == 'copy' and manualmeta == False:
            shutil.copy(filepath, new_filepath)
        else:
            shutil.copy(filepath, new_filepath)

        filepath = new_filepath
        original_perms = os.stat(filepath).st_mode
        original_cix = comicinfo.read_raw(og_filepath)
        tag_mode = comicinfo.tag_mode()
    except Exception as e:
        logger.warn('%s Unexpected Error: %s [%s]' % (module, sys.exc_info()[0], e))
        logger.warn(module + ' Unable to create temporary directory to perform meta-tagging. Processing without metatagging.')
        sendnotify("Error - Unable to create temporary directory to perform meta-tagging. Processing without metatagging.", filename, module)
        tidyup(og_filepath, new_filepath, new_folder, manualmeta)
        return "fail"

    ## Sets up other directories ##
    scriptname = os.path.basename(sys.argv[0])
    downloadpath = os.path.abspath(dirName)
    sabnzbdscriptpath = os.path.dirname(sys.argv[0])
    comicpath = new_folder

    logger.fdebug(module + ' Paths / Locations:')
    logger.fdebug(module + ' scriptname : ' + scriptname)
    logger.fdebug(module + ' downloadpath : ' + downloadpath)
    logger.fdebug(module + ' sabnzbdscriptpath : ' + sabnzbdscriptpath)
    logger.fdebug(module + ' comicpath : ' + comicpath)
    logger.fdebug(module + ' Running the ComicTagger Add-on for Mylar')


    if not mylar.CONFIG.CBR2CBZ_ONLY and not tag_types():
        logger.warn(module + ' You have metatagging enabled, but you have not selected the type(s) of metadata to write. Please fix and re-run manually')
        tidyup(filepath, new_filepath, new_folder, manualmeta)
        return "fail"

    if not zipfile.is_zipfile(filepath):
        res, out = run_comictagger(export_args(filepath), module)
        if res is None or res.get('status') == 'read_failure':
            logger.fdebug('%s Output: %s' % (module, out))
            if not os.path.isfile(filepath):
                logger.warn('%s[COMIC-TAGGER] Unable to locate file: %s' % (module, filename))
            else:
                logger.warn('%s[COMIC-TAGGER] %s is not a comic archive ComicTagger can read.' % (module, filename))
            tidyup(og_filepath, new_filepath, new_folder, manualmeta)
            return 'file not found||%s' % filename
        exported = res.get('renamed_path')
        if not exported or not os.path.isfile(exported):
            logger.fdebug('%s Output: %s' % (module, out))
            tidyup(og_filepath, new_filepath, new_folder, manualmeta)
            if CORRUPT.search(out):
                return 'corrupt'
            cbz_message = 'Failed to convert cbr to cbz - check permissions on folder %s and/or the location where Issuarr is trying to tag the files from.' % mylar.CONFIG.CACHE_DIR
            logger.warn('%s[COMIC-TAGGER][CBR-TO-CBZ]%s' % (module, cbz_message))
            sendnotify('Error - %s' % (cbz_message), filename, module)
            return 'fail'
        filepath = exported
        wanted = os.path.join(comicpath, os.path.splitext(filename)[0] + '.cbz')
        if filepath != wanted:
            # a .cbz-named rar exports to "name (1).cbz" because the rar still holds the name.
            # Both are in our temporary folder, so the cbz takes the name over.
            try:
                os.replace(filepath, wanted)
                filepath = wanted
            except OSError:
                logger.warn('%s unable to rename file to accomodate metatagging cbz to the same filename' % module)
        logger.fdebug('%s[COMIC-TAGGER][CBR-TO-CBZ] New filename: %s' % (module, filepath))
    else:
        logger.fdebug('%s[COMIC-TAGGER] %s is already a cbz.' % (module, filename))

    if mylar.CONFIG.CBR2CBZ_ONLY:
        logger.fdebug(module + ' CBR2CBZ Conversion only.')
        return filepath

    if tag_mode == 'skip':
        logger.fdebug(module + ' Will NOT modify existing tag blocks even if they exist already.')
    elif tag_mode == 'fill':
        logger.fdebug(module + ' Will fill in missing tags and keep every existing value.')
    else:
        logger.fdebug(module + ' Will overwrite existing tags with ComicVine data.')

    logger.info(module + ' ComicRack tagging meta-tagging processing started.')
    from mylar import cv
    publisher, imprint = series_publisher(issueid)
    attempt = 0
    while True:
        if not pace(issueid, module):
            tidyup(og_filepath, new_filepath, new_folder, manualmeta)
            return 'fail'
        res, out = run_comictagger(tag_args(filepath, issueid, comversion, agerating, tag_mode, imprint), module)
        status = res.get('status') if res else None
        if status != 'fetch_data_failure' or not RATE_LIMITED.search(out or '') or attempt >= len(cv.RATELIMIT_WAITS):
            break
        # ComicTagger already waited 10 seconds three times, so this backs off the way
        # Issuarr's own ComicVine calls do and tags the file again afterwards.
        wait = cv.RATELIMIT_WAITS[attempt]
        attempt += 1
        importstatus.set_ratelimit('Rate limit exceeded', 'issue', wait, attempt)
        logger.warn('%s[COMIC-TAGGER] ComicVine rate limit hit while tagging %s. Waiting %s minutes before trying again (attempt %s).' % (module, filename, round(wait / 60, 1), attempt))
    if attempt and status in ('success', 'existing_tags'):
        importstatus.clear_ratelimit()
    if status == 'existing_tags':
        logger.info('%s[COMIC-TAGGER] %s already has tags - leaving them alone.' % (module, filename))
        return filepath
    if status != 'success':
        logger.fdebug('%s Output: %s' % (module, out))
        if status == 'read_failure':
            logger.warn('%s[COMIC-TAGGER] Unable to read file: %s' % (module, filename))
            tidyup(og_filepath, new_filepath, new_folder, manualmeta)
            return 'file not found||%s' % filename
        unknown_message = FAILURES.get(status, 'ComicTagger could not tag the file (%s)' % (status or 'no result'))
        logger.warn('%s[COMIC-TAGGER][UNKNOWN-ERROR-DURING-METATAGGING] %s' % (module, unknown_message))
        sendnotify('Error - %s' % (unknown_message), filename, module)
        tidyup(og_filepath, new_filepath, new_folder, manualmeta)
        return 'fail'

    logger.info('%s[COMIC-TAGGER] Successfully wrote ComicRack tagging [%s]' % (module, filepath))
    # ComicTagger rewrites the archive, which resets the file's permissions, so this restores them
    os.chmod(filepath, original_perms)

    fields = arc_fields(readingorder) or {}
    if imprint:
        # ComicVine's publisher replaces anything passed in, so the parent publisher
        # goes in afterwards, next to the imprint ComicTagger wrote.
        fields['Publisher'] = publisher
    if fields or mylar.CONFIG.CT_NOTES_FORMAT == 'CVDB':
        comicinfo.adjust(filepath, fields, notes_format=mylar.CONFIG.CT_NOTES_FORMAT)

    if not comicinfo.keep_existing(original_cix, filepath, tag_mode):
        logger.warn('%s Unable to merge the new tags with the existing ones - filing the file without tagging.' % module)
        tidyup(og_filepath, new_filepath, new_folder, manualmeta)
        return "fail"

    return filepath



# Tags written by ComicTagger. It dropped ComicBookLover tags after 1.3.5, so ComicRack
# (ComicInfo.xml) is the only kind left.
CT_TAGS = 'cr'

CORRUPT = re.compile(r'corrupt|crc|expected size|failed the read|bad ?rar|truncated|unexpected end', re.I)

FAILURES = {
    'match_failure': 'ComicTagger could not find a confident match on ComicVine',
    'fetch_data_failure': 'ComicTagger could not get the issue details from ComicVine',
    'write_failure': 'ComicTagger could not write the tags into the file',
    'write_permission_failure': 'ComicTagger could not write to the file - check its permissions',
}


# ComicVine allows about 200 calls an hour on each resource, and each tag fetches its
# issue unless ComicTagger has it cached. Every file gets a new ComicTagger process whose
# limiter starts fresh, so each tag books its call from Issuarr's own ComicVine schedule
# (cv.reserve), with some room left for Issuarr's own calls. ComicTagger's shared key is
# only allowed 100 an hour.
HOURLY_TAGS = 180
HOURLY_TAGS_DEFAULT_KEY = 90

RATE_LIMITED = re.compile(r'rate limit|slow down|abnormal traffic|did not provide json|\b(?:107|420|429): ', re.I)


def personal_key():
    return mylar.CONFIG.COMICVINE_API not in (None, '', 'None')


def cached(issueid):
    """True when ComicTagger's cache already holds the issue, so tagging it makes no call."""
    if issueid is None or not mylar.CONFIG.CT_SETTINGSPATH:
        return False
    db = pathlib.Path(mylar.CONFIG.CT_SETTINGSPATH, 'cache', 'comic_cache.db')
    if not db.is_file():
        return False
    # ComicTagger drops cached issues after a year
    fresh = str(datetime.datetime.today() - datetime.timedelta(days=365))
    try:
        con = sqlite3.connect(db.absolute().as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            row = con.execute("SELECT complete FROM Issues WHERE id=? AND source='comicvine' AND timestamp >= ?", [str(issueid), fresh]).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return bool(row and row[0])


def pace(issueid, module):
    """Wait out a ComicVine back-off Issuarr already knows about, then hold the tag until
    its slot in Issuarr's ComicVine schedule. False when Issuarr is shutting down meanwhile."""
    from mylar import cv
    remaining = importstatus.ratelimit_remaining()
    if remaining > 0:
        logger.info('%s[COMIC-TAGGER] Waiting %s minutes for the ComicVine rate limit to clear before tagging.' % (module, round(remaining / 60, 1)))
        if not cv._cv_wait(remaining):
            return False
    if cached(issueid):
        return True
    limit = HOURLY_TAGS if personal_key() else HOURLY_TAGS_DEFAULT_KEY
    wait = cv.reserve('issue', limit)
    if wait >= 60:
        logger.info('%s[COMIC-TAGGER] Waiting %s minutes for a ComicVine slot before tagging.' % (module, round(wait / 60, 1)))
    return wait <= 0 or cv._cv_wait(wait)


def series_publisher(issueid):
    """The series' publisher and imprint when Issuarr's imprint listing (data/imprints.json)
    found one, such as DC Comics and Vertigo. ComicVine often lists the imprint as the
    publisher and has no imprint field."""
    if issueid is None:
        return None, None
    from mylar import db
    myDB = db.DBConnection()
    for table in ('issues', 'annuals'):
        row = myDB.selectone('SELECT c.ComicPublisher, c.PublisherImprint FROM %s i JOIN comics c ON c.ComicID = i.ComicID WHERE i.IssueID=?' % table, [str(issueid)]).fetchone()
        if row:
            break
    else:
        return None, None
    publisher, imprint = row['ComicPublisher'], row['PublisherImprint']
    if publisher in (None, '', 'None') or imprint in (None, '', 'None'):
        return None, None
    return publisher, imprint


def tag_types():
    return CT_TAGS if mylar.CONFIG.CT_TAG_CR else None


def comictagger_cmd():
    return [sys.executable, os.path.join(mylar.CMTAGGER_PATH or mylar.PROG_DIR, 'comictagger.py')]


def export_args(filepath):
    args = ['-e', '--config', mylar.CONFIG.CT_SETTINGSPATH, '--json']
    if mylar.CONFIG.FILE_OPTS == 'move':
        args.append('--delete-original')
    return args + [filepath]


def volume_number(comversion):
    if not mylar.CONFIG.CMTAG_VOLUME:
        return None
    if any([comversion is None, comversion == '', comversion == 'None']):
        if mylar.CONFIG.SETDEFAULTVOLUME and not mylar.CONFIG.CMTAG_START_YEAR_AS_VOLUME:
            return 1
        return None
    digits = re.sub('[^0-9]', '', str(comversion)).strip()
    return int(digits) if digits else None


def metadata_arg(comversion, agerating, imprint=None):
    md = {}
    if imprint:
        md['imprint'] = imprint
    volume = volume_number(comversion)
    if volume is not None:
        md['volume'] = volume
    if all([agerating is not None, agerating != 'None', agerating != '']):
        md['maturity_rating'] = str(agerating)
    return json.dumps(md) if md else None


def tag_args(filepath, issueid, comversion, agerating, tag_mode, imprint=None):
    args = ['-s', '-o', '--tags-write', CT_TAGS, '--config', mylar.CONFIG.CT_SETTINGSPATH, '--json']
    if personal_key():
        args += ['--comicvine-key', mylar.CONFIG.COMICVINE_API]
    else:
        logger.fdebug('[META-TAGGER] No personal ComicVine API key supplied - ComicTagger will use its own. Take your chances.')
    cv_api_url = (getattr(mylar.CONFIG, 'COMICVINE_URL', None) or '').strip().rstrip('/')
    args += ['--comicvine-url', cv_api_url or 'https://comicvine.gamespot.com/api']
    md = metadata_arg(comversion, agerating, imprint)
    if md:
        args += ['-m', md]
    if tag_mode == 'skip':
        args.append('--skip-existing-tags')
    if issueid is None:
        args.append('-f')
    else:
        args += ['--id', str(issueid)]
    return args + [filepath]


def arc_fields(readingorder):
    # ComicTagger has no story arc numbers, so the arcs Issuarr knows about are written
    # into ComicInfo.xml afterwards, keeping each name next to its number.
    if not readingorder:
        return None
    if not isinstance(readingorder, list):
        return {'StoryArcNumber': str(readingorder)}
    names = [str(r[0]) for r in readingorder]
    numbers = [str(r[1]) for r in readingorder]
    return {'StoryArc': ','.join(names), 'StoryArcNumber': ','.join(numbers)}


def _redact(args):
    key = mylar.CONFIG.COMICVINE_API
    return [('REDACTED' if key and a == key else a) for a in args]


def run_comictagger(args, module):
    script_cmd = comictagger_cmd() + args
    logger.fdebug('%s Executing command: %s' % (module, _redact(script_cmd)))
    try:
        p = subprocess.run(script_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace')
    except OSError as e:
        logger.warn('%s[COMIC-TAGGER] Unable to run comictagger: %s' % (module, e))
        return None, str(e)
    out = (p.stderr or '').strip()
    res = None
    start = (p.stdout or '').find('{')
    if start >= 0:
        try:
            res = json.JSONDecoder().raw_decode(p.stdout[start:])[0]
        except ValueError:
            pass
    if res is None:
        logger.warn('%s[COMIC-TAGGER] No result from ComicTagger (exit code %s): %s' % (module, p.returncode, out[-500:]))
    else:
        logger.fdebug('%s[COMIC-TAGGER] %s: %s' % (module, res.get('action'), res.get('status')))
    return res, out

def tidyup(filepath, new_filepath, new_folder, manualmeta):
   if all([new_filepath is not None, new_folder is not None]):
        if mylar.CONFIG.FILE_OPTS == 'copy' and manualmeta == False:
            if all([os.path.exists(new_folder), os.path.isfile(filepath)]):
                shutil.rmtree(new_folder)
            elif os.path.exists(new_filepath) and not os.path.exists(filepath):
                shutil.move(new_filepath, filepath + '.BAD')
        else:
            if os.path.exists(new_filepath) and not os.path.exists(filepath):
                shutil.move(new_filepath, filepath + '.BAD')
            if all([os.path.exists(new_folder), os.path.isfile(filepath)]):
                shutil.rmtree(new_folder)

def sendnotify(message, filename, module):

    prline = filename

    prline2 = 'Issuarr metatagging error: ' + message + ' File: ' + prline

    try:
        if mylar.CONFIG.PROWL_ENABLED:
            pushmessage = prline
            prowl = notifiers.PROWL()
            prowl.notify(pushmessage, "Issuarr metatagging error: ", module=module)

        if mylar.CONFIG.PUSHOVER_ENABLED:
            pushover = notifiers.PUSHOVER()
            pushover.notify(prline, prline2, module=module)

        if mylar.CONFIG.BOXCAR_ENABLED:
            boxcar = notifiers.BOXCAR()
            boxcar.notify(prline=prline, prline2=prline2, module=module)

        if mylar.CONFIG.PUSHBULLET_ENABLED:
            pushbullet = notifiers.PUSHBULLET()
            pushbullet.notify(prline=prline, prline2=prline2, module=module)

        if mylar.CONFIG.TELEGRAM_ENABLED:
            telegram = notifiers.TELEGRAM()
            telegram.notify(prline2)

        if mylar.CONFIG.SLACK_ENABLED:
            slack = notifiers.SLACK()
            slack.notify("Issuarr metatagging error: ", prline2, module=module)

        if mylar.CONFIG.MATTERMOST_ENABLED:
            mattermost = notifiers.MATTERMOST()
            mattermost.notify("Issuarr metatagging error: ", prline2, module=module)

        if mylar.CONFIG.DISCORD_ENABLED:
            discord = notifiers.DISCORD()
            discord.notify(filename, message, module=module)

        if mylar.CONFIG.EMAIL_ENABLED and mylar.CONFIG.EMAIL_ONPOST:
            logger.info("Sending email notification")
            email = notifiers.EMAIL()
            email.notify(prline2, "Issuarr metatagging error: ", module=module)

        if mylar.CONFIG.GOTIFY_ENABLED:
            gotify = notifiers.GOTIFY()
            gotify.notify("Issuarr metatagging error: ", prline2, module=module)
    except Exception as e:
        logger.warn('[NOTIFICATION] Unable to send notification: %s' % e)

    return
