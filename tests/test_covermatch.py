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
