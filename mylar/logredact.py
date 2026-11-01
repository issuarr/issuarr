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
#
#  You should have received a copy of the GNU General Public License
#  along with Issuarr.  If not, see <http://www.gnu.org/licenses/>.

"""Masks API keys, passwords and tokens in log lines before they're written anywhere."""

import logging
import re
import time
import traceback

import mylar

MASK = '***'

_NAMES = r'(?:apikey|api_key|api-key|x-api-key|r|token|access_token|passkey|authkey|torrent_pass|password|passwd|pass|pwd|secret|nzbkey)'
# ?apikey=abc or &r=abc in a url
_QUERY = re.compile(r'([?&;]' + _NAMES + r'=)[^&\s\'"<>#]+', re.IGNORECASE)
# 'apikey': 'abc' in a printed dict, or "apikey": "abc" in json
_PAIR = re.compile(r'([\'"]' + _NAMES + r'[\'"]\s*:\s*[\'"])[^\'"]+', re.IGNORECASE)
# https://user:password@host
_USERINFO = re.compile(r'(\b[a-z][a-z0-9+.-]*://[^/\s:@\'"]+:)[^@\s/\'"]+@', re.IGNORECASE)

_SECRET_SETTING = re.compile(r'(PASS|KEY|TOKEN|SECRET|_API$|WEBHOOK_URL$)')
_NOT_SECRET = {'HTTPS_KEY', 'PP_SSHKEYFILE', 'PROWLARR_KNOWN', 'ENCRYPT_PASSWORDS'}
_MIN_LEN = 6
_REFRESH = 60
_cache = {'at': None, 'values': ()}


def _settings_secrets():
    cfg = getattr(mylar, 'CONFIG', None)
    if cfg is None:
        return ()
    found = set()
    for name in dir(cfg):
        if not name.isupper() or name in _NOT_SECRET or not _SECRET_SETTING.search(name):
            continue
        try:
            value = getattr(cfg, name)
        except Exception:
            continue
        if isinstance(value, str):
            found.add(value.strip())
    for extras in ('EXTRA_NEWZNABS', 'EXTRA_TORZNABS'):
        for entry in getattr(cfg, extras, None) or ():
            if isinstance(entry, (list, tuple)) and len(entry) > 3 and isinstance(entry[3], str):
                found.add(entry[3].strip())
    found = {v for v in found if len(v) >= _MIN_LEN and v.lower() not in ('none', 'null')}
    # longest first, so a key that contains a shorter one is masked whole
    return tuple(sorted(found, key=len, reverse=True))


def known_secrets():
    now = time.monotonic()
    if _cache['at'] is None or now - _cache['at'] >= _REFRESH:
        try:
            _cache['values'] = _settings_secrets()
        except Exception:
            _cache['values'] = ()
        _cache['at'] = now
    return _cache['values']


def forget():
    _cache['at'] = None


def redact(text):
    if not text or not isinstance(text, str):
        return text
    text = _QUERY.sub(r'\1' + MASK, text)
    text = _PAIR.sub(r'\1' + MASK, text)
    text = _USERINFO.sub(r'\1' + MASK + '@', text)
    for secret in known_secrets():
        if secret in text:
            text = text.replace(secret, MASK)
    return text


class RedactFilter(logging.Filter):
    """Rewrites each record's message (and traceback) with secrets masked, for every handler."""

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        if record.exc_info and not record.exc_text:
            try:
                record.exc_text = redact(''.join(traceback.format_exception(*record.exc_info)).rstrip('\n'))
            except Exception:
                pass
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True
