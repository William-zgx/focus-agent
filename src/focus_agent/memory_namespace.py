"""Compatibility shim.

Canonical import:
    from focus_agent.storage.namespaces import *
"""

from .storage.namespaces import (
    branch_namespace,
    conversation_main_namespace,
    conversation_namespace_for_context,
    is_user_profile_payload_allowed,
    user_profile_namespace,
)

__all__ = [
    "branch_namespace",
    "conversation_main_namespace",
    "conversation_namespace_for_context",
    "is_user_profile_payload_allowed",
    "user_profile_namespace",
]
