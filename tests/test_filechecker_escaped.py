import types

import pytest

import mylar
from mylar import config, filechecker


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    c = types.SimpleNamespace(**{k: v[2] for k, v in config._CONFIG_DEFINITIONS.items()})
    c.IGNORE_SEARCH_WORDS = []
    monkeypatch.setattr(mylar, 'CONFIG', c, raising=False)


@pytest.mark.unit
@pytest.mark.parametrize('name,out', [
    ('X-Men _C2_BD (1998) (digital)', 'X-Men ½ (1998) (digital)'),
    ('Pok_C3_A9mon Adventures 01', 'Pok_C3_A9mon Adventures 01'),   # inside a word: left alone
    ('Pok_C3_A9 01', 'Poké 01'),
    ('Hulk _E2_80_94 Gray 01', 'Hulk \u2014 Gray 01'),
    ('X-Men_C2_BD_1998', 'X-Men½_1998'),
    ('Batman_Beyond_Be 01', 'Batman_Beyond_Be 01'),      # one byte, or not a byte: left alone
    ('Death_BE_DE 01', 'Death_BE_DE 01'),                # not UTF-8: left alone
    ('Hulk_20_12 01', 'Hulk_20_12 01'),                  # ASCII bytes: left alone
])
def test_unescape_bytes(name, out):
    assert filechecker.unescape_bytes(name) == out


@pytest.mark.unit
def test_escaped_half_reads_as_issue_half():
    # "X-Men ½ (1998)" written by a tool that escaped the ½ as its UTF-8 bytes
    r = filechecker.FileChecker(file='X-Men _C2_BD (1998) (digital) (Minutemen-Bluntman).cbr').listFiles()
    assert r['series_name'] == 'X-Men'
    assert r['issue_number'] == '½'
    assert r['issue_year'] == '1998'
    # the name on disk is kept, so filing still finds the file
    assert r['comicfilename'] == 'X-Men _C2_BD (1998) (digital) (Minutemen-Bluntman).cbr'
