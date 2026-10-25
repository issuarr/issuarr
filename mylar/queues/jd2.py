"""JD2 queue worker."""

import datetime
import os
import re
import shutil
import threading
import time

import mylar
from .. import logger, helpers
from mylar import db, getcomics
from . import ddl
from mylar.downloaders.jdownloader2 import JDownloader2, local_folder, local_path, job_ids

# The record id of the item the monitor is working on. It's out of the queue while the monitor
# checks it and sleeps before putting it back, but it's still at JD2.
HOLDING = [None]
# Set once the monitor has put the rows saved with a JD2 job id back in its queue. Until then those
# rows are still JD2's even though at_jd2() doesn't list them yet.
LOADED = threading.Event()

# A JD2 job whose download hasn't moved for this long is given up on, whatever JD2 says about it.
# Long enough that a big, slow download still making progress is never cut short.
NO_PROGRESS_LIMIT = 6 * 60 * 60
NO_PROGRESS_TEXT = '6 hours'
# JD2 job id -> (last progress seen, when it last changed)
PROGRESS = {}

# How often JD2's download list is checked for finished downloads the user added with the comment.
PICKUP_EVERY = 60
LAST_PICKUP = [0.0]
# JD2 job ids Issuarr sent since it started. With the ones saved in ddl_info, they tell Issuarr's
# own packages from the user's, which carry the same comment.
SENT = set()
# Tagged user packages already sent to post-processing, or already warned about, by package uuid.
PICKED = set()
WARNED = set()


def at_jd2():
    """Record ids handed to JD2: waiting in its queue, or being checked by the monitor."""
    ids = ddl._ids(mylar.JD2_QUEUE)
    if HOLDING[0] is not None:
        ids.add(HOLDING[0])
    return ids


def loaded():
    """Whether at_jd2() lists every row JD2 has: the monitor has reloaded its saved rows, or JD2 is off."""
    return LOADED.is_set() or not getattr(mylar.CONFIG, 'JD2_ENABLE', False)


def jd2_queue_monitor(queue):
    jd2_client = JDownloader2()
    myDB = db.DBConnection()
    while True:
        if time.monotonic() - LAST_PICKUP[0] >= PICKUP_EVERY:
            LAST_PICKUP[0] = time.monotonic()
            pickup_user_downloads(jd2_client, myDB)
        if queue.qsize() >= 1:
            item = queue.get(True)
            HOLDING[0] = str(item.get('id') or item.get('ID')) if isinstance(item, dict) else None
            if item == 'exit':
                logger.info('[JD2-QUEUE] Cleaning up workers for shutdown')
                break
            if item == 'startup':
                try:
                    pending_jd2 = myDB.select(
                        "SELECT * FROM ddl_info WHERE jd2_job_id IS NOT NULL AND status = 'Queued'"
                    )

                except Exception as err:
                    logger.warn('[JD2-QUEUE] Unable to repopulate JD2 monitor queue: %s', err)
                else:
                    logger.info('[JD2-QUEUE] Repopulating JD2 monitor queue')
                    for job in pending_jd2 or []:
                        job_data = dict(job)
                        job_id = job_data.get('jd2_job_id')
                        record_id = job_data.get('ID') or job_data.get('id')
                        series = job_data.get('series')
                        year = job_data.get('year')
                        filename = job_data.get('tmp_filename') or job_data.get('filename')
                        if not filename:
                            if series and year:
                                filename = f"{series} ({year}) - {record_id}"
                            elif series:
                                filename = series
                            elif record_id:
                                filename = str(record_id)
                        queue_payload = {
                            'link': job_data.get('link'),
                            'mainlink': job_data.get('mainlink'),
                            'series': series,
                            'year': year,
                            'size': job_data.get('size'),
                            'comicid': job_data.get('comicid'),
                            'issueid': job_data.get('issueid'),
                            'oneoff': job_data.get('oneoff'),
                            'id': record_id,
                            'link_type': job_data.get('link_type'),
                            'filename': filename,
                            'comicinfo': job_data.get('comicinfo'),
                            'packinfo': job_data.get('packinfo'),
                            'site': job_data.get('site') or 'DDL(GetComics)',
                            'remote_filesize': job_data.get('remote_filesize') or 0,
                            'resume': None,
                            'jd2_job_id': job_id,
                        }
                        queue.put(queue_payload)
                LOADED.set()
                ddl.refile_unfiled(myDB)  # JD2 downloads that finished before a restart; once, whichever worker asks first
                continue

            if item.get('jd2_job_id') == 0:
                jd2_priority_links = resolve_links(item.get('jd2_priority_links'))
                queue_payload = dict(item)
                queue_payload.pop('jd2_job_id', None)
                queue_payload.pop('jd2_priority_links', None)
                if not jd2_priority_links:
                    logger.warn('Priority links don\'t exist; cannot process JD2 job. Falling back to DDL queue.')
                    mylar.DDL_QUEUE.put(queue_payload)
                    continue
                record_id = item.get('id') or item.get('ID')
                package_name = '%s (%s) - %s' % (item.get('series'), item.get('year'), record_id)
                submit_result = jd2_client.submit(jd2_priority_links, package_name, record_id)

                if not submit_result.get('status'):
                    logger.warn('[JD2] Submission failed for %s; falling back to DDL queue. Details: %s', package_name, submit_result)
                    mylar.DDL_QUEUE.put(queue_payload)
                else:
                    logger.debug('[JD2] Submission response for %s: %s', package_name, submit_result)
                    job_id = submit_result.get('jobid')
                    if not job_id:
                        mylar.DDL_QUEUE.put(queue_payload)
                        continue
                    queue_payload['jd2_job_id'] = job_id
                    SENT.update(job_ids(job_id))
                    mylar.JD2_QUEUE.put(queue_payload)
                    logger.info('[JD2] JD2 job %s submitted for %s', job_id, package_name)
                    time.sleep(10)
                    continue

            logger.info('[JD2-QUEUE] Now loading from queue: %s' % item)
            record_id = item.get('ID') or item.get('id')
            job_id = item.get('jd2_job_id')
            series = item.get('series')
            year = item.get('year')

            job_filename = None

            if jd2_client is not None and job_id:
                if jd2_job_unwanted(myDB, jd2_client, item, record_id, job_id):
                    continue
                try:
                    status_payload = jd2_client.status(job_id, record_id)
                except Exception as err:
                    logger.warn('[JD2-QUEUE] Error polling job %s: %s', job_id, err)
                else:
                    logger.info('[JD2-QUEUE] status update for job %s (record %s): %s', job_id, record_id, status_payload)
                    job_status = (status_payload or {}).get('status')
                    job_found = (status_payload or {}).get('found')

                    completed_states = {'FINISHED', 'Finished', 'finished', 'DONE', 'Done', 'Extraction OK', '[SHA256] CRC OK', 'Finished(Mirror)'}
                    failed_states = {'ERROR', 'FAILED', 'Error', 'Failed'}

                    if not job_found:
                        stale = False
                        try:
                            row = myDB.selectone("SELECT updated_date FROM ddl_info WHERE id=?", [record_id]).fetchone()
                        except Exception as err:
                            logger.warning('JD2 stale check failed for record %s: %s', record_id, err)
                            updated_str = None
                        else:
                            if row is None:
                                logger.info('[JD2-QUEUE] No ddl_info entry found for id %s; dropping job %s from monitoring.', record_id, job_id)
                                PROGRESS.pop(str(job_id), None)
                                continue
                            updated_str = row['updated_date']

                        if updated_str:
                            try:
                                updated_dt = datetime.datetime.strptime(updated_str, '%Y-%m-%d %H:%M')
                            except Exception:
                                stale = False
                            else:
                                stale = (datetime.datetime.now() - updated_dt) >= datetime.timedelta(minutes=3)

                        if stale:
                            jd2_give_up(myDB, item, record_id, 'job %s never reached the JD2 download list (links offline or rejected)' % job_id)
                            continue

                        queue.put(item)
                        time.sleep(10)
                        continue

                    job_filename = ((status_payload or {}).get('data') or {}).get('name')
                    if job_status in completed_states and not is_comic_name(job_filename):
                        # JD2 finished on something else - a script or page from the post - not the comic
                        logger.warn('[JD2-QUEUE] JD2 finished %s with %s, which is not a comic.', record_id, job_filename)
                        jd2_client.remove(job_id, record_id)
                        jd2_give_up(myDB, item, record_id, 'JD2 downloaded %s, not a comic' % job_filename)
                        continue

                    if job_status in completed_states:
                        PROGRESS.pop(str(job_id), None)
                        # the file is downloaded, so it's post-processed even if the row went while JD2 was asked
                        jd2_set_row(myDB, record_id, {'status': 'Completed',
                                                      'updated_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')})
                        logger.info('[JD2-QUEUE] Download for %s completed; status marked as Completed.', record_id)

                        if not isinstance(item, dict):
                            logger.warn('[JD2-QUEUE] Unexpected item type %s for job %s; skipping post-processing.', type(item), job_id)
                            continue
                        if mylar.CONFIG.POST_PROCESSING is True:
                            dest_root = local_folder()
                            # the folder JD2 really used, where the file that finished is; it can name the
                            # package after the post's own folder, or put it in a dated subfolder
                            package = ((status_payload or {}).get('data') or {}).get('packageUUID')
                            nzb_folder = jd2_folder(jd2_client, job_id, record_id, package) or os.path.join(dest_root, (
                                "%s - %s" % (item.get('filename'), record_id)
                                if item.get('filename')
                                else "%s (%s) - %s" % (series, year, record_id)
                            ))
                            folder_name = os.path.basename(nzb_folder.rstrip(os.sep))
                            pack = ddl.is_pack(dict(item, id=record_id), myDB)
                            # a pack that came as many files is filed as a whole folder against the series;
                            # one that came as a single zip is unpacked by post-processing as before
                            whole_folder = bool(pack) and ((status_payload or {}).get('files') or 1) > 1
                            nzb_name = folder_name if whole_folder else (job_filename or 'Manual Run')
                            if not pack and job_filename and os.path.isfile(os.path.join(nzb_folder, job_filename)):
                                # just this file: a shared folder (a dated one) can hold other downloads too
                                nzb_folder = os.path.join(nzb_folder, job_filename)

                            if nzb_folder:
                                # read before the job leaves JD2's list: the other mirrors' copies and part files
                                files = jd2_files(jd2_client, job_id, record_id)
                                try:
                                    mylar.PP_QUEUE.put({
                                        'nzb_name': nzb_name,
                                        'nzb_folder': nzb_folder,
                                        'failed': False,
                                        'issueid': None if whole_folder else item.get('issueid'),
                                        'comicid': item.get('comicid'),
                                        'apicall': True,
                                        'ddl': True,
                                        'pack': pack,
                                        'download_info': {'provider': 'JD2', 'id': record_id, 'job_id': job_id,
                                                          'issueid': item.get('issueid'), 'files': files},
                                    })
                                    logger.info('[JD2-QUEUE] Submitted %s for post-processing (folder: %s).', nzb_name, nzb_folder)
                                    jd2_client.remove(job_id, record_id)
                                except Exception as err:
                                    logger.warn('[JD2-QUEUE] Unable to enqueue %s for post-processing: %s', job_filename, err)
                            else:
                                logger.warn('[JD2-QUEUE] JD2 destination is not configured; skipping post-processing enqueue for %s.', job_filename)
                        else:
                            logger.info('[JD2-QUEUE] Post-processing disabled, please manually handle your files.')
                        continue

                    if job_status in failed_states or jd2_status_is_dead(job_status):
                        reason = (status_payload or {}).get('reason') or job_status
                        logger.warn('[JD2-QUEUE] Download %s can not complete in JD2 (%s).', job_filename or record_id, reason)
                        jd2_client.remove(job_id, record_id)
                        jd2_give_up(myDB, item, record_id, 'JD2 status %s' % reason)
                        continue

                    progress = (status_payload or {}).get('loaded')
                    if progress is None:
                        progress = job_status
                    if jd2_waiting(status_payload):
                        PROGRESS.pop(str(job_id), None)  # its clock starts when JD2 starts on it
                    elif progress is not None and jd2_no_progress(job_id, progress):
                        logger.warn('[JD2-QUEUE] Download %s has made no progress in JD2 for %s (%s).', job_filename or record_id, NO_PROGRESS_TEXT, job_status)
                        jd2_client.remove(job_id, record_id)
                        jd2_give_up(myDB, item, record_id, 'no progress in JD2 for %s' % NO_PROGRESS_TEXT)
                        continue

                    if job_status not in completed_states:
                        time.sleep(10)
                        queue.put(item)
                        continue
            else:
                logger.warn('[JD2-QUEUE] Missing JD2 client or job id for item: %s', item)
                jd2_give_up(myDB, item, record_id, 'no JD2 job id to monitor')
        else:
            HOLDING[0] = None
            time.sleep(10)


def jd2_folder(jd2_client, job_id, record_id, package=None):
    folder = getattr(jd2_client, 'folder', None)
    return folder(job_id, record_id, package) if folder else None


def jd2_files(jd2_client, job_id, record_id):
    files = getattr(jd2_client, 'files', None)
    return files(job_id, record_id) if files else []


def own_package(package, own_jobs, own_records):
    """Whether a JD2 package is one Issuarr sent: a link carries one of its job ids, or it still has
    the name Issuarr gave it, 'Series (Year) - <record id>'."""
    if any(str(l.get('jobUUID')) in own_jobs for l in package.get('links') or [] if l.get('jobUUID') is not None):
        return True
    m = re.search(r' - ([^ ]+)$', str(package.get('name') or ''))
    return bool(m) and m.group(1) in own_records


def package_finished(package):
    """Whether JD2 is done with every link of a package: at least one finished, the rest finished or
    dead, and nothing still being unpacked."""
    links = [l for l in package.get('links') or [] if l.get('enabled') is not False]
    if not links:
        return False
    st = lambda l: str(l.get('status') or '').lower()
    done = lambda l: l.get('finished') is True or any(d in st(l) for d in JDownloader2.DONE)
    dead = lambda l: any(d in st(l) for d in JDownloader2.DEAD)
    extracting = lambda l: 'extract' in st(l) and not any(x in st(l) for x in ('ok', 'error', 'fail'))
    if any(extracting(l) for l in links):
        return False
    return any(done(l) for l in links) and all(done(l) or dead(l) for l in links)


def user_folder(package):
    """The folder Issuarr should file a finished user package from, as Issuarr sees it. A folder of
    its own is used as it is. When the package shares a folder (JD2's download folder itself, or one
    holding other things), its files are moved into a folder of their own first, so filing never
    touches anything else there. None when none of its files can be found."""
    folder = local_path(package.get('saveTo'))
    if not folder or not os.path.isdir(folder):
        return None
    names = {str(l.get('name')) for l in package.get('links') or [] if l.get('name')}
    present = sorted(n for n in names if os.path.isfile(os.path.join(folder, n)))
    if not present:
        return None
    root = local_folder()
    shared = (root and os.path.normpath(folder) == os.path.normpath(root)) or not set(os.listdir(folder)) <= names
    if not shared:
        return folder
    own = os.path.join(folder, 'Issuarr - %s' % (re.sub(r'[\\/:*?"<>|]', '_', str(package.get('name') or package.get('uuid'))).strip() or package.get('uuid')))
    os.makedirs(own, exist_ok=True)
    for n in present:
        shutil.move(os.path.join(folder, n), os.path.join(own, n))
    return own


def pickup_user_downloads(jd2_client, myDB):
    """File downloads the user added to JD2 with the comment 'issuarr', once JD2 has finished them,
    then take them off JD2's list. Issuarr's own packages carry the comment too; they're left to the
    monitor, which follows them by job id."""
    if not getattr(mylar.CONFIG, 'POST_PROCESSING', False) or not hasattr(jd2_client, 'tagged_packages'):
        return
    try:
        packages = jd2_client.tagged_packages()
    except Exception as err:
        logger.fdebug('[JD2-QUEUE] Unable to check JD2 for downloads marked "issuarr": %s' % err)
        return
    if not packages:
        return
    try:
        rows = myDB.select('SELECT ID, jd2_job_id FROM ddl_info') or []
    except Exception as err:
        logger.warn('[JD2-QUEUE] Unable to read the direct download queue, not checking JD2 for your own downloads: %s', err)
        return
    own_jobs = set(SENT)
    own_records = set()
    for row in rows:
        own_records.add(str(row['ID']))
        own_jobs.update(job_ids(row['jd2_job_id']))
    for package in packages:
        uuid = package.get('uuid')
        if uuid in PICKED or own_package(package, own_jobs, own_records) or not package_finished(package):
            continue
        name = package.get('name') or uuid
        try:
            folder = user_folder(package)
        except Exception as err:
            folder = None
            logger.warn('[JD2-QUEUE] Unable to set aside the files of %s for filing: %s', name, err)
        if not folder:
            if uuid not in WARNED:
                WARNED.add(uuid)
                logger.warn('[JD2-QUEUE] JD2 finished %s (marked "issuarr"), but Issuarr can\'t find its files under %s.'
                            ' Check "Same folder, as Issuarr sees it" under Settings > Download clients > JDownloader 2.',
                            name, local_path(package.get('saveTo')) or package.get('saveTo'))
            continue
        PICKED.add(uuid)
        logger.info('[JD2-QUEUE] JD2 finished %s, which you marked "issuarr" - filing it from %s.', name, folder)
        mylar.PP_QUEUE.put({'nzb_name': 'Manual Run', 'nzb_folder': folder, 'failed': False, 'issueid': None,
                            'comicid': None, 'apicall': False, 'ddl': False, 'download_info': None})
        try:
            jd2_client.remove_packages([uuid])
        except Exception as err:
            logger.warn('[JD2-QUEUE] Unable to take %s off JD2\'s download list: %s', name, err)


COMIC_FILES = ('.cbz', '.cbr', '.cb7', '.cbt', '.pdf', '.zip', '.rar', '.7z')


def is_comic_name(name):
    """Whether a finished JD2 file could be a comic. An unknown name gets the benefit of the doubt."""
    if not name:
        return True
    return str(name).lower().endswith(COMIC_FILES)


def resolve_links(links):
    """{GetComics button: priority} -> {file host address: priority}. JD2 can't follow the
    buttons itself, and downloads a script from the page instead. Buttons that lead nowhere are dropped."""
    if not links:
        return links
    # a link to a GetComics post isn't a download: JD2 would crawl the page and every post it links to
    links = {u: p for u, p in links.items() if not getcomics.post_path(u)}
    if not any(getcomics.is_redirect_link(u) for u in links):
        return links
    gc = getcomics.GC()
    out = {}
    for url, priority in links.items():
        real = gc.resolve_link(url)
        if real:
            out.setdefault(real, priority)
        else:
            logger.info('[JD2] Dropping a download button that leads nowhere: %s', url[:60])
    return out


JD2_DEAD_STATUS = ('offline', 'file not found', 'not available', 'plugin defect', 'aborted', 'blocked by cloudflare',
                   'hosting period', 'only paid users')


def jd2_no_progress(job_id, progress, now=None):
    """Whether a JD2 job's progress (bytes downloaded, or its status when JD2 doesn't say) has
    stayed the same for NO_PROGRESS_LIMIT seconds."""
    now = time.monotonic() if now is None else now
    last = PROGRESS.get(str(job_id))
    if last is None or last[0] != progress:
        PROGRESS[str(job_id)] = (progress, now)
        return False
    return now - last[1] >= NO_PROGRESS_LIMIT


def jd2_waiting(status_payload):
    """Whether the job is in JD2's download list but JD2 isn't working on it: it's waiting its turn
    behind other downloads, or JD2 is stopped. JD2 gives such a link no status, which the client
    reports as 'Queued'. That's waiting, not stuck, so the no-progress clock doesn't run."""
    payload = status_payload or {}
    return payload.get('status') == 'Queued' and payload.get('loaded') is not None


def jd2_job_unwanted(myDB, jd2_client, item, record_id, job_id):
    """Stop following a JD2 job the queue no longer wants: the item was removed or aborted, or
    Restart sent it somewhere else. Removes only this job from JD2 and drops the item, so it isn't
    polled forever or given up on into a row the user deleted."""
    why = jd2_unwanted_reason(myDB, record_id, job_id)
    if not why:
        return False
    logger.info('[JD2-QUEUE] Stopped following JD2 job %s for %s: %s.', job_id, item.get('series') or record_id, why)
    jd2_client.remove(job_id)  # this job only: a newer job for the same item carries on
    jd2_drop(item, record_id)
    return True


def jd2_unwanted_reason(myDB, record_id, job_id):
    if str(record_id) in mylar.DDL_CANCEL:
        return 'it was removed or aborted'
    try:
        row = myDB.selectone('SELECT status, jd2_job_id FROM ddl_info WHERE id=?', [record_id]).fetchone()
    except Exception as err:
        logger.warn('[JD2-QUEUE] Unable to check %s is still queued: %s', record_id, err)
        return None
    if row is None:
        return 'it was removed from the queue'
    if row['status'] != 'Queued':
        return 'it is now %s' % row['status']
    if str(row['jd2_job_id']) != str(job_id):
        return 'it was sent again as job %s' % row['jd2_job_id']
    return None


def jd2_drop(item, record_id):
    """Let go of an item without queueing it anywhere else."""
    if HOLDING[0] == str(record_id):
        HOLDING[0] = None
    PROGRESS.pop(str(item.get('jd2_job_id')), None)
    if str(record_id) in mylar.DDL_CANCEL:
        # clears the cancel, so a later grab of the same post isn't dropped, and undoes a pack's Snatched issues
        ddl.ddl_cancelled(dict(item, id=record_id, series=item.get('series') or record_id, comicid=item.get('comicid')))


def jd2_set_row(myDB, record_id, values):
    """Update the ddl_info row while it's still Queued, never create it: a download the user
    removed or aborted while JD2 was being asked stays that way. False when it's no longer ours."""
    cols = ', '.join('%s=?' % k for k in values)
    result = myDB.action("UPDATE ddl_info SET %s WHERE id=? AND status='Queued'" % cols, list(values.values()) + [record_id])
    return result is None or result.rowcount != 0


def jd2_give_up(myDB, item, record_id, reason):
    """JD2 couldn't finish the download. The DDL failover worker tries Issuarr's own downloaders
    for the same post, file hosts first for big files, and never JD2 again. Only when direct
    downloads are off, or the post can't be read again, is the issue marked Failed here."""
    job_id = item.get('jd2_job_id')
    PROGRESS.pop(str(job_id), None)
    if str(record_id) in mylar.DDL_CANCEL:
        # aborted or removed while JD2 was being asked
        logger.info('[JD2-QUEUE] Not retrying %s (%s): it was removed or aborted.', item.get('series') or record_id, reason)
        jd2_drop(item, record_id)
        return
    try:
        row = myDB.selectone('SELECT jd2_job_id FROM ddl_info WHERE id=?', [record_id]).fetchone()
    except Exception as err:
        logger.warn('[JD2-QUEUE] Unable to check the JD2 job for %s: %s', record_id, err)
        row = False  # unknown, carry on
    if row is None:
        logger.info('[JD2-QUEUE] Not retrying %s (%s): it was removed from the queue.', item.get('series') or record_id, reason)
        jd2_drop(item, record_id)
        return
    current = row['jd2_job_id'] if row else None
    if job_id and current and str(current) != str(job_id):
        # Restart sent the item to JD2 again; the newer job carries on.
        logger.info('[JD2-QUEUE] Ignoring JD2 job %s for %s: it was replaced by job %s.', job_id, item.get('series') or record_id, current)
        return
    if HOLDING[0] == str(record_id):
        HOLDING[0] = None  # let go of it, or failover would think JD2 still has it
    if not item.get('mainlink') or not getattr(mylar.CONFIG, 'ENABLE_DDL', False):
        jd2_mark_failed(myDB, item, record_id, reason)
        return
    logger.info('[JD2-QUEUE] JD2 gave up on %s (%s) - trying Issuarr\'s own downloaders.', item.get('series') or record_id, reason)
    payload = dict(item)
    for k in ('jd2_job_id', 'jd2_priority_links', 'main_link'):
        payload.pop(k, None)
    payload['id'] = record_id
    payload.setdefault('resume', None)
    try:
        kept = jd2_set_row(myDB, record_id, {'status': 'Queued', 'jd2_job_id': None,
                                             'updated_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')})
    except Exception as err:
        logger.warn('[JD2-QUEUE] Unable to reset %s for the built-in downloaders: %s', record_id, err)
    else:
        if not kept:
            logger.info('[JD2-QUEUE] Not retrying %s: it was removed or aborted.', item.get('series') or record_id)
            jd2_drop(item, record_id)
            return
    ddl.send_to_failover(payload, {'success': False, 'reason': reason}, jd2_gave_up=True)


def jd2_status_is_dead(job_status):
    if not job_status:
        return False
    return any(x in str(job_status).lower() for x in JD2_DEAD_STATUS)


def jd2_mark_failed(myDB, item, record_id, reason):
    # mark both the ddl_info row and the issue itself Failed, so the issue doesn't sit at Snatched forever
    if str(record_id) in mylar.DDL_CANCEL:
        logger.info('[JD2-QUEUE] Not marking %s Failed (%s): it was removed or aborted.', item.get('series') or record_id, reason)
        jd2_drop(item, record_id)
        return
    logger.info('[JD2-QUEUE] Giving up on %s: %s', item.get('series') or record_id, reason)
    try:
        kept = jd2_set_row(myDB, record_id, {'status': 'Failed',
                                             'updated_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')})
    except Exception as err:
        logger.warn('[JD2-QUEUE] Unable to mark ddl_info %s as Failed: %s', record_id, err)
    else:
        if not kept:
            logger.info('[JD2-QUEUE] Not marking %s Failed: it was removed or aborted.', item.get('series') or record_id)
            jd2_drop(item, record_id)
            return

    issueid = item.get('issueid') or item.get('IssueID')
    comicid = item.get('comicid') or item.get('ComicID')
    pack = bool(item.get('pack'))
    try:
        pack = pack or item['comicinfo'][0]['pack'] is True
    except Exception:
        pass
    if not issueid and record_id:
        try:
            row = myDB.selectone('SELECT issueid, comicid, pack FROM ddl_info WHERE id=?', [record_id]).fetchone()
        except Exception:
            row = None
        if row is not None:
            issueid = row['issueid']
            comicid = comicid or row['comicid']
            pack = pack or bool(row['pack'])

    if pack:
        helpers.reverse_the_pack_snatch(record_id, comicid)
    elif all([issueid, issueid != 'None', not item.get('oneoff')]):
        try:
            mylar.search.FailedMark(issueid, comicid, record_id, item.get('series') or str(record_id), item.get('site') or 'DDL(GetComics)', retry=True)
        except Exception as err:
            logger.warn('[JD2-QUEUE] Unable to mark issueid %s as Failed: %s', issueid, err)
