import base64
from types import SimpleNamespace
from unittest import mock

import pytest

import mylar
from mylar import notifiers


@pytest.fixture(autouse=True)
def _quiet_logger(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)


def _config(**kw):
    base = dict(NTFY_SERVER_URL='https://ntfy.example/', NTFY_TOPIC='comics-abc', NTFY_TOKEN='tk_1',
                WEBHOOK_URL='https://hooks.example/issuarr')
    base.update(kw)
    return SimpleNamespace(**base)


def _resp(code=200):
    return SimpleNamespace(status_code=code, text='')


def test_ntfy_text_only_posts_to_topic_with_token():
    with mock.patch.object(mylar, 'CONFIG', _config(), create=True), \
         mock.patch.object(notifiers.requests, 'post', return_value=_resp()) as post:
        assert notifiers.NTFY().notify('Snatched', 'Issue snatched!', snatched_nzb='Saga (2018) #54', prov='GetComics')
    url, = post.call_args.args
    assert url == 'https://ntfy.example/comics-abc'
    assert post.call_args.kwargs['headers'] == {'Authorization': 'Bearer tk_1'}
    assert post.call_args.kwargs['params']['message'] == 'Issue snatched!: Saga (2018) #54 from GetComics'


def test_ntfy_attaches_cover_and_links_comicvine():
    cover = base64.b64encode(b'\xff\xd8jpeg').decode()
    with mock.patch.object(mylar, 'CONFIG', _config(NTFY_TOKEN=None), create=True), \
         mock.patch.object(notifiers.requests, 'put', return_value=_resp()) as put:
        assert notifiers.NTFY().notify('Done', 'Filed Saga #54', imageFile=cover, metadata={'issueid': '42'})
    kw = put.call_args.kwargs
    assert kw['data'] == b'\xff\xd8jpeg'
    assert kw['params']['filename'] == 'cover.jpg'
    assert kw['params']['click'] == 'https://comicvine.gamespot.com/issue/4000-42/'
    assert kw['headers'] == {}


def test_ntfy_without_topic_sends_nothing():
    with mock.patch.object(mylar, 'CONFIG', _config(NTFY_TOPIC=''), create=True), \
         mock.patch.object(notifiers.requests, 'post') as post:
        assert notifiers.NTFY().notify('t', 'm') is False
    post.assert_not_called()


def test_webhook_payload_fields():
    with mock.patch.object(mylar, 'CONFIG', _config(), create=True), \
         mock.patch.object(notifiers.requests, 'post', return_value=_resp(204)) as post:
        ok = notifiers.WEBHOOK().notify('Snatched', 'Issue snatched!', snatched_nzb='Saga (2018) #54', prov='NZBgeek',
                                        sent_to='SABnzbd', metadata={'series': 'Saga', 'issue': '54', 'year': '2018'},
                                        event='snatched')
    assert ok
    body = post.call_args.kwargs['json']
    assert body['event'] == 'snatched'
    assert body['series'] == 'Saga' and body['issue'] == '54'
    assert body['release'] == 'Saga (2018) #54' and body['provider'] == 'NZBgeek' and body['client'] == 'SABnzbd'
    assert body['comicvine_url'] is None
    assert body['time'].endswith('Z')


def test_webhook_error_status_is_failure():
    with mock.patch.object(mylar, 'CONFIG', _config(), create=True), \
         mock.patch.object(notifiers.requests, 'post', return_value=_resp(500)):
        assert notifiers.WEBHOOK().test_notify() is False
