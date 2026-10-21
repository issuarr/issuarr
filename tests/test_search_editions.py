"""Which result editions a series accepts in search (search_filer.edition_fits).

GetComics posts a collected edition as a TPB, HC, Omnibus or Collection whatever ComicVine calls
it, so a series that is a collected edition takes any of them (Predator vs. Wolverine, 2026-10-19).
"""
import pytest

from mylar.search_filer import edition_fits


@pytest.mark.unit
@pytest.mark.parametrize('booktype,parsed', [
    ('Print', 'issue'), ('Digital', 'issue'), (None, 'issue'),
    ('One-Shot', 'issue'), ('One-Shot', 'TPB/GN/HC/One-Shot'),
    ('TPB', 'TPB'), ('HC', 'HC'), ('GN', 'GN'), ('TPB', 'TPB/GN/HC/One-Shot'),
])
def test_matching_editions_are_accepted(booktype, parsed):
    assert edition_fits(booktype, parsed)


@pytest.mark.unit
@pytest.mark.parametrize('booktype,parsed', [
    ('Print', 'TPB'), ('Print', 'HC'), ('Digital', 'TPB'), ('One-Shot', 'TPB'), ('One-Shot', 'HC'),
])
def test_a_collected_edition_is_not_an_issue(booktype, parsed):
    assert not edition_fits(booktype, parsed, title='Predator Vs. Wolverine (TPB) (2024)')


@pytest.mark.unit
@pytest.mark.parametrize('booktype,parsed,title', [
    ('TPB', 'HC', 'Predator Vs. Wolverine (HC) (2024)'),
    ('HC', 'TPB', 'Predator Vs. Wolverine (TPB) (2024)'),
    ('GN', 'TPB', 'Saga (TPB) (2012)'),
    ('TPB', 'issue', 'Captain America Epic Collection - Bucky Reborn (2017)'),
    ('TPB', 'issue', 'Avengers Omnibus 01 (2021)'),
    ('HC', 'issue', 'Spider-Man - The Complete Collection 1 (2019)'),
])
def test_a_collected_series_takes_any_collected_edition(booktype, parsed, title):
    assert edition_fits(booktype, parsed, title=title)


@pytest.mark.unit
def test_a_collected_series_still_turns_single_issues_away():
    assert not edition_fits('TPB', 'issue', title='Predator vs. Wolverine #1 (2023)')
    assert not edition_fits('HC', 'issue', title='Saga 054 (2018)')


@pytest.mark.unit
def test_accept_any_edition_takes_everything():
    assert edition_fits('Print', 'TPB', ignore_booktype=True)
    assert edition_fits('One-Shot', 'HC', ignore_booktype=True)


@pytest.mark.unit
def test_a_run_of_issues_with_its_tpbs_suits_issue_and_tpb_searches():
    # 'X-Men Vol. 3 #1 - 41 + TPBs' was thrown out when searching a Print series
    from mylar.search_filer import edition_fits
    for booktype in (None, 'Print', 'Digital', 'TPB'):
        assert edition_fits(booktype, 'issue+TPB')
    assert not edition_fits('Print', 'TPB')
