"""Import results: importing a series with a ComicVine ID typed in by hand."""
import json
import sqlite3
import types

import pytest

import mylar
from mylar import cvlink, webserve
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
    # 39340 is a series, 664333 an issue of it, 999 neither
    monkeypatch.setattr(cvlink, 'series_for_number', lambda n: {'39340': '39340', '664333': '39340'}.get(n))
    monkeypatch.setattr(cvlink, 'local_issue', lambda n: None)
    monkeypatch.setattr(cvlink, 'cv_issue', lambda n: {'issueid': n, 'comicid': '39340'} if n == '664333' else None)
    w = WebInterface()
    w.started = []
    monkeypatch.setattr(w, '_start_import', lambda comiclist, action: w.started.append(comiclist) or True, raising=False)
    return w


def ids():
    return DB.conn.execute('SELECT impID, ComicID FROM importresults ORDER BY impID').fetchall()


@pytest.mark.parametrize('typed', ['39340', ' 4050-39340 ', 'https://comicvine.gamespot.com/invincible/4050-39340/',
                                   '4000-664333', '664333', 'https://comicvine.gamespot.com/invincible-1/4000-664333/'])
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


def test_number_that_comicvine_does_not_know_is_refused(page):
    out = json.loads(page.importByCvid('999', 'Invincible', 'invincible'))
    assert out['ok'] is False
    assert page.started == []


class Lookup:
    def __init__(self, comics=(), issues=None):
        self.comics, self.issues = set(comics), issues or {}

    def __call__(self):
        return self

    def selectone(self, query, args):
        found = args[0] in self.comics
        return types.SimpleNamespace(fetchone=lambda: {'ComicID': args[0]} if found else None)


@pytest.fixture
def numbers(monkeypatch):
    def setup(comics=(), local=None, cv_series=None, cv_issues=None):
        monkeypatch.setattr(cvlink.db, 'DBConnection', Lookup(comics))
        monkeypatch.setattr(cvlink, 'local_issue', lambda n: {'comicid': local[n]} if local and n in local else None)
        monkeypatch.setattr(cvlink, 'cv_series', lambda n: cv_series(n) if callable(cv_series) else cv_series)
        monkeypatch.setattr(cvlink, 'cv_issue', lambda n: {'comicid': cv_issues[n]} if cv_issues and n in cv_issues else None)
    return setup


def test_number_on_the_watchlist_is_that_series(numbers):
    numbers(comics=['39340'], cv_series=lambda n: pytest.fail('asked ComicVine'))
    assert cvlink.series_for_number('39340') == '39340'


def test_number_of_a_watchlist_issue_is_its_series(numbers):
    numbers(local={'664333': '39340'}, cv_series=lambda n: pytest.fail('asked ComicVine'))
    assert cvlink.series_for_number('664333') == '39340'


def test_comicvine_series_wins_over_issue(numbers):
    numbers(cv_series=True, cv_issues={'5000': '1'})
    assert cvlink.series_for_number('5000') == '5000'


def test_comicvine_issue_stands_for_its_series(numbers):
    numbers(cv_series=False, cv_issues={'664333': '39340'})
    assert cvlink.series_for_number('664333') == '39340'


def test_unknown_number_is_none(numbers):
    numbers(cv_series=False)
    assert cvlink.series_for_number('999') is None


def test_without_comicvine_a_number_is_taken_as_a_series(numbers):
    numbers(cv_series=None)
    assert cvlink.series_for_number('39340') == '39340'
