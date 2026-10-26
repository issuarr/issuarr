import io
import os
import shutil
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


def run_scan(comicid=None):
    assert library_check.scan(comicid)
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


def test_uses_the_bundled_rarfile_module():
    # Issuarr puts lib/ first on sys.path, where a bare "import rarfile" finds the empty lib/rarfile package
    assert library_check.rarfile.__name__ == 'lib.rarfile.rarfile'
    assert library_check.rarfile.RarCannotExec and library_check.rarfile.Error


def test_a_rar_with_no_unrar_or_a_bad_rar_doesnt_stop_the_scan(lib):
    db, folder, _ = lib
    (folder / 'Saga 008.cbr').write_bytes(b'Rar!\x1a\x07\x00' + b'\x00' * 64)   # a broken RAR
    run_scan()
    st = library_check.status()
    assert st['error'] is None and st['checked'] == 5


def test_one_file_that_breaks_the_checker_doesnt_stop_the_scan(lib, monkeypatch):
    real = library_check.check_file

    def check(path):
        if path.endswith('Saga 001.cbz'):
            raise AttributeError('surprise')
        return real(path)
    monkeypatch.setattr(library_check, 'check_file', check)
    run_scan()
    st = library_check.status()
    assert st['error'] is None and st['checked'] == 4 and st['unchecked'] == 1


def test_a_scan_that_stops_says_so(lib, monkeypatch):
    def boom(path):
        raise RuntimeError('disk went away')
    monkeypatch.setattr(library_check, '_stat', boom)
    run_scan()
    st = library_check.status()
    assert st['error'] == 'RuntimeError: disk went away'
    library_check.STATE['error'] = None


def test_files_webp_read_through_arent_opened_again(lib, monkeypatch):
    import os
    from mylar import webp
    db, folder, _ = lib

    def seen(name, status, reason=''):
        st = os.stat(folder / name)
        return {'size': st.st_size, 'mtime': st.st_mtime, 'status': status, 'reason': reason}
    remembered = {
        str(folder / 'Saga 001.cbz'): seen('Saga 001.cbz', 'converted'),
        str(folder / 'Saga 003.cbz'): seen('Saga 003.cbz', 'damaged', 'not a cbz'),
        str(folder / 'Saga 004.cbz'): seen('Saga 004.cbz', 'nothing to gain', 'no pages'),   # pages never read
    }
    remembered[str(folder / 'Saga 002.cbz')] = dict(seen('Saga 002.cbz', 'converted'), size=1)   # changed since
    monkeypatch.setattr(webp, 'remembered', lambda myDB=None: remembered)
    opened = []
    real = library_check.check_file
    monkeypatch.setattr(library_check, 'check_file', lambda path: opened.append(os.path.basename(path)) or real(path))
    run_scan()
    assert sorted(opened) == ['Saga 002.cbz', 'Saga 004.cbz']
    st = library_check.status()
    assert library_check.STATE['trusted'] == 2
    found = {f['name']: (f['status'], f['detail']) for f in st['files']}
    assert found['Saga 003.cbz'] == ('damaged', 'Found while converting to WebP: not a cbz.')
    assert 'Saga 001.cbz' not in found


def test_a_series_check_reads_its_files_again_and_leaves_the_rest(lib, tmp_path):
    db, folder, _ = lib
    other = tmp_path / 'Other (2020)'
    other.mkdir()
    (other / 'Other 001.cbz').write_bytes(cbz_bytes(1))
    db.c.execute("INSERT INTO comics VALUES ('2', 'Other', '2020', ?, 'other')", [str(other)])
    run_scan()
    assert library_check.STATE['opened'] == 5
    run_scan('1')
    assert library_check.STATE['done'] == 4 and library_check.STATE['opened'] == 4   # remembered, but read again
    st = library_check.status('1')
    assert sorted(f['name'] for f in st['files']) == ['Saga 002.cbz', 'Saga 003.cbz', 'Saga 004.cbz']
    assert [f['name'] for f in library_check.status('2')['files']] == ['Other 001.cbz']   # kept, not dropped
    assert len(library_check.status()['files']) == 4


SOLID = os.path.join(os.path.dirname(__file__), 'data', 'rar', 'comic-solid.rar')


def test_a_solid_rar_is_listed_and_repacked_with_the_original_in_the_trash(lib):
    db, folder, rescans = lib
    shutil.copy(SOLID, folder / 'Saga 005.cbr')
    db.c.execute("INSERT INTO issues VALUES ('i5', '1', '5', 'Saga 005.cbr', 'Downloaded')")
    assert library_check.check_file(str(folder / 'Saga 005.cbr'))[0] == 'repack'
    run_scan()
    [f] = [f for f in library_check.status()['files'] if f['name'] == 'Saga 005.cbr']
    assert f['status'] == 'repack' and f['repack'] and not f['unwrap']
    out = library_check.repack(str(folder / 'Saga 005.cbr'))
    assert out['ok'], out
    assert not (folder / 'Saga 005.cbr').exists()
    with zipfile.ZipFile(folder / 'Saga 005.cbz') as z:
        assert z.namelist() == ['001.jpg', '002.jpg', '003.jpg'] and z.testzip() is None
    assert [p.name for p in (folder.parent / 'trash').rglob('*.cbr')] == ['Saga 005.cbr']
    assert db.select("SELECT Location FROM issues WHERE IssueID='i5'")[0]['Location'] == 'Saga 005.cbz'
    assert rescans == ['1']
    assert 'Saga 005.cbr' not in [f['name'] for f in library_check.status()['files']]
    assert not library_check.repack(str(folder / 'Saga 003.cbz'))['ok']     # damaged, not one to repack


def test_a_rar_webp_called_damaged_is_opened_again(lib, monkeypatch):
    from mylar import webp
    db, folder, _ = lib
    shutil.copy(SOLID, folder / 'Saga 005.cbr')
    st = os.stat(folder / 'Saga 005.cbr')
    monkeypatch.setattr(webp, 'remembered', lambda myDB=None: {str(folder / 'Saga 005.cbr'): {
        'size': st.st_size, 'mtime': st.st_mtime, 'status': 'damaged', 'reason': 'RarCRCError: unrar stopped with code 3'}})
    run_scan()
    found = {f['name']: f['status'] for f in library_check.status()['files']}
    assert found['Saga 005.cbr'] == 'repack'
