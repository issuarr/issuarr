"""Auto-add finds a file's series by ComicVine's names and aliases, and single-issue volumes for files with no number."""
import types

import pytest

import mylar
from mylar import autoadd, config

VOLUMES = [
    {'id': 60462, 'name': "X-Men '95", 'start_year': '1995', 'count_of_issues': 1, 'aliases': 'X-Men Annual 1995\r\nX-Men Annual \'95\r\nX-Men 1995'},
    {'id': 60465, 'name': 'X-Men 2000', 'start_year': '2000', 'count_of_issues': 1, 'aliases': 'X-Men Annual 2000'},
    {'id': 10748, 'name': 'X-Men Annual', 'start_year': '1992', 'count_of_issues': 3, 'aliases': None},
    {'id': 27374, 'name': 'Silver Surfer: The Enslavers', 'start_year': '1990', 'count_of_issues': 1, 'aliases': None},
    {'id': 27088, 'name': 'The Silver Surfer: Inner Demons', 'start_year': '1998', 'count_of_issues': 1, 'aliases': None},
    {'id': 119305, 'name': 'Silver Surfer Epic Collection: Inner Demons', 'start_year': '2019', 'count_of_issues': 1, 'aliases': None},
    {'id': 32126, 'name': 'X-Men Ashcan', 'start_year': '1994', 'count_of_issues': 1, 'aliases': None},
    {'id': 22687, 'name': 'X-Men Ashcan', 'start_year': '1994', 'count_of_issues': 1, 'aliases': None},
    {'id': 26316, 'name': "X-Men / Dr. Doom '98", 'start_year': '1998', 'count_of_issues': 1, 'aliases': 'X-Men / Dr. Doom 1998\r\nX-Men / Dr. Doom Annual 1998'},
]


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    c = types.SimpleNamespace(**{k: v[2] for k, v in config._CONFIG_DEFINITIONS.items()})
    c.IGNORE_SEARCH_WORDS = []
    monkeypatch.setattr(mylar, 'CONFIG', c, raising=False)
    asked = []

    def cv(resource, params):
        asked.append((resource, params.get('query') or params.get('filter')))
        return VOLUMES if resource == 'search' else []
    monkeypatch.setattr(autoadd, '_cv', cv)
    return asked


def find(name):
    info = autoadd._parse('/downloads/' + name)
    return autoadd._find_volume(info['series'], info['issue'], info['year'], None, info.get('name_year'))


@pytest.mark.unit
@pytest.mark.parametrize('name,volid', [
    ('X-Men Annual 1995 (1995) (digital) (Minutemen-Bluntman).cbr', '60462'),   # by its alias
    ('X-Men Annual 2000 (scan).cbr', '60465'),
    ('Silver Surfer Enslavers (1990) (Digital) (Shadowcat-Empire).cbz', '27374'),   # no number: the 1990 one-shot
    ('Silver Surfer Inner Demons (1998).cbr', '27088'),   # not the 2019 collection
    ('X-Men - Dr. Doom Annual (1998) (Digital) (Shadowcat-Empire).cbz', '26316'),
    ('X-Men - Ashcan (1994) (c2c).cbr', None),   # two volumes fit: don't guess
])
def test_volume_is_found_by_name_alias_and_year(name, volid):
    assert find(name) == volid


@pytest.mark.unit
def test_an_annual_year_asks_comicvine_for_the_name_with_the_year(cfg):
    find('X-Men Annual 2000 (scan).cbr')
    assert cfg[0] == ('search', 'X-Men Annual 2000')
