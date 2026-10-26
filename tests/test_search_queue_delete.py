import queue

import pytest

import mylar
from mylar import search


@pytest.mark.unit
def test_deleting_a_series_takes_its_issues_out_of_the_search_queue(monkeypatch):
    # 2026-10-20: 66 Savage Dragon searches came up after the series was deleted, each dropped
    # only after a lookup, holding up the issues behind them
    q = queue.Queue()
    for n, cid in enumerate(['21', '21', '777', '21', '888']):
        q.put({'comicid': cid, 'issueid': str(n), 'comicname': 'X', 'issuenumber': str(n)})
    q.put('exit')
    monkeypatch.setattr(mylar, 'SEARCH_QUEUE', q, raising=False)
    assert search.drop_series(21) == 3
    left = list(q.queue)
    assert [x['comicid'] for x in left if isinstance(x, dict)] == ['777', '888'] and left[-1] == 'exit'
    assert search.drop_series('21') == 0
    for _ in left:
        q.get_nowait()
        q.task_done()
    q.join()  # the dropped items don't leave the queue waiting forever


@pytest.mark.unit
def test_deleting_the_series_being_searched_stops_its_search(monkeypatch):
    monkeypatch.setattr(mylar, 'SEARCH_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(mylar, 'SEARCH_CURRENT', {'comicid': '21', 'issueid': '5', 'comicname': 'Uncanny X-Men',
                                                  'issuenumber': '5'}, raising=False)
    monkeypatch.setattr(mylar, 'SEARCH_ABORT', None, raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    search.drop_series('777')  # another series: the search goes on
    search.check_aborted('21')
    search.drop_series(21)
    with pytest.raises(search.SearchAborted):
        search.check_aborted('21')
    with pytest.raises(search.SearchAborted):
        search.search_the_matrix({'ComicID': 21})  # before the next provider is asked
    search.check_aborted('777')
    search.check_aborted(None)
