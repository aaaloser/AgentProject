from mini_api.pagination import paginate


def test_last_non_empty_page_has_no_next_page() -> None:
    result = paginate([1, 2, 3], page=2, page_size=2)

    assert result["items"] == [3]
    assert result["next_page"] is None


def test_page_after_last_page_is_empty_without_next_page() -> None:
    result = paginate([1, 2, 3], page=3, page_size=2)

    assert result["items"] == []
    assert result["next_page"] is None
