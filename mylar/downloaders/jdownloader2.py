#  This file is part of Mylar.
#
#  Provides a lightweight wrapper around the JDownloader2 remote API so
#  GetComics links can be handed off for downloading.

import json
import os
import datetime
import time
from typing import Any, Dict, List, Optional

import requests

import mylar
from mylar import db, logger

# Issuarr puts this comment on every link it sends JD2. Downloads the user adds to JD2 with the
# same comment (on the package or its links) are filed by Issuarr too.
COMMENT = 'issuarr'


def tagged(comment):
    """Whether a JD2 package or link comment marks it for Issuarr."""
    return str(comment or '').strip().lower() == COMMENT


def local_folder():
    """JD2's download folder as Issuarr sees it. The two programs can see the same folder under
    different paths (say /output in JD2's container and /downloads in Issuarr's), so the JD2 path
    is only used here when no Issuarr path is set."""
    for key in ('JD2_LOCAL_DIR', 'JD2_DEST_DIR'):
        path = getattr(mylar.CONFIG, key, None)
        if path and path != 'None':
            return path
    return None


def job_ids(job_id):
    """A JD2 job as Issuarr stores it: the ids JD2 gave each link it was sent, comma separated."""
    return [j for j in str(job_id or '').split(',') if j.strip() and j.strip() != 'None']


def local_path(save_to):
    """A folder JD2 reports (its saveTo) as Issuarr sees it. JD2 can file a package in a subfolder
    of its download folder, such as '2026-06/07', so the whole path under that folder is kept."""
    if not save_to:
        return None
    save_to = str(save_to).replace('\\', '/').rstrip('/')
    dest = str(getattr(mylar.CONFIG, 'JD2_DEST_DIR', None) or '').replace('\\', '/').rstrip('/')
    local = local_folder()
    if not local:
        return None
    if dest and dest != 'None' and (save_to == dest or save_to.startswith(dest + '/')):
        rel = save_to[len(dest):].lstrip('/')
    else:
        rel = os.path.basename(save_to)
    return os.path.join(local, rel) if rel else local


class JDownloader2(object):
    """Simple helper for submitting links to JDownloader2 and polling status."""

    LINKGRABBER_ENDPOINT = 'linkgrabberv2/addLinks'
    LINKGRABBER_QUERY_ENDPOINT = 'linkgrabberv2/queryLinks'
    DOWNLOADS_ENDPOINT = 'downloadsV2/queryLinks'

    def __init__(self, base_url: Optional[str] = None, timeout: int = 30, session: Optional[requests.Session] = None):
        self.base_url = (base_url or mylar.CONFIG.JD2_URL or '').rstrip('/')
        if not self.base_url:
            raise ValueError('JD2 URL is not configured')
        self.timeout = timeout
        self.session = session or requests.Session()

        self.destination_root = mylar.CONFIG.JD2_DEST_DIR
        self.destination_folder = None
        if self.destination_root and self.destination_root != 'None':
            # the path JD2 saves to; Issuarr checks the folder under its own path for it
            self.destination_folder = self.destination_root
            local = local_folder()
            try:
                os.makedirs(local, exist_ok=True)
            except Exception as err:
                logger.warn('[JD2] Issuarr can\'t reach JD2\'s download folder at %s (%s), so JD2 downloads won\'t be filed.'
                            ' Set "Same folder, as Issuarr sees it" under Settings > Download clients > JDownloader 2.', local, err)

    def _url(self, endpoint: str) -> str:
        return f"{self.base_url}/{endpoint.lstrip('/')}"

    def submit(self, links: dict, package_name: str, record_id: Optional[str] = None) -> Dict[str, Any]:
        """Submit a link to JD2 and return the assigned job id (if any)."""
        query = {
            'assignJobID': True,
            'autostart': True,
            'packageName': package_name,
            'comment': COMMENT,
        }
        if self.destination_folder:
            query['destinationFolder'] = self.destination_folder
        endpoint = self._url(self.LINKGRABBER_ENDPOINT)
        payload = None
        job_id = None
        # each link is its own JD2 job; all of them are kept, or a mirror JD2 finishes is never seen
        ids = []
        error = 'JD2 returned no job id'
        
        for url, priority in links.items():
            query['priority'] = priority
            query['links'] = url
            params = {'query': json.dumps(query)}
            try:
                resp = self.session.get(
                    endpoint,
                    params=params,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
            except Exception as err:
                logger.error('[JD2] Failed to submit %s (url=%s params=%s): %s', package_name, endpoint, params, err)
                error = err
                continue
            try:
                link_payload = resp.json() or None
                if isinstance(link_payload, dict):
                    data = link_payload.get('data', link_payload)
                    if isinstance(data, dict) and (data.get('id') or data.get('jobID')):
                        ids.append(str(data.get('id') or data.get('jobID')))
                        payload = payload or link_payload
                        time.sleep(1)
            except Exception as json_err:
                logger.warn('[JD2] Unable to decode submit response JSON: %s', json_err)

        if ids:
            job_id = ','.join(ids)
        if job_id is None:
            logger.error('[JD2] No job id returned for %s', package_name)
            return {'status': False, 'jobid': None, 'error': error}

        if record_id:
            try:
                myDB = db.DBConnection()
                myDB.upsert(
                    'ddl_info',
                    {
                        'jd2_job_id': str(job_id),
                        'status': 'Queued',
                        'updated_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
                    },
                    {'id': record_id},
                )
            except Exception as err:
                logger.error('[JD2] Unable to update database for job id %s for record %s: %s', job_id, record_id, err)
                return {'status': False, 'jobid': None, 'error': err}
    
        return {'status': True, 'jobid': str(job_id), 'payload': payload}

    def query_links(self, id: str) -> Dict[str, Any]:

        query = {
            "jobUUIDs": list(id),
        }

        endpoint = self._url(self.LINKGRABBER_QUERY_ENDPOINT)
        try:
            response = requests.get(endpoint, params=json.dumps(query), timeout=self.timeout)
            response.raise_for_status()
        except Exception as err:
            logger.error(
                "[JD2] Failed to query links (url=%s id=%s): %s",
                endpoint,
                id,
                err,
            )
            
        try:
            payload = response.json() or {}
        except Exception as json_err:
            logger.warning("[JD2] Unable to decode links JSON: %s", json_err)
            payload = {}

        data = payload.get("data", payload if isinstance(payload, list) else [])
        result = data if isinstance(data, list) else []
        return result

    def query(self, job_ids: List[str]) -> List[Dict[str, Any]]:
        if not job_ids:
            return []
        query = {
            'jobUUID': True,
            'jobUUIDs': job_ids,
            'status': True,
            'finished': True,
            'packageUUID': True,
            'uuid': True,
            'name': True,
            'maxResults': 1000,
            'startAt': 0,
        }
        endpoint = self._url(self.DOWNLOADS_ENDPOINT)
        params = {'queryParams': json.dumps(query)}
        try:
            resp = self.session.get(
                endpoint,
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except Exception as err:
            logger.error('[JD2] Failed to query job ids %s (url=%s params=%s): %s', job_ids, endpoint, params, err)
            return []

        try:
            payload = resp.json() or {}
        except Exception as json_err:
            logger.warn('[JD2] Unable to decode query response JSON: %s', json_err)
            payload = {}


        data = payload.get('data', payload if isinstance(payload, list) else [])
        return data if isinstance(data, list) else []

    DONE = ('finished', 'finished(mirror)', 'done', 'extraction ok', 'crc ok')
    DEAD = ('offline', 'file not found', 'not available', 'plugin defect', 'aborted', 'blocked by cloudflare', 'failed', 'error',
            'hosting period', 'only paid users')

    def _links(self, endpoint, query):
        extra = {'availability': True} if endpoint.startswith('linkgrabber') else {'finished': True, 'bytesLoaded': True}
        query = dict(query, status=True, packageUUID=True, jobUUID=True, uuid=True, name=True, host=True, maxResults=1000, startAt=0, **extra)
        r = self.session.get(self._url(endpoint), params={'queryParams': json.dumps(query)}, timeout=self.timeout)
        r.raise_for_status()
        data = (r.json() or {}).get('data') or []
        return [l for l in data if isinstance(l, dict)]

    def _packages(self, area, record_id):
        if not record_id:
            return []
        r = self.session.get(self._url('%s/queryPackages' % area), params={'queryParams': json.dumps({'uuid': True, 'name': True})}, timeout=self.timeout)
        r.raise_for_status()
        suffix = ' - %s' % record_id
        return sorted({p.get('uuid') for p in (r.json() or {}).get('data') or [] if isinstance(p, dict) and str(p.get('name') or '').endswith(suffix)})

    def _job_links(self, job_id, record_id=None):
        found = {}
        for area, endpoint in (('downloadsV2', 'downloadsV2/queryLinks'), ('linkgrabberv2', 'linkgrabberv2/queryLinks')):
            packages = set(self._packages(area, record_id))
            if job_ids(job_id):
                packages |= {l.get('packageUUID') for l in self._links(endpoint, {'jobUUIDs': job_ids(job_id)}) if l.get('packageUUID')}
            links = self._links(endpoint, {'packageUUIDs': sorted(packages)}) if packages else []
            found[area] = (links, sorted(packages))
        return found

    def _package_links(self, job_id, record_id=None):
        links, packages = self._job_links(job_id, record_id)['downloadsV2']
        return links, packages

    def status(self, job_id: str, record_id: Optional[str] = None) -> Dict[str, Any]:
        if job_id is None and record_id is None:
            return {'found': False, 'status': None, 'data': None}
        try:
            found = self._job_links(job_id, record_id)
        except Exception as err:
            logger.warn('[JD2] Unable to query job %s: %s', job_id, err)
            return {'found': True, 'status': None, 'data': None}
        links = found['downloadsV2'][0]
        grabber = found['linkgrabberv2'][0]
        if not links and not grabber:
            return {'found': False, 'status': None, 'data': None}
        is_done = lambda l: l.get('finished') is True or any(d in str(l.get('status') or '').lower() for d in self.DONE)
        is_dead = lambda l: any(d in str(l.get('status') or '').lower() for d in self.DEAD)
        # Each file host is one mirror of the post. A mirror can be one file or every file of a pack
        # (a zip on one host, the single issues on another), so the job is done once one host has
        # finished all of its files - not when the first file of a pack lands.
        hosts = {}
        for l in links:
            hosts.setdefault(l.get('host'), []).append(l)
        # files of a host still in the link grabber haven't started yet (a big folder is still being added)
        waiting = {l.get('host') for l in grabber if not any(d in str(l.get('availability') or '').lower() for d in self.DEAD)}
        for host, host_links in hosts.items():
            done = [l for l in host_links if is_done(l)]
            if done and host not in waiting and all(is_done(l) or is_dead(l) for l in host_links):
                return {'found': True, 'status': 'Finished', 'data': done[0], 'files': len(done)}
        states = [str(l.get('status') or '').lower() for l in links] + [str(l.get('availability') or '').lower() for l in grabber]
        if all(st and any(d in st for d in self.DEAD) for st in states):
            reasons = {str(l.get('status')) for l in links} | {str(l.get('availability')) for l in grabber}
            return {'found': True, 'status': 'Failed', 'data': (links or grabber)[0], 'reason': '; '.join(sorted(reasons))}
        # a dead mirror (say one blocked by Cloudflare) isn't the job's state while another one is still going
        unavailable = lambda l: any(d in str(l.get('availability') or '').lower() for d in self.DEAD)
        alive = [l for l in links if not is_dead(l)] + [l for l in grabber if not unavailable(l)]
        first = (alive or links or grabber)[0]
        # bytes downloaded so far across the package, so the monitor can tell a slow download from a stuck one
        loaded = [l['bytesLoaded'] for l in links if isinstance(l.get('bytesLoaded'), (int, float))]
        return {'found': True, 'status': first.get('status') or 'Queued', 'data': first, 'loaded': sum(loaded) if loaded else None}

    def _save_to(self, packages):
        """{package uuid: the folder JD2 saves it to} for these packages of the download list."""
        if not packages:
            return {}
        r = self.session.get(self._url('downloadsV2/queryPackages'),
                             params={'queryParams': json.dumps({'uuid': True, 'name': True, 'saveTo': True, 'packageUUIDs': packages})},
                             timeout=self.timeout)
        r.raise_for_status()
        return {p.get('uuid'): p['saveTo'] for p in (r.json() or {}).get('data') or []
                if isinstance(p, dict) and p.get('uuid') in packages and p.get('saveTo')}

    def folder(self, job_id: str, record_id: Optional[str] = None, package=None) -> Optional[str]:
        """The folder JD2 saved the job's download in, as Issuarr sees it. JD2 can rename a package
        after the post's own folder name, or file it in a dated subfolder, so it isn't always the
        name Issuarr asked for. `package` is the package of the file that finished, when known."""
        try:
            packages = self._job_links(job_id, record_id)['downloadsV2'][1]
            save_to = self._save_to(packages)
            path = save_to.get(package) or next((save_to[p] for p in packages if p in save_to), None)
            return local_path(path)
        except Exception as err:
            logger.warn('[JD2] Unable to look up the folder of job %s: %s', job_id, err)
        return None

    def tagged_packages(self) -> List[Dict[str, Any]]:
        """The packages in JD2's download list marked for Issuarr: the package or one of its links
        has the comment. Each is {'uuid', 'name', 'saveTo', 'links'}, with all of the package's links."""
        r = self.session.get(self._url('downloadsV2/queryPackages'),
                             params={'queryParams': json.dumps({'uuid': True, 'name': True, 'saveTo': True, 'comment': True,
                                                                'maxResults': -1, 'startAt': 0})},
                             timeout=self.timeout)
        r.raise_for_status()
        packages = {p.get('uuid'): p for p in (r.json() or {}).get('data') or [] if isinstance(p, dict) and p.get('uuid')}
        links = self._links('downloadsV2/queryLinks', {'comment': True, 'enabled': True})
        by_package = {}
        for l in links:
            by_package.setdefault(l.get('packageUUID'), []).append(l)
        out = []
        for uuid, p in packages.items():
            package_links = by_package.get(uuid) or []
            if tagged(p.get('comment')) or any(tagged(l.get('comment')) for l in package_links):
                out.append({'uuid': uuid, 'name': p.get('name'), 'saveTo': p.get('saveTo'), 'links': package_links})
        return out

    def remove_packages(self, packages: List[Any]) -> None:
        """Take packages off JD2's download list. Their files stay where they are."""
        if packages:
            self.session.get(self._url('downloadsV2/removeLinks'), params={'linkIds': '[]', 'packageIds': json.dumps(list(packages))},
                             timeout=self.timeout)

    def remove(self, job_id: str, record_id: Optional[str] = None) -> None:
        if not job_id and not record_id:
            return
        try:
            found = self._job_links(job_id, record_id)
            try:
                folders = [local_path(f) for f in self._save_to(found['downloadsV2'][1]).values()]
            except Exception:
                folders = []
            for area in ('downloadsV2', 'linkgrabberv2'):
                packages = found[area][1]
                if packages:
                    self.session.get(self._url('%s/removeLinks' % area), params={'linkIds': '[]', 'packageIds': json.dumps(packages)}, timeout=self.timeout)
            for folder in folders:
                # JD2 makes a package's folder when it starts on it; one whose links never downloaded stays empty
                try:
                    if folder and os.path.normpath(folder) != os.path.normpath(local_folder() or '') and os.path.isdir(folder) and not os.listdir(folder):
                        os.rmdir(folder)
                except OSError:
                    pass
        except Exception as err:
            logger.warn('[JD2] Unable to remove job %s from JD2: %s', job_id, err)
