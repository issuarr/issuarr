"""Watching download clients for downloads in Issuarr's category (#245).

2026-11-01: qBittorrent had no completion monitor, and SABnzbd/NZBGet handling followed only jobs
Issuarr sent, so downloads added by hand with Issuarr's category were never seen. The watcher lists
each client's category, files finished downloads whose files match a watchlist issue, and leaves
the rest waiting as "Needs a choice".
"""
import os

import pytest

import mylar
from mylar import clientwatch, db


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'DB_FILE', str(tmp_path / 'mylar.db'), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    for k, v in mylar.config._CONFIG_DEFINITIONS.items():
        monkeypatch.setattr(mylar.CONFIG, k, v[2], raising=False)
    for k, v in dict(IGNORE_SEARCH_WORDS=[], CUSTOM_ISSUE_EXCEPTIONS=[], ANNUALS_ON=False, ENABLE_TORRENTS=True,
                     DYNAMIC_UPDATE=99, OLDCONFIG_VERSION=None, POST_PROCESSING=True, CLIENT_WATCH=True,
                     QBITTORRENT_HOST='http://qbit:8080', QBITTORRENT_LABEL='comics', SAB_HOST='http://sab:8080',
                     SAB_CATEGORY='comics', CHECK_FOLDER=None, DDL_LOCATION=None).items():
        monkeypatch.setattr(mylar.CONFIG, k, v, raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    for flag in ('USE_SABNZBD', 'USE_NZBGET', 'USE_QBITTORRENT'):
        monkeypatch.setattr(mylar, flag, False, raising=False)
    mylar.USE_QBITTORRENT = True
    mylar.dbcheck()
    for name in ('LAST', 'NOTES', 'FINISHED_AT', 'MATCHES'):
        monkeypatch.setattr(clientwatch, name, {})
    monkeypatch.setattr(clientwatch, 'WARNED', set())
    monkeypatch.setattr(clientwatch, 'MISSING', [])
    monkeypatch.setattr(clientwatch, 'RUN', {'busy': False, 'last': 0.0})
    monkeypatch.setattr(clientwatch, 'SETTLE', 0)

    myDB = db.DBConnection()
    myDB.action("INSERT INTO comics (ComicID, ComicName, ComicYear) VALUES ('100', 'Foo', '2020')")
    myDB.action("INSERT INTO issues (IssueID, ComicID, Issue_Number, Status) VALUES ('1001', '100', '1', 'Wanted')")
    myDB.action("INSERT INTO issues (IssueID, ComicID, Issue_Number, Status) VALUES ('1002', '100', '2', 'Snatched')")

    filed = []
    monkeypatch.setattr(clientwatch, 'file_as', lambda path, issue: filed.append((os.path.basename(path), issue['IssueID'])) or True)
    matches = {'Foo 001 (2020).cbz': {'comicid': '100', 'issueid': '1001', 'series': 'Foo', 'year': '2020', 'number': '1', 'owned': False}}
    monkeypatch.setattr(clientwatch, 'identify', lambda name: matches.get(name))
    torrents = []
    monkeypatch.setitem(clientwatch.FETCHERS, 'qbittorrent', lambda cat: clientwatch.qbit_items(torrents, cat))
    return {'tmp': tmp_path, 'filed': filed, 'torrents': torrents, 'db': myDB}


def torrent(tmp, name, state='uploading', progress=1.0, h='abc', category='comics', make=True):
    path = tmp / 'downloads' / name
    if make:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x')
    return {'hash': h, 'name': name, 'state': state, 'progress': progress, 'category': category, 'size': 100,
            'dlspeed': 10, 'eta': 60, 'content_path': str(path)}


# ---- reading each client ----

@pytest.mark.unit
def test_sabnzbd_lists_only_the_category_and_reads_history_states():
    q = {'queue': {'slots': [{'nzo_id': 'A', 'filename': 'Foo 003', 'cat': 'Comics', 'status': 'Downloading', 'mb': '10', 'mbleft': '5'},
                             {'nzo_id': 'B', 'filename': 'A movie', 'cat': 'movies', 'status': 'Downloading', 'mb': '10', 'mbleft': '5'}]}}
    h = {'history': {'slots': [{'nzo_id': 'C', 'name': 'Foo 001', 'category': 'comics', 'status': 'Completed', 'storage': '/dl/comics/Foo 001', 'bytes': 9},
                               {'nzo_id': 'D', 'name': 'Foo 002', 'category': 'comics', 'status': 'Failed', 'fail_message': 'Out of retention'},
                               {'nzo_id': 'E', 'name': 'Foo 004', 'category': 'comics', 'status': 'Extracting'}]}}
    items = {i['id']: i for i in clientwatch.sab_items(q, h, 'comics')}
    assert set(items) == {'A', 'C', 'D', 'E'}
    assert items['A']['state'] == 'Downloading' and items['A']['percent'] == 50
    assert items['C']['state'] == 'Finished' and items['C']['path'] == '/dl/comics/Foo 001'
    assert items['D']['state'] == 'Failed' and items['D']['message'] == 'Out of retention'
    assert items['E']['state'] == 'Processing'


@pytest.mark.unit
def test_nzbget_skips_other_categories_and_deleted_history():
    groups = [{'NZBID': 1, 'NZBName': 'Foo 003', 'Category': 'comics', 'Status': 'QUEUED', 'FileSizeMB': 10, 'RemainingSizeMB': 10}]
    history = [{'NZBID': 2, 'Name': 'Foo 001', 'Category': 'comics', 'Status': 'SUCCESS/ALL', 'DestDir': '/dl/Foo 001', 'Kind': 'NZB'},
               {'NZBID': 3, 'Name': 'Foo 002', 'Category': 'comics', 'Status': 'DELETED/MANUAL', 'Kind': 'NZB'},
               {'NZBID': 4, 'Name': 'Other', 'Category': 'tv', 'Status': 'SUCCESS/ALL', 'Kind': 'NZB'}]
    items = {i['id']: i for i in clientwatch.nzbget_items(groups, history, 'comics')}
    assert set(items) == {'1', '2'}
    assert items['1']['state'] == 'Queued'
    assert items['2']['state'] == 'Finished' and items['2']['path'] == '/dl/Foo 001'


@pytest.mark.unit
def test_qbittorrent_states(tmp_path):
    ts = [torrent(tmp_path, 'a.cbz', 'stalledUP', 1.0, 'A', make=False), torrent(tmp_path, 'b.cbz', 'stalledDL', 0.4, 'B', make=False),
          torrent(tmp_path, 'c.cbz', 'missingFiles', 1.0, 'C', make=False), torrent(tmp_path, 'd.cbz', 'pausedDL', 0.1, 'D', make=False),
          torrent(tmp_path, 'e.mkv', 'uploading', 1.0, 'E', category='tv', make=False)]
    items = {i['id']: i for i in clientwatch.qbit_items(ts, 'comics')}
    assert {k: v['state'] for k, v in items.items()} == {'a': 'Finished', 'b': 'Downloading', 'c': 'Failed', 'd': 'Paused'}
    assert items['b']['percent'] == 40


@pytest.mark.unit
def test_a_client_path_is_found_under_a_folder_issuarr_knows(env, monkeypatch):
    local = env['tmp'] / 'mnt' / 'processing' / 'comics' / 'Foo 001'
    local.mkdir(parents=True)
    monkeypatch.setattr(mylar.CONFIG, 'CHECK_FOLDER', str(env['tmp'] / 'mnt' / 'processing'))
    assert clientwatch.local_path('qbittorrent', '/data/torrents/comics/Foo 001') == str(local)
    assert clientwatch.local_path('qbittorrent', '/data/torrents/comics/Nope') is None


# ---- the check ----

@pytest.mark.unit
def test_a_finished_download_you_added_is_filed_once_when_it_matches(env):
    env['torrents'].append(torrent(env['tmp'], 'Foo 001 (2020).cbz'))
    clientwatch.check(force=True)
    assert env['filed'] == [('Foo 001 (2020).cbz', '1001')]
    clientwatch.check(force=True)
    assert len(env['filed']) == 1
    assert clientwatch.queue_rows(env['db']) == []


@pytest.mark.unit
def test_a_download_nothing_matches_waits_as_needs_a_choice(env):
    env['torrents'].append(torrent(env['tmp'], 'Mystery 001.cbz'))
    clientwatch.check(force=True)
    assert env['filed'] == []
    rows = clientwatch.queue_rows(env['db'])
    assert [(r['status'], r['source'], r['via']) for r in rows] == [('Needs a choice', 'qBittorrent', 'Added by you')]


@pytest.mark.unit
def test_a_download_in_progress_shows_what_it_matches(env):
    env['torrents'].append(torrent(env['tmp'], 'Foo 001 (2020).cbz', 'downloading', 0.5))
    clientwatch.check(force=True)
    rows = clientwatch.queue_rows(env['db'])
    assert rows[0]['status'] == 'Downloading' and rows[0]['message'] == 'Matches Foo (2020) #1'
    assert env['filed'] == []


@pytest.mark.unit
def test_a_finished_download_waits_one_check_before_filing(env, monkeypatch):
    monkeypatch.setattr(clientwatch, 'SETTLE', 50)
    env['torrents'].append(torrent(env['tmp'], 'Foo 001 (2020).cbz'))
    clientwatch.check(force=True)
    assert env['filed'] == []
    assert clientwatch.queue_rows(env['db'])[0]['status'] == 'Waiting to file'


@pytest.mark.unit
def test_issuarrs_own_qbittorrent_grab_is_filed_as_the_issue_it_was_grabbed_for(env):
    env['db'].action("CREATE TABLE IF NOT EXISTS client_jobs (IssueID TEXT, IssueArcID TEXT, ComicID TEXT, Client TEXT, "
                     "JobID TEXT, Name TEXT, DateAdded TEXT)")
    env['db'].action("INSERT INTO client_jobs (IssueID, ComicID, Client, JobID) VALUES ('1002', '100', 'qbittorrent', 'OWN')")
    env['torrents'].append(torrent(env['tmp'], 'Some odd name.cbz', h='own'))
    clientwatch.check(force=True)
    assert env['filed'] == [('Some odd name.cbz', '1002')]
    assert clientwatch.queue_rows(env['db']) == []


@pytest.mark.unit
def test_issuarrs_own_sabnzbd_grab_is_left_to_completed_download_handling(env, monkeypatch):
    mylar.USE_SABNZBD = True
    env['db'].action("CREATE TABLE IF NOT EXISTS client_jobs (IssueID TEXT, IssueArcID TEXT, ComicID TEXT, Client TEXT, "
                     "JobID TEXT, Name TEXT, DateAdded TEXT)")
    env['db'].action("INSERT INTO client_jobs (IssueID, ComicID, Client, JobID) VALUES ('1001', '100', 'sabnzbd', 'SABnzbd_nzo_1')")
    path = env['tmp'] / 'sab' / 'Foo 001 (2020).cbz'
    path.parent.mkdir()
    path.write_bytes(b'x')
    item = clientwatch._item('sabnzbd', 'SABnzbd_nzo_1', 'Foo 001 (2020)', 'Finished', path=str(path))
    monkeypatch.setitem(clientwatch.FETCHERS, 'sabnzbd', lambda cat: [dict(item)])
    clientwatch.check(force=True)
    assert env['filed'] == []
    assert clientwatch.queue_rows(env['db']) == []


@pytest.mark.unit
def test_files_that_cant_be_found_are_logged_together_and_not_filed(env):
    env['torrents'].append(torrent(env['tmp'], 'Foo 001 (2020).cbz', make=False))
    env['torrents'][0]['content_path'] = '/elsewhere/Foo 001 (2020).cbz'
    clientwatch.check(force=True)
    assert env['filed'] == []
    row = clientwatch.queue_rows(env['db'])[0]
    assert row['status'] == 'Not filed' and '/elsewhere' in row['message']


@pytest.mark.unit
def test_nothing_is_checked_when_watching_is_off(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'CLIENT_WATCH', False)
    env['torrents'].append(torrent(env['tmp'], 'Foo 001 (2020).cbz'))
    assert clientwatch.check(force=True) == []
    assert env['filed'] == [] and clientwatch.LAST == {}


@pytest.mark.unit
def test_a_client_without_a_category_is_not_watched(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'QBITTORRENT_LABEL', None)
    assert clientwatch.watched() == []



@pytest.mark.unit
def test_identify_asks_the_watchlist_and_needs_series_and_issue_to_agree(monkeypatch):
    from mylar import attention
    monkeypatch.setattr(clientwatch, 'MATCHES', {})
    best = {'comicid': '100', 'name': 'Foo', 'year': '2020', 'issueid': '1001', 'number': '1', 'owned': False,
            'agree': {'series': True, 'issue': True, 'year': True, 'volume': None, 'format': True}}
    monkeypatch.setattr(attention, 'parse', lambda name: {'series': 'Foo', 'name': name})
    monkeypatch.setattr(attention, 'suggest', lambda parsed, limit=3: [best])
    assert clientwatch.identify('Foo 001 (2020).cbz')['issueid'] == '1001'
    best['agree']['year'] = False
    assert clientwatch.identify('Foo 001 (1999).cbz') is None
    best['agree'].update(year=True, issue=False)
    assert clientwatch.identify('Foo 099 (2020).cbz') is None


# ---- step 2: Deluge, Transmission, rTorrent, uTorrent ----

@pytest.mark.unit
def test_other_torrent_clients_are_read_by_label_or_transmission_folder():
    rows = [{'hash': 'A', 'name': 'Foo 001.cbz', 'label': 'comics', 'progress': 1.0, 'path': '/dl/Foo 001.cbz'},
            {'hash': 'B', 'name': 'Foo 002.cbz', 'label': 'Comics', 'progress': 0.25, 'total': 400, 'speed': 5, 'eta': 60},
            {'hash': 'C', 'name': 'A movie', 'label': 'movies', 'progress': 1.0},
            {'hash': 'D', 'name': 'Foo 003.cbz', 'label': 'comics', 'progress': 0.5, 'error': 'Tracker gone'},
            {'hash': 'E', 'name': 'Foo 004.cbz', 'label': 'comics', 'progress': 0.9, 'seeding': True}]
    items = {i['id']: i for i in clientwatch.torrent_items('deluge', rows, 'comics')}
    assert {k: v['state'] for k, v in items.items()} == {'a': 'Finished', 'b': 'Downloading', 'd': 'Failed', 'e': 'Finished'}
    assert items['b']['percent'] == 25 and items['d']['message'] == 'Tracker gone'
    tr = [{'hash': 'F', 'name': 'Foo 005.cbz', 'folder': '/data/comics/', 'progress': 1.0},
          {'hash': 'G', 'name': 'Other', 'folder': '/data/tv', 'progress': 1.0}]
    assert [i['id'] for i in clientwatch.torrent_items('transmission', tr, '/data/comics', by_folder=True)] == ['f']


@pytest.mark.unit
def test_every_torrent_client_with_a_label_is_watched(env, monkeypatch):
    for flag in ('USE_DELUGE', 'USE_TRANSMISSION', 'USE_RTORRENT', 'USE_UTORRENT'):
        monkeypatch.setattr(mylar, flag, True, raising=False)
    for k, v in dict(DELUGE_HOST='d:58846', DELUGE_LABEL='comics', TRANSMISSION_HOST='http://t:9091', TRANSMISSION_DIRECTORY='/data/comics',
                     RTORRENT_HOST='r:5000', RTORRENT_LABEL='comics', UTORRENT_HOST='http://u:8080', UTORRENT_LABEL=None).items():
        monkeypatch.setattr(mylar.CONFIG, k, v, raising=False)
    assert [c for c, _ in clientwatch.watched()] == ['qbittorrent', 'deluge', 'transmission', 'rtorrent']


@pytest.mark.unit
def test_own_deluge_grab_is_left_to_auto_snatch_when_it_is_on(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'AUTO_SNATCH', False, raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'LOCAL_TORRENT_PP', False, raising=False)
    assert clientwatch._ours_to_file('deluge') and clientwatch._ours_to_file('transmission')
    monkeypatch.setattr(mylar.CONFIG, 'AUTO_SNATCH', True, raising=False)
    assert not clientwatch._ours_to_file('deluge') and not clientwatch._ours_to_file('rtorrent')
    assert clientwatch._ours_to_file('utorrent') and not clientwatch._ours_to_file('sabnzbd')


@pytest.mark.unit
def test_a_finished_deluge_download_you_added_is_filed(env, monkeypatch):
    monkeypatch.setattr(mylar, 'USE_DELUGE', True, raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'DELUGE_HOST', 'd:58846', raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'DELUGE_LABEL', 'comics', raising=False)
    path = env['tmp'] / 'deluge' / 'Foo 001 (2020).cbz'
    path.parent.mkdir()
    path.write_bytes(b'x')
    rows = [{'hash': 'DEL1', 'name': 'Foo 001 (2020).cbz', 'label': 'comics', 'progress': 1.0, 'path': str(path)}]
    monkeypatch.setitem(clientwatch.FETCHERS, 'deluge', lambda label: clientwatch.torrent_items('deluge', rows, label))
    clientwatch.check(force=True)
    assert env['filed'] == [('Foo 001 (2020).cbz', '1001')]
