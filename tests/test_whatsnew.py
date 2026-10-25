"""The What's new window: which changelog lines an install shows after an update."""
import json
import os

import pytest

import mylar
from mylar import whatsnew

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SAMPLE = """# Changelog

## Unreleased (on dev)

- A brand-new **thing** with `code`. ([`aaaaaaa`](https://github.com/issuarr/issuarr/commit/aaaaaaa))

## 0.2.0 (1 October 2026)

### Screens

- Two commits made this,
  and it wraps. ([`bbbbbbb`](https://github.com/issuarr/issuarr/commit/bbbbbbb), [`ccccccc`](https://github.com/issuarr/issuarr/commit/ccccccc))
- See [the docs](https://issuarr.github.io/issuarr/) for <more>. ([`ddddddd`](https://github.com/issuarr/issuarr/commit/ddddddd))

## 0.1.0 (1 September 2026)

Nothing yet.
"""


@pytest.fixture
def install(tmp_path, monkeypatch):
    prog = tmp_path / 'prog'
    data = tmp_path / 'data'
    prog.mkdir()
    data.mkdir()
    (prog / 'CHANGELOG.md').write_text(SAMPLE, encoding='utf-8')
    monkeypatch.setattr(mylar, 'PROG_DIR', str(prog))
    monkeypatch.setattr(mylar, 'DATA_DIR', str(data))
    monkeypatch.setattr(whatsnew, '_cache', {})
    return prog, data


def _seen(data):
    return json.loads((data / whatsnew.STATE_FILE).read_text())['seen']


@pytest.mark.unit
def test_parse_keeps_lines_with_commits_and_their_headings():
    items = whatsnew.parse(SAMPLE)
    assert [i['key'] for i in items] == ['aaaaaaa', 'bbbbbbb', 'ddddddd']
    assert items[1]['release'] == '0.2.0 (1 October 2026)'
    assert items[1]['group'] == 'Screens'
    assert items[1]['text'] == 'Two commits made this, and it wraps.'
    assert [c for c, _ in items[1]['commits']] == ['bbbbbbb', 'ccccccc']


@pytest.mark.unit
def test_to_html_escapes_and_keeps_simple_markdown():
    out = whatsnew.to_html('See [the docs](https://x.example/) for <more> **now** with `a<b`.')
    assert '<a href="https://x.example/" target="_blank" rel="noopener">the docs</a>' in out
    assert '&lt;more&gt;' in out
    assert '<b>now</b>' in out
    assert '<code>a&lt;b</code>' in out


@pytest.mark.unit
def test_first_start_shows_nothing_and_remembers_every_line(install):
    _, data = install
    assert whatsnew.pending() == []
    assert _seen(data) == ['aaaaaaa', 'bbbbbbb', 'ddddddd']


@pytest.mark.unit
def test_update_shows_only_unseen_lines_until_closed(install):
    _, data = install
    (data / whatsnew.STATE_FILE).write_text(json.dumps({'seen': ['bbbbbbb', 'ddddddd']}))
    assert [e['key'] for e in whatsnew.pending()] == ['aaaaaaa']
    whatsnew.mark_seen()
    assert whatsnew.pending() == []
    assert 'aaaaaaa' in _seen(data)


@pytest.mark.unit
def test_downgrade_shows_nothing_and_keeps_newer_lines_seen(install):
    _, data = install
    (data / whatsnew.STATE_FILE).write_text(json.dumps({'seen': ['aaaaaaa', 'bbbbbbb', 'ddddddd', 'eeeeeee']}))
    assert whatsnew.pending() == []
    whatsnew.mark_seen()
    assert 'eeeeeee' in _seen(data)


@pytest.mark.unit
def test_payload_groups_by_release_and_heading(install):
    _, data = install
    (data / whatsnew.STATE_FILE).write_text(json.dumps({'seen': []}))
    d = whatsnew.payload()
    assert [r['name'] for r in d['releases']] == ['Unreleased (on dev)', '0.2.0 (1 October 2026)']
    assert d['releases'][1]['groups'][0]['name'] == 'Screens'
    assert d['releases'][1]['groups'][0]['items'][0]['commits'][1] == {'id': 'ccccccc', 'url': 'https://github.com/issuarr/issuarr/commit/ccccccc'}
    assert d['changelog_url'].endswith('/CHANGELOG.md')


@pytest.mark.unit
def test_shipped_changelog_lines_all_name_a_commit():
    with open(os.path.join(ROOT, 'CHANGELOG.md'), encoding='utf-8') as f:
        text = f.read()
    bullets = [l for l in text.splitlines() if l.startswith('- ')]
    assert len(whatsnew.parse(text)) == len(bullets)
