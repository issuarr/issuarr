"""Downloads > Needs attention: files filing couldn't place, and what's in the review folder."""
import datetime
import os
import threading
import types

import pytest

import mylar
from mylar import attention, db


@pytest.fixture
def env(monkeypatch, tmp_path):
    review = tmp_path / 'mylar-review'
    review.mkdir()
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    for k, v in dict(IGNORE_SEARCH_WORDS=[], CUSTOM_ISSUE_EXCEPTIONS=[], ANNUALS_ON=False, FOLDER_SCAN_LOG_VERBOSE=False,
                     ARCHIVE_REVIEW_DIR=str(review), ATTENTION_TRASH_DAYS=14, ZERO_LEVEL_N=None, ZERO_LEVEL=False).items():
        monkeypatch.setattr(mylar.CONFIG, k, v, raising=False)
    for name in ('fdebug', 'info', 'warn'):
        monkeypatch.setattr(attention.logger, name, lambda *a, **k: None)
    monkeypatch.setattr(attention, '_COUNT', [0.0, 0])
    monkeypatch.setattr(attention, '_COMICS', [0.0, []])
    monkeypatch.setattr(attention, 'JOBS', {})
    d = db.DBConnection()
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT, ComicVersion TEXT, Total INTEGER, Type TEXT, Corrected_Type TEXT, AlternateSearch TEXT)')
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Status TEXT, IssueDate TEXT, ReleaseDate TEXT)')
    d.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicVersion, Total) VALUES ('85120', 'Marvel Universe Guardians of the Galaxy', '2015', NULL, 23), "
             "('94801', 'Great Lakes Avengers', '2016', NULL, 7)")
    d.action("INSERT INTO issues VALUES ('547001', '85120', '3', 'Snatched', '2016-02-01', NULL), "
             "('562595', '94801', '2', 'Snatched', '2017-01-01', NULL)")
    return types.SimpleNamespace(root=tmp_path, review=review, db=d)


def touch(path, data=b'x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return str(path)


@pytest.mark.unit
def test_the_most_telling_reason_wins():
    assert attention.pick({'series', 'volume'}) == 'volume'
    assert attention.pick({'year', 'issue'}) == 'year'
    assert attention.pick(set()) == 'series'


@pytest.mark.unit
def test_a_recorded_reject_is_listed_with_its_reason_and_closest_match(env):
    p = touch(env.root / 'dl' / 'Marvel Universe Guardians of the Galaxy v2 003 (2016).cbr')
    attention.record(p, 'volume', 'The file says v2; Marvel Universe Guardians of the Galaxy has no volume set.', '85120')
    [item] = attention.items()
    assert item['reason'] == 'volume' and item['detail'].startswith('The file says v2')
    assert item['parsed']['series'] == 'Marvel Universe Guardians of the Galaxy' and item['parsed']['issue'] == '003'
    best = item['matches'][0]
    assert (best['name'], best['issueid'], best['number']) == ('Marvel Universe Guardians of the Galaxy', '547001', '3')
    assert best['agree']['series'] and best['agree']['issue'] and best['agree']['volume'] is False
    assert attention.count() == 1


@pytest.mark.unit
def test_everything_in_the_review_folder_is_listed(env):
    touch(env.review / 'Jungle Action' / 'Great Lakes Avengers 002 (2017).cbz')
    touch(env.review / 'notes.txt')
    [item] = attention.items()
    assert item['reason'] == 'unclaimed' and item['in_review'] is True
    assert item['matches'][0]['issueid'] == '562595'


@pytest.mark.unit
def test_a_moved_file_keeps_its_reason_and_a_gone_file_drops_off(env):
    old = touch(env.root / 'dl' / 'Foo 001 (2020).cbr')
    attention.record(old, 'year', 'The file says 2020.')
    new = str(env.review / 'Foo 001 (2020).cbr')
    os.replace(old, new)
    attention.moved(old, new)
    assert [(i['path'], i['reason']) for i in attention.items()] == [(new, 'year')]
    os.remove(new)
    assert attention.items() == []
    assert env.db.select('SELECT * FROM attention') == []


@pytest.mark.unit
def test_an_ignored_file_stays_hidden_until_it_changes(env):
    p = touch(env.review / 'Foo 001 (2020).cbr')
    attention.ignore(p)
    assert attention.items() == []
    touch(p, b'a bigger file now')
    assert len(attention.items()) == 1


@pytest.mark.unit
def test_trash_moves_the_file_into_todays_folder_and_old_days_are_purged(env):
    p = touch(env.review / 'Foo 001 (2020).cbr')
    out = attention.trash(p)
    assert out['ok'] and 'after 14 days' in out['note']
    today = os.path.join(attention.trash_dir(), datetime.date.today().isoformat())
    assert os.listdir(today) == ['Foo 001 (2020).cbr'] and not os.path.exists(p)
    old = os.path.join(attention.trash_dir(), (datetime.date.today() - datetime.timedelta(days=20)).isoformat())
    touch(os.path.join(old, 'gone.cbr'))
    assert attention.purge_trash() == 1 and not os.path.exists(old) and os.path.isdir(today)


@pytest.mark.unit
def test_only_files_on_the_page_can_be_acted_on(env):
    outside = touch(env.root / 'library' / 'Keep Me 001 (2020).cbz')
    assert attention.trash(outside)['ok'] is False and os.path.exists(outside)
    assert attention.file_as(outside, '94801', '562595')['ok'] is False


@pytest.mark.unit
def test_file_as_refuses_an_issue_not_on_that_series(env):
    p = touch(env.review / 'Great Lakes Avengers 002 (2017).cbz')
    assert attention.file_as(p, '85120', '562595') == {'ok': False, 'note': 'That issue isn\'t on your watchlist.'}


@pytest.mark.unit
def test_file_as_hands_filing_the_users_pick_as_a_forced_match(env, monkeypatch):
    p = touch(env.review / 'Great Lakes Avengers 002 (2017).cbz')
    seen = []

    class FakePP(object):
        def __init__(self, nzb_name, folder, queue=None):
            seen.append((nzb_name, folder))

        def nzb_or_oneoff_pp(self, manual=None):
            seen.append(manual)
            os.replace(p, str(env.root / 'library.cbz'))           # filed: moved into the library
            db.DBConnection().action("UPDATE issues SET Status='Downloaded' WHERE IssueID='562595'")

    from mylar import PostProcessor
    monkeypatch.setattr(PostProcessor, 'PostProcessor', FakePP)
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args, **k: types.SimpleNamespace(start=lambda: target(*args)))
    out = attention.file_as(p, '94801', '562595')
    assert out == {'ok': True, 'note': "Filing as Great Lakes Avengers #2. It starts as soon as the filing that's running now finishes."}
    assert seen[0] == ('Manual Run', str(env.review))
    [entry] = seen[1]
    assert entry['ComicLocation'] == p and entry['IssueID'] == '562595' and entry['ForcedMatch'] is True
    assert attention.JOBS[p] == {'state': 'filed', 'note': 'Filed as Great Lakes Avengers #2'}
    assert attention.items() == []


@pytest.mark.unit
def test_filing_that_doesnt_finish_says_so(env, monkeypatch):
    p = touch(env.review / 'Great Lakes Avengers 002 (2017).cbz')

    class FakePP(object):
        def __init__(self, *a, **k):
            pass

        def nzb_or_oneoff_pp(self, manual=None):
            pass

    from mylar import PostProcessor
    monkeypatch.setattr(PostProcessor, 'PostProcessor', FakePP)
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args, **k: types.SimpleNamespace(start=lambda: target(*args)))
    attention.file_as(p, '94801', '562595')
    assert attention.JOBS[p]['state'] == 'failed'
    assert attention.items()[0]['job']['state'] == 'failed'


@pytest.mark.unit
def test_search_finds_watchlist_series_by_part_of_the_name(env):
    assert [s['comicid'] for s in attention.search('guardians')] == ['85120']
    assert attention.search('') == []


@pytest.mark.unit
def test_filing_records_only_the_files_it_left_unplaced(env, monkeypatch):
    from mylar import PostProcessor
    recorded = []
    monkeypatch.setattr(attention, 'record', lambda path, reason, detail='', comicid=None: recorded.append((os.path.basename(path), reason, detail, comicid)))
    a = touch(env.root / 'dl' / 'Marvel Universe Guardians of the Galaxy v2 003 (2016).cbr')
    b = touch(env.root / 'dl' / 'Marvel Universe Guardians of the Galaxy 001 (2015).cbr')
    pp = PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)
    pp.comicid = None
    manual = []
    for path in (a, b):
        pp._att_start({'comiclocation': os.path.dirname(path), 'sub': None, 'comicfilename': os.path.basename(path)}, (len(manual), 0, 0))
        if path == a:
            pp._att_why('series')
            pp._att_why('volume', 'The file says v2; it has no volume set.', '85120')
        else:
            manual.append({'ComicLocation': path})     # this one was placed
    pp._att_settle((len(manual), 0, 0))
    assert recorded == [('Marvel Universe Guardians of the Galaxy v2 003 (2016).cbr', 'volume', 'The file says v2; it has no volume set.', '85120')]


@pytest.mark.unit
def test_series_with_the_same_name_are_told_apart_by_the_issues_year(env):
    env.db.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicVersion, Total) VALUES ('1001', 'X-Factor', '1986', NULL, 259), ('1002', 'X-Factor', '2020', NULL, 10), "
                  "('1003', 'Battle Scars', '2012', NULL, 6)")
    env.db.action("INSERT INTO issues VALUES ('a3', '1001', '3', 'Downloaded', '1986-04-01', NULL), "
                  "('b3', '1002', '3', 'Wanted', '2020-09-01', NULL), ('c3', '1003', '3', 'Wanted', '2012-03-01', NULL)")
    out = attention.suggest({'series': 'X-Factor', 'issue': '003', 'year': '2020', 'volume': None})
    assert [(m['comicid'], m['agree']['year']) for m in out] == [('1002', True), ('1001', False)]
    assert attention.suggest({'series': 'Untitled scan', 'issue': '0003', 'year': None, 'volume': None}) == []


@pytest.mark.unit
def test_search_puts_the_exact_name_first(env):
    env.db.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicVersion, Total) VALUES ('1001', 'X-Factor', '1986', NULL, 259), ('2001', 'All-New X-Factor', '2014', NULL, 20)")
    assert [s['name'] for s in attention.search('x-factor')][:2] == ['X-Factor', 'All-New X-Factor']


def cbz_with_cover(path):
    import io, zipfile
    from PIL import Image
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, 'w') as z:
        for n, colour in ((1, (200, 30, 30)), (2, (240, 240, 240))):
            b = io.BytesIO()
            Image.new('RGB', (400, 600), colour).save(b, 'JPEG')
            z.writestr('Great Lakes Avengers 002-%03d.jpg' % n, b.getvalue())
    return str(path)


@pytest.mark.unit
def test_the_files_front_cover_is_extracted_and_cached(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root / 'cache'), raising=False)
    p = cbz_with_cover(env.review / 'Great Lakes Avengers 002 (2017).cbz')
    out = attention.file_cover(p)
    from PIL import Image
    with Image.open(out) as im:
        assert im.format == 'JPEG' and im.getpixel((10, 10))[0] > 150     # the red first page, not the white second
    assert attention.file_cover(p) == out
    assert attention.file_cover(str(env.root / 'library' / 'x.cbz')) is None


@pytest.mark.unit
def test_the_issue_cover_comes_from_comicvine_once(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root / 'cache'), raising=False)
    env.db.action("ALTER TABLE issues ADD COLUMN ImageURL TEXT")
    env.db.action("ALTER TABLE issues ADD COLUMN ImageURL_ALT TEXT")
    env.db.action("UPDATE issues SET ImageURL='https://comicvine.gamespot.com/a/uploads/scale_small/gla2.jpg' WHERE IssueID='562595'")
    calls = []
    import requests

    def get(url, **kw):
        calls.append(url)
        return types.SimpleNamespace(content=b'\xff\xd8jpeg', headers={'Content-Type': 'image/jpeg'}, raise_for_status=lambda: None)
    monkeypatch.setattr(requests, 'get', get)
    out = attention.issue_cover('562595')
    assert open(out, 'rb').read() == b'\xff\xd8jpeg'
    assert attention.issue_cover('562595') == out and len(calls) == 1
    assert attention.issue_cover('547001') is None                   # no image on record


@pytest.mark.unit
def test_a_page_that_isnt_an_image_is_not_kept_as_a_cover(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root / 'cache'), raising=False)
    env.db.action("ALTER TABLE issues ADD COLUMN ImageURL TEXT")
    env.db.action("ALTER TABLE issues ADD COLUMN ImageURL_ALT TEXT")
    env.db.action("UPDATE issues SET ImageURL='https://comicvine.gamespot.com/x.jpg' WHERE IssueID='562595'")
    import requests
    monkeypatch.setattr(requests, 'get', lambda url, **kw: types.SimpleNamespace(content=b'<html>', headers={'Content-Type': 'text/html'}, raise_for_status=lambda: None))
    assert attention.issue_cover('562595') is None


@pytest.mark.unit
def test_quick_bounds_never_drop_a_close_name(monkeypatch):
    # the length and shared-letter bounds must keep every series the full comparison would keep
    import collections
    import difflib
    names = ['X-Factor', 'All-New X-Factor', 'X-Force', 'Uncanny X-Men', 'X-Men', 'Batman', 'Batman Beyond',
             'Spider-Man', 'Superior Spider-Man', 'Spider-Woman', 'Powers', 'Power Pack', 'Hetalia Axis Powers',
             'Supergirl', 'Supergirl Being Super', 'Ragnarok', 'Jungle Action', 'Great Lakes Avengers']
    rows = [{'ComicID': str(i), 'ComicName': n, 'norm': attention._norm(n), 'names': [(attention._norm(n), collections.Counter(attention._norm(n)))]}
            for i, n in enumerate(names)]
    monkeypatch.setattr(attention, '_watchlist', lambda: rows)
    attention._NAMED.clear()
    for want in ['x factor', 'xfactor', 'x men', 'spiderman', 'spider man', 'power', 'supergirl', 'batman beyon', 'ragnarok']:
        brute = sorted(r['ComicID'] for r in rows if difflib.SequenceMatcher(None, want, r['norm']).ratio() >= 0.75)
        assert sorted(c['ComicID'] for s, c in attention._named(want)) == brute, want


@pytest.mark.unit
def test_a_cover_request_gives_up_with_busy_when_every_slot_is_taken(env, monkeypatch):
    # cover requests must not pile up on the web server's few threads
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root / 'cache'), raising=False)
    monkeypatch.setattr(attention, 'COVER_WAIT', 0.05)
    p = cbz_with_cover(env.review / 'Great Lakes Avengers 002 (2017).cbz')
    taken = [attention.COVER_SLOTS.acquire(timeout=0) for _ in range(5)]
    try:
        assert attention.file_cover(p) == attention.BUSY
    finally:
        for got in taken:
            if got:
                attention.COVER_SLOTS.release()
    assert attention.file_cover(p) not in (None, attention.BUSY)


@pytest.mark.unit
def test_a_file_without_a_cover_is_only_opened_once(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root / 'cache'), raising=False)
    p = env.review / 'Broken 001 (2020).cbz'
    p.write_bytes(b'not a zip')
    from mylar import getimage
    calls = []
    monkeypatch.setattr(getimage, 'extract_image', lambda *a, **k: calls.append(a) or None)
    assert attention.file_cover(str(p)) is None
    assert attention.file_cover(str(p)) is None and len(calls) == 1


@pytest.mark.unit
def test_a_failed_comicvine_cover_is_not_fetched_again_straight_away(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root / 'cache'), raising=False)
    env.db.action("ALTER TABLE issues ADD COLUMN ImageURL TEXT")
    env.db.action("ALTER TABLE issues ADD COLUMN ImageURL_ALT TEXT")
    env.db.action("UPDATE issues SET ImageURL='https://comicvine.gamespot.com/x.jpg' WHERE IssueID='562595'")
    import requests
    calls = []

    def get(url, **kw):
        calls.append(url)
        raise requests.exceptions.ConnectTimeout('slow')
    monkeypatch.setattr(requests, 'get', get)
    assert attention.issue_cover('562595') is None
    assert attention.issue_cover('562595') is None and len(calls) == 1


@pytest.mark.unit
def test_the_cover_endpoint_says_busy_with_a_503(monkeypatch):
    import cherrypy
    from mylar.webserve import WebInterface
    monkeypatch.setattr(attention, 'file_cover', lambda path: attention.BUSY)
    with pytest.raises(cherrypy.HTTPError) as e:
        WebInterface().attention_cover('/x.cbz', v='1', r='2')
    assert e.value.status == 503


def _no_thread(monkeypatch):
    started = []
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args=(), **k: types.SimpleNamespace(start=lambda: started.append((target, args))))
    return started


@pytest.mark.unit
def test_a_file_as_choice_survives_a_restart(env, monkeypatch):
    p = touch(env.review / 'Great Lakes Avengers 002 (2017).cbz')
    started = _no_thread(monkeypatch)
    assert attention.file_as(p, '94801', '562595')['ok'] is True
    assert attention.JOBS[p]['state'] == 'waiting'
    row = env.db.selectone('SELECT status, pick FROM attention WHERE path=?', [p]).fetchone()
    assert (row['status'], row['pick']) == ('queued', '94801|562595')
    # filing turning the file down again doesn't drop the user's choice
    attention.record(p, 'series')
    assert env.db.selectone('SELECT status FROM attention WHERE path=?', [p]).fetchone()['status'] == 'queued'
    # restart: jobs in memory are gone, the choice is picked up again
    attention.JOBS.clear()
    assert [i['job'] for i in attention.items()] == [{'state': 'waiting', 'note': 'Waiting to file'}]
    del started[:]
    assert attention.resume_picks() == 1
    assert attention.JOBS[p]['note'] == 'Waiting to file as Great Lakes Avengers #2'
    assert len(started) == 1


@pytest.mark.unit
def test_a_choice_that_fails_goes_back_to_open(env, monkeypatch):
    p = touch(env.review / 'Great Lakes Avengers 002 (2017).cbz')

    class FakePP(object):
        def __init__(self, *a, **k):
            pass

        def nzb_or_oneoff_pp(self, manual=None):
            pass   # nothing filed

    from mylar import PostProcessor
    monkeypatch.setattr(PostProcessor, 'PostProcessor', FakePP)
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args, **k: types.SimpleNamespace(start=lambda: target(*args)))
    attention.file_as(p, '94801', '562595')
    assert attention.JOBS[p]['state'] == 'failed'
    row = env.db.selectone('SELECT status, pick FROM attention WHERE path=?', [p]).fetchone()
    assert (row['status'], row['pick']) == ('open', None)


@pytest.mark.unit
def test_a_file_already_moved_by_hand_just_leaves_the_list(env):
    p = touch(env.root / 'downloads' / 'Some Comic 001 (2020).cbz')
    attention.record(p, 'series')
    os.remove(p)
    out = attention.trash(p)
    assert out['ok'] is True and out['gone'] is True
    assert env.db.selectone('SELECT path FROM attention WHERE path=?', [p]).fetchone() is None


@pytest.mark.unit
def test_refile_folders_groups_review_runs_it_last_and_skips_nested(env):
    review = str(env.review)
    paths = [os.path.join(review, 'a.cbz'), os.path.join(review, 'sub', 'b.cbz'),
             '/dl/Pack (2003)/x.cbz', '/dl/Pack (2003)/Annuals/y.cbz', '/dl/Other/z.cbz', '/dl/Pack (2003)/Annuals/w.cbz']
    assert attention.refile_folders(paths) == ['/dl/Other', '/dl/Pack (2003)', review]


@pytest.mark.unit
def test_try_filing_again_runs_filing_over_each_folder_after_new_downloads(env, monkeypatch):
    a = touch(env.review / 'Great Lakes Avengers 002 (2017).cbz')
    b = touch(env.root / 'dl' / 'Pack' / 'Other 001 (2001).cbz')
    attention.record(b, 'year')
    ran, waits = [], []
    sizes = [2, 1, 0]
    monkeypatch.setattr(mylar, 'PP_QUEUE', types.SimpleNamespace(qsize=lambda: sizes.pop(0) if sizes else 0), raising=False)
    monkeypatch.setattr(attention.time, 'sleep', waits.append)

    class FakePP(object):
        def __init__(self, name, folder, queue=None):
            self.folder = folder
            ran.append((name, folder))

        def Process(self):
            if self.folder == str(env.review):
                os.remove(a)   # filed

    from mylar import PostProcessor
    monkeypatch.setattr(PostProcessor, 'PostProcessor', FakePP)
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args=(), **k: types.SimpleNamespace(start=lambda: target(*args)))
    out = attention.refile_all()
    assert out['ok'] is True
    assert ran == [('Manual Run', str(env.root / 'dl' / 'Pack')), ('Manual Run', str(env.review))]
    assert len(waits) == 2   # waited twice for the queue to empty before starting
    st = attention.status()['refile']
    assert (st['state'], st['before'], st['after'], st['done'], st['total']) == ('done', 2, 1, 2, 2)


@pytest.mark.unit
def test_everything_is_tried_again_once_per_new_version(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(env.root), raising=False)
    monkeypatch.setattr(mylar, 'CURRENT_VERSION', 'abc123', raising=False)
    calls = []
    monkeypatch.setattr(attention, 'refile_all', lambda auto=False: calls.append(auto))
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args=(), **k: types.SimpleNamespace(start=lambda: target(*args)))
    monkeypatch.setattr(attention.time, 'sleep', lambda s: None)
    assert attention.refile_after_update() is True
    assert attention.refile_after_update() is False
    monkeypatch.setattr(mylar, 'CURRENT_VERSION', 'def456', raising=False)
    assert attention.refile_after_update() is True
    assert calls == [True, True]


@pytest.mark.unit
def test_comicvine_search_marks_series_already_on_the_watchlist(env, monkeypatch):
    from mylar import mb
    monkeypatch.setattr(mylar.CONFIG, 'COMICVINE_API', 'key', raising=False)
    asked = {}

    def find(name, mode, issue, **kw):
        asked.update(kw, name=name)
        return [{'comicid': 94801, 'name': 'Great Lakes Avengers', 'comicyear': '2016', 'publisher': 'Marvel', 'issues': '7', 'volume': None},
                {'comicid': 4321, 'name': 'Great Lakes Avengers', 'comicyear': '1999', 'publisher': 'Marvel', 'issues': '4', 'volume': None}]
    monkeypatch.setattr(mb, 'findComic', find)
    got = attention.find_series('great lakes avengers')
    assert asked['page'] == 1 and asked['name'] == 'great lakes avengers'
    assert [(s['comicid'], s['watched']) for s in got['series']] == [('94801', True), ('4321', False)]


@pytest.mark.unit
def test_comicvine_search_needs_a_key(env, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'COMICVINE_API', None, raising=False)
    got = attention.find_series('anything')
    assert got['ok'] is False and 'API key' in got['note']


@pytest.mark.unit
def test_adding_a_series_queues_it_and_says_when_its_issues_are_there(env, monkeypatch):
    from mylar import importer
    monkeypatch.setattr(mylar.CONFIG, 'COMICVINE_API', 'key', raising=False)
    env.db.action('ALTER TABLE comics ADD COLUMN Status TEXT')
    queued = []
    monkeypatch.setattr(importer, 'importer_thread', lambda lst: queued.extend(lst))

    got = attention.add_series('4050-4321', 'Great Lakes Avengers', '1999')
    assert got['ok'] and got['state'] == 'adding'
    assert queued == [{'comicid': '4321', 'comicname': 'Great Lakes Avengers', 'seriesyear': '1999'}]
    assert attention.series_state('4321')['state'] == 'missing'

    env.db.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicVersion, Total, Status) VALUES ('4321', 'Great Lakes Avengers', '1999', NULL, 4, 'Loading')")
    assert attention.series_state('4321')['state'] == 'adding'
    env.db.action("UPDATE comics SET Status='Active' WHERE ComicID='4321'")
    env.db.action("INSERT INTO issues VALUES ('9001', '4321', '1', 'Skipped', '1999-01-01', NULL)")
    ready = attention.series_state('4321')
    assert ready['state'] == 'ready' and ready['series']['name'] == 'Great Lakes Avengers'
    assert {s['comicid'] for s in attention.search('great lakes avengers')} == {'94801', '4321'}

    # a series that's already there isn't queued again
    again = attention.add_series('4321', 'Great Lakes Avengers', '1999')
    assert again['state'] == 'ready' and len(queued) == 1


@pytest.mark.unit
def test_adding_refuses_something_that_isnt_a_comicvine_id(env):
    assert attention.add_series('nope')['ok'] is False


@pytest.mark.unit
def test_comicvine_search_asks_for_the_best_match_and_ranks_by_alias_and_year(env, monkeypatch):
    from mylar import mb
    monkeypatch.setattr(mylar.CONFIG, 'COMICVINE_API', 'key', raising=False)
    asked = []

    def find(name, mode, issue, **kw):
        asked.append(dict(kw, name=name))
        return [{'comicid': 1, 'name': 'X-Men Annual', 'comicyear': '1970', 'aliases': []},
                {'comicid': 2, 'name': 'X-Men Annual', 'comicyear': '1992', 'aliases': []},
                {'comicid': 60462, 'name': "X-Men '95", 'comicyear': '1995', 'aliases': ['X-Men Annual 1995', "X-Men Annual '95", 'X-Men 1995']}]
    monkeypatch.setattr(mb, 'findComic', find)
    got = attention.find_series('X-Men Annual 1995 (1995)')
    # the "(1995)" is the year, not part of the name, and only ComicVine's best-match search is asked
    assert asked == [{'name': 'X-Men Annual 1995', 'page': 1, 'pageSize': 20, 'relevance': True}]
    assert [(s['comicid'], s['alias']) for s in got['series']][0] == ('60462', 'X-Men Annual 1995')


@pytest.mark.unit
def test_comicvine_search_puts_the_files_year_first_among_same_names(env, monkeypatch):
    from mylar import mb
    monkeypatch.setattr(mylar.CONFIG, 'COMICVINE_API', 'key', raising=False)
    monkeypatch.setattr(mb, 'findComic', lambda name, mode, issue, **kw: [
        {'comicid': 1, 'name': 'Silver Surfer: Dangerous Artifacts', 'comicyear': '2024'},
        {'comicid': 2, 'name': 'Silver Surfer: Dangerous Artifacts', 'comicyear': '1996'}])
    assert [s['comicid'] for s in attention.find_series('Silver Surfer Dangerous Artifacts', year='1996')['series']] == ['2', '1']


@pytest.mark.unit
def test_comicvine_search_falls_back_to_the_name_search(env, monkeypatch):
    from mylar import mb
    monkeypatch.setattr(mylar.CONFIG, 'COMICVINE_API', 'key', raising=False)
    asked = []

    def find(name, mode, issue, **kw):
        asked.append(kw.get('relevance', False))
        return False if kw.get('relevance') else [{'comicid': 9, 'name': 'Kissmas', 'comicyear': '2011'}]
    monkeypatch.setattr(mb, 'findComic', find)
    assert [s['comicid'] for s in attention.find_series('kissmas')['series']] == ['9']
    assert asked == [True, False]


@pytest.mark.unit
def test_watchlist_matching_reads_a_series_aliases(env):
    env.db.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicVersion, Total, AlternateSearch) VALUES "
                  "('60462', 'X-Men ''95', '1995', NULL, 1, 'X-Men Annual 1995##X-Men Annual ''95##X-Men 1995'), "
                  "('1', 'X-Men Annual', '1970', NULL, 7, 'None')")
    env.db.action("INSERT INTO issues VALUES ('i95', '60462', '1', 'Wanted', '1995-11-01', NULL), ('i70', '1', '3', 'Wanted', '1972-01-01', NULL)")
    assert attention.search('X-Men Annual 1995 (1995)')[0]['comicid'] == '60462'
    # the name reads as X-Men Annual #1995; the series is really called that, and its one issue is the one
    parsed = attention.parse('X-Men Annual 1995 (1995) (digital) (Minutemen-Bluntman).cbr')
    assert parsed['search'] == 'X-Men Annual 1995'
    best = attention.suggest(parsed)[0]
    assert (best['comicid'], best['issueid']) == ('60462', 'i95')


@pytest.mark.unit
def test_a_one_shot_is_offered_with_its_only_issue(env):
    env.db.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicVersion, Total) VALUES ('5001', 'Silver Surfer: Dangerous Artifacts', '1996', NULL, 1)")
    env.db.action("INSERT INTO issues VALUES ('da1', '5001', '1', 'Wanted', '1996-06-01', NULL)")
    best = attention.suggest({'series': 'Silver Surfer Dangerous Artifacts', 'issue': None, 'year': '1996', 'volume': None, 'name': 'Silver Surfer Dangerous Artifacts (1996) (Bchry-DCP).cbz'})[0]
    assert (best['comicid'], best['issueid'], best['agree']['issue']) == ('5001', 'da1', True)


@pytest.mark.unit
def test_an_annual_named_for_one_year_is_not_offered_another_years_one_shot(env):
    env.db.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicVersion, Total, AlternateSearch) VALUES "
                  "('7199', 'Uncanny X-Men 1999', '1999', NULL, 1, 'Uncanny X-Men Annual 1999'), "
                  "('7196', 'X-Man ''96', '1996', NULL, 1, 'None')")
    env.db.action("INSERT INTO issues VALUES ('u99', '7199', '1', 'Wanted', '2000-01-01', NULL), ('x96', '7196', '1', 'Wanted', '1996-10-01', NULL)")
    for y in ('1995', '1997', '1998'):
        parsed = attention.parse('Uncanny X-Men Annual %s (Universo Edits-DCP).cbr' % y)
        assert [m['comicid'] for m in attention.suggest(parsed)] == [], y
    parsed = attention.parse('Uncanny X-Men Annual 1999 (Universo Edits-DCP).cbr')
    best = attention.suggest(parsed)[0]
    assert (best['comicid'], best['issueid']) == ('7199', 'u99')
    # a name only partly like the file's isn't handed its only issue
    for m in attention.suggest(attention.parse('Uncanny X-Men Annual 1996 (Universo Edits-DCP).cbr')):
        assert m['issueid'] is None
    assert [s['comicid'] for s in attention.search('Uncanny X-Men Annual 1997')] == []


@pytest.mark.unit
def test_a_year_beside_other_words_picks_that_years_series(env):
    env.db.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicVersion, Total) VALUES "
                  "('2015', 'Star Wars', '2015', NULL, 75), ('2020', 'Star Wars', '2020', 'v3', 50)")
    env.db.action("INSERT INTO issues VALUES ('sw15', '2015', '7', 'Wanted', '2015-09-01', NULL), ('sw20', '2020', '7', 'Downloaded', '2020-09-01', NULL)")
    parsed = attention.parse('/downloads/mylar-dl/The Star Wars 000-008 (2015 Marvel edition) [__633460__]/'
                             'The Star Wars 007 (2015, Marvel edition) (Digital) (Zone-Empire).cbr')
    assert parsed['year'] == '2015'
    assert attention.suggest(parsed)[0]['issueid'] == 'sw15'


@pytest.mark.unit
def test_a_name_without_a_year_takes_its_pack_folders(env):
    pack = '/downloads/mylar-dl/The Star Wars 000-008 (2015 Marvel edition) [__633460__]/'
    assert attention.parse(pack + 'The Star Wars 007.cbr')['year'] == '2015'
    # a folder for something else doesn't lend its year
    assert attention.parse('/downloads/Marvel Weekly (2015)/The Star Wars 007.cbr')['year'] is None


def _x_men_annuals(env):
    env.db.action('ALTER TABLE comics ADD COLUMN ComicPublished TEXT')
    env.db.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicVersion, Total, ComicPublished) VALUES "
                  "('22988', 'X-Men Annual', '1970', NULL, 15, 'December 1970 - September 1991'), "
                  "('10748', 'X-Men Annual', '1992', 'v1', 3, 'July 1992 - December 1994'), "
                  "('146988', 'X-Men Annual', '2023', NULL, 1, 'February 2023'), "
                  "('153608', 'X-Men Annual', '2023', NULL, 1, 'November 2023'), "
                  "('60440', 'Iron Man 2000', '2000', NULL, 1, 'October 2000')")
    env.db.action("UPDATE comics SET AlternateSearch='Iron Man Annual 2000' WHERE ComicID='60440'")
    env.db.action("INSERT INTO issues VALUES ('a70', '22988', '1', 'Downloaded', '1970-12-01', NULL), ('a92', '10748', '1', 'Downloaded', '1992-07-01', NULL), "
                  "('a23', '146988', '1', 'Downloaded', '2023-02-01', NULL), ('b23', '153608', '1', 'Downloaded', '2023-11-01', NULL), "
                  "('im', '60440', '1', 'Wanted', '2000-10-01', NULL)")


@pytest.mark.unit
def test_search_puts_the_series_from_the_year_asked_for_first(env):
    _x_men_annuals(env)
    # the 2000 is the year: the X-Men Annual nearest 2000 first, the 2023 ones after, another title's Annual 2000 not above them
    out = attention.search('X-Men Annual 2000')
    assert [s['comicid'] for s in out][:4] == ['10748', '22988', '146988', '153608']
    # the same name twice from one year: side by side at the top, told apart by their run
    out = attention.search('X-Men Annual', year='2023')
    assert [(s['comicid'], s['published'], s['fits']) for s in out][:2] == [('146988', 'February 2023', True), ('153608', 'November 2023', True)]
    out = attention.search('X-Men Annual', year='1995')
    assert [s['comicid'] for s in out][:2] == ['10748', '22988']


@pytest.mark.unit
def test_suggestions_without_a_matching_issue_go_by_the_series_year(env):
    _x_men_annuals(env)
    out = attention.suggest(attention.parse('X-Men Annual 2000 (scan).cbr'), limit=4)
    assert [m['comicid'] for m in out] == ['10748', '22988', '146988', '153608']
    assert 'February 2023' in [m['published'] for m in out]
@pytest.mark.unit
def test_trashing_a_damaged_library_file_can_mark_its_issue_wanted(env, monkeypatch):
    from mylar import search
    searched = []
    monkeypatch.setattr(search, 'searchIssueIDList', lambda ids: searched.append(ids))
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args, **k: types.SimpleNamespace(start=lambda: target(*args)))
    env.db.action('ALTER TABLE comics ADD COLUMN ComicLocation TEXT')
    env.db.action('ALTER TABLE issues ADD COLUMN Location TEXT')
    env.db.action('ALTER TABLE issues ADD COLUMN ComicSize TEXT')
    env.db.action('CREATE TABLE webp_files (path TEXT PRIMARY KEY, size INTEGER, mtime REAL, status TEXT, reason TEXT, at TEXT, saved INTEGER)')
    # the series' folder on record is out of date; the file name still ties it to one issue
    env.db.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicLocation) VALUES ('34429', 'The Perhapanauts', '2005', '/comics/Dark Horse Comics/The Perhapanauts (2005)')")
    env.db.action("INSERT INTO issues (IssueID, ComicID, Issue_Number, Status, Location, ComicSize) VALUES "
                  "('p4', '34429', '4', 'Archived', 'Perhapanauts 04 (2006).cbr', '6626616'), ('p3', '34429', '3', 'Archived', 'Perhapanauts 03 (2006).cbr', '1')")
    bad = touch(env.root / 'comics' / 'Perhapanauts (Image)' / 'Perhapanauts 04 (2006).cbr')
    env.db.action("INSERT INTO webp_files (path, status) VALUES (?, 'damaged')", [bad])
    attention.record(bad, 'damaged', 'Bad CRC')
    item = [i for i in attention.items() if i['path'] == bad][0]
    assert item['in_library'] and (item['issue']['issueid'], item['issue']['status']) == ('p4', 'Archived')

    out = attention.trash(bad, want=True)
    assert out['ok'] and 'The Perhapanauts (2005) #4 is now Wanted.' in out['note']
    assert not os.path.exists(bad)
    row = env.db.selectone("SELECT Status, Location FROM issues WHERE IssueID='p4'").fetchone()
    assert (row['Status'], row['Location']) == ('Wanted', None)
    assert searched == [['p4']]
    assert env.db.selectone("SELECT Status FROM issues WHERE IssueID='p3'").fetchone()['Status'] == 'Archived'


@pytest.mark.unit
def test_plain_trash_leaves_the_issue_alone(env, monkeypatch):
    env.db.action('ALTER TABLE comics ADD COLUMN ComicLocation TEXT')
    env.db.action('ALTER TABLE issues ADD COLUMN Location TEXT')
    env.db.action('CREATE TABLE webp_files (path TEXT PRIMARY KEY, size INTEGER, mtime REAL, status TEXT, reason TEXT, at TEXT, saved INTEGER)')
    env.db.action("INSERT INTO comics (ComicID, ComicName, ComicYear) VALUES ('9', 'Thunderbolts', '1997')")
    env.db.action("INSERT INTO issues (IssueID, ComicID, Issue_Number, Status, Location) VALUES ('t66', '9', '66', 'Downloaded', 'Thunderbolts 66 (2002).cbz')")
    bad = touch(env.root / 'comics' / 'Thunderbolts (1997)' / 'Thunderbolts 66 (2002).cbz')
    env.db.action("INSERT INTO webp_files (path, status) VALUES (?, 'damaged')", [bad])
    attention.record(bad, 'damaged', 'Bad CRC')
    assert 'Wanted' not in attention.trash(bad)['note']
    assert env.db.selectone("SELECT Status FROM issues WHERE IssueID='t66'").fetchone()['Status'] == 'Downloaded'
def test_a_suggested_issue_already_in_the_library_says_so(env):
    # "Aliens 002 (2024)" is Alien (2024) #2, already filed: the page offers the trash, not File as
    env.db.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicVersion, Total) VALUES ('154673', 'Alien', '2024', NULL, 4)")
    env.db.action("INSERT INTO issues VALUES ('a2', '154673', '2', 'Downloaded', '2024-02-01', '2023-12-20'), "
                  "('a3', '154673', '3', 'Wanted', '2024-03-01', '2024-01-17')")
    best = attention.suggest({'series': 'Aliens', 'issue': '002', 'year': '2024', 'volume': None})[0]
    assert (best['comicid'], best['issueid'], best['owned']) == ('154673', 'a2', True)
    best = attention.suggest({'series': 'Aliens', 'issue': '003', 'year': '2024', 'volume': None})[0]
    assert (best['issueid'], best['owned']) == ('a3', False)
def test_try_filing_again_looks_up_unclaimed_series_first_when_auto_add_is_on(env, monkeypatch):
    from mylar import autoadd, PostProcessor
    a = touch(env.review / 'X-Men Annual 2000 (scan).cbr')
    b = touch(env.review / 'Great Lakes Avengers 002 (2017).cbz')
    attention.record(b, 'year')
    order = []
    monkeypatch.setattr(autoadd, 'enabled', lambda: True)
    monkeypatch.setattr(autoadd, '_run', lambda paths, folder=None, refile=True: order.append(('lookup', sorted(paths), refile)))
    monkeypatch.setattr(mylar, 'PP_QUEUE', None, raising=False)

    class FakePP(object):
        def __init__(self, name, folder, queue=None):
            order.append(('file', folder))

        def Process(self):
            pass
    monkeypatch.setattr(PostProcessor, 'PostProcessor', FakePP)
    monkeypatch.setattr(attention.threading, 'Thread', lambda target, args=(), **k: types.SimpleNamespace(start=lambda: target(*args)))
    assert attention.refile_all()['ok'] is True
    # only the file nothing claimed is looked up, files tried before included, and filing runs after
    assert order == [('lookup', [a], False), ('file', str(env.review))]
    order.clear()
    monkeypatch.setattr(autoadd, 'enabled', lambda: False)
    attention.refile_all()
    assert order == [('file', str(env.review))]
