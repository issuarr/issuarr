"""Import tags a series' untagged files from the stored issue info when tagging is on."""
import types
import zipfile

import pytest

import mylar
from mylar import moveit, quicktag, webp


class FakeDB:
    def __init__(self, location, issues):
        self.location = location
        self.issues = issues

    def selectone(self, query, args=None):
        if 'FROM comics' in query:
            return types.SimpleNamespace(fetchone=lambda: {'ComicLocation': self.location})
        name = args[0]
        found = name in self.issues
        return types.SimpleNamespace(fetchone=lambda: {'ComicName': 'T2', 'Issue_Number': name} if found else None)

    def select(self, query, args=None):
        return [{'Location': name} for name in self.issues]


def cbz(path, tagged=False):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('001.jpg', b'page')
        if tagged:
            z.writestr('ComicInfo.xml', '<ComicInfo/>')


@pytest.fixture
def series(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(ENABLE_META=True), raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    cbz(tmp_path / 'T2 #01.cbz')
    cbz(tmp_path / 'T2 #02.cbz', tagged=True)
    cbz(tmp_path / 'T2 #03.cbr')                                # a zip named .cbr
    issues = ['T2 #01.cbz', 'T2 #02.cbz', 'T2 #03.cbr', 'T2 #05.cbz']   # #05's file is missing
    monkeypatch.setattr(moveit.db, 'DBConnection', lambda: FakeDB(str(tmp_path), issues))
    monkeypatch.setattr(quicktag, 'build', lambda row: b'<ComicInfo><Series>T2</Series></ComicInfo>')
    monkeypatch.setattr(webp, '_relocate', lambda old, new: None)
    rescans = []
    monkeypatch.setattr(moveit.updater, 'forceRescan', rescans.append)
    return tmp_path, rescans


def test_import_tags_only_untagged_files(series):
    folder, rescans = series
    done = moveit.tag_imported('19063')
    assert done == [str(folder / 'T2 #01.cbz'), str(folder / 'T2 #03.cbz')]
    assert all(quicktag.tagged(p) for p in done)
    assert rescans == ['19063']


def test_import_tags_nothing_when_tagging_is_off(series):
    folder, rescans = series
    mylar.CONFIG.ENABLE_META = False
    assert moveit.tag_imported('19063') == []
    assert not quicktag.tagged(str(folder / 'T2 #01.cbz')) and (folder / 'T2 #03.cbr').exists()
    assert rescans == []
