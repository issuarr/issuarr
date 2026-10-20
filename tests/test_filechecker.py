import pytest
import csv
from pathlib import Path
import mylar
from mylar import filechecker


def empty_string_to_none(input):
    return None if input == '' else input


def none_string_to_none(input):
    return None if input == 'None' else input


def load_filename_parsing_tests():
    test_filechecker_data = Path(Path(__file__).parents[0], "data", "filename_tests.csv")

    test_list = []

    with open(test_filechecker_data) as csvfile:
        reader = csv.DictReader(csvfile, delimiter=',', quotechar='"', )
        entry_counter = 0
        for entry in reader:
            entry_counter += 1
            test_id = f"{entry_counter:03}:{entry['filename']}"
            
            test_list.append(
                pytest.param(entry['filename'], entry['series'], none_string_to_none(entry['issue']),
                             none_string_to_none(entry['year']), none_string_to_none(entry['volume']),
                             (entry['xfail'].lower() == "true"), id=test_id))
            # Retaining for reference - alternative approach to expected failures to report them (and unexpected passes) but not
            # fail the suite.
            # if entry['xfail'].lower() == "true":
            #     test_list.append(
            #         pytest.param(entry['filename'], entry['series'], none_string_to_none(entry['issue']),
            #                      none_string_to_none(entry['year']), none_string_to_none(entry['volume']),
            #                      True, id=test_id, marks=pytest.mark.xfail(reason=entry['testnotes'])))
            # else:
            #     test_list.append(
            #         pytest.param(entry['filename'], entry['series'], none_string_to_none(entry['issue']),
            #                      none_string_to_none(entry['year']), none_string_to_none(entry['volume']),
            #                      False, id=test_id))

    return test_list


@pytest.mark.parametrize("filename,series,issue,year,volume,xfail", load_filename_parsing_tests())
@pytest.mark.unit
def test_manual_filename_parsing(monkeypatch, filename, series, issue, year, volume, xfail):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "IGNORE_SEARCH_WORDS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)

    fc_obj = filechecker.FileChecker(file=filename, justparse=True, manual=True)
    parsed = fc_obj.parseit(path='/dummypath/', filename=filename)

    # Rather than multiple asserts and early exit, checks all at once (skipping blanks)
    if xfail:
        assert ((parsed['series_name'] .lower(),
                None if volume is None else parsed['series_volume'],
                None if year is None else parsed['issue_year'],
                None if issue is None else parsed['issue_number'])
                !=
                (series.lower(),
                volume,
                year,
                issue))
    else:
        assert ((parsed['series_name'] .lower(),
                None if volume is None else parsed['series_volume'],
                None if year is None else parsed['issue_year'],
                None if issue is None else parsed['issue_number'])
                ==
                (series.lower(),
                volume,
                year,
                issue))



@pytest.mark.unit
@pytest.mark.parametrize("filename,issue", [
    ("American Vampire 1976 007.cbz", "007"),
    ("American Vampire 1976 001.cbz", "001"),
    ("American Vampire 1976 001 (2020).cbz", "001"),
    ("American Vampire 1976 #1.cbz", "1"),
    ("American Vampire 1976 v1 001 (2020).cbz", "001"),
])
def test_series_title_with_trailing_year_retained_when_watchcomic_known(monkeypatch, filename, issue):
    # Some real titles end in a bare year ("American Vampire 1976"). When the known series name
    # (watchcomic) says so, the year stays part of the title instead of being dropped.
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "IGNORE_SEARCH_WORDS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)
    fc_obj = filechecker.FileChecker(watchcomic="American Vampire 1976", file=filename, justparse=True, manual=True)
    parsed = fc_obj.parseit(path='/dummypath/', filename=filename)
    assert parsed['series_name'] == "American Vampire 1976"
    assert parsed['issue_number'] == issue


@pytest.mark.unit
def test_launch_year_still_dropped_when_not_in_title(monkeypatch):
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "IGNORE_SEARCH_WORDS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)
    filename = "Batman 2016 001.cbz"
    fc_obj = filechecker.FileChecker(watchcomic="Batman", file=filename, justparse=True, manual=True)
    parsed = fc_obj.parseit(path='/dummypath/', filename=filename)
    assert parsed['series_name'] == "Batman"
    assert parsed['issue_number'] == "001"


@pytest.mark.unit
@pytest.mark.parametrize("watchcomic,filename,issue", [
    ("Cyberpunk 2077", "Cyberpunk 2077 001.cbz", "001"),
    ("Cyberpunk 2077", "Cyberpunk 2077 001 (2020).cbz", "001"),
    ("7174 Annual", "7174 Annual 001.cbz", "001"),
    ("7174 Annual", "7174 Annual.cbz", None),
    ("100 Bullets", "100 Bullets 012.cbz", "012"),
])
def test_numeric_series_title_matches_known_series(monkeypatch, watchcomic, filename, issue):
    # Titles that are or contain a number (#2): the number stays in the series name and the
    # file still matches the series on rescan. A file with no issue number matches too; the
    # rescan decides which issue it is (updater.numberless_issue).
    monkeypatch.setattr(mylar, "LOG_LEVEL", 0, raising=False)
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "IGNORE_SEARCH_WORDS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "ANNUALS_ON", False, raising=False)
    fc_obj = filechecker.FileChecker(dir='/dummypath/', watchcomic=watchcomic)
    parsed = fc_obj.parseit('/dummypath/', filename)
    assert parsed['process_status'] == 'match'
    assert parsed['series_name'] == watchcomic
    assert parsed['justthedigits'] == issue


@pytest.mark.unit
@pytest.mark.parametrize("filename,issue", [
    ("Detective Comics 659 ctc (Early 05-1993).cbr", "659"),
    ("Detective Comics 868 ctc (2010) (F).cbr", "868"),
    ("Detective Comics 541 ctc (1984).cbr", "541"),
    ("Detective Comics 426 36p ctc (08-1972).cbz", "426"),
    ("Detective Comics 426 36p (08-1972).cbz", "426"),
])
def test_scan_tag_after_the_issue_number_is_ignored(monkeypatch, filename, issue):
    # 'ctc' (cover to cover) after a bare issue number was glued to it ('659ctc'), so the whole
    # name read as the series and the file never matched on rescan (Detective Comics, 2026-10-19).
    monkeypatch.setattr(mylar, "LOG_LEVEL", 0, raising=False)
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "IGNORE_SEARCH_WORDS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "ANNUALS_ON", False, raising=False)
    fc_obj = filechecker.FileChecker(dir='/dummypath/', watchcomic="Detective Comics")
    parsed = fc_obj.parseit('/dummypath/', filename)
    assert parsed['process_status'] == 'match'
    assert parsed['series_name'] == "Detective Comics"
    assert parsed['justthedigits'] == issue


@pytest.mark.unit
@pytest.mark.parametrize("watchcomic,filename", [
    ("Predator vs. Wolverine", "Predator Versus Wolverine 001 (2023).cbz"),
    ("Predator vs. Wolverine", "Predator vs Wolverine 001 (2023).cbz"),
    ("DC versus Marvel", "DC vs. Marvel 001 (1996).cbz"),
    ("DC versus Marvel", "DC Versus Marvel 001 (1996).cbz"),
])
def test_versus_and_vs_are_the_same_word(monkeypatch, watchcomic, filename):
    # titles use 'versus', 'vs' and 'vs.' interchangeably, so a file named one way matches a series named another
    monkeypatch.setattr(mylar, "LOG_LEVEL", 0, raising=False)
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "IGNORE_SEARCH_WORDS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "ANNUALS_ON", False, raising=False)
    fc_obj = filechecker.FileChecker(dir='/dummypath/', watchcomic=watchcomic)
    parsed = fc_obj.parseit('/dummypath/', filename)
    assert parsed['process_status'] == 'match'


@pytest.mark.unit
@pytest.mark.parametrize("watchcomic,filename,issue,booktype", [
    # the book's number before the label: it was lost to an assumed volume 1
    ("Batman", "Batman 3 (TPB) (2013).cbz", "3", "TPB"),
    # (HC) and (GN) in brackets, and a Vol. number with them: it was read as no number at all
    ("Batman", "Batman Vol. 3 (HC) (2013).cbz", "3", "HC"),
    ("Batman", "Batman Vol. 03 - Death of the Family (2013) (HC) (Digital).cbz", "03", "HC"),
    ("Batman", "Batman 3 (HC) (2013).cbz", "3", "HC"),
    ("Batman", "Batman 003 (2016) (GN).cbz", "003", "GN"),
    # unchanged
    ("Batman", "Batman TPB 3 (2013).cbz", "3", "TPB"),
    ("Batman", "Batman v3 (TPB) (2013).cbz", "3", "TPB"),
    ("Batman", "Batman TPB (2013).cbz", "1", "TPB"),
    ("Batman", "Batman (TPB) (2013).cbz", "1", "TPB"),
    ("Saga", "Saga Vol 07 (2017) (Digital TPB).cbz", "07", "TPB"),
    ("100 Bullets", "100 Bullets (TPB) (2000).cbz", "1", "TPB"),
    ("Spider-Man 2099", "Spider-Man 2099 (TPB) (2019).cbz", "1", "TPB"),
    ("Cyberpunk 2077", "Cyberpunk 2077 (TPB) (2020).cbz", "1", "TPB"),
])
def test_collected_edition_number_next_to_its_label(monkeypatch, watchcomic, filename, issue, booktype):
    # In a TPB, HC or GN series the book's number is its issue; a file read without one counts as #1.
    monkeypatch.setattr(mylar, "LOG_LEVEL", 0, raising=False)
    monkeypatch.setattr(mylar, "CONFIG", mylar.config.Config("./nothing"))
    monkeypatch.setattr(mylar.CONFIG, "IGNORE_SEARCH_WORDS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "CUSTOM_ISSUE_EXCEPTIONS", [], raising=False)
    monkeypatch.setattr(mylar.CONFIG, "ANNUALS_ON", False, raising=False)
    fc_obj = filechecker.FileChecker(dir='/dummypath/', watchcomic=watchcomic)
    parsed = fc_obj.parseit('/dummypath/', filename)
    assert parsed['process_status'] == 'match'
    assert parsed['justthedigits'] == issue
    assert parsed['booktype'] == booktype
