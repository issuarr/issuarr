"""Import & scan: moving scanned files into the series folder."""
import types

import mylar
from mylar import helpers, moveit


class FakeDB:
    def __init__(self):
        self.upserts = []

    def upsert(self, table, values, keys):
        self.upserts.append((table, values, keys))


def setup(monkeypatch, tmp_path, renamed):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(CREATE_FOLDERS=True, IMP_RENAME=True,
                                                              FILE_FORMAT='$Series $Issue'), raising=False)
    fake = FakeDB()
    monkeypatch.setattr(moveit.db, 'DBConnection', lambda: fake)
    monkeypatch.setattr(helpers, 'rename_param', lambda *a, **k: renamed)
    src = tmp_path / 'staging'
    src.mkdir()
    dst = tmp_path / 'Series (2020)'
    dst.mkdir()
    f = src / 'Series - The Red Shadow HC.cbz'
    f.write_bytes(b'x')
    imported = {'ComicName': 'Series', 'srid': None,
                'filelisting': [{'comiclocation': str(f), 'comicfilename': f.name,
                                 'issuenumber': '1', 'import_id': '123'}]}
    return fake, dst, f, imported


def test_file_without_a_matching_issue_keeps_its_name(monkeypatch, tmp_path):
    fake, dst, f, imported = setup(monkeypatch, tmp_path, None)
    moveit.movefiles('4050', str(dst), imported)
    assert (dst / f.name).exists()
    assert not f.exists()
    assert fake.upserts[0][1]['Status'] == 'Imported'


def test_file_is_renamed_when_the_issue_is_known(monkeypatch, tmp_path):
    fake, dst, f, imported = setup(monkeypatch, tmp_path, {'nfilename': 'Series 001.cbz'})
    moveit.movefiles('4050', str(dst), imported)
    assert (dst / 'Series 001.cbz').exists()
