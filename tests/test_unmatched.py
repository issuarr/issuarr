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
