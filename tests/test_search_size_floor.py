"""Results whose known size is under 1 MB are dropped as fakes, even with the minimum size off."""
import pytest

from mylar.search_filer import too_small


@pytest.mark.unit
@pytest.mark.parametrize('size,small', [
    (512, True), ('999999', True), (1000000, False), ('48234567', False),
    (0, False), ('0', False), (None, False), ('', False), ('unknown', False),
])
def test_too_small(size, small):
    assert too_small(size) is small
