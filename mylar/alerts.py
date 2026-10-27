#  This file is part of Issuarr.
#
#  Issuarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Issuarr is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the
#  implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public
#  License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Issuarr.  If not, see <http://www.gnu.org/licenses/>.

"""Notifications about Issuarr itself, each behind its own switch in Settings > Notifications:
scheduled tasks starting and finishing, new files on Needs attention, new series on Import results
waiting for a match, download clients that can't be reached, and low disk space.

tick() runs every few minutes and only tells about what changed since the last look, so a file
waiting on Needs attention is told about once, not every tick. The first look after a start only
takes note of what is already there."""

import os
import shutil
import threading
import time

import mylar
from mylar import db, logger, notifiers

TICK = 5   # minutes between looks
TASKS = ('Auto-Search', 'RSS Feeds', 'Folder Monitor', 'Weekly Pullist', 'DB Updater', 'Check Version')
DEFAULT_TASKS = 'Auto-Search,Weekly Pullist,DB Updater'
MOST_NAMES = 5

_lock = threading.Lock()
_running = {}   # task name -> start time
_seen = {}      # what -> set of keys already told about (None until the first look)
_low = set()    # folders already told to be low on space


def _on(name):
    return bool(getattr(mylar.CONFIG, name, False))


def chosen_tasks():
    return [t.strip() for t in str(getattr(mylar.CONFIG, 'NOTIFY_TASKS', '') or '').split(',') if t.strip()]


def tasks_from_form(picked):
    """The Tasks to notify about boxes as saved: one ticked box comes as a string, several as a list."""
    picked = [picked] if isinstance(picked, str) else list(picked or [])
    return ','.join(t for t in TASKS if t in picked)


def _send(event, headline, message, imageFile=None):
    notifiers.send_all(headline, message, message, event=event, imageFile=imageFile, module='[ALERTS]')


def _first_cover(paths):
    """The cover of the first new file on Needs attention (as the message lists them), for the services that show one."""
    if not paths or not notifiers.wants_cover():
        return None
    return notifiers.cover(path=sorted(paths, key=os.path.basename)[0])


def _took(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return '%s seconds' % seconds
    if seconds < 3600:
        return '%s min' % (seconds // 60)
    return '%s h %s min' % (seconds // 3600, seconds % 3600 // 60)


def task(job, started):
    """A scheduled task (as Settings > Tasks names it) started (True) or finished (False)."""
    try:
        with _lock:
            if started:
                _running[job] = time.time()
            elif job in _running:
                began = _running.pop(job)
            else:
                return   # a finish without its start: told already, or started before Issuarr did
        if job not in chosen_tasks():
            return
        if started and _on('NOTIFY_ON_TASK_START'):
            _send('task_started', 'Task started', '%s started.' % job)
        elif not started and _on('NOTIFY_ON_TASK_DONE'):
            _send('task_finished', 'Task finished', '%s finished after %s.' % (job, _took(time.time() - began)))
    except Exception as e:
        logger.fdebug('[ALERTS] Could not tell about %s: %s' % (job, e))


def _names(items):
    items = sorted(items)
    shown = ', '.join(items[:MOST_NAMES])
    if len(items) > MOST_NAMES:
        shown += ' and %s more' % (len(items) - MOST_NAMES)
    return shown


def _new(what, now):
    """The keys in now that weren't there at the last look. The first look only takes note."""
    before = _seen.get(what)
    _seen[what] = set(now)
    return set() if before is None else set(now) - before


def _attention():
    from mylar import attention
    return set(attention.shown_paths(db.DBConnection()))


def _match_needed():
    rows = db.DBConnection().select("SELECT DISTINCT ComicName, Volume FROM importresults WHERE Status='Manual Intervention' "
                                    "AND (WatchMatch IS NULL OR WatchMatch LIKE 'C%')")
    return {('%s %s' % (r['ComicName'], r['Volume'])).strip() if r['Volume'] else str(r['ComicName']) for r in rows or []}


def _clients_down():
    from mylar import clientstatus
    return {c['name'] for c in clientstatus.status() if not c['ok']}


def folders():
    """[(label, path)] for the folders whose free space matters: the library, downloads and the config folder."""
    c = mylar.CONFIG
    out = [('Library', getattr(c, 'DESTINATION_DIR', None)),
           ('Download folder', getattr(c, 'CHECK_FOLDER', None) if getattr(c, 'ENABLE_CHECK_FOLDER', False) else None),
           ('Direct downloads', getattr(c, 'DDL_LOCATION', None) if getattr(c, 'ENABLE_DDL', False) else None),
           ('Config folder', getattr(mylar, 'DATA_DIR', None))]
    seen, keep = set(), []
    for label, path in out:
        if not path or not os.path.isdir(path):
            continue
        try:
            dev = os.stat(path).st_dev
        except OSError:
            continue
        if dev in seen:
            continue   # same disk as one already listed
        seen.add(dev)
        keep.append((label, path))
    return keep


def _min_free():
    try:
        return max(0.1, float(getattr(mylar.CONFIG, 'NOTIFY_DISK_MIN_GB', 10) or 10)) * 1024 ** 3
    except (TypeError, ValueError):
        return 10 * 1024 ** 3


def _disk():
    low = []
    limit = _min_free()
    for label, path in folders():
        try:
            free = shutil.disk_usage(path).free
        except OSError:
            continue
        if free < limit:
            if path not in _low:
                low.append('%s (%s) has %.1f GB free' % (label, path, free / 1024 ** 3))
            _low.add(path)
        elif free > limit * 1.1:
            _low.discard(path)   # told again if it fills up again
    return low


def tick():
    """Look for what changed since the last look and tell about it."""
    checks = (('NOTIFY_ON_ATTENTION', 'attention', _attention, 'attention', 'Needs attention',
               lambda new: '%s new %s on Needs attention: %s' % (len(new), 'file' if len(new) == 1 else 'files',
                                                                 _names(os.path.basename(p) for p in new))),
              ('NOTIFY_ON_MATCH_NEEDED', 'match', _match_needed, 'match_needed', 'Choose a match',
               lambda new: 'Import results needs you to choose the match for %s' % _names(new)),
              ('NOTIFY_ON_ACTION', 'clients', _clients_down, 'action_required', 'Action required',
               lambda new: "Issuarr can't reach %s. Check that it is running and its settings are right." % _names(new)))
    for switch, what, look, event, headline, say in checks:
        if not _on(switch):
            _seen.pop(what, None)   # start fresh when turned back on
            continue
        try:
            new = _new(what, look())
            if new:
                _send(event, headline, say(new), _first_cover(new) if what == 'attention' else None)
        except Exception as e:
            logger.fdebug('[ALERTS] Could not check %s: %s' % (what, e))
    if _on('NOTIFY_ON_DISK_LOW'):
        try:
            low = _disk()
            if low:
                _send('disk_low', 'Low disk space', 'Running out of disk space: %s.' % '; '.join(low))
        except Exception as e:
            logger.fdebug('[ALERTS] Could not check disk space: %s' % e)
    else:
        _low.clear()
