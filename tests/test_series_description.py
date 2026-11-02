"""Series descriptions keep their full text unless they have a "Collected" section (issue #266)."""
from mylar.importer import strip_collected


def test_description_without_collected_is_kept_whole():
    assert strip_collected('Some description') == 'Some description'


def test_description_is_cut_at_collected_section():
    assert strip_collected('The story so far. Collected Editions: Vol 1') == 'The story so far. '


def test_empty_and_missing_descriptions():
    assert strip_collected('') == ''
    assert strip_collected('None') is None
    assert strip_collected(None) is None
