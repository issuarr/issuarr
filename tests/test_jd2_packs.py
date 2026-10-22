"""JD2 and multi-file packs.

2026-10-20: 'Daredevil Vol. 1 #1 - 380 + Annuals' (12.8 GB) went to JD2 with five hosts. JD2
downloaded the zip from one host and the single issues from another at the same time. When the
first single issue finished, Issuarr called the whole job done, removed it from JD2 and filed
that one file from a folder name JD2 never used. 336 issues stayed Wanted.
"""
import queue
import sqlite3
import types

import pytest

import mylar
from mylar import db, ddlsources, getcomics
from mylar.downloaders.jdownloader2 import JDownloader2
from mylar.queues import jd2

JOB = '1792476665396'


def client_with(links):
    client = JDownloader2.__new__(JDownloader2)
    client._job_links = lambda job_id, record_id=None: {'downloadsV2': (links, ['p1']), 'linkgrabberv2': ([], [])}
    return client


@pytest.mark.unit
def test_a_pack_is_not_done_when_its_first_file_is():
    links = [{'host': 'mega.nz', 'name': 'Daredevil -1 (1997).cbz', 'finished': True, 'bytesLoaded': 59329998},
             {'host': 'mega.nz', 'name': 'Daredevil 001 (1964).cbr', 'finished': True, 'bytesLoaded': 46800087},
             {'host': 'mega.nz', 'name': 'Daredevil 002 (1964).cbr', 'status': 'Downloading', 'bytesLoaded': 1696256},
             {'host': 'mediafire.com', 'name': 'Daredevil Vol. 1.zip', 'status': 'Downloading', 'bytesLoaded': 500}]
    result = client_with(links).status(JOB, '6078')
    assert result['status'] != 'Finished' and result['loaded'] == 59329998 + 46800087 + 1696256 + 500


@pytest.mark.unit
def test_a_pack_is_done_when_one_host_has_every_file():
    links = [{'host': 'mega.nz', 'finished': True, 'name': 'a.cbr'},
             {'host': 'mega.nz', 'finished': True, 'name': 'b.cbr'},
             {'host': 'mega.nz', 'status': 'File not found', 'name': 'c.cbr'},  # one dead file doesn't hold up the rest
             {'host': 'mediafire.com', 'status': 'Downloading', 'name': 'all.zip'}]
    result = client_with(links).status(JOB, '6078')
    assert result['status'] == 'Finished' and result['files'] == 2


@pytest.mark.unit
def test_a_pack_still_being_added_to_jd2_is_not_done():
    client = JDownloader2.__new__(JDownloader2)
    client._job_links = lambda job_id, record_id=None: {
        'downloadsV2': ([{'host': 'mega.nz', 'finished': True, 'name': 'a.cbr'}], ['p1']),
        'linkgrabberv2': ([{'host': 'mega.nz', 'availability': 'ONLINE', 'name': 'b.cbr'},
                           {'host': 'mediafire.com', 'availability': 'OFFLINE', 'name': 'all.zip'}], ['g1'])}
    assert client.status(JOB, '6078')['status'] != 'Finished'


@pytest.mark.unit
def test_a_single_issue_is_done_when_any_mirror_finishes():
    links = [{'host': 'mega.nz', 'finished': True, 'name': 'Batman 001.cbr'},
             {'host': 'pixeldrain.com', 'status': 'Waiting', 'name': 'Batman 001.cbr'}]
    assert client_with(links).status(JOB, '1')['status'] == 'Finished'


def packages_client(save_to, calls=None, links=()):
    client = client_with(list(links))

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {'data': [{'uuid': 'p1', 'name': 'Daredevil Vol. 1 001 – 380 + Annuals (1964-1998)', 'saveTo': save_to}]}

    client.session = types.SimpleNamespace(get=lambda url, params=None, timeout=None: (calls if calls is not None else []).append(url) or Resp())
    client.base_url, client.timeout = 'http://jd2', 5
    return client


@pytest.mark.unit
def test_the_folder_is_the_one_jd2_saved_to(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(JD2_DEST_DIR='/output', JD2_LOCAL_DIR='/downloads'), raising=False)
    client = client_with([])
    calls = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {'data': [{'uuid': 'p1', 'name': 'Daredevil Vol. 1 001 – 380 + Annuals (1964-1998)',
                              'saveTo': '/output/Daredevil Vol. 1 001 – 380 + Annuals (1964-1998)'}]}

    client.session = types.SimpleNamespace(get=lambda url, params=None, timeout=None: calls.append(url) or Resp())
    client.base_url, client.timeout = 'http://jd2', 5
    assert client.folder(JOB, '6078') == '/downloads/Daredevil Vol. 1 001 – 380 + Annuals (1964-1998)'
    assert calls == ['http://jd2/downloadsV2/queryPackages']


@pytest.mark.unit
def test_a_dated_subfolder_jd2_saved_to_is_kept(monkeypatch):
    # 2026-10-22: JD2 saved Weird War Tales #1 - 62 in complete/2026-06/07. Issuarr kept only '07' and
    # post-processed /downloads/complete/07, which doesn't exist, so the pack was never filed.
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(JD2_DEST_DIR='/output/complete', JD2_LOCAL_DIR='/downloads/complete'), raising=False)
    assert packages_client('/output/complete/2026-06/07').folder(JOB, '19434') == '/downloads/complete/2026-06/07'


@pytest.mark.unit
def test_every_mirror_sent_to_jd2_is_part_of_the_job(monkeypatch):
    # 2026-10-21: Detective Comics #1112. Each mirror is its own JD2 job; only the first (a datanodes link
    # stuck on a captcha) was watched. JD2 finished another mirror in a minute, Issuarr never saw it,
    # gave up after 6 hours and downloaded the issue again.
    client = JDownloader2.__new__(JDownloader2)
    client.base_url, client.timeout, client.destination_folder = 'http://jd2', 5, None
    replies = iter([{'data': {'id': 111}}, {'data': {'id': 222}}, {'data': {'id': 333}}])

    class Resp:
        def __init__(self):
            self.body = next(replies)

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    client.session = types.SimpleNamespace(get=lambda url, params=None, timeout=None: Resp())
    monkeypatch.setattr(mylar.downloaders.jdownloader2, 'time', types.SimpleNamespace(sleep=lambda s: None))
    result = client.submit({'https://datanodes.to/a': 'HIGHEST', 'https://pixeldrain.com/u/b': 'HIGH', 'https://mega.nz/c': 'DEFAULT'},
                           'Detective Comics #1112 (2026) - 404406')
    assert result['jobid'] == '111,222,333'

    asked = []
    client._links = lambda endpoint, query: asked.append(query) or []
    client._packages = lambda area, record_id: []
    client._job_links(result['jobid'], '404406')
    assert asked[0] == {'jobUUIDs': ['111', '222', '333']}


@pytest.mark.unit
def test_removing_a_job_deletes_jd2_folders_that_stayed_empty(monkeypatch, tmp_path):
    local = tmp_path / 'complete'
    empty, full = local / 'Detective Comics #1112 (2026) - 404406', local / '2026-08' / '26'
    empty.mkdir(parents=True)
    full.mkdir(parents=True)
    (full / 'Detective Comics 1112 (2026).cbz').write_bytes(b'x')
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(JD2_DEST_DIR='/output/complete', JD2_LOCAL_DIR=str(local)), raising=False)
    client = JDownloader2.__new__(JDownloader2)
    client.base_url, client.timeout = 'http://jd2', 5
    client._job_links = lambda job_id, record_id=None: {'downloadsV2': ([], ['p1', 'p2']), 'linkgrabberv2': ([], [])}
    client._save_to = lambda packages: {'p1': '/output/complete/Detective Comics #1112 (2026) - 404406', 'p2': '/output/complete/2026-08/26'}
    client.session = types.SimpleNamespace(get=lambda url, params=None, timeout=None: None)
    client.remove('111,222', '404406')
    assert not empty.exists() and full.exists() and local.exists()


class FakeJD2:
    def __init__(self, status, folder):
        self._status, self._folder = status, folder
        self.removed = []

    def status(self, job_id, record_id=None):
        return self._status

    def folder(self, job_id, record_id=None, package=None):
        return self._folder

    def remove(self, job_id, record_id=None):
        self.removed.append(job_id)


def make_db(pack):
    conn = db.DBConnection.__new__(db.DBConnection)
    conn.connection = sqlite3.connect(':memory:')
    conn.connection.row_factory = sqlite3.Row
    conn.connection.execute('CREATE TABLE ddl_info (id TEXT, series TEXT, status TEXT, jd2_job_id TEXT, '
                            'updated_date TEXT, issueid TEXT, comicid TEXT, pack INTEGER)')
    conn.connection.execute("INSERT INTO ddl_info (id, series, status, jd2_job_id, pack) VALUES ('6078', 'Daredevil', 'Queued', ?, ?)",
                            [JOB, pack])
    return conn


@pytest.mark.unit
@pytest.mark.parametrize('pack', [1, 0])
def test_a_finished_job_is_filed_from_the_folder_jd2_used(monkeypatch, tmp_path, pack):
    pp = queue.Queue()
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(POST_PROCESSING=True, JD2_DEST_DIR='/downloads/mylar-dl',
                                                               ENABLE_DDL=True, CACHE_DIR=str(tmp_path)), raising=False)
    monkeypatch.setattr(mylar, 'PP_QUEUE', pp, raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(jd2, 'HOLDING', [None])
    monkeypatch.setattr(jd2, 'PROGRESS', {})
    monkeypatch.setattr(jd2, 'time', types.SimpleNamespace(sleep=lambda s: None, monotonic=lambda: 0.0))
    client = FakeJD2({'found': True, 'status': 'Finished', 'data': {'name': 'Daredevil 001 (1964).cbr'}, 'files': 382},
                     '/downloads/mylar-dl/Daredevil Vol. 1 001 – 380 + Annuals (1964-1998)')
    monkeypatch.setattr(jd2, 'JDownloader2', lambda: client)
    conn = make_db(pack)
    monkeypatch.setattr(jd2.db, 'DBConnection', lambda: conn)
    q = queue.Queue()
    q.put({'id': '6078', 'series': 'Daredevil Vol. 1 #1 – 380', 'year': '1964-1998', 'jd2_job_id': JOB,
           'filename': 'Daredevil Vol. 1 #1 – 380 (1964-1998)', 'comicid': '2190', 'issueid': '11324',
           'mainlink': 'https://getcomics.org/marvel/daredevil-vol-1/'})
    q.put('exit')
    jd2.jd2_queue_monitor(q)
    sent = pp.get_nowait()
    assert sent['nzb_folder'] == '/downloads/mylar-dl/Daredevil Vol. 1 001 – 380 + Annuals (1964-1998)'
    if pack:
        # the whole folder is filed against the series, like a direct download of a pack
        assert sent['nzb_name'] == 'Daredevil Vol. 1 001 – 380 + Annuals (1964-1998)'
        assert sent['issueid'] is None and sent['pack'] is True
    else:
        assert sent['nzb_name'] == 'Daredevil 001 (1964).cbr' and sent['issueid'] == '11324'


@pytest.mark.unit
@pytest.mark.parametrize('pack,hosts', [(True, 1), (False, 3)])
def test_jd2_gets_one_host_for_a_pack_and_every_mirror_for_an_issue(monkeypatch, pack, hosts):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(
        DDL_PRIORITY_ORDER='["main","pixeldrain","mega","mediafire"]', DDL_DISABLED_SOURCES='[]',
        DDL_MAIN_LARGE_LAST=True, DDL_MAIN_LARGE_MB=400), raising=False)
    monkeypatch.setattr(ddlsources, 'pixeldrain_fits', lambda b: False)
    monkeypatch.setattr(mylar, 'DDL_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'JD2_QUEUE', queue.Queue(), raising=False)
    gc = getcomics.GC.__new__(getcomics.GC)
    gc.jd2 = object()
    gc.issueid, gc.comicid, gc.oneoff = '11324', '2190', False
    links = [{'series': 'Daredevil Vol. 1', 'site': site, 'year': '1964', 'size': '12.8 GB', 'issues': None,
              'links': 'https://getcomics.org/dls/%s' % site.lower(), 'pack': pack}
             for site in ('Mediafire', 'Mega', 'Pixeldrain')]
    fake_db = types.SimpleNamespace(upsert=lambda *a: None)
    gc._queue_links([links[1]], links, [], '6078', 'https://getcomics.org/marvel/daredevil-vol-1/', None, None, [], fake_db)
    sent = mylar.JD2_QUEUE.get_nowait()['jd2_priority_links']
    assert len(sent) == hosts
    if pack:
        assert list(sent) == ['https://getcomics.org/dls/mega']  # mega ranks first when pixeldrain can't take it


@pytest.mark.unit
def test_a_dead_mirror_is_not_the_job_while_another_is_downloading():
    # 2026-10-21: Catwoman #92. The first link was JD2's crawler blocked by Cloudflare; Pixeldrain had
    # already loaded the whole file. Issuarr gave up on JD2, downloaded the issue again itself, and
    # JD2's copy was left in the download folder.
    links = [{'host': 'linkcrawlerretry', 'name': 'Blocked by!Cloudflare Site-Protection', 'status': 'File not found', 'bytesLoaded': 0},
             {'host': 'pixeldrain.com', 'name': 'Catwoman 092 (2026).cbz', 'status': 'Downloading', 'bytesLoaded': 47424828}]
    result = client_with(links).status(JOB, '408847')
    assert not jd2.jd2_status_is_dead(result['status'])
    assert result['data']['host'] == 'pixeldrain.com' and result['loaded'] == 47424828


@pytest.mark.unit
def test_a_dead_link_waits_for_a_mirror_still_in_the_link_grabber():
    client = JDownloader2.__new__(JDownloader2)
    client._job_links = lambda job_id, record_id=None: {
        'downloadsV2': ([{'host': 'mega.nz', 'status': 'File not found', 'name': 'a.cbr'}], ['p1']),
        'linkgrabberv2': ([{'host': 'pixeldrain.com', 'availability': 'ONLINE', 'name': 'a.cbr'}], ['g1'])}
    assert not jd2.jd2_status_is_dead(client.status(JOB, '1')['status'])


@pytest.mark.unit
def test_every_mirror_dead_is_still_a_failure():
    links = [{'host': 'mega.nz', 'status': 'File not found', 'name': 'a.cbr'},
             {'host': 'pixeldrain.com', 'status': 'Offline', 'name': 'a.cbr'}]
    assert client_with(links).status(JOB, '1')['status'] == 'Failed'


@pytest.mark.unit
def test_a_single_issue_is_filed_by_its_own_file_in_a_shared_folder(monkeypatch, tmp_path):
    # a dated folder JD2 uses can hold other downloads too, so only the file that finished is handed over
    dated = tmp_path / '2026-08' / '26'
    dated.mkdir(parents=True)
    (dated / 'Detective Comics 1112 (2026).cbz').write_bytes(b'x')
    (dated / 'Something Else 001 (2026).cbz').write_bytes(b'x')
    pp = queue.Queue()
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(POST_PROCESSING=True, JD2_DEST_DIR=str(tmp_path),
                                                               ENABLE_DDL=True, CACHE_DIR=str(tmp_path)), raising=False)
    monkeypatch.setattr(mylar, 'PP_QUEUE', pp, raising=False)
    monkeypatch.setattr(mylar, 'DDL_CANCEL', set(), raising=False)
    monkeypatch.setattr(jd2, 'HOLDING', [None])
    monkeypatch.setattr(jd2, 'PROGRESS', {})
    monkeypatch.setattr(jd2, 'time', types.SimpleNamespace(sleep=lambda s: None, monotonic=lambda: 0.0))
    client = FakeJD2({'found': True, 'status': 'Finished', 'data': {'name': 'Detective Comics 1112 (2026).cbz'}, 'files': 1}, str(dated))
    monkeypatch.setattr(jd2, 'JDownloader2', lambda: client)
    conn = make_db(0)
    monkeypatch.setattr(jd2.db, 'DBConnection', lambda: conn)
    q = queue.Queue()
    q.put({'id': '6078', 'series': 'Detective Comics #1112', 'year': '2026', 'jd2_job_id': JOB,
           'comicid': '1', 'issueid': '1189483', 'mainlink': 'https://getcomics.org/dc/detective-comics-1112-2026/'})
    q.put('exit')
    jd2.jd2_queue_monitor(q)
    sent = pp.get_nowait()
    assert sent['nzb_folder'] == str(dated / 'Detective Comics 1112 (2026).cbz') and sent['issueid'] == '1189483'
