"""Import results: importing a series with a ComicVine ID typed in by hand."""
import json
import sqlite3
import types

import pytest

import mylar
from mylar import webserve
from mylar.webserve import WebInterface


class DB:
    conn = None

    def action(self, query, args=()):
        return self.conn.execute(query, args)


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    DB.conn = sqlite3.connect(':memory:')
    DB.conn.execute('CREATE TABLE importresults (impID TEXT, DynamicName TEXT, Volume TEXT, Status TEXT, ComicID TEXT)')
    DB.conn.executemany('INSERT INTO importresults VALUES (?, ?, ?, ?, ?)', [
        ('1', 'invincible', None, 'No Results', None),
        ('2', 'invincible', None, 'No Results', None),
        ('3', 'invincible', None, 'Imported', '111'),
        ('4', 'invincible', 'v2', 'No Results', None),
    ])
    monkeypatch.setattr(webserve.db, 'DBConnection', DB)
    w = WebInterface()
    w.started = []
    monkeypatch.setattr(w, '_start_import', lambda comiclist, action: w.started.append(comiclist) or True, raising=False)
    return w


def ids():
    return DB.conn.execute('SELECT impID, ComicID FROM importresults ORDER BY impID').fetchall()


@pytest.mark.parametrize('typed', ['39340', ' 4050-39340 ', 'https://comicvine.gamespot.com/invincible/4050-39340/'])
def test_id_or_link_imports_that_series(page, typed):
    out = json.loads(page.importByCvid(typed, 'Invincible', 'invincible'))
    assert out == {'ok': True, 'comicid': '39340'}
    assert ids() == [('1', '39340'), ('2', '39340'), ('3', '111'), ('4', None)]
    assert page.started == [[{'ComicName': 'Invincible', 'DynamicName': 'invincible', 'Volume': None, 'ComicID': '39340'}]]


def test_volume_is_kept_apart(page):
    json.loads(page.importByCvid('39340', 'Invincible', 'invincible', 'v2'))
    assert ids() == [('1', None), ('2', None), ('3', '111'), ('4', '39340')]


def test_text_that_is_not_an_id_is_refused(page):
    out = json.loads(page.importByCvid('invincible', 'Invincible', 'invincible'))
    assert out['ok'] is False
    assert page.started == []
    assert ids()[0] == ('1', None)
