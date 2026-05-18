from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from focus_agent.api.contract_models.productivity import (
    CaptureNoteRequest,
    CaptureTaskRequest,
    CreateNoteRequest,
    CreateTaskRequest,
    NoteListResponse,
    NoteResponse,
    TaskEventListResponse,
    TaskListResponse,
    TaskResponse,
    UpdateNoteRequest,
    UpdateTaskRequest,
)
from focus_agent.api.deps import get_app_runtime, get_current_principal
from focus_agent.core.productivity import FocusTaskStatus
from focus_agent.engine.runtime import AppRuntime
from focus_agent.repositories.productivity_repository import ProductivityRepository
from focus_agent.services.productivity import ProductivityService

router = APIRouter()


@router.get("/v1/notes", response_model=NoteListResponse)
def list_notes(
    q: str | None = Query(default=None),
    tag: list[str] | None = Query(default=None),
    include_archived: bool = False,
    limit: int = Query(default=50, ge=0, le=200),
    offset: int = Query(default=0, ge=0),
    principal=Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> NoteListResponse:
    items = _repository(runtime).list_notes(
        user_id=principal.user_id,
        query=q,
        tags=tag,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    return NoteListResponse(items=items, count=len(items))


@router.post("/v1/notes", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
def create_note(
    payload: CreateNoteRequest,
    principal=Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> NoteResponse:
    try:
        note = _service(runtime).create_note(user_id=principal.user_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return NoteResponse(note=note)


@router.post(
    "/v1/productivity/capture/note",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
)
def capture_note(
    payload: CaptureNoteRequest,
    principal=Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> NoteResponse:
    try:
        note = _service(runtime).capture_note(user_id=principal.user_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return NoteResponse(note=note)


@router.get("/v1/notes/{note_id}", response_model=NoteResponse)
def get_note(
    note_id: str,
    principal=Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> NoteResponse:
    note = _repository(runtime).get_note(note_id=note_id, user_id=principal.user_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found.")
    return NoteResponse(note=note)


@router.patch("/v1/notes/{note_id}", response_model=NoteResponse)
def update_note(
    note_id: str,
    payload: UpdateNoteRequest,
    principal=Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> NoteResponse:
    try:
        note = _service(runtime).update_note(
            note_id=note_id,
            user_id=principal.user_id,
            **payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found.")
    return NoteResponse(note=note)


@router.get("/v1/tasks", response_model=TaskListResponse)
def list_tasks(
    status_filter: FocusTaskStatus | None = Query(default=None, alias="status"),
    include_archived: bool = False,
    limit: int = Query(default=50, ge=0, le=200),
    offset: int = Query(default=0, ge=0),
    principal=Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TaskListResponse:
    items = _repository(runtime).list_tasks(
        user_id=principal.user_id,
        status=status_filter,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    return TaskListResponse(items=items, count=len(items))


@router.post("/v1/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: CreateTaskRequest,
    principal=Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TaskResponse:
    try:
        task = _service(runtime).create_task(user_id=principal.user_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TaskResponse(task=task)


@router.post(
    "/v1/productivity/capture/task",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def capture_task(
    payload: CaptureTaskRequest,
    principal=Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TaskResponse:
    try:
        task = _service(runtime).capture_task(user_id=principal.user_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TaskResponse(task=task)


@router.patch("/v1/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: str,
    payload: UpdateTaskRequest,
    principal=Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TaskResponse:
    try:
        task = _service(runtime).update_task(
            task_id=task_id,
            user_id=principal.user_id,
            **payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return TaskResponse(task=task)


@router.post("/v1/tasks/{task_id}/complete", response_model=TaskResponse)
def complete_task(
    task_id: str,
    principal=Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TaskResponse:
    task = _service(runtime).complete_task(task_id=task_id, user_id=principal.user_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return TaskResponse(task=task)


@router.post("/v1/tasks/{task_id}/archive", response_model=TaskResponse)
def archive_task(
    task_id: str,
    principal=Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TaskResponse:
    task = _service(runtime).archive_task(task_id=task_id, user_id=principal.user_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return TaskResponse(task=task)


@router.get("/v1/tasks/{task_id}/events", response_model=TaskEventListResponse)
def list_task_events(
    task_id: str,
    principal=Depends(get_current_principal),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> TaskEventListResponse:
    events = _repository(runtime).list_task_events(task_id=task_id, user_id=principal.user_id)
    return TaskEventListResponse(items=events, count=len(events))


def _repository(runtime: AppRuntime) -> ProductivityRepository:
    repository = getattr(runtime, "productivity_repository", None)
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Productivity repository is not configured.",
        )
    return repository


def _service(runtime: AppRuntime) -> ProductivityService:
    service = getattr(runtime, "productivity_service", None)
    if service is not None:
        return service
    service = ProductivityService(_repository(runtime))
    try:
        runtime.productivity_service = service
    except Exception:  # noqa: BLE001
        pass
    return service


__all__ = ["router"]
