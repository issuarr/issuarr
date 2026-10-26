import mylar
from mylar import db, logger, helpers, updater, filechecker, webp
import os
import shutil
import ast

def movefiles(comicid, comlocation, imported):
    #comlocation is destination
    #comicid is used for rename
    files_moved = []
    try:
        imported = ast.literal_eval(imported)
    except ValueError:
        pass

    myDB = db.DBConnection()

    logger.fdebug('comlocation is : ' + comlocation)
    logger.fdebug('original comicname is : ' + imported['ComicName'])

    impres = imported['filelisting']

    if impres is not None:
        if all([mylar.CONFIG.CREATE_FOLDERS is False, not os.path.isdir(comlocation)]):
            checkdirectory = filechecker.validateAndCreateDirectory(comlocation, True)
            if not checkdirectory:
                logger.warn('Error trying to validate/create directory. Aborting this process at this time.')
                return

        for impr in impres:
            srcimp = impr['comiclocation']
            orig_filename = impr['comicfilename']
            #before moving check to see if Rename to Mylar structure is enabled.
            if mylar.CONFIG.IMP_RENAME and mylar.CONFIG.FILE_FORMAT != '':
                logger.fdebug("Renaming files according to configuration details : " + str(mylar.CONFIG.FILE_FORMAT))
                renameit = helpers.rename_param(comicid, imported['ComicName'], impr['issuenumber'], orig_filename)
                if renameit is None:
                    # no matching issue in the series (e.g. a collected edition): file it under its own name
                    logger.warn('[IMPORT] No issue %s in %s to name %s after - keeping its own filename.' % (impr['issuenumber'], imported['ComicName'], orig_filename))
                    dstimp = os.path.join(comlocation, orig_filename)
                else:
                    dstimp = os.path.join(comlocation, renameit['nfilename'])
            else:
                logger.fdebug("Renaming files not enabled, keeping original filename(s)")
                dstimp = os.path.join(comlocation, orig_filename)

            logger.info("moving " + srcimp + " ... to " + dstimp)
            try:
                shutil.move(srcimp, dstimp)
            except (OSError, IOError):
                logger.error("Failed to move files - check directories and manually re-run.")
            else:
                files_moved.append({'srid':       imported['srid'],
                                    'filename':   impr['comicfilename'],
                                    'import_id':  impr.get('import_id'),
                                    'dest':       convert(dstimp)})

        logger.fdebug("all files moved.")
        #now that it's moved / renamed ... we remove it from importResults or mark as completed.

    if len(files_moved) > 0:
        logger.info('files_moved: ' + str(files_moved))
        for result in files_moved:
            if result['import_id'] is None:
                #if it's an 'older' import that wasn't imported, just make it a basic match so things can move and update properly.
                controlValue = {"ComicFilename": result['filename'],
                                "SRID":          result['srid']}
                newValue = {"Status":            "Imported",
                            "ComicID":           comicid}
            else:
                controlValue = {"impID":         result['import_id'],
                                "ComicFilename": result['filename']}
                newValue = {"Status":            "Imported",
                            "SRID":              result['srid'],
                            "ComicID":           comicid}
            # where the file is now, so Import results can tell whether an issue points to it
            newValue['ComicLocation'] = result['dest']
            myDB.upsert("importresults", newValue, controlValue)
    return

def convert(path):
    """Give an imported file what a download gets when it's filed: a .cbr becomes a .cbz
    when CBR to CBZ or metadata tagging is on, then WebP on import if that's on."""
    if path.lower().endswith('.cbr') and any([mylar.CONFIG.ENABLE_META, mylar.CONFIG.CBR2CBZ_ONLY]):
        res = webp.to_cbz(path)
        if res['status'] == 'converted':
            logger.info('[IMPORT] %s %s to %s' % ('Repacked' if res['repacked'] else 'Renamed', os.path.basename(path), os.path.basename(res['target'])))
            path = res['target']
        else:
            logger.warn('[IMPORT] Left %s as a .cbr: %s' % (os.path.basename(path), res['reason']))
    webp.after_import(path)
    return path

def tag_imported(comicid):
    """Tag an imported series' files that have no ComicInfo.xml, from the stored issue info, when
    tagging is on - as filing a download tags it. Imported files are never post-processed, so
    without this only a series' downloads carry tags and readers that group by ComicInfo.xml
    (Kavita, Komga) list the imported issues as a separate series. No ComicVine lookups."""
    from mylar import quicktag
    if not mylar.CONFIG.ENABLE_META:
        return []
    myDB = db.DBConnection()
    comic = myDB.selectone('SELECT ComicLocation FROM comics WHERE ComicID=?', [comicid]).fetchone()
    if not comic or not comic['ComicLocation']:
        return []
    done = []
    for row in myDB.select('SELECT Location FROM issues WHERE ComicID=? AND Location IS NOT NULL', [comicid]):
        path = quicktag.fill(os.path.join(comic['ComicLocation'], row['Location']), myDB)
        if path:
            done.append(path)
    if done:
        logger.info('[IMPORT] Tagged %s imported file%s that had no ComicInfo.xml.' % (len(done), '' if len(done) == 1 else 's'))
        updater.forceRescan(comicid)
    return done


def archivefiles(comicid, comlocation, imported):
    myDB = db.DBConnection()
    # if move files isn't enabled, let's set all found comics to Archive status :)
    try:
        imported = ast.literal_eval(imported)
    except Exception as e:
        logger.warn('[%s] Error encountered converting import data' % e)

    ComicName = imported['ComicName']
    impres = imported['filelisting']

    if impres is not None:
        scandir = []
        for impr in impres:
            srcimp = impr['comiclocation']
            orig_filename = impr['comicfilename']

            if not any([os.path.abspath(os.path.join(srcimp, os.pardir)) == x for x in scandir]):
                scandir.append(os.path.abspath(os.path.join(srcimp, os.pardir)))


        for sdir in scandir:
            logger.info('Updating issue information and setting status to Archived for location: ' + sdir)
            updater.forceRescan(comicid, archive=sdir) #send to rescanner with archive mode turned on

        logger.info('Now scanning in files.')
        updater.forceRescan(comicid)

        for result in impres:
            try:
                res = result['import_id']
            except:
                #if it's an 'older' import that wasn't imported, just make it a basic match so things can move and update properly.
                controlValue = {"ComicFilename": result['comicfilename'],
                                "SRID":          imported['srid']}
                newValue = {"Status":            "Imported",
                            "ComicID":           comicid}
            else:
                controlValue = {"impID":         result['import_id'],
                                "ComicFilename": result['comicfilename']}
                newValue = {"Status":            "Imported",
                            "SRID":              imported['srid'],
                            "ComicID":           comicid}
            myDB.upsert("importresults", newValue, controlValue)


    return
