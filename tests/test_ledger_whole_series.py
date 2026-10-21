"""Library > Trades: Replaces a whole series finds single-issue series whose every issue sits in trades you have."""
import pytest

from mylar import ledger


class FakeDB:
    def __init__(self, locations, annuals=()):
        self.locations, self.annuals = locations, annuals

    def select(self, sql, *a):
        if 'FROM annuals' in sql:
            return [{'ComicID': c} for c in self.annuals]
        return [{'ComicID': c, 'ComicLocation': l} for c, l in self.locations.items()]


def comic(name, kind):
    return {'ComicName': name, 'ComicYear': '2009', 'Corrected_Type': None, 'Type': kind}


def issue(cid, status, location=None):
    return {'ComicID': cid, 'Status': status, 'Location': location}


def trade(iid, found, status='Downloaded'):
    return {'row': {'TradeIssueID': iid}, 'trade': {'Status': status, 'Location': iid + '.cbz'}, 'found': found}


@pytest.fixture
def lib(tmp_path):
    for cid in ('S', 'T'):
        (tmp_path / cid).mkdir()
    for iid in ('t1', 't2'):
        (tmp_path / 'T' / (iid + '.cbz')).write_text('x')
    comics = {'S': comic('Noir', 'Print'), 'T': comic('Noir', 'TPB')}
    # The singles series has a gap (#2 wanted, #3 skipped): it still counts as replaced.
    status = {'s1': issue('S', 'Downloaded'), 's2': issue('S', 'Wanted'), 's3': issue('S', 'Skipped'),
              't1': issue('T', 'Downloaded', 't1.cbz'), 't2': issue('T', 'Downloaded', 't2.cbz')}
    locations = {'S': str(tmp_path / 'S'), 'T': str(tmp_path / 'T')}
    return comics, status, locations


@pytest.mark.unit
def test_trades_together_replace_a_series_with_gaps(lib):
    comics, status, locations = lib
    w = ledger._whole_series(FakeDB(locations), status, comics, [trade('t1', ['s1', 's2']), trade('t2', ['s3'])])
    assert len(w) == 1
    assert w[0]['cid'] == 'S' and w[0]['issues'] == 3 and w[0]['have'] == 1 and not w[0]['shared']
    assert w[0]['cover'] == {'t1': ['s1', 's2'], 't2': ['s3']}


@pytest.mark.unit
def test_an_issue_no_trade_collects_means_not_replaced(lib):
    comics, status, locations = lib
    assert ledger._whole_series(FakeDB(locations), status, comics, [trade('t1', ['s1', 's2'])]) == []


@pytest.mark.unit
def test_trades_you_dont_have_or_whose_file_is_gone_dont_count(lib, tmp_path):
    comics, status, locations = lib
    assert ledger._whole_series(FakeDB(locations), status, comics, [trade('t1', ['s1', 's2']), trade('t2', ['s3'], 'Wanted')]) == []
    (tmp_path / 'T' / 't2.cbz').unlink()
    assert ledger._whole_series(FakeDB(locations), status, comics, [trade('t1', ['s1', 's2']), trade('t2', ['s3'])]) == []


@pytest.mark.unit
def test_series_with_tracked_annuals_are_left_out(lib):
    comics, status, locations = lib
    assert ledger._whole_series(FakeDB(locations, annuals=['S']), status, comics, [trade('t1', ['s1', 's2', 's3'])]) == []


@pytest.mark.unit
def test_a_folder_shared_with_the_trades_is_flagged_so_it_is_never_deleted(lib, tmp_path):
    comics, status, locations = lib
    locations['T'] = locations['S']
    (tmp_path / 'S' / 't1.cbz').write_text('x')
    w = ledger._whole_series(FakeDB(locations), status, comics, [trade('t1', ['s1', 's2', 's3'])])
    assert w[0]['shared']


@pytest.mark.unit
def test_trade_series_themselves_are_never_offered(lib):
    comics, status, locations = lib
    comics['S']['Corrected_Type'] = 'HC'
    assert ledger._whole_series(FakeDB(locations), status, comics, [trade('t1', ['s1', 's2', 's3'])]) == []


@pytest.mark.unit
def test_the_page_keeps_shared_folders_when_removing():
    src = open('data/js/ledger.js').read()
    assert "delete_dir: files && (keep || []).indexOf(cid) < 0 ? 1 : ''" in src
