"""The book type a ComicVine volume gets from its description (Predator vs. Wolverine, 2026-10-19).

"Collecting PREDATOR VS. WOLVERINE #1-4" wasn't read as a collected edition, so the one-issue
volume became a One-Shot and the search turned the TPB it found away ("Booktypes do not match").
"""
import types

import pytest

import mylar
from mylar import cv


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(CV_VERIFY=False), raising=False)


def booktype(desc, deck='None'):
    return cv.get_imprint_volume_and_booktype(False, '2024', 'Marvel', None, desc, deck)['Type']


@pytest.mark.unit
@pytest.mark.parametrize('desc', ['Collecting PREDATOR VS. WOLVERINE #1-4.',
                                  'Collects Uncanny X-Men #1-6.',
                                  'Collected edition of the first six issues.',
                                  'Epic Collection collecting Captain America #120-138',
                                  # digital collections are posted as TPBs ("Hulk vs. The Avengers (TPB)")
                                  'Digital collection collecting the Korvac Quest chapters from Fantastic Four',
                                  'Digital collection of Avengers #49, Black Panther #39'])
def test_a_description_that_collects_issues_is_a_trade_paperback(desc):
    assert booktype(desc) == 'TPB'


@pytest.mark.unit
@pytest.mark.parametrize('desc', ['Ten issue series continuing from the Outlawed one shot.',
                                  'Five issue mini-series continuing from the Outlawed one shot.',
                                  'The story continues from The New Golden Age one-shot.'])
def test_a_series_that_follows_a_one_shot_is_not_one(desc):
    assert booktype(desc) == 'Print'


@pytest.mark.unit
@pytest.mark.parametrize('desc,expected', [('A one-shot depicting the Winter Guard and the new second Darkstar.', 'One-Shot'),
                                           ('A digital-first series from Marvel Unlimited.', 'Digital'),
                                           ('The collector returns in a new series.', 'Print')])
def test_other_descriptions_keep_their_type(desc, expected):
    assert booktype(desc) == expected
