from __future__ import annotations

# ruff: noqa: F403, F405
from ..route_helpers import *

router = APIRouter()


@router.post('/v1/branches/fork')
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
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return record.model_dump(mode='json')

@router.post('/v1/branches/{child_thread_id}/archive')
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
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return record.model_dump(mode='json')

@router.patch('/v1/branches/{child_thread_id}')
def rename_branch_route(
    child_thread_id: str,
    payload: UpdateBranchNameRequest,
    runtime: AppRuntime = Depends(get_app_runtime),
    principal: Principal = Depends(get_current_principal),
):
    branch_name = str(payload.branch_name or '').strip()
    if not branch_name:
        raise HTTPException(status_code=400, detail='Branch name cannot be empty.')
    try:
        record = runtime.branch_service.rename_branch(
            child_thread_id=child_thread_id,
            user_id=principal.user_id,
            branch_name=branch_name,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return record.model_dump(mode='json')

@router.post('/v1/branches/{child_thread_id}/activate')
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
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return record.model_dump(mode='json')

@router.post('/v1/branches/{child_thread_id}/proposal')
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
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return proposal.model_dump(mode='json')

@router.post('/v1/branches/{child_thread_id}/merge', response_model=ApplyMergeDecisionResponse)
def submit_merge_decision(
    child_thread_id: str,
    payload: ApplyMergeDecisionRequest,
    runtime: AppRuntime = Depends(get_app_runtime),
    principal: Principal = Depends(get_current_principal),
) -> ApplyMergeDecisionResponse:
    try:
        record = runtime.repo.get_by_child_thread_id(child_thread_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    decision = MergeDecision.model_validate(payload.model_dump(exclude={'user_id'}))
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
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApplyMergeDecisionResponse(imported=imported)

@router.get('/v1/branches/tree/{root_thread_id}', response_model=BranchTreeResponse)
def get_branch_tree_view(
    root_thread_id: str,
    runtime: AppRuntime = Depends(get_app_runtime),
    principal: Principal = Depends(get_current_principal),
) -> BranchTreeResponse:
    try:
        root = runtime.branch_service.get_branch_tree(root_thread_id=root_thread_id, user_id=principal.user_id)
        archived_branches = runtime.branch_service.list_archived_branches(
            root_thread_id=root_thread_id,
            user_id=principal.user_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    token_usage_by_thread = _token_usage_by_thread_for_root(runtime=runtime, root_thread_id=root_thread_id)
    root_thread_usage = _token_usage_for_root_thread(runtime=runtime, root_thread_id=root_thread_id)
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
