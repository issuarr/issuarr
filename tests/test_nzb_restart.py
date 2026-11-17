"""SABnzbd/NZBGet grabs survive a restart and don't wait behind each other (issue #268)."""
import queue
import types

import pytest

import mylar
from mylar import db, sabnzbd, nzbget
from mylar.queues import nzb


@pytest.fixture
def cfg(monkeypatch):
    c = types.SimpleNamespace(SAB_HOST='http://sab:8080', SAB_APIKEY='k', SAB_CATEGORY=None,
                              SAB_CLIENT_POST_PROCESSING=True, NZBGET_CLIENT_POST_PROCESSING=False)
    monkeypatch.setattr(mylar, 'CONFIG', c, raising=False)
    monkeypatch.setattr(mylar, 'USE_SABNZBD', True, raising=False)
    monkeypatch.setattr(mylar, 'USE_NZBGET', False, raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(nzb.time, 'sleep', lambda s: None)
    monkeypatch.setattr(sabnzbd.time, 'sleep', lambda s: None)
    monkeypatch.setattr(nzbget.time, 'sleep', lambda s: None)
    return c


@pytest.fixture
def myDB(monkeypatch, tmp_path, cfg):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    d = db.DBConnection()
    d.action('CREATE TABLE client_jobs (IssueID TEXT, IssueArcID TEXT, ComicID TEXT, Client TEXT, JobID TEXT, Name TEXT, DateAdded TEXT)')
    d.action('CREATE TABLE issues (IssueID TEXT, Status TEXT)')
    d.action('CREATE TABLE annuals (IssueID TEXT, Status TEXT, Deleted INTEGER DEFAULT 0)')
    d.action('CREATE TABLE storyarcs (IssueArcID TEXT, Status TEXT)')
    d.action('CREATE TABLE nzblog (IssueID TEXT, NZBName TEXT, SARC TEXT, PROVIDER TEXT, ID TEXT, AltNZBName TEXT, OneOff TEXT)')
    d.action('CREATE TABLE snatched (IssueID TEXT, ComicName TEXT, Issue_Number TEXT, Size INTEGER, DateAdded TEXT, Status TEXT, '
             'FolderName TEXT, ComicID TEXT, Provider TEXT, Hash TEXT, crc TEXT)')
    return d


@pytest.fixture
def sab_holds(monkeypatch):
    from mylar import downloadqueue
    held = {'value': None}
    monkeypatch.setattr(downloadqueue, 'client_has', lambda client, ids: held['value'])
    return held


def job(d, issueid, jobid, at, client='sabnzbd', arc=None):
    d.action('INSERT INTO client_jobs VALUES (?, ?, ?, ?, ?, ?, ?)', [issueid, arc, '100', client, jobid, 'name', at])


@pytest.mark.unit
def test_restart_picks_up_snatched_sab_grabs(myDB, sab_holds):
    myDB.action("INSERT INTO issues VALUES ('527', 'Snatched'), ('530', 'Downloaded')")
    myDB.action("INSERT INTO nzblog (IssueID, PROVIDER, ID) VALUES ('527', 'DrunkenSlug', 'abc')")
    job(myDB, '527', 'SABnzbd_nzo_a', '2026-11-01 23:56:00')
    job(myDB, '530', 'SABnzbd_nzo_b', '2026-11-01 23:57:00')
    items = nzb.pending_jobs(myDB)
    assert [i['nzo_id'] for i in items] == ['SABnzbd_nzo_a']
    assert items[0]['issueid'] == '527' and items[0]['comicid'] == '100'
    assert items[0]['download_info'] == {'provider': 'DrunkenSlug', 'id': 'abc'}
    assert items[0]['queue']['mode'] == 'queue'


@pytest.mark.unit
def test_restart_uses_the_latest_grab_of_an_issue(myDB, sab_holds):
    myDB.action("INSERT INTO issues VALUES ('527', 'Snatched')")
    job(myDB, '527', 'SABnzbd_nzo_old', '2026-11-01 10:00:00')
    job(myDB, '527', 'SABnzbd_nzo_new', '2026-11-01 23:00:00')
    assert [i['nzo_id'] for i in nzb.pending_jobs(myDB)] == ['SABnzbd_nzo_new']


@pytest.mark.unit
def test_restart_skips_jobs_sab_no_longer_has(myDB, sab_holds):
    myDB.action("INSERT INTO issues VALUES ('527', 'Snatched'), ('531', 'Snatched')")
    job(myDB, '527', 'SABnzbd_nzo_A', '2026-11-01 23:56:00')
    job(myDB, '531', 'SABnzbd_nzo_B', '2026-11-01 23:58:00')
    sab_holds['value'] = {'sabnzbd_nzo_a'}
    assert [i['nzo_id'] for i in nzb.pending_jobs(myDB)] == ['SABnzbd_nzo_A']


@pytest.mark.unit
def test_restart_picks_up_annuals_and_story_arcs(myDB, sab_holds):
    myDB.action("INSERT INTO annuals (IssueID, Status) VALUES ('900', 'Snatched')")
    myDB.action("INSERT INTO storyarcs VALUES ('77', 'Snatched')")
    job(myDB, '900', 'SABnzbd_nzo_ann', '2026-11-01 23:00:00')
    job(myDB, None, 'SABnzbd_nzo_arc', '2026-11-01 23:01:00', arc='77')
    assert sorted(i['issueid'] for i in nzb.pending_jobs(myDB)) == ['900', 'S77']


@pytest.mark.unit
def test_restart_ignores_other_clients(myDB, sab_holds):
    myDB.action("INSERT INTO issues VALUES ('527', 'Snatched')")
    job(myDB, '527', 'abcdef', '2026-11-01 23:56:00', client='qbittorrent')
    assert nzb.pending_jobs(myDB) == []


@pytest.mark.unit
def test_nzbget_grabs_get_their_numeric_id(myDB, sab_holds, cfg, monkeypatch):
    monkeypatch.setattr(mylar, 'USE_SABNZBD', False, raising=False)
    monkeypatch.setattr(mylar, 'USE_NZBGET', True, raising=False)
    cfg.NZBGET_CLIENT_POST_PROCESSING = True
    myDB.action("INSERT INTO issues VALUES ('527', 'Snatched')")
    job(myDB, '527', '42', '2026-11-01 23:56:00', client='nzbget')
    assert [i['NZBID'] for i in nzb.pending_jobs(myDB)] == [42]


@pytest.mark.unit
def test_requeue_does_not_add_a_job_twice(myDB, sab_holds, monkeypatch):
    myDB.action("INSERT INTO issues VALUES ('527', 'Snatched')")
    job(myDB, '527', 'SABnzbd_nzo_a', '2026-11-01 23:56:00')
    monkeypatch.setattr(nzb.db, 'DBConnection', lambda: myDB)
    q = queue.Queue()
    assert nzb.requeue_pending(q) == 1
    assert nzb.requeue_pending(q) == 0
    assert q.qsize() == 1


class Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def sab_item(nzo):
    return {'status': True, 'nzo_id': nzo, 'issueid': '527', 'comicid': '100', 'apicall': True, 'download_info': None,
            'queue': {'mode': 'queue', 'search': nzo, 'output': 'json', 'apikey': 'k'}}


@pytest.mark.unit
def test_sab_job_still_downloading_is_handed_back(cfg, monkeypatch):
    calls = []

    def fake_get(url, params=None, verify=None):
        calls.append(dict(params))
        return Resp({'queue': {'status': 'Downloading', 'slots': [{'nzo_id': 'n1', 'status': 'Downloading', 'mbleft': '30', 'filename': 'x'}]}})
    monkeypatch.setattr(sabnzbd.requests, 'get', fake_get)
    item = sab_item('n1')
    assert sabnzbd.SABnzbd(item).processor()['status'] == 'downloading'
    # a second look at the same item works too (the first look used to change it)
    assert sabnzbd.SABnzbd(item).processor()['status'] == 'downloading'
    assert all(c['nzo_ids'] == 'n1' and c['mode'] == 'queue' for c in calls)


@pytest.mark.unit
def test_sab_job_not_in_queue_goes_to_history_even_while_others_download(cfg, monkeypatch):
    # SABnzbd reports the whole queue as Downloading for other jobs; that must not hold this one
    monkeypatch.setattr(sabnzbd.requests, 'get',
                        lambda url, params=None, verify=None: Resp({'queue': {'status': 'Downloading', 'mbleft': '500', 'slots': []}}))
    seen = []
    monkeypatch.setattr(sabnzbd.SABnzbd, 'historycheck', lambda self, info: seen.append(info['nzo_id']) or {'status': True})
    assert sabnzbd.SABnzbd(sab_item('n2')).processor() == {'status': True}
    assert seen == ['n2']


@pytest.mark.unit
def test_downloading_item_goes_to_the_back_of_the_queue(cfg, monkeypatch):
    q = queue.Queue()
    monkeypatch.setattr(mylar, 'NZB_QUEUE', q, raising=False)
    item = sab_item('n1')
    nzb.cdh_monitor(q, item, {'status': 'downloading', 'failed': False})
    assert q.get_nowait() is item and item['checked'] is True


@pytest.mark.unit
def test_nzbget_job_still_downloading_is_handed_back(cfg, monkeypatch):
    nz = nzbget.NZBGet.__new__(nzbget.NZBGet)
    nz.server = types.SimpleNamespace(listgroups=lambda: [{'NZBID': 42, 'PostInfoText': '', 'ScriptStatuses': [], 'Parameters': [],
                                                           'NZBName': 'x', 'Status': 'DOWNLOADING', 'RemainingSizeMB': 10}])
    assert nz.processor({'NZBID': 42})['status'] == 'downloading'


@pytest.mark.unit
def test_nzbget_job_out_of_queue_goes_to_history(cfg, monkeypatch):
    nz = nzbget.NZBGet.__new__(nzbget.NZBGet)
    nz.server = types.SimpleNamespace(listgroups=lambda: [])
    monkeypatch.setattr(nzbget.NZBGet, 'historycheck', lambda self, info: {'status': True, 'id': info['NZBID']})
    assert nz.processor({'NZBID': 42}) == {'status': True, 'id': 42}
