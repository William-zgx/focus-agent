"""Shared pagination query parameter types for list endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

MAX_PAGE_LIMIT = 200

# ``limit`` must request at least one item; ``limit=0`` used to silently return an empty page on
# some endpoints and 422 on others. Endpoints keep their own default value.
PageLimit = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)]
PageOffset = Annotated[int, Query(ge=0)]

__all__ = ["MAX_PAGE_LIMIT", "PageLimit", "PageOffset"]
