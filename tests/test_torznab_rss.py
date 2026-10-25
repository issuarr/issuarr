import pytest

import mylar
from mylar import rsscheck

FEED = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:torznab="http://torznab.com/schemas/2015/feed">
<channel><title>Prowlarr</title>
<item>
  <title>Saga 061 (2022) (Digital) (Zone-Empire)</title>
  <guid>https://tracker.example/t/1</guid>
  <link>http://prowlarr:9696/1/download?apikey=x&amp;link=abc</link>
  <pubDate>Wed, 22 Oct 2026 10:00:00 +0000</pubDate>
  <size>41234567</size>
  <enclosure url="http://prowlarr:9696/1/download?apikey=x&amp;link=abc" length="41234567" type="application/x-bittorrent"/>
  <torznab:attr name="seeders" value="12"/>
  <torznab:attr name="size" value="41234567"/>
</item>
<item>
  <title>Monstress 050 (2024) (Digital)</title>
  <link>magnet:?xt=urn:btih:abcdef</link>
  <pubDate>Wed, 22 Oct 2026 09:00:00 +0000</pubDate>
  <torznab:attr name="size" value="30000000"/>
</item>
</channel></rss>'''


class Conf:
    ENABLE_TORRENT_SEARCH = True
    ENABLE_TORZNAB = True
    NEWZNAB = False
    EXPERIMENTAL = False
    ENABLE_AIRDCPP = False
    EXTRA_NEWZNABS = []
    EXTRA_TORZNABS = [['Prowlarr', 'http://prowlarr:9696/1/api/', '0', 'key', '7030#8020', '1'],
                      ['Off', 'http://off/api', '0', 'key', '', '0']]


class Answer:
    status_code = 200
    content = FEED


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', Conf(), raising=False)
    monkeypatch.setattr(rsscheck.helpers, 'block_provider_check', lambda name: False)


def test_only_enabled_torznabs_while_torrent_search_is_on(monkeypatch):
    assert [t[0] for t in rsscheck.torznab_feed_hosts()] == ['Prowlarr']
    monkeypatch.setattr(Conf, 'ENABLE_TORRENT_SEARCH', False)
    assert rsscheck.torznab_feed_hosts() == []


def test_feed_request_is_a_search_without_query():
    site, url, verify, params = rsscheck.torznab_feed_request(Conf.EXTRA_TORZNABS[0])
    assert (site, url, verify) == ('Prowlarr', 'http://prowlarr:9696/1/api', False)
    assert params == {'t': 'search', 'cat': '7030,8020', 'apikey': 'key', 'limit': '100'}
    assert rsscheck.torznab_feed_request(['', 'http://x/api', '1', 'k', None, '1'])[3]['cat'] == '8020'


def test_rss_check_stores_torznab_releases(monkeypatch):
    calls, stored = [], []
    monkeypatch.setattr(rsscheck.requests, 'get', lambda url, **k: calls.append((url, k['params'])) or Answer())
    monkeypatch.setattr(rsscheck, 'rssdbupdate', lambda data, i, kind: stored.append((data, kind)))
    rsscheck.nzbs()
    assert [c[0] for c in calls] == ['http://prowlarr:9696/1/api']
    data, kind = stored[0]
    assert kind == 'usenet'
    assert [(d['Site'], d['Title'], str(d['Size'])) for d in data] == [
        ('Prowlarr', 'Saga 061 (2022) (Digital) (Zone-Empire)', '41234567'),
        ('Prowlarr', 'Monstress 050 (2024) (Digital)', '30000000')]
    assert data[0]['Link'].startswith('http://prowlarr:9696/1/download')
    assert data[1]['Link'].startswith('magnet:')
    assert all(d['Pubdate'] for d in data)
