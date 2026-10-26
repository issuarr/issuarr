"""Issue descriptions from a series refresh are kept as plain text for stored-info tags."""
from mylar import cv


def test_summary_text_keeps_paragraphs_and_drops_html():
    html = '<p><em>Marketing Description:</em> Things heat up!</p><p>Line one<br/>line two</p><ul><li>Item</li></ul>'
    assert cv.summary_text(html) == 'Marketing Description: Things heat up!\n\nLine one\nline two\n\nItem'


def test_summary_text_is_none_without_a_description():
    assert cv.summary_text(None) is None
    assert cv.summary_text('  ') is None
    assert cv.summary_text('<p> </p>') is None
