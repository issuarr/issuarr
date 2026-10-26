import pytest

from mylar.downloaders import pixeldrain


@pytest.mark.unit
@pytest.mark.parametrize('url, expected', [
    ('https://pixeldrain.com/l/AbC123', 'AbC123'),
    ('https://pixeldrain.net/l/AbC123#item=2', 'AbC123'),
    ('https://pixeldrain.com/api/list/xyz9', 'xyz9'),
    ('https://pixeldrain.com/u/AbC123', None),
    ('https://getcomics.org/dls/abc', None),
    (None, None),
])
def test_album_id(url, expected):
    assert pixeldrain.album_id(url) == expected


@pytest.mark.unit
def test_pick_album_file_prefers_the_largest_comic():
    files = [{'id': 'a', 'name': 'cover.jpg', 'size': 900}, {'id': 'b', 'name': 'Saga 054.cbz', 'size': 50},
             {'id': 'c', 'name': 'Saga 054 (HD).CBR', 'size': 80}]
    assert pixeldrain.pick_album_file(files)['id'] == 'c'


@pytest.mark.unit
def test_pick_album_file_falls_back_to_the_largest_file():
    assert pixeldrain.pick_album_file([{'id': 'a', 'name': 'x.bin', 'size': 1}, {'id': 'b', 'name': 'y', 'size': 9}])['id'] == 'b'
    assert pixeldrain.pick_album_file([]) is None
    assert pixeldrain.pick_album_file(None) is None
