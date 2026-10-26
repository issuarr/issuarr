"""Stop and Pause for the search queue (Wanted), direct downloads (Downloads) and running jobs (Tasks)."""
import collections
import json
import queue
import threading
import types

import cherrypy
import pytest

import mylar
from mylar import db, search
from mylar.queues import ddl
from mylar.queues import search as search_worker
from mylar.webserve import WebInterface


def item(issueid, comicid='21'):
    return {'issueid': issueid, 'comicid': comicid, 'comicname': 'Uncanny X-Men', 'issuenumber': issueid}


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(cherrypy.request, 'method', 'POST', raising=False)


@pytest.fixture
def searching(monkeypatch, quiet):
    q = queue.Queue()
    for n in ('2', '3'):
        q.put(item(n, comicid=n))
    q.put('exit')
    monkeypatch.setattr(mylar, 'SEARCH_QUEUE', q, raising=False)
    monkeypatch.setattr(mylar, 'SEARCH_CURRENT', item('1'), raising=False)
    monkeypatch.setattr(mylar, 'SEARCH_ABORT', None, raising=False)
    monkeypatch.setattr(mylar, 'SEARCH_PAUSED', False, raising=False)
    monkeypatch.setattr(mylar, 'SEARCHLOCK', True, raising=False)
    monkeypatch.setattr(search_worker, 'HELD', {'2': 0})
    return q


def control(action):
    return json.loads(WebInterface().search_queue_control(action=action))


@pytest.mark.unit
def test_stop_searching_empties_the_queue_and_stops_any_search(searching):
    r = control('stop')
    assert r['message'] == 'Stopping the search for Uncanny X-Men #1, 2 waiting searches dropped'
    assert list(searching.queue) == ['exit'] and search_worker.HELD == {}
    for comicid in ('21', '999', None):   # whatever is being searched stops at its next provider
        with pytest.raises(search.SearchAborted):
            search.check_aborted(comicid)


@pytest.mark.unit
def test_stop_with_nothing_searching(searching, monkeypatch):
    monkeypatch.setattr(mylar, 'SEARCH_CURRENT', None)
    searching.queue.clear()
    assert control('stop')['message'] == 'Nothing was searching'
    assert mylar.SEARCH_ABORT is None


@pytest.mark.unit
def test_pause_and_resume_searches(searching):
    assert control('pause')['message'] == 'Searches paused. The one running now finishes first'
    assert mylar.SEARCH_PAUSED is True and search.search_status()['paused'] is True
    assert control('resume')['message'] == 'Searches resumed'
    assert mylar.SEARCH_PAUSED is False


@pytest.mark.unit
def test_queue_controls_are_post_only(searching, monkeypatch):
    monkeypatch.setattr(cherrypy.request, 'method', 'GET', raising=False)
    for call in (lambda: WebInterface().search_queue_control(action='stop'),
                 lambda: WebInterface().ddl_queue_control(action='stop_all'),
                 lambda: WebInterface().job_stop(job='RSS Feeds')):
        with pytest.raises(cherrypy.HTTPError):
            call()
    assert len(searching.queue) == 3


@pytest.mark.unit
def test_a_paused_search_queue_takes_nothing_new_but_still_shuts_down(monkeypatch, quiet):
    q = queue.Queue()
    q.put(item('5'))
    monkeypatch.setattr(mylar, 'SEARCHLOCK', False, raising=False)
    monkeypatch.setattr(mylar, 'SEARCH_PAUSED', True, raising=False)
    slept = []

    def sleep(s):
        slept.append(s)
        if len(slept) == 3:
            q.put('exit')
    monkeypatch.setattr(search_worker.time, 'sleep', sleep)
    search_worker.search_queue(q)   # returns once the exit marker is waiting
    assert slept == [2, 2, 2] and q.queue[0]['issueid'] == '5'


@pytest.mark.unit
def test_paused_direct_downloads_start_nothing_new(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_MAX_PARALLEL=3), raising=False)
    monkeypatch.setattr(mylar, 'DDL_PAUSED', True, raising=False)
    monkeypatch.setattr(ddl, 'PENDING', collections.deque([{'id': 'a'}]))
    monkeypatch.setattr(ddl, 'RUNNING', [0])
    monkeypatch.setattr(ddl, 'STOP', threading.Event())
    started = []
    monkeypatch.setattr(ddl, '_start', lambda *a: started.append(a))
    ddl.start_waiting()
    assert not started and list(ddl.PENDING) == [{'id': 'a'}]
    mylar.DDL_PAUSED = False
    ddl.start_waiting()
    assert len(started) == 1


@pytest.mark.unit
def test_a_paused_getcomics_worker_puts_its_item_back_in_front(monkeypatch):
    q = queue.Queue()
    for i in ('a', 'b'):
        q.put({'id': i})
    stop = threading.Event()
    monkeypatch.setattr(mylar, 'DDL_PAUSED', False, raising=False)
    monkeypatch.setattr(ddl, 'WORKER_POLL', 0.01)

    def nxt(q_, stop_):
        got = q_.get_nowait()
        mylar.DDL_PAUSED = True   # paused while the worker waited for this item
        stop.set()
        return got
    monkeypatch.setattr(ddl, '_next', lambda q_, s: nxt(q_, s) if not stop.is_set() else None)
    ran = []
    monkeypatch.setattr(ddl, 'run_download', ran.append)
    ddl.gc_worker(q, stop)
    assert not ran and [x['id'] for x in q.queue] == ['a', 'b']


@pytest.fixture
def ddl_db(monkeypatch, tmp_path, quiet):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(mylar, 'DDL_PAUSED', False, raising=False)
    d = db.DBConnection()
    d.action('CREATE TABLE ddl_info (ID TEXT UNIQUE, series TEXT, status TEXT, issueid TEXT)')
    d.action('CREATE TABLE issues (IssueID TEXT, Status TEXT)')
    d.action('CREATE TABLE snatched (IssueID TEXT, Status TEXT)')
    for rid, status in (('1', 'Downloading'), ('2', 'Queued'), ('3', 'Completed'), ('4', 'Failed')):
        d.action('INSERT INTO ddl_info VALUES (?, ?, ?, ?)', [rid, 'Series %s' % rid, status, 'iss%s' % rid])
        d.action('INSERT INTO issues VALUES (?, ?)', ['iss%s' % rid, 'Downloaded'])
    return d


@pytest.mark.unit
def test_stop_all_stops_running_and_removes_queued_direct_downloads(ddl_db):
    r = json.loads(WebInterface().ddl_queue_control(action='stop_all'))
    assert r['message'].startswith('Stopped 1 download and removed 1 queued')
    assert sorted((x['ID'], x['status']) for x in ddl_db.select('SELECT ID, status FROM ddl_info')) == \
        [('1', 'Failed'), ('3', 'Completed'), ('4', 'Failed')]
    assert mylar.DDL_CANCEL == {'1', '2'}


@pytest.mark.unit
def test_pause_and_resume_direct_downloads(ddl_db):
    assert json.loads(WebInterface().ddl_queue_control(action='pause'))['status'] is True
    assert mylar.DDL_PAUSED is True
    json.loads(WebInterface().ddl_queue_control(action='resume'))
    assert mylar.DDL_PAUSED is False


@pytest.mark.unit
@pytest.mark.parametrize('job, status, key, ok', [
    ('RSS Feeds', 'Running', 'rss', True),
    ('Folder Monitor', 'Running', 'monitor', True),
    ('RSS Feeds', 'Waiting', 'rss', False),       # not running: nothing to stop
    ('Check Version', 'Running', None, False),    # finishes in moments, no stop points
])
def test_job_stop_asks_only_running_stoppable_jobs(monkeypatch, quiet, job, status, key, ok):
    monkeypatch.setattr(mylar, 'JOB_STOP', set(), raising=False)
    monkeypatch.setattr(WebInterface, '_job_rows', lambda self: [{'jobname': job, 'status': status}])
    r = json.loads(WebInterface().job_stop(job=job))
    assert r['ok'] is ok
    assert mylar.JOB_STOP == ({key} if ok else set())
    if ok:
        assert mylar.helpers.job_stopping(key)
