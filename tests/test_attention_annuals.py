"""Needs attention and filing know the annuals kept with their series (Keep annuals with their series, #274)."""
import os
import types

import pytest

import mylar
from mylar import attention, db, unmatched
from tests.test_attention import touch


@pytest.fixture
def env(monkeypatch, tmp_path):
    review = tmp_path / 'mylar-review'
    review.mkdir()
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    for k, v in dict(IGNORE_SEARCH_WORDS=[], CUSTOM_ISSUE_EXCEPTIONS=[], ANNUALS_ON=True, FOLDER_SCAN_LOG_VERBOSE=False,
                     ARCHIVE_REVIEW_DIR=str(review), ATTENTION_TRASH_DAYS=14, ZERO_LEVEL_N=None, ZERO_LEVEL=False).items():
        monkeypatch.setattr(mylar.CONFIG, k, v, raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    for name in ('fdebug', 'info', 'warn'):
        monkeypatch.setattr(attention.logger, name, lambda *a, **k: None)
    monkeypatch.setattr(attention, '_COUNT', [0.0, 0])
    monkeypatch.setattr(attention, '_COMICS', [0.0, []])
    monkeypatch.setattr(attention, 'JOBS', {})
    d = db.DBConnection()
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT, ComicVersion TEXT, Total INTEGER, Type TEXT, Corrected_Type TEXT, '
             'AlternateSearch TEXT, AgeRating TEXT)')
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT, IssueDate TEXT, ReleaseDate TEXT)')
    d.action('CREATE TABLE annuals (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Int_IssueNumber INT, Status TEXT, IssueDate TEXT, ReleaseDate TEXT, '
             'ReleaseComicID TEXT, ReleaseComicName TEXT, Deleted INT DEFAULT 0)')
    d.action("INSERT INTO comics (ComicID, ComicName, ComicYear, Total) VALUES ('110000', 'Sonic the Hedgehog', '2018', 80)")
    d.action("INSERT INTO issues VALUES ('901', '110000', '1', 'Downloaded', '2018-07-01', NULL)")
    d.action("INSERT INTO annuals VALUES ('a19', '110000', '1', 1000, 'Wanted', '2019-07-01', NULL, '120000', 'Sonic the Hedgehog Annual 2019', 0), "
             "('a24', '110000', '1', 1000, 'Wanted', '2024-07-01', NULL, '160329', 'Sonic the Hedgehog Annual 2024', 0)")
    return types.SimpleNamespace(root=tmp_path, review=review, db=d)


@pytest.mark.unit
def test_a_waiting_annual_is_matched_to_the_annual_kept_with_its_series(env):
    p = touch(env.review / 'Sonic the Hedgehog Annual 2024 001 (2024).cbz')
    attention.record(p, 'series')
    [item] = attention.items()
    best = item['matches'][0]
    assert (best['comicid'], best['issueid'], best['label']) == ('110000', 'a24', 'Annual 2024 #1')
    assert best['agree']['issue'] and best['agree']['year']


@pytest.mark.unit
def test_the_issue_picker_lists_the_annuals_after_the_issues(env):
    listed = attention.issues('110000')
    assert [i['IssueID'] for i in listed] == ['901', 'a19', 'a24']
    assert listed[2]['Label'] == 'Annual 2024 #1' and listed[2]['Annual']
    mylar.CONFIG.ANNUALS_ON = False
    assert [i['IssueID'] for i in attention.issues('110000')] == ['901']


@pytest.mark.unit
def test_file_as_an_annual_files_it_as_that_annual(env, monkeypatch):
    p = touch(env.review / 'sonic annual.cbz')
    seen = []

    class FakePP(object):
        def __init__(self, *a, **k):
            pass

        def nzb_or_oneoff_pp(self, manual=None):
            seen.extend(manual)
            os.replace(p, str(env.root / 'library.cbz'))
            db.DBConnection().action("UPDATE annuals SET Status='Downloaded' WHERE IssueID='a24'")

    from mylar import PostProcessor
    monkeypatch.setattr(PostProcessor, 'PostProcessor', FakePP)
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args, **k: types.SimpleNamespace(start=lambda: target(*args)))
    out = attention.file_as(p, '110000', 'a24')
    assert out['ok'] and 'Sonic the Hedgehog Annual 2024 #1' in out['note']
    [entry] = seen
    assert (entry['IssueID'], entry['AnnualType'], entry['AnnualSeries']) == ('a24', 'Annual', 'Sonic the Hedgehog Annual 2024')
    assert attention.JOBS[p]['state'] == 'filed'


@pytest.mark.unit
def test_filing_picks_up_a_file_named_for_an_annual(env):
    from mylar import PostProcessor
    p = touch(env.root / 'dl' / 'Sonic the Hedgehog Annual 2024 #1 (2024).cbz')
    pp = PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)
    pp.module = '[TEST]'
    entry = pp._named_annual(db.DBConnection(), {'issueid': None}, p)
    assert (entry['ComicID'], entry['IssueID'], entry['AnnualType']) == ('110000', 'a24', 'Annual')
    assert pp._named_annual(db.DBConnection(), {'issueid': None}, touch(env.root / 'dl' / 'Sonic the Hedgehog 002 (2018).cbz')) is None
    mylar.CONFIG.ANNUALS_ON = False
    assert pp._named_annual(db.DBConnection(), {'issueid': None}, p) is None


def fake_get(calls):
    def get(url, **kw):
        calls.append(url)
        return types.SimpleNamespace(content=b'\xff\xd8jpeg', headers={'Content-Type': 'image/jpeg'}, raise_for_status=lambda: None)
    return get


@pytest.mark.unit
def test_an_annual_shows_its_kept_cover(env, monkeypatch):
    import requests
    from mylar import cvlink
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root / 'cache'), raising=False)
    for table in ('issues', 'annuals'):
        env.db.action('ALTER TABLE %s ADD COLUMN ImageURL TEXT' % table)
        env.db.action('ALTER TABLE %s ADD COLUMN ImageURL_ALT TEXT' % table)
    env.db.action("UPDATE annuals SET ImageURL='https://comicvine.gamespot.com/a/uploads/scale_small/sonic24.jpg' WHERE IssueID='a24'")
    calls = []
    monkeypatch.setattr(requests, 'get', fake_get(calls))
    monkeypatch.setattr(cvlink, 'cv_issue_image', lambda i: pytest.fail('asked ComicVine for a kept cover'))
    out = attention.issue_cover('a24')
    assert open(out, 'rb').read() == b'\xff\xd8jpeg' and calls == ['https://comicvine.gamespot.com/a/uploads/scale_small/sonic24.jpg']


@pytest.mark.unit
def test_an_older_annual_gets_its_cover_from_comicvine_once(env, monkeypatch):
    import requests
    from mylar import cvlink
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root / 'cache'), raising=False)
    for table in ('issues', 'annuals'):
        env.db.action('ALTER TABLE %s ADD COLUMN ImageURL TEXT' % table)
        env.db.action('ALTER TABLE %s ADD COLUMN ImageURL_ALT TEXT' % table)
    asked = []
    monkeypatch.setattr(cvlink, 'cv_issue_image', lambda i: asked.append(i) or ('https://cv/small/%s.jpg' % i if i == 'a24' else None))
    monkeypatch.setattr(requests, 'get', fake_get([]))
    assert attention.issue_cover('a24') is not None
    assert attention.issue_cover('a24') is not None
    assert env.db.selectone("SELECT ImageURL FROM annuals WHERE IssueID='a24'").fetchone()[0] == 'https://cv/small/a24.jpg'
    # ComicVine has none for this one: not asked again straight away
    assert attention.issue_cover('a19') is None and attention.issue_cover('a19') is None
    assert asked == ['a24', 'a19']
