"""JD2 downloads marked with the comment 'issuarr'.

2026-10-25: Issuarr puts the comment 'issuarr' on everything it sends JD2, and files downloads the
user added to JD2 with the same comment. Its own packages carry the comment too, so they must be
left to the monitor and never filed twice.
"""
import json
import queue
import types

import pytest

import mylar
from mylar.downloaders import jdownloader2
from mylar.downloaders.jdownloader2 import JDownloader2
from mylar.queues import jd2


class Resp(object):
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {'data': self.data}


class Session(object):
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return Resp(self.answers.get(url.rsplit('/', 2)[-2] + '/' + url.rsplit('/', 1)[-1], {}))


def _config(monkeypatch, **kw):
    kw.setdefault('JD2_URL', 'http://jd2:3128')
    kw.setdefault('JD2_DEST_DIR', None)
    kw.setdefault('POST_PROCESSING', True)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(**kw), raising=False)


class DB(object):
    def __init__(self, rows):
        self.rows = rows

    def select(self, sql, args=None):
        return self.rows


class Client(object):
    def __init__(self, packages):
        self.packages = packages
        self.removed = []

    def tagged_packages(self):
        return self.packages

    def remove_packages(self, uuids):
        self.removed.extend(uuids)


@pytest.fixture
def pp(monkeypatch):
    q = queue.Queue()
    monkeypatch.setattr(mylar, 'PP_QUEUE', q, raising=False)
    monkeypatch.setattr(jd2, 'SENT', set())
    monkeypatch.setattr(jd2, 'PICKED', set())
    monkeypatch.setattr(jd2, 'WARNED', set())
    return q


def drain(q):
    out = []
    while not q.empty():
        out.append(q.get())
    return out


@pytest.mark.unit
def test_issuarrs_own_links_carry_the_comment(monkeypatch):
    _config(monkeypatch)
    session = Session({'linkgrabberv2/addLinks': {'id': 111}})
    monkeypatch.setattr(jdownloader2.time, 'sleep', lambda s: None)
    JDownloader2(session=session).submit({'https://mega.nz/file/x': 'HIGHEST'}, 'Batman (2016) - 77')
    query = json.loads(session.calls[0][1]['query'])
    assert query['comment'] == 'issuarr'


@pytest.mark.unit
def test_tagged_packages_by_package_or_link_comment(monkeypatch):
    _config(monkeypatch)
    session = Session({
        'downloadsV2/queryPackages': [{'uuid': 1, 'name': 'Mine', 'comment': 'Issuarr ', 'saveTo': '/d/Mine'},
                                      {'uuid': 2, 'name': 'Link tagged', 'saveTo': '/d/Link'},
                                      {'uuid': 3, 'name': 'Not for Issuarr', 'comment': 'movies', 'saveTo': '/d/Other'}],
        'downloadsV2/queryLinks': [{'packageUUID': 1, 'name': 'a.cbz'},
                                   {'packageUUID': 2, 'name': 'b.cbz', 'comment': 'issuarr'},
                                   {'packageUUID': 3, 'name': 'film.mkv'}],
    })
    found = JDownloader2(session=session).tagged_packages()
    assert [p['uuid'] for p in found] == [1, 2]
    assert found[0]['links'] == [{'packageUUID': 1, 'name': 'a.cbz'}]


@pytest.mark.unit
def test_a_package_is_finished_only_when_every_link_is():
    assert jd2.package_finished({'links': [{'finished': True}, {'status': 'File not found'}]})
    assert not jd2.package_finished({'links': [{'finished': True}, {'status': 'Downloading'}]})
    assert not jd2.package_finished({'links': [{'status': 'File not found'}]})
    assert not jd2.package_finished({'links': [{'finished': True, 'status': 'Extracting'}]})
    assert jd2.package_finished({'links': [{'finished': True, 'status': 'Extraction OK'}, {'enabled': False}]})
    assert not jd2.package_finished({'links': []})


@pytest.mark.unit
def test_a_finished_user_download_is_filed_and_taken_off_jd2(monkeypatch, tmp_path, pp):
    root = tmp_path / 'complete'
    (root / 'Batman 001').mkdir(parents=True)
    (root / 'Batman 001' / 'Batman 001 (2016).cbz').write_bytes(b'x')
    _config(monkeypatch, JD2_DEST_DIR='/output/complete', JD2_LOCAL_DIR=str(root))
    client = Client([{'uuid': 9, 'name': 'Batman 001', 'saveTo': '/output/complete/Batman 001',
                      'links': [{'name': 'Batman 001 (2016).cbz', 'finished': True, 'jobUUID': 5}]}])
    jd2.pickup_user_downloads(client, DB([]))
    jobs = drain(pp)
    assert [(j['nzb_name'], j['nzb_folder'], j['issueid']) for j in jobs] == [('Manual Run', str(root / 'Batman 001'), None)]
    assert client.removed == [9]
    jd2.pickup_user_downloads(client, DB([]))  # still listed, say removing it failed: not filed twice
    assert drain(pp) == []


@pytest.mark.unit
def test_issuarrs_own_packages_are_left_to_the_monitor(monkeypatch, tmp_path, pp):
    root = tmp_path / 'complete'
    (root / 'X').mkdir(parents=True)
    (root / 'X' / 'a.cbz').write_bytes(b'x')
    _config(monkeypatch, JD2_DEST_DIR=str(root))
    done = [{'name': 'a.cbz', 'finished': True}]
    by_job = {'uuid': 1, 'name': 'Renamed by JD2', 'saveTo': str(root / 'X'), 'links': [dict(done[0], jobUUID=555)]}
    by_name = {'uuid': 2, 'name': 'Batman (2016) - 77', 'saveTo': str(root / 'X'), 'links': [dict(done[0], jobUUID=1)]}
    by_sent = {'uuid': 3, 'name': 'Sent this run', 'saveTo': str(root / 'X'), 'links': [dict(done[0], jobUUID=999)]}
    jd2.SENT.add('999')
    client = Client([by_job, by_name, by_sent])
    jd2.pickup_user_downloads(client, DB([{'ID': '77', 'jd2_job_id': '444,555'}]))
    assert drain(pp) == [] and client.removed == []


@pytest.mark.unit
def test_unfinished_user_downloads_wait(monkeypatch, tmp_path, pp):
    _config(monkeypatch, JD2_DEST_DIR=str(tmp_path))
    client = Client([{'uuid': 1, 'name': 'A', 'saveTo': str(tmp_path), 'links': [{'name': 'a.cbz', 'status': 'Downloading'}]}])
    jd2.pickup_user_downloads(client, DB([]))
    assert drain(pp) == [] and client.removed == []


@pytest.mark.unit
def test_a_download_in_a_shared_folder_is_moved_to_its_own_first(monkeypatch, tmp_path, pp):
    # JD2's download folder also holds things the user handles by hand: filing must never touch them
    root = tmp_path / 'complete'
    root.mkdir()
    (root / 'Hulk 001.cbr').write_bytes(b'x')
    (root / 'DC Master Reading Order').mkdir()
    _config(monkeypatch, JD2_DEST_DIR=str(root))
    client = Client([{'uuid': 4, 'name': 'Hulk: 001', 'saveTo': str(root), 'links': [{'name': 'Hulk 001.cbr', 'finished': True}]}])
    jd2.pickup_user_downloads(client, DB([]))
    own = root / 'Issuarr - Hulk_ 001'
    assert [j['nzb_folder'] for j in drain(pp)] == [str(own)]
    assert (own / 'Hulk 001.cbr').is_file() and (root / 'DC Master Reading Order').is_dir()
    assert sorted(p.name for p in root.iterdir()) == ['DC Master Reading Order', 'Issuarr - Hulk_ 001']


@pytest.mark.unit
def test_files_issuarr_cant_see_are_not_taken_off_jd2(monkeypatch, tmp_path, pp):
    _config(monkeypatch, JD2_DEST_DIR='/output/complete', JD2_LOCAL_DIR=str(tmp_path))
    client = Client([{'uuid': 1, 'name': 'A', 'saveTo': '/output/complete/A', 'links': [{'name': 'a.cbz', 'finished': True}]}])
    jd2.pickup_user_downloads(client, DB([]))
    assert drain(pp) == [] and client.removed == []


@pytest.mark.unit
def test_nothing_is_picked_up_with_post_processing_off(monkeypatch, tmp_path, pp):
    _config(monkeypatch, JD2_DEST_DIR=str(tmp_path), POST_PROCESSING=False)
    (tmp_path / 'A').mkdir()
    (tmp_path / 'A' / 'a.cbz').write_bytes(b'x')
    client = Client([{'uuid': 1, 'name': 'A', 'saveTo': str(tmp_path / 'A'), 'links': [{'name': 'a.cbz', 'finished': True}]}])
    jd2.pickup_user_downloads(client, DB([]))
    assert drain(pp) == [] and client.removed == []
