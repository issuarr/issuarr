#  This file is part of Issuarr.
#
#  Issuarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Issuarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

"""The "What's new" window shown once after an update.

CHANGELOG.md ships with every install and each of its lines ends with the
commit that made the change. An install's version is a commit id, and two ids
can't say which is newer without the git history, which Docker images don't
have. So instead of comparing versions, Issuarr remembers which changelog lines
the person has already been shown (whats_new.json next to config.ini) and shows
the rest. A downgrade has no lines that weren't seen before, so it shows
nothing. A first start, with nothing remembered yet, counts every line as seen.
"""

import html
import json
import os
import re
import tempfile
import threading

import mylar

STATE_FILE = 'whats_new.json'
REPO_URL = 'https://github.com/issuarr/issuarr'

_COMMIT = re.compile(r'\[`([0-9a-f]{7,40})`\]\((https://github\.com/[^)\s]+)\)')
# The commit list that ends a line: " ([`abc1234`](…), [`def5678`](…))".
_TAIL = re.compile(r'\s*\((?:\s*\[`[0-9a-f]{7,40}`\]\([^)\s]+\)\s*,?)+\)\s*$')
_LINK = re.compile(r'\[([^\]]+)\]\((https?://[^)\s]+)\)')

_lock = threading.Lock()
_cache = {}


def changelog_path():
    return os.path.join(mylar.PROG_DIR or '', 'CHANGELOG.md')


def state_path(data_dir=None):
    return os.path.join(data_dir or mylar.DATA_DIR or '', STATE_FILE)


def parse(text):
    """Changelog lines that name a commit, newest first, as dicts:
    release (the ## heading), group (the ### heading, may be ''), text (markdown,
    without the commit list), commits [(id, url)] and key (the first commit id)."""
    items = []
    release, group = '', ''
    current = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith('## '):
            release, group, current = line[3:].strip(), '', None
            continue
        if line.startswith('### '):
            group, current = line[4:].strip(), None
            continue
        if line.startswith('- '):
            current = {'release': release, 'group': group, 'lines': [line[2:].strip()]}
            items.append(current)
            continue
        if current is not None and line.startswith('  ') and line.strip():
            current['lines'].append(line.strip())
        else:
            current = None
    out = []
    for it in items:
        body = ' '.join(it.pop('lines'))
        commits = [(m.group(1), m.group(2)) for m in _COMMIT.finditer(body)]
        if not commits:
            continue
        it['text'] = _TAIL.sub('', body).strip()
        it['commits'] = commits
        it['key'] = commits[0][0][:7]
        out.append(it)
    return out


def to_html(md):
    """The little markdown changelog lines use: `code`, **bold**, *italic* and links."""
    links = []

    def keep(m):
        links.append('<a href="%s" target="_blank" rel="noopener">%s</a>' % (html.escape(m.group(2), quote=True), html.escape(m.group(1))))
        return '\x00%d\x00' % (len(links) - 1)

    text = html.escape(_LINK.sub(keep, md), quote=False)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])', r'<i>\1</i>', text)
    return re.sub('\x00(\\d+)\x00', lambda m: links[int(m.group(1))], text)


def _entries():
    """The installed changelog's lines, read once per run (the file only changes with an update)."""
    path = changelog_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return []
    if _cache.get('mtime') != mtime:
        try:
            with open(path, encoding='utf-8') as f:
                _cache['entries'] = parse(f.read())
        except (OSError, UnicodeDecodeError):
            _cache['entries'] = []
        _cache['mtime'] = mtime
    return _cache['entries']


def _read_seen(data_dir=None):
    """The keys already shown, or None when nothing has been saved yet."""
    try:
        with open(state_path(data_dir), encoding='utf-8') as f:
            seen = json.load(f).get('seen')
    except FileNotFoundError:
        return None
    except (OSError, ValueError, AttributeError):
        return set()
    return set(seen) if isinstance(seen, list) else set()


def _write_seen(seen, data_dir=None):
    path = state_path(data_dir)
    folder = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(prefix='.whats-new-', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'seen': sorted(seen)}, f)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def pending(data_dir=None):
    """Changelog lines this install hasn't shown yet, newest first."""
    entries = _entries()
    with _lock:
        seen = _cache.get('seen')
        if seen is None:
            seen = _read_seen(data_dir)
            if seen is None:
                # First start: there is no "before" to compare with, so nothing is new.
                seen = {e['key'] for e in entries}
                try:
                    _write_seen(seen, data_dir)
                except OSError:
                    pass
            _cache['seen'] = seen
    return [e for e in entries if e['key'] not in seen]


def mark_seen(data_dir=None):
    """Remember every line of the installed changelog as shown."""
    with _lock:
        seen = set(_cache.get('seen') or _read_seen(data_dir) or ())
        seen.update(e['key'] for e in _entries())
        _write_seen(seen, data_dir)
        _cache['seen'] = seen


def branch():
    b = str(getattr(mylar.CONFIG, 'GIT_BRANCH', None) or '').strip()
    return b if b in ('main', 'dev') else 'main'


def payload(data_dir=None):
    """What the window shows, grouped by release then by heading, as JSON-ready data."""
    releases = []
    for e in pending(data_dir):
        if not releases or releases[-1]['name'] != e['release']:
            releases.append({'name': e['release'], 'groups': []})
        groups = releases[-1]['groups']
        if not groups or groups[-1]['name'] != e['group']:
            groups.append({'name': e['group'], 'items': []})
        groups[-1]['items'].append({
            'html': to_html(e['text']),
            'commits': [{'id': c[:7], 'url': u} for c, u in e['commits']],
        })
    return {
        'releases': releases,
        'changelog_url': '%s/blob/%s/CHANGELOG.md' % (REPO_URL, branch()),
    }
