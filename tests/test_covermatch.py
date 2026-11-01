"""Cover matching: a file's front cover against the issue's cover on ComicVine."""
import os
import types

import pytest
from PIL import Image, ImageDraw

import mylar
from mylar import attention, covermatch, db


def picture(path, kind, size=(400, 600)):
    im = Image.new('RGB', size, 'white')
    d = ImageDraw.Draw(im)
    w, h = size
    if kind == 'left':
        d.rectangle([0, 0, w // 2, h], fill='black')
    elif kind == 'top':
        d.rectangle([0, 0, w, h // 2], fill='black')
    elif kind == 'right':
        d.rectangle([w // 2, 0, w, h], fill='black')
    im.save(str(path), 'JPEG')
    return str(path)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    for k, v in dict(COVER_MATCH_SCORE=16, COVER_MATCH_STRICT=False, CACHE_DIR=str(tmp_path / 'cache'),
                     ARCHIVE_LEFTOVERS='delete', ARCHIVE_REVIEW_DIR=str(tmp_path / 'review'),
                     IGNORE_SEARCH_WORDS=[], CUSTOM_ISSUE_EXCEPTIONS=[], ANNUALS_ON=False, ZERO_LEVEL_N=None, ZERO_LEVEL=False).items():
        monkeypatch.setattr(mylar.CONFIG, k, v, raising=False)
    for name in ('fdebug', 'info', 'warn'):
        monkeypatch.setattr(attention.logger, name, lambda *a, **k: None)
    monkeypatch.setattr(covermatch, '_SCORED', {})
    monkeypatch.setattr(covermatch, '_HASHES', {})
    monkeypatch.setattr(attention, 'JOBS', {})
    covers = {}
    issue_covers = {}
    monkeypatch.setattr(attention, 'cover_of', lambda p: covers.get(p))
    monkeypatch.setattr(attention, 'issue_cover', lambda i: issue_covers.get(str(i)))
    return types.SimpleNamespace(root=tmp_path, covers=covers, issue_covers=issue_covers)


def comic(env, name, kind):
    path = str(env.root / 'dl' / name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'comic')
    env.covers[path] = picture(env.root / (name + '.jpg'), kind)
    return path


@pytest.mark.unit
def test_the_same_cover_is_0_apart_and_a_different_one_far():
    a = covermatch.average_hash(Image.new('L', (80, 120), 0).copy())
    assert covermatch.distance(a, a) == 0
    assert covermatch.distance(0b1010, 0b0110) == 2


@pytest.mark.unit
def test_verdicts_follow_the_pass_score(env):
    assert covermatch.verdict(None) == 'unknown'
    assert covermatch.verdict(16) == 'match'
    assert covermatch.verdict(20) == 'unsure'
    assert covermatch.verdict(24) == 'mismatch'
    mylar.CONFIG.COVER_MATCH_SCORE = 10
    assert covermatch.verdict(12) == 'unsure' and covermatch.verdict(18) == 'mismatch'
    mylar.CONFIG.COVER_MATCH_SCORE = 999
    assert covermatch.pass_score() == 32


@pytest.mark.unit
def test_only_a_clear_mismatch_stops_filing_unless_strict(env):
    for v, normal, strict in (('match', True, True), ('unsure', True, False), ('unknown', True, False), ('mismatch', False, False)):
        mylar.CONFIG.COVER_MATCH_STRICT = False
        assert covermatch.may_file({'verdict': v}) is normal
        mylar.CONFIG.COVER_MATCH_STRICT = True
        assert covermatch.may_file({'verdict': v}) is strict


@pytest.mark.unit
def test_a_file_is_compared_with_the_issue_cover(env):
    path = comic(env, 'Saga 001 (2012).cbz', 'left')
    env.issue_covers['1'] = picture(env.root / 'issue-1.jpg', 'left', size=(300, 450))
    env.issue_covers['2'] = picture(env.root / 'issue-2.jpg', 'top')
    assert covermatch.check(path, '1') == {'distance': 0, 'verdict': 'match'}
    assert covermatch.check(path, '2')['verdict'] == 'mismatch'
    assert covermatch.check(path, '3') == {'distance': None, 'verdict': 'unknown'}


@pytest.mark.unit
def test_a_two_page_spread_is_compared_by_its_front_half(env):
    path = str(env.root / 'spread.cbz')
    open(path, 'wb').close()
    im = Image.new('RGB', (800, 600), 'white')
    ImageDraw.Draw(im).rectangle([400, 0, 600, 600], fill='black')   # front cover: left half black
    im.save(str(env.root / 'spread.jpg'))
    env.covers[path] = str(env.root / 'spread.jpg')
    env.issue_covers['1'] = picture(env.root / 'front.jpg', 'left')
    assert covermatch.check(path, '1')['verdict'] == 'match'


@pytest.mark.unit
def test_the_matching_cover_goes_first_and_wins_alone(env):
    path = comic(env, 'Saga 001 (2012).cbz', 'right')
    env.issue_covers.update({'1': picture(env.root / 'i1.jpg', 'left'), '2': picture(env.root / 'i2.jpg', 'right')})
    matches = [{'issueid': '1', 'rank': 1.5, 'name': 'Saga'}, {'issueid': '2', 'rank': 1.0, 'name': 'Saga'}, {'issueid': None, 'rank': 0.5}]
    assert covermatch.annotate(path, matches)[0]['cover']['distance'] is None   # nothing compared yet, nothing fetched
    scored = covermatch.annotate(path, matches, fetch=True)
    assert [m['issueid'] for m in scored] == ['2', '1', None]
    assert covermatch.winner(scored)['issueid'] == '2'
    # without fetching, a page sees what was compared before
    assert covermatch.annotate(path, matches)[0]['cover']['verdict'] == 'match'


@pytest.mark.unit
def test_two_matching_covers_are_left_for_the_user(env):
    path = comic(env, 'Saga 001 (2012).cbz', 'left')
    env.issue_covers.update({'1': picture(env.root / 'i1.jpg', 'left'), '2': picture(env.root / 'i2.jpg', 'left', size=(200, 300))})
    scored = covermatch.annotate(path, [{'issueid': '1'}, {'issueid': '2'}], fetch=True)
    assert covermatch.winner(scored) is None


@pytest.fixture
def filing(env, monkeypatch):
    from mylar import PostProcessor, archives
    d = db.DBConnection()
    monkeypatch.setattr(archives, 'tally', lambda *a: None)
    pp = PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)
    pp.module = '[TEST]'
    env.issue_covers['1'] = picture(env.root / 'i1.jpg', 'left')
    return types.SimpleNamespace(pp=pp, db=d)


def entry(path, **kw):
    e = {'ComicLocation': path, 'ComicID': '10', 'IssueID': '1', 'ComicName': 'Saga', 'SeriesYear': '2012', 'IssueNumber': '1'}
    e.update(kw)
    return e


@pytest.mark.unit
def test_filing_holds_back_a_file_whose_cover_is_another_issues(env, filing):
    good = comic(env, 'Saga 001 (2012).cbz', 'left')
    bad = comic(env, 'Saga 001 (2012) (variant).cbz', 'top')
    assert filing.pp._cover_ok(entry(good)) is True
    assert filing.pp._cover_ok(entry(bad)) is False
    row = filing.db.selectone('SELECT reason, detail, comicid FROM attention WHERE path=?', [bad]).fetchone()
    assert row['reason'] == 'coverart' and row['comicid'] == '10' and 'Saga (2012) #1' in row['detail']
    assert filing.pp._att_listed == [bad]
    # an issue the user picked by hand isn't checked
    assert filing.pp._cover_ok(entry(bad, ForcedMatch=True)) is True


@pytest.mark.unit
def test_strict_filing_needs_a_cover_to_match(env, filing):
    nocover = comic(env, 'Saga 002 (2012).cbz', 'left')
    assert filing.pp._cover_ok(entry(nocover, IssueID='2')) is True
    mylar.CONFIG.COVER_MATCH_STRICT = True
    assert filing.pp._cover_ok(entry(nocover, IssueID='2')) is False
    assert 'no cover to compare' in filing.db.selectone('SELECT detail FROM attention WHERE path=?', [nocover]).fetchone()['detail']


@pytest.mark.unit
def test_a_file_held_back_for_its_cover_is_never_deleted_as_a_leftover(env, filing):
    from mylar import archives
    bad = comic(env, 'Saga 001 (2012).cbz', 'top')
    other = comic(env, 'Unwanted 001 (2012).cbz', 'top')
    filing.pp._cover_ok(entry(bad))
    assert attention.held(bad) and not attention.held(other)
    assert archives._dispose(other, '') == 'deleted'
    assert archives._dispose(bad, '') == 'moved'
    moved = os.path.join(mylar.CONFIG.ARCHIVE_REVIEW_DIR, os.path.basename(bad))
    assert os.path.isfile(moved) and attention.held(moved)


@pytest.mark.unit
def test_the_cover_pass_files_a_single_clear_match(env, filing, monkeypatch):
    path = comic(env, 'Saga 001 (2012).cbz', 'left')
    other = comic(env, 'Saga 002 (2012).cbz', 'right')
    attention.record(path, 'year')
    attention.record(other, 'year')
    monkeypatch.setattr(attention, 'in_library', lambda p: False)
    monkeypatch.setattr(attention, 'suggest', lambda parsed, comicid=None: [
        {'comicid': '10', 'issueid': '1', 'name': 'Saga', 'number': '1', 'rank': 1.0, 'owned': False}])
    filed = []
    monkeypatch.setattr(attention, 'file_as', lambda p, c, i: filed.append((p, c, i)) or {'ok': True})
    attention.cover_pass(wait=True)
    assert filed == [(path, '10', '1')]


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


@pytest.fixture
def cv(env, monkeypatch):
    from mylar import cv as cvmod
    monkeypatch.setattr(mylar.CONFIG, 'COMICVINE_API', 'key', raising=False)
    monkeypatch.setattr(mylar, 'CVURL', 'https://cv/api/', raising=False)
    monkeypatch.setattr(covermatch, '_CV_COVERS', {})
    calls, results = [], []
    monkeypatch.setattr(cvmod, 'cv_request', lambda url: calls.append(url) or FakeResponse({'results': results}))
    urls = {}
    monkeypatch.setattr(attention, 'url_cover', lambda name, url: urls.get(url))
    return types.SimpleNamespace(calls=calls, results=results, urls=urls)


def cv_issue(series, image, alts=()):
    return {'id': 1, 'issue_number': '1', 'volume': {'id': int(series)}, 'image': {'super_url': image},
            'associated_images': [{'original_url': a} for a in alts]}


@pytest.mark.unit
def test_issue_numbers_are_asked_for_as_comicvine_writes_them():
    assert covermatch._cv_number('001') == '1' and covermatch._cv_number('1.0') == '1'
    assert covermatch._cv_number('0') == '0' and covermatch._cv_number('½') == '½'


@pytest.mark.unit
def test_one_call_asks_for_the_issue_of_every_series(env, cv):
    cv.results[:] = [cv_issue(11268, 'http://a/1.jpg', ['http://a/1b.jpg']), cv_issue(11269, 'http://a/2.jpg')]
    found = covermatch.cv_covers(['11269', '11268'], '001')
    assert found == {'11268': ('http://a/1.jpg', ['http://a/1b.jpg']), '11269': ('http://a/2.jpg', [])}
    assert len(cv.calls) == 1 and 'filter=volume:11268|11269,issue_number:1&' in cv.calls[0]
    covermatch.cv_covers(['11268', '11269'], '1')
    assert len(cv.calls) == 1   # remembered


@pytest.mark.unit
def test_a_series_matches_by_an_alternate_cover_only_when_it_is_closer(env, cv):
    path = comic(env, 'Brigade v1 #1.cbz', 'left')
    cv.results[:] = [cv_issue(1, 'http://a/top.jpg', ['http://a/left.jpg']), cv_issue(2, 'http://a/right.jpg')]
    cv.urls.update({'http://a/top.jpg': picture(env.root / 'top.jpg', 'top'), 'http://a/left.jpg': picture(env.root / 'l.jpg', 'left'),
                    'http://a/right.jpg': picture(env.root / 'r.jpg', 'right')})
    found = covermatch.series_distances(path, '1', ['1', '2'])
    assert found['1'] == 0 and found['2'] > 16


@pytest.mark.unit
def test_the_file_compared_is_number_1_not_0_or_a_half():
    from mylar import importchoice
    files = [{'path': 'a', 'number': '0'}, {'path': 'b', 'number': '½'}, {'path': 'c', 'number': '1'}, {'path': 'd', 'number': '2'}]
    assert importchoice.reference_file(files)['path'] == 'c'
    assert importchoice.reference_file([{'path': 'a', 'number': '0'}, {'path': 'e', 'number': '3'}])['path'] == 'e'
    assert importchoice.reference_file([{'path': 'a', 'number': '0'}])['path'] == 'a'
    assert importchoice.reference_file([{'path': 'a', 'number': '1', 'missing': True}]) is None


@pytest.mark.unit
def test_an_import_picks_the_series_whose_cover_matches(env, cv, monkeypatch):
    from mylar import importchoice
    one = comic(env, 'Brigade v1 #1.cbz', 'left')
    zero = comic(env, 'Brigade v1 #0.cbz', 'top')
    monkeypatch.setattr(importchoice, '_rows', lambda myDB, d, v: [{'ComicLocation': zero, 'IssueNumber': '0'},
                                                                   {'ComicLocation': one, 'IssueNumber': '1'}])
    monkeypatch.setattr(importchoice, '_live', lambda p: p)
    cv.results[:] = [cv_issue(11268, 'http://a/left.jpg'), cv_issue(11269, 'http://a/right.jpg')]
    cv.urls.update({'http://a/left.jpg': picture(env.root / 'l.jpg', 'left'), 'http://a/right.jpg': picture(env.root / 'r.jpg', 'right')})
    cands = [{'comicid': '11269', 'name': 'Brigade (1993)'}, {'comicid': '11268', 'name': 'Brigade (1992)'}]
    assert importchoice.cover_pick(cands, 'brigade', 'v1')['comicid'] == '11268'
    assert 'issue_number:1&' in cv.calls[0]
    # both covers alike: left for the user
    cv.urls['http://a/right.jpg'] = picture(env.root / 'l2.jpg', 'left', size=(300, 450))
    monkeypatch.setattr(covermatch, '_CV_COVERS', {})
    monkeypatch.setattr(covermatch, '_HASHES', {})
    assert importchoice.cover_pick(cands, 'brigade', 'v1') is None
