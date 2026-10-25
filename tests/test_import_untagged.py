import types
import zipfile

import pytest

import mylar
from mylar import librarysync


class FakeDB:
    def select(self, query, args=None):
        return []

    def action(self, query, args=None, executemany=False):
        pass


class FakeChecker:
    def __init__(self, dir=None, file=None):
        self.file = file

    def listFiles(self):
        return {'parse_status': 'success', 'series_name': 'Sonic Super Special', 'series_volume': None,
                'issue_year': '1997', 'issue_number': '001'}

    def dynamic_replace(self, name):
        return {'mod_seriesname': name}


@pytest.fixture
def scan(monkeypatch, tmp_path):
    folder = tmp_path / 'Archie Comics' / 'Sonic Super Special (1997)'
    folder.mkdir(parents=True)
    # a plain cbz: no ComicInfo.xml and no zip comment
    with zipfile.ZipFile(folder / 'Sonic Super Special 001 (1997).cbz', 'w') as z:
        z.writestr('page01.jpg', b'x')
    cfg = types.SimpleNamespace(COMIC_DIR=str(tmp_path), IMP_CHANGED_ONLY=False, IMP_PATHS=False, IMP_METADATA=True,
                                IMP_MOVE=False, IMP_RENAME=False, DUPLICATE_DUMP=None)
    monkeypatch.setattr(mylar, 'CONFIG', cfg, raising=False)
    for name in ('IMPORT_FILES', 'IMPORT_PARSED_COUNT', 'IMPORT_FAILURE_COUNT', 'IMPORT_CID_COUNT', 'IMPORT_TOTALFILES'):
        monkeypatch.setattr(mylar, name, 0, raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(librarysync.db, 'DBConnection', FakeDB)
    monkeypatch.setattr(librarysync.filechecker, 'FileChecker', FakeChecker)
    monkeypatch.setattr(librarysync, 'work_folders', lambda: [])
    return tmp_path


@pytest.mark.unit
def test_an_untagged_cbz_is_imported_by_its_filename(scan):
    result = librarysync.libraryScan(dir=str(scan))
    assert result['import_count'] == 1
    found = result['import_by_comicids'][0]
    assert found['comicname'] == 'Sonic Super Special'
    assert found['issuenumber'] == '001'
    assert found['comicyear'] == '1997'
