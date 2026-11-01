"""A later grab of the same issue from the same provider keeps its own snatched row."""
import datetime

import pytest

import mylar
from mylar import db, updater

KEY = {'IssueID': '223399', 'Status': 'Snatched', 'Provider': 'NZBGeek'}


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    d = db.DBConnection()
    d.action('CREATE TABLE snatched (IssueID TEXT, ComicName TEXT, Issue_Number TEXT, Size INTEGER, DateAdded TEXT, '
             'Status TEXT, FolderName TEXT, ComicID TEXT, Provider TEXT, Hash TEXT, crc TEXT)')
    return d


def ago(minutes):
    return (datetime.datetime.now() - datetime.timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')


def values(when):
    return {'ComicName': 'Fantastic Four Annual', 'ComicID': '2129', 'Issue_Number': '32', 'DateAdded': when,
            'Status': 'Snatched', 'Hash': None}


def rows(d):
    return [r['DateAdded'] for r in d.select('SELECT DateAdded FROM snatched ORDER BY DateAdded')]


@pytest.mark.unit
def test_first_grab_is_added(myDB):
    updater._record_snatch(myDB, values(ago(0)), KEY)
    assert len(rows(myDB)) == 1


@pytest.mark.unit
def test_the_same_grab_moments_later_updates_its_row(myDB):
    updater._record_snatch(myDB, values(ago(2)), KEY)
    updater._record_snatch(myDB, values(ago(0)), KEY)
    assert rows(myDB) == [ago(0)]


@pytest.mark.unit
def test_a_later_grab_gets_its_own_row(myDB):
    old, new = ago(60 * 24 * 2), ago(0)
    updater._record_snatch(myDB, values(old), KEY)
    updater._record_snatch(myDB, values(new), KEY)
    assert rows(myDB) == [old, new]
    updater._record_snatch(myDB, values(ago(0)), KEY)
    assert rows(myDB) == [old, ago(0)]


@pytest.mark.unit
def test_another_provider_is_its_own_row(myDB):
    updater._record_snatch(myDB, values(ago(0)), KEY)
    updater._record_snatch(myDB, values(ago(0)), dict(KEY, Provider='DDL(GetComics)'))
    assert len(rows(myDB)) == 2
