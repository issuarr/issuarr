"""Collected editions (TPB, HC, Omnibus) are kept apart from single issues when matching by itself."""
import os
import zipfile

import pytest

import mylar
from mylar import attention, db, editions, filechecker, matching, updater


@pytest.mark.unit
@pytest.mark.parametrize('name', ['Batman TPB Vol 2 (2017).cbz', 'Batman Vol. 02 - I Am Suicide (2017) (TPB).cbz',
                                  'Saga HC Book 01 (2017).cbz', 'Batman Omnibus Vol 1 (2020).cbz',
                                  'Saga Deluxe Edition v01 (2014).cbz', 'X-Men Epic Collection v05 (2019).cbz',
                                  'Walking_Dead_Compendium_01.cbz', 'Watchmen (Hardcover) (1987).cbr'])
def test_collected_editions_are_recognized(name):
    assert editions.collected(name)


@pytest.mark.unit
@pytest.mark.parametrize('name', ['Batman 002 (2016).cbz', 'Absolute Batman 001 (2024).cbz', 'Chcken 001.cbz', 'Batman 100 (GNU).cbz'])
def test_single_issues_are_not(name):
    assert not editions.collected(name)


@pytest.mark.unit
def test_words_in_the_series_name_dont_count():
    assert not editions.collected('Spider-Man Omnibus 001.cbz', 'Spider-Man Omnibus')
    assert editions.collected('Spider-Man Omnibus HC 001.cbz', 'Spider-Man Omnibus')


@pytest.mark.unit
def test_format_words_are_not_part_of_the_series_name():
    assert editions.strip_format('Saga HC Book') == 'Saga'
    assert editions.strip_format('Saga TPB') == 'Saga'
    assert editions.strip_format('Book of Death') == 'Book of Death'
    assert editions.strip_format('HC') == 'HC'
    assert editions.strip_format('Mystery HC', watchcomic='Mystery HC') == 'Mystery HC'


@pytest.mark.unit
def test_series_types():
    assert editions.singles('Print') and editions.singles('Digital') and editions.singles(None) and editions.singles('None')
    assert not editions.singles('TPB') and not editions.singles('One-Shot')
    assert not editions.singles('Print', 'TPB') and editions.singles('TPB', 'Print')


@pytest.mark.unit
def test_import_only_picks_a_collected_series_for_collected_editions():
    singles, tpb = {'comicid': '1', 'type': 'Print'}, {'comicid': '2', 'type': 'TPB'}
    assert editions.auto_pick([singles], False) is singles
    assert editions.auto_pick([singles], True) is None
    assert editions.auto_pick([singles, tpb], True) is tpb
    assert editions.auto_pick([singles, tpb], False) is None


def comic_file(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('001.jpg', b'x' * 10)
    return str(path)


@pytest.fixture
def library(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'DB_FILE', str(tmp_path / 'mylar.db'), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    for k, v in mylar.config._CONFIG_DEFINITIONS.items():
        monkeypatch.setattr(mylar.CONFIG, k, v[2], raising=False)
    for k, v in dict(IGNORE_SEARCH_WORDS=[], CUSTOM_ISSUE_EXCEPTIONS=[], ANNUALS_ON=False, FOLDER_SCAN_LOG_VERBOSE=False,
                     MULTIPLE_DEST_DIRS=None, ZERO_LEVEL_N=None, ZERO_LEVEL=False, IGNORE_HAVETOTAL=False,
                     SNATCHED_HAVETOTAL=False, ENABLE_TORRENTS=False, DUPECONSTRAINT='filesize',
                     DYNAMIC_UPDATE=99, OLDCONFIG_VERSION=None).items():
        monkeypatch.setattr(mylar.CONFIG, k, v, raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(matching, '_TAGS', {})
    monkeypatch.setattr(attention, '_COMICS', [0.0, []])
    mylar.dbcheck()
    d = db.DBConnection()

    def series(comicid, name, kind, issues):
        folder = tmp_path / 'library' / ('%s %s' % (name, comicid))
        d.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicLocation, ComicPublisher, Type, Status, Total, Have) "
                 "VALUES (?, ?, '2016', ?, 'DC Comics', ?, 'Active', ?, 0)", [comicid, name, str(folder), kind, issues])
        for n in range(1, issues + 1):
            d.action("INSERT INTO issues (IssueID, ComicID, ComicName, Issue_Number, Int_IssueNumber, IssueDate, Status) "
                     "VALUES (?, ?, ?, ?, ?, '2017-01-01', 'Wanted')", ['%s0%s' % (comicid, n), comicid, name, str(n), n * 1000])
        return folder
    return series


def status(issueid):
    return db.DBConnection().selectone('SELECT Status FROM issues WHERE IssueID=?', [issueid]).fetchone()['Status']


@pytest.mark.unit
def test_the_format_word_leaves_the_series_name(library):
    p = filechecker.FileChecker(file='Saga HC Book 01 (2017).cbz').listFiles()
    assert p['series_name'] == 'Saga'


@pytest.mark.unit
def test_recheck_keeps_collected_editions_out_of_a_series_of_single_issues(library):
    folder = library('500', 'Batman', 'Print', 3)
    comic_file(folder / 'Batman 001 (2016).cbz')
    comic_file(folder / 'Batman TPB Vol 2 (2017).cbz')
    comic_file(folder / 'Batman Vol. 03 - I Am Bane (2017) (TPB).cbz')
    updater.forceRescan('500')
    assert [status(i) for i in ('50001', '50002', '50003')] == ['Downloaded', 'Wanted', 'Wanted']


@pytest.mark.unit
def test_recheck_matches_volumes_of_a_tpb_series(library):
    folder = library('600', 'Batman', 'TPB', 3)
    comic_file(folder / 'Batman TPB Vol 2 (2017).cbz')
    updater.forceRescan('600')
    assert [status(i) for i in ('60001', '60002', '60003')] == ['Wanted', 'Downloaded', 'Wanted']


@pytest.mark.unit
def test_needs_attention_offers_the_tpb_series_for_a_tpb(library):
    library('500', 'Batman', 'Print', 3)
    library('600', 'Batman', 'TPB', 3)
    found = attention.suggest(attention.parse('/downloads/Batman TPB Vol 2 (2017).cbz'))
    assert found[0]['comicid'] == '600' and found[0]['number'] == '2' and found[0]['agree']['format'] is True
    singles = [m for m in found if m['comicid'] == '500'][0]
    assert singles['issueid'] is None and singles['agree']['format'] is False and singles['format'] == 'Single issues'


@pytest.mark.unit
def test_needs_attention_offers_the_singles_series_for_an_issue(library):
    library('500', 'Batman', 'Print', 3)
    library('600', 'Batman', 'TPB', 3)
    found = attention.suggest(attention.parse('/downloads/Batman 002 (2017).cbz'))
    assert found[0]['comicid'] == '500' and found[0]['number'] == '2' and found[0]['agree']['format'] is True
