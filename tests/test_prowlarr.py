import pytest

import mylar
from mylar import prowlarr

INDEXERS = [
    {'id': 1, 'name': 'NZBgeek', 'protocol': 'usenet', 'enable': True,
     'capabilities': {'categories': [{'id': 7000, 'subCategories': [{'id': 7030}]}]}},
    {'id': 2, 'name': 'Nyaa', 'protocol': 'torrent', 'enable': True,
     'capabilities': {'categories': [{'id': 5070}]}},
    {'id': 3, 'name': 'Old', 'protocol': 'torrent', 'enable': False, 'capabilities': {}},
]


class Answer:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class Conf:
    def __init__(self):
        self.EXTRA_NEWZNABS = [('Hand added', 'https://api.example/api', '1', 'k', '', '1', 1)]
        self.EXTRA_TORZNABS = []
        self.NEWZNAB = False
        self.ENABLE_TORZNAB = False
        self.PROWLARR_URL = None
        self.PROWLARR_APIKEY = None
        self.PROWLARR_SYNC = False
        self.PROWLARR_KNOWN = ''
        self.saved = 0

    def writeconfig(self):
        self.saved += 1


@pytest.fixture
def conf(monkeypatch):
    c = Conf()
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', c, raising=False)
    monkeypatch.setattr(mylar, 'PROVIDER_START_ID', 1, raising=False)
    state = {'indexers': INDEXERS}
    monkeypatch.setattr(prowlarr.requests, 'get', lambda url, **k: Answer(state['indexers']))
    c.state = state
    return c


def test_fetch_reads_protocol_and_comics(conf):
    got = prowlarr.fetch('http://prowlarr:9696/', 'key')
    assert [(x['name'], x['protocol'], x['enabled'], x['comics']) for x in got] == [
        ('Nyaa', 'torrent', True, False), ('NZBgeek', 'usenet', True, True), ('Old', 'torrent', False, False)]


def test_add_creates_entries_through_prowlarr(conf):
    out = prowlarr.add('http://prowlarr:9696/', 'key', ['1', '2'], sync=True)
    assert out['ok'] and out['added'] == 2
    assert conf.EXTRA_NEWZNABS[1][:6] == ('NZBgeek (Prowlarr)', 'http://prowlarr:9696/1/api', '0', 'key', '#7030', '1')
    assert conf.EXTRA_TORZNABS[0][:6] == ('Nyaa (Prowlarr)', 'http://prowlarr:9696/2/api', '0', 'key', '7030', '1')
    assert {conf.EXTRA_NEWZNABS[1][6], conf.EXTRA_TORZNABS[0][6]} == {2, 3}
    assert conf.NEWZNAB and conf.ENABLE_TORZNAB and conf.PROWLARR_SYNC
    assert conf.PROWLARR_URL == 'http://prowlarr:9696' and conf.PROWLARR_KNOWN == '1,2,3'
    # adding again changes nothing
    assert prowlarr.add('http://prowlarr:9696', 'key', ['1'])['added'] == 0
    listed = prowlarr.listing('http://prowlarr:9696', 'key')['indexers']
    assert [(x['name'], x['added']) for x in listed] == [('Nyaa', True), ('NZBgeek', True), ('Old', False)]


def test_sync_adds_new_turns_off_gone_and_rekeys(conf):
    prowlarr.add('http://prowlarr:9696', 'key', ['1', '2'], sync=True)
    conf.EXTRA_TORZNABS.pop()            # removed by hand here: not added back
    conf.state['indexers'] = [
        dict(INDEXERS[0], enable=False),  # turned off in Prowlarr
        INDEXERS[1],
        {'id': 4, 'name': 'New one', 'protocol': 'torrent', 'enable': True, 'capabilities': {}},
    ]
    conf.PROWLARR_APIKEY = 'newkey'
    out = prowlarr.sync()
    assert out == {'added': 1, 'off': 1, 'rekey': 0}
    assert [e[0] for e in conf.EXTRA_TORZNABS] == ['New one (Prowlarr)']
    assert conf.EXTRA_TORZNABS[0][3] == 'newkey'
    assert conf.EXTRA_NEWZNABS[1][5] == '0'
    assert conf.EXTRA_NEWZNABS[0][5] == '1'   # hand-added indexer untouched


def test_sync_turns_off_indexers_deleted_from_prowlarr_and_updates_keys(conf):
    prowlarr.add('http://prowlarr:9696', 'key', ['1', '2'], sync=True)
    conf.state['indexers'] = [INDEXERS[1]]
    conf.PROWLARR_APIKEY = 'rotated'
    assert prowlarr.sync() == {'added': 0, 'off': 1, 'rekey': 1}
    assert conf.EXTRA_NEWZNABS[1][5] == '0'
    assert conf.EXTRA_TORZNABS[0][3] == 'rotated'


def test_sync_does_nothing_when_off(conf):
    assert prowlarr.sync() is None
    assert conf.saved == 0
