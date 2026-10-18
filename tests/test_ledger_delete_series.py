"""Ledger > By series: Remove… deletes a series through deleteSeries, which answers in JSON when asked."""
import json
import types

import cherrypy
import pytest

import mylar
from mylar import webserve


class FakeDB:
    def __init__(self, comic):
        self.comic, self.actions = comic, []

    def selectone(self, sql, args):
        return types.SimpleNamespace(fetchone=lambda: self.comic)

    def action(self, sql, args=None):
        self.actions.append(sql)


@pytest.fixture
def setup(monkeypatch, tmp_path):
    def go(comic):
        fake = FakeDB(comic)
        monkeypatch.setattr(webserve.db, 'DBConnection', lambda: fake)
        monkeypatch.setattr(webserve.helpers, 'ComicSort', lambda **k: None)
        monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(ANNUALS_ON=False), raising=False)
        for name in ('info', 'fdebug', 'warn'):
            monkeypatch.setattr(webserve.logger, name, lambda *a, **k: None)
        return fake
    return go


def comic(path):
    return {'ComicName': 'Keeper', 'ComicLocation': str(path), 'ComicYear': '2000', 'ComicVersion': None}


@pytest.mark.unit
def test_ajax_delete_answers_json_and_removes_the_folder_when_asked(setup, tmp_path):
    folder = tmp_path / 'Keeper'
    folder.mkdir()
    (folder / 'k1.cbz').write_text('x')
    fake = setup(comic(folder))
    r = json.loads(webserve.WebInterface().deleteSeries('3', delete_dir='1', ajax='1'))
    assert r == {'ok': True}
    assert not folder.exists()
    assert 'DELETE from comics WHERE ComicID=?' in fake.actions


@pytest.mark.unit
def test_ajax_delete_keeps_files_without_delete_dir(setup, tmp_path):
    folder = tmp_path / 'Keeper'
    folder.mkdir()
    setup(comic(folder))
    assert json.loads(webserve.WebInterface().deleteSeries('3', delete_dir='', ajax='1')) == {'ok': True}
    assert folder.exists()


@pytest.mark.unit
def test_ajax_delete_of_an_unknown_series_says_not_ok(setup):
    setup(None)
    assert json.loads(webserve.WebInterface().deleteSeries('9', ajax='1')) == {'ok': False}


@pytest.mark.unit
def test_series_page_delete_still_redirects_home(setup, tmp_path):
    setup(comic(tmp_path / 'gone'))
    with pytest.raises(cherrypy.HTTPRedirect):
        webserve.WebInterface().deleteSeries('3')
