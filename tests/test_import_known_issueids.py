import sqlite3

import pytest

from mylar import librarysync


class MemDB:
    def __init__(self):
        self.con = sqlite3.connect(':memory:')
        self.con.row_factory = sqlite3.Row
        self.con.executescript('''
            CREATE TABLE comics (ComicID TEXT, ComicName TEXT);
            CREATE TABLE issues (IssueID TEXT, ComicID TEXT, ComicName TEXT, IssueName TEXT, Issue_Number TEXT);
            CREATE TABLE annuals (IssueID TEXT, ComicID TEXT, ComicName TEXT, IssueName TEXT, Issue_Number TEXT,
                                  ReleaseComicID TEXT, ReleaseComicName TEXT, Deleted INT DEFAULT 0);
            INSERT INTO comics VALUES ('796', 'Batman');
            INSERT INTO issues VALUES ('125134', '796', 'Batman', 'Hush Chapter Four', '611');
            INSERT INTO annuals VALUES ('900', '796', 'Batman', 'Annual', '1', '5000', 'Batman Annual', 0);
            INSERT INTO annuals VALUES ('901', '796', 'Batman', 'Gone', '2', '5000', 'Batman Annual', 1);
        ''')

    def select(self, query, args=None):
        return self.con.execute(query, args or []).fetchall()


@pytest.mark.unit
def test_issueids_already_in_the_database_resolve_without_comicvine():
    vals = librarysync.known_issueids(MemDB(), ['125134', 125134, '900', '901', '777'])
    by_id = dict((v['IssueID'], v) for v in vals)
    assert sorted(by_id) == ['125134', '900']
    assert by_id['125134'] == {'ComicID': '796', 'IssueID': '125134', 'ComicName': 'Batman',
                               'Issue_Name': 'Hush Chapter Four', 'Issue_Number': '611'}
    # an annual belongs to its own ComicVine series, as the ComicVine lookup would say
    assert by_id['900']['ComicID'] == '5000'
    assert by_id['900']['ComicName'] == 'Batman Annual'


@pytest.mark.unit
def test_large_id_lists_are_queried_in_chunks():
    db = MemDB()
    ids = [str(n) for n in range(1000, 3000)] + ['125134']
    assert [v['IssueID'] for v in librarysync.known_issueids(db, ids)] == ['125134']
