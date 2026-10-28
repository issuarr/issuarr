"""Settings > Notifications: which events are sent (downloaded and filed, files added by hand)."""
import json
from types import SimpleNamespace
from unittest import mock

import pytest

import mylar
from mylar import db, matching, notifiers, updater
from tests.test_matching import series  # noqa: F401  (fixture)


def _resp(code=204):
    return SimpleNamespace(status_code=code, text='')


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(notifiers, 'send_all', lambda *a, **kw: calls.append((a, kw)))
    return calls


@pytest.mark.unit
def test_added_line_lists_numbers_and_counts_the_rest():
    assert notifiers.added_line('Saga', '2018', ['54'])[0] == 'Saga (2018) #54'
    line, issues = notifiers.added_line('Saga', None, [str(n) for n in range(1, 14)])
    assert line == 'Saga #1, #2, #3, #4, #5, #6, #7, #8, #9, #10 and 3 more'
    assert issues.endswith('and 3 more')


@pytest.mark.unit
def test_files_added_needs_its_switch(monkeypatch, sent):
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(**dict({k: v[2] for k, v in mylar.config._CONFIG_DEFINITIONS.items()},
                                                               NOTIFY_ON_ADDED=False)), raising=False)
    notifiers.files_added('Saga', '2018', ['54'])
    assert sent == []
    monkeypatch.setattr(mylar.CONFIG, 'NOTIFY_ON_ADDED', True)
    notifiers.files_added('Saga', '2018', ['54', '55'])
    (args, kw), = sent
    assert args[1] == 'Saga (2018) #54, #55'
    assert kw['event'] == 'added'


@pytest.mark.unit
def test_a_recheck_sends_one_message_for_the_new_files(series, monkeypatch, sent):
    monkeypatch.setattr(mylar.CONFIG, 'NOTIFY_ON_ADDED', True)
    updater.forceRescan('500')
    (args, kw), = sent
    assert args[1] == 'Foo (2020) #1, #2, #3'
    sent.clear()
    updater.forceRescan('500')
    assert sent == []   # nothing new the second time


@pytest.mark.unit
def test_a_recheck_from_post_processing_sends_nothing(series, monkeypatch, sent):
    monkeypatch.setattr(mylar.CONFIG, 'NOTIFY_ON_ADDED', True)
    updater.forceRescan('500', recheck=True)
    assert sent == []


@pytest.mark.unit
def test_a_snatched_issue_found_by_a_recheck_is_left_to_post_processing(series, monkeypatch, sent):
    monkeypatch.setattr(mylar.CONFIG, 'NOTIFY_ON_ADDED', True)
    db.DBConnection().action("UPDATE issues SET Status='Snatched' WHERE IssueID='1001'")
    updater.forceRescan('500')
    (args, kw), = sent
    assert args[1] == 'Foo (2020) #2, #3'


@pytest.mark.unit
def test_matching_a_file_by_hand_sends_a_message(series, monkeypatch, sent):
    updater.forceRescan('500')
    monkeypatch.setattr(mylar.CONFIG, 'NOTIFY_ON_ADDED', True)
    assert matching.match('500', '1004', 'Bar 007.cbz')['ok']
    (args, kw), = sent
    assert args[1] == 'Foo (2020) #4'
    assert kw['metadata']['issueid'] == '1004'


@pytest.mark.unit
def test_filed_issues_need_their_switch(monkeypatch, sent):
    from mylar import PostProcessor
    pp = PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(NOTIFY_ON_DOWNLOAD=False), raising=False)
    pp.sendnotify('Saga', '2018', '54', None, '', None, issueid='9')
    assert sent == []
    monkeypatch.setattr(mylar.CONFIG, 'NOTIFY_ON_DOWNLOAD', True)
    pp.sendnotify('Saga', '2018', '54', None, '', None, issueid='9')
    (args, kw), = sent
    assert args[2] == 'Issuarr has downloaded and post-processed: Saga (2018) #54'
    assert kw['event'] == 'downloaded' and kw['metadata']['issueid'] == '9'


@pytest.mark.unit
def test_discord_says_which_event_and_reads_the_series_from_metadata(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(DISCORD_WEBHOOK_URL='https://discord.example/hook'), raising=False)
    with mock.patch.object(notifiers.requests, 'post', return_value=_resp()) as post:
        assert notifiers.DISCORD().notify('Files added', 'Added to Issuarr: Saga (2018) #54, #55', event='added',
                                          metadata={'series': 'Saga', 'year': '2018', 'issue': '#54, #55'})
        embed = json.loads(post.call_args.kwargs['data'])['embeds'][0]
        assert embed['author']['name'] == 'Added to Issuarr'
        assert [f['value'] for f in embed['fields']] == ['Saga (2018)', '#54, #55']

        notifiers.DISCORD().notify('Done', 'Issuarr has downloaded and post-processed: Saga (2018) #54')
        embed = json.loads(post.call_args.kwargs['data'])['embeds'][0]
        assert embed['author']['name'] == 'Downloaded by Issuarr'
        assert [f['value'] for f in embed['fields']] == ['Saga (2018)', '#54']


@pytest.mark.unit
def test_send_all_reaches_the_webhook_with_the_event(monkeypatch):
    cfg = {k: v[2] for k, v in mylar.config._CONFIG_DEFINITIONS.items()}
    cfg.update(WEBHOOK_ENABLED=True, WEBHOOK_URL='https://hooks.example/x')
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(**cfg), raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    with mock.patch.object(notifiers.requests, 'post', return_value=_resp()) as post:
        notifiers.send_all('Files added', 'Saga (2018) #54', 'Added to Issuarr: Saga (2018) #54', event='added',
                           metadata={'series': 'Saga', 'issue': '#54', 'year': '2018'})
    assert post.call_args.kwargs['json']['event'] == 'added'


def _cover_jpeg(path, colour=(200, 30, 30)):
    from PIL import Image
    Image.new('RGB', (900, 1400), colour).save(path, 'JPEG')
    return path


@pytest.mark.unit
def test_a_recheck_sends_the_series_cover_when_a_service_shows_covers(series, monkeypatch, sent, tmp_path):
    import base64, io
    from PIL import Image
    monkeypatch.setattr(mylar.CONFIG, 'NOTIFY_ON_ADDED', True)
    monkeypatch.setattr(mylar.CONFIG, 'DISCORD_ENABLED', True)
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(tmp_path))
    _cover_jpeg(tmp_path / '500.jpg')
    updater.forceRescan('500')
    (args, kw), = sent
    img = Image.open(io.BytesIO(base64.b64decode(kw['imageFile'])))
    assert img.size[0] == 600   # resized like the download notification's cover


@pytest.mark.unit
def test_no_cover_is_read_when_no_service_shows_one(series, monkeypatch, sent, tmp_path):
    monkeypatch.setattr(mylar.CONFIG, 'NOTIFY_ON_ADDED', True)
    monkeypatch.setattr(mylar.CONFIG, 'CACHE_DIR', str(tmp_path))
    _cover_jpeg(tmp_path / '500.jpg')
    with mock.patch.object(notifiers, 'cover') as cover:
        updater.forceRescan('500')
    cover.assert_not_called()
    (args, kw), = sent
    assert kw['imageFile'] is None


@pytest.mark.unit
def test_a_match_by_hand_sends_that_files_cover(series, monkeypatch, sent):
    updater.forceRescan('500')
    monkeypatch.setattr(mylar.CONFIG, 'NOTIFY_ON_ADDED', True)
    monkeypatch.setattr(mylar.CONFIG, 'DISCORD_ENABLED', True)
    with mock.patch.object(notifiers, 'cover', return_value='COVER') as cover:
        assert matching.match('500', '1004', 'Bar 007.cbz')['ok']
    assert cover.call_args.args == (str(series / 'Bar 007.cbz'), '500', '1004')
    (args, kw), = sent
    assert kw['imageFile'] == 'COVER'


@pytest.mark.unit
def test_cover_falls_back_to_the_series_cover_and_then_to_none(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(CACHE_DIR=str(tmp_path)), raising=False)
    assert notifiers.cover(str(tmp_path / 'gone.cbz'), '77') is None
    _cover_jpeg(tmp_path / '77.jpg')
    assert notifiers.cover(str(tmp_path / 'gone.cbz'), '77')


@pytest.mark.unit
def test_gotify_with_a_cover_and_no_issue_still_sends(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(), raising=False)
    with mock.patch.object(notifiers.requests, 'post', return_value=SimpleNamespace(status_code=200, text='')) as post:
        assert notifiers.GOTIFY(test_webhook_url='https://gotify.example/message').notify(
            'Files added', 'Added to Issuarr: Saga (2018) #54, #55', imageFile='QUJD', metadata={'issueid': None})
    assert 'client::notification' not in post.call_args.kwargs['json']['extras']


def _snatch_config(**kw):
    cfg = {k: v[2] for k, v in mylar.config._CONFIG_DEFINITIONS.items()}
    cfg.update(kw)
    return SimpleNamespace(**cfg)


@pytest.mark.unit
def test_a_grab_sends_the_issue_cover_and_a_pack_the_series_cover(monkeypatch):
    from mylar import search
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', _snatch_config(DISCORD_ENABLED=True, DISCORD_ONSNATCH=True), raising=False)
    with mock.patch.object(notifiers, 'cover', return_value='COVER') as cover, \
         mock.patch.object(notifiers.DISCORD, 'notify') as discord:
        search.notify_snatch('SABnzbd', 'Saga', '2018', '54', 'NZBgeek', False, comicid='500', issueid='1004')
        search.notify_snatch('SABnzbd', 'Saga', '2018', '#1 - 60', 'NZBgeek', True, comicid='500')
    assert [c.kwargs for c in cover.call_args_list] == [{'comicid': '500', 'issueid': '1004'}, {'comicid': '500', 'issueid': None}]
    assert all(c.kwargs['imageFile'] == 'COVER' for c in discord.call_args_list)


@pytest.mark.unit
def test_a_grab_reads_no_cover_when_no_grab_notification_shows_one(monkeypatch):
    from mylar import search
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    # Discord is on but not for grabs; Pushover is on for grabs without its image switch
    monkeypatch.setattr(mylar, 'CONFIG', _snatch_config(DISCORD_ENABLED=True, PUSHOVER_ENABLED=True, PUSHOVER_ONSNATCH=True,
                                                        PUSHOVER_APIKEY='k'), raising=False)
    with mock.patch.object(notifiers, 'cover') as cover, mock.patch.object(notifiers.PUSHOVER, 'notify') as pushover:
        search.notify_snatch('SABnzbd', 'Saga', '2018', '54', 'NZBgeek', False, comicid='500', issueid='1004')
    cover.assert_not_called()
    assert pushover.call_args.kwargs['imageFile'] is None


@pytest.mark.unit
def test_mattermost_grab_switch_now_sends(monkeypatch):
    from mylar import search
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', _snatch_config(MATTERMOST_ENABLED=True, MATTERMOST_ONSNATCH=True), raising=False)
    with mock.patch.object(notifiers.MATTERMOST, 'notify') as mm:
        search.notify_snatch('SABnzbd', 'Saga', '2018', '54', 'NZBgeek', False, comicid='500', issueid='1004')
    assert mm.call_args.kwargs['metadata']['issueid'] == '1004'


@pytest.mark.unit
def test_cover_uses_the_issues_comicvine_cover_before_the_series_cover(monkeypatch, tmp_path):
    from mylar import attention
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(CACHE_DIR=str(tmp_path)), raising=False)
    _cover_jpeg(tmp_path / '500.jpg')
    issue_jpg = _cover_jpeg(tmp_path / 'issue-1004.jpg', colour=(10, 200, 10))
    with mock.patch.object(attention, 'issue_cover', return_value=str(issue_jpg)):
        got = notifiers.cover(comicid='500', issueid='1004')
    with mock.patch.object(attention, 'issue_cover', return_value=None):
        fallback = notifiers.cover(comicid='500', issueid='1004')
    assert got and fallback and got != fallback


@pytest.mark.unit
def test_mattermost_links_the_comicvine_cover(series, monkeypatch):
    db.DBConnection().action("UPDATE issues SET ImageURL='https://comicvine.example/1004.jpg' WHERE IssueID='1004'")
    monkeypatch.setattr(mylar.CONFIG, 'MATTERMOST_WEBHOOK_URL', 'https://mm.example/hook')
    with mock.patch.object(notifiers.requests, 'post', return_value=SimpleNamespace(status_code=200, text='')) as post:
        notifiers.MATTERMOST().notify('Done', 'Filed', metadata={'series': 'Foo', 'issue': '#4', 'year': '2020', 'issueid': '1004'})
    assert post.call_args.kwargs['json']['attachments'][0]['image_url'] == 'https://comicvine.example/1004.jpg'


@pytest.mark.unit
def test_discord_grab_shows_the_cover_in_its_embed(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(DISCORD_WEBHOOK_URL='https://discord.example/hook'), raising=False)
    with mock.patch.object(notifiers.requests, 'post', return_value=_resp()) as post:
        notifiers.DISCORD().notify('Snatched', 'Issue snatched!', snatched_nzb='Saga (2018) #54', prov='NZBgeek',
                                   sent_to='SABnzbd', imageFile='QUJD')
    payload = json.loads(post.call_args.kwargs['files']['payload_json'][1])
    assert payload['embeds'][0]['image'] == {'url': 'attachment://image.jpg'}
