import types

import pytest

import mylar
from mylar.downloaders import airdcpp, airdcpp_pack

MB = 1024 * 1024


def item(name, size=20 * MB, tth=None, kind='file'):
    return {'name': name, 'size': size, 'tth': ('T' + name) if tth is None else tth, 'type': {'id': kind}}


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)


@pytest.mark.unit
@pytest.mark.parametrize('name, expected', [
    ('Batman 012 (2016) (Digital) (Zone-Empire).cbz', ('batman', '12', 2016)),
    ('Batman v3 012 (2016).cbr', ('batman', '12', 2016)),
    ('Mr. Miracle #005.cbz', ('mr miracle', '5', None)),
    ('Batman 012.5 (2016).cbz', ('batman', '12.5', 2016)),
    ('Batman Annual 001 (2017).cbz', ('batman annual', '1', 2017)),
    ('Batman 001 (2016) (TPB).cbz', None),
    ('Batman Vol. 1 - I Am Gotham (2017).cbz', None),
    ('Batman 012 (2016).pdf', None),
])
def test_parse_name(name, expected):
    assert airdcpp_pack.parse_name(name) == expected


@pytest.mark.unit
def test_pick_files_takes_one_copy_per_wanted_issue():
    wanted = {'2': {'issueid': 'i2', 'year': 2016}, '3': {'issueid': 'i3', 'year': 2016},
              '9': {'issueid': 'i9', 'year': 2017}}
    items = [
        item('Batman 001 (2016).cbz'),                       # not wanted
        item('Batman 002 (2016) (small).cbz', 15 * MB),
        item('Batman 002 (2016) (big).cbz', 40 * MB),        # bigger copy wins
        item('Batman 003 (2016).cbz', 500),                  # under 1 MB: a fake
        item('Batman 009 (1940).cbz'),                       # before the series began
        item('Batman Annual 002 (2016).cbz'),                # another series
        item('Batman 009 (2017).cbz', tth=''),               # no TTH, can't queue
        item('Extras', kind='directory'),
    ]
    picked = airdcpp_pack.pick_files(items, ['Batman'], wanted, series_year=2016)
    assert [(p['name'], p['issueid']) for p in picked] == [('Batman 002 (2016) (big).cbz', 'i2')]


@pytest.mark.unit
def test_pick_files_rejects_a_later_run():
    wanted = {'1': {'issueid': 'i1', 'year': 2011}}
    later = [item('Batman 001 (2016).cbz')]
    assert airdcpp_pack.pick_files(later, ['Batman'], wanted, series_year=2011) == []
    close = [item('Batman 001 (2012).cbz')]
    assert [p['issueid'] for p in airdcpp_pack.pick_files(close, ['Batman'], wanted, series_year=2011)] == ['i1']


@pytest.mark.unit
def test_peer_and_folder_from_a_search_result():
    result = {'path': '/Comics/DC/Batman (2016)/Batman 001 (2016).cbz',
              'users': {'count': 1, 'user': {'cid': 'CID', 'hub_url': 'adc://hub:1511', 'nicks': 'alice'}}}
    assert airdcpp.peer_of(result) == {'cid': 'CID', 'hub_url': 'adc://hub:1511', 'nicks': 'alice'}
    assert airdcpp.folder_of(result['path']) == '/Comics/DC/Batman (2016)/'
    assert airdcpp.peer_of({'users': {'count': 0}}) is None
    assert airdcpp.folder_of('') is None


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.text = 'x' if data is not None else ''

    def json(self):
        return self._data


class FakeAirDC:
    """Answers the filelist and queue calls a folder pack makes."""
    def __init__(self, items, download_dir, complete=True):
        self.items = items
        self.download_dir = download_dir
        self.complete = complete
        self.calls = []
        self.auth = None
        self.queued = {}

    def post(self, url, json=None, headers=None, timeout=None):
        path = url.split('/api/v1', 1)[1]
        self.calls.append(('POST', path, json))
        if path == '/filelists':
            return FakeResponse({'id': 'FL'})
        if path == '/queue/bundles/file':
            bid = len(self.queued) + 1
            self.queued[bid] = json
            return FakeResponse({'bundle_info': {'id': bid}})
        raise AssertionError(path)

    def get(self, url, headers=None, timeout=None):
        path = url.split('/api/v1', 1)[1]
        self.calls.append(('GET', path, None))
        if path == '/filelists/FL':
            return FakeResponse({'state': {'id': 'loaded'}})
        if path.startswith('/filelists/FL/items/'):
            start = int(path.split('/')[-2])
            return FakeResponse({'items': self.items[start:start + 500]})
        if path.startswith('/queue/bundles/'):
            bid = int(path.rsplit('/', 1)[1])
            if not self.complete:
                return FakeResponse({'status': {'failed': True}})
            q = self.queued[bid]
            with open(q['target_directory'] + q['target_name'], 'wb') as f:
                f.write(b'x')
            return FakeResponse({'status': {'completed': True}, 'target': q['target_directory'] + q['target_name']})
        raise AssertionError(path)

    def delete(self, url, headers=None, timeout=None):
        self.calls.append(('DELETE', url.split('/api/v1', 1)[1], None))
        return FakeResponse(None, 204)


class FakeDB:
    issues = []
    comic = None

    def __init__(self):
        pass

    def select(self, query, args):
        return [i for i in FakeDB.issues if i['ComicID'] == args[0] and i['Status'] == 'Wanted']

    def selectone(self, query, args):
        return types.SimpleNamespace(fetchone=lambda: FakeDB.comic)

    def action(self, query, args):
        for i in FakeDB.issues:
            if i['IssueID'] == args[0] and i['Status'] == 'Snatched':
                i['Status'] = 'Wanted'


def setup_pack(monkeypatch, tmp_path, fake):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(
        AIRDCPP_HOST='http://airdcpp:5600', AIRDCPP_USERNAME='', AIRDCPP_PASSWORD='',
        AIRDCPP_DOWNLOAD_DIR=str(tmp_path), AIRDCPP_FOLDER_MODE='issuarr', AIRDCPP_REMOTE_DIR='',
        DDL_LOCATION=str(tmp_path), POST_PROCESSING=True, AIRDCPP_FOLDER_PACKS=True), raising=False)
    queue = []
    monkeypatch.setattr(mylar, 'PP_QUEUE', types.SimpleNamespace(put=queue.append), raising=False)
    monkeypatch.setattr(airdcpp_pack.db, 'DBConnection', FakeDB)
    snatched = []

    def foundsearch(comicid, issueid, **kw):
        snatched.append(issueid)
        for i in FakeDB.issues:
            if i['IssueID'] == issueid:
                i['Status'] = 'Snatched'
    monkeypatch.setattr(airdcpp_pack.updater, 'foundsearch', foundsearch)
    monkeypatch.setattr(airdcpp_pack.updater, 'nzblog', lambda *a, **kw: None)
    monkeypatch.setattr(airdcpp_pack.time, 'sleep', lambda s: None)
    monkeypatch.setattr(airdcpp_pack.airdcpp, 'AirDCPP', lambda **kw: types.SimpleNamespace(
        session=fake, headers={}, api_url='http://airdcpp:5600/api/v1'))
    FakeDB.comic = {'ComicName': 'Batman', 'ComicYear': '2016', 'AlternateSearch': None}
    FakeDB.issues = [
        {'ComicID': 'C', 'IssueID': 'i1', 'Issue_Number': '1', 'IssueDate': '2016-08-01', 'Status': 'Wanted'},
        {'ComicID': 'C', 'IssueID': 'i2', 'Issue_Number': '2', 'IssueDate': '2016-08-15', 'Status': 'Wanted'},
        {'ComicID': 'C', 'IssueID': 'i4', 'Issue_Number': '4', 'IssueDate': '2016-09-15', 'Status': 'Wanted'},
    ]
    return queue, snatched


ENTRY = {'peer': {'cid': 'CID', 'hub_url': 'adc://hub:1511', 'nicks': 'alice'}, 'folder': '/Comics/Batman (2016)/'}


@pytest.mark.unit
def test_grab_folder_queues_only_the_other_wanted_issues(monkeypatch, tmp_path):
    fake = FakeAirDC([item('Batman 001 (2016).cbz'), item('Batman 002 (2016).cbz'),
                      item('Batman 003 (2016).cbz'), item('Batman 004 (2016).cbz')], tmp_path.as_posix() + '/')
    queue, snatched = setup_pack(monkeypatch, tmp_path, fake)

    airdcpp_pack.grab_folder('C', 'i1', ENTRY)

    opened = [c for c in fake.calls if c[1] == '/filelists'][0][2]
    assert opened == {'user': {'cid': 'CID', 'hub_url': 'adc://hub:1511'}, 'directory': '/Comics/Batman (2016)/'}
    assert ('DELETE', '/filelists/FL', None) in fake.calls
    assert sorted(q['target_name'] for q in fake.queued.values()) == ['Batman 002 (2016).cbz', 'Batman 004 (2016).cbz']
    assert all(q['target_directory'] == tmp_path.as_posix() + '/' for q in fake.queued.values())
    assert sorted(snatched) == ['i2', 'i4']
    assert sorted(q['nzb_name'] for q in queue) == ['Batman 002 (2016)[__i2__].cbz', 'Batman 004 (2016)[__i4__].cbz']
    assert (tmp_path / 'Batman 002 (2016)[__i2__].cbz').exists()


@pytest.mark.unit
def test_failed_files_go_back_to_wanted(monkeypatch, tmp_path):
    fake = FakeAirDC([item('Batman 002 (2016).cbz')], tmp_path.as_posix() + '/', complete=False)
    queue, snatched = setup_pack(monkeypatch, tmp_path, fake)

    airdcpp_pack.grab_folder('C', 'i1', ENTRY)

    assert snatched == ['i2']
    assert queue == []
    assert [i['Status'] for i in FakeDB.issues if i['IssueID'] == 'i2'] == ['Wanted']


@pytest.mark.unit
def test_start_needs_the_setting_and_a_peer(monkeypatch, tmp_path):
    fake = FakeAirDC([], tmp_path.as_posix() + '/')
    setup_pack(monkeypatch, tmp_path, fake)
    monkeypatch.setattr(airdcpp_pack, 'grab_folder', lambda *a: None)
    assert airdcpp_pack.start('C', 'i1', {'peer': None, 'folder': '/x/'}) is False
    mylar.CONFIG.AIRDCPP_FOLDER_PACKS = False
    assert airdcpp_pack.start('C', 'i1', ENTRY) is False
    mylar.CONFIG.AIRDCPP_FOLDER_PACKS = True
    assert airdcpp_pack.start('C', 'i1', ENTRY) is True
