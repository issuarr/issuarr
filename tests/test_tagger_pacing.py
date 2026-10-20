"""Tagging follows ComicVine's rate limit, and imprint series are tagged with their parent publisher."""
import datetime
import json
import os
import sqlite3
import types
import zipfile

import pytest

import mylar
from mylar import cmtagmylar, cv, db, importstatus


@pytest.fixture
def config(tmp_path, monkeypatch):
    c = types.SimpleNamespace(CT_SETTINGSPATH=str(tmp_path / 'ct'), CACHE_DIR=str(tmp_path / 'cache'), FILE_OPTS='move',
                              CT_TAG_CR=True, CBR2CBZ_ONLY=False, CT_TAG_MODE='overwrite', COMICVINE_API='personal-key',
                              COMICVINE_URL=None, CMTAG_VOLUME=False, SETDEFAULTVOLUME=False, CT_NOTES_FORMAT='Issue ID',
                              PROWL_ENABLED=False, PUSHOVER_ENABLED=False, BOXCAR_ENABLED=False, PUSHBULLET_ENABLED=False,
                              TELEGRAM_ENABLED=False, SLACK_ENABLED=False, MATTERMOST_ENABLED=False, DISCORD_ENABLED=False,
                              EMAIL_ENABLED=False, GOTIFY_ENABLED=False)
    for d in (c.CT_SETTINGSPATH, c.CACHE_DIR):
        os.makedirs(d, exist_ok=True)
    monkeypatch.setattr(mylar, 'CONFIG', c, raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(cmtagmylar, '_fetches', cmtagmylar.deque())
    monkeypatch.setattr(cmtagmylar, 'series_publisher', lambda issueid: (None, None))
    importstatus.clear_ratelimit()
    yield c
    importstatus.clear_ratelimit()


@pytest.fixture
def waits(monkeypatch):
    waited = []

    def fake_wait(seconds):
        waited.append(round(seconds))
        # let the oldest call in the hour drop out, as if the time had passed
        if cmtagmylar._fetches:
            cmtagmylar._fetches[0] -= 3600
        importstatus.clear_ratelimit()
        return True
    monkeypatch.setattr(cv, '_cv_wait', fake_wait)
    return waited


def comic(path):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('001.jpg', b'x' * 10)
    return str(path)


def ct_cache(config, rows):
    folder = os.path.join(config.CT_SETTINGSPATH, 'cache')
    os.makedirs(folder, exist_ok=True)
    con = sqlite3.connect(os.path.join(folder, 'comic_cache.db'))
    con.execute("CREATE TABLE Issues(timestamp DATE DEFAULT (datetime('now','localtime')), id TEXT NOT NULL, "
                "source TEXT NOT NULL, series_id TEXT, data BLOB, complete BOOL, PRIMARY KEY (id, source))")
    for issueid, complete, age in rows:
        when = str(datetime.datetime.today() - datetime.timedelta(days=age))
        con.execute("INSERT INTO Issues (timestamp, id, source, complete) VALUES (?, ?, 'comicvine', ?)", [when, issueid, complete])
    con.commit()
    con.close()


@pytest.mark.unit
def test_cached_issues_are_read_from_the_comictagger_cache(config):
    assert not cmtagmylar.cached('1')
    ct_cache(config, [('1', 1, 3), ('2', 0, 3), ('3', 1, 400)])
    assert cmtagmylar.cached('1')
    assert not cmtagmylar.cached('2')     # only part of the issue was cached
    assert not cmtagmylar.cached('3')     # ComicTagger drops it after a year
    assert not cmtagmylar.cached('4') and not cmtagmylar.cached(None)


@pytest.mark.unit
def test_tagging_waits_when_the_hour_is_used_up(config, waits, monkeypatch):
    monkeypatch.setattr(cmtagmylar, 'HOURLY_TAGS', 2)
    assert cmtagmylar.pace('1', '') and cmtagmylar.pace('2', '')
    assert waits == []
    assert cmtagmylar.pace('3', '')
    assert len(waits) == 1 and 3590 <= waits[0] <= 3600
    assert len(cmtagmylar._fetches) == 2


@pytest.mark.unit
def test_the_default_key_gets_half_the_pace(config, waits, monkeypatch):
    config.COMICVINE_API = None
    monkeypatch.setattr(cmtagmylar, 'HOURLY_TAGS_DEFAULT_KEY', 1)
    cmtagmylar.pace('1', '')
    cmtagmylar.pace('2', '')
    assert len(waits) == 1


@pytest.mark.unit
def test_cached_issues_dont_use_up_the_hour(config, waits, monkeypatch):
    monkeypatch.setattr(cmtagmylar, 'HOURLY_TAGS', 1)
    ct_cache(config, [('1', 1, 3), ('2', 1, 3)])
    for i in ('1', '2', '1', '3'):
        assert cmtagmylar.pace(i, '')
    assert waits == [] and len(cmtagmylar._fetches) == 1


@pytest.mark.unit
def test_tagging_waits_out_a_comicvine_back_off_first(config, waits):
    importstatus.set_ratelimit('HTTP 420', 'volume', 120, 1)
    assert cmtagmylar.pace('1', '')
    assert waits and 115 <= waits[0] <= 120


@pytest.mark.unit
def test_shutting_down_while_waiting_stops_the_tag(config, monkeypatch):
    monkeypatch.setattr(cv, '_cv_wait', lambda seconds: False)
    importstatus.set_ratelimit('HTTP 420', 'issue', 120, 1)
    assert not cmtagmylar.pace('1', '')


RATE_LIMITED = ({'status': 'fetch_data_failure'},
                'Error retrieving issue details. Save aborted. Comic Vine encountered a Network error. '
                'Rate Limit Error: Check your current API usage limit at https://comicvine.gamespot.com/api/')


@pytest.mark.unit
def test_a_rate_limited_file_is_tagged_again_after_the_wait(tmp_path, config, waits, monkeypatch):
    calls = []
    backoffs = []

    def fake_ct(args, module):
        calls.append(args)
        backoffs.append(importstatus.ratelimit_remaining())
        return RATE_LIMITED if len(calls) == 1 else ({'status': 'success'}, '')
    monkeypatch.setattr(cmtagmylar, 'run_comictagger', fake_ct)
    monkeypatch.setattr(cmtagmylar.comicinfo, 'keep_existing', lambda *a: True)
    src = comic(tmp_path / 'a.cbz')
    out = cmtagmylar.run(str(tmp_path), issueid='123', filename=src)
    assert out.endswith('a.cbz') and out != src
    assert len(calls) == 2 and waits == [cv.RATELIMIT_WAITS[0]]
    assert importstatus.ratelimit_remaining() == 0


@pytest.mark.unit
def test_a_rate_limit_that_never_clears_fails_the_file(tmp_path, config, waits, monkeypatch):
    calls = []
    monkeypatch.setattr(cmtagmylar, 'run_comictagger', lambda args, module: calls.append(1) or RATE_LIMITED)
    assert cmtagmylar.run(str(tmp_path), issueid='123', filename=comic(tmp_path / 'a.cbz')) == 'fail'
    assert len(calls) == len(cv.RATELIMIT_WAITS) + 1
    assert waits == cv.RATELIMIT_WAITS


@pytest.mark.unit
@pytest.mark.parametrize('out', ['No match for ID 123 was found.', 'Comic Vine encountered a Network error. 100: Invalid API Key'])
def test_other_failures_are_not_retried(tmp_path, config, waits, monkeypatch, out):
    calls = []
    monkeypatch.setattr(cmtagmylar, 'run_comictagger', lambda args, module: calls.append(1) or ({'status': 'fetch_data_failure'}, out))
    assert cmtagmylar.run(str(tmp_path), issueid='123', filename=comic(tmp_path / 'a.cbz')) == 'fail'
    assert len(calls) == 1 and waits == []


@pytest.mark.unit
def test_comicvine_107_is_a_rate_limit():
    assert cmtagmylar.RATE_LIMITED.search('Comic Vine encountered a Network error. 107: Rate limit exceeded.  Slow down cowboy.')
    assert cmtagmylar.RATE_LIMITED.search('Comic Vine encountered a Data error. ComicVine did not provide json')
    assert not cmtagmylar.RATE_LIMITED.search('Unable to read /comics/Batman 107 (2001).cbz')


@pytest.mark.unit
def test_the_imprint_is_passed_to_comictagger(config):
    args = cmtagmylar.tag_args('/x/a.cbz', '123', None, None, 'overwrite', 'Vertigo')
    assert json.loads(args[args.index('-m') + 1]) == {'imprint': 'Vertigo'}
    assert '-m' not in cmtagmylar.tag_args('/x/a.cbz', '123', None, None, 'overwrite')


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'DB_FILE', str(tmp_path / 'mylar.db'), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    for k, v in mylar.config._CONFIG_DEFINITIONS.items():
        monkeypatch.setattr(mylar.CONFIG, k, v[2], raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'DYNAMIC_UPDATE', 99, raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'OLDCONFIG_VERSION', None, raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    mylar.dbcheck()
    d = db.DBConnection()
    for comicid, publisher, imprint in (('1', 'DC Comics', 'Vertigo'), ('2', 'Marvel', None), ('3', 'Image', 'None')):
        d.action('INSERT INTO comics (ComicID, ComicName, ComicPublisher, PublisherImprint) VALUES (?, ?, ?, ?)',
                 [comicid, 'Series %s' % comicid, publisher, imprint])
        d.action("INSERT INTO issues (IssueID, ComicID, Issue_Number) VALUES (?, ?, '1')", ['10' + comicid, comicid])
    d.action("INSERT INTO annuals (IssueID, ComicID, Issue_Number) VALUES ('201', '1', '1')")
    return d


@pytest.mark.unit
def test_series_publisher_comes_from_the_imprint_listing(library):
    assert cmtagmylar.series_publisher('101') == ('DC Comics', 'Vertigo')
    assert cmtagmylar.series_publisher('201') == ('DC Comics', 'Vertigo')
    assert cmtagmylar.series_publisher('102') == (None, None)
    assert cmtagmylar.series_publisher('103') == (None, None)
    assert cmtagmylar.series_publisher('999') == (None, None)
    assert cmtagmylar.series_publisher(None) == (None, None)
