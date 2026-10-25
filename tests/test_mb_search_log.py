"""The log says what each ComicVine series search was for, so an empty result can be explained."""
from xml.dom.minidom import parseString

import pytest

import mylar
from mylar import mb


@pytest.fixture
def logged(monkeypatch):
    lines = []
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'COMICVINE_API', 'key', raising=False)
    monkeypatch.setattr(mb, 'listLibrary', lambda: {})
    monkeypatch.setattr(mb, 'pullsearch', lambda *a, **k: parseString(
        '<r><number_of_total_results>0</number_of_total_results></r>'))
    monkeypatch.setattr(mb.logger, 'info', lambda msg, *a: lines.append(msg))
    return lines


@pytest.mark.unit
def test_name_search_logs_what_was_typed_and_the_words_sent(logged):
    mb.findComic('KISSmas Special', 'series', None)
    assert logged == ['[COMICVINE] Series search for "KISSmas Special" (words sent: KISSmas, Special): 0 result(s)']


@pytest.mark.unit
def test_link_lookup_logs_the_series_id(logged):
    mb.findComic('https://comicvine.gamespot.com/kissmas/4050-54999/', 'series', None, volumeid='54999')
    assert logged == ['[COMICVINE] Looked up series 4050-54999: 0 result(s)']
