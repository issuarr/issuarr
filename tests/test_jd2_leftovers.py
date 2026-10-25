"""What JD2's other mirrors leave behind once a download is filed.

2026-10-25: JD2 is sent every mirror of a post. Capes #6 was filed from one mirror while a second
mirror's copy stayed in its folder; Green Lantern #62-67 was filed, but the zip and what JD2
unpacked from it stayed; Savage Dragon Archives v10 was filed while another mirror's .part stayed
in JD2's dated folder 2025-08/14. Nothing cleared them, because only packs in the direct-download
folder were cleared.
"""
import types
import zipfile

import pytest

import mylar
from mylar import archives, attention
from mylar.downloaders import jdownloader2


@pytest.fixture
def jd2_root(monkeypatch, tmp_path):
    root = tmp_path / 'complete'
    root.mkdir()
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(
        JD2_DEST_DIR='/output/complete', JD2_LOCAL_DIR=str(root), DDL_LOCATION=str(tmp_path / 'mylar-dl'),
        FILE_OPTS='move', ARCHIVE_REVIEW_DIR=str(tmp_path / 'review'), CHECK_FOLDER=None), raising=False)
    monkeypatch.setattr(attention, 'trash_dir', lambda: str(tmp_path / 'trash'))
    monkeypatch.setattr(attention, 'forget', lambda path: None)
    monkeypatch.setattr(archives, '_hold', lambda path: False)
    monkeypatch.setattr(archives, '_filed', lambda issueid: issueid == 'filed')
    return root


def info(files, issueid='filed'):
    return {'provider': 'JD2', 'id': '395187', 'job_id': '1,2', 'issueid': issueid, 'files': [str(f) for f in files]}


def trashed(tmp_path):
    return sorted(p.name for p in (tmp_path / 'trash').rglob('*') if p.is_file())


@pytest.mark.unit
def test_the_other_mirrors_copy_goes_to_the_trash(jd2_root, tmp_path):
    folder = jd2_root / 'Capes #6 (Empire) (2026) - 395187'
    folder.mkdir()
    (folder / 'Capes 006 (LeDuch).cbz').write_bytes(b'x')
    filed = folder / 'Capes 006 (Zone-Empire).cbz'   # moved to the library already
    assert archives.clear_jd2(info([filed, folder / 'Capes 006 (LeDuch).cbz'])) == 1
    assert trashed(tmp_path) == ['Capes 006 (LeDuch).cbz']
    assert not folder.exists()


@pytest.mark.unit
def test_a_part_file_in_a_dated_folder_goes_and_the_rest_of_the_folder_stays(jd2_root, tmp_path):
    dated = jd2_root / '2025-08' / '14'
    dated.mkdir(parents=True)
    (dated / 'Savage Dragon Archives v10.cbr.part').write_bytes(b'x')
    (dated / 'Someone else.cbz').write_bytes(b'x')
    assert archives.clear_jd2(info([dated / 'Savage Dragon Archives v10.cbr'])) == 1
    assert trashed(tmp_path) == ['Savage Dragon Archives v10.cbr.part']
    assert (dated / 'Someone else.cbz').exists()


@pytest.mark.unit
def test_an_empty_dated_folder_is_dropped(jd2_root, tmp_path):
    dated = jd2_root / '2025-08' / '14'
    dated.mkdir(parents=True)
    (dated / 'Savage Dragon Archives v10.cbr.part').write_bytes(b'x')
    archives.clear_jd2(info([dated / 'Savage Dragon Archives v10.cbr']))
    assert not (jd2_root / '2025-08').exists() and jd2_root.is_dir()


@pytest.mark.unit
def test_a_zip_and_what_jd2_unpacked_from_it_go(jd2_root, tmp_path):
    folder = jd2_root / 'Green Lantern #62 - 67 (2010) - 3328'
    inner = folder / 'Green Lantern 062-067 (2010) (Digital)'
    inner.mkdir(parents=True)
    zpath = folder / 'Green Lantern 062-067 (2010) (Digital).zip'
    with zipfile.ZipFile(zpath, 'w') as z:
        for n in ('062', '063'):
            z.writestr('Green Lantern 062-067 (2010) (Digital)/Green Lantern %s.cbr' % n, b'x')
    for n in ('062', '063'):
        (inner / ('Green Lantern %s.cbr' % n)).write_bytes(b'x')
    assert archives.clear_jd2(info([zpath])) == 3
    assert trashed(tmp_path) == ['Green Lantern 062-067 (2010) (Digital).zip', 'Green Lantern 062.cbr', 'Green Lantern 063.cbr']
    assert not folder.exists()


@pytest.mark.unit
def test_nothing_is_cleared_when_filing_did_not_take(jd2_root, tmp_path):
    folder = jd2_root / 'Capes #6 - 395187'
    folder.mkdir()
    (folder / 'Capes 006.cbz').write_bytes(b'x')
    assert archives.clear_jd2(info([folder / 'Capes 006.cbz'], issueid='snatched')) == 0
    assert (folder / 'Capes 006.cbz').exists()


@pytest.mark.unit
def test_nothing_is_cleared_when_files_are_copied(jd2_root, tmp_path):
    mylar.CONFIG.FILE_OPTS = 'copy'
    folder = jd2_root / 'Capes #6 - 395187'
    folder.mkdir()
    (folder / 'Capes 006.cbz').write_bytes(b'x')
    assert archives.clear_jd2(info([folder / 'Capes 006.cbz'])) == 0
    assert (folder / 'Capes 006.cbz').exists()


@pytest.mark.unit
def test_paths_outside_jd2s_folder_are_never_touched(jd2_root, tmp_path):
    other = tmp_path / 'elsewhere'
    other.mkdir()
    (other / 'Capes 006.cbz').write_bytes(b'x')
    assert archives.clear_jd2(info([other / 'Capes 006.cbz'])) == 0
    assert (other / 'Capes 006.cbz').exists()


@pytest.mark.unit
def test_other_downloads_are_left_alone(jd2_root, tmp_path):
    (jd2_root / 'Capes 006.cbz').write_bytes(b'x')
    assert archives.clear_jd2({'provider': 'DDL', 'id': '1', 'issueid': 'filed', 'files': [str(jd2_root / 'Capes 006.cbz')]}) == 0
    assert archives.clear_jd2(None) == 0
    assert (jd2_root / 'Capes 006.cbz').exists()


@pytest.mark.unit
def test_jd2_lists_every_file_its_links_save_to(jd2_root):
    client = jdownloader2.JDownloader2.__new__(jdownloader2.JDownloader2)
    client._job_links = lambda job_id, record_id=None: {'downloadsV2': ([
        {'packageUUID': 'p1', 'name': 'Capes 006 (Zone-Empire).cbz'},
        {'packageUUID': 'p1', 'name': 'Capes 006 (LeDuch).cbz'},
        {'packageUUID': 'p2', 'name': 'Capes 006 (LeDuch).cbz'}], ['p1', 'p2']), 'linkgrabberv2': ([], [])}
    client._save_to = lambda packages: {'p1': '/output/complete/Capes #6 - 395187', 'p2': '/output/complete/2025-08/14'}
    assert client.files('1,2', '395187') == [
        str(jd2_root / 'Capes #6 - 395187' / 'Capes 006 (Zone-Empire).cbz'),
        str(jd2_root / 'Capes #6 - 395187' / 'Capes 006 (LeDuch).cbz'),
        str(jd2_root / '2025-08' / '14' / 'Capes 006 (LeDuch).cbz')]
