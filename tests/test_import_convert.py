"""Import & scan converts a moved .cbr to .cbz like filing a download does."""
import types
import zipfile

import pytest

import mylar
from mylar import moveit, webp


@pytest.fixture
def cbr(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(webp, '_relocate', lambda old, new: None)
    queued = []
    monkeypatch.setattr(webp, 'after_import', lambda path, issueyear=None: queued.append(path))
    path = tmp_path / 'Series 001.cbr'
    with zipfile.ZipFile(path, 'w') as z:   # a zip named .cbr: renamed, no unrar needed
        z.writestr('001.jpg', b'page')
    return path, queued


def config(monkeypatch, **kw):
    opts = dict(ENABLE_META=False, CBR2CBZ_ONLY=False)
    opts.update(kw)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(**opts), raising=False)


def test_cbr_becomes_cbz_when_cbr_to_cbz_is_on(monkeypatch, cbr):
    path, queued = cbr
    config(monkeypatch, CBR2CBZ_ONLY=True)
    out = moveit.convert(str(path))
    assert out.endswith('Series 001.cbz')
    assert not path.exists()
    assert queued == [out]


def test_cbr_is_left_alone_when_conversion_is_off(monkeypatch, cbr):
    path, queued = cbr
    config(monkeypatch)
    assert moveit.convert(str(path)) == str(path)
    assert path.exists()
    assert queued == [str(path)]
