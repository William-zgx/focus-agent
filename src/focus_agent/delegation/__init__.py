"""Consolidated delegation domain modules.

Backward compatibility is preserved by legacy shims under focus_agent/agent_*.py.
"""

from .context_engineering import *
from .context_engineering import __all__ as _context_engineering_all
from .delegation import *
from .delegation import __all__ as _delegation_all
from .delegation_models import *
from .delegation_models import __all__ as _delegation_models_all
from .delegation_planning import *
from .delegation_planning import __all__ as _delegation_planning_all
from .delegation_repair import *
from .delegation_repair import __all__ as _delegation_repair_all
from .delegation_routing import *
from .delegation_routing import __all__ as _delegation_routing_all
from .execution import *
from .execution import __all__ as _execution_all
from .execution_executors import *
from .execution_executors import __all__ as _execution_executors_all
from .execution_modes import *
from .execution_modes import __all__ as _execution_modes_all
from .execution_model_task import *
from .execution_model_task import __all__ as _execution_model_task_all
from .execution_registry import *
from .execution_registry import __all__ as _execution_registry_all
from .execution_types import *
from .execution_types import __all__ as _execution_types_all
from .roles import *
from .roles import __all__ as _roles_all
from .subagents import *
from .subagents import __all__ as _subagents_all
from .task_ledger import *
from .task_ledger import __all__ as _task_ledger_all

__all__ = list(
    dict.fromkeys(
        [
            *_context_engineering_all,
            *_delegation_all,
            *_delegation_models_all,
            *_delegation_planning_all,
            *_delegation_repair_all,
            *_delegation_routing_all,
            *_execution_all,
            *_execution_executors_all,
            *_execution_modes_all,
            *_execution_model_task_all,
            *_execution_registry_all,
            *_execution_types_all,
            *_roles_all,
            *_subagents_all,
            *_task_ledger_all,
        ]
    ).keys()
)
