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
