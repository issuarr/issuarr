"""GetComics' page cache folder is made when it's missing, instead of the download failing."""
import os

import pytest

import mylar
from mylar import getcomics


class Response(object):
    def iter_content(self, chunk_size=1024):
        yield b'<html></html>'


class Session(object):
    def get(self, *a, **kw):
        return Response()


@pytest.mark.unit
def test_loadsite_makes_the_cache_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', type('C', (), {'CACHE_DIR': str(tmp_path)})(), raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    gc = getcomics.GC.__new__(getcomics.GC)
    gc.session = Session()
    gc.headers = {}
    gc.cookie_receipt = lambda: None
    gc.loadsite('39390', 'https://getcomics.org/x')
    assert os.path.exists(os.path.join(str(tmp_path), 'html_cache', 'getcomics-39390.html'))
