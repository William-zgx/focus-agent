from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from focus_agent.config import ModelCatalogValidationError
from focus_agent.core.users import AuditDecision
from focus_agent.engine.runtime import AppRuntime
from focus_agent.security.permissions import AuthContext
from focus_agent.services.admin_config import (
    AdminConfigError,
    read_admin_config,
    refresh_admin_skill_config,
    update_admin_model_config,
    update_admin_policy_config,
    update_admin_skill_config,
    update_admin_tool_config,
)
from focus_agent.services.users import UserService

from ..contracts import (
    AdminConfigResponse,
    AdminModelConfigUpdateRequest,
    AdminPolicyConfigUpdateRequest,
    AdminSkillConfigUpdateRequest,
    AdminToolConfigUpdateRequest,
)
from ..deps import get_app_runtime, get_user_service, require_admin_user

router = APIRouter(prefix="/v1/admin/config", tags=["admin"])


@router.get("", response_model=AdminConfigResponse)
def get_admin_config(
    runtime: AppRuntime = Depends(get_app_runtime),
    context: AuthContext = Depends(require_admin_user),
) -> AdminConfigResponse:
    return read_admin_config(runtime, updated_by=context.user.user_id)


@router.patch("/models", response_model=AdminConfigResponse)
def patch_admin_model_config(
    payload: AdminModelConfigUpdateRequest,
    request: Request,
    runtime: AppRuntime = Depends(get_app_runtime),
    user_service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_admin_user),
) -> AdminConfigResponse:
    try:
        response = update_admin_model_config(
            runtime,
            payload,
            updated_by=context.user.user_id,
        )
    except (AdminConfigError, ModelCatalogValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _record_config_audit(
        user_service,
        context,
        request,
        section="models",
        reason=payload.reason,
        requires_restart=response.models.requires_restart,
    )
    return response


@router.patch("/tools", response_model=AdminConfigResponse)
def patch_admin_tool_config(
    payload: AdminToolConfigUpdateRequest,
    request: Request,
    runtime: AppRuntime = Depends(get_app_runtime),
    user_service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_admin_user),
) -> AdminConfigResponse:
    try:
        response = update_admin_tool_config(
            runtime,
            payload,
            updated_by=context.user.user_id,
        )
    except (AdminConfigError, ModelCatalogValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _record_config_audit(
        user_service,
        context,
        request,
        section="tools",
        reason=payload.reason,
        requires_restart=response.tools.requires_restart,
    )
    return response


@router.patch("/skills", response_model=AdminConfigResponse)
def patch_admin_skill_config(
    payload: AdminSkillConfigUpdateRequest,
    request: Request,
    runtime: AppRuntime = Depends(get_app_runtime),
    user_service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_admin_user),
) -> AdminConfigResponse:
    try:
        response = update_admin_skill_config(
            runtime,
            payload,
            updated_by=context.user.user_id,
        )
    except AdminConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _record_config_audit(
        user_service,
        context,
        request,
        section="skills",
        reason=payload.reason,
        requires_restart=response.skills.requires_restart,
    )
    return response


@router.post("/skills/refresh", response_model=AdminConfigResponse)
def refresh_admin_skill_index(
    request: Request,
    runtime: AppRuntime = Depends(get_app_runtime),
    user_service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_admin_user),
) -> AdminConfigResponse:
    response = refresh_admin_skill_config(runtime, updated_by=context.user.user_id)
    _record_config_audit(
        user_service,
        context,
        request,
        section="skills",
        reason="refresh skill index",
        requires_restart=response.skills.requires_restart,
        action="config.skills.refresh",
    )
    return response


@router.patch("/policies", response_model=AdminConfigResponse)
def patch_admin_policy_config(
    payload: AdminPolicyConfigUpdateRequest,
    request: Request,
    runtime: AppRuntime = Depends(get_app_runtime),
    user_service: UserService = Depends(get_user_service),
    context: AuthContext = Depends(require_admin_user),
) -> AdminConfigResponse:
    try:
        response = update_admin_policy_config(
            runtime,
            payload,
            updated_by=context.user.user_id,
        )
    except AdminConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _record_config_audit(
        user_service,
        context,
        request,
        section="policies",
        reason=payload.reason,
        requires_restart=response.policies.requires_restart,
    )
    return response


def _record_config_audit(
    user_service: UserService,
    context: AuthContext,
    request: Request,
    *,
    section: str,
    reason: str | None,
    requires_restart: bool,
    action: str | None = None,
) -> None:
    user_service.record_admin_action(
        actor=context,
        action=action or f"config.{section}.update",
        resource_id=section,
        decision=AuditDecision.SUCCESS,
        reason=reason,
        metadata={
            "resource_type": "config",
            "section": section,
            "requires_restart": requires_restart,
        },
        request_id=getattr(request.state, "request_id", None),
    )


__all__ = ["router"]
