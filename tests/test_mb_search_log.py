"""The log says what each ComicVine series search was for, so an empty result can be explained."""
from xml.dom.minidom import parseString

import pytest

import mylar
from mylar import mb

PULLSEARCH = mb.pullsearch


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


SEARCH = '''<response><error>OK</error><number_of_total_results>2</number_of_total_results><results>
<volume><aliases>X-Men Annual 1995
X-Men Annual '95</aliases><count_of_issues>1</count_of_issues><first_issue><id>1</id><name>a</name><issue_number>1</issue_number></first_issue>
<id>60462</id><image><thumb_url>t.jpg</thumb_url></image><name>X-Men '95</name><publisher/>
<site_detail_url>https://comicvine.gamespot.com/x-men-annual-95/4050-60462/</site_detail_url><start_year>1995</start_year><resource_type>volume</resource_type></volume>
<series><id>7</id><name>X-Men '97</name><resource_type>series</resource_type></series>
</results></response>'''


@pytest.mark.unit
def test_best_match_search_asks_comicvines_search_for_comic_series_only(logged, monkeypatch):
    asked = []
    monkeypatch.setattr(mb, 'pullsearch', PULLSEARCH)
    monkeypatch.setattr(mb.logger, 'fdebug', lambda *a, **k: None)
    monkeypatch.setattr(mylar, 'CVURL', 'https://comicvine.gamespot.com/api/', raising=False)
    volumes = '<response><results><volume><id>60462</id><publisher><id>31</id><name>Marvel</name></publisher></volume></results></response>'
    monkeypatch.setattr(mb.cv, 'cv_request', lambda url: asked.append(url) or type('R', (), {'content': (SEARCH if '/search/' in url else volumes).encode()})())
    monkeypatch.setattr(mb, 'ignored_publisher_check', lambda pub: False)
    monkeypatch.setattr(mb.cv, 'get_imprint_volume_and_booktype', lambda series, year, pub, *a: {
        'Type': 'Print', 'ComicDescription': 'None', 'ComicVersion': 'None', 'ComicPublisher': pub, 'PublisherImprint': 'None'})
    found = mb.findComic('X-Men Annual 1995', 'series', None, page=1, pageSize=20, relevance=True)
    assert '/api/search/?' in asked[0] and '&resources=volume&' in asked[0] and '&limit=20&page=1' in asked[0]
    # the search leaves publishers empty; one volumes call fills them in
    assert len(asked) == 2 and '/api/volumes/?' in asked[1] and 'filter=id:60462&' in asked[1]
    assert found[0]['publisher'] == 'Marvel'
    assert '&query=X%20Men%20Annual%201995&' in asked[0] and 'aliases' in asked[0]
    # the TV show ComicVine calls a "series" is left out
    assert [(x['comicid'], x['name'], x['aliases']) for x in found] == [('60462', "X-Men '95", ['X-Men Annual 1995', "X-Men Annual '95"])]
