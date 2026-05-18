"""Compatibility shim for ``focus_agent.services.branches.actions``."""

from focus_agent.services.branches.actions import *
from focus_agent.services.branches.actions import (  # noqa: F401
    _clean_name as _clean_name,
    _compact as _compact,
    _extract_branch_name as _extract_branch_name,
    _extract_topic_name as _extract_topic_name,
)
