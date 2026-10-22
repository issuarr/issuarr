import types

import pytest

import mylar
from mylar import attention
from mylar.queues import ddl


class FakeDB:
    def __init__(self, tmp):
        self.tmp = tmp

    def selectone(self, query, args=None):
        row = {'tmp_filename': self.tmp}
        return types.SimpleNamespace(fetchone=lambda: row)


@pytest.fixture
def dl(monkeypatch, tmp_path):
    root = tmp_path / 'mylar-dl'
    root.mkdir()
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_LOCATION=str(root), JD2_LOCAL_DIR=None,
                                                              JD2_DEST_DIR=None, ARCHIVE_REVIEW_DIR=str(tmp_path / 'review')),
                        raising=False)
    return root


@pytest.mark.unit
def test_a_corrupt_download_is_deleted(dl):
    bad = dl / 'Detective Comics 949 (2017) [__578425__].cbr'
    bad.write_bytes(b'Rar!\x1a\x07\x00cut short')
    ddl.discard_download(FakeDB(str(bad)), {'id': '46127'}, {'success': False, 'path': str(bad)})
    assert not bad.exists()


@pytest.mark.unit
def test_an_empty_download_known_only_by_its_tmp_name_is_deleted(dl):
    empty = dl / 'Batman 013 (2017) [__569298__].cbz'
    empty.write_bytes(b'')
    ddl.discard_download(FakeDB(str(empty)), {'id': '1'}, {'success': False, 'path': None})
    assert not empty.exists()


@pytest.mark.unit
def test_a_zip_that_wont_unpack_goes_with_its_partly_unpacked_folder(dl):
    zipped = dl / 'Star Wars 012 (2016) [__506184__].zip'
    zipped.write_bytes(b'PK\x03\x04broken')
    folder = dl / 'Star Wars 012 (2016) [__506184__]'
    folder.mkdir()
    (folder / 'page.jpg').write_bytes(b'x')
    ddl.discard_download(FakeDB(str(zipped)), {'id': '2'}, {'success': False, 'path': None})
    assert not zipped.exists() and not folder.exists()


@pytest.mark.unit
def test_nothing_outside_the_download_folder_is_touched(dl, tmp_path):
    outside = tmp_path / 'DC MASTER READING ORDER.cbr'
    outside.write_bytes(b'keep me')
    ddl.discard_download(FakeDB(str(outside)), {'id': '3'}, {'success': False, 'path': str(outside)})
    ddl.discard_download(FakeDB(None), {'id': '3'}, {'success': False, 'path': str(dl)})
    assert outside.exists() and dl.is_dir()


@pytest.mark.unit
def test_empty_download_folders_are_cleared_up_to_the_download_folder(dl):
    inner = dl / 'Impaler v1 (001-006) [__411995__]' / 'Impaler v1 GetComics.INFO'
    inner.mkdir(parents=True)
    attention.prune_empty(str(inner))
    assert not (dl / 'Impaler v1 (001-006) [__411995__]').exists()
    assert dl.is_dir()


@pytest.mark.unit
def test_a_folder_that_still_holds_files_stays(dl):
    pack = dl / 'House of Secrets [__2747__]'
    pack.mkdir()
    (pack / 'House of Secrets 077.cbz').write_bytes(b'x')
    attention.prune_empty(str(pack))
    assert pack.is_dir()


@pytest.mark.unit
def test_the_mega_folder_and_folders_elsewhere_stay(dl, tmp_path):
    (dl / 'mega').mkdir()
    other = tmp_path / 'complete' / 'DC MASTER READING ORDER'
    other.mkdir(parents=True)
    attention.prune_empty(str(dl / 'mega'))
    attention.prune_empty(str(other))
    assert (dl / 'mega').is_dir() and other.is_dir()
