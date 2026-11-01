"""A pack doesn't claim issues already Snatched by another grab."""
import pytest

import mylar
from mylar import db, helpers


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'PACK_ISSUEIDS_DONT_QUEUE', {}, raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    for k, v in mylar.config._CONFIG_DEFINITIONS.items():
        monkeypatch.setattr(mylar.CONFIG, k, v[2], raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'ZERO_LEVEL_N', None, raising=False)
    d = db.DBConnection()
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Int_IssueNumber INTEGER, Status TEXT)')
    for n in range(25, 37):
        status = 'Snatched' if n <= 30 else 'Downloaded' if n == 31 else 'Wanted'
        d.action('INSERT INTO issues VALUES (?, ?, ?, ?, ?)',
                 ['iss%s' % n, '100', str(n), helpers.issue_number_parser(str(n)).asInt, status])
    return d


@pytest.mark.unit
def test_snatched_issues_are_left_out(myDB):
    r = helpers.issue_find_ids('Mighty Avengers', '100', '25-36', '36', 'pack1')
    assert r['valid'] is True
    assert [x['issuenumber'] for x in r['issues']] == [str(n) for n in range(32, 37)]
    assert set(mylar.PACK_ISSUEIDS_DONT_QUEUE) == {'iss%s' % n for n in range(32, 37)}


@pytest.mark.unit
def test_the_searched_issue_is_kept_even_if_snatched(myDB):
    myDB.action("UPDATE issues SET Status='Snatched' WHERE IssueID='iss36'")
    r = helpers.issue_find_ids('Mighty Avengers', '100', '25-36', '36', 'pack1')
    assert r['valid'] is True
    assert 'iss36' in [x['issueid'] for x in r['issues']]
