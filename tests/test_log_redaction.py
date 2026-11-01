import logging
import types

import pytest

import mylar
from mylar import logredact


@pytest.fixture
def config(monkeypatch):
    cfg = types.SimpleNamespace(SAB_APIKEY='sabkey1234567', COMICVINE_API='cvkey7654321', QBITTORRENT_PASSWORD='hunter22',
                                PP_SSHKEYFILE='/config/id_rsa', HTTPS_KEY='/config/server.key', DELUGE_PASSWORD='abc',
                                EXTRA_NEWZNABS=[('NZBGeek', 'https://api.nzbgeek.info', '1', 'geekkey99887766', '', '1', '0')],
                                EXTRA_TORZNABS=[])
    monkeypatch.setattr(mylar, 'CONFIG', cfg, raising=False)
    logredact.forget()
    yield cfg
    logredact.forget()


def test_indexer_link_in_result_dump(config):
    line = "bb: {'entries': [{'title': 'Absolute Batman 025', 'link': 'https://api.nzbgeek.info/api?t=get&id=abc&apikey=0123456789abcdef'}]}"
    out = logredact.redact(line)
    assert '0123456789abcdef' not in out
    assert 'apikey=***' in out and 'id=abc' in out and 'Absolute Batman 025' in out


def test_query_names(config):
    out = logredact.redact('https://x/rss?r=secretR1&i=7 and https://y/dl?passkey=pk1&authkey=ak1&torrent_pass=tp1&token=tk1')
    for s in ('secretR1', 'pk1', 'ak1', 'tp1', 'tk1'):
        assert s not in out
    assert 'i=7' in out


def test_dict_and_json_pairs(config):
    out = logredact.redact("{'apikey': 'k1k1k1', \"password\": \"p2p2p2\", 'mode': 'queue'}")
    assert 'k1k1k1' not in out and 'p2p2p2' not in out and "'mode': 'queue'" in out


def test_userinfo(config):
    assert logredact.redact('http://admin:s3cr3t@sab:8080/api') == 'http://admin:***@sab:8080/api'


def test_configured_values_masked_anywhere(config):
    out = logredact.redact('ComicVine key cvkey7654321 failed; SAB sabkey1234567; geek geekkey99887766; qb hunter22')
    assert out == 'ComicVine key *** failed; SAB ***; geek ***; qb ***'


def test_paths_and_short_values_left_alone(config):
    assert logredact.redact('/config/id_rsa /config/server.key abc') == '/config/id_rsa /config/server.key abc'


def test_filter_masks_message_args_and_traceback(config):
    records = []

    class Keep(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    log = logging.getLogger('test-log-redaction')
    log.propagate = False
    log.addFilter(logredact.RedactFilter())
    handler = Keep()
    log.addHandler(handler)
    try:
        log.info('fetching %s', 'https://h/api?apikey=zzzzzzzz')
        try:
            raise ValueError('bad url https://h/api?t=get&apikey=yyyyyyyy')
        except ValueError:
            log.exception('failed with %s', config.SAB_APIKEY)
    finally:
        log.removeHandler(handler)
    text = '\n'.join(records)
    assert 'zzzzzzzz' not in text and 'yyyyyyyy' not in text and 'sabkey1234567' not in text
    assert 'apikey=***' in text and 'ValueError' in text
