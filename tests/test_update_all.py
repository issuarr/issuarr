"""Library > Update all refreshes every active series."""
import sqlite3
import types

import pytest

import mylar
from mylar import importer, updater


class DB:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT, Corrected_SeriesYear TEXT, Corrected_Type TEXT, '
                          'LastUpdated TEXT, LatestDate TEXT, Status TEXT)')
        self.conn.execute('CREATE TABLE exceptions (ComicID TEXT, variloop TEXT)')

    def __call__(self):
        return self

    def select(self, query, args=()):
        return self.conn.execute(query, args).fetchall()

    def selectone(self, query, args=()):
        return self.conn.execute(query, args)


@pytest.fixture
def library(monkeypatch):
    db = DB()
    monkeypatch.setattr(updater.db, 'DBConnection', db)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'IMPORTLOCK', False, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(UPDATE_ENDED=False, CV_ONLY=False, REFRESH_CACHE=7), raising=False)
    monkeypatch.setattr(updater.time, 'sleep', lambda s: None)
    refreshed = []
    monkeypatch.setattr(importer, 'addComictoDB', lambda comicid, mismatch, **kw: refreshed.append(comicid))
    return db, refreshed


def add(db, comicid, year='2020', corrected=None, updated='2026-10-25 10:00:00'):
    db.conn.execute('INSERT INTO comics VALUES (?, ?, ?, ?, NULL, ?, ?, ?)', [comicid, 'Series %s' % comicid, year, corrected, updated, '2026-10-01', 'Active'])


def test_a_corrected_series_year_does_not_stop_the_update(library):
    db, refreshed = library
    add(db, '1', corrected='1996')
    add(db, '2')
    updater.dbUpdate(['1', '2'])
    assert refreshed == ['1', '2']


def test_without_ids_recently_refreshed_series_are_left_alone(library):
    db, refreshed = library
    import datetime
    add(db, '1', updated=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    add(db, '2', updated='2020-01-01 00:00:00')
    updater.dbUpdate()
    assert refreshed == ['2']
