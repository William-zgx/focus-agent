"""Compatibility shim for ``focus_agent.services.branches.merge``."""

from focus_agent.services.branches.merge import *
from focus_agent.services.branches.merge import (  # noqa: F401
    _merge_import_blocked_reason as _merge_import_blocked_reason,
)
