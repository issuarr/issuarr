"""Files with no ComicInfo.xml get one from the stored issue info, matching what tagging writes."""
import types
import xml.etree.ElementTree as ET
import zipfile

import pytest

import mylar
from mylar import cmtagmylar, quicktag, webp

ROW = {'IssueID': '113826', 'Issue_Number': '1', 'IssueName': None, 'IssueDate': '2007-07-01', 'ReleaseDate': '0000-00-00',
       'ComicName': 'Terminator 2: Infinity', 'ComicYear': '2007', 'ComicVersion': None,
       'ComicPublisher': 'Dynamite Entertainment', 'Total': '7', 'AgeRating': None}


class FakeDB:
    def __init__(self, row):
        self.row = row

    def selectone(self, query, args=None):
        return types.SimpleNamespace(fetchone=lambda: self.row if 'FROM issues' in query else None)


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(
        ENABLE_META=True, CMTAG_VOLUME=True, CMTAG_START_YEAR_AS_VOLUME=True, SETDEFAULTVOLUME=False,
        CT_NOTES_FORMAT='Issue ID'), raising=False)
    monkeypatch.setattr(cmtagmylar, 'series_publisher', lambda issueid: (None, None))
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)


def cbz(path, tagged=False):
    with zipfile.ZipFile(path, 'w') as z:
        for n in range(3):
            z.writestr('%03d.jpg' % n, b'page')
        if tagged:
            z.writestr('ComicInfo.xml', '<ComicInfo><Series>Kept</Series></ComicInfo>')
    return str(path)


def fields(path):
    with zipfile.ZipFile(path) as z:
        return {el.tag: el.text for el in ET.fromstring(z.read('ComicInfo.xml'))}


def test_build_matches_what_comictagger_wrote():
    out = {el.tag: el.text for el in ET.fromstring(quicktag.build(ROW))}
    # the fields Kavita groups by, as ComicTagger wrote them into the series' tagged issues
    assert {k: out.get(k) for k in ('Series', 'Number', 'Count', 'Volume', 'Publisher', 'Year', 'Month', 'Day')} == {
        'Series': 'Terminator 2: Infinity', 'Number': '1', 'Count': '7', 'Volume': '2007',
        'Publisher': 'Dynamite Entertainment', 'Year': '2007', 'Month': '7', 'Day': '1'}
    assert '[Issue ID 113826]' in out['Notes']
    assert 'Title' not in out


def test_build_uses_the_series_volume_when_start_year_is_off():
    mylar.CONFIG.CMTAG_START_YEAR_AS_VOLUME = False
    out = {el.tag: el.text for el in ET.fromstring(quicktag.build(dict(ROW, ComicVersion='v2')))}
    assert out['Volume'] == '2'


def test_build_uses_the_cvdb_notes_form_and_the_imprints_parent(monkeypatch):
    mylar.CONFIG.CT_NOTES_FORMAT = 'CVDB'
    monkeypatch.setattr(cmtagmylar, 'series_publisher', lambda issueid: ('DC Comics', 'Vertigo'))
    out = {el.tag: el.text for el in ET.fromstring(quicktag.build(dict(ROW, IssueName='Time & Again')))}
    assert '[CVDB113826]' in out['Notes']
    assert (out['Publisher'], out['Imprint'], out['Title']) == ('DC Comics', 'Vertigo', 'Time & Again')


def test_fill_writes_tags_into_an_untagged_file(tmp_path):
    path = cbz(tmp_path / 'T2 #01.cbz')
    assert quicktag.fill(path, FakeDB(ROW)) == path
    assert fields(path)['Series'] == 'Terminator 2: Infinity'
    with zipfile.ZipFile(path) as z:
        assert sorted(z.namelist()) == ['000.jpg', '001.jpg', '002.jpg', 'ComicInfo.xml']


def test_fill_leaves_tagged_files_unknown_files_and_tagging_off_alone(tmp_path):
    tagged = cbz(tmp_path / 'tagged.cbz', tagged=True)
    assert not quicktag.fill(tagged, FakeDB(ROW))
    assert fields(tagged) == {'Series': 'Kept'}
    assert not quicktag.fill(cbz(tmp_path / 'stray.cbz'), FakeDB(None))
    mylar.CONFIG.ENABLE_META = False
    off = cbz(tmp_path / 'off.cbz')
    assert not quicktag.fill(off, FakeDB(ROW))
    assert quicktag.fill(off, FakeDB(ROW), force=True) == off    # asked for, so tagging being off doesn't matter


def test_fill_makes_a_cbr_a_cbz_only_when_it_will_tag_it(monkeypatch, tmp_path):
    monkeypatch.setattr(webp, '_relocate', lambda old, new: None)
    cbr = cbz(tmp_path / 'T2 #03.cbr')                         # a zip named .cbr
    mylar.CONFIG.ENABLE_META = False
    assert not quicktag.fill(cbr, FakeDB(ROW))
    assert not quicktag.fill(cbr, FakeDB(None), force=True)    # no issue to tag it as
    assert (tmp_path / 'T2 #03.cbr').exists()
    out = quicktag.fill(cbr, FakeDB(ROW), force=True)
    assert out == str(tmp_path / 'T2 #03.cbz') and not (tmp_path / 'T2 #03.cbr').exists()
    assert fields(out)['Number'] == '1'


def test_fill_leaves_a_file_webp_is_converting(tmp_path):
    path = cbz(tmp_path / 'T2 #01.cbz')
    with webp.claim(path) as mine:
        assert mine
        assert not quicktag.fill(path, FakeDB(ROW))
    assert not quicktag.tagged(path)
