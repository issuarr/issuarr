"""Scanning the same folder again replaces its import results instead of adding them twice."""
import sqlite3

from mylar import librarysync


class DB:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute('CREATE TABLE importresults (impID TEXT, ComicLocation TEXT, Status TEXT)')

    def action(self, query, args=()):
        return self.conn.execute(query, args)

    def add(self, impid, path, status='Not Imported'):
        self.conn.execute('INSERT INTO importresults VALUES (?, ?, ?)', [impid, path, status])

    def rows(self):
        return self.conn.execute('SELECT impID, ComicLocation FROM importresults ORDER BY impID').fetchall()


def test_rescanning_a_file_drops_every_earlier_row_for_it():
    db = DB()
    db.add('1', '/staging/X-Men/X-Men 001.cbz')
    db.add('2', '/staging/X-Men/X-Men 001.cbz')
    db.add('3', '/staging/X-Men/X-Men 002.cbz')
    librarysync.forget_earlier_scans(db, '/staging/X-Men/X-Men 001.cbz')
    assert db.rows() == [('3', '/staging/X-Men/X-Men 002.cbz')]
