import json
import types

import pytest
import requests

import mylar
from mylar import webserve


@pytest.fixture
def calls(monkeypatch):
    made = []

    def dead(url, params=None, verify=None, timeout=None):
        made.append(timeout)
        raise requests.exceptions.ConnectTimeout('no answer')

    monkeypatch.setattr(webserve.requests, 'get', dead)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(SAB_HOST='http://192.0.2.1:8080', SAB_USERNAME=None,
                                                               SAB_PASSWORD=None, SAB_APIKEY='x'), raising=False)
    return made


@pytest.mark.unit
def test_an_address_that_does_not_answer_gives_up_once_with_a_timeout(calls):
    result = json.loads(webserve.WebInterface().SABtest())
    assert result['status'] is False
    # one try, not a second one without SSL checks, and never without a timeout
    assert calls == [30]
