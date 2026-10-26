import http.server
import importlib.util
import io
import json
import os
import shutil
import stat
import struct
import threading
import types
import zipfile
import zlib
import xml.etree.ElementTree as ET

import pytest

import mylar
from mylar import cmtagmylar, comicinfo, cv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
needs_ct = pytest.mark.skipif(importlib.util.find_spec('comictaggerlib') is None, reason='ComicTagger is not installed')
needs_unrar = pytest.mark.skipif(shutil.which('unrar') is None, reason='unrar is not installed')

ISSUE = {
    'id': 123, 'name': 'The Title', 'issue_number': '12', 'volume': {'api_detail_url': 'https://comicvine.gamespot.com/api/volume/4050-456/', 'id': 456,
               'name': 'Test Hero', 'site_detail_url': 'https://comicvine.gamespot.com/test-hero/4050-456/'},
    'cover_date': '2023-05-01', 'description': '<p>The hero &amp; friends save the day.</p>',
    'site_detail_url': 'https://comicvine.gamespot.com/test-hero-12/4000-123/',
    'person_credits': [{'name': 'Someone Else', 'role': 'writer'}, {'name': 'Pen Person', 'role': 'penciler'}],
    'story_arc_credits': [{'name': 'CV Arc'}], 'character_credits': [{'name': 'The Hero'}],
    'team_credits': [], 'location_credits': [], 'associated_images': [],
}
SERIES = {
    'id': 456, 'name': 'Test Hero', 'start_year': '2019', 'publisher': {'name': 'Test Comics'},
    'count_of_issues': 20, 'site_detail_url': 'https://comicvine.gamespot.com/test-hero/4050-456/',
}

ORIGINAL = b'''<?xml version="1.0" encoding="utf-8"?>
<ComicInfo>
  <Series>Test Hero</Series>
  <Number>12</Number>
  <Writer>Hand Picked</Writer>
  <Tags>favourite</Tags>
</ComicInfo>'''


def cfg(tmp_path, **kw):
    c = dict(CT_SETTINGSPATH=str(tmp_path / 'ct'), CACHE_DIR=str(tmp_path / 'cache'), FILE_OPTS='move',
             CT_TAG_CR=True, CT_TAG_CBL=False, CBR2CBZ_ONLY=False, CT_TAG_MODE='fill', CT_CBZ_OVERWRITE=False,
             COMICVINE_API='personal-key', COMICVINE_URL=None, CMTAG_VOLUME=True, CMTAG_START_YEAR_AS_VOLUME=True,
             SETDEFAULTVOLUME=False, CT_NOTES_FORMAT='Issue ID')
    c.update(kw)
    for d in (c['CT_SETTINGSPATH'], c['CACHE_DIR']):
        os.makedirs(d, exist_ok=True)
    return types.SimpleNamespace(**c)


@pytest.fixture
def config(tmp_path, monkeypatch):
    c = cfg(tmp_path)
    monkeypatch.setattr(mylar, 'CONFIG', c, raising=False)
    monkeypatch.setattr(mylar, 'CMTAGGER_PATH', ROOT, raising=False)
    monkeypatch.setattr(mylar, 'PROG_DIR', ROOT, raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(cmtagmylar, 'series_publisher', lambda issueid: (None, None))
    monkeypatch.setattr(cv, '_booked', {})
    monkeypatch.setattr(cv, '_slots', [])
    return c


def args_after(args, flag):
    return args[args.index(flag) + 1]


@pytest.mark.unit
def test_tag_args_use_the_new_flags(config):
    args = cmtagmylar.tag_args('/x/a.cbz', '123', '2019', 'Teen', 'fill')
    assert args[:3] == ['-s', '-o', '--tags-write'] and args_after(args, '--tags-write') == 'cr'
    assert args_after(args, '--config') == config.CT_SETTINGSPATH
    assert args_after(args, '--comicvine-key') == 'personal-key'
    assert args_after(args, '--comicvine-url') == 'https://comicvine.gamespot.com/api'
    assert args_after(args, '--id') == '123' and '-f' not in args
    assert json.loads(args_after(args, '-m')) == {'volume': 2019, 'maturity_rating': 'Teen'}
    assert '--json' in args and '--skip-existing-tags' not in args and args[-1] == '/x/a.cbz'
    for old in ('--configfolder', '--type', '--nooverwrite', '--cv-api-key', '--notes_format'):
        assert old not in args


@pytest.mark.unit
def test_tag_args_without_key_or_issue(config):
    config.COMICVINE_API = None
    config.COMICVINE_URL = 'http://cv.local/api/'
    args = cmtagmylar.tag_args('/x/a.cbz', None, None, 'None', 'skip')
    assert '--comicvine-key' not in args and '-m' not in args
    assert args_after(args, '--comicvine-url') == 'http://cv.local/api'
    assert '-f' in args and '--id' not in args and '--skip-existing-tags' in args


@pytest.mark.unit
@pytest.mark.parametrize('opts, comversion, volume', [
    (dict(), 'v2', 2),
    (dict(CMTAG_VOLUME=False), '2', None),
    (dict(CMTAG_START_YEAR_AS_VOLUME=False, SETDEFAULTVOLUME=True), None, 1),
    (dict(CMTAG_START_YEAR_AS_VOLUME=False, SETDEFAULTVOLUME=False), 'None', None),
])
def test_volume(config, opts, comversion, volume):
    for k, v in opts.items():
        setattr(config, k, v)
    assert cmtagmylar.volume_number(comversion) == volume


@pytest.mark.unit
def test_export_args(config):
    assert cmtagmylar.export_args('/x/a.cbr') == ['-e', '--config', config.CT_SETTINGSPATH, '--json', '--delete-original', '/x/a.cbr']
    config.FILE_OPTS = 'copy'
    assert '--delete-original' not in cmtagmylar.export_args('/x/a.cbr')


@pytest.mark.unit
def test_arc_fields_keep_names_and_numbers_together():
    assert cmtagmylar.arc_fields(None) is None and cmtagmylar.arc_fields([]) is None
    assert cmtagmylar.arc_fields([('Big Event', 3), ('Other', 10)]) == {'StoryArc': 'Big Event,Other', 'StoryArcNumber': '3,10'}
    assert cmtagmylar.arc_fields(4) == {'StoryArcNumber': '4'}


@pytest.mark.unit
def test_api_key_is_redacted(config):
    assert cmtagmylar._redact(['--comicvine-key', 'personal-key', 'x']) == ['--comicvine-key', 'REDACTED', 'x']


@pytest.mark.unit
def test_adjust_sets_arc_numbers_and_cvdb_notes(tmp_path):
    p = str(tmp_path / 'a.cbz')
    cix = b'<?xml version="1.0"?>\n<ComicInfo>\n  <Notes>Tagged with ComicTagger. [Issue ID 99]</Notes>\n  <StoryArc>CV Arc</StoryArc>\n</ComicInfo>'
    with zipfile.ZipFile(p, 'w') as z:
        z.writestr('001.jpg', b'x')
        z.writestr('ComicInfo.xml', cix)
    assert comicinfo.adjust(p, {'StoryArc': 'Mine & Yours', 'StoryArcNumber': '7'}, notes_format='CVDB')
    root = ET.fromstring(comicinfo.read_raw(p))
    assert root.findtext('StoryArc') == 'Mine & Yours' and root.findtext('StoryArcNumber') == '7'
    assert root.findtext('Notes') == 'Tagged with ComicTagger. [CVDB99]'


# --- end to end against the installed ComicTagger and a stand-in ComicVine ---



@pytest.fixture
def comicvine():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split('?')[0].rstrip('/')
            if path.endswith('/issue/4000-123'):
                body = ISSUE
            elif path.endswith('/volume/4050-456'):
                body = SERIES
            else:
                self.send_response(404)
                self.end_headers()
                return
            data = json.dumps({'status_code': 1, 'error': 'OK', 'results': body}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield 'http://127.0.0.1:%d/api' % srv.server_port
    srv.shutdown()


def page():
    from PIL import Image
    b = io.BytesIO()
    Image.new('RGB', (20, 30), (200, 10, 10)).save(b, 'JPEG')
    return b.getvalue()


def make_cbz(path, cix=None):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('001.jpg', page())
        z.writestr('002.jpg', page())
        if cix is not None:
            z.writestr('ComicInfo.xml', cix)
    return str(path)


def make_cbr(path, files):
    # A RAR 4 archive with stored (uncompressed) files, enough for unrar to read.
    def block(htype, flags, body, add=b''):
        head = struct.pack('<BHH', htype, flags, 7 + len(body)) + body
        return struct.pack('<H', zlib.crc32(head) & 0xFFFF) + head + add
    out = b'Rar!\x1a\x07\x00' + block(0x73, 0, b'\x00' * 6)
    for name, data in files:
        n = name.encode()
        body = struct.pack('<IIBIIBBHI', len(data), len(data), 3, zlib.crc32(data), 0x5A210000, 20, 0x30, len(n), 0o100644 << 16) + n
        out += block(0x74, 0x8000, body, data)
    out += block(0x7B, 0x4000, b'')
    with open(path, 'wb') as f:
        f.write(out)
    return str(path)


def cix_of(path):
    raw = comicinfo.read_raw(path)
    return None if raw is None else ET.fromstring(raw)


def run(config, comicvine, path, **kw):
    config.COMICVINE_URL = comicvine
    return cmtagmylar.run(os.path.dirname(path), issueid='123', comversion='2019', filename=path, **kw)


@pytest.mark.integration
@needs_ct
def test_fill_mode_keeps_existing_values_and_adds_arcs(tmp_path, config, comicvine):
    src = make_cbz(tmp_path / 'Test Hero 012 (2023).cbz', ORIGINAL)
    os.chmod(src, 0o640)
    out = run(config, comicvine, src, readingorder=[('Big Event', 7)])
    assert out.endswith('Test Hero 012 (2023).cbz') and os.path.dirname(out) != str(tmp_path)
    root = cix_of(out)
    assert root.findtext('Writer') == 'Hand Picked' and root.findtext('Tags') == 'favourite'
    assert root.findtext('Publisher') == 'Test Comics' and root.findtext('Title') == 'The Title'
    assert root.findtext('Penciller') == 'Pen Person' and root.findtext('Volume') == '2019'
    assert root.findtext('StoryArc') == 'Big Event' and root.findtext('StoryArcNumber') == '7'
    assert '[Issue ID 123]' in root.findtext('Notes')
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o640


@pytest.mark.integration
@needs_ct
def test_overwrite_mode_and_cvdb_notes(tmp_path, config, comicvine):
    config.CT_TAG_MODE = 'overwrite'
    config.CT_NOTES_FORMAT = 'CVDB'
    out = run(config, comicvine, make_cbz(tmp_path / 'a.cbz', ORIGINAL), agerating='Teen')
    root = cix_of(out)
    assert root.findtext('Writer') == 'Someone Else' and root.findtext('Tags') == 'favourite'
    assert root.findtext('AgeRating') == 'Teen' and '[CVDB123]' in root.findtext('Notes')


@pytest.mark.integration
@needs_ct
def test_skip_mode_leaves_tagged_files_alone(tmp_path, config, comicvine):
    config.CT_TAG_MODE = 'skip'
    out = run(config, comicvine, make_cbz(tmp_path / 'a.cbz', ORIGINAL))
    with zipfile.ZipFile(out) as z:
        assert z.read('ComicInfo.xml') == ORIGINAL
    out = run(config, comicvine, make_cbz(tmp_path / 'b.cbz'))
    assert cix_of(out).findtext('Series') == 'Test Hero'


@pytest.mark.integration
@needs_ct
@needs_unrar
def test_cbr_is_converted_and_tagged(tmp_path, config, comicvine):
    src = make_cbr(tmp_path / 'Test Hero 012 (2023).cbr', [('001.jpg', page()), ('002.jpg', page()), ('ComicInfo.xml', ORIGINAL)])
    out = run(config, comicvine, src)
    assert out.endswith('Test Hero 012 (2023).cbz') and zipfile.is_zipfile(out)
    assert not os.path.exists(os.path.join(os.path.dirname(out), 'Test Hero 012 (2023).cbr'))
    root = cix_of(out)
    assert root.findtext('Writer') == 'Hand Picked' and root.findtext('Publisher') == 'Test Comics'
    assert os.path.exists(src)


@pytest.mark.integration
@needs_ct
@needs_unrar
def test_cbr_to_cbz_only(tmp_path, config, comicvine):
    config.CBR2CBZ_ONLY = True
    config.FILE_OPTS = 'copy'
    out = run(config, comicvine, make_cbr(tmp_path / 'a.cbr', [('001.jpg', page()), ('002.jpg', page())]))
    assert out.endswith('a.cbz') and zipfile.is_zipfile(out) and cix_of(out) is None


@pytest.mark.integration
@needs_ct
@needs_unrar
@pytest.mark.parametrize('file_opts', ['move', 'copy'])
def test_cbz_named_rar_keeps_its_name(tmp_path, config, comicvine, file_opts):
    config.CBR2CBZ_ONLY = True
    config.FILE_OPTS = file_opts
    out = run(config, comicvine, make_cbr(tmp_path / 'a.cbz', [('001.jpg', page()), ('002.jpg', page())]))
    assert os.path.basename(out) == 'a.cbz' and zipfile.is_zipfile(out)
    assert os.listdir(os.path.dirname(out)) == ['a.cbz']


@pytest.mark.integration
@needs_ct
def test_unknown_issue_fails_and_keeps_the_original(tmp_path, config, comicvine):
    src = make_cbz(tmp_path / 'a.cbz', ORIGINAL)
    config.COMICVINE_URL = comicvine
    assert cmtagmylar.run(str(tmp_path), issueid='999', comversion='1', filename=src) == 'fail'
    with zipfile.ZipFile(src) as z:
        assert z.read('ComicInfo.xml') == ORIGINAL


@pytest.mark.integration
@needs_ct
def test_not_a_comic(tmp_path, config, comicvine):
    src = tmp_path / 'a.cbr'
    src.write_bytes(b'not an archive')
    assert run(config, comicvine, str(src)) == 'file not found||a.cbr'


@pytest.mark.integration
@needs_ct
def test_imprint_series_get_the_parent_publisher_and_imprint(tmp_path, config, comicvine, monkeypatch):
    # ComicVine lists the series under its own publisher; Issuarr's imprint listing knows better
    monkeypatch.setattr(cmtagmylar, 'series_publisher', lambda issueid: ('DC Comics', 'Vertigo'))
    root = cix_of(run(config, comicvine, make_cbz(tmp_path / 'a.cbz')))
    assert root.findtext('Publisher') == 'DC Comics' and root.findtext('Imprint') == 'Vertigo'
    assert root.findtext('Title') == 'The Title'


@pytest.mark.integration
@needs_ct
def test_series_without_an_imprint_keep_the_comicvine_publisher(tmp_path, config, comicvine):
    root = cix_of(run(config, comicvine, make_cbz(tmp_path / 'a.cbz')))
    assert root.findtext('Publisher') == 'Test Comics' and root.findtext('Imprint') is None
