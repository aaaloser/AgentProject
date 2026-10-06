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
from mokioclaw.core.task_closeout import TaskCloseout, CloseoutMode, CloseoutPurpose, TaskCloseoutError
from mokioclaw.core.task_observation import (
    TaskObservation, ObservationRecord, LedgerNumbers, normalize_usage,
)
from mokioclaw.core.trace import TraceRecorder, normalize_trace_mode
from mokioclaw.graph.workflow import build_complex_workflow, build_entry_workflow
from mokioclaw.dashboard.task_executor import TaskExecutionError
from mokioclaw.dashboard.task_context import (
    TaskToolServices, TaskContextError, RequestBinding, request_binding, measure_request,
    validate_groups, tool_message_size, baseline_messages, POLICY,
)
from mokioclaw.providers.openai_provider import (
    ProviderSettings, TaskProviderError, create_task_model, task_provider_failure_kind,
)


_TASK_MODEL_STAGES = (
    "entry", "chat", "planner", "code_agent", "verifier", "context_compressor",
)
_PROVIDER_ROOTS = frozenset({"provider_failed", "provider_auth_failed", "provider_rate_limited",
                           "provider_invalid_request", "provider_transport_failed", "provider_server_failed",
                           "usage_unavailable", "provider_budget_exhausted"})
_TERMINAL_ROOTS = _PROVIDER_ROOTS | {"task_tool_failed", "verification_command_failed", "task_closeout_incomplete"}


class _TaskModel:
    def __init__(self, underlying: Any, context: TaskRunContext, stage: str,
                 purpose: CloseoutPurpose | None = None) -> None:
        self._underlying = underlying
        self._context = context
        self._stage = stage
        self._purpose = purpose
        self._binding: RequestBinding | None = None
        self._delegation: tuple | None = None

    def bind_tools(self, tools: Any, **kwargs: Any) -> _TaskModel:
        try:
            bound = self._underlying.bind_tools(tools, **kwargs)
        except Exception:
            self._context.record_terminal_root("provider_failed")
            raise TaskProviderError("provider_setup_failed") from None
        result = _TaskModel(bound, self._context, self._stage, self._purpose)
        if self._stage == "code_agent" and self._context.task_filesystem is not None:
            result._binding = request_binding(tools, **kwargs)
            session = self._context.task_services.session if self._context.task_services is not None else None
            if session is None:
                raise TaskContextError("invalid_message_group")
            result._delegation = session.identity
        return result

    def for_purpose(self, purpose: CloseoutPurpose) -> _TaskModel:
        result = _TaskModel(self._underlying, self._context, self._stage, purpose)
        result._binding = self._binding
        result._delegation = self._delegation
        return result

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        context = self._context
        if context.observation is None:
            return self._invoke(messages, **kwargs)
        with context._lock:
            initial_calls = context.provider_calls
            self._gate = "known_failure"
            try:
                return self._invoke(messages, **kwargs)
            except Exception:
                if context.provider_calls == initial_calls:
                    context._observe("invoke_refused", stage=self._stage,
                                     purpose=self._purpose, status="refused", gate=self._gate,
                                     before=context._ledger(), after=context._ledger())
                raise

    def _invoke(self, messages: Any, **kwargs: Any) -> Any:
        context = self._context
        with context._lock:
            context.check_known_failure()
            self._gate = ("usage" if context.usage_unavailable else
                          "total_calls" if context.provider_calls >= context.max_provider_calls else "total_tokens")
            context.preflight_provider_budget()
            self._gate = "context"
            if self._stage == "code_agent" and context.task_filesystem is not None:
                session = context.task_services.session if context.task_services is not None else None
                if (session is None or session.closed or session.identity != self._delegation
                        or self._binding is None or self._binding != session.binding):
                    raise TaskContextError("invalid_message_group")
                if list(messages[:len(session.anchors)]) != list(session.anchors):
                    raise TaskContextError("invalid_message_group")
                if measure_request(baseline_messages(session.anchors, session._state([])), self._binding,
                                   invocation_options=kwargs) >= POLICY.target:
                    raise TaskContextError("input_too_large")
                index = len(session.anchors)
                if (len(messages) <= index or getattr(messages[index], "name", None) != "task_context_index"):
                    raise TaskContextError("invalid_message_group")
                groups = validate_groups(list(messages[index + 1:]))
                if any(any(tool_message_size(t) > POLICY.tool_json for t in g.tools)
                       or sum(tool_message_size(t) for t in g.tools) > POLICY.group_json for g in groups):
                    raise TaskContextError("input_too_large")
                if measure_request(list(messages), self._binding, invocation_options=kwargs) > POLICY.hard:
                    raise TaskContextError("input_too_large")
            allowed = {
                "code_agent": {CloseoutPurpose.REPAIR, CloseoutPurpose.HANDOFF},
                "planner": {CloseoutPurpose.PLANNER}, "verifier": {CloseoutPurpose.VERIFIER},
                "context_compressor": {CloseoutPurpose.PRE_COMPRESS, CloseoutPurpose.POST_COMPRESS},
            }
            if self._purpose is not None and self._purpose not in allowed.get(self._stage, set()):
                raise ValueError("task_model_purpose_invalid")
            if context.closeout.mode != CloseoutMode.INACTIVE:
                self._gate = "phase"
                if self._purpose is None:
                    if context.closeout.mode != CloseoutMode.REPAIR or self._stage != "planner":
                        raise TaskCloseoutError("phase_limit")
                else:
                    context.closeout.claim_invoke(self._purpose)
            before = context._ledger() if context.observation is not None else None
            context.provider_calls += 1
            context._stage_calls[self._stage] += 1
            call_no = context.provider_calls
            context._observe("invoke_started", stage=self._stage, purpose=self._purpose,
                             call_no=call_no, status="started",
                             before=before, after=context._ledger() if before is not None else None)
            try:
                response = self._underlying.invoke(messages, **kwargs)
            except Exception as exc:
                kind = task_provider_failure_kind(exc)
                context.record_terminal_root(kind if kind in _PROVIDER_ROOTS else "provider_failed")
                context._observe("invoke_failed", stage=self._stage, purpose=self._purpose,
                                 call_no=call_no, status="provider_failed",
                                 before=before, after=context._ledger() if before is not None else None)
                raise TaskProviderError(kind) from None
            usage = getattr(response, "usage_metadata", None)
            total = usage.get("total_tokens") if isinstance(usage, dict) else None
            if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                context._usage_unavailable = True
            else:
                context.reported_tokens += total
                context._stage_tokens[self._stage] += total
                context.closeout.record_usage(self._purpose, total)
            numbers = normalize_usage(usage) if context.observation is not None else None
            if numbers is not None:
                context._observe("invoke_finished", stage=self._stage, purpose=self._purpose,
                                 call_no=call_no,
                                 status="usage_unavailable" if numbers.total_tokens is None else "valid_usage",
                                 total_tokens=numbers.total_tokens, input_tokens=numbers.input_tokens,
                                 output_tokens=numbers.output_tokens, split_status=numbers.split_status,
                                 before=before, after=context._ledger())
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
        observation: TaskObservation | None = None,
    ) -> None:
        if (not 1 <= max_provider_calls <= 24 or not 1 <= max_total_tokens <= 300_000
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
        self.task_services: TaskToolServices | None = None
        self.current_attempt = 1
        self.fixed_verification_commands: tuple[str, ...] = ()
        self._terminal_root: str | None = None
        self.observation = observation
        self.closeout = TaskCloseout(max_output_tokens_per_call,
                                    observer=self._observe_closeout if observation is not None else None)

    def _ledger(self) -> LedgerNumbers:
        return LedgerNumbers(self.provider_calls, self.reported_tokens,
                             max(0, self.max_provider_calls - self.provider_calls),
                             self.max_total_tokens - self.reported_tokens)

    def _observe(self, kind, *, purpose=None, **values) -> None:
        if self.observation is None:
            return
        try:
            self.observation.emit(ObservationRecord(
                task_id=self.observation.task_id, attempt_id=self.current_attempt,
                kind=kind, purpose=purpose.value if isinstance(purpose, CloseoutPurpose) else purpose,
                **values,
            ))
        except Exception:
            self.observation.invalidate()

    def _observe_closeout(self, notice) -> None:
        with self._lock:
            snapshot = notice.snapshot
            self._observe(notice.kind, purpose=notice.purpose, call_no=notice.call_no,
                          gate=notice.gate, reasons=notice.reasons,
                          before=self._ledger(), after=self._ledger(),
                          policy={"mode": snapshot.mode, "E_repair": snapshot.E_repair,
                                  "R_calls": snapshot.R_calls, "R_tokens": snapshot.R_tokens,
                                  "iterations_left": snapshot.iterations_left, "slots": dict(snapshot.slots)})

    def check_known_failure(self) -> None:
        with self._lock:
            if self._terminal_root in _PROVIDER_ROOTS:
                raise TaskProviderError(self._terminal_root)
            if self._terminal_root in {"task_tool_failed", "verification_command_failed"}:
                raise TaskExecutionError(self._terminal_root)
            if self._terminal_root == "task_closeout_incomplete":
                raise TaskCloseoutError("phase_limit")
            if self._usage_unavailable:
                self.record_terminal_root("usage_unavailable")
                raise TaskProviderError("usage_unavailable")

    def resolve_closeout_failure(self, error: TaskCloseoutError) -> str:
        if not isinstance(error, TaskCloseoutError):
            raise ValueError("task_closeout_failure_invalid")
        with self._lock:
            if self._terminal_root is not None:
                return self._terminal_root
            if self._usage_unavailable:
                return "usage_unavailable"
            if self.provider_calls >= self.max_provider_calls or self.reported_tokens >= self.max_total_tokens:
                return "provider_budget_exhausted"
            return "task_closeout_incomplete"

    def record_terminal_root(self, kind: str) -> None:
        if kind not in _TERMINAL_ROOTS:
            raise ValueError("task_terminal_root_invalid")
        with self._lock:
            if self._terminal_root is None:
                self._terminal_root = kind

    def resolve_context_failure(self, error: TaskContextError) -> str:
        if not isinstance(error, TaskContextError):
            raise ValueError("task_context_failure_invalid")
        with self._lock:
            if self._terminal_root is not None:
                return self._terminal_root
            if self._usage_unavailable:
                return "usage_unavailable"
            if self.provider_calls >= self.max_provider_calls or self.reported_tokens >= self.max_total_tokens:
                return "provider_budget_exhausted"
            return "task_context_error"

    def preflight_provider_budget(self) -> None:
        with self._lock:
            if self._usage_unavailable:
                self.record_terminal_root("usage_unavailable")
                raise TaskProviderError("usage_unavailable")
            if (self.provider_calls >= self.max_provider_calls or self.reported_tokens >= self.max_total_tokens):
                self.record_terminal_root("provider_budget_exhausted")
                raise TaskProviderError("provider_budget_exhausted")

    def attach_tools(
        self, filesystem: Any, tools: list[Any], *, services: TaskToolServices, gateway: Any | None = None,
        verification_commands: tuple[str, ...] = (),
    ) -> None:
        if self.task_filesystem is not None or not tools:
            raise ValueError("task_tools_already_configured")
        if services.filesystem is not filesystem:
            raise TaskContextError("invalid_message_group")
        if any(not isinstance(command, str) or not command.strip() for command in verification_commands):
            raise ValueError("task_verification_invalid")
        self.task_filesystem = filesystem
        self.task_services = services
        services.terminal_recorder = self.record_terminal_root
        self.task_tools = list(tools)
        self.task_gateway = gateway
        self.fixed_verification_commands = tuple(verification_commands)

    def begin_attempt(self, attempt_id: int) -> None:
        with self._lock:
            if attempt_id == self.current_attempt:
                self.closeout.begin_attempt(attempt_id)
                return
            if attempt_id != self.current_attempt + 1 or self.task_gateway is None:
                raise TaskExecutionError("task_attempt_invalid")
            if self.closeout.mode == CloseoutMode.INACTIVE:
                self.closeout.begin_attempt(self.current_attempt)
            try:
                self.task_gateway.set_attempt(attempt_id)
            except Exception:
                raise TaskExecutionError("task_attempt_invalid") from None
            self.current_attempt = attempt_id
            self.closeout.begin_attempt(attempt_id)
            if self.task_services is not None:
                self.task_services.close_delegation()

    @classmethod
    def from_settings(
        cls,
        settings: ProviderSettings,
        *,
        max_provider_calls: int,
        max_total_tokens: int,
        max_output_tokens_per_call: int,
        observation: TaskObservation | None = None,
    ) -> TaskRunContext:
        return cls(
            lambda: create_task_model(settings, max_output_tokens=max_output_tokens_per_call),
            max_provider_calls=max_provider_calls,
            max_total_tokens=max_total_tokens,
            max_output_tokens_per_call=max_output_tokens_per_call,
            observation=observation,
        )

    @classmethod
    def for_fake_model(
        cls,
        model: Any,
        *,
        max_provider_calls: int,
        max_total_tokens: int,
        max_output_tokens_per_call: int,
        observation: TaskObservation | None = None,
    ) -> TaskRunContext:
        return cls(
            lambda: model,
            max_provider_calls=max_provider_calls,
            max_total_tokens=max_total_tokens,
            max_output_tokens_per_call=max_output_tokens_per_call,
            observation=observation,
        )

    def model(self, *, stage: str, purpose: CloseoutPurpose | None = None) -> _TaskModel:
        if stage not in _TASK_MODEL_STAGES:
            raise ValueError("task_model_stage_invalid")
        with self._lock:
            if self._model is None:
                try:
                    self._model = self._model_factory()
                except TaskProviderError:
                    self.record_terminal_root("provider_failed")
                    raise
                except Exception:
                    self.record_terminal_root("provider_failed")
                    raise TaskProviderError("provider_setup_failed") from None
            return _TaskModel(self._model, self, stage, purpose)

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
