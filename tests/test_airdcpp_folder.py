import types

import pytest

import mylar
from mylar.downloaders import airdcpp


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.text = ''

    def json(self):
        return self._data


class FakeSession:
    """Stands in for AirDC++: answers the download request, then reports the bundle done at `target`."""
    def __init__(self, target, make_file=None):
        self.target = target
        self.make_file = make_file
        self.posted = []
        self.auth = None

    def post(self, url, json=None, headers=None, timeout=None):
        self.posted.append(json)
        if self.make_file:
            self.make_file()
        return FakeResponse({'bundle_info': {'id': 77}})

    def get(self, url, headers=None, timeout=None):
        return FakeResponse({'status': {'completed': True}, 'target': self.target})


def configure(monkeypatch, tmp_path, **kwargs):
    base = dict(AIRDCPP_HOST='http://airdcpp:5600', AIRDCPP_USERNAME='', AIRDCPP_PASSWORD='',
                AIRDCPP_DOWNLOAD_DIR=str(tmp_path), AIRDCPP_FOLDER_MODE='issuarr', AIRDCPP_REMOTE_DIR='',
                DDL_LOCATION=str(tmp_path))
    base.update(kwargs)
    monkeypatch.setattr(mylar, 'LOG_LEVEL', 0, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(**base), raising=False)


def grab(target, make_file=None):
    dl = airdcpp.AirDCPP()
    dl.session = FakeSession(target, make_file)
    result = dl.download('TTH', 'Batman 001 (2020).cbz', '1', issueid='555', search_instance_id='9')
    return dl.session.posted[0], result


@pytest.mark.unit
def test_default_mode_still_sends_the_download_folder(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    payload, result = grab(None, lambda: (tmp_path / 'Batman 001 (2020).cbz').write_bytes(b'x'))
    assert payload['target_directory'] == str(tmp_path) + '/'
    assert payload['target_name'] == 'Batman 001 (2020).cbz'
    assert result['success'] is True
    assert result['path'] == str(tmp_path) + '/Batman 001 (2020)[__555__].cbz'


@pytest.mark.unit
def test_own_folder_mode_leaves_the_folder_to_airdcpp_and_maps_its_path(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, AIRDCPP_FOLDER_MODE='airdcpp', AIRDCPP_REMOTE_DIR='D:\\Downloads\\')
    (tmp_path / 'Comics').mkdir()
    payload, result = grab('D:\\Downloads\\Comics\\Batman 001 (2020).cbz',
                           lambda: (tmp_path / 'Comics' / 'Batman 001 (2020).cbz').write_bytes(b'x'))
    assert 'target_directory' not in payload
    assert payload['target_name'] == 'Batman 001 (2020).cbz'
    assert result['success'] is True
    assert result['path'] == str(tmp_path) + '/Comics/Batman 001 (2020)[__555__].cbz'


@pytest.mark.unit
def test_own_folder_mode_without_the_folder_does_not_create_it(monkeypatch, tmp_path):
    missing = tmp_path / 'not-mounted'
    configure(monkeypatch, tmp_path, AIRDCPP_FOLDER_MODE='airdcpp', AIRDCPP_DOWNLOAD_DIR=str(missing))
    dl = airdcpp.AirDCPP()
    dl.session = FakeSession(None)
    result = dl.download('TTH', 'x.cbz', '1', search_instance_id='9')
    assert result['success'] is False
    assert dl.session.posted == []
    assert not missing.exists()


@pytest.mark.unit
@pytest.mark.parametrize('target, remote, expected', [
    # no target reported: look in the folder itself
    (None, '', '/comics/dl/file.cbz'),
    # no mapping set: just the file name in the folder
    ('/downloads/sub/file.cbz', '', '/comics/dl/file.cbz'),
    # mapping keeps subfolders
    ('/downloads/sub/file.cbz', '/downloads', '/comics/dl/sub/file.cbz'),
    # Windows paths match without case and with either slash
    ('d:\\Downloads\\file.cbz', 'D:/downloads/', '/comics/dl/file.cbz'),
    # Linux paths keep case, so a near miss falls back to the file name
    ('/Downloads/sub/file.cbz', '/downloads', '/comics/dl/file.cbz'),
    # a directory bundle holds the file
    ('/downloads/Batman/', '/downloads', '/comics/dl/Batman/file.cbz'),
])
def test_local_path(target, remote, expected):
    assert airdcpp.local_path(target, remote, '/comics/dl', 'file.cbz') == expected
