"""CBL import finds an annual kept with its series instead of adding its annual series again (#274)."""
import io
import json
import types

import pytest

import mylar
from mylar import cbl_catalog, db, importer, webserve

CBL = b'''<?xml version="1.0"?>
<ReadingList><Name>Sonic</Name><Books>
  <Book Series="Sonic the Hedgehog" Number="1" Volume="2018" Year="2018"><Database Name="cv" Series="110000" Issue="901" /></Book>
  <Book Series="Sonic the Hedgehog Annual 2024" Number="1" Volume="2024" Year="2024"><Database Name="cv" Series="160329" Issue="a24" /></Book>
</Books></ReadingList>'''


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'ANNUALS_ON', True, raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'AUTOWANT_ALL', False, raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'writeconfig', lambda **k: None, raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    d = db.DBConnection()
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT)')
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT)')
    d.action('CREATE TABLE annuals (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT, ReleaseComicID TEXT, ReleaseComicName TEXT, Deleted INT DEFAULT 0)')
    d.action("INSERT INTO comics VALUES ('110000', 'Sonic the Hedgehog', '2018')")
    d.action("INSERT INTO issues VALUES ('901', '110000', '1', 'Downloaded')")
    d.action("INSERT INTO annuals VALUES ('a24', '110000', '1', 'Downloaded', '160329', 'Sonic the Hedgehog Annual 2024', 0)")
    added, wanted = [], []
    monkeypatch.setattr(importer, 'importer_thread', lambda req: added.extend(req))
    monkeypatch.setattr(importer, 'issue_watcher_thread', lambda ids: wanted.extend(ids))
    return types.SimpleNamespace(db=d, added=added, wanted=wanted)


def upload():
    return types.SimpleNamespace(file=io.BytesIO(CBL), filename='sonic.cbl')


@pytest.mark.unit
def test_an_annual_series_kept_with_its_series_counts_as_in_the_library(env):
    assert cbl_catalog.watched_series(env.db, '160329') == '110000'
    assert cbl_catalog.watched_series(env.db, '110000') == '110000'
    assert cbl_catalog.watched_series(env.db, '999') is None
    mylar.CONFIG.ANNUALS_ON = False
    assert cbl_catalog.watched_series(env.db, '160329') is None


@pytest.mark.unit
def test_the_check_finds_the_annual_under_its_series(env):
    out = json.loads(webserve.WebInterface().checkCBLFile(upload()))
    assert out['status'] == 'success' and out['missing_volumes'] == 0 and out['missing_issues'] == 0
    annual = out['results'][1]
    assert annual[3] == 'Downloaded' and annual[4] == 'No action needed'
    assert 'comicDetails?ComicID=110000' in annual[1]


@pytest.mark.unit
def test_the_import_doesnt_add_the_annual_series(env):
    env.db.action("UPDATE annuals SET Status='Skipped'")
    out = json.loads(webserve.WebInterface().processCBLFile(upload()))
    assert out['status'] == 'success'
    assert [r for r in env.added if r] == []
    assert env.wanted == ['a24']
