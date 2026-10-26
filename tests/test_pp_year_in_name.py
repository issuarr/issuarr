"""A year that is part of a series' name ("Uncanny X-Men Annual 1999") isn't read as the issue number."""
import pytest

import mylar
from mylar import db, filechecker
from mylar.PostProcessor import year_in_name


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    monkeypatch.setattr(mylar.CONFIG, 'ANNUALS_ON', False, raising=False)
    monkeypatch.setattr(year_in_name.__globals__['logger'], 'fdebug', lambda *a, **k: None)
    d = db.DBConnection()
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, DynamicComicName TEXT, AlternateSearch TEXT)')
    d.action('CREATE TABLE issues (ComicID TEXT, Issue_Number TEXT)')
    d.action("INSERT INTO comics VALUES ('7199', 'Uncanny X-Men 1999', 'uncannyxmen1999', 'Uncanny X-Men Annual 1999'), "
             "('60462', 'X-Men ''95', 'xmen95', 'None'), ('3092', 'The Uncanny X-Men', 'uncannyxmen', 'None')")
    d.action("INSERT INTO issues VALUES ('7199', '1'), ('60462', '1'), ('3092', '1'), ('3092', '2')")
    return d


def alt_list(myDB):
    out = []
    for r in myDB.select("SELECT * FROM comics WHERE AlternateSearch != 'None'"):
        info = filechecker.FileChecker(AlternateSearch=r['AlternateSearch']).altcheck()
        out.append({'AS_Alt': info['AS_Alt'], 'AS_Tuple': info['AS_Tuple'], 'AS_DyComicName': r['DynamicComicName']})
    return out


@pytest.mark.unit
def test_a_year_named_series_takes_the_file_by_its_alternate_name(myDB):
    files = [{'series_name': 'Uncanny X-Men Annual', 'issue_number': '1999', 'comicfilename': 'a.cbr'}]
    year_in_name(myDB, files, alt_list(myDB))
    assert (files[0]['series_name'], files[0]['issue_number']) == ('Uncanny X-Men 1999', '1')


@pytest.mark.unit
def test_other_years_and_real_issue_numbers_are_left_alone(myDB):
    files = [{'series_name': 'Uncanny X-Men Annual', 'issue_number': '1997', 'comicfilename': 'b.cbr'},
             {'series_name': 'Uncanny X-Men', 'issue_number': '2', 'comicfilename': 'c.cbr'},
             {'series_name': 'X-Men', 'issue_number': '1995', 'comicfilename': 'd.cbr'}]
    year_in_name(myDB, files, alt_list(myDB))
    assert [(f['series_name'], f['issue_number']) for f in files] == [
        ('Uncanny X-Men Annual', '1997'), ('Uncanny X-Men', '2'), ('X-Men', '1995')]
