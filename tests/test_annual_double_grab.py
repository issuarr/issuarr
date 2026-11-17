"""An annual listed under its series and as an issue of a separate Annual series is only grabbed once."""
import pytest

import mylar
from mylar import db, helpers


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    d = db.DBConnection()
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Status TEXT)')
    d.action('CREATE TABLE annuals (IssueID TEXT, ComicID TEXT, Status TEXT, Deleted INTEGER DEFAULT 0)')
    d.action('CREATE TABLE storyarcs (IssueArcID TEXT, Status TEXT)')
    return d


@pytest.mark.unit
@pytest.mark.parametrize('issue, annual, expected', [
    ('Wanted', 'Snatched', True),
    ('Snatched', 'Wanted', True),
    ('Wanted', 'Downloaded', True),
    ('Wanted', 'Wanted', False),
])
def test_either_copy_counts(myDB, issue, annual, expected):
    myDB.action("INSERT INTO issues VALUES ('223399', '2129', ?)", [issue])
    myDB.action("INSERT INTO annuals (IssueID, ComicID, Status) VALUES ('223399', '2045', ?)", [annual])
    assert helpers.issue_status('223399') is expected


@pytest.mark.unit
def test_deleted_annual_is_ignored(myDB):
    myDB.action("INSERT INTO issues VALUES ('1', '2129', 'Wanted')")
    myDB.action("INSERT INTO annuals VALUES ('1', '2045', 'Snatched', 1)")
    assert helpers.issue_status('1') is False


@pytest.mark.unit
def test_single_rows_still_work(myDB):
    myDB.action("INSERT INTO issues VALUES ('2', '1', 'Snatched')")
    myDB.action("INSERT INTO annuals (IssueID, ComicID, Status) VALUES ('3', '1', 'Wanted')")
    myDB.action("INSERT INTO storyarcs VALUES ('4', 'Downloaded')")
    assert helpers.issue_status('2') is True
    assert helpers.issue_status('3') is False
    assert helpers.issue_status('4') is True
    assert helpers.issue_status('5') is False
