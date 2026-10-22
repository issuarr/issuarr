"""A post whose only links are HD-Digital ones.

2026-10-20: 'Kill Your Darlings #4' and '#5' were found, then the download step crashed with
KeyError 'normal:pixeldrain': with 'prefer upscaled' off, a host's link was looked up only as
SD-Digital or unlabelled, and this post had neither.
"""
import os
import types

import pytest

import mylar
from mylar import ddlsources, getcomics

POST = '''<p style="text-align: center;"><strong>Kill Your Darlings #4 HD-Digital</strong><strong>Language</strong><strong>: English</strong><strong>Year</strong><strong>2023</strong><strong>Size</strong><strong>60 MB</strong></p>
<p style="text-align: center;"><div class="aio-pulse"><a href="https://getcomics.org/dls/main" title="Download Now">Download Now</a></div></p>
<p style="text-align: center;"><div class="aio-pulse"><a href="https://getcomics.org/dls/px" title="PIXELDRAIN">Pixeldrain</a></div></p>
<p style="text-align: center;"><div class="aio-pulse"><a href="https://getcomics.org/dls/mf" title="MEDIAFIRE">Mediafire</a></div></p>'''

INFO = [{'ComicName': 'Kill Your Darlings', 'IssueNumber': '4', 'IssueID': '1', 'ComicID': '100', 'comyear': '2023', 'pack': False}]


@pytest.mark.unit
@pytest.mark.parametrize('order,picked', [('["pixeldrain","main","mediafire"]', 'px'),
                                          ('["main","pixeldrain","mediafire"]', 'main')])
def test_an_hd_only_post_downloads_from_the_preferred_host(monkeypatch, tmp_path, order, picked):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(
        DDL_PRIORITY_ORDER=order, DDL_DISABLED_SOURCES='[]', DDL_MAIN_LARGE_LAST=False, DDL_MAIN_LARGE_MB=400,
        DDL_PREFER_UPSCALED=False, ENABLE_TORRENTS=False, CACHE_DIR=str(tmp_path)), raising=False)
    monkeypatch.setattr(ddlsources, 'pixeldrain_fits', lambda b: True)
    os.makedirs(tmp_path / 'html_cache', exist_ok=True)
    (tmp_path / 'html_cache' / 'getcomics-p1.html').write_text(POST, encoding='utf-8')
    (tmp_path / 'html_cache' / 'getcomics-p1').write_text('', encoding='utf-8')
    g = getcomics.GC.__new__(getcomics.GC)
    g.jd2, g.issueid, g.comicid, g.oneoff = None, '1', '100', False
    queued = []
    monkeypatch.setattr(g, '_queue_links', lambda links, *a: queued.append(links) or {'success': True})
    monkeypatch.setattr(getcomics.db, 'DBConnection', lambda: types.SimpleNamespace(action=lambda *a: None))
    g.parse_downloadresults('p1', 'https://getcomics.org/kill-your-darlings-4', INFO, None, None)
    assert queued and queued[0][0]['links'].endswith('/' + picked)
