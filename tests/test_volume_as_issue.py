import os

import pytest

import mylar
from mylar import archives, filechecker, PostProcessor
from mylar.PostProcessor import volume_as_issue


def parse(monkeypatch, name):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "IGNORE_SEARCH_WORDS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)
    return filechecker.FileChecker(file=name, justparse=True, manual=True).parseit(path='/dummypath/', filename=name)


@pytest.mark.unit
@pytest.mark.parametrize("name,issue", [
    # each book of an omnibus is numbered only as a volume: the volume is the issue
    ("Aliens Omnibus v01 (2007) (digital) (The Magicians-Empire).cbr", "1"),
    ("Aliens Omnibus v04 (2008) (digital) (The Magicians-Empire).cbr", "4"),
    # the same volume on every issue of a series: the issue number stays
    ("Justice League v2 015 (2013) (Digital).cbz", "015"),
])
def test_the_volume_stands_in_only_when_there_is_no_issue_number(monkeypatch, name, issue):
    assert volume_as_issue(parse(monkeypatch, name)) == issue


@pytest.mark.unit
def test_no_volume_and_no_issue_leaves_nothing():
    assert volume_as_issue({'issue_number': None, 'series_volume': None}) is None
    assert volume_as_issue({'issue_number': None, 'series_volume': 'v00'}) is None
    assert volume_as_issue({'issue_number': '7', 'series_volume': 'v2'}) == '7'


@pytest.fixture
def config(monkeypatch, tmp_path):
    complete = tmp_path / 'complete'
    complete.mkdir()
    cfg = mylar.config.Config("./nothing")
    monkeypatch.setattr(mylar, "CONFIG", cfg)
    for key in archives.ROOT_SETTINGS:
        monkeypatch.setattr(cfg, key, None, raising=False)
    monkeypatch.setattr(cfg, 'FILE_OPTS', 'move', raising=False)
    monkeypatch.setattr(cfg, 'JD2_LOCAL_DIR', str(complete), raising=False)
    return complete


@pytest.mark.unit
def test_an_emptied_download_folder_is_removed(config):
    folder = config / 'Aliens Omnibus v01 (2007) (digital) (The Magicians-Empire)'
    folder.mkdir()
    assert archives.drop_empty_source(str(folder)) is True
    assert not folder.exists()


@pytest.mark.unit
def test_a_folder_with_something_left_stays(config):
    folder = config / 'Aliens Omnibus v02 (2007)'
    folder.mkdir()
    (folder / 'Aliens Omnibus v02 (2007).cbr').write_bytes(b'x')
    assert archives.drop_empty_source(str(folder)) is False
    assert folder.exists()


@pytest.mark.unit
def test_a_folder_a_setting_points_at_stays_even_empty(config, monkeypatch, tmp_path):
    assert archives.drop_empty_source(str(config)) is False
    assert config.exists()
    # nor a folder above one
    monkeypatch.setattr(mylar.CONFIG, 'JD2_LOCAL_DIR', str(tmp_path / 'outer' / 'inner'), raising=False)
    (tmp_path / 'outer').mkdir()
    assert archives.drop_empty_source(str(tmp_path / 'outer')) is False


@pytest.mark.unit
def test_copying_leaves_folders_alone(config, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'FILE_OPTS', 'copy', raising=False)
    folder = config / 'empty'
    folder.mkdir()
    assert archives.drop_empty_source(str(folder)) is False
    assert folder.exists()


@pytest.mark.unit
def test_a_manual_run_tidies_its_folder_when_done(config, monkeypatch):
    folder = config / 'Issuarr - Aliens Omnibus v03'
    folder.mkdir()
    monkeypatch.setattr(mylar.CONFIG, 'CHECK_FOLDER', None, raising=False)
    pp = PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)
    pp.nzb_folder, pp.nzb_name = str(folder), 'Manual Run'
    monkeypatch.setattr(pp, '_process_main', lambda: {'mode': 'stop'}, raising=False)
    monkeypatch.setattr(pp, '_clear_pack', lambda: None, raising=False)
    pp._locked_process()
    assert not folder.exists()
