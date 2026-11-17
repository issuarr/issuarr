"""NZB queue worker and helpers."""

import time
from pathlib import Path

import mylar
from .. import logger, helpers
from mylar import sabnzbd, nzbget, db


def _cdh_client():
    if mylar.USE_SABNZBD is True and mylar.CONFIG.SAB_CLIENT_POST_PROCESSING is True:
        return 'sabnzbd'
    if mylar.USE_NZBGET is True and mylar.CONFIG.NZBGET_CLIENT_POST_PROCESSING is True:
        return 'nzbget'
    return None


def _still_snatched(myDB, issueid, issuearcid):
    if issueid is not None:
        rows = [myDB.selectone('SELECT Status FROM issues WHERE IssueID=?', [issueid]).fetchone(),
                myDB.selectone('SELECT Status FROM annuals WHERE IssueID=? AND NOT Deleted', [issueid]).fetchone()]
    else:
        rows = [myDB.selectone('SELECT Status FROM storyarcs WHERE IssueArcID=?', [issuearcid]).fetchone()]
    return any(r is not None and r['Status'] == 'Snatched' for r in rows)


def _download_info(myDB, key):
    r = myDB.selectone('SELECT PROVIDER, ID FROM nzblog WHERE IssueID=?', [key]).fetchone()
    if r is not None:
        return {'provider': r['PROVIDER'], 'id': r['ID']}
    r = myDB.selectone("SELECT Provider FROM snatched WHERE IssueID=? AND Status='Snatched' ORDER BY DateAdded DESC",
                       [key]).fetchone()
    return {'provider': r['Provider'] if r is not None else None, 'id': None}


def pending_jobs(myDB=None):
    """Queue items for Issuarr's own SABnzbd/NZBGet grabs whose issue is still Snatched. The
    completed-download queue only lives in memory, so these are lost when Issuarr restarts."""
    client = _cdh_client()
    if client is None:
        return []
    myDB = myDB or db.DBConnection()
    try:
        rows = myDB.select('SELECT IssueID, IssueArcID, ComicID, JobID FROM client_jobs WHERE Client=? ORDER BY DateAdded',
                           [client])
    except Exception:
        return []
    latest = {}
    for r in rows:
        key = r['IssueID'] if r['IssueID'] is not None else ('S%s' % r['IssueArcID'] if r['IssueArcID'] is not None else None)
        if key is not None and r['JobID']:
            latest[key] = r   # a later grab of the same issue replaces the earlier one
    items = []
    for key, r in latest.items():
        try:
            if not _still_snatched(myDB, r['IssueID'], r['IssueArcID']):
                continue
            info = _download_info(myDB, key)
        except Exception as e:
            logger.fdebug('[AUTO-COMPLETE-NZB] Could not check %s: %s' % (key, e))
            continue
        item = {'status': True, 'comicid': r['ComicID'], 'issueid': key, 'apicall': True, 'download_info': info}
        if client == 'sabnzbd':
            item['nzo_id'] = r['JobID']
            item['queue'] = {'mode': 'queue', 'search': r['JobID'], 'output': 'json', 'apikey': mylar.CONFIG.SAB_APIKEY}
        else:
            try:
                item['NZBID'] = int(r['JobID'])
            except ValueError:
                continue
        items.append(item)
    if items:
        from mylar import downloadqueue
        held = downloadqueue.client_has(client, [str(i.get('nzo_id') or i.get('NZBID')) for i in items])
        if held is not None:   # None: the client couldn't be asked, so keep them all
            items = [i for i in items if str(i.get('nzo_id') or i.get('NZBID')).lower() in held]
    return items


def requeue_pending(queue):
    """Put grabs sent before a restart back on the completed-download queue."""
    waiting = {str(i.get('nzo_id') or i.get('NZBID')) for i in list(queue.queue) if isinstance(i, dict)}
    added = 0
    for item in pending_jobs():
        if str(item.get('nzo_id') or item.get('NZBID')) not in waiting:
            queue.put(item)
            added += 1
    if added:
        logger.info('[AUTO-COMPLETE-NZB] Picked up %s grab(s) sent before the restart that are still waiting to be filed.' % added)
    return added


def nzb_monitor(queue):
    try:
        requeue_pending(queue)
    except Exception as e:
        logger.warn('[AUTO-COMPLETE-NZB] Could not pick up grabs sent before the restart: %s' % e)
    while True:
        if mylar.RETURN_THE_NZBQUEUE.qsize() >= 1:
            if mylar.USE_SABNZBD is True:
                sab_params = {
                    'apikey': mylar.CONFIG.SAB_APIKEY,
                    'mode': 'queue',
                    'start': 0,
                    'limit': 5,
                    'search': None,
                    'output': 'json',
                }
                s = sabnzbd.SABnzbd(params=sab_params)
                sabresponse = s.sender(chkstatus=True)
                if sabresponse['status'] is False:
                    while True:
                        if mylar.RETURN_THE_NZBQUEUE.qsize() >= 1:
                            qu_retrieve = mylar.RETURN_THE_NZBQUEUE.get(True)
                            try:
                                nzstat = s.historycheck(qu_retrieve)
                                cdh_monitor(queue, qu_retrieve, nzstat, readd=True)
                            except Exception as e:
                                logger.error('Exception occured trying to re-add %s to queue: %s' % (qu_retrieve, e))
                            time.sleep(5)
                        else:
                            break

        if queue.qsize() >= 1:
            item = queue.get(True)
            if item == 'exit':
                logger.info('Cleaning up workers for shutdown')
                break
            try:
                tmp_apikey = item['queue'].pop('apikey')
                logger.info('Now loading from queue: %s' % item)
            except Exception:
                logger.info('Now loading from queue: %s' % item)
            else:
                item['queue']['apikey'] = tmp_apikey
            if all([mylar.USE_SABNZBD is True, mylar.CONFIG.SAB_CLIENT_POST_PROCESSING is True]):
                nz = sabnzbd.SABnzbd(item)
                nzstat = nz.processor()
            elif all([mylar.USE_NZBGET is True, mylar.CONFIG.NZBGET_CLIENT_POST_PROCESSING is True]):
                nz = nzbget.NZBGet()
                nzstat = nz.processor(item)
            else:
                logger.warn('There are no NZB Completed Download handlers enabled. Not sending item to completed download handling...')
                break
            cdh_monitor(queue, item, nzstat)
        else:
            time.sleep(5)


def cdh_monitor(queue, item, nzstat, readd=False):
    known_nzb_id = item['nzo_id'] if (mylar.USE_SABNZBD is True) else item['NZBID']
    if any([nzstat['status'] == 'file not found', nzstat['status'] == 'double-pp']):
        logger.warn('Unable to complete post-processing call due to not finding file in the location provided. [%s]' % item)
    elif nzstat['status'] == 'nzb removed' or 'unhandled status' in str(nzstat['status']).lower():
        if readd is True:
            logger.warn('NZB seems to have been in a staging process within SABnzbd during attempt. Will requeue: %s.' % known_nzb_id)
            mylar.RETURN_THE_NZBQUEUE.put(item)
        else:
            logger.warn('NZB seems to have been removed from queue: %s' % known_nzb_id)
    elif nzstat['status'] == 'downloading':
        # still downloading: check it again after the other grabs
        item['checked'] = True
        time.sleep(2)
        if item not in queue.queue:
            mylar.NZB_QUEUE.put(item)
    elif nzstat['status'] == 'failed_in_sab':
        logger.warn('Failure returned from SAB for %s for some reason. You should probably check your SABnzbd logs' % known_nzb_id)
    elif nzstat['status'] == 'queue_paused':
        if mylar.USE_SABNZBD is True:
            logger.info('[PAUSED_SAB_QUEUE] adding %s to a temporary queue that will fire off when SABnzbd is unpaused' % item)
            mylar.RETURN_THE_NZBQUEUE.put(item)
    elif nzstat['status'] is False:
        logger.info('Download %s failed. Requeue NZB to check later...' % known_nzb_id)
        time.sleep(5)
        if item not in queue.queue:
            mylar.NZB_QUEUE.put(item)
    elif nzstat['status'] is True:
        if nzstat['failed'] is False and mylar.USE_SABNZBD is True:
            fullpath = Path(nzstat['location']) / nzstat['name']
            filecondition = helpers.check_file_condition(fullpath)
            if not filecondition['status']:
                logger.warn(f"CRC Check: File {fullpath} failed condition check ({filecondition['quality']}).  Marking as failed.")
                nzstat['failed'] = True

        if nzstat['failed'] is False:
            logger.info('File successfully downloaded - now initiating completed downloading handling.')
        else:
            logger.info('File failed either due to being corrupt or incomplete - now initiating completed failed downloading handling.')
        try:
            mylar.PP_QUEUE.put({
                'nzb_name':     nzstat['name'],
                'nzb_folder':   nzstat['location'],
                'failed':       nzstat['failed'],
                'issueid':      nzstat['issueid'],
                'comicid':      nzstat['comicid'],
                'apicall':      nzstat['apicall'],
                'ddl':          False,
                'download_info': nzstat['download_info'],
            })
        except Exception as e:
            logger.error('process error: %s' % e)
    return
