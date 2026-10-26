"""Two series sharing a folder, and two files for one issue: the file from the issue's own year wins."""
import os

import pytest

import mylar
from mylar import db, matching, updater


def comic_file(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'x' * size)


@pytest.fixture
def shared(monkeypatch, tmp_path):
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
    mylar.dbcheck()
    d = db.DBConnection()
    old, new, alone = tmp_path / 'library' / 'Foo (1998)', None, tmp_path / 'library' / 'Bar (2020)'
    for cid, name, year, folder in (('500', 'Foo', '1963', old), ('501', 'Foo', '1998', old), ('502', 'Bar', '2020', alone)):
        d.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicLocation, ComicPublisher, Type, Status, Total, Have) "
                 "VALUES (?, ?, ?, ?, 'Marvel', 'Print', 'Active', 3, 0)", [cid, name, year, str(folder)])
        for n in range(1, 4):
            d.action("INSERT INTO issues (IssueID, ComicID, ComicName, Issue_Number, Int_IssueNumber, IssueDate, Status) "
                     "VALUES (?, ?, ?, ?, ?, ?, 'Wanted')", ['%s%s' % (cid, n), cid, name, str(n), n * 1000, '%s-0%s-01' % (year, n)])
    # the 1963 files are the larger ones, as in a library where the old volume is a better scan
    comic_file(old / 'Foo 1 (1963).cbz', 5000)
    comic_file(old / 'Foo 1 (1998).cbz', 1000)
    comic_file(old / 'Foo 2 (1998).cbz', 1000)
    comic_file(old / 'Foo 3 (1963).cbz', 5000)
    comic_file(alone / 'Bar 1 (2005).cbz', 1000)
    return old


def issue(i):
    r = db.DBConnection().selectone('SELECT Status, Location FROM issues WHERE IssueID=?', [i]).fetchone()
    return r['Status'], r['Location']


@pytest.mark.unit
def test_the_file_from_the_issues_own_year_wins_over_a_bigger_one_from_another_volume(shared):
    updater.forceRescan('501')
    assert issue('5011') == ('Downloaded', 'Foo 1 (1998).cbz')
    assert issue('5012') == ('Downloaded', 'Foo 2 (1998).cbz')


@pytest.mark.unit
def test_a_far_off_year_file_is_not_taken_when_the_folder_is_shared(shared):
    updater.forceRescan('501')
    assert issue('5013')[0] != 'Downloaded'
    updater.forceRescan('500')
    assert issue('5001') == ('Downloaded', 'Foo 1 (1963).cbz')
    assert issue('5003') == ('Downloaded', 'Foo 3 (1963).cbz')
    assert issue('5002')[0] != 'Downloaded'


@pytest.mark.unit
def test_a_series_with_its_own_folder_still_takes_a_reprint_from_another_year(shared):
    updater.forceRescan('502')
    assert issue('5021') == ('Downloaded', 'Bar 1 (2005).cbz')


@pytest.mark.unit
@pytest.mark.parametrize('name,year', [
    ('The Avengers 16 (1965).cbz', 1965), ('Foo 5 (Jan 2008).cbz', 2008), ('Foo 7 (03-2000).cbz', 2000),
    ('Batman 428 [1988].cbz', 1988), ('Foo 12 (of 12) (2007).cbz', 2007), ('Foo (c2c) (2020-05).cbz', 2020),
    ('Foo 001.cbz', None), ('Foo 1999 issue.cbz', None)])
def test_the_year_is_read_from_brackets_in_the_name(name, year):
    assert matching.name_year(name) == year


@pytest.mark.unit
def test_a_year_is_off_only_when_three_or_more_years_away():
    assert matching.year_off('Foo 1 (1965).cbz', '1999-05-01')
    assert matching.year_off('Foo 1 (1997).cbz', '1999-05-01') is False
    assert matching.year_off('Foo 1 (2002).cbz', '1999-05-01')
    assert matching.year_off('Foo 1.cbz', '1999-05-01') is False
    assert matching.year_off('Foo 1 (1965).cbz', None) is False


@pytest.mark.unit
def test_the_year_preference_needs_exactly_one_file_to_fit():
    assert matching.year_preference('Foo 1 (1999).cbz', 'Foo 1 (1965).cbz', '1999-05-01') == 'new'
    assert matching.year_preference('Foo 1 (1965).cbz', 'Foo 1 (1999).cbz', '1999-05-01') == 'existing'
    assert matching.year_preference('Foo 1 (1998).cbz', 'Foo 1 (1999).cbz', '1999-05-01') is None
    assert matching.year_preference('Foo 1 (1960).cbz', 'Foo 1 (1965).cbz', '1999-05-01') is None
    assert matching.year_preference('Foo 1.cbz', 'Foo 1 (1965).cbz', '1999-05-01') == 'new'
