import socket
import types

import pytest

import mylar
from mylar import clientstatus


@pytest.fixture
def cfg(monkeypatch):
    c = types.SimpleNamespace(ENABLE_TORRENTS=False, JD2_ENABLE=False, SAB_HOST=None, NZBGET_HOST=None, NZBGET_PORT=None,
                              BLACKHOLE_DIR=None, QBITTORRENT_HOST=None, DELUGE_HOST=None, TORRENT_LOCAL=False,
                              LOCAL_WATCHDIR=None, JD2_URL=None)
    monkeypatch.setattr(mylar, 'CONFIG', c, raising=False)
    for flag in ('USE_SABNZBD', 'USE_NZBGET', 'USE_BLACKHOLE', 'USE_UTORRENT', 'USE_RTORRENT', 'USE_TRANSMISSION',
                 'USE_DELUGE', 'USE_QBITTORRENT', 'USE_WATCHDIR'):
        monkeypatch.setattr(mylar, flag, False, raising=False)
    monkeypatch.setattr(clientstatus, '_cache', {'at': 0.0, 'clients': None})
    return c


@pytest.mark.unit
def test_nothing_turned_on_lists_nothing(cfg):
    # the torrent client setting defaults to a watch folder, but torrents are off
    mylar.USE_WATCHDIR = True
    assert clientstatus.status() == []


@pytest.mark.unit
def test_only_enabled_clients_are_listed_and_checked(cfg, monkeypatch):
    seen = []
    monkeypatch.setattr(clientstatus, '_reachable', lambda host, port=None: seen.append((host, port)) or host != 'http://jd:3128')
    mylar.USE_NZBGET = True
    cfg.NZBGET_HOST, cfg.NZBGET_PORT = 'http://nzbget', '6789'
    cfg.ENABLE_TORRENTS, mylar.USE_QBITTORRENT, cfg.QBITTORRENT_HOST = True, True, 'qbit:8080'
    cfg.JD2_ENABLE, cfg.JD2_URL = True, 'http://jd:3128'
    assert clientstatus.status() == [{'name': 'NZBGet', 'ok': True}, {'name': 'qBittorrent', 'ok': True},
                                     {'name': 'JDownloader', 'ok': False}]
    assert seen == [('http://nzbget', '6789'), ('qbit:8080', None), ('http://jd:3128', None)]


@pytest.mark.unit
def test_results_are_cached_until_a_client_is_turned_on_or_off(cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(clientstatus, '_reachable', lambda host, port=None: calls.append(host) or True)
    cfg.JD2_ENABLE, cfg.JD2_URL = True, 'http://jd:3128'
    clientstatus.status()
    clientstatus.status()
    assert calls == ['http://jd:3128']
    mylar.USE_SABNZBD, cfg.SAB_HOST = True, 'http://sab:8080'
    assert [c['name'] for c in clientstatus.status()] == ['SABnzbd', 'JDownloader']


@pytest.mark.unit
def test_reachable_opens_a_connection_to_the_host_and_port(monkeypatch):
    opened = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(socket, 'create_connection', lambda addr, timeout=None: opened.append(addr) or Conn())
    assert clientstatus._reachable('https://sab.local/sabnzbd') and clientstatus._reachable('deluge:58846')
    assert clientstatus._reachable('http://nzbget', '6789')
    assert opened == [('sab.local', 443), ('deluge', 58846), ('nzbget', 6789)]
    monkeypatch.setattr(socket, 'create_connection', lambda addr, timeout=None: (_ for _ in ()).throw(OSError('refused')))
    assert clientstatus._reachable('qbit:8080') is False and clientstatus._reachable(None) is False
