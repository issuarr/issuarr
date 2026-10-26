import types

import mylar
from mylar.downloaders import jdownloader2


def _config(monkeypatch, **kw):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(**kw), raising=False)


def test_issuarr_path_wins_when_jd2_sees_the_folder_elsewhere(monkeypatch):
    _config(monkeypatch, JD2_DEST_DIR='/output/complete', JD2_LOCAL_DIR='/downloads/complete')
    assert jdownloader2.local_folder() == '/downloads/complete'


def test_jd2_path_is_used_when_both_see_the_same_path(monkeypatch):
    for empty in (None, '', 'None'):
        _config(monkeypatch, JD2_DEST_DIR='/downloads/jd2', JD2_LOCAL_DIR=empty)
        assert jdownloader2.local_folder() == '/downloads/jd2'


def test_no_folder_at_all(monkeypatch):
    _config(monkeypatch, JD2_DEST_DIR=None)
    assert jdownloader2.local_folder() is None


def test_jd2_is_still_told_its_own_path(monkeypatch, tmp_path):
    local = tmp_path / 'complete'
    _config(monkeypatch, JD2_URL='http://jd2:3128', JD2_DEST_DIR='/output/complete', JD2_LOCAL_DIR=str(local))
    client = jdownloader2.JDownloader2()
    assert client.destination_folder == '/output/complete'
    assert local.is_dir()
