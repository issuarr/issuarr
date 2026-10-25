import pytest

import mylar
from mylar import volume_check

MB = 1048576


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)


def f(name, size=20 * MB, number=None, reads_as=None):
    return {'name': name, 'size': size, 'number': number, 'reads_as': reads_as}


def test_file_past_the_last_issue_is_another_volume():
    files = [f('Batman 001 (2016).cbz', number='1'), f('Batman 713 (1972).cbz', reads_as='713')]
    found, whole = volume_check.suspects(files, [str(n) for n in range(1, 151)], 'Batman')
    assert found['Batman 713 (1972).cbz']['kind'] == 'volume'
    assert '#150' in found['Batman 713 (1972).cbz']['note']
    assert not whole


def test_new_issue_just_past_the_end_is_not_flagged():
    files = [f('Saga 067.cbz', reads_as='67')]
    found, _ = volume_check.suspects(files, [str(n) for n in range(1, 67)], 'Saga')
    assert found == {}


def test_most_files_past_the_end_means_wrong_series():
    files = [f('X %d.cbz' % n, reads_as=str(n)) for n in (40, 41, 42)] + [f('X 1.cbz', number='1')]
    _, whole = volume_check.suspects(files, ['1', '2', '3', '4', '5', '6'], 'X')
    assert whole


def test_collected_name_in_singles_series():
    files = [f('Saga 001.cbz', number='1'), f('Saga Vol 02 TPB.cbz', number='2')]
    found, _ = volume_check.suspects(files, ['1', '2', '3'], 'Saga')
    assert found['Saga Vol 02 TPB.cbz']['kind'] == 'collected'
    found, _ = volume_check.suspects(files, ['1', '2', '3'], 'Saga', singles=False)
    assert found == {}


def test_series_own_omnibus_name_is_not_flagged():
    files = [f('Marvel Omnibus 001.cbz', number='1')]
    found, _ = volume_check.suspects(files, ['1'], 'Marvel Omnibus')
    assert found == {}


def test_size_outlier_against_series_typical_size():
    files = [f('Saga %03d.cbz' % n, 15 * MB, number=str(n)) for n in range(1, 7)]
    files.append(f('Saga 007.cbz', 140 * MB, number='7'))
    found, _ = volume_check.suspects(files, [str(n) for n in range(1, 8)], 'Saga')
    assert list(found) == ['Saga 007.cbz']
    assert found['Saga 007.cbz']['kind'] == 'size'


def test_size_needs_enough_files_and_the_floor():
    few = [f('A 1.cbz', 10 * MB, '1'), f('A 2.cbz', 100 * MB, '2')]
    assert volume_check.suspects(few, ['1', '2'], 'A')[0] == {}
    small = [f('B %d.cbz' % n, 5 * MB, str(n)) for n in range(1, 7)] + [f('B 7.cbz', 30 * MB, '7')]
    assert volume_check.suspects(small, [str(n) for n in range(1, 8)], 'B')[0] == {}


def test_odd_numbers_dont_crash():
    files = [f('A Annual.cbz', reads_as='Annual'), f('A 1.cbz', reads_as='1')]
    assert volume_check.suspects(files, ['1', 'Annual', None], 'A')[0] == {}
    assert volume_check.suspects(files, [], 'A')[0] == {}


class FakeDB:
    def __init__(self):
        import sqlite3
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.execute('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT, ComicLocation TEXT, Type TEXT, Corrected_Type TEXT)')
        self.c.execute('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Location TEXT, Status TEXT)')

    def select(self, q, args=()):
        return self.c.execute(q, args).fetchall()

    def selectone(self, q, args=()):
        return self.c.execute(q, args)


def test_check_skips_files_another_series_in_the_folder_owns(tmp_path, monkeypatch):
    from mylar import attention, matching
    folder = tmp_path / 'Saga (2012)'
    folder.mkdir()
    for name in ('Saga 001.cbz', 'Saga Vol 01 TPB.cbz', 'Saga Vol 02 TPB.cbz'):
        (folder / name).write_bytes(b'x' * 10)
    db = FakeDB()
    db.c.execute("INSERT INTO comics VALUES ('1', 'Saga', '2012', ?, 'Print', NULL)", [str(folder)])
    db.c.execute("INSERT INTO comics VALUES ('2', 'Saga', '2012', ?, 'TPB', NULL)", [str(folder)])
    db.c.execute("INSERT INTO issues VALUES ('a', '1', '1', 'Saga 001.cbz', 'Downloaded')")
    db.c.execute("INSERT INTO issues VALUES ('b', '2', '1', 'Saga Vol 01 TPB.cbz', 'Downloaded')")
    monkeypatch.setattr(volume_check.db, 'DBConnection', lambda: db)
    monkeypatch.setattr(matching, '_extensions', lambda: ('.cbz',))
    monkeypatch.setattr(mylar, 'CONFIG', type('C', (), {'MULTIPLE_DEST_DIRS': None})(), raising=False)
    monkeypatch.setattr(attention, 'parse', lambda p: {'issue': None})
    volume_check._CACHE.clear()
    out = volume_check.check('1')
    assert [x['name'] for x in out['files']] == ['Saga Vol 02 TPB.cbz']

    review = tmp_path / 'review'
    noted, rescanned = [], []
    monkeypatch.setattr(attention, 'review_dir', lambda: str(review))
    monkeypatch.setattr(attention, 'record', lambda path, reason, detail='', comicid=None: noted.append((path, reason)))
    monkeypatch.setattr(matching, '_rescan', rescanned.append)
    assert not volume_check.send_away('1', 'Saga 001.cbz')['ok']     # not flagged
    assert volume_check.send_away('1', 'Saga Vol 02 TPB.cbz')['ok']
    assert (review / 'Saga Vol 02 TPB.cbz').exists() and not (folder / 'Saga Vol 02 TPB.cbz').exists()
    assert noted == [(str(review / 'Saga Vol 02 TPB.cbz'), 'volume')] and rescanned == ['1']
    assert (folder / 'Saga Vol 01 TPB.cbz').exists()
