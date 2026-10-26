"""Remove series with its files keeps a folder that another series or other comics still use."""
import sqlite3

import pytest

import mylar
from mylar import helpers


class DB:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT, ComicLocation TEXT)')
        self.conn.execute('CREATE TABLE issues (ComicID TEXT, Location TEXT)')
        self.conn.execute('CREATE TABLE annuals (ComicID TEXT, Location TEXT)')

    def select(self, query, args=()):
        return self.conn.execute(query, args).fetchall()


@pytest.fixture
def lib(tmp_path, monkeypatch):
    db = DB()
    monkeypatch.setattr(helpers.db, 'DBConnection', lambda: db)
    folder = tmp_path / 'Marvel' / 'Avengers (1998)'
    folder.mkdir(parents=True)
    (folder / 'Avengers 001 (1998).cbz').write_bytes(b'x')
    (folder / 'cvinfo').write_text('x')
    db.conn.execute('INSERT INTO comics VALUES (?, ?, ?, ?)', ['7084', 'Avengers', '1998', str(folder)])
    db.conn.execute('INSERT INTO issues VALUES (?, ?)', ['7084', 'Avengers 001 (1998).cbz'])
    return db, folder


def test_a_folder_with_only_the_series_own_files_may_go(lib):
    _, folder = lib
    assert helpers.folder_in_use(str(folder), '7084') is None


def test_a_folder_another_series_uses_stays(lib):
    db, folder = lib
    db.conn.execute('INSERT INTO comics VALUES (?, ?, ?, ?)', ['2128', 'The Avengers', '1963', str(folder)])
    assert 'The Avengers (1963)' in helpers.folder_in_use(str(folder), '7084')


def test_a_folder_holding_another_series_folder_stays(lib):
    db, folder = lib
    db.conn.execute('INSERT INTO comics VALUES (?, ?, ?, ?)', ['9', 'Avengers Annual', '1998', str(folder / 'Annuals')])
    assert 'Avengers Annual' in helpers.folder_in_use(str(folder), '7084')


def test_a_folder_with_other_comics_stays(lib):
    _, folder = lib
    (folder / 'Extras').mkdir()
    (folder / 'Extras' / 'Sketchbook.cbr').write_bytes(b'x')
    assert helpers.folder_in_use(str(folder), '7084') == '1 comic file in it is no issue of this series'


def test_a_sibling_folder_with_a_longer_name_does_not_count(lib):
    db, folder = lib
    db.conn.execute('INSERT INTO comics VALUES (?, ?, ?, ?)', ['3', 'Avengers', '1998b', str(folder) + ' Extra'])
    assert helpers.folder_in_use(str(folder), '7084') is None
