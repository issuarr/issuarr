"""Whether the download clients that are turned on can be reached, for the sidebar's Service status.
Only clients that are enabled are listed: Usenet being down means nothing when Usenet is off."""
import os
import socket
import threading
import time
from urllib.parse import urlparse

import mylar

CACHE_SECONDS = 300
TIMEOUT = 3
_cache = {'at': 0.0, 'clients': None}
_lock = threading.Lock()


def _reachable(host, port=None):
    """A TCP connection to the client's host and port. Every client (web UIs, Deluge's daemon,
    rTorrent's SCGI) answers this, and it needs no login."""
    if not host:
        return False
    host = str(host).strip()
    if '://' not in host:
        host = 'http://' + host
    try:
        u = urlparse(host)
        port = int(port or u.port or (443 if u.scheme in ('https', 'scgi+ssl') else 80))
        if not u.hostname:
            return False
        with socket.create_connection((u.hostname, port), timeout=TIMEOUT):
            return True
    except (OSError, ValueError):
        return False


def _folder(path):
    return bool(path) and os.path.isdir(path)


def enabled():
    """[(name, check)] for each download client that is turned on."""
    c = mylar.CONFIG
    out = []
    if getattr(mylar, 'USE_SABNZBD', False):
        out.append(('SABnzbd', lambda: _reachable(c.SAB_HOST)))
    elif getattr(mylar, 'USE_NZBGET', False):
        out.append(('NZBGet', lambda: _reachable(c.NZBGET_HOST, c.NZBGET_PORT)))
    elif getattr(mylar, 'USE_BLACKHOLE', False):
        out.append(('Usenet blackhole', lambda: _folder(c.BLACKHOLE_DIR)))
    if getattr(c, 'ENABLE_TORRENTS', False):
        for flag, name, key in (('USE_UTORRENT', 'uTorrent', 'UTORRENT_HOST'), ('USE_RTORRENT', 'rTorrent', 'RTORRENT_HOST'),
                                ('USE_TRANSMISSION', 'Transmission', 'TRANSMISSION_HOST'), ('USE_DELUGE', 'Deluge', 'DELUGE_HOST'),
                                ('USE_QBITTORRENT', 'qBittorrent', 'QBITTORRENT_HOST')):
            if getattr(mylar, flag, False):
                out.append((name, lambda key=key: _reachable(getattr(c, key, None))))
                break
        else:
            if getattr(mylar, 'USE_WATCHDIR', False) and getattr(c, 'TORRENT_LOCAL', False):
                out.append(('Torrent folder', lambda: _folder(c.LOCAL_WATCHDIR)))
    if getattr(c, 'JD2_ENABLE', False):
        out.append(('JDownloader', lambda: _reachable(c.JD2_URL)))
    return out


def status(force=False):
    """[{'name', 'ok'}] for the enabled clients, checked at most every CACHE_SECONDS."""
    checks = enabled()
    with _lock:
        cached = _cache['clients']
        if not force and cached is not None and time.time() - _cache['at'] < CACHE_SECONDS \
                and [x['name'] for x in cached] == [name for name, _ in checks]:  # a client turned on or off is checked now
            return cached
        clients = [{'name': name, 'ok': bool(check())} for name, check in checks]
        _cache.update(at=time.time(), clients=clients)
        return clients
