import sqlite3

import pytest

import mylar
from mylar import Failed


class FakeDB:
    def __init__(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.execute('CREATE TABLE failed (ID TEXT, Status TEXT, ComicID TEXT, IssueID TEXT, Provider TEXT, ComicName TEXT, Issue_Number TEXT, NZBName TEXT, DateFailed TEXT)')

    def add(self, id_, name, comicid='111', status='Failed', prov='nzbgeek'):
        self.c.execute('INSERT INTO failed (ID, Status, ComicID, Provider, NZBName) VALUES (?,?,?,?,?)', (id_, status, comicid, prov, name))

    def select(self, q, args=()):
        return self.c.execute(q, args).fetchall()

    def selectone(self, q, args=()):
        return self.c.execute(q, args)


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)


def test_normalize_title_ignores_dots_case_and_extension():
    a = Failed.normalize_title('Saga.061.(2022).(Digital).cbz')
    assert a == Failed.normalize_title('saga 061 (2022) (digital)')
    assert a == Failed.normalize_title('Saga_061_2022_Digital.nzb')
    assert Failed.normalize_title('Batman & Robin 01') == Failed.normalize_title('Batman and Robin 01')


def test_title_failed_matches_same_series_only():
    db = FakeDB()
    db.add('abc', 'Saga.061.(2022).(Digital)')
    assert Failed.title_failed(db, 'Saga 061 (2022) (Digital).cbz', '111')['ID'] == 'abc'
    assert Failed.title_failed(db, 'Saga 061 (2022) (Digital)', '222') is None
    assert Failed.title_failed(db, 'Saga 062 (2022) (Digital)', '111') is None


def test_title_failed_skips_retries_short_names_and_missing_series():
    db = FakeDB()
    db.add('a', 'Saga 061 (2022)', status='Retry')
    db.add('b', 'X 1')
    assert Failed.title_failed(db, 'Saga 061 (2022)', '111') is None
    assert Failed.title_failed(db, 'X 1', '111') is None
    assert Failed.title_failed(db, 'Saga 061 (2022)', None) is None


def test_failed_check_blocks_new_id_for_failed_title(monkeypatch):
    db = FakeDB()
    db.add('old-id', 'Saga.061.(2022).(Digital)')
    monkeypatch.setattr(Failed.db, 'DBConnection', lambda: db)
    fp = Failed.FailedProcessor(nzb_name='Saga 061 (2022) (Digital)', id='new-id', issueid='9', comicid='111', prov='DOGnzb')
    assert fp.failed_check() == 'Failed'
    fp = Failed.FailedProcessor(nzb_name='Saga 062 (2022) (Digital)', id='other', issueid='10', comicid='111', prov='DOGnzb')
    assert fp.failed_check() == 'Good'
