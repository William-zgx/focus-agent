from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from focus_agent.core.branching import MergeDecision, MergeMode, MergeTarget
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.tokens import Principal
from focus_agent.services.chat_turn_errors import ConcurrentTurnError

from ..contracts import (
    ApplyMergeDecisionRequest,
    ApplyMergeDecisionResponse,
    BranchTreeResponse,
    ForkBranchRequest,
    PrepareMergeProposalRequest,
    UpdateBranchNameRequest,
)
from ..deps import get_app_runtime, get_current_principal
from ..route_utils.token_usage import (
    _annotate_branch_tree_token_usage,
    _token_usage_by_thread_for_root,
    _token_usage_for_root_thread,
)

router = APIRouter()


@router.post("/v1/branches/fork")
def create_branch(
    payload: ForkBranchRequest,
    runtime: AppRuntime = Depends(get_app_runtime),
    principal: Principal = Depends(get_current_principal),
):
    try:
        record = runtime.branch_service.fork_branch(
            parent_thread_id=payload.parent_thread_id,
            user_id=principal.user_id,
            branch_name=payload.branch_name,
            name_source=payload.name_source,
            language=payload.language,
            branch_role=payload.branch_role,
            fork_checkpoint_id=payload.fork_checkpoint_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentTurnError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return record.model_dump(mode="json")


@router.post("/v1/branches/{child_thread_id}/archive")
def archive_branch_route(
    child_thread_id: str,
    runtime: AppRuntime = Depends(get_app_runtime),
    principal: Principal = Depends(get_current_principal),
):
    try:
        record = runtime.branch_service.archive_branch(
            child_thread_id=child_thread_id,
            user_id=principal.user_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentTurnError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        _raise_child_thread_diagnostic(
            runtime=runtime,
            thread_id=child_thread_id,
            user_id=principal.user_id,
            exc=exc,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return record.model_dump(mode="json")


@router.patch("/v1/branches/{child_thread_id}")
def rename_branch_route(
    child_thread_id: str,
    payload: UpdateBranchNameRequest,
    runtime: AppRuntime = Depends(get_app_runtime),
    principal: Principal = Depends(get_current_principal),
):
    branch_name = str(payload.branch_name or "").strip()
    if not branch_name:
        raise HTTPException(status_code=400, detail="Branch name cannot be empty.")
    try:
        record = runtime.branch_service.rename_branch(
            child_thread_id=child_thread_id,
            user_id=principal.user_id,
            branch_name=branch_name,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentTurnError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        _raise_child_thread_diagnostic(
            runtime=runtime,
            thread_id=child_thread_id,
            user_id=principal.user_id,
            exc=exc,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return record.model_dump(mode="json")


@router.post("/v1/branches/{child_thread_id}/activate")
def activate_branch_route(
    child_thread_id: str,
    runtime: AppRuntime = Depends(get_app_runtime),
    principal: Principal = Depends(get_current_principal),
):
    try:
        record = runtime.branch_service.activate_branch(
            child_thread_id=child_thread_id,
            user_id=principal.user_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentTurnError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        _raise_child_thread_diagnostic(
            runtime=runtime,
            thread_id=child_thread_id,
            user_id=principal.user_id,
            exc=exc,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return record.model_dump(mode="json")


@router.post("/v1/branches/{child_thread_id}/proposal")
def prepare_branch_merge_proposal(
    child_thread_id: str,
    payload: PrepareMergeProposalRequest,
    runtime: AppRuntime = Depends(get_app_runtime),
    principal: Principal = Depends(get_current_principal),
):
    del payload
    try:
        proposal = runtime.branch_service.prepare_merge_proposal(
            child_thread_id=child_thread_id,
            user_id=principal.user_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentTurnError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        _raise_child_thread_diagnostic(
            runtime=runtime,
            thread_id=child_thread_id,
            user_id=principal.user_id,
            exc=exc,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return proposal.model_dump(mode="json")


@router.post("/v1/branches/{child_thread_id}/merge", response_model=ApplyMergeDecisionResponse)
def submit_merge_decision(
    child_thread_id: str,
    payload: ApplyMergeDecisionRequest,
    runtime: AppRuntime = Depends(get_app_runtime),
    principal: Principal = Depends(get_current_principal),
) -> ApplyMergeDecisionResponse:
    try:
        require_child = getattr(runtime.branch_service, "_require_child_branch_record", None)
        if callable(require_child):
            record = require_child(
                child_thread_id=child_thread_id,
                user_id=principal.user_id,
                operation="Submitting a merge decision",
            )
        else:
            record = runtime.repo.get_by_child_thread_id(child_thread_id)
    except KeyError as exc:
        _raise_child_thread_diagnostic(
            runtime=runtime,
            thread_id=child_thread_id,
            user_id=principal.user_id,
            exc=exc,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    decision = MergeDecision.model_validate(payload.model_dump(exclude={"user_id"}))
    try:
        imported = runtime.branch_service.apply_merge_decision(
            child_thread_id=child_thread_id,
            decision=decision,
            context=RequestContext(
                user_id=principal.user_id,
                root_thread_id=record.root_thread_id,
            ),
            proposal_overrides=payload.proposal_overrides,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentTurnError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    target_thread_id = None
    if imported is not None and decision.approved and decision.mode != MergeMode.NONE:
        target_thread_id = (
            record.root_thread_id
            if decision.target == MergeTarget.ROOT_THREAD
            else record.return_thread_id
        )
    return ApplyMergeDecisionResponse(imported=imported, target_thread_id=target_thread_id)


@router.get("/v1/branches/tree/{root_thread_id:path}", response_model=BranchTreeResponse)
def get_branch_tree_view(
    root_thread_id: str,
    runtime: AppRuntime = Depends(get_app_runtime),
    principal: Principal = Depends(get_current_principal),
) -> BranchTreeResponse:
    try:
        resolved_root_thread_id = _resolve_root_thread_id(
            runtime=runtime,
            thread_id=root_thread_id,
            user_id=principal.user_id,
        )
        root = runtime.branch_service.get_branch_tree(
            root_thread_id=resolved_root_thread_id, user_id=principal.user_id
        )
        archived_branches = runtime.branch_service.list_archived_branches(
            root_thread_id=resolved_root_thread_id,
            user_id=principal.user_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    token_usage_by_thread = _token_usage_by_thread_for_root(
        runtime=runtime, root_thread_id=resolved_root_thread_id
    )
    root_thread_usage = _token_usage_for_root_thread(
        runtime=runtime, root_thread_id=resolved_root_thread_id
    )
    return BranchTreeResponse(
        root=_annotate_branch_tree_token_usage(
            root,
            by_thread_id=token_usage_by_thread,
            root_thread_usage=root_thread_usage,
        ),
        archived_branches=[
            _annotate_branch_tree_token_usage(
                item,
                by_thread_id=token_usage_by_thread,
                root_thread_usage=root_thread_usage,
            )
            for item in archived_branches
        ],
    )


def _resolve_root_thread_id(*, runtime: AppRuntime, thread_id: str, user_id: str) -> str:
    resolver = getattr(runtime.repo, "resolve_thread_ref", None)
    if not callable(resolver):
        return thread_id
    return str(resolver(thread_id=thread_id, owner_user_id=user_id).root_thread_id)


def _raise_child_thread_diagnostic(
    *,
    runtime: AppRuntime,
    thread_id: str,
    user_id: str,
    exc: KeyError,
) -> None:
    resolver = getattr(runtime.repo, "resolve_thread_ref", None)
    if callable(resolver):
        try:
            resolution = resolver(thread_id=thread_id, owner_user_id=user_id)
        except PermissionError as permission_error:
            raise HTTPException(status_code=403, detail=str(permission_error)) from permission_error
        if resolution.is_root and _is_registered_thread_root(
            runtime=runtime,
            root_thread_id=str(resolution.root_thread_id),
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Thread {thread_id} is a root thread. This branch operation requires "
                    "a child_thread_id."
                ),
            ) from exc
    raise HTTPException(status_code=404, detail=str(exc)) from exc


def _is_registered_thread_root(*, runtime: AppRuntime, root_thread_id: str) -> bool:
    get_owner = getattr(runtime.repo, "get_thread_owner", None)
    if callable(get_owner) and get_owner(thread_id=root_thread_id) is not None:
        return True
    get_conversation = getattr(runtime.repo, "get_conversation", None)
    if not callable(get_conversation):
        return False
    try:
        get_conversation(root_thread_id)
    except Exception:
        return False
    return True
