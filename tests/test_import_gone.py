"""Import results forget files that are gone, even when their whole folder was removed with them."""
import sqlite3
import types

import pytest

import mylar
from mylar import importchoice


class DB:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('CREATE TABLE importresults (impID TEXT, ComicLocation TEXT, Status TEXT)')

    def select(self, query, args=()):
        return self.conn.execute(query, args).fetchall()

    def action(self, query, args=()):
        return self.conn.execute(query, args)

    def left(self):
        return sorted(r[0] for r in self.conn.execute('SELECT impID FROM importresults'))


@pytest.fixture
def lib(tmp_path, monkeypatch):
    db = DB()
    monkeypatch.setattr(importchoice.db, 'DBConnection', lambda: db)
    monkeypatch.setattr(importchoice.navcounts, 'clear', lambda: None)
    comics = tmp_path / 'comics'
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(
        COMIC_DIR=str(comics) + '/', DESTINATION_DIR=str(comics), MULTIPLE_DEST_DIRS='None'), raising=False)
    kept = comics / 'Image' / 'Saga (2012)'
    kept.mkdir(parents=True)
    (kept / 'Saga 001.cbz').write_bytes(b'x')
    rows = [('kept', kept / 'Saga 001.cbz'),
            # a sorting folder deleted with everything in it: nothing two levels up is left
            ('unmatched', comics / '_UNMATCHED' / 'IDW Publishing' / 'Transformers (2009)' / 'Transformers #01 (2009).cbz'),
            ('publisher', comics / 'Image' / 'Dark Horse Comics' / 'Time Traveler Tales (2023)' / 'Time Traveler Tales 001.cbz'),
            ('deleted', kept / 'Saga 002.cbz')]
    for impid, path in rows:
        db.conn.execute('INSERT INTO importresults VALUES (?, ?, ?)', [impid, str(path), 'Manual Intervention'])
    return db, comics


def test_files_gone_with_their_whole_folder_are_forgotten(lib):
    db, _ = lib
    assert importchoice.drop_gone(force=True) == 3
    assert db.left() == ['kept']


def test_an_unmounted_library_folder_is_left_alone(lib):
    db, comics = lib
    for f in sorted(comics.rglob('*'), reverse=True):
        f.unlink() if f.is_file() else f.rmdir()
    assert importchoice.drop_gone(force=True) == 0
    assert len(db.left()) == 4


def test_a_missing_library_folder_is_left_alone(lib, tmp_path):
    db, comics = lib
    mylar.CONFIG.COMIC_DIR = mylar.CONFIG.DESTINATION_DIR = str(tmp_path / 'elsewhere')
    db.conn.execute('INSERT INTO importresults VALUES (?, ?, ?)',
                    ['away', str(tmp_path / 'elsewhere' / 'DC' / 'Batman (2016)' / 'Batman 001.cbz'), 'No Results'])
    importchoice.drop_gone(force=True)
    assert 'away' in db.left()


def test_a_file_outside_the_library_needs_the_folder_two_levels_up(lib, tmp_path):
    db, _ = lib
    (tmp_path / 'downloads' / 'Week').mkdir(parents=True)
    db.conn.execute('INSERT INTO importresults VALUES (?, ?, ?)',
                    ['near', str(tmp_path / 'downloads' / 'Week' / 'Pack' / 'Hulk 001.cbz'), 'No Results'])
    db.conn.execute('INSERT INTO importresults VALUES (?, ?, ?)',
                    ['far', str(tmp_path / 'away' / 'Week' / 'Pack' / 'Hulk 001.cbz'), 'No Results'])
    importchoice.drop_gone(force=True)
    assert 'near' not in db.left()
    assert 'far' in db.left()
