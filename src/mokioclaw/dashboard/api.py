from __future__ import annotations

from dataclasses import asdict
import hmac
from pathlib import Path
import re
import secrets
from threading import Lock

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from mokioclaw.dashboard.catalog import RepositoryCatalog, RegisteredRepository
from mokioclaw.dashboard.git_reader import (
    CommitNotFound, GitOutputLimit, GitReadError, GitReadTimeout, InvalidRepository, LocalGitReader,
)
from mokioclaw.dashboard.pagination import CursorCodec, InvalidCursor
from mokioclaw.dashboard.priority import RULE_VERSION, assess_commit
from mokioclaw.dashboard.task_api import install_task_routes, task_error
from mokioclaw.dashboard.task_service import TaskService


def _error(status: int, code: str, message: str, retryable: bool = False) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message, "retryable": retryable})


def create_dashboard_app(
    catalog: RepositoryCatalog, reader: LocalGitReader, cursor_codec: CursorCodec,
    task_service: TaskService | None = None,
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    csrf_token = secrets.token_urlsafe(32)
    static_root = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static_root), name="dashboard-static")
    detail_cache: dict[tuple[str, str, str, str], dict] = {}
    cache_lock = Lock()

    @app.middleware("http")
    async def secure_response(request: Request, call_next):
        host = request.headers.get("host", "").split(":", 1)[0].lower()
        if host != "127.0.0.1":
            response = _error(400, "invalid_host", "Use the local dashboard address.")
        elif request.method == "POST" and request.url.path.startswith(("/api/tasks", "/api/task-previews")):
            raw_host = request.headers.get("host", "")
            origin = request.headers.get("origin", "")
            token = request.headers.get("x-mokioclaw-csrf", "")
            if not re.fullmatch(r"127\.0\.0\.1(?::(?:[1-9][0-9]{0,4}))?", raw_host) or origin != f"http://{raw_host}":
                response = task_error(403, "invalid_origin", "Local write authorization failed.")
            elif not hmac.compare_digest(token, csrf_token):
                response = task_error(403, "invalid_csrf", "Local write authorization failed.")
            elif request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                response = task_error(415, "invalid_content_type", "A JSON request is required.")
            else:
                try:
                    length = request.headers.get("content-length")
                    if length is not None and (not length.isdigit() or int(length) > 16_384):
                        response = task_error(413, "request_too_large", "The request is too large.")
                    else:
                        body = bytearray()
                        async for chunk in request.stream():
                            body.extend(chunk)
                            if len(body) > 16_384:
                                break
                        if len(body) > 16_384:
                            response = task_error(413, "request_too_large", "The request is too large.")
                        else:
                            request._body = bytes(body)
                            response = await call_next(request)
                except Exception:
                    response = _error(500, "internal_error", "The request could not be completed.")
        else:
            try:
                response = await call_next(request)
            except Exception:
                response = _error(500, "internal_error", "The request could not be completed.")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException):
        if exc.status_code == 405:
            return _error(405, "method_not_allowed", "Only supported read requests are available.")
        if exc.status_code == 404:
            return _error(404, "not_found", "The requested resource was not found.")
        return _error(exc.status_code, "request_error", "The request could not be completed.")

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError):
        return _error(400, "invalid_request", "The request parameters are invalid.")

    @app.exception_handler(InvalidCursor)
    async def cursor_error(_request: Request, _exc: InvalidCursor):
        return _error(400, "invalid_cursor", "The page cursor is invalid.")

    @app.exception_handler(ValueError)
    async def value_error(_request: Request, _exc: ValueError):
        return _error(400, "invalid_sha", "A full commit SHA is required.")

    @app.exception_handler(CommitNotFound)
    async def commit_error(_request: Request, _exc: CommitNotFound):
        return _error(404, "commit_not_found", "The commit is unavailable in this history.")

    async def git_limit_error(_request: Request, exc: GitReadTimeout | GitOutputLimit):
        code = "git_timeout" if isinstance(exc, GitReadTimeout) else "git_output_limit"
        return _error(503, code, "Repository reading could not finish. Try again.", True)

    async def repository_error(_request: Request, _exc: InvalidRepository | GitReadError):
        return _error(503, "repository_unavailable", "This repository is currently unavailable.", True)

    for error_type in (GitReadTimeout, GitOutputLimit):
        app.add_exception_handler(error_type, git_limit_error)
    for error_type in (InvalidRepository, GitReadError):
        app.add_exception_handler(error_type, repository_error)

    def registered(repo_id: str) -> RegisteredRepository:
        repository = catalog.get(repo_id)
        if repository is None:
            raise HTTPException(404)
        return repository

    def state_for(repository: RegisteredRepository):
        state = reader.inspect(repository.root)
        if state.root != repository.root or state.object_format != repository.state.object_format:
            raise InvalidRepository("Repository identity changed")
        return state

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_root / "index.html", media_type="text/html")

    @app.get("/api/repositories")
    def repositories():
        return [asdict(item) for item in catalog.summaries()]

    @app.get("/api/repositories/{repo_id}/commits")
    def commits(repo_id: str, cursor: str | None = None):
        repository = registered(repo_id)
        state = state_for(repository)
        if cursor is None:
            anchor_sha, offset = state.head_sha, 0
        else:
            decoded = cursor_codec.decode(cursor, repo_id)
            anchor_sha, offset = decoded.anchor_sha, decoded.offset
        if anchor_sha is None:
            return {"repo_id": repo_id, "anchor_sha": None, "current_head_sha": None, "commits": [], "next_cursor": None}
        rows = reader.list_commits(repository.root, anchor_sha, offset, limit=50)
        more = bool(reader.list_commits(repository.root, anchor_sha, offset + 50, limit=1)) if len(rows) == 50 else False
        return {
            "repo_id": repo_id,
            "anchor_sha": anchor_sha,
            "current_head_sha": state.head_sha,
            "commits": [asdict(row) for row in rows],
            "next_cursor": cursor_codec.encode(repo_id, anchor_sha, offset + 50) if more else None,
        }

    @app.get("/api/repositories/{repo_id}/commits/{sha}")
    def commit_detail(repo_id: str, sha: str, anchor: str | None = None):
        repository = registered(repo_id)
        state_for(repository)
        if anchor is None:
            return _error(400, "invalid_anchor", "A full history anchor is required.")
        cache_key = (repo_id, anchor.lower(), sha.lower(), RULE_VERSION)
        with cache_lock:
            cached = detail_cache.get(cache_key)
        if cached is not None:
            return cached
        detail = reader.get_commit(repository.root, sha, anchor)
        result = {"repo_id": repo_id, "anchor_sha": anchor.lower(), "detail": asdict(detail), "assessment": asdict(assess_commit(detail))}
        with cache_lock:
            if len(detail_cache) >= 512:
                detail_cache.clear()
            detail_cache[cache_key] = result
        return result

    install_task_routes(app, task_service, csrf_token)
    return app
