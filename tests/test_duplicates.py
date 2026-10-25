import sqlite3
import zipfile

import pytest

import mylar
from mylar import attention, duplicates, matching


def cbz(path, pages, tagged=False):
    with zipfile.ZipFile(path, 'w') as z:
        for n in range(pages):
            z.writestr('%03d.jpg' % n, b'x' * 100)
        if tagged:
            z.writestr('ComicInfo.xml', '<ComicInfo/>')


class FakeDB:
    def __init__(self):
        self.c = sqlite3.connect(':memory:', check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.c.execute('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT, ComicLocation TEXT, ComicSortName TEXT)')
        self.c.execute('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Location TEXT, Status TEXT)')
        self.c.execute('CREATE TABLE annuals (IssueID TEXT, ComicID TEXT, Location TEXT)')

    def select(self, q, args=()):
        return self.c.execute(q, args).fetchall()


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', type('C', (), {'MULTIPLE_DEST_DIRS': None, 'DDUMP': False, 'DUPLICATE_DUMP': None})(), raising=False)
    monkeypatch.setattr(matching, '_extensions', lambda: ('.cbz',))
    monkeypatch.setattr(matching, '_rescan', lambda comicid: None)
    monkeypatch.setattr(attention, 'trash_dir', lambda: str(tmp_path / 'trash'))
    numbers = {'Saga 001.cbz': '1', 'Saga 001 (c2c).cbz': '1', 'Saga 002.cbz': '2', 'Saga Annual 001.cbz': '1',
               'Saga Vol 01 TPB.cbz': '1', 'Saga 001 (other).cbz': '1'}
    monkeypatch.setattr(attention, 'parse', lambda p: {'issue': numbers.get(p.split('/')[-1])})
    folder = tmp_path / 'Saga (2012)'
    folder.mkdir()
    cbz(folder / 'Saga 001.cbz', 20)
    cbz(folder / 'Saga 001 (c2c).cbz', 22, tagged=True)
    cbz(folder / 'Saga 002.cbz', 20)
    cbz(folder / 'Saga Annual 001.cbz', 40)
    cbz(folder / 'Saga Vol 01 TPB.cbz', 150)
    db = FakeDB()
    db.c.execute("INSERT INTO comics VALUES ('1', 'Saga', '2012', ?, 'saga')", [str(folder)])
    db.c.execute("INSERT INTO issues VALUES ('a', '1', '1', 'Saga 001.cbz', 'Downloaded')")
    db.c.execute("INSERT INTO issues VALUES ('b', '1', '2', 'Saga 002.cbz', 'Downloaded')")
    monkeypatch.setattr(duplicates.db, 'DBConnection', lambda: db)
    return db, folder


def test_file_info_and_rank(tmp_path):
    cbz(tmp_path / 'a.cbz', 3, tagged=True)
    (tmp_path / 'b.cbz').write_bytes(b'not a zip')
    assert duplicates.file_info(str(tmp_path / 'a.cbz')) == {'readable': True, 'tagged': True, 'pages': 3}
    assert duplicates.file_info(str(tmp_path / 'b.cbz'))['readable'] is False
    files = [{'readable': False, 'tagged': True, 'pages': 30, 'size': 9}, {'readable': True, 'tagged': False, 'pages': 20, 'size': 5},
             {'readable': True, 'tagged': True, 'pages': 18, 'size': 1}, {'readable': True, 'tagged': True, 'pages': 18, 'size': 2}]
    assert [f['size'] for f in duplicates.rank(files)] == [2, 1, 5, 9]


def test_series_groups_keeps_tagged_copy_and_skips_annuals_and_trades(lib):
    db, folder = lib
    groups = duplicates.series_groups(db, db.select('SELECT * FROM comics')[0])
    assert len(groups) == 1 and groups[0]['number'] == '1'
    assert [(f['name'], f['keep'], f['matched']) for f in groups[0]['files']] == [
        ('Saga 001 (c2c).cbz', True, False), ('Saga 001.cbz', False, True)]


def test_remove_moves_to_trash_and_never_every_copy(lib):
    db, folder = lib
    duplicates.STATE['groups'] = duplicates.series_groups(db, db.select('SELECT * FROM comics')[0])
    both = [str(folder / 'Saga 001.cbz'), str(folder / 'Saga 001 (c2c).cbz')]
    out = duplicates.remove(both)
    assert out['moved'] == 0 and all((folder / n).exists() for n in ('Saga 001.cbz', 'Saga 001 (c2c).cbz'))
    assert not duplicates.remove([str(folder / 'Saga 002.cbz')])['ok']      # not from the scan
    out = duplicates.remove([str(folder / 'Saga 001.cbz')])
    assert out['moved'] == 1 and 'trash' in out['note']
    assert not (folder / 'Saga 001.cbz').exists() and (folder / 'Saga 001 (c2c).cbz').exists()
    assert duplicates.STATE['groups'] == []


def test_scan_runs_in_background(lib):
    import time
    assert duplicates.scan()
    for _ in range(50):
        if duplicates.status()['state'] == 'done':
            break
        time.sleep(0.05)
    st = duplicates.status()
    assert st['state'] == 'done' and st['total'] == 1 and len(st['groups']) == 1
