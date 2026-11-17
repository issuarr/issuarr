"""Files of annuals kept with their series (Keep annuals with their series) are found by a library scan (#274)."""
import os

import pytest

import mylar
from mylar import db, matching, updater
from tests.test_matching import comic_file


@pytest.fixture
def sonic(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'DB_FILE', str(tmp_path / 'mylar.db'), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    for k, v in mylar.config._CONFIG_DEFINITIONS.items():
        monkeypatch.setattr(mylar.CONFIG, k, v[2], raising=False)
    for k, v in dict(IGNORE_SEARCH_WORDS=[], CUSTOM_ISSUE_EXCEPTIONS=[], ANNUALS_ON=True, FOLDER_SCAN_LOG_VERBOSE=False,
                     MULTIPLE_DEST_DIRS=None, ZERO_LEVEL_N=None, ZERO_LEVEL=False, IGNORE_HAVETOTAL=False,
                     SNATCHED_HAVETOTAL=False, ENABLE_TORRENTS=False, DUPECONSTRAINT='filesize',
                     DYNAMIC_UPDATE=99, OLDCONFIG_VERSION=None).items():
        monkeypatch.setattr(mylar.CONFIG, k, v, raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(matching, '_TAGS', {})
    mylar.dbcheck()
    folder = tmp_path / 'Sonic the Hedgehog (2018)'
    d = db.DBConnection()
    d.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicLocation, ComicPublisher, Type, Status, Total, Have) "
             "VALUES ('110000', 'Sonic the Hedgehog', '2018', ?, 'IDW Publishing', 'Print', 'Active', 2, 0)", [str(folder)])
    for n in (1, 2):
        d.action("INSERT INTO issues (IssueID, ComicID, ComicName, Issue_Number, Int_IssueNumber, IssueDate, Status) "
                 "VALUES (?, '110000', 'Sonic the Hedgehog', ?, ?, '2018-07-01', 'Wanted')", ['90%s' % n, str(n), n * 1000])
    # two one-issue annual series, both numbered #1
    for issueid, volid, year in (('2019', '120000', '2019'), ('2024', '160329', '2024')):
        d.action("INSERT INTO annuals (IssueID, ComicID, ComicName, Issue_Number, Int_IssueNumber, IssueDate, Status, ReleaseComicID, ReleaseComicName) "
                 "VALUES (?, '110000', ?, '1', 1000, ?, 'Wanted', ?, ?)",
                 ['a' + issueid, 'Sonic the Hedgehog Annual %s' % year, '%s-07-01' % year, volid, 'Sonic the Hedgehog Annual %s' % year])
    os.makedirs(folder)
    comic_file(folder / 'Sonic the Hedgehog 001 (2018).cbz')
    return folder


def annual(i):
    return dict(db.DBConnection().selectone('SELECT Status, Location FROM annuals WHERE IssueID=?', [i]).fetchone())


@pytest.mark.unit
@pytest.mark.parametrize('name', [
    'Sonic the Hedgehog Annual 2024 001 (2024).cbz',
    'Sonic the Hedgehog Annual 2024.cbz',
    'Sonic the Hedgehog Annual (2024).cbz',
    'Sonic the Hedgehog Annual 2024 (2024) 001.cbz',
    'Sonic the Hedgehog Annual 2024 #1 (2024).cbz',
    'Sonic the Hedgehog 2024 Annual 001 (2024).cbz',
    'Sonic the Hedgehog Annual 001 (2024).cbz',
])
def test_an_annual_named_for_its_annual_series_is_found(sonic, name):
    comic_file(sonic / name)
    updater.forceRescan('110000')
    assert annual('a2024') == {'Status': 'Downloaded', 'Location': name}
    assert annual('a2019')['Location'] is None
    assert db.DBConnection().selectone("SELECT Location FROM issues WHERE IssueID='901'").fetchone()[0] == 'Sonic the Hedgehog 001 (2018).cbz'


@pytest.mark.unit
def test_each_annual_series_gets_its_own_file(sonic):
    comic_file(sonic / 'Sonic the Hedgehog Annual 2019 001 (2019).cbz')
    comic_file(sonic / 'Sonic the Hedgehog Annual 2024 001 (2024).cbz')
    updater.forceRescan('110000')
    assert annual('a2019')['Location'] == 'Sonic the Hedgehog Annual 2019 001 (2019).cbz'
    assert annual('a2024')['Location'] == 'Sonic the Hedgehog Annual 2024 001 (2024).cbz'


@pytest.mark.unit
def test_an_unknown_annual_series_is_left_alone(sonic):
    comic_file(sonic / 'Sonic the Hedgehog Annual 2030 001 (2030).cbz')
    updater.forceRescan('110000')
    assert annual('a2019')['Location'] is None and annual('a2024')['Location'] is None


@pytest.mark.unit
def test_nothing_changes_with_annuals_kept_apart(sonic, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'ANNUALS_ON', False)
    comic_file(sonic / 'Sonic the Hedgehog Annual 2024 001 (2024).cbz')
    assert matching.by_annual_name('110000', [(str(sonic), None, 'Sonic the Hedgehog Annual 2024 001 (2024).cbz', 10)], {}, set()) == []
