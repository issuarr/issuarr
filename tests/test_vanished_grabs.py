"""Grabs the download client no longer has go back to Wanted (issue #259).

Clearing SABnzbd's history left every grab Issuarr had sent there at "Waiting on client" for good:
nothing un-snatched an issue whose job left the client before it was filed.
"""
import datetime
import json
import types

import pytest
import requests

import mylar
from mylar import autoadd, downloadqueue
from mylar.webserve import WebInterface
from tests.test_snatched_reset import NOW, OLD, issue, method, myDB, statuses  # noqa: F401  (fixtures)

LATER = NOW + datetime.timedelta(minutes=10)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(downloadqueue, 'MISSED', {})
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(autoadd, 'running', lambda: False)


def grab(d, iid, jobid, client='sabnzbd', at=OLD, provider='NZBGeek', **kw):
    issue(d, iid, snatched=at, provider=provider, **kw)
    if jobid:
        d.action('INSERT INTO client_jobs VALUES (?, NULL, ?, ?, ?, ?, ?)', [iid, kw.get('comicid', '29329'), client, jobid, 'job %s' % iid, at])


def holding(*ids, asked=None):
    def ask(client, jobids):
        if asked is not None:
            asked.append((client, sorted(jobids)))
        return {i.lower() for i in ids}
    return ask


@pytest.mark.unit
def test_the_queue_button_puts_grabs_the_client_dropped_back_to_wanted(myDB):
    grab(myDB, '903447', 'SABnzbd_nzo_aaa')
    grab(myDB, '903448', 'SABnzbd_nzo_bbb', number='2')
    r = downloadqueue.clear_vanished(myDB, force=True, ask=holding('SABnzbd_nzo_bbb'), rescan=lambda cid: None, now=NOW)
    assert r['wanted'] == ['903447'] and r['gone'] == 1
    assert statuses(myDB) == {'903447': 'Wanted', '903448': 'Snatched'}


@pytest.mark.unit
def test_the_scheduled_check_needs_two_misses_ten_minutes_apart(myDB):
    grab(myDB, '903447', 'SABnzbd_nzo_aaa')
    first = downloadqueue.clear_vanished(myDB, ask=holding(), rescan=lambda cid: None, now=NOW)
    assert first['gone'] == 0 and statuses(myDB) == {'903447': 'Snatched'}
    downloadqueue.clear_vanished(myDB, ask=holding(), rescan=lambda cid: None, now=NOW + datetime.timedelta(minutes=5))
    assert statuses(myDB) == {'903447': 'Snatched'}
    downloadqueue.clear_vanished(myDB, ask=holding(), rescan=lambda cid: None, now=LATER)
    assert statuses(myDB) == {'903447': 'Wanted'}


@pytest.mark.unit
def test_a_job_seen_again_between_checks_starts_over(myDB):
    grab(myDB, '903447', 'SABnzbd_nzo_aaa')
    downloadqueue.clear_vanished(myDB, ask=holding(), rescan=lambda cid: None, now=NOW)
    downloadqueue.clear_vanished(myDB, ask=holding('SABnzbd_nzo_aaa'), rescan=lambda cid: None, now=NOW + datetime.timedelta(minutes=5))
    downloadqueue.clear_vanished(myDB, ask=holding(), rescan=lambda cid: None, now=LATER)
    assert statuses(myDB) == {'903447': 'Snatched'}


@pytest.mark.unit
def test_nothing_changes_when_the_client_cant_be_asked(myDB):
    grab(myDB, '903447', 'SABnzbd_nzo_aaa')
    r = downloadqueue.clear_vanished(myDB, force=True, ask=lambda client, ids: None, rescan=lambda cid: None, now=NOW)
    assert r['unchecked'] == 1 and statuses(myDB) == {'903447': 'Snatched'}


@pytest.mark.unit
def test_grabs_without_their_own_job_id_are_left_alone(myDB):
    # Walking Dead Deluxe 27 in #255: snatched, but no client_jobs row; or only an older grab's job
    grab(myDB, '1', None)
    grab(myDB, '2', 'SABnzbd_nzo_old', number='2', at='2026-10-09 10:00:00')
    myDB.action("INSERT INTO snatched VALUES ('2', 'Deadpool Team-Up', '2', ?, 'Snatched', '29329', 'NZBGeek')", [OLD])
    r = downloadqueue.clear_vanished(myDB, force=True, ask=holding(), rescan=lambda cid: None, now=NOW)
    assert r['unchecked'] == 2 and statuses(myDB) == {'1': 'Snatched', '2': 'Snatched'}


@pytest.mark.unit
def test_new_grabs_are_left_alone(myDB):
    grab(myDB, '903447', 'SABnzbd_nzo_aaa', at=(NOW - datetime.timedelta(minutes=20)).strftime('%Y-%m-%d %H:%M:%S'))
    r = downloadqueue.clear_vanished(myDB, ask=holding(), rescan=lambda cid: None, now=NOW)
    downloadqueue.clear_vanished(myDB, ask=holding(), rescan=lambda cid: None, now=NOW + datetime.timedelta(minutes=5))
    assert r['gone'] == 0 and statuses(myDB) == {'903447': 'Snatched'}


@pytest.mark.unit
def test_a_grab_already_filed_becomes_downloaded_not_wanted(myDB):
    grab(myDB, '903447', 'SABnzbd_nzo_aaa')

    def rescan(cid):
        myDB.action("UPDATE issues SET Status='Downloaded' WHERE IssueID='903447'")
    r = downloadqueue.clear_vanished(myDB, force=True, ask=holding(), rescan=rescan, now=NOW)
    assert r['filed'] == 1 and r['wanted'] == []
    assert statuses(myDB) == {'903447': 'Downloaded'}


@pytest.mark.unit
def test_a_newer_direct_download_keeps_the_issue(myDB):
    grab(myDB, '903447', 'SABnzbd_nzo_aaa')
    myDB.action("INSERT INTO snatched VALUES ('903447', 'Deadpool Team-Up', '1', ?, 'Snatched', '29329', 'DDL(GetComics)')", [OLD.replace('22:41', '23:41')])
    r = downloadqueue.clear_vanished(myDB, force=True, ask=holding(), rescan=lambda cid: None, now=NOW)
    assert r['gone'] == 0 and statuses(myDB) == {'903447': 'Snatched'}


@pytest.mark.unit
def test_each_client_is_asked_about_its_own_jobs(myDB):
    grab(myDB, '1', 'SABnzbd_nzo_aaa')
    grab(myDB, '2', 'ABCDEF', client='qbittorrent', number='2', provider='WWT')
    asked = []
    downloadqueue.clear_vanished(myDB, force=True, ask=holding('abcdef', asked=asked), rescan=lambda cid: None, now=NOW)
    assert sorted(asked) == [('qbittorrent', ['ABCDEF']), ('sabnzbd', ['SABnzbd_nzo_aaa'])]
    assert statuses(myDB) == {'1': 'Wanted', '2': 'Snatched'}


@pytest.mark.unit
def test_forget_puts_one_grab_back_to_wanted(myDB, method):
    grab(myDB, '1', None)
    r = json.loads(WebInterface().forgetGrab(issueid='1'))
    assert r['ok'] and statuses(myDB) == {'1': 'Wanted'}
    assert json.loads(WebInterface().forgetGrab(issueid='1'))['ok'] is False


# ---- asking SABnzbd ---------------------------------------------------------

class Answer(object):
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


@pytest.fixture
def sab(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(SAB_HOST='http://sab:8080', SAB_APIKEY='k'), raising=False)
    monkeypatch.setattr(mylar, 'USE_SABNZBD', True, raising=False)
    calls = []

    def answer(replies):
        def get(url, params=None, **kw):
            calls.append(params)
            return Answer(replies[params['mode']])
        monkeypatch.setattr(requests, 'get', get)
        return calls
    return answer


@pytest.mark.unit
def test_sabnzbd_is_asked_by_job_id_in_queue_and_history(sab):
    calls = sab({'queue': {'queue': {'slots': [{'nzo_id': 'SABnzbd_nzo_a'}]}}, 'history': {'history': {'slots': [{'nzo_id': 'SABnzbd_nzo_b'}]}}})
    assert downloadqueue.client_has('sabnzbd', ['SABnzbd_nzo_a', 'SABnzbd_nzo_b', 'SABnzbd_nzo_c']) == {'sabnzbd_nzo_a', 'sabnzbd_nzo_b'}
    assert {c['mode'] for c in calls} == {'queue', 'history'}
    assert all(c['nzo_ids'] == 'SABnzbd_nzo_a,SABnzbd_nzo_b,SABnzbd_nzo_c' for c in calls)


@pytest.mark.unit
def test_a_sabnzbd_that_ignores_nzo_ids_isnt_trusted(sab):
    # an old version lists every job instead; a job missing from a page of them isn't gone
    sab({'queue': {'queue': {'slots': [{'nzo_id': 'SABnzbd_nzo_tv'}]}}, 'history': {'history': {'slots': []}}})
    assert downloadqueue.client_has('sabnzbd', ['SABnzbd_nzo_a']) is None


@pytest.mark.unit
def test_a_sabnzbd_error_isnt_read_as_every_job_gone(sab):
    sab({'queue': {'status': False, 'error': 'API Key Incorrect'}, 'history': {'status': False}})
    assert downloadqueue.client_has('sabnzbd', ['SABnzbd_nzo_a']) is None
