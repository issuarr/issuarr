import datetime
from types import SimpleNamespace

import pytest

import mylar
from mylar import db, discover

WEEKLY = ('CREATE TABLE weekly (SHIPDATE TEXT, PUBLISHER TEXT, ISSUE TEXT, COMIC VARCHAR(150), EXTRA TEXT, STATUS TEXT, '
          'ComicID TEXT, IssueID TEXT, CV_Last_Update TEXT, DynamicName TEXT, weeknumber TEXT, year TEXT, volume TEXT, '
          'seriesyear TEXT, annuallink TEXT, format TEXT, rowid INTEGER PRIMARY KEY)')


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(ANNUALS_ON=False, ALT_PULL=2, COMICVINE_API=None), raising=False)
    d = db.DBConnection()
    d.action(WEEKLY)
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicPublisher TEXT, Status TEXT)')
    return d


def pull(d, comic, issue, comicid, ship, week, year='2026', publisher='Image', fmt='Print', issueid=None):
    d.action('INSERT INTO weekly (SHIPDATE, PUBLISHER, ISSUE, COMIC, ComicID, IssueID, weeknumber, year, seriesyear, format) '
             'VALUES (?,?,?,?,?,?,?,?,?,?)', [ship, publisher, issue, comic, comicid, issueid or comicid + '0', week, year, year, fmt])


@pytest.mark.unit
def test_recent_weeks_are_distinct_and_newest_first():
    weeks = discover.recent_weeks(3, today=datetime.date(2026, 10, 25))
    assert len(weeks) == 3
    assert weeks[0] == (43, 2026)
    assert weeks == sorted(weeks, reverse=True)


@pytest.mark.unit
def test_new_series_are_first_issues_once_per_series(myDB):
    pull(myDB, 'Absolute Batman', '1', '100', '2026-10-21', '43', publisher='DC Comics')
    pull(myDB, 'Absolute Batman', '1', '100', '2026-10-28', '44', publisher='DC Comics', issueid='999')  # a later printing
    pull(myDB, 'Saga', '70', '200', '2026-10-21', '43')
    pull(myDB, 'Saga Vol 11 TP', '1', '300', '2026-10-21', '43', fmt='TP')
    pull(myDB, 'Hulk Omnibus', '1', '301', '2026-10-21', '43', fmt='Hardcover')
    f = discover.feeds(myDB, [(44, 2026), (43, 2026)])
    assert [(c['series'], c['shipdate']) for c in f['new']] == [('Absolute Batman', '2026-10-21')]
    assert sorted(c['series'] for c in f['latest']) == ['Absolute Batman', 'Saga']
    assert next(c for c in f['latest'] if c['series'] == 'Absolute Batman')['shipdate'] == '2026-10-28'


@pytest.mark.unit
def test_only_the_asked_weeks_count(myDB):
    pull(myDB, 'Old Thing', '1', '400', '2026-01-07', '2')
    assert discover.feeds(myDB, [(43, 2026)])['new'] == []


@pytest.mark.unit
def test_for_you_uses_the_publishers_you_collect_and_owned_is_marked(myDB):
    myDB.action("INSERT INTO comics VALUES ('500', 'Monstress', 'Image', 'Active')")
    myDB.action("INSERT INTO comics VALUES ('501', 'Saga', 'Image', 'Active')")
    pull(myDB, 'Monstress', '1', '500', '2026-10-21', '43', publisher='Image')
    pull(myDB, 'New Image Book', '1', '600', '2026-10-21', '43', publisher='Image')
    pull(myDB, 'Some DC Book', '1', '700', '2026-10-21', '43', publisher='DC Comics')
    f = discover.feeds(myDB, [(43, 2026)])
    assert f['publishers'] == ['Image']
    assert sorted(c['series'] for c in f['foryou']) == ['Monstress', 'New Image Book']
    owned = {c['series']: c['owned'] for c in f['new']}
    assert owned == {'Monstress': True, 'New Image Book': False, 'Some DC Book': False}


@pytest.mark.unit
def test_missing_weeks_reads_text_or_numbers(myDB):
    pull(myDB, 'A', '1', '1', '2026-10-21', '43')
    assert discover.missing_weeks(myDB, [(43, 2026), (42, 2026)]) == [(42, 2026)]


@pytest.mark.unit
def test_rows_without_a_comicvine_id_still_show(myDB):
    myDB.action("INSERT INTO weekly (SHIPDATE, PUBLISHER, ISSUE, COMIC, weeknumber, year, format) VALUES "
                "('2026-10-21', 'Oni', '1', 'Brand New', '43', '2026', 'Print')")
    card, = discover.feeds(myDB, [(43, 2026)])['new']
    assert card['comicid'] is None and card['owned'] is False


@pytest.mark.unit
def test_no_weekly_table_is_empty_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(ANNUALS_ON=False), raising=False)
    d = db.DBConnection()
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicPublisher TEXT, Status TEXT)')
    assert discover.feeds(d, [(43, 2026)])['new'] == []
    assert discover.missing_weeks(d, [(43, 2026)]) == [(43, 2026)]


@pytest.mark.unit
def test_cover_urls_are_looked_up_in_one_batch_and_remembered(monkeypatch, tmp_path):
    from mylar import cv
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CVURL', 'https://cv.example/api/', raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(COMICVINE_API='key', CACHE_DIR=str(tmp_path)), raising=False)
    calls = []

    def fake(url, params=None, timeout=None):
        calls.append(params['filter'])
        return SimpleNamespace(json=lambda: {'results': [{'id': 11, 'image': {'medium_url': 'https://img.example/11.jpg'}}]})
    monkeypatch.setattr(cv, 'cv_request', fake)
    monkeypatch.setattr(discover.threading, 'Thread',
                        lambda target, args, **kw: SimpleNamespace(start=lambda: target(*args)))

    assert discover.cover_url('11') is None
    discover.want_covers(['11', '12', '11', None])
    assert calls == ['id:11|12']
    assert discover.cover_url('11') == 'https://img.example/11.jpg'
    assert discover.cover_url('12') == ''          # ComicVine had none: not asked again
    assert discover.cover('12') is None
    discover.want_covers(['11', '12'])
    assert len(calls) == 1
