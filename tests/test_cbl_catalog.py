
import pytest
import requests

import mylar
from mylar import cbl_catalog

TREE = {'truncated': False, 'tree': [
    {'path': 'Marvel', 'type': 'tree'},
    {'path': 'Marvel/Events/[Marvel] Civil War.cbl', 'type': 'blob', 'size': 900},
    {'path': 'DC/[DC] Crisis.CBL', 'type': 'blob', 'size': 500},
    {'path': 'README.md', 'type': 'blob', 'size': 10},
]}


class Answer:
    def __init__(self, data=None, content=b'', status=200):
        self.data, self.content, self.status = data, content, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.exceptions.HTTPError(self.status)

    def json(self):
        return self.data


@pytest.fixture(autouse=True)
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', type('C', (), {'CACHE_DIR': str(tmp_path)})(), raising=False)


def test_lists_from_tree_keeps_cbl_files_only():
    lists = cbl_catalog.lists_from_tree(TREE)
    assert [x['path'] for x in lists] == ['DC/[DC] Crisis.CBL', 'Marvel/Events/[Marvel] Civil War.cbl']
    assert lists[1]['folder'] == 'Marvel/Events' and lists[1]['name'] == '[Marvel] Civil War'


def test_catalog_is_kept_for_a_day_and_falls_back_on_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(cbl_catalog.requests, 'get', lambda url, **k: calls.append(url) or Answer(TREE))
    assert len(cbl_catalog.catalog()['lists']) == 2
    assert len(cbl_catalog.catalog()['lists']) == 2
    assert len(calls) == 1

    def down(url, **k):
        raise requests.exceptions.ConnectionError('down')
    monkeypatch.setattr(cbl_catalog.requests, 'get', down)
    out = cbl_catalog.catalog(refresh=True)
    assert out['ok'] and len(out['lists']) == 2 and 'earlier' in out['note']


def test_catalog_without_copy_reports_failure(monkeypatch):
    monkeypatch.setattr(cbl_catalog.requests, 'get', lambda url, **k: Answer(status=403))
    out = cbl_catalog.catalog()
    assert not out['ok'] and out['lists'] == []


def test_fetch_only_listed_paths(monkeypatch):
    got = []
    monkeypatch.setattr(cbl_catalog.requests, 'get', lambda url, **k: got.append(url) or (Answer(TREE) if 'api.github' in url else Answer(content=b'<ReadingList/>')))
    cbl_catalog.catalog()
    assert cbl_catalog.fetch('../../etc/passwd')[0] is None
    name, body = cbl_catalog.fetch('Marvel/Events/[Marvel] Civil War.cbl')
    assert name == '[Marvel] Civil War.cbl' and body == b'<ReadingList/>'
    assert got[-1].endswith('Marvel/Events/%5BMarvel%5D%20Civil%20War.cbl')
