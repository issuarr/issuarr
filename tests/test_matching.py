"""Series page > Match files: files matched to issues by hand, and files placed by their ComicInfo tags."""
import os
import zipfile

import pytest

import mylar
from mylar import comicinfo, db, matching, updater


def comic_file(path, notes=None, web=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('001.jpg', b'x' * 10)
        if notes or web:
            xml = '<?xml version="1.0"?>\n<ComicInfo>\n'
            if notes:
                xml += '  <Notes>%s</Notes>\n' % notes
            if web:
                xml += '  <Web>%s</Web>\n' % web
            z.writestr('ComicInfo.xml', xml + '</ComicInfo>\n')
    return str(path)


@pytest.fixture
def series(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'DB_FILE', str(tmp_path / 'mylar.db'), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    for k, v in mylar.config._CONFIG_DEFINITIONS.items():
        monkeypatch.setattr(mylar.CONFIG, k, v[2], raising=False)
    for k, v in dict(IGNORE_SEARCH_WORDS=[], CUSTOM_ISSUE_EXCEPTIONS=[], ANNUALS_ON=False, FOLDER_SCAN_LOG_VERBOSE=False,
                     MULTIPLE_DEST_DIRS=None, ZERO_LEVEL_N=None, ZERO_LEVEL=False, IGNORE_HAVETOTAL=False,
                     SNATCHED_HAVETOTAL=False, ENABLE_TORRENTS=False, DUPECONSTRAINT='filesize',
                     DYNAMIC_UPDATE=99, OLDCONFIG_VERSION=None).items():
        monkeypatch.setattr(mylar.CONFIG, k, v, raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(matching, '_TAGS', {})
    mylar.dbcheck()
    folder = tmp_path / 'library' / 'Foo (2020)'
    d = db.DBConnection()
    d.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicLocation, ComicPublisher, Type, Status, Total, Have) "
             "VALUES ('500', 'Foo', '2020', ?, 'Marvel', 'Print', 'Active', 4, 0)", [str(folder)])
    for n in range(1, 5):
        d.action("INSERT INTO issues (IssueID, ComicID, ComicName, Issue_Number, Int_IssueNumber, IssueDate, Status) "
                 "VALUES (?, '500', 'Foo', ?, ?, '2020-0%s-01', 'Wanted')" % n, ['100%s' % n, str(n), n * 1000])
    comic_file(folder / 'Foo 001 (2020).cbz')
    comic_file(folder / 'Foo 002 (2020).cbz')
    comic_file(folder / 'weird scan.cbz', notes='Tagged with ComicTagger 1.6 using info from Comic Vine. [Issue ID 1003]')
    comic_file(folder / 'Bar 007.cbz')
    return folder


def issue(i):
    return dict(db.DBConnection().selectone('SELECT Status, Location, forced_file FROM issues WHERE IssueID=?', [i]).fetchone())


@pytest.mark.unit
def test_the_comicvine_issue_id_is_read_from_the_tags(tmp_path):
    assert comicinfo.cv_issue_id(comic_file(tmp_path / 'a.cbz', notes='blah [Issue ID 4567]')) == '4567'
    assert comicinfo.cv_issue_id(comic_file(tmp_path / 'b.cbz', notes='[CVDB89]')) == '89'
    assert comicinfo.cv_issue_id(comic_file(tmp_path / 'c.cbz', web='https://comicvine.gamespot.com/foo-1/4000-321/')) == '321'
    assert comicinfo.cv_issue_id(comic_file(tmp_path / 'd.cbz', notes='nothing here')) is None
    assert comicinfo.cv_issue_id(comic_file(tmp_path / 'e.cbz')) is None


@pytest.mark.unit
def test_a_file_the_name_cant_place_is_matched_by_its_tags(series):
    updater.forceRescan('500')
    assert issue('1001')['Location'] == 'Foo 001 (2020).cbz'
    assert issue('1002')['Location'] == 'Foo 002 (2020).cbz'
    assert (issue('1003')['Status'], issue('1003')['Location']) == ('Downloaded', 'weird scan.cbz')
    assert issue('1004')['Status'] == 'Wanted'


@pytest.mark.unit
def test_a_file_matched_by_hand_stays_matched_through_a_recheck(series):
    updater.forceRescan('500')
    r = matching.match('500', '1004', 'Bar 007.cbz')
    assert r['ok']
    assert issue('1004') == {'Status': 'Downloaded', 'Location': 'Bar 007.cbz', 'forced_file': 1}
    updater.forceRescan('500')
    assert issue('1004') == {'Status': 'Downloaded', 'Location': 'Bar 007.cbz', 'forced_file': 1}
    listed = {f['name']: f for f in matching.files('500')['files']}
    assert listed['Bar 007.cbz']['issueid'] == '1004' and listed['Bar 007.cbz']['pinned']
    assert listed['weird scan.cbz']['issueid'] == '1003' and not listed['weird scan.cbz']['pinned']


@pytest.mark.unit
def test_matching_a_file_to_another_issue_moves_it(series):
    updater.forceRescan('500')
    assert matching.match('500', '1003', 'Foo 002 (2020).cbz')['ok']
    assert issue('1003')['Location'] == 'Foo 002 (2020).cbz'
    # its old issue has no file now, and the tagged file has nowhere left to go
    assert issue('1002')['Status'] == 'Archived'
    assert issue('1001')['Location'] == 'Foo 001 (2020).cbz'


@pytest.mark.unit
def test_undoing_a_match_goes_back_to_the_name(series):
    updater.forceRescan('500')
    matching.match('500', '1004', 'Foo 001 (2020).cbz')
    assert issue('1004')['Location'] == 'Foo 001 (2020).cbz'
    assert matching.unmatch('500', '1004')['ok']
    assert issue('1004')['forced_file'] == 0
    assert issue('1001')['Location'] == 'Foo 001 (2020).cbz' and issue('1001')['Status'] == 'Downloaded'


@pytest.mark.unit
def test_a_match_whose_file_is_gone_is_dropped(series):
    updater.forceRescan('500')
    matching.match('500', '1004', 'Bar 007.cbz')
    os.remove(series / 'Bar 007.cbz')
    updater.forceRescan('500')
    assert issue('1004')['forced_file'] == 0
    assert issue('1004')['Status'] == 'Archived'


@pytest.mark.unit
def test_only_files_in_the_series_folder_can_be_matched(series):
    assert not matching.match('500', '1004', '../../etc/passwd')['ok']
    assert not matching.match('500', '9999', 'Bar 007.cbz')['ok']
    assert not matching.match('501', '1004', 'Bar 007.cbz')['ok']


@pytest.mark.unit
def test_a_cover_is_only_made_for_a_file_in_the_series_folder(series, monkeypatch):
    from mylar import attention
    made = []
    monkeypatch.setattr(attention, 'cover_of', lambda path: made.append(path) or path)
    assert matching.cover('500', 'Bar 007.cbz') == str(series / 'Bar 007.cbz')
    assert matching.cover('500', '../Foo (2020)/Bar 007.cbz') is None
    assert matching.cover('501', 'Bar 007.cbz') is None
    assert made == [str(series / 'Bar 007.cbz')]


@pytest.mark.unit
def test_files_waiting_in_needs_attention_for_this_series_are_listed(series, monkeypatch):
    from mylar import attention
    listed = [{'path': '/dl/Foo 004.cbz', 'name': 'Foo 004.cbz', 'size': 9, 'modified': 5.0, 'in_library': False, 'job': None,
               'parsed': {'issue': '004'}, 'matches': [{'comicid': '500', 'issueid': '1004', 'number': '4'}]},
              {'path': '/dl/Other 001.cbz', 'name': 'Other 001.cbz', 'size': 9, 'modified': 5.0, 'in_library': False, 'job': None,
               'parsed': {'issue': '001'}, 'matches': [{'comicid': '777', 'issueid': '1', 'number': '1'}]}]
    monkeypatch.setattr(attention, 'items', lambda: listed)
    assert matching.waiting('500') == [{'path': '/dl/Foo 004.cbz', 'name': 'Foo 004.cbz', 'size': 9, 'modified': 5,
                                        'reads_as': '004', 'issueid': '1004', 'number': '4'}]


def right_series(folder, n=4):
    d = db.DBConnection()
    d.action("INSERT INTO comics (ComicID, ComicName, ComicYear, ComicLocation, ComicPublisher, Type, Status, Total, Have) "
             "VALUES ('600', 'Foo', '2019', ?, 'DC', 'Print', 'Active', ?, 0)", [str(folder), n])
    for i in range(1, n + 1):
        d.action("INSERT INTO issues (IssueID, ComicID, ComicName, Issue_Number, Int_IssueNumber, IssueDate, Status) "
                 "VALUES (?, '600', 'Foo', ?, ?, '2019-0%s-01', 'Skipped')" % i, ['200%s' % i, str(i), i * 1000])


@pytest.mark.unit
def test_wrong_series_moves_the_files_and_matches_them_in_the_right_one(series, tmp_path):
    right = tmp_path / 'library' / 'Foo (2019)'
    right_series(right)
    got = matching.move_to('500', '600')
    assert got['ok'] and got['moved'] == 4 and got['kept'] == []
    assert sorted(os.listdir(right)) == ['Bar 007.cbz', 'Foo 001 (2020).cbz', 'Foo 002 (2020).cbz', 'weird scan.cbz']
    assert os.listdir(series) == []
    assert issue('2001')['Status'] == 'Downloaded' and issue('2002')['Status'] == 'Downloaded'
    assert issue('1001')['Status'] != 'Downloaded'
    # the wrong series is left for the user to remove
    assert db.DBConnection().selectone("SELECT ComicID FROM comics WHERE ComicID='500'").fetchone() is not None


@pytest.mark.unit
def test_wrong_series_keeps_a_file_whose_name_is_taken(series, tmp_path):
    right = tmp_path / 'library' / 'Foo (2019)'
    right_series(right)
    comic_file(right / 'Foo 001 (2020).cbz')
    got = matching.move_to('500', '600')
    assert got['ok'] and got['moved'] == 3 and got['kept'] == ['Foo 001 (2020).cbz']
    assert os.path.exists(series / 'Foo 001 (2020).cbz')


@pytest.mark.unit
def test_wrong_series_needs_a_different_series_with_its_issues(series, tmp_path):
    assert matching.move_to('500', '500')['ok'] is False
    assert matching.move_to('500', '999')['ok'] is False
    db.DBConnection().action("INSERT INTO comics (ComicID, ComicName, ComicLocation, Status) VALUES ('700', 'Foo', ?, 'Loading')",
                             [str(tmp_path / 'x')])
    got = matching.move_to('500', '700')
    assert got['ok'] is False and 'still being added' in got['note']
    assert len(os.listdir(series)) == 4
