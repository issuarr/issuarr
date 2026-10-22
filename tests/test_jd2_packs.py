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


@pytest.mark.unit
def test_the_folder_is_the_one_jd2_saved_to():
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
    assert client.folder(JOB, '6078') == 'Daredevil Vol. 1 001 – 380 + Annuals (1964-1998)'
    assert calls == ['http://jd2/downloadsV2/queryPackages']


class FakeJD2:
    def __init__(self, status, folder):
        self._status, self._folder = status, folder
        self.removed = []

    def status(self, job_id, record_id=None):
        return self._status

    def folder(self, job_id, record_id=None):
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
                     'Daredevil Vol. 1 001 – 380 + Annuals (1964-1998)')
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
