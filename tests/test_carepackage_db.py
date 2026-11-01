"""The care package's copy of the database has API keys and passwords removed."""
import sqlite3

import pytest

import mylar
from mylar import carepackage, redact

KEY = 'abcdef0123456789abcdef0123456789'


@pytest.fixture
def src(tmp_path, monkeypatch):
    monkeypatch.setattr(redact, 'secrets', lambda: ())
    path = tmp_path / 'mylar.db'
    d = sqlite3.connect(str(path))
    d.execute('CREATE TABLE rssdb (Title TEXT, Link TEXT, Size INTEGER)')
    d.execute('CREATE TABLE comics (ComicID TEXT, ComicName TEXT)')
    d.execute("INSERT INTO rssdb VALUES ('Wonder Woman 783', 'https://api.nzbgeek.info/api?t=get&id=99&apikey=%s', 5)" % KEY)
    d.execute("INSERT INTO rssdb VALUES ('Other', 'https://user:hunter22@host/x?id=1', 1)")
    d.execute("INSERT INTO rssdb VALUES ('Saved key', 'secret-indexer-key-1234 in text', 1)")
    d.execute("INSERT INTO comics VALUES ('2045', 'Fantastic Four')")
    d.commit()
    d.close()
    return path


@pytest.mark.unit
def test_keys_are_removed_and_the_rest_kept(src, tmp_path):
    dest = tmp_path / 'clean.db'
    n = carepackage.scrubbed_db(str(src), str(dest), ['secret-indexer-key-1234', '', '1234'])
    assert n == 3
    d = sqlite3.connect(str(dest))
    links = [r[0] for r in d.execute('SELECT Link FROM rssdb ORDER BY rowid')]
    assert links[0] == 'https://api.nzbgeek.info/api?t=get&id=99&apikey=REDACTED'
    assert 'hunter22' not in links[1]
    assert links[2] == '-REDACTED- in text'
    assert list(d.execute('SELECT * FROM comics')) == [('2045', 'Fantastic Four')]
    assert KEY in sqlite3.connect(str(src)).execute('SELECT Link FROM rssdb').fetchone()[0]
