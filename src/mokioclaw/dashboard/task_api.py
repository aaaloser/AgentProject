"""Narrow, local-only task routes; no raw task files or provider data."""

from __future__ import annotations

import re
from dataclasses import asdict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from mokioclaw.dashboard.task_service import InvalidTaskRequest, TaskService
from mokioclaw.dashboard.task_source import InvalidTaskPreview
from mokioclaw.dashboard.task_store import TaskConflict


_PREVIEW_FIELDS = frozenset({"repo_id", "base_sha", "anchor_sha", "source_read_scope"})
_CREATE_FIELDS = _PREVIEW_FIELDS | frozenset({
    "preview_id", "description", "max_seconds", "max_attempts", "verification_commands",
    "max_provider_calls", "max_total_tokens", "max_output_tokens_per_call",
})
_TASK_ID = re.compile(r"[A-Za-z0-9_-]{16,64}\Z")


def task_error(status: int, code: str, message: str, retryable: bool = False) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message, "retryable": retryable})


def _record(record) -> dict:
    return {
        "task_id": record.task_id, "repo_id": record.repo_id, "base_sha": record.base_sha,
        "anchor_sha": record.anchor_sha, "state": record.state, "sequence": record.sequence,
        "attempt_id": record.attempt_id, "failure_kind": record.failure_kind,
        "verification_status": record.verification_status, "created_at": record.created_at,
    }


async def _body(request: Request, fields: frozenset[str]) -> dict:
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidTaskRequest("Invalid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != fields:
        raise InvalidTaskRequest("Invalid request fields")
    return payload


def install_task_routes(app: FastAPI, service: TaskService | None, csrf_token: str) -> None:
    def available() -> TaskService:
        if service is None:
            raise RuntimeError("task_unavailable")
        return service

    @app.get("/api/task-session")
    def session() -> dict:
        return {"csrf_token": csrf_token, "task_available": service is not None, "run_available": False}

    @app.post("/api/task-previews")
    async def preview(request: Request):
        if service is None:
            return task_error(503, "task_unavailable", "Local tasks are not enabled.")
        try:
            result = await run_in_threadpool(available().preview, await _body(request, _PREVIEW_FIELDS))
        except (InvalidTaskRequest, InvalidTaskPreview, KeyError, TypeError):
            return task_error(400, "invalid_preview", "The source preview request is invalid.")
        return {
            "preview_id": result.preview_id, "repo_id": result.repo_id, "base_sha": result.base_sha,
            "anchor_sha": result.anchor_sha, "manifest_digest": result.manifest_digest,
            "source_read_scope": result.source_read_scope, "file_count": result.file_count,
            "total_bytes": result.total_bytes, "blocked_paths": [asdict(item) for item in result.blocked_paths],
            "expires_at": result.expires_at, "content_checks_pending": result.content_checks_pending,
        }

    @app.post("/api/tasks")
    async def create(request: Request):
        if service is None:
            return task_error(503, "task_unavailable", "Local tasks are not enabled.")
        key = request.headers.get("idempotency-key", "")
        try:
            record = available().create_task(await _body(request, _CREATE_FIELDS), key)
        except (InvalidTaskRequest, InvalidTaskPreview, KeyError, TypeError):
            return task_error(400, "invalid_task", "The task request is invalid.")
        except TaskConflict:
            return task_error(409, "task_conflict", "This task request conflicts with an existing task.")
        return JSONResponse(status_code=202, content=_record(record))

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        if service is None:
            return task_error(503, "task_unavailable", "Local tasks are not enabled.")
        if not _TASK_ID.fullmatch(task_id):
            return task_error(404, "task_not_found", "The task is unavailable.")
        try:
            return _record(available().get(task_id))
        except KeyError:
            return task_error(404, "task_not_found", "The task is unavailable.")

    @app.get("/api/tasks/{task_id}/events")
    def events(task_id: str, after: int = 0):
        if service is None:
            return task_error(503, "task_unavailable", "Local tasks are not enabled.")
        if not _TASK_ID.fullmatch(task_id) or after < 0:
            return task_error(404, "task_not_found", "The task is unavailable.")
        try:
            record = available().get(task_id)
        except KeyError:
            return task_error(404, "task_not_found", "The task is unavailable.")
        return {"task_id": task_id, "events": [asdict(event) for event in record.events if event.sequence > after][:100]}

    @app.post("/api/tasks/{task_id}/run")
    async def run(task_id: str, request: Request):
        if service is None:
            return task_error(503, "task_unavailable", "Local tasks are not enabled.")
        try:
            await _body(request, frozenset())
            record = available().get(task_id) if _TASK_ID.fullmatch(task_id) else None
        except (InvalidTaskRequest, KeyError):
            return task_error(404, "task_not_found", "The task is unavailable.")
        if record is None:
            return task_error(404, "task_not_found", "The task is unavailable.")
        if available().store.has_active_task(exclude_task_id=task_id):
            return task_error(409, "task_busy", "Another task is active; try again later.", True)
        return task_error(503, "run_unavailable", "Agent execution is not enabled.")
