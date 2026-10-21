"""Series page: Related TPBs links trades through the single-issue series they collect."""
import pytest

from mylar import ledger


@pytest.mark.unit
def test_spans_read_as_runs_in_the_series_own_order():
    labels = ['40', '41', '42', '43', '44', '45', '46', '47']
    assert ledger._spans([2, 3, 4, 5, 7], labels) == '#42-45, #47'
    assert ledger._spans([0], labels) == '#40'


class FakeDB:
    ISSUES = {'S': [('s%d' % n, str(n)) for n in range(1, 13)], 'V7': [('v7', '1')], 'V1': [('v1', '1')]}

    def select(self, sql, args=()):
        if 'WHERE ComicID=?' in sql:
            return [{'IssueID': i, 'Issue_Number': n} for i, n in self.ISSUES[args[0]]]
        return [{'IssueID': i, 'IssueName': 'Volume ' + i[1:]} for i in args]


@pytest.fixture
def lib(monkeypatch):
    comics = {'S': {'ComicName': 'Hulk', 'ComicYear': '2009', 'Corrected_Type': None, 'Type': 'Print'},
              'V7': {'ComicName': 'Hulk: Seven', 'ComicYear': '2011', 'Corrected_Type': None, 'Type': 'TPB'},
              'V1': {'ComicName': 'Hulk: One', 'ComicYear': '2010', 'Corrected_Type': 'HC', 'Type': 'Print'}}
    status = {'s%d' % n: {'ComicID': 'S', 'Status': 'Downloaded'} for n in range(1, 13)}
    status.update({'v7': {'ComicID': 'V7', 'Issue_Number': '1', 'Status': 'Downloaded'},
                   'v1': {'ComicID': 'V1', 'Issue_Number': '1', 'Status': 'Wanted'}})
    trades = [{'row': {'TradeIssueID': 'v7', 'TradeComicID': 'V7'}, 'trade': status['v7'], 'comic': comics['V7'], 'found': ['s7', 's8', 's9']},
              {'row': {'TradeIssueID': 'v1', 'TradeComicID': 'V1'}, 'trade': status['v1'], 'comic': comics['V1'], 'found': ['s1', 's2', 's3']}]
    monkeypatch.setattr(ledger.db, 'DBConnection', FakeDB)
    monkeypatch.setattr(ledger, '_lookups', lambda db: (status, comics))
    monkeypatch.setattr(ledger, '_trades', lambda db, s, c: trades)
    monkeypatch.setattr(ledger, 'status_summary', lambda db: {'stored': 2})


@pytest.mark.unit
def test_a_singles_series_lists_its_trades_in_issue_order(lib):
    d = ledger.related('S')
    assert not d['trade'] and len(d['groups']) == 1
    assert [(t['name'], t['issues'], t['title']) for t in d['groups'][0]['trades']] == [('Hulk: One', '#1-3', 'Volume 1'), ('Hulk: Seven', '#7-9', 'Volume 7')]


@pytest.mark.unit
def test_a_one_issue_trade_links_to_the_other_volumes_of_the_same_series(lib):
    d = ledger.related('V7')
    assert d['trade'] and [g['cid'] for g in d['groups']] == ['S']
    assert [(t['cid'], t['this']) for t in d['groups'][0]['trades']] == [('V1', False), ('V7', True)]
