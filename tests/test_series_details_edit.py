"""Series page > Details: each field can be edited in place, and edits to ComicVine fields are kept on refresh."""
import json
import types

import cherrypy
import pytest

from mylar import webserve


class FakeDB:
    def __init__(self, comic):
        self.comic = comic

    def selectone(self, sql, args):
        return types.SimpleNamespace(fetchone=lambda: self.comic)

    def upsert(self, table, values, ctrl):
        assert table == 'comics' and ctrl == {'ComicID': '7'}
        self.comic.update(values)


def series():
    return {'ComicID': '7', 'ComicName': 'Keeper', 'ComicPublisher': 'DC Comics', 'Corrected_Publisher': None,
            'PublisherImprint': None, 'Corrected_Imprint': None, 'ComicYear': '2016', 'Corrected_SeriesYear': None,
            'ComicVersion': None, 'Type': 'Print', 'Corrected_Type': None, 'AgeRating': None,
            'Description': 'From ComicVine.', 'DescriptionEdit': None}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(series())
    monkeypatch.setattr(webserve.db, 'DBConnection', lambda: fake)
    monkeypatch.setattr(webserve.logger, 'info', lambda *a, **k: None)
    monkeypatch.setattr(cherrypy.request, 'method', 'POST', raising=False)
    return fake


def edit(field, value):
    return json.loads(webserve.WebInterface().series_detail_edit('7', field, value))


@pytest.mark.unit
def test_publisher_edit_is_kept_and_blank_drops_it(db):
    r = edit('publisher', '  Vertigo ')
    assert r == {'ok': True, 'value': 'Vertigo', 'edited': True, 'note': None}
    assert db.comic['ComicPublisher'] == db.comic['Corrected_Publisher'] == 'Vertigo'
    r = edit('publisher', '')
    assert r['edited'] is False and r['value'] == 'Vertigo' and r['note']
    assert db.comic['Corrected_Publisher'] is None


@pytest.mark.unit
def test_empty_imprint_can_be_filled_in(db):
    assert edit('imprint', 'Black Label')['edited'] is True
    assert db.comic['PublisherImprint'] == db.comic['Corrected_Imprint'] == 'Black Label'
    edit('imprint', '')
    assert db.comic['PublisherImprint'] == 'None' and db.comic['Corrected_Imprint'] is None


@pytest.mark.unit
def test_year_needs_four_digits(db):
    assert edit('year', '16')['ok'] is False
    assert db.comic['ComicYear'] == '2016'
    assert edit('year', '2017')['edited'] is True
    assert db.comic['Corrected_SeriesYear'] == '2017'


@pytest.mark.unit
@pytest.mark.parametrize('typed,stored', [('2', 'v2'), ('V3', 'v3'), ('', None)])
def test_volume(db, typed, stored):
    edit('volume', typed)
    assert db.comic['ComicVersion'] == stored


@pytest.mark.unit
def test_bad_volume_is_refused(db):
    assert edit('volume', 'two')['ok'] is False


@pytest.mark.unit
def test_edition_and_back_to_comicvine(db):
    r = edit('edition', 'TPB')
    assert r['edited'] is True and r['value'] == 'TPB' and r['input'] == 'TPB'
    r = edit('edition', '')
    assert r['edited'] is False and r['value'] == 'Print' and db.comic['Corrected_Type'] is None
    assert edit('edition', 'Paperback')['ok'] is False


@pytest.mark.unit
def test_age_rating(db):
    assert edit('age_rating', 'Teen')['ok'] is False
    edit('age_rating', '12+')
    assert db.comic['AgeRating'] == '12+'
    edit('age_rating', '')
    assert db.comic['AgeRating'] is None


@pytest.mark.unit
def test_description_edit_and_clear(db):
    assert edit('description', 'Mine.') == {'ok': True, 'value': 'Mine.', 'edited': True, 'note': None}
    r = edit('description', '')
    assert r['value'] == 'From ComicVine.' and r['edited'] is False


@pytest.mark.unit
def test_unknown_field_and_get_are_refused(db, monkeypatch):
    assert edit('ComicName', 'x')['ok'] is False
    monkeypatch.setattr(cherrypy.request, 'method', 'GET', raising=False)
    with pytest.raises(cherrypy.HTTPError):
        edit('publisher', 'x')
