import os
import types

import pytest

import mylar
from mylar import librarysync


@pytest.fixture
def tree(tmp_path):
    for d in ('Marvel/Avengers', '_Duplicates', '_UNMATCHED/Other', '.hidden', 'Marvel/_Extras', 'dump', 'Image'):
        (tmp_path / d).mkdir(parents=True)
        (tmp_path / d / 'x 1 (2000).cbz').write_bytes(b'x')
    return tmp_path


def walked(root, work):
    seen = []
    for r, d, f in os.walk(root):
        librarysync.skip_work_folders(r, d, work)
        seen += [os.path.relpath(os.path.join(r, n), root).replace(os.sep, '/') for n in f]
    return sorted(seen)


@pytest.mark.unit
def test_underscore_and_dot_folders_are_not_entered(tree):
    seen = walked(str(tree), [])
    assert 'Marvel/Avengers/x 1 (2000).cbz' in seen
    assert 'Image/x 1 (2000).cbz' in seen
    assert not [p for p in seen if p.startswith(('_', '.')) or '/_' in p]


@pytest.mark.unit
def test_configured_work_folders_are_not_entered(tree):
    seen = walked(str(tree), [os.path.normpath(str(tree / 'dump'))])
    assert 'dump/x 1 (2000).cbz' not in seen
    assert 'Image/x 1 (2000).cbz' in seen


@pytest.mark.unit
def test_the_scan_root_itself_may_start_with_an_underscore(tree):
    seen = walked(str(tree / '_UNMATCHED'), [])
    assert seen == ['Other/x 1 (2000).cbz']


@pytest.mark.unit
def test_work_folders_come_from_the_settings(monkeypatch, tmp_path):
    cfg = types.SimpleNamespace(DUPLICATE_DUMP=str(tmp_path / 'dupes') + '/', ARCHIVE_REVIEW_DIR=str(tmp_path / 'review'),
                                CHECK_FOLDER=None, CACHE_DIR=str(tmp_path / 'cache'))
    monkeypatch.setattr(mylar, 'CONFIG', cfg, raising=False)
    work = librarysync.work_folders()
    assert os.path.normpath(str(tmp_path / 'dupes')) in work
    assert os.path.normpath(str(tmp_path / 'review')) in work
    cfg.DUPLICATE_DUMP = None
    assert None not in librarysync.work_folders()
