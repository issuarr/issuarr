import queue
import types

import pytest

import mylar
import mylar.search  # noqa: F401 - makes mylar.search available to patch
from mylar.queues import ddl


class FakeGC:
    instances = []
    reply = {'success': True, 'site': 'GC-Media'}

    def __init__(self, query=None, issueid=None, comicid=None, oneoff=False, **kwargs):
        self.jd2 = 'jd2-helper'
        self.calls = []
        FakeGC.instances.append(self)

    def parse_downloadresults(self, id, mainlink, comicinfo=None, packinfo=None, link_type_failure=None):
        self.calls.append({'id': id, 'mainlink': mainlink, 'failed': list(link_type_failure or [])})
        return FakeGC.replies.pop(0) if FakeGC.replies else FakeGC.reply


@pytest.fixture
def failover(monkeypatch):
    FakeGC.instances = []
    FakeGC.reply = {'success': True, 'site': 'GC-Media'}
    FakeGC.replies = []
    FakeGC.posts = []
    monkeypatch.setattr(ddl, 'FAILOVER', {})
    monkeypatch.setattr(ddl.getcomics, 'GC', FakeGC)
    monkeypatch.setattr(ddl.getcomics, 'linked_post', lambda id, comicinfo, skip=(): next((p for p in FakeGC.posts if p not in skip), None))
    gave_up = []
    monkeypatch.setattr(ddl, 'ddl_give_up', lambda myDB, item: gave_up.append(item['id']))
    return gave_up


def item(**kwargs):
    base = {'id': '54429', 'series': 'Age of Ultron', 'site': 'DDL(GetComics)', 'link_type': 'GC-Mega',
            'mainlink': 'https://getcomics.org/marvel/age-of-ultron-1-10ai-2013/', 'comicid': '58436',
            'issueid': '390442', 'oneoff': False, 'comicinfo': None, 'packinfo': None}
    base.update(kwargs)
    return base


@pytest.mark.unit
def test_failed_link_is_skipped_on_the_next_try(failover):
    ddl.handle_failure(None, item(), {'success': False})
    gc = FakeGC.instances[0]
    assert gc.calls == [{'id': '54429', 'mainlink': item()['mainlink'], 'failed': ['GC-Mega']}]
    assert gc.jd2 == 'jd2-helper'
    assert failover == []


@pytest.mark.unit
def test_jd2_give_up_tries_own_downloaders_without_jd2(failover):
    ddl.handle_failure(None, item(), {}, jd2_gave_up=True)
    gc = FakeGC.instances[0]
    assert gc.jd2 is None
    assert gc.calls[0]['failed'] == []


@pytest.mark.unit
def test_item_jd2_gave_up_on_never_goes_back_to_jd2(failover):
    ddl.handle_failure(None, item(), {}, jd2_gave_up=True)
    ddl.handle_failure(None, item(), {'success': False})
    second = FakeGC.instances[1]
    assert second.jd2 is None
    assert second.calls[0]['failed'] == ['GC-Mega']


@pytest.mark.unit
def test_no_links_left_marks_failed(failover):
    FakeGC.reply = {'success': False, 'links_exhausted': ['GC-Mega']}
    ddl.handle_failure(None, item(), {'success': False})
    assert failover == ['54429']


@pytest.mark.unit
def test_exhausted_result_gives_up_without_rereading_the_page(failover):
    ddl.handle_failure(None, item(), {'success': False, 'links_exhausted': ['GC-Main']})
    assert failover == ['54429']
    assert FakeGC.instances == []


@pytest.mark.unit
def test_item_without_mainlink_is_marked_failed(failover):
    ddl.handle_failure(None, item(mainlink=None), {'success': False})
    assert failover == ['54429']
    assert FakeGC.instances == []


@pytest.mark.unit
def test_external_server_failure_marks_issue_failed(failover, monkeypatch):
    marked, deleted = [], []
    monkeypatch.setattr(mylar.search, 'FailedMark', lambda *a, **k: marked.append(a))
    fake_db = types.SimpleNamespace(action=lambda sql, args: deleted.append(args))
    ddl.handle_failure(fake_db, item(site='DDL(External)', link_type='DDL-Ext'), {'success': False, 'filename': 'x.cbz'})
    assert deleted == [['54429']]
    assert marked[0][:3] == ('390442', '58436', '54429')
    assert '54429' not in ddl.FAILOVER


@pytest.mark.unit
def test_items_waiting_for_failover_count_as_queued(monkeypatch):
    monkeypatch.setattr(mylar, 'DDL_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(ddl, 'FAILOVER_QUEUE', queue.Queue())
    ddl.send_to_failover({'id': 'x'}, {'success': False})
    assert 'x' in ddl.waiting_ids()
    assert ddl.waiting_count() == 1


@pytest.mark.unit
def test_same_link_type_failing_twice_gives_up(failover):
    # a source that keeps coming back after it failed would reload the GetComics page forever
    ddl.handle_failure(None, item(link_type='Unknown'), {'success': False})
    ddl.handle_failure(None, item(link_type='Unknown'), {'success': False})
    assert len(FakeGC.instances) == 1
    assert failover == ['54429']


@pytest.mark.unit
def test_cancelled_item_in_failover_is_dropped(failover, monkeypatch):
    monkeypatch.setattr(mylar, 'DDL_CANCEL', {'54429'}, raising=False)
    dropped = []
    monkeypatch.setattr(ddl, 'ddl_cancelled', lambda item, ddzstat=None: dropped.append(item['id']) or True)
    ddl.handle_failure(None, item(), {'success': False})
    assert dropped == ['54429']
    assert FakeGC.instances == []


@pytest.mark.unit
def test_item_in_failover_counts_as_queued_while_handled(failover, monkeypatch):
    monkeypatch.setattr(mylar, 'DDL_QUEUE', queue.Queue(), raising=False)
    monkeypatch.setattr(ddl, 'ACTIVE', set())
    seen = []
    real = FakeGC.parse_downloadresults

    def parse(self, *a, **k):
        seen.append('54429' in ddl.waiting_ids())
        return real(self, *a, **k)
    monkeypatch.setattr(FakeGC, 'parse_downloadresults', parse)
    ddl.handle_failure(None, item(), {'success': False})
    assert seen == [True]
    assert '54429' not in ddl.ACTIVE


class FakeDB:
    def __init__(self):
        self.rows = []

    def upsert(self, table, values, ctrl):
        self.rows.append((table, values, ctrl))


OTHER_POST = 'https://getcomics.org/marvel/age-of-ultron-1-10-2013-fixed/'


@pytest.mark.unit
def test_a_linked_post_is_tried_once_every_link_on_the_post_failed(failover):
    FakeGC.replies = [{'success': False, 'links_exhausted': ['GC-Mega']}, {'success': True, 'site': 'GC-Pixel'}]
    FakeGC.posts = [OTHER_POST]
    myDB = FakeDB()
    ddl.handle_failure(myDB, item(), {'success': False})
    calls = FakeGC.instances[0].calls
    assert [c['mainlink'] for c in calls] == [item()['mainlink'], OTHER_POST]
    assert calls[1]['failed'] == []  # the other post's sources are all new
    assert myDB.rows == [('ddl_info', {'mainlink': OTHER_POST}, {'id': '54429'})]
    assert failover == []


@pytest.mark.unit
def test_on_page_links_come_before_linked_posts(failover):
    FakeGC.posts = [OTHER_POST]
    ddl.handle_failure(FakeDB(), item(), {'success': False})
    assert [c['mainlink'] for c in FakeGC.instances[0].calls] == [item()['mainlink']]


@pytest.mark.unit
def test_gives_up_when_the_linked_post_fails_too(failover):
    FakeGC.reply = {'success': False, 'links_exhausted': []}
    FakeGC.posts = [OTHER_POST]
    ddl.handle_failure(FakeDB(), item(), {'success': False})
    assert [c['mainlink'] for c in FakeGC.instances[0].calls] == [item()['mainlink'], OTHER_POST]
    assert failover == ['54429']


@pytest.mark.unit
def test_linked_posts_are_followed_a_few_times_at_most(failover):
    FakeGC.reply = {'success': False, 'links_exhausted': []}
    FakeGC.posts = ['https://getcomics.org/marvel/post-%s/' % n for n in range(10)]
    ddl.handle_failure(FakeDB(), item(), {'success': False})
    assert len(FakeGC.instances[0].calls) == 1 + ddl.MAX_LINKED_POSTS
    assert failover == ['54429']
