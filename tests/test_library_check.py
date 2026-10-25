import io
import sqlite3
import time
import zipfile

import pytest

import mylar
from mylar import attention, library_check, matching


def cbz_bytes(pages, extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for n in range(pages):
            z.writestr('%03d.jpg' % n, b'x' * 50)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


class FakeDB:
    def __init__(self):
        self.c = sqlite3.connect(':memory:', check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.c.execute('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT, ComicLocation TEXT, ComicSortName TEXT)')
        self.c.execute('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT, Location TEXT, Status TEXT)')

    def select(self, q, args=()):
        return self.c.execute(q, args).fetchall()

    def selectone(self, q, args=()):
        return self.c.execute(q, args)

    def action(self, q, args=()):
        self.c.execute(q, args)

    def upsert(self, table, vals, ctrl):
        keys = list(ctrl) + list(vals)
        cur = self.c.execute('UPDATE %s SET %s WHERE %s' % (table, ', '.join('%s=?' % k for k in vals), ' AND '.join('%s=?' % k for k in ctrl)),
                             list(vals.values()) + list(ctrl.values()))
        if cur.rowcount == 0:
            self.c.execute('INSERT INTO %s (%s) VALUES (%s)' % (table, ', '.join(keys), ', '.join('?' * len(keys))),
                           list(ctrl.values()) + list(vals.values()))


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', type('C', (), {'MULTIPLE_DEST_DIRS': None})(), raising=False)
    monkeypatch.setattr(matching, '_extensions', lambda: ('.cbz', '.cbr'))
    rescans = []
    monkeypatch.setattr(matching, '_rescan', rescans.append)
    monkeypatch.setattr(attention, 'trash_dir', lambda: str(tmp_path / 'trash'))
    folder = tmp_path / 'Saga (2012)'
    folder.mkdir()
    (folder / 'Saga 001.cbz').write_bytes(cbz_bytes(20))
    (folder / 'Saga 002.cbz').write_bytes(cbz_bytes(0, {'Saga 002.cbr': cbz_bytes(20, {'ComicInfo.xml': '<inner/>'}), 'ComicInfo.xml': '<outer/>'}))
    (folder / 'Saga 003.cbz').write_bytes(b'<html>Cloudflare</html>')
    (folder / 'Saga 004.cbz').write_bytes(cbz_bytes(1))
    db = FakeDB()
    db.c.execute("INSERT INTO comics VALUES ('1', 'Saga', '2012', ?, 'saga')", [str(folder)])
    for n in (1, 2, 3, 4):
        db.c.execute("INSERT INTO issues VALUES (?, '1', ?, ?, 'Downloaded')", ['i%d' % n, str(n), 'Saga 00%d.cbz' % n])
    monkeypatch.setattr(library_check.db, 'DBConnection', lambda: db)
    return db, folder, rescans


def run_scan():
    assert library_check.scan()
    for _ in range(100):
        if library_check.STATE['state'] == 'done':
            return
        time.sleep(0.05)


def test_check_file(lib):
    _, folder, _ = lib
    assert library_check.check_file(str(folder / 'Saga 001.cbz'))[0] == 'ok'
    assert library_check.check_file(str(folder / 'Saga 002.cbz')) == ('nested', 'Holds Saga 002.cbr instead of pages.', 'Saga 002.cbr')
    assert library_check.check_file(str(folder / 'Saga 003.cbz'))[0] == 'damaged'
    assert library_check.check_file(str(folder / 'Saga 004.cbz')) == ('damaged', 'Has 1 page.', None)
    broken = bytearray(cbz_bytes(5))
    broken[60] ^= 0xFF
    (folder / 'x.cbz').write_bytes(bytes(broken))
    assert library_check.check_file(str(folder / 'x.cbz'))[0] == 'damaged'


def test_scan_lists_problems_and_remembers_files(lib):
    db, folder, _ = lib
    run_scan()
    st = library_check.status()
    assert st['checked'] == 4 and st['state'] == 'done'
    assert sorted((f['name'], f['status'], f['unwrap'], f['number']) for f in st['files']) == [
        ('Saga 002.cbz', 'nested', True, '2'), ('Saga 003.cbz', 'damaged', False, '3'), ('Saga 004.cbz', 'damaged', False, '4')]
    run_scan()
    assert library_check.STATE['opened'] == 0      # nothing changed


def test_unwrap_keeps_inner_tags_and_trashes_original(lib):
    db, folder, rescans = lib
    run_scan()
    out = library_check.unwrap(str(folder / 'Saga 002.cbz'))
    assert out['ok'], out
    with zipfile.ZipFile(folder / 'Saga 002.cbz') as z:
        assert len([n for n in z.namelist() if n.endswith('.jpg')]) == 20
        assert z.read('ComicInfo.xml') == b'<inner/>'
    assert len(list((folder.parent / 'trash').rglob('*.cbz'))) == 1
    assert rescans == ['1']
    assert not library_check.unwrap(str(folder / 'Saga 001.cbz'))['ok']


def test_redownload_trashes_and_wants_issue(lib):
    db, folder, rescans = lib
    run_scan()
    out = library_check.redownload(str(folder / 'Saga 003.cbz'))
    assert out['ok'] and not (folder / 'Saga 003.cbz').exists()
    assert db.select("SELECT Status FROM issues WHERE IssueID='i3'")[0]['Status'] == 'Wanted'
    assert not library_check.remove(str(folder / 'Saga 001.cbz'))['ok']     # not listed
    assert library_check.remove(str(folder / 'Saga 004.cbz'))['ok']
