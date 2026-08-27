from __future__ import annotations

import math

from fastapi import Response


DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def set_pagination_headers(
    response: Response,
    *,
    total: int,
    page: int,
    page_size: int,
) -> None:
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Page-Size"] = str(page_size)
    response.headers["X-Total-Pages"] = str(math.ceil(total / page_size) if total else 0)


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
