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

"""Keeps API keys, passwords and tokens out of the logs (issue #243).

Every line the 'mylar' logger writes, to the log file, the console and the Logs page, goes through
SecretFilter: secrets in URLs (apikey=..., user:password@host) and the values of every secret
setting are replaced with REDACTED."""

import logging
import re
import threading
import time

import mylar

MASK = 'REDACTED'
MIN_SECRET = 6   # shorter values would mask ordinary words
REFRESH = 60     # seconds between re-reading the secret settings

# query parameters that carry a key, password or token
_PARAMS = re.compile(r'(?i)([?&;](?:apikey|api_key|api-key|r|i|token|access_token|passkey|password|passwd|pass|pwd|key|nzbkey|rsskey|authkey|torrent_pass|secret)=)([^&;#\s\'"<>]+)')
# user:password@host in a URL
_USERINFO = re.compile(r'(?i)(\b[a-z][a-z0-9+.-]*://[^/\s:@\'"]*:)([^@\s/\'"]+)(@)')
# settings whose value is a secret (HTTPS_KEY is a file path, so not that one)
_SECRET_SETTING = re.compile(r'(APIKEY|API_KEY|PASSWORD|PASSKEY|TOKEN|SECRET|_PASS$|WEBHOOK_URL$|^COMICVINE_API$)')

_lock = threading.Lock()
_cache = {'at': 0.0, 'values': ()}


def _settings_secrets():
    c = getattr(mylar, 'CONFIG', None)
    if c is None:
        return ()
    values = set()
    try:
        from mylar import config
        names = [k for k in config._CONFIG_DEFINITIONS if _SECRET_SETTING.search(k)]
    except Exception:
        names = []
    for name in names:
        v = getattr(c, name, None)
        if isinstance(v, str) and len(v.strip()) >= MIN_SECRET:
            values.add(v.strip())
    # (name, host, verify, apikey, ...) for each newznab and torznab indexer
    for extras in (getattr(c, 'EXTRA_NEWZNABS', None), getattr(c, 'EXTRA_TORZNABS', None)):
        if isinstance(extras, (list, tuple)):
            for entry in extras:
                try:
                    v = entry[3]
                except (IndexError, KeyError, TypeError):
                    continue
                if isinstance(v, str) and len(v.strip()) >= MIN_SECRET:
                    values.add(v.strip())
    return tuple(sorted(values, key=len, reverse=True))   # longest first, so one inside another goes whole


def secrets():
    """The secret values from settings, read again at most every REFRESH seconds."""
    with _lock:
        if time.time() - _cache['at'] > REFRESH:
            try:
                _cache['values'] = _settings_secrets()
            except Exception:
                pass
            _cache['at'] = time.time()
        return _cache['values']


def forget():
    """Read the settings again on the next line, after they were saved."""
    with _lock:
        _cache['at'] = 0.0


def redact(text):
    """text with keys, passwords and tokens replaced by REDACTED."""
    if not text:
        return text
    text = str(text)
    for value in secrets():
        if value in text:
            text = text.replace(value, MASK)
    text = _PARAMS.sub(lambda m: m.group(1) + MASK, text)
    return _USERINFO.sub(lambda m: m.group(1) + MASK + m.group(3), text)


class SecretFilter(logging.Filter):
    """Redacts each record before any handler writes it."""

    def filter(self, record):
        try:
            message = record.getMessage()
            clean = redact(message)
            if clean != message:
                record.msg, record.args = clean, None
            if record.exc_info and not record.exc_text:
                # handlers reuse exc_text, so the traceback is redacted once here
                record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        except Exception:
            pass   # never lose a log line over this
        return True
