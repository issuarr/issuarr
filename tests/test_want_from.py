import sqlite3

import pytest

import mylar
from mylar import want_from


class FakeDB:
    def __init__(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.execute('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, WantFrom TEXT)')
        self.c.execute('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT)')

    def select(self, q, args=()):
        return self.c.execute(q, args).fetchall()

    def selectone(self, q, args=()):
        return self.c.execute(q, args)

    def upsert(self, table, vals, ctrl):
        self.c.execute('UPDATE %s SET %s WHERE %s' % (table, ', '.join('%s=?' % k for k in vals), ' AND '.join('%s=?' % k for k in ctrl)),
                       list(vals.values()) + list(ctrl.values()))


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    db = FakeDB()
    db.c.execute("INSERT INTO comics VALUES ('1', 'Saga', NULL)")
    for n, status in (('1', 'Wanted'), ('2', 'Downloaded'), ('24', 'Wanted'), ('25', 'Skipped'), ('26', 'Skipped'),
                      ('26.1', 'Skipped'), ('30', 'Archived'), ('Annual 1', 'Wanted')):
        db.c.execute("INSERT INTO issues VALUES (?, '1', ?, ?)", ['i' + n, n, status])
    monkeypatch.setattr(want_from.db, 'DBConnection', lambda: db)
    want_from._CACHE.clear()
    return db


def statuses(db):
    return {r['Issue_Number']: r['Status'] for r in db.select('SELECT Issue_Number, Status FROM issues')}


def test_decide():
    assert want_from.decide(None, '5', 'Skipped') == 'Skipped'
    assert want_from.decide(25, '5', 'Wanted') == 'Skipped'
    assert want_from.decide(25, '#025', 'Skipped') == 'Wanted'
    assert want_from.decide(25, '25.1', 'Skipped') == 'Wanted'
    assert want_from.decide(25, '30', 'Downloaded') == 'Downloaded'
    assert want_from.decide(25, 'Annual', 'Wanted') == 'Wanted'


def test_set_from_changes_only_wanted_and_skipped(fake):
    out = want_from.set_from('1', '#25')
    assert out['ok'] and out['changed'] == 5
    assert statuses(fake) == {'1': 'Skipped', '2': 'Downloaded', '24': 'Skipped', '25': 'Wanted', '26': 'Wanted',
                              '26.1': 'Wanted', '30': 'Archived', 'Annual 1': 'Wanted'}
    assert fake.select('SELECT WantFrom FROM comics')[0]['WantFrom'] == '25'
    assert want_from.adjust('1', '31', 'Skipped') == 'Wanted'
    assert want_from.adjust('1', '3', 'Wanted') == 'Skipped'


def test_clearing_changes_nothing(fake):
    want_from.set_from('1', '25')
    before = statuses(fake)
    out = want_from.set_from('1', '')
    assert out['ok'] and out['changed'] == 0 and statuses(fake) == before
    assert want_from.adjust('1', '3', 'Wanted') == 'Wanted'


def test_bad_number(fake):
    assert not want_from.set_from('1', 'abc')['ok']
    assert not want_from.set_from('9', '5')['ok']
