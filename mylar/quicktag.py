"""A ComicInfo.xml built from what Issuarr already knows about an issue, for files that have none.

ComicTagger asks ComicVine for each issue, which is paced to stay under ComicVine's hourly
limit. The series and issue rows already hold the fields readers group by (series, volume,
number, count, date, publisher), so a file can be tagged from them without asking again.
The values match what tagging writes, so these files sort with the ones ComicTagger tagged.
"""

import datetime
import os
import zipfile
from xml.sax.saxutils import escape

import mylar
from mylar import db, logger, comicinfo


def tagged(path):
    """True when the file is a zip holding a ComicInfo.xml. Tags are never written into a RAR,
    so a .cbr counts as untagged: tagging makes it a .cbz first."""
    try:
        with zipfile.ZipFile(path) as z:
            return any(comicinfo._is_comicinfo(n) for n in z.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


def issue_for_path(path, myDB=None):
    """The issue row whose file is at path, joined with its series, or None. Annuals are left to
    ComicTagger: ComicVine lists them as series of their own, which the stored rows don't name."""
    myDB = myDB or db.DBConnection()
    folder = os.path.dirname(path)
    return myDB.selectone('SELECT i.IssueID, i.Issue_Number, i.IssueName, i.IssueDate, i.ReleaseDate, i.Description, c.ComicName, '
                          'c.ComicYear, c.ComicVersion, c.ComicPublisher, c.Total, c.AgeRating FROM issues i '
                          'JOIN comics c ON c.ComicID=i.ComicID WHERE i.Location=? AND c.ComicLocation IN (?, ?)',
                          [os.path.basename(path), folder, folder + os.sep]).fetchone()


def _blank(value):
    return value is None or str(value).strip() in ('', 'None')


def _date(row):
    """(year, month, day) from the cover date, else the release date. Zero parts are left out."""
    for value in (row['IssueDate'], row['ReleaseDate']):
        parts = str(value or '').split('-')
        if len(parts) == 3 and parts[0].isdigit() and int(parts[0]) > 0:
            return tuple(int(p) if p.isdigit() and int(p) > 0 else None for p in parts)
    return None, None, None


def _volume(row):
    from mylar import cmtagmylar
    if mylar.CONFIG.CMTAG_START_YEAR_AS_VOLUME and not _blank(row['ComicYear']):
        return cmtagmylar.volume_number(row['ComicYear'])
    return cmtagmylar.volume_number(row['ComicVersion'])


def build(row):
    """ComicInfo.xml bytes for an issue row from issue_for_path()."""
    from mylar import cmtagmylar
    publisher, imprint = cmtagmylar.series_publisher(row['IssueID'])
    year, month, day = _date(row)
    count = str(row['Total'] or '')
    issue_id = '[CVDB%s]' if mylar.CONFIG.CT_NOTES_FORMAT == 'CVDB' else '[Issue ID %s]'
    fields = [
        ('Title', row['IssueName']),
        ('Series', row['ComicName']),
        ('Number', row['Issue_Number']),
        ('Count', count if count.isdigit() and int(count) > 0 else None),
        ('Volume', _volume(row)),
        ('Summary', row['Description'] if 'Description' in row.keys() else None),
        ('Notes', 'Tagged by Issuarr from its stored ComicVine info on %s. %s' % (
            datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), issue_id % row['IssueID'])),
        ('Year', year),
        ('Month', month),
        ('Day', day),
        ('Publisher', publisher or row['ComicPublisher']),
        ('Imprint', imprint),
        ('Web', 'https://comicvine.gamespot.com/issue/4000-%s/' % row['IssueID']),
        ('AgeRating', row['AgeRating']),
    ]
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">']
    lines += ['  <%s>%s</%s>' % (tag, escape(str(value)), tag) for tag, value in fields if not _blank(value)]
    lines.append('</ComicInfo>')
    return ('\n'.join(lines) + '\n').encode('utf-8')


def fill(path, myDB=None, force=False):
    """Write a ComicInfo.xml from stored info into an issue file that has none. A .cbr is made a
    .cbz first, since only a zip can hold one, but only once it's known a tag will be written.
    Runs when tagging is on, or with force when someone asked for it. The file is held so WebP
    doesn't rewrite it meanwhile. Returns the file's path (a .cbr's new .cbz) when tags were
    written, else None."""
    from mylar import webp
    if not (force or mylar.CONFIG.ENABLE_META) or not os.path.isfile(path) or tagged(path):
        return None
    try:
        row = issue_for_path(path, myDB)
    except Exception as e:
        logger.fdebug('[TAGS] Unable to look up the issue for %s: %s' % (path, e))
        return None
    if row is None:
        return None
    with webp.claim(path) as mine:
        if not mine:
            return None    # being converted right now; WebP adds the tags itself
        if not path.lower().endswith('.cbz'):
            res = webp.to_cbz(path)
            if res['status'] != 'converted':
                logger.warn('[TAGS] %s was left as it is and not tagged: %s' % (os.path.basename(path), res['reason']))
                return None
            path = res['target']
        if not comicinfo.write(path, build(row)):
            return None
    logger.info('[TAGS] %s had no ComicInfo.xml - wrote one from the stored info for %s #%s.' % (
        os.path.basename(path), row['ComicName'], row['Issue_Number']))
    return path
