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
