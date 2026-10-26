"""Settings > Notifications: tasks starting and finishing, Needs attention, matches to choose, clients down, low disk space."""
import json
from collections import namedtuple
from types import SimpleNamespace
from unittest import mock

import pytest

import mylar
from mylar import alerts, notifiers

Usage = namedtuple('Usage', 'total used free')
GB = 1024 ** 3


def _config(**kw):
    base = {k: v[2] for k, v in mylar.config._CONFIG_DEFINITIONS.items()}
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(alerts.notifiers, 'send_all', lambda headline, prline, message, **kw: calls.append((kw['event'], message)))
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(alerts, '_running', {})
    monkeypatch.setattr(alerts, '_seen', {})
    monkeypatch.setattr(alerts, '_low', set())
    return calls


@pytest.mark.unit
def test_tasks_are_told_only_when_switched_on_and_chosen(monkeypatch, sent):
    monkeypatch.setattr(mylar, 'CONFIG', _config(NOTIFY_ON_TASK_START=True, NOTIFY_ON_TASK_DONE=True), raising=False)
    alerts.task('Auto-Search', True)
    alerts.task('Auto-Search', False)
    alerts.task('Folder Monitor', True)   # not chosen by default: it runs every few minutes
    alerts.task('Folder Monitor', False)
    assert [e for e, _ in sent] == ['task_started', 'task_finished']
    assert sent[0][1] == 'Auto-Search started.'
    assert sent[1][1].startswith('Auto-Search finished after ')


@pytest.mark.unit
def test_a_finish_without_its_start_is_not_told(monkeypatch, sent):
    monkeypatch.setattr(mylar, 'CONFIG', _config(NOTIFY_ON_TASK_DONE=True), raising=False)
    alerts.task('Auto-Search', True)
    alerts.task('Auto-Search', False)
    alerts.task('Auto-Search', False)   # DB Updater can write its finish twice
    assert [e for e, _ in sent] == ['task_finished']


@pytest.mark.unit
def test_tasks_are_off_by_default(monkeypatch, sent):
    monkeypatch.setattr(mylar, 'CONFIG', _config(), raising=False)
    alerts.task('Auto-Search', True)
    alerts.task('Auto-Search', False)
    assert sent == []


def _quiet_checks(monkeypatch, attention=(), match=(), down=()):
    monkeypatch.setattr(alerts, '_attention', lambda: set(attention))
    monkeypatch.setattr(alerts, '_match_needed', lambda: set(match))
    monkeypatch.setattr(alerts, '_clients_down', lambda: set(down))
    monkeypatch.setattr(alerts, 'folders', lambda: [])


@pytest.mark.unit
def test_the_first_look_only_takes_note_then_new_files_are_told_once(monkeypatch, sent):
    monkeypatch.setattr(mylar, 'CONFIG', _config(), raising=False)
    _quiet_checks(monkeypatch, attention=['/r/a.cbz'])
    alerts.tick()
    assert sent == []
    _quiet_checks(monkeypatch, attention=['/r/a.cbz', '/r/b.cbz', '/r/c.cbz'])
    alerts.tick()
    alerts.tick()
    assert sent == [('attention', '2 new files on Needs attention: b.cbz, c.cbz')]


@pytest.mark.unit
def test_matches_to_choose_and_clients_down(monkeypatch, sent):
    monkeypatch.setattr(mylar, 'CONFIG', _config(), raising=False)
    _quiet_checks(monkeypatch)
    alerts.tick()
    _quiet_checks(monkeypatch, match=['Saga 2012'], down=['SABnzbd'])
    alerts.tick()
    assert sent == [('match_needed', 'Import results needs you to choose the match for Saga 2012'),
                    ('action_required', "Issuarr can't reach SABnzbd. Check that it is running and its settings are right.")]
    sent.clear()
    _quiet_checks(monkeypatch)   # SABnzbd back up
    alerts.tick()
    _quiet_checks(monkeypatch, down=['SABnzbd'])   # and down again
    alerts.tick()
    assert [e for e, _ in sent] == ['action_required']


@pytest.mark.unit
def test_a_switch_turned_off_sends_nothing(monkeypatch, sent):
    monkeypatch.setattr(mylar, 'CONFIG', _config(NOTIFY_ON_ATTENTION=False), raising=False)
    _quiet_checks(monkeypatch)
    alerts.tick()
    _quiet_checks(monkeypatch, attention=['/r/a.cbz'])
    alerts.tick()
    assert sent == []


@pytest.mark.unit
def test_low_disk_space_is_told_once_until_there_is_space_again(monkeypatch, sent, tmp_path):
    monkeypatch.setattr(mylar, 'CONFIG', _config(NOTIFY_DISK_MIN_GB=10), raising=False)
    _quiet_checks(monkeypatch)
    monkeypatch.setattr(alerts, 'folders', lambda: [('Library', str(tmp_path))])
    free = [5 * GB]
    monkeypatch.setattr(alerts.shutil, 'disk_usage', lambda p: Usage(100 * GB, 0, free[0]))
    alerts.tick()
    alerts.tick()
    assert sent == [('disk_low', 'Running out of disk space: Library (%s) has 5.0 GB free.' % tmp_path)]
    free[0] = 50 * GB
    alerts.tick()
    free[0] = 2 * GB
    alerts.tick()
    assert len(sent) == 2


@pytest.mark.unit
def test_folders_on_the_same_disk_are_checked_once(monkeypatch, tmp_path):
    lib, dl = tmp_path / 'lib', tmp_path / 'dl'
    lib.mkdir(); dl.mkdir()
    monkeypatch.setattr(mylar, 'CONFIG', _config(DESTINATION_DIR=str(lib), CHECK_FOLDER=str(dl), ENABLE_CHECK_FOLDER=True), raising=False)
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path / 'missing'), raising=False)
    assert alerts.folders() == [('Library', str(lib))]


@pytest.mark.unit
def test_discord_shows_an_alert_as_its_own_embed(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(DISCORD_WEBHOOK_URL='https://discord.example/hook'), raising=False)
    with mock.patch.object(notifiers.requests, 'post', return_value=SimpleNamespace(status_code=204, text='')) as post:
        assert notifiers.DISCORD().notify('Low disk space', 'Running out of disk space: Library (/comics) has 2.0 GB free.', event='disk_low')
    embed = json.loads(post.call_args.kwargs['data'])['embeds'][0]
    assert embed['author']['name'] == 'Low disk space'
    assert embed['description'].startswith('Running out of disk space')


@pytest.mark.unit
def test_mattermost_sends_an_alert_without_issue_fields(monkeypatch):
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', SimpleNamespace(MATTERMOST_WEBHOOK_URL='https://mm.example/hook'), raising=False)
    with mock.patch.object(notifiers.requests, 'post', return_value=SimpleNamespace(status_code=200, text='')) as post:
        assert notifiers.MATTERMOST().notify('Task started', 'Auto-Search started.', metadata={})
    assert post.call_args.kwargs['json']['attachments'] == []


@pytest.mark.unit
def test_send_all_emails_alerts_without_the_filed_issues_switch(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', _config(EMAIL_ENABLED=True, EMAIL_ONPOST=False), raising=False)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    with mock.patch.object(notifiers.EMAIL, 'notify') as email:
        notifiers.send_all('Task started', 'Auto-Search started.', 'Auto-Search started.', event='task_started')
        notifiers.send_all('Done', 'Saga #1', 'Issuarr has downloaded and post-processed: Saga #1', event='downloaded')
    assert email.call_count == 1
    assert email.call_args.args[1] == 'Issuarr notification - Task started'


@pytest.mark.unit
def test_the_task_boxes_are_saved_as_a_list_of_names():
    assert alerts.tasks_from_form('RSS Feeds') == 'RSS Feeds'
    assert alerts.tasks_from_form(['DB Updater', 'Auto-Search', 'Nope']) == 'Auto-Search,DB Updater'
    assert alerts.tasks_from_form([]) == ''


@pytest.mark.unit
def test_the_switches_are_on_the_settings_page():
    with open('data/interfaces/default/config.html', encoding='utf-8') as f:
        page = f.read()
    for name in ('notify_on_task_start', 'notify_on_task_done', 'notify_task', 'notify_tasks_shown', 'notify_on_attention',
                 'notify_on_match_needed', 'notify_on_action', 'notify_on_disk_low', 'notify_disk_min_gb'):
        assert "'%s'" % name in page or 'name="%s"' % name in page
