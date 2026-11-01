"""A collected edition's volume number ("v3") is its number in a TPB, HC or GN series, and GN counts as a collected edition."""
import pytest

from mylar import editions, filechecker, updater
from tests.test_editions import library, comic_file, status  # noqa: F401


@pytest.mark.unit
@pytest.mark.parametrize("name", [
    "30 Days of Night (2011) v03 - Run Alice Run (2013) (digital) (Dr.Vink).cbz",
    "30 Days of Night v03 - Run Alice Run (2013) (digital).cbz",
    "30 Days of Night v3 (2013).cbz",
    "30 Days of Night GN v3 (2013).cbz",
    "30 Days of Night OGN v3 (2013).cbz",
    "30 Days of Night TPB v3 (2013).cbz",
    "30 Days of Night v3 GN (2013).cbz",
])
def test_recheck_reads_v3_as_volume_3_of_a_tpb_series(library, name):
    folder = library('700', '30 Days of Night', 'TPB', 3)
    comic_file(folder / name)
    updater.forceRescan('700')
    assert [status(i) for i in ('70001', '70002', '70003')] == ['Wanted', 'Wanted', 'Downloaded']


@pytest.mark.unit
def test_recheck_matches_volumes_of_a_gn_series(library):
    folder = library('800', 'Saga', 'GN', 3)
    comic_file(folder / 'Saga GN Vol 2 (2017).cbz')
    updater.forceRescan('800')
    assert [status(i) for i in ('80001', '80002', '80003')] == ['Wanted', 'Downloaded', 'Wanted']


@pytest.mark.unit
def test_recheck_keeps_a_gn_out_of_a_series_of_single_issues(library):
    folder = library('900', 'Saga', 'Print', 3)
    comic_file(folder / 'Saga GN v02 (2017).cbz')
    comic_file(folder / 'Saga OGN v03 (2017).cbz')
    updater.forceRescan('900')
    assert [status(i) for i in ('90001', '90002', '90003')] == ['Wanted', 'Wanted', 'Wanted']


@pytest.mark.unit
@pytest.mark.parametrize("name", ["Saga GN v02 (2017).cbz", "Saga OGN v02 (2017).cbz",
                                  "Saga Graphic Novel v02 (2017).cbz", "Saga v02 (2017) (GN).cbz"])
def test_gn_is_a_collected_edition(name):
    assert editions.collected(name)


@pytest.mark.unit
@pytest.mark.parametrize("name,booktype", [("Saga GN v02 (2017).cbz", "GN"), ("Saga OGN v02 (2017).cbz", "GN"),
                                           ("Saga v02 (2017) (GN).cbz", "GN"), ("Saga TPB v02 (2017).cbz", "TPB")])
def test_gn_and_ogn_give_the_gn_book_type(library, name, booktype):
    p = filechecker.FileChecker(file=name).listFiles()
    assert p['series_name'] == 'Saga' and p['booktype'] == booktype
