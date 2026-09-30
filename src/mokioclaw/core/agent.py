from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Callable, Iterator

from dotenv import load_dotenv
from langgraph.graph import add_messages

from mokioclaw.core.checkpoint import CheckpointManager, load_resume_inputs, normalize_checkpoint_mode
from mokioclaw.core.execution import CommandExecutor
from mokioclaw.core.paths import default_workspace
from mokioclaw.core.session import (
    append_assistant_turn,
    append_user_turn,
    build_session_context,
    load_or_create_session,
    save_session,
    session_started_event,
    session_turn_saved_event,
    session_turn_started_event,
)
from mokioclaw.core.state import RuntimeState
from mokioclaw.core.trace import TraceRecorder, normalize_trace_mode
from mokioclaw.graph.workflow import build_complex_workflow, build_entry_workflow
from mokioclaw.dashboard.task_executor import TaskExecutionError
from mokioclaw.providers.openai_provider import (
    ProviderSettings, TaskProviderError, create_task_model, task_provider_failure_kind,
)


_TASK_MODEL_STAGES = (
    "entry", "chat", "planner", "code_agent", "verifier", "context_compressor",
)


class _TaskModel:
    def __init__(self, underlying: Any, context: TaskRunContext, stage: str) -> None:
        self._underlying = underlying
        self._context = context
        self._stage = stage

    def bind_tools(self, tools: Any, **kwargs: Any) -> _TaskModel:
        try:
            return _TaskModel(self._underlying.bind_tools(tools, **kwargs), self._context, self._stage)
        except Exception:
            raise TaskProviderError("provider_setup_failed") from None

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        context = self._context
        with context._lock:
            if context._usage_unavailable:
                raise TaskProviderError("usage_unavailable")
            if (context.provider_calls >= context.max_provider_calls
                    or context.reported_tokens >= context.max_total_tokens):
                raise TaskProviderError("provider_budget_exhausted")
            context.provider_calls += 1
            context._stage_calls[self._stage] += 1
            try:
                response = self._underlying.invoke(messages, **kwargs)
            except Exception as exc:
                raise TaskProviderError(task_provider_failure_kind(exc)) from None
            usage = getattr(response, "usage_metadata", None)
            total = usage.get("total_tokens") if isinstance(usage, dict) else None
            if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                context._usage_unavailable = True
            else:
                context.reported_tokens += total
                context._stage_tokens[self._stage] += total
            return response


class TaskRunContext:
    """Explicit task model and shared attempt-spanning provider budget."""

    allow_web_search = False
    trace_mode = "off"
    checkpoint_mode = "off"

    def __init__(
        self,
        model_factory: Callable[[], Any],
        *,
        max_provider_calls: int,
        max_total_tokens: int,
        max_output_tokens_per_call: int,
    ) -> None:
        if (not 1 <= max_provider_calls <= 20 or not 1 <= max_total_tokens <= 100_000
                or not 1 <= max_output_tokens_per_call <= 4096):
            raise TaskProviderError("invalid_provider_budget")
        self._model_factory = model_factory
        self._model: Any | None = None
        self._lock = threading.RLock()
        self._usage_unavailable = False
        self.max_provider_calls = max_provider_calls
        self.max_total_tokens = max_total_tokens
        self.max_output_tokens_per_call = max_output_tokens_per_call
        self.provider_calls = 0
        self.reported_tokens = 0
        self._stage_calls = dict.fromkeys(_TASK_MODEL_STAGES, 0)
        self._stage_tokens = dict.fromkeys(_TASK_MODEL_STAGES, 0)
        self.task_filesystem: Any | None = None
        self.task_tools: list[Any] | None = None
        self.task_gateway: Any | None = None
        self.current_attempt = 1
        self.fixed_verification_commands: tuple[str, ...] = ()

    def attach_tools(
        self, filesystem: Any, tools: list[Any], *, gateway: Any | None = None,
        verification_commands: tuple[str, ...] = (),
    ) -> None:
        if self.task_filesystem is not None or not tools:
            raise ValueError("task_tools_already_configured")
        if any(not isinstance(command, str) or not command.strip() for command in verification_commands):
            raise ValueError("task_verification_invalid")
        self.task_filesystem = filesystem
        self.task_tools = list(tools)
        self.task_gateway = gateway
        self.fixed_verification_commands = tuple(verification_commands)

    def begin_attempt(self, attempt_id: int) -> None:
        with self._lock:
            if attempt_id == self.current_attempt:
                return
            if attempt_id != self.current_attempt + 1 or self.task_gateway is None:
                raise TaskExecutionError("task_attempt_invalid")
            try:
                self.task_gateway.set_attempt(attempt_id)
            except Exception:
                raise TaskExecutionError("task_attempt_invalid") from None
            self.current_attempt = attempt_id

    @classmethod
    def from_settings(
        cls,
        settings: ProviderSettings,
        *,
        max_provider_calls: int,
        max_total_tokens: int,
        max_output_tokens_per_call: int,
    ) -> TaskRunContext:
        return cls(
            lambda: create_task_model(settings, max_output_tokens=max_output_tokens_per_call),
            max_provider_calls=max_provider_calls,
            max_total_tokens=max_total_tokens,
            max_output_tokens_per_call=max_output_tokens_per_call,
        )

    @classmethod
    def for_fake_model(
        cls,
        model: Any,
        *,
        max_provider_calls: int,
        max_total_tokens: int,
        max_output_tokens_per_call: int,
    ) -> TaskRunContext:
        return cls(
            lambda: model,
            max_provider_calls=max_provider_calls,
            max_total_tokens=max_total_tokens,
            max_output_tokens_per_call=max_output_tokens_per_call,
        )

    def model(self, *, stage: str) -> _TaskModel:
        if stage not in _TASK_MODEL_STAGES:
            raise ValueError("task_model_stage_invalid")
        with self._lock:
            if self._model is None:
                try:
                    self._model = self._model_factory()
                except TaskProviderError:
                    raise
                except Exception:
                    raise TaskProviderError("provider_setup_failed") from None
            return _TaskModel(self._model, self, stage)

    def usage_snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                key: value
                for stage in _TASK_MODEL_STAGES
                for key, value in (
                    (f"{stage}_calls", self._stage_calls[stage]),
                    (f"{stage}_reported_tokens", self._stage_tokens[stage]),
                )
            }

    @property
    def usage_unavailable(self) -> bool:
        with self._lock:
            return self._usage_unavailable


def create_runtime(
    workspace: Path | None = None,
    *,
    approval_mode: str = "inline",
    approval_handler=None,
    checkpoint_mode: str | None = None,
    resume_from: Path | None = None,
    trace_mode: str | None = None,
    command_executor: CommandExecutor | None = None,
    allow_web_search: bool = True,
    task_context: TaskRunContext | None = None,
) -> RuntimeState:
    if task_context is not None:
        filesystem = task_context.task_filesystem
        if filesystem is None or task_context.task_tools is None or resume_from is not None:
            raise ValueError("task_context_incomplete")
        selected = workspace or filesystem.prepared.work
        if (not selected.is_dir() or selected.is_symlink()
                or selected.resolve(strict=True) != filesystem.prepared.work.resolve(strict=True)):
            raise ValueError("task_workspace_mismatch")
        return RuntimeState(
            workspace=selected, approval_mode="deny", checkpoint_mode="off", trace_mode="off",
            command_executor=None, allow_web_search=False, bash_env_file=None,
            task_filesystem=filesystem,
        )
    load_dotenv()
    selected = workspace or resume_from or default_workspace()
    selected.mkdir(parents=True, exist_ok=True)
    return RuntimeState(
        workspace=selected,
        approval_mode=approval_mode,
        approval_handler=approval_handler,
        bash_default_timeout_seconds=_env_int("MOKIO_BASH_DEFAULT_TIMEOUT_SECONDS", 120),
        bash_max_timeout_seconds=_env_int("MOKIO_BASH_MAX_TIMEOUT_SECONDS", 600),
        bash_max_output_chars=_env_int("MOKIO_BASH_MAX_OUTPUT_CHARS", 6000),
        bash_env_file=_env_path("MOKIO_BASH_ENV_FILE"),
        checkpoint_mode=normalize_checkpoint_mode(checkpoint_mode or os.getenv("MOKIO_CHECKPOINT_MODE", "light")),
        resume_from=resume_from,
        trace_mode=normalize_trace_mode(trace_mode or os.getenv("MOKIO_TRACE_MODE", "on")),
        command_executor=command_executor,
        allow_web_search=allow_web_search,
    )


def stream_agent_events(
    task: str | None = None,
    *,
    workspace: Path | None = None,
    max_attempts: int = 3,
    approval_mode: str = "inline",
    approval_handler=None,
    checkpoint_mode: str | None = None,
    resume_workspace: Path | None = None,
    trace_mode: str | None = None,
    command_executor: CommandExecutor | None = None,
    allow_web_search: bool = True,
    task_context: TaskRunContext | None = None,
) -> Iterator[dict[str, Any]]:
    if task_context is not None and resume_workspace is not None:
        raise ValueError("task_resume_unavailable")
    if task_context is not None and (task_context.task_filesystem is None or task_context.task_tools is None):
        raise ValueError("task_context_incomplete")
    resume_path = resume_workspace.expanduser() if resume_workspace is not None else None
    if resume_path is None:
        route = "workflow"
        entry_state: dict[str, Any] = {"task": task or "", "messages": []}
        if task_context is not None:
            entry_state["task_context"] = task_context
        for mode, event in build_entry_workflow().stream(entry_state, stream_mode=["updates", "custom"]):
            if mode == "custom":
                yield {"type": "custom_event", "event": event}
                if isinstance(event, dict) and event.get("type") == "intent_decision":
                    route = str(event.get("route") or "workflow")
            else:
                _merge_graph_update(entry_state, event)
                yield {"type": "graph_event", "event": event}
        if route == "chat":
            return

    selected_workspace = resume_path or workspace
    state = create_runtime(
        selected_workspace,
        approval_mode=approval_mode,
        approval_handler=approval_handler,
        checkpoint_mode=checkpoint_mode,
        resume_from=resume_path,
        trace_mode=trace_mode,
        command_executor=command_executor,
        allow_web_search=allow_web_search,
        task_context=task_context,
    )
    workflow = build_complex_workflow()
    yield {"type": "workspace", "path": str(state.workspace)}

    resumed = False
    resume_event: dict[str, Any] | None = None
    if resume_path is not None:
        inputs, resume_event = load_resume_inputs(state, task=task, max_attempts=max_attempts)
        resumed = True
        yield {"type": "custom_event", "event": resume_event}
    else:
        inputs = {
            "task": task or "",
            "runtime": state,
            "messages": [],
            "attempts": 0,
            "max_attempts": max_attempts,
        }
    if task_context is not None:
        inputs["task_context"] = task_context

    yield from _stream_traced_workflow(workflow, inputs, state, resumed=resumed, resume_event=resume_event)


def stream_session_events(
    task: str | None = None,
    *,
    session_workspace: Path | None = None,
    max_attempts: int = 3,
    approval_mode: str = "inline",
    approval_handler=None,
    checkpoint_mode: str | None = None,
    resume_workspace: Path | None = None,
    trace_mode: str | None = None,
    command_executor: CommandExecutor | None = None,
    allow_web_search: bool = True,
) -> Iterator[dict[str, Any]]:
    workspace = (resume_workspace or session_workspace or default_workspace()).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)
    session = load_or_create_session(workspace)
    resumed = resume_workspace is not None
    yield {"type": "custom_event", "event": session_started_event(workspace, session, resumed=resumed)}
    yield {"type": "workspace", "path": str(workspace)}

    if not task:
        return

    turn = append_user_turn(session, task)
    save_session(workspace, session)
    yield {"type": "custom_event", "event": session_turn_started_event(workspace, session, turn=turn, task=task)}
    session_context = build_session_context(workspace, session)

    route = "workflow"
    entry_state: dict[str, Any] = {
        "task": task or "",
        "messages": [],
        "session_id": session.get("session_id", ""),
        "session_turn": turn,
        "session_context": session_context,
    }
    for mode, event in build_entry_workflow().stream(entry_state, stream_mode=["updates", "custom"]):
        if mode == "custom":
            yield {"type": "custom_event", "event": event}
            if isinstance(event, dict) and event.get("type") == "intent_decision":
                route = str(event.get("route") or "workflow")
        else:
            _merge_graph_update(entry_state, event)
            yield {"type": "graph_event", "event": event}

    if route == "chat":
        response = str(entry_state.get("chat_response") or entry_state.get("final_answer") or "")
        append_assistant_turn(session, turn=turn, route="chat", content=response, summary=response)
        save_session(workspace, session)
        yield {"type": "custom_event", "event": session_turn_saved_event(workspace, session, turn=turn, route="chat")}
        return

    workflow_events = _stream_complex_workflow(
        task=task,
        workspace=workspace,
        max_attempts=max_attempts,
        approval_mode=approval_mode,
        approval_handler=approval_handler,
        checkpoint_mode=checkpoint_mode,
        resume_workspace=resume_workspace,
        trace_mode=trace_mode,
        command_executor=command_executor,
        allow_web_search=allow_web_search,
        session=session,
        turn=turn,
        session_context=session_context,
    )
    final_answer = ""
    for event in workflow_events:
        final_answer = _final_answer_from_event(event) or final_answer
        yield event

    append_assistant_turn(session, turn=turn, route="workflow", content=final_answer, summary=final_answer)
    save_session(workspace, session)
    yield {"type": "custom_event", "event": session_turn_saved_event(workspace, session, turn=turn, route="workflow")}


def stream_eval_workflow_events(
    workflow,
    *,
    task: str,
    workspace: Path,
    max_attempts: int,
    command_executor: CommandExecutor | None,
) -> Iterator[dict[str, Any]]:
    state = create_runtime(
        workspace,
        approval_mode="deny",
        checkpoint_mode="off",
        trace_mode="on",
        command_executor=command_executor,
        allow_web_search=False,
    )
    inputs = {
        "task": task or "",
        "runtime": state,
        "messages": [],
        "attempts": 0,
        "max_attempts": max_attempts,
    }
    yield {"type": "workspace", "path": str(state.workspace)}
    yield from _stream_traced_workflow(workflow, inputs, state)


def _stream_complex_workflow(
    *,
    task: str | None,
    workspace: Path,
    max_attempts: int,
    approval_mode: str,
    approval_handler,
    checkpoint_mode: str | None,
    resume_workspace: Path | None,
    trace_mode: str | None,
    command_executor: CommandExecutor | None = None,
    allow_web_search: bool = True,
    session: dict[str, Any] | None = None,
    turn: int | None = None,
    session_context: str = "",
) -> Iterator[dict[str, Any]]:
    resume_path = resume_workspace.expanduser() if resume_workspace is not None else None
    state = create_runtime(
        workspace,
        approval_mode=approval_mode,
        approval_handler=approval_handler,
        checkpoint_mode=checkpoint_mode,
        resume_from=resume_path,
        trace_mode=trace_mode,
        command_executor=command_executor,
        allow_web_search=allow_web_search,
    )
    workflow = build_complex_workflow()

    resumed = False
    resume_event: dict[str, Any] | None = None
    if resume_path is not None:
        inputs, resume_event = load_resume_inputs(state, task=task, max_attempts=max_attempts)
        resumed = True
        yield {"type": "custom_event", "event": resume_event}
    else:
        inputs = {
            "task": task or "",
            "runtime": state,
            "messages": [],
            "attempts": 0,
            "max_attempts": max_attempts,
        }

    if session is not None:
        inputs["session_id"] = session.get("session_id", "")
    if turn is not None:
        inputs["session_turn"] = turn
    if session_context:
        inputs["session_context"] = session_context
    metadata = dict(inputs.get("metadata", {}))
    if session is not None:
        metadata["session_id"] = session.get("session_id", "")
    if turn is not None:
        metadata["session_turn"] = turn
    if metadata:
        inputs["metadata"] = metadata

    yield from _stream_traced_workflow(workflow, inputs, state, resumed=resumed, resume_event=resume_event)


def _stream_traced_workflow(
    workflow,
    inputs: dict[str, Any],
    runtime: RuntimeState,
    *,
    resumed: bool = False,
    resume_event: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    current_state: dict[str, Any] = dict(inputs)
    manager = CheckpointManager(runtime, task=str(current_state.get("task", "")))
    trace = TraceRecorder(runtime, task=str(current_state.get("task", "")))
    trace.start(current_state, resumed=resumed, resume_event=resume_event)
    if resume_event is not None:
        trace.record_custom_event(resume_event)
    started_checkpoint = manager.save(current_state, status="started", latest_node="start")
    if started_checkpoint:
        trace.record_custom_event(started_checkpoint)
    latest_node = "start"

    try:
        for mode, event in workflow.stream(inputs, stream_mode=["updates", "custom"]):
            if mode == "custom":
                trace.record_custom_event(event)
                if _custom_event_needs_checkpoint(event):
                    saved = manager.save(current_state, status="running", latest_node=latest_node, event={"mode": mode, "payload": event})
                    if saved:
                        trace.record_custom_event(saved)
                yield {"type": "custom_event", "event": event}
            else:
                latest_node = _latest_graph_node(event) or latest_node
                _merge_graph_update(current_state, event)
                trace.record_graph_update(event)
                saved = manager.save(current_state, status="running", latest_node=latest_node, event={"mode": mode, "payload": event})
                if saved:
                    trace.record_custom_event(saved)
                yield {"type": "graph_event", "event": event}
    except KeyboardInterrupt:
        saved = manager.save(current_state, status="interrupted", latest_node=latest_node)
        if saved:
            trace.record_custom_event(saved)
            yield {"type": "custom_event", "event": saved}
        trace_event = trace.end(status="interrupted", latest_node=latest_node, final_state=current_state)
        if trace_event:
            yield {"type": "custom_event", "event": trace_event}
        return

    saved = manager.save(current_state, status="finished", latest_node=latest_node)
    if saved:
        trace.record_custom_event(saved)
        yield {"type": "custom_event", "event": saved}
    trace_event = trace.end(status="finished", latest_node=latest_node, final_state=current_state)
    if trace_event:
        yield {"type": "custom_event", "event": trace_event}


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_path(name: str) -> Path | None:
    raw = os.getenv(name, "").strip()
    return Path(raw).expanduser() if raw else None


def _latest_graph_node(event: Any) -> str | None:
    if isinstance(event, dict) and event:
        return str(next(reversed(event)))
    return None


def _merge_graph_update(state: dict[str, Any], event: Any) -> None:
    if not isinstance(event, dict):
        return
    for update in event.values():
        if not isinstance(update, dict):
            continue
        for key, value in update.items():
            if key == "messages":
                state["messages"] = list(add_messages(state.get("messages", []), value))
            else:
                state[key] = value


def _custom_event_needs_checkpoint(event: Any) -> bool:
    if not isinstance(event, dict):
        return False
    if event.get("type") != "tool_result":
        return False
    result = event.get("result")
    if not isinstance(result, dict):
        return False
    return result.get("ok") is False or bool(result.get("requires_approval"))


def _final_answer_from_event(event: dict[str, Any]) -> str:
    if event.get("type") != "graph_event":
        return ""
    payload = event.get("event")
    if not isinstance(payload, dict):
        return ""
    update = payload.get("final")
    if not isinstance(update, dict):
        return ""
    return str(update.get("final_answer") or "")
