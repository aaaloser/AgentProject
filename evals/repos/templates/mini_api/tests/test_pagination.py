import pytest

from mini_api.pagination import paginate


def test_first_page_points_to_second_page() -> None:
    assert paginate([1, 2, 3], page=1, page_size=2) == {
        "items": [1, 2],
        "page": 1,
        "page_size": 2,
        "next_page": 2,
    }


def test_rejects_non_positive_page_values() -> None:
    with pytest.raises(ValueError):
        paginate([1], page=0, page_size=1)
