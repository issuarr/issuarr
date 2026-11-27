"""Want and search missing on a story arc marks the watched series' issues Wanted, not just the arc rows."""
import queue
import types

import pytest

import mylar
from mylar import db, webserve


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(), raising=False)
    monkeypatch.setattr(mylar, 'SEARCH_QUEUE', queue.Queue(), raising=False)
    d = db.DBConnection()
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT, Type TEXT)')
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, ComicName TEXT, Issue_Number TEXT, Status TEXT)')
    d.action('CREATE TABLE storyarcs (StoryArcID TEXT, StoryArc TEXT, IssueArcID TEXT, IssueID TEXT, ComicID TEXT, '
             'ComicName TEXT, IssueNumber TEXT, SeriesYear TEXT, IssueYEAR TEXT, IssueDate TEXT, ReleaseDate TEXT, '
             'Publisher TEXT, Type TEXT, Status TEXT)')
    d.action("INSERT INTO comics VALUES ('2127', 'The Amazing Spider-Man', '1963', 'Print')")
    d.action("INSERT INTO issues VALUES ('106921', '2127', 'The Amazing Spider-Man', '529', 'Skipped')")
    d.action("INSERT INTO issues VALUES ('113517', '2127', 'The Amazing Spider-Man', '530', 'Downloaded')")
    return d


def arc_row(d, arcissue, issueid, number, status):
    d.action("INSERT INTO storyarcs VALUES ('40615', 'Civil War', ?, ?, '2127', 'The Amazing Spider-Man', ?, '1963', "
             "'2006', '2006-02-01', '2006-02-22', 'Marvel', 'Print', ?)", [arcissue, issueid, number, status])


def status(d, table, col, val):
    return d.selectone('SELECT Status FROM %s WHERE %s=?' % (table, col), [val]).fetchone()['Status']


@pytest.mark.unit
def test_want_and_search_missing_marks_the_library_issue_wanted(myDB):
    arc_row(myDB, '40615_5818', '106921', '529', 'Skipped')     # IssueArcID is never an issues.IssueID
    webserve.WebInterface().ReadGetWanted('40615')
    assert status(myDB, 'issues', 'IssueID', '106921') == 'Wanted'
    assert status(myDB, 'storyarcs', 'IssueArcID', '40615_5818') == 'Wanted'
    queued = list(mylar.SEARCH_QUEUE.queue)
    assert [(q['issueid'], q['seriesyear']) for q in queued] == [('106921', '1963')]


@pytest.mark.unit
def test_want_and_search_missing_leaves_downloaded_issues_alone(myDB):
    arc_row(myDB, '40615_4078', '113517', '530', 'Downloaded')
    webserve.WebInterface().ReadGetWanted('40615')
    assert status(myDB, 'issues', 'IssueID', '113517') == 'Downloaded'
    assert list(mylar.SEARCH_QUEUE.queue) == []
