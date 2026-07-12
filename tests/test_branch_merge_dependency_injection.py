from __future__ import annotations

import inspect

from focus_agent.core.merge_review import generate_merge_proposal
from focus_agent.services.branches.service import BranchService


def test_branch_service_exposes_explicit_proposal_generator_dependency() -> None:
    parameter = inspect.signature(BranchService).parameters["proposal_generator"]

    assert parameter.default is generate_merge_proposal
