from __future__ import annotations

# ruff: noqa: F403, F405
from ..route_helpers import *

router = APIRouter()


@router.post('/v1/auth/demo-token', response_model=TokenResponse)
def issue_demo_token(payload: DemoTokenRequest, runtime: AppRuntime = Depends(get_app_runtime)) -> TokenResponse:
    if not runtime.settings.auth_demo_tokens_enabled:
        raise HTTPException(status_code=404, detail='Demo token issuance is disabled.')
    token = create_access_token(
        settings=runtime.settings,
        user_id=payload.user_id,
        tenant_id=payload.tenant_id,
        scopes=payload.scopes,
    )
    return TokenResponse(
        access_token=token,
        expires_in_seconds=runtime.settings.auth_access_token_ttl_seconds,
        issuer=runtime.settings.auth_jwt_issuer,
    )

@router.get('/v1/auth/me', response_model=PrincipalResponse)
def get_me(principal: Principal = Depends(get_current_principal), runtime: AppRuntime = Depends(get_app_runtime)) -> PrincipalResponse:
    return PrincipalResponse(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        scopes=list(principal.scopes),
        auth_enabled=runtime.settings.auth_enabled,
    )

@router.get('/v1/models', response_model=ModelCatalogResponse)
def list_models(
    principal: Principal = Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> ModelCatalogResponse:
    del principal
    return ModelCatalogResponse(
        default_model=runtime.settings.model,
        models=[
            {
                "id": item.id,
                "provider": item.provider,
                "provider_label": item.provider_label,
                "name": item.name,
                "label": item.label,
                "is_default": item.is_default,
                "supports_thinking": item.supports_thinking,
                "default_thinking_enabled": item.default_thinking_enabled,
            }
            for item in build_model_catalog(runtime.settings)
        ],
    )
