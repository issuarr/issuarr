"""Import tags a series' untagged files when tagging is on, like filing a download does."""
import types
import zipfile

import pytest

import mylar
from mylar import moveit


class FakeDB:
    def __init__(self, location, issues):
        self.location = location
        self.issues = issues

    def selectone(self, query, args=None):
        return types.SimpleNamespace(fetchone=lambda: {'ComicLocation': self.location})

    def select(self, query, args=None):
        return [{'IssueID': i, 'Location': name} for i, name in self.issues] if 'FROM issues' in query else []


def cbz(path, tagged):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('001.jpg', b'page')
        if tagged:
            z.writestr('ComicInfo.xml', '<ComicInfo/>')


@pytest.fixture
def series(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(ENABLE_META=True, ANNUALS_ON=False), raising=False)
    cbz(tmp_path / 'T2 #01.cbz', tagged=False)
    cbz(tmp_path / 'T2 #02.cbz', tagged=True)
    (tmp_path / 'T2 #03.cbr').write_bytes(b'Rar!\x1a\x07\x00')   # a real RAR has no tags we can read
    cbz(tmp_path / 'T2 #04.cbr', tagged=True)                   # a zip named .cbr
    issues = [('1', 'T2 #01.cbz'), ('2', 'T2 #02.cbz'), ('3', 'T2 #03.cbr'), ('4', 'T2 #04.cbr'), ('5', 'T2 #05.cbz')]
    monkeypatch.setattr(moveit.db, 'DBConnection', lambda: FakeDB(str(tmp_path), issues))
    return tmp_path


def test_untagged_lists_files_without_comicinfo(series):
    assert moveit.untagged('19063') == ['1', '3']   # #05's file is missing, so it's left out


def test_tag_series_tags_only_untagged_files(monkeypatch, series):
    tagged, rescans = [], []
    import mylar.webserve
    monkeypatch.setattr(mylar.webserve.WebInterface, 'manual_metatag', lambda self, issueid, group=False: tagged.append((issueid, group)))
    monkeypatch.setattr(moveit.updater, 'forceRescan', lambda comicid: rescans.append(comicid))
    moveit._tag_series('19063')
    assert tagged == [('1', True), ('3', True)]
    assert rescans == ['19063']


def test_tag_imported_does_nothing_when_tagging_is_off(monkeypatch, series):
    mylar.CONFIG.ENABLE_META = False
    moveit.tag_imported('19063')
    assert moveit._tag_queue.empty()
