import os
import sqlite3

import pytest

from mylar import librarysync


class MemDB:
    def __init__(self):
        self.con = sqlite3.connect(':memory:')
        self.con.row_factory = sqlite3.Row
        self.con.executescript('''
            CREATE TABLE comics (ComicID TEXT, ComicLocation TEXT);
            CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Location TEXT, ComicSize TEXT, Status TEXT);
            CREATE TABLE annuals (IssueID TEXT, ComicID TEXT, Location TEXT, ComicSize TEXT, Status TEXT);
            CREATE TABLE library_files (Path TEXT PRIMARY KEY, Size INTEGER, Mtime REAL);
            INSERT INTO comics VALUES ('1', '/comics/Marvel/Fantastic Four (2022)/');
            INSERT INTO issues VALUES ('11', '1', 'Fantastic Four 033 (2025).cbz', '1000', 'Downloaded');
            INSERT INTO issues VALUES ('12', '1', 'Fantastic Four 034 (2025).cbz', '2000', 'Wanted');
            INSERT INTO annuals VALUES ('13', '1', 'Fantastic Four Annual 001 (2023).cbz', '3000', 'Archived');
            INSERT INTO library_files VALUES ('/comics/Marvel/Fantastic Four (2022)/Fantastic Four 033 (2025).cbz', 1000, 50.0);
        ''')

    def select(self, query, args=None):
        return self.con.execute(query, args or []).fetchall()


FOLDER = '/comics/Marvel/Fantastic Four (2022)'


@pytest.fixture
def known():
    db = MemDB()
    return librarysync.library_files(db), librarysync.seen_files(db)


@pytest.mark.unit
def test_only_files_the_library_has_are_known(known):
    in_library, seen = known
    assert sorted(os.path.basename(p) for p in in_library) == ['Fantastic Four 033 (2025).cbz', 'Fantastic Four Annual 001 (2023).cbz']
    assert seen == {os.path.join(FOLDER, 'Fantastic Four 033 (2025).cbz'): (1000, 50.0)}


@pytest.mark.unit
def test_a_file_the_library_has_is_left_out_until_it_changes(known):
    in_library, seen = known
    path = os.path.join(FOLDER, 'Fantastic Four 033 (2025).cbz')
    assert librarysync.unchanged(path, 1000, 50.0, in_library, seen)
    # a different size, or the same size pasted over it later
    assert not librarysync.unchanged(path, 1001, 50.0, in_library, seen)
    assert not librarysync.unchanged(path, 1000, 99.0, in_library, seen)


@pytest.mark.unit
def test_a_file_no_scan_has_seen_yet_goes_by_the_recorded_size(known):
    in_library, seen = known
    path = os.path.join(FOLDER, 'Fantastic Four Annual 001 (2023).cbz')
    assert librarysync.unchanged(path, 3000, 12.0, in_library, seen)
    assert not librarysync.unchanged(path, 2999, 12.0, in_library, seen)


@pytest.mark.unit
def test_new_files_are_always_scanned(known):
    in_library, seen = known
    # a re-downloaded copy under another name, and an issue whose file was never linked
    assert not librarysync.unchanged(os.path.join(FOLDER, 'Fantastic Four 033 (2025) (Digital).cbz'), 1000, 50.0, in_library, seen)
    assert not librarysync.unchanged(os.path.join(FOLDER, 'Fantastic Four 034 (2025).cbz'), 2000, 50.0, in_library, seen)
