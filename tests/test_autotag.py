"""Untagged issue files get tags on their own while tagging is on."""
import os
import sqlite3
import types
import zipfile

import pytest

import mylar
from mylar import autotag, quicktag, webp


class FakeDB:
    def __init__(self):
        self.c = sqlite3.connect(':memory:', check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.c.execute('CREATE TABLE comics (ComicID TEXT, ComicLocation TEXT, ComicSortName TEXT)')
        self.c.execute('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Location TEXT)')

    def select(self, q, args=()):
        return self.c.execute(q, args).fetchall()

    def selectone(self, q, args=()):
        return self.c.execute(q, args)

    def action(self, q, args=()):
        self.c.execute(q, args)

    def upsert(self, table, vals, ctrl):
        keys = list(ctrl) + list(vals)
        self.c.execute('INSERT OR REPLACE INTO %s (%s) VALUES (%s)' % (table, ', '.join(keys), ', '.join('?' * len(keys))),
                       list(ctrl.values()) + list(vals.values()))


def cbz(path, tagged=False):
    with zipfile.ZipFile(path, 'w') as z:
        for n in range(3):
            z.writestr('%03d.jpg' % n, b'page')
        if tagged:
            z.writestr('ComicInfo.xml', '<ComicInfo/>')


@pytest.fixture
def lib(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(ENABLE_META=True), raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    db = FakeDB()
    db.c.execute("INSERT INTO comics VALUES ('1', ?, 't2')", [str(tmp_path)])
    for n, name in enumerate(['T2 #01.cbz', 'T2 #02.cbz', 'T2 #03.cbr', 'T2 #05.cbz', 'html.cbz']):
        db.c.execute("INSERT INTO issues VALUES (?, '1', ?)", [str(n), name])
    cbz(tmp_path / 'T2 #01.cbz')
    cbz(tmp_path / 'T2 #02.cbz', tagged=True)
    cbz(tmp_path / 'T2 #03.cbr')                        # a zip named .cbr; #05's file is missing
    (tmp_path / 'html.cbz').write_bytes(b'<html>not a comic</html>')
    monkeypatch.setattr(autotag.db, 'DBConnection', lambda: db)
    monkeypatch.setattr(quicktag, 'issue_for_path', lambda path, myDB=None: {'ComicName': 'T2', 'Issue_Number': '1'})
    monkeypatch.setattr(quicktag, 'build', lambda row: b'<ComicInfo><Series>T2</Series></ComicInfo>')
    monkeypatch.setattr(webp, '_relocate', lambda old, new: None)
    monkeypatch.setattr(webp, '_update_size', lambda path, size: None)
    return db, tmp_path


def test_a_pass_tags_untagged_files_and_remembers_the_rest(lib):
    db, folder = lib
    assert autotag.run(busy=lambda: '') == 'finished'
    assert quicktag.tagged(str(folder / 'T2 #01.cbz')) and quicktag.tagged(str(folder / 'T2 #03.cbz'))
    assert (autotag.STATE['tagged'], autotag.STATE['failed'], autotag.STATE['opened']) == (2, 1, 4)
    autotag.run(busy=lambda: '')
    assert autotag.STATE['opened'] == 0          # nothing changed since: only stat()ed


def test_a_pass_gives_way_and_does_nothing_with_tagging_off(lib):
    db, folder = lib
    assert autotag.run(busy=lambda: 'downloads are being filed') == 'gave way: downloads are being filed'
    assert not quicktag.tagged(str(folder / 'T2 #01.cbz'))
    mylar.CONFIG.ENABLE_META = False
    assert not autotag.tick()
    assert autotag.run(busy=lambda: '') == 'tagging was turned off'
    assert not quicktag.tagged(str(folder / 'T2 #01.cbz'))
