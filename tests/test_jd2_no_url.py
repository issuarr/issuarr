"""JD2 turned on with a blank address used to crash the JD2 queue thread with
"ValueError: JD2 URL is not configured" (issue #179)."""
import queue
import types

import pytest

import mylar
from mylar.queues import jd2


@pytest.fixture
def config(monkeypatch):
    cfg = types.SimpleNamespace(JD2_ENABLE=True, JD2_URL='', JD2_DEST_DIR=None, POST_PROCESSING=False)
    monkeypatch.setattr(mylar, 'CONFIG', cfg, raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(jd2.LOADED, 'is_set', lambda: False)
    return cfg


@pytest.mark.unit
@pytest.mark.parametrize('url', ['', None, '/'])
def test_the_monitor_stops_quietly_without_an_address(config, url):
    config.JD2_URL = url
    q = queue.Queue()
    q.put('startup')
    jd2.jd2_queue_monitor(q)  # returns instead of raising
    # the startup item is left for the monitor that starts once an address is saved
    assert q.get_nowait() == 'startup'


@pytest.mark.unit
def test_without_an_address_jd2_counts_as_off(config):
    assert jd2.loaded()
    config.JD2_URL = 'http://127.0.0.1:3128'
    assert not jd2.loaded()
