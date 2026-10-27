import types

import pytest

import mylar
from mylar import config, filechecker


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    c = types.SimpleNamespace(**{k: v[2] for k, v in config._CONFIG_DEFINITIONS.items()})
    c.IGNORE_SEARCH_WORDS = []
    monkeypatch.setattr(mylar, 'CONFIG', c, raising=False)


def parse(name):
    return filechecker.FileChecker(file=name).listFiles()


@pytest.mark.unit
@pytest.mark.parametrize('name,series,issue', [
    ('001 X-Men Annual 001 (1992) (Digital) (Shadowcat-Empire).cbz', 'X-Men Annual', '001'),
    ('002 Uncanny X-Men Annual 016 (1992) (Digital).cbz', 'Uncanny X-Men Annual', '016'),
    ('007- The Mighty Thor Vol.1989 #445 (March, 1992).cbz', 'The Mighty Thor', '445'),
    ('01 - BATTLE OF THE ATOM - X-Men - Battle of the Atom 01 (of 2) (2013) (Digital) (Zone-Empire).cbr', 'X-Men - Battle of the Atom', '01'),
    ('02 - BATTLE OF THE ATOM - All New X-Men 016 (2013) (Digital) (Zone-Empire).cbr', 'All New X-Men', '016'),
    ('10 - BATTLE OF THE ATOM - X-Men - Battle of the Atom 02 (of 2) (2013) (Digital) (Zone-Empire).cbr', 'X-Men - Battle of the Atom', '02'),
    ('05 - Aliens Omnibus v02 (2007) (digital).cbr', 'Aliens Omnibus', None),
    ('12 - Aliens Omnibus v03 (2008) (digital).cbr', 'Aliens Omnibus', None),
    ('7 - Justice League Vol. 2 015 (2013).cbz', 'Justice League', '015'),
])
def test_reading_order_prefix_is_ignored(name, series, issue):
    r = parse(name)
    assert r['series_name'] == series and r['issue_number'] == issue
    assert r['reading_order'] and r['reading_order']['reading_sequence'].lstrip('0')


@pytest.mark.unit
@pytest.mark.parametrize('name,series', [
    ('52 001 (2006).cbz', '52'),
    ('30 Days of Night 001 (2002).cbz', '30 Days of Night'),
    ('100 Bullets 050 (2004).cbz', '100 Bullets'),
    ('52 - Week Fifty-Two 052 (2007).cbz', '52 - Week Fifty-Two'),
])
def test_titles_starting_with_numbers_are_kept(name, series):
    assert parse(name)['series_name'] == series
