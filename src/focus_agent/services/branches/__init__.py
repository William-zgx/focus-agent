"""Consolidated branches service modules.

Backward compatibility is preserved by legacy shims under focus_agent.services.branch_*.py.
"""

from focus_agent.core.merge_review import generate_merge_proposal

from .actions import *
from .actions import __all__ as _actions_all
from .merge import *
from .merge import __all__ as _merge_all
from .service import *
from .service import __all__ as _service_all

__all__ = [
    *_service_all,
    *_actions_all,
    *_merge_all,
    "generate_merge_proposal",
]
