"""Links to other GetComics posts aren't downloads.

2026-10-21: the Tales to Astonish Vol. 1 #1 - 101 post lists related posts, and one of them,
'Tales to Astonish Vol. 1 #1 - 101 (1959-1968) (2.1 GB) (#59 - 101)', looked like a download of its
own. Its only link was a post page, which went to JD2 as a mirror. JD2 crawled that page and every
Hulk post it links to, and filled the download folder with packs no one asked for.
"""
import types

import pytest
from bs4 import BeautifulSoup

import mylar
from mylar import ddlsources, getcomics
from mylar.queues import jd2

PAGE = '''<h3>Related Issues</h3><ul>
<li><a href="https://getcomics.info/marvel/the-incredible-hulk-vol-1-1-6-1962-1963/">The Incredible Hulk Vol. 1 #1 &#8211; 6 (1962-1963)</a></li>
<li><a href="https://getcomics.info/marvel/tales-to-astonish-vol-1-1-101/">Tales to Astonish Vol. 1 #1 &#8211; 101 (1959-1968) (2.1 GB) (#59 &#8211; 101)</a></li>
<li><a href="https://getcomics.info/marvel/tales-to-astonish-scans-1-58/">Tales to Astonish #1 &#8211; 58 (1959-1964) (Scans)</a></li>
<li><a href="https://getcomics.info/marvel/hulk-1-57-red-she-hulk-58-67-tpbs-2008-2013/">Hulk #1 &#8211; 57 + Red She-Hulk #58 &#8211; 67 + TPBs</a></li>
</ul>
<p style="text-align: center;"><div class="aio-pulse"><a href="https://getcomics.org/dls/pixel" title="PIXELDRAIN">PIXELDRAIN</a></div></p>'''

MAIN = 'https://getcomics.org/marvel/tales-to-astonish-vol-1-1-101/'


@pytest.fixture(autouse=True)
def cfg(monkeypatch, tmp_path):
    (tmp_path / 'html_cache').mkdir()
    (tmp_path / 'html_cache' / 'getcomics-10398.html').write_text(PAGE, encoding='utf-8')
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(
        CACHE_DIR=str(tmp_path), DDL_PRIORITY_ORDER='["main","pixeldrain","mega","mediafire"]', DDL_DISABLED_SOURCES='[]',
        DDL_MAIN_LARGE_LAST=True, DDL_MAIN_LARGE_MB=400), raising=False)
    monkeypatch.setattr(ddlsources, 'pixeldrain_fits', lambda b: True)


def gc():
    g = getcomics.GC.__new__(getcomics.GC)
    g.jd2 = object()
    return g


def info(issue):
    return [{'ComicName': 'Tales to Astonish', 'IssueNumber': issue, 'IssueID': '4182'}]


@pytest.mark.unit
@pytest.mark.parametrize('link, path', [
    ('https://getcomics.info/marvel/tales-to-astonish-vol-1-1-101/', '/marvel/tales-to-astonish-vol-1-1-101'),
    ('https://getcomics.org/marvel/tales-to-astonish-vol-1-1-101', '/marvel/tales-to-astonish-vol-1-1-101'),
    ('https://getcomics.org/dls/abc/def', None),
    ('https://getcomics.org/tag/hulk/', None),
    ('https://getcomics.org/', None),
    ('https://pixeldrain.com/u/1Gi72juH', None),
])
def test_post_path(link, path):
    assert getcomics.post_path(link) == path


@pytest.mark.unit
def test_a_related_post_is_not_a_download():
    assert gc()._single_item(BeautifulSoup(PAGE, 'html.parser'), info('1')) is None


@pytest.mark.unit
def test_linked_post_finds_another_post_for_the_same_issue():
    # the same post on the old domain is skipped; the Hulk posts aren't Tales to Astonish
    assert getcomics.linked_post('10398', info('12'), [MAIN]) == 'https://getcomics.info/marvel/tales-to-astonish-scans-1-58/'


@pytest.mark.unit
def test_linked_post_ignores_posts_that_dont_have_the_issue():
    assert getcomics.linked_post('10398', info('80'), [MAIN]) is None


@pytest.mark.unit
def test_linked_post_skips_posts_already_tried():
    assert getcomics.linked_post('10398', info('12'), [MAIN, 'https://getcomics.org/marvel/tales-to-astonish-scans-1-58/']) is None


@pytest.mark.unit
def test_jd2_is_never_given_a_post_page():
    links = {'https://getcomics.info/marvel/tales-to-astonish-vol-1-1-101/': 'HIGHEST', 'https://pixeldrain.com/u/x': 'HIGH'}
    assert jd2.resolve_links(links) == {'https://pixeldrain.com/u/x': 'HIGH'}
