import types

import pytest

import mylar
from mylar import sabnzbd


@pytest.fixture
def sent(monkeypatch):
    calls = []

    class Resp:
        def json(self):
            return {'status': True}

    def fake_get(url, params=None, verify=None):
        calls.append(dict(params))
        return Resp()

    monkeypatch.setattr(sabnzbd.requests, 'get', fake_get)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    return calls


def client(monkeypatch, completed, failed):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(SAB_HOST='http://sab:8080', SAB_APIKEY='k',
                                                               SAB_REMOVE_COMPLETED=completed, SAB_REMOVE_FAILED=failed), raising=False)
    return sabnzbd.SABnzbd(params={})


def test_finished_job_keeps_its_files_with_both_switches_on(monkeypatch, sent):
    client(monkeypatch, True, True).remove_history('nzo_1', 'Completed')
    assert len(sent) == 1 and sent[0]['name'] == 'delete' and 'del_files' not in sent[0]


def test_failed_job_files_deleted(monkeypatch, sent):
    client(monkeypatch, False, True).remove_history('nzo_2', 'Failed')
    assert sent[0]['del_files'] == 1


def test_finished_job_left_alone_without_remove_finished(monkeypatch, sent):
    client(monkeypatch, False, True).remove_history('nzo_3', 'Completed')
    assert sent == []
