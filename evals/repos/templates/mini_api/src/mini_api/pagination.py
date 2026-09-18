from __future__ import annotations

from typing import Any


def paginate(items: list[Any], *, page: int, page_size: int) -> dict[str, Any]:
    if page < 1 or page_size < 1:
        raise ValueError("page and page_size must be positive")
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": items[start:end],
        "page": page,
        "page_size": page_size,
        "next_page": page + 1 if end < len(items) else None,
    }
