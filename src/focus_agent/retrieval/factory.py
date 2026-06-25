from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .index import RetrievalIndex
from .zvec_index import ZvecRetrievalIndex

logger = logging.getLogger(__name__)


def create_retrieval_index(
    settings: Any,
    *,
    dimensions: int,
) -> tuple[RetrievalIndex | None, str | None]:
    if not bool(getattr(settings, "agent_zvec_enabled", True)):
        return None, "disabled"
    backend = str(getattr(settings, "agent_retrieval_backend", "zvec") or "zvec").lower()
    if backend not in {"zvec", "auto"}:
        return None, f"backend={backend}"
    data_dir = Path(
        getattr(settings, "agent_zvec_data_dir", None) or ".focus_agent/zvec"
    ).expanduser()
    try:
        return ZvecRetrievalIndex(data_dir=data_dir, dimensions=dimensions), None
    except Exception as exc:  # noqa: BLE001
        logger.info("zvec retrieval index unavailable; falling back: %s", exc)
        logger.debug("zvec retrieval index creation failed", exc_info=True)
        return None, f"zvec_unavailable: {type(exc).__name__}"
