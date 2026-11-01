"""Keys, passwords and tokens never reach the logs (issue #243)."""
import io
import logging
from types import SimpleNamespace

import pytest

import mylar
from mylar import redact


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    cfg = {k: v[2] for k, v in mylar.config._CONFIG_DEFINITIONS.items()}
    cfg.update(SAB_APIKEY='sabkey0123456789', COMICVINE_API='cvkey9876543210', HTTPS_KEY='/config/server.key',
               DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/1/hooktoken',
               EXTRA_NEWZNABS=[('NZBGeek', 'https://api.nzbgeek.info', '1', 'geekkey1234567', '', '1', 0)],
               EXTRA_TORZNABS=[], SAB_PASSWORD='abc')
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(**cfg), raising=False)
    redact.forget()
    yield
    redact.forget()


@pytest.mark.unit
def test_the_search_dump_from_the_issue_is_redacted():
    line = ("bb: {'entries': [{'title': 'Absolute Batman 025 [2026] [Digital]', "
            "'link': 'https://api.nzbgeek.info/api?t=get&id=abc123&apikey=someotherkey42', 'site': 'NZBGeek'}]}")
    out = redact.redact(line)
    assert 'someotherkey42' not in out
    assert 'apikey=REDACTED' in out and 'id=abc123' in out and 'Absolute Batman 025' in out


@pytest.mark.unit
@pytest.mark.parametrize('url', ['https://x.example/rss?r=SECRETVAL&i=12345', 'https://x.example/dl?passkey=SECRETVAL',
                                 'https://x.example/api?token=SECRETVAL', 'http://user:SECRETVAL@sab.local:8080/api'])
def test_secrets_in_urls_are_redacted(url):
    assert 'SECRETVAL' not in redact.redact('Fetching %s now' % url)


@pytest.mark.unit
def test_the_values_of_secret_settings_are_redacted_wherever_they_show():
    out = redact.redact('SAB said sabkey0123456789 was wrong; CV cvkey9876543210; geek geekkey1234567; '
                        'hook https://discord.com/api/webhooks/1/hooktoken')
    for secret in ('sabkey0123456789', 'cvkey9876543210', 'geekkey1234567', 'hooktoken'):
        assert secret not in out


@pytest.mark.unit
def test_paths_and_short_values_are_left_alone():
    assert redact.redact('Loading /config/server.key and abc') == 'Loading /config/server.key and abc'


@pytest.mark.unit
def test_the_filter_redacts_message_args_and_tracebacks():
    log = logging.getLogger('redact-test')
    log.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter('%(message)s'))
    log.addHandler(handler)
    log.addFilter(redact.SecretFilter())
    log.warning('Fetching %s', 'https://x.example/api?apikey=leakyleaky')
    try:
        raise ValueError('bad url https://x.example/api?apikey=leakyleaky')
    except ValueError:
        log.exception('failed')
    assert 'leakyleaky' not in stream.getvalue()
    assert 'ValueError: bad url https://x.example/api?apikey=REDACTED' in stream.getvalue()


@pytest.mark.unit
def test_the_mylar_logger_has_the_filter():
    from mylar import logger   # noqa: F401  (installs the filter)
    assert any(isinstance(f, redact.SecretFilter) for f in logging.getLogger('mylar').filters)


@pytest.mark.unit
def test_new_keys_are_masked_after_settings_are_saved():
    assert 'brandnewkey99' in redact.redact('brandnewkey99')
    mylar.CONFIG.SAB_APIKEY = 'brandnewkey99'
    redact.forget()
    assert redact.redact('brandnewkey99') == 'REDACTED'


def test_init_logger_uses_module_sys():
    # a local "import sys" in initLogger made the console handler's sys unbound at startup
    import symtable
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / 'mylar' / 'logger.py'
    top = symtable.symtable(src.read_text(), str(src), 'exec')
    found = [t for t in top.get_children() if t.get_name() == 'initLogger']
    assert found
    for table in found:
        assert not table.lookup('sys').is_local()
