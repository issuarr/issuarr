"""Imported files that no issue points to say "Imported, no issue" in Import results."""
import os
import sqlite3

import pytest

from mylar import importchoice


class DB:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('CREATE TABLE importresults (impID TEXT, ComicLocation TEXT, Status TEXT, ComicID TEXT)')
        self.conn.execute('CREATE TABLE comics (ComicID TEXT, ComicLocation TEXT)')
        self.conn.execute('CREATE TABLE issues (ComicID TEXT, Location TEXT)')
        self.conn.execute('CREATE TABLE annuals (ComicID TEXT, Location TEXT)')

    def select(self, query, args=()):
        return self.conn.execute(query, args).fetchall()

    def action(self, query, args=()):
        return self.conn.execute(query, args)

    def status(self, impid):
        return self.conn.execute('SELECT Status FROM importresults WHERE impID=?', [impid]).fetchone()[0]


@pytest.fixture
def lib(tmp_path, monkeypatch):
    db = DB()
    monkeypatch.setattr(importchoice.db, 'DBConnection', lambda: db)
    monkeypatch.setattr(importchoice.navcounts, 'clear', lambda: None)
    monkeypatch.setattr(importchoice, '_untied_at', [0])
    series = tmp_path / 'comics' / 'IDW' / 'Locke & Key (2011)'
    loose = tmp_path / 'comics' / 'Image' / 'Retro Rocket'
    series.mkdir(parents=True)
    loose.mkdir(parents=True)
    for f in (series / 'Locke & Key 001.cbz', series / 'Locke & Key TPB.cbz', loose / 'Retro Rocket 03.cbr'):
        f.write_bytes(b'x')
    db.conn.execute('INSERT INTO comics VALUES (?, ?)', ['1', str(series)])
    db.conn.execute('INSERT INTO issues VALUES (?, ?)', ['1', 'Locke & Key 001.cbz'])
    rows = [('a', series / 'Locke & Key 001.cbz', '1'), ('b', series / 'Locke & Key TPB.cbz', '1'),
            ('c', loose / 'Retro Rocket 03.cbr', '2'), ('d', series / 'Locke & Key 002.cbz', '1')]
    for impid, path, comicid in rows:
        db.conn.execute('INSERT INTO importresults VALUES (?, ?, ?, ?)', [impid, str(path), 'Imported', comicid])
    return db, series


def test_files_no_issue_points_to_say_so(lib):
    db, _ = lib
    assert importchoice.mark_untied() == 2
    assert db.status('a') == 'Imported'
    assert db.status('b') == importchoice.NO_ISSUE
    assert db.status('c') == importchoice.NO_ISSUE


def test_a_gone_file_is_left_alone(lib):
    db, _ = lib
    importchoice.mark_untied()
    assert db.status('d') == 'Imported'


def test_only_the_imported_series_is_checked(lib):
    db, _ = lib
    assert importchoice.mark_untied('1') == 1
    assert db.status('b') == importchoice.NO_ISSUE
    assert db.status('c') == 'Imported'


def test_a_file_matched_later_says_imported_again(lib):
    db, _ = lib
    importchoice.mark_untied()
    db.conn.execute('INSERT INTO issues VALUES (?, ?)', ['1', 'Locke & Key TPB.cbz'])
    importchoice.mark_untied()
    assert db.status('b') == 'Imported'


def test_a_cbr_converted_since_counts_under_its_new_name(lib):
    db, series = lib
    os.rename(series / 'Locke & Key TPB.cbz', series / 'Locke & Key TPB.cbr')
    db.conn.execute("UPDATE importresults SET ComicLocation=? WHERE impID='b'", [str(series / 'Locke & Key TPB.cbz')])
    db.conn.execute('INSERT INTO issues VALUES (?, ?)', ['1', 'Locke & Key TPB.cbr'])
    importchoice.mark_untied()
    assert db.status('b') == 'Imported'


def test_the_page_checks_at_most_once_a_minute(lib):
    db, _ = lib
    assert importchoice.mark_untied(force=False) == 2
    db.conn.execute("UPDATE importresults SET Status='Imported'")
    assert importchoice.mark_untied(force=False) == 0
