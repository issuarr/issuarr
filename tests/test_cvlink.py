"""ComicVine links pasted into Add series, Wrong series, Needs attention and Match a file."""
import types

import pytest

import mylar
from mylar import attention, cv, cvlink, db, mb

VOLUME = 'https://comicvine.gamespot.com/kissmas/4050-54999/'
ISSUE = 'https://comicvine.gamespot.com/kissmas-1-merry-kissmas/4000-374290/'


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'COMICVINE_API', 'key', raising=False)
    monkeypatch.setattr(mylar, 'CVURL', 'https://comicvine.gamespot.com/api/', raising=False)
    for name in ('fdebug', 'info', 'warn'):
        monkeypatch.setattr(cvlink.logger, name, lambda *a, **k: None)
    d = db.DBConnection()
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT, ComicVersion TEXT)')
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, IssueName TEXT)')
    d.action("INSERT INTO comics VALUES ('54999', 'Kissmas', '2012', NULL)")
    d.action("INSERT INTO issues VALUES ('374290', '54999', '1', 'Merry Kissmas')")
    calls = []

    def fake_request(url, params=None, timeout=None):
        calls.append(url)
        return types.SimpleNamespace(json=lambda: {'status_code': 1, 'results': [
            {'id': 999001, 'issue_number': '4', 'name': 'Elsewhere', 'volume': {'id': 77001, 'name': 'Other Series'}}]})
    monkeypatch.setattr(cv, 'cv_request', fake_request)
    return types.SimpleNamespace(db=d, calls=calls)


@pytest.mark.unit
@pytest.mark.parametrize('text, want', [
    (VOLUME, ('volume', '54999')),
    (ISSUE, ('issue', '374290')),
    ('  ' + ISSUE + '  ', ('issue', '374290')),
    ('http://comicvine.gamespot.com/kissmas/4050-54999', ('volume', '54999')),
    ('comicvine.gamespot.com/kissmas/4050-54999/?ref=x', ('volume', '54999')),
    ('https://www.comicvine.com/volume/4050-54999/', ('volume', '54999')),
    ('4050-54999', ('volume', '54999')),
    ('4000-374290', ('issue', '374290')),
])
def test_links_are_read_for_their_series_or_issue(text, want):
    assert cvlink.parse(text) == want


@pytest.mark.unit
@pytest.mark.parametrize('text', ['Kissmas', 'Kissmas 4050', 'https://example.com/kissmas/4050-54999/', '4050-', '',
                                  'https://comicvine.gamespot.com/kissmas/4045-123/', None])
def test_other_text_is_not_a_link(text):
    assert cvlink.parse(text) is None


@pytest.mark.unit
def test_an_issue_on_the_watchlist_resolves_without_asking_comicvine(env):
    assert cvlink.resolve(ISSUE) == {'kind': 'issue', 'issueid': '374290', 'comicid': '54999', 'number': '1', 'name': 'Merry Kissmas'}
    assert cvlink.resolve(VOLUME) == {'kind': 'volume', 'comicid': '54999', 'issueid': None}
    assert env.calls == []


@pytest.mark.unit
def test_an_unknown_issue_is_looked_up_on_comicvine_for_its_series(env):
    link = cvlink.resolve('https://comicvine.gamespot.com/elsewhere/4000-999001/')
    assert (link['comicid'], link['issueid'], link['number'], link['series']) == ('77001', '999001', '4', 'Other Series')
    assert len(env.calls) == 1 and 'issues/' in env.calls[0] and 'filter=id:999001' in env.calls[0]
    # as the user types, only the watchlist is looked at
    assert cvlink.resolve('4000-999001', ask_cv=False) == {'kind': 'issue', 'comicid': None, 'issueid': '999001'}
    assert len(env.calls) == 1


@pytest.mark.unit
def test_a_series_link_asks_comicvine_for_that_one_series_by_id(env, monkeypatch):
    urls = []
    monkeypatch.setattr(mb.cv, 'cv_request', lambda url, **k: urls.append(url) or types.SimpleNamespace(
        content=b'<response><status_code>1</status_code><number_of_total_results>0</number_of_total_results></response>'))
    mb.pullsearch('key', None, 0, 'volume', volumeid='54999')
    mb.pullsearch('key', ['kiss', 'mas'], 0, 'volume')
    assert '&filter=id:54999&' in urls[0]
    assert '&filter=name:kiss,name:mas&' in urls[1]


@pytest.mark.unit
def test_needs_attention_picks_the_series_and_issue_of_a_pasted_link(env):
    out = attention.search_link(ISSUE)
    assert out['series'] == [{'comicid': '54999', 'name': 'Kissmas', 'year': '2012', 'volume': None}]
    assert out['link']['issueid'] == '374290'
    assert attention.search_link('Kissmas') is None
    # not on the watchlist: no series, so the page looks it up on ComicVine
    assert attention.search_link('https://comicvine.gamespot.com/x/4050-1/')['series'] == []


@pytest.mark.unit
def test_comicvine_search_with_a_link_lists_just_its_series(env, monkeypatch):
    seen = []
    monkeypatch.setattr(mb, 'findComic', lambda name, mode, issue, **k: seen.append(k) or [
        {'comicid': '77001', 'name': 'Other Series', 'comicyear': '2020'}])
    out = attention.find_series('https://comicvine.gamespot.com/elsewhere/4000-999001/')
    assert seen == [{'volumeid': '77001'}]
    assert [s['comicid'] for s in out['series']] == ['77001'] and out['link']['issueid'] == '999001'
