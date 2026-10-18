import os
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from mylar import logger

CT_FIELDS = {'Title', 'Series', 'Number', 'Count', 'Volume', 'AlternateSeries', 'AlternateNumber', 'AlternateCount',
             'Summary', 'Notes', 'Year', 'Month', 'Day', 'Writer', 'Penciller', 'Inker', 'Colorist', 'Letterer',
             'CoverArtist', 'Editor', 'Publisher', 'Imprint', 'Genre', 'Web', 'PageCount', 'LanguageISO', 'Format',
             'Manga', 'Characters', 'Teams', 'Locations', 'ScanInformation', 'StoryArc', 'StoryArcNumber',
             'SeriesGroup', 'AgeRating'}
MODES = ('fill', 'skip', 'overwrite')


def tag_mode():
    import mylar
    mode = (getattr(mylar.CONFIG, 'CT_TAG_MODE', None) or '').lower()
    if mode in MODES:
        return mode
    return 'overwrite' if getattr(mylar.CONFIG, 'CT_CBZ_OVERWRITE', False) else 'fill'


def _is_comicinfo(name):
    return name.replace('\\', '/').rsplit('/', 1)[-1].lower() == 'comicinfo.xml'


def _pick(names):
    found = [n for n in names if _is_comicinfo(n)]
    if not found:
        return None
    return min(found, key=lambda n: n.count('/'))


def read_raw(path):
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                name = _pick(z.namelist())
                return z.read(name) if name else None
        from lib.rarfile import rarfile
        if rarfile.is_rarfile(path):
            with rarfile.RarFile(path) as rf:
                name = _pick([i.filename for i in rf.infolist() if not i.is_dir()])
                return rf.read(name) if name else None
    except Exception as e:
        logger.fdebug('[COMICINFO] Unable to read ComicInfo from %s: %s' % (path, e))
    return None


def _decode(raw):
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16'), 'utf-16'
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw[3:].decode('utf-8'), 'utf-8-sig'
    return raw.decode('utf-8'), 'utf-8'


def _blank(el):
    return not (el.text or '').strip() and len(el) == 0


def _element_text(tag, el):
    attrs = ''.join(' %s="%s"' % (k, escape(v, {'"': '&quot;'})) for k, v in el.attrib.items())
    return '<%s%s>%s</%s>' % (tag, attrs, escape((el.text or '').strip()), tag)


def _span(text, tag):
    m = re.search(r'<%s(\s[^>]*)?/>|<%s(\s[^>]*)?>(.*?)</%s\s*>' % (tag, tag, tag), text, re.S)
    return m


def merge(original, tagged, mode='fill'):
    if original is None:
        return tagged, [], []
    if tagged is None:
        return original, [], []
    try:
        new_root = ET.fromstring(tagged)
    except ET.ParseError:
        return original, [], []
    try:
        old_root = ET.fromstring(original)
        text, enc = _decode(original)
    except (ET.ParseError, UnicodeDecodeError, ValueError):
        logger.warn('[COMICINFO] The existing ComicInfo.xml could not be read, so the newly tagged one is used.')
        return tagged, ['(all)'], []
    old = {}
    for child in old_root:
        old.setdefault(child.tag, child)
    added, replaced, append = [], [], []
    for child in new_root:
        if child.tag in ('Pages',) or _blank(child):
            continue
        cur = old.get(child.tag)
        if cur is None:
            append.append(_element_text(child.tag, child))
            added.append(child.tag)
            continue
        if len(cur) or len(child):
            continue
        if _blank(cur) or (mode == 'overwrite' and child.tag in CT_FIELDS and (cur.text or '').strip() != (child.text or '').strip()):
            m = _span(text, child.tag)
            if not m:
                continue
            text = text[:m.start()] + _element_text(child.tag, child) + text[m.end():]
            (added if _blank(cur) else replaced).append(child.tag)
    if not added and not replaced:
        return original, [], []
    if append:
        text = _append(text, append)
        if text is None:
            return original, [], []
    out = _encode(text, enc)
    if out is None:
        return original, [], []
    return out, added, replaced


def _append(text, elements):
    close = text.rfind('</ComicInfo>')
    if close < 0:
        return None
    indent = '  '
    prev = re.search(r'\n([ \t]+)<', text)
    if prev:
        indent = prev.group(1)
    before = text[:close].rstrip(' \t')
    if not before.endswith('\n'):
        before += '\n'
    return before + ''.join('%s%s\n' % (indent, a) for a in elements) + text[close:]


def _encode(text, enc):
    out = text.encode('utf-8') if enc == 'utf-8' else (b'\xef\xbb\xbf' + text.encode('utf-8') if enc == 'utf-8-sig' else text.encode(enc))
    try:
        ET.fromstring(out)
    except ET.ParseError:
        return None
    return out


def adjust(path, fields=None, notes_format=None):
    """Set fields ComicTagger can't write (such as StoryArcNumber) in a tagged file's
    ComicInfo.xml, and switch the notes to the [CVDBnnn] form when that is chosen."""
    raw = read_raw(path)
    if raw is None:
        return False
    try:
        root = ET.fromstring(raw)
        text, enc = _decode(raw)
    except (ET.ParseError, UnicodeDecodeError, ValueError):
        return False
    fields = dict(fields or {})
    if notes_format == 'CVDB':
        notes = root.findtext('Notes') or ''
        cvdb = re.sub(r'\[Issue ID (\d+)\]', r'[CVDB\1]', notes)
        if cvdb != notes:
            fields['Notes'] = cvdb
    append = []
    for tag, value in fields.items():
        if value is None:
            continue
        el = ET.Element(tag)
        el.text = str(value)
        m = _span(text, tag)
        if m:
            text = text[:m.start()] + _element_text(tag, el) + text[m.end():]
        else:
            append.append(_element_text(tag, el))
    if append:
        text = _append(text, append)
        if text is None:
            return False
    out = _encode(text, enc)
    if out is None or out == raw:
        return out is not None
    return write(path, out)


def write(path, data):
    tmp = os.path.join(os.path.dirname(path), '.%s.cix-tmp' % os.path.basename(path))
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            name = _pick([i.filename for i in infos]) or 'ComicInfo.xml'
            with zipfile.ZipFile(tmp, 'w', allowZip64=True) as zo:
                zo.comment = z.comment
                done = False
                for info in infos:
                    zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                    zi.compress_type = info.compress_type
                    zi.external_attr = info.external_attr
                    if info.filename == name:
                        zi.compress_type = zipfile.ZIP_DEFLATED
                        zo.writestr(zi, data)
                        done = True
                    else:
                        zo.writestr(zi, b'' if info.filename.endswith('/') else z.read(info))
                if not done:
                    zi = zipfile.ZipInfo(name, date_time=infos[0].date_time if infos else (1980, 1, 1, 0, 0, 0))
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zo.writestr(zi, data)
        with zipfile.ZipFile(path) as a, zipfile.ZipFile(tmp) as b:
            for info in a.infolist():
                if info.filename != name and not info.filename.endswith('/') and a.read(info) != b.read(info.filename):
                    raise ValueError('%s changed' % info.filename)
            if b.read(name) != data:
                raise ValueError('ComicInfo was not written')
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
        return True
    except Exception as e:
        logger.warn('[COMICINFO] Unable to update ComicInfo in %s: %s' % (os.path.basename(path), e))
        return False
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def keep_existing(original, path, mode):
    if original is None or mode == 'skip':
        return True
    tagged = read_raw(path)
    out, added, replaced = merge(original, tagged, mode)
    if out == tagged:
        return True
    if not write(path, out):
        return False
    if added or replaced:
        logger.info('[COMICINFO] %s: kept the existing tags%s%s.' % (
            os.path.basename(path), ', added %s' % ', '.join(added) if added else '',
            ', updated %s' % ', '.join(replaced) if replaced else ''))
    else:
        logger.info('[COMICINFO] %s: nothing new from ComicVine - the existing tags were kept as they were.' % os.path.basename(path))
    return True
