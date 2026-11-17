"""Series page > Match a file lists the annuals kept with the series, and a match to one holds (#274)."""
import os

import pytest

import mylar
from mylar import db, matching, updater
from tests.test_matching import comic_file


@pytest.fixture
def series(monkeypatch, tmp_path):
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
             "VALUES ('110000', 'Sonic the Hedgehog', '2018', ?, 'IDW Publishing', 'Print', 'Active', 1, 0)", [str(folder)])
    d.action("INSERT INTO issues (IssueID, ComicID, ComicName, Issue_Number, Int_IssueNumber, IssueDate, Status) "
             "VALUES ('901', '110000', 'Sonic the Hedgehog', '1', 1000, '2018-07-01', 'Wanted')")
    d.action("INSERT INTO annuals (IssueID, ComicID, ComicName, Issue_Number, Int_IssueNumber, IssueDate, Status, ReleaseComicID, ReleaseComicName) "
             "VALUES ('a24', '110000', 'Sonic the Hedgehog Annual 2024', '1', 1000, '2024-07-01', 'Wanted', '160329', 'Sonic the Hedgehog Annual 2024')")
    comic_file(folder / 'Sonic the Hedgehog 001 (2018).cbz')
    comic_file(folder / 'sonic special thing.cbz')
    return folder


def annual():
    return dict(db.DBConnection().selectone("SELECT Status, Location, forced_file FROM annuals WHERE IssueID='a24'").fetchone())


@pytest.mark.unit
def test_annuals_are_listed_to_match(series):
    listed = {i['issueid']: i for i in matching.files('110000')['issues']}
    assert listed['901']['label'] == '#1' and not listed['901']['annual']
    assert listed['a24']['label'] == 'Annual 2024 #1' and listed['a24']['annual']


@pytest.mark.unit
def test_a_file_matched_to_an_annual_stays_through_a_recheck(series):
    updater.forceRescan('110000')
    r = matching.match('110000', 'a24', 'sonic special thing.cbz')
    assert r['ok'] and r['note'] == 'sonic special thing.cbz is now Annual 2024 #1.'
    assert annual() == {'Status': 'Downloaded', 'Location': 'sonic special thing.cbz', 'forced_file': 1}
    updater.forceRescan('110000')
    assert annual() == {'Status': 'Downloaded', 'Location': 'sonic special thing.cbz', 'forced_file': 1}
    files = {f['name']: f for f in matching.files('110000')['files']}
    assert files['sonic special thing.cbz']['issueid'] == 'a24' and files['sonic special thing.cbz']['label'] == 'Annual 2024 #1'
    assert files['sonic special thing.cbz']['pinned']
    # the series' own issue keeps its file
    assert db.DBConnection().selectone("SELECT Location FROM issues WHERE IssueID='901'").fetchone()[0] == 'Sonic the Hedgehog 001 (2018).cbz'


@pytest.mark.unit
def test_undoing_an_annual_match(series):
    matching.match('110000', 'a24', 'sonic special thing.cbz')
    assert matching.unmatch('110000', 'a24')['ok']
    assert annual()['forced_file'] == 0
    assert annual()['Status'] == 'Skipped'   # its name doesn't say it's the annual


@pytest.mark.unit
def test_an_annual_match_whose_file_is_gone_is_dropped(series):
    matching.match('110000', 'a24', 'sonic special thing.cbz')
    os.remove(series / 'sonic special thing.cbz')
    updater.forceRescan('110000')
    assert annual()['forced_file'] == 0 and annual()['Location'] is None


@pytest.mark.unit
def test_annuals_kept_apart_are_not_offered(series, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'ANNUALS_ON', False)
    assert 'a24' not in {i['issueid'] for i in matching.files('110000')['issues']}
    assert not matching.match('110000', 'a24', 'sonic special thing.cbz')['ok']
