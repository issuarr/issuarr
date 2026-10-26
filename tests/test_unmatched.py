"""The Library's Unmatched tab: comic files a scan saw that no issue points to."""
import os
import sqlite3
from types import SimpleNamespace

import pytest

import mylar
from mylar import attention, librarysync, unmatched


class DB:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        for sql in ('CREATE TABLE library_files (Path TEXT PRIMARY KEY, Size INTEGER, Mtime REAL)',
                    'CREATE TABLE unmatched_ignored (Path TEXT PRIMARY KEY, Size INTEGER, Mtime REAL)',
                    'CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT, ComicLocation TEXT)',
                    'CREATE TABLE issues (ComicID TEXT, Location TEXT)',
                    'CREATE TABLE annuals (ComicID TEXT, Location TEXT)',
                    'CREATE TABLE importresults (ComicLocation TEXT, Status TEXT, ComicID TEXT, DynamicName TEXT, Volume TEXT, SRID TEXT)'):
            self.conn.execute(sql)

    def select(self, query, args=()):
        return self.conn.execute(query, args).fetchall()

    def selectone(self, query, args=()):
        return self.conn.execute(query, args)

    def action(self, query, args=()):
        return self.conn.execute(query, args)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    root = tmp_path / 'comics'
    db = DB()
    monkeypatch.setattr(unmatched.db, 'DBConnection', lambda: db)
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(DESTINATION_DIR=str(root), MULTIPLE_DEST_DIRS=None,
                                                         STORYARC_LOCATION=str(root / 'StoryArcs'), GRABBAG_DIR=str(root / 'Grabbag')),
                        raising=False)
    monkeypatch.setattr(librarysync, 'work_folders', lambda: [str(root / 'Dupes')])
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(attention, 'parse', lambda p: {'series': 'X', 'issue': '1', 'year': None, 'collected': False})
    monkeypatch.setattr(attention, 'suggest', lambda parsed, limit=1: [])
    unmatched.forget()

    def add(rel, scanned=True):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'comic')
        if scanned:
            db.conn.execute('INSERT INTO library_files VALUES (?, ?, ?)', [str(p), 5, p.stat().st_mtime])
        return str(p)

    series = root / 'Marvel' / 'Avengers (1998)'
    db.conn.execute('INSERT INTO comics VALUES (?, ?, ?, ?)', ['7084', 'Avengers', '1998', str(series)])
    db.conn.execute('INSERT INTO issues VALUES (?, ?)', ['7084', 'Avengers 001 (1998).cbz'])
    paths = {
        'tied': add('Marvel/Avengers (1998)/Avengers 001 (1998).cbz'),
        'in_series': add('Marvel/Avengers (1998)/The Avengers 268 (1986).cbz'),
        'below_series': add('Marvel/Avengers (1998)/Extras/Avengers Sketchbook.cbz'),
        'loose': add('Image/Spawn/Spawn 001.cbr'),
        'loose2': add('Image/Spawn/Spawn 002.cbr'),
        'work': add('_Unsorted/Thing 001.cbz'),
        'dump': add('Dupes/Avengers 001 (1998).cbz'),
        'grabbag': add('Grabbag/One Shot.cbz'),
        'arcs': add('StoryArcs/Civil War/Civil War 01.cbz'),
        'not_comic': add('Image/Spawn/cover.jpg'),
        'unscanned': add('Image/Spawn/Spawn 003.cbr', scanned=False),
    }
    outside = tmp_path / 'downloads' / 'Saga 001.cbz'
    outside.parent.mkdir()
    outside.write_bytes(b'x')
    db.conn.execute('INSERT INTO library_files VALUES (?, ?, ?)', [str(outside), 1, 0])
    gone = str(root / 'Image' / 'Spawn' / 'Spawn 000.cbr')
    db.conn.execute('INSERT INTO library_files VALUES (?, ?, ?)', [gone, 1, 0])
    return db, paths, root


def listed():
    return sorted(os.path.basename(f['path']) for f in unmatched.files(force=True))


def test_only_untied_comics_in_the_library_are_listed(lib):
    assert listed() == ['Avengers Sketchbook.cbz', 'Spawn 001.cbr', 'Spawn 002.cbr', 'The Avengers 268 (1986).cbz']


def test_folders_note_the_series_whose_folder_they_are_in(lib):
    _, _, root = lib
    groups = {g['rel']: g for g in unmatched.folders()}
    assert set(groups) == {'Marvel/Avengers (1998)', 'Marvel/Avengers (1998)/Extras', 'Image/Spawn'}
    assert groups['Image/Spawn']['count'] == 2 and groups['Image/Spawn']['series'] == []
    assert groups['Image/Spawn']['publisher'] == 'Image'
    own = groups['Marvel/Avengers (1998)']
    assert [s['name'] for s in own['series']] == ['Avengers'] and own['series_above'] is False
    assert groups['Marvel/Avengers (1998)/Extras']['series_above'] is True


def test_a_folder_lists_its_files_with_their_import_results_state(lib):
    db, paths, root = lib
    db.conn.execute('INSERT INTO importresults VALUES (?, ?, ?, ?, ?, ?)', [paths['loose'], 'Manual Intervention', None, 'spawn', None, '9'])
    data = unmatched.folder(str(root / 'Image' / 'Spawn'))
    by = {f['name']: f for f in data['files']}
    assert by['Spawn 001.cbr']['import']['Status'] == 'Manual Intervention'
    assert by['Spawn 002.cbr']['import'] is None
    assert unmatched.folder(str(root / 'Marvel')) is None


def test_ignored_files_come_back_when_they_change(lib):
    db, paths, _ = lib
    assert unmatched.ignore(paths['loose'])['ok']
    assert 'Spawn 001.cbr' not in listed()
    with open(paths['loose'], 'ab') as f:
        f.write(b'more')
    assert 'Spawn 001.cbr' in listed()


def test_only_unmatched_files_can_be_ignored_or_shown(lib, monkeypatch):
    _, paths, _ = lib
    monkeypatch.setattr(attention, 'cover_of', lambda p: 'cover.jpg')
    assert not unmatched.ignore(paths['tied'])['ok']
    assert unmatched.cover(paths['tied']) is None
    assert unmatched.cover(paths['work']) is None
    assert unmatched.cover(paths['loose']) == 'cover.jpg'


@pytest.fixture
def matchable(lib, monkeypatch):
    db, paths, root = lib
    from mylar import matching
    db.conn.execute('INSERT INTO comics VALUES (?, ?, ?, ?)', ['500', 'Spawn', '1992', str(root / 'Image' / 'Spawn (1992)')])
    db.conn.execute('INSERT INTO comics VALUES (?, ?, ?, ?)', ['900', 'Dupe Series', '2000', str(root / 'Dupes')])
    calls = []

    def fake_match(comicid, issueid, name):
        calls.append((comicid, issueid, name))
        db.conn.execute('INSERT INTO issues VALUES (?, ?)', [comicid, name])
        return {'ok': True, 'note': '%s is now #1.' % name}

    monkeypatch.setattr(matching, 'series_dirs', lambda comic: [comic['ComicLocation']])
    monkeypatch.setattr(matching, 'match', fake_match)
    monkeypatch.setattr(matching, '_rescan', lambda comicid: db.conn.execute(
        'INSERT INTO issues VALUES (?, ?)', [comicid, 'Spawn 001.cbr']))
    real = db.selectone

    def selectone(query, args=()):
        if query.startswith('SELECT IssueID FROM issues'):
            return db.conn.execute('SELECT 1')
        return real(query, args)
    monkeypatch.setattr(db, 'selectone', selectone)
    return db, paths, root, calls


def test_the_plan_says_what_moves_before_anything_does(matchable):
    db, paths, root, _ = matchable
    p = unmatched.plan([paths['loose'], paths['tied']], '500')
    assert p['move'] == [paths['loose']] and p['stay'] == []
    assert [b['path'] for b in p['blocked']] == [paths['tied']]
    assert os.path.exists(paths['loose'])


def test_nothing_is_matched_into_a_work_folder(matchable):
    _, paths, _, _ = matchable
    p = unmatched.plan([paths['loose']], '900')
    assert not p['ok'] and 'work folder' in p['note']


def test_a_file_already_in_the_series_folder_stays(matchable):
    _, paths, _, _ = matchable
    p = unmatched.plan([paths['in_series']], '7084')
    assert p['stay'] == [paths['in_series']] and p['move'] == []


def test_matching_a_file_moves_it_and_matches_it_by_hand(matchable):
    db, paths, root, calls = matchable
    db.conn.execute('INSERT INTO importresults VALUES (?, ?, ?, ?, ?, ?)', [paths['loose'], 'No Results', None, 'spawn', None, None])
    res = unmatched.match_file(paths['loose'], '500', '42')
    target = str(root / 'Image' / 'Spawn (1992)' / 'Spawn 001.cbr')
    assert res['ok'] and os.path.exists(target) and not os.path.exists(paths['loose'])
    assert calls == [('500', '42', 'Spawn 001.cbr')]
    assert db.conn.execute('SELECT Path FROM library_files WHERE Path=?', [target]).fetchone()
    assert db.conn.execute('SELECT ComicLocation FROM importresults').fetchone()[0] == target


def test_a_name_already_in_the_series_folder_blocks_the_move(matchable):
    _, paths, root, calls = matchable
    dest = root / 'Image' / 'Spawn (1992)'
    dest.mkdir(parents=True)
    (dest / 'Spawn 001.cbr').write_bytes(b'other')
    res = unmatched.match_file(paths['loose'], '500', '42')
    assert not res['ok'] and os.path.exists(paths['loose']) and calls == []


def test_matching_a_folder_moves_its_files_and_rechecks_the_series(matchable):
    _, paths, root, _ = matchable
    res = unmatched.match_folder(str(root / 'Image' / 'Spawn'), '500')
    assert res['ok'] and res['moved'] == 2 and res['tied'] == 1 and res['left'] == 1
    assert sorted(os.listdir(root / 'Image' / 'Spawn (1992)')) == ['Spawn 001.cbr', 'Spawn 002.cbr']
