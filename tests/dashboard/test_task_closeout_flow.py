import pytest

from task_closeout_fakes import offline_closeout_guard
from test_task_closeout_agents import state_with_script
from mokioclaw.core.task_closeout import CloseoutPurpose, TaskCloseoutError
from mokioclaw.graph import nodes


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_closeout_guard(monkeypatch):
        yield


def test_both_monitors_consume_distinct_reserved_slots(tmp_path):
    state, context, model, _, _ = state_with_script(tmp_path, [{"content": "{}"}, {"content": "{}"}])
    context.begin_attempt(1)
    context.closeout.enter_closing()
    state["context_next_node"] = "verifier"
    # Force the original estimator over400000 with synthetic task text, not changed threshold.
    state["task"] = "x" * 1600100
    context.closeout.note_node_return("planner")
    monitored = nodes.context_monitor_node(state)
    assert monitored["context_should_compress"]
    nodes.context_compressor_node({**state, **monitored})
    context.closeout.note_node_return("verifier")
    state["context_next_node"] = "final"
    monitored = nodes.context_monitor_node(state)
    nodes.context_compressor_node({**state, **monitored})
    assert model.calls == 2 and context.usage_snapshot()["context_compressor_calls"] == 2
    assert context.closeout.remaining_calls == 5
    with pytest.raises(TaskCloseoutError):
        context.model(stage="context_compressor", purpose=CloseoutPurpose.PRE_COMPRESS).invoke([])


def test_monitor_releases_only_actual_branch(tmp_path):
    state, context, _, _, _ = state_with_script(tmp_path, [])
    context.begin_attempt(1)
    context.closeout.enter_closing()
    assert context.closeout.remaining_calls == 7
    context.closeout.note_node_return("planner")
    assert not nodes.context_monitor_node(state)["context_should_compress"]
    assert context.closeout.remaining_calls == 6
    assert not nodes.context_monitor_node(state)["context_should_compress"]
    assert context.closeout.remaining_calls == 6
    context.closeout.note_node_return("verifier")
    nodes.context_monitor_node(state)
    assert context.closeout.remaining_calls == 5


def test_retry_8_calls_keeps_previous_attempt(tmp_path):
    state, context, _, _, _ = state_with_script(tmp_path, [])
    context.begin_attempt(1)
    context.provider_calls = 16
    calls = []
    context.task_gateway = type("Gateway", (), {"set_attempt": lambda self, n: calls.append(n)})()
    with pytest.raises(TaskCloseoutError):
        nodes.planner_node({**state, "attempts": 1, "verifier_explicit_failure": True, "max_attempts": 3})
    assert context.current_attempt == 1 and calls == [] and context.provider_calls == 16


def test_retry_9_calls_starts_without_resetting_usage(tmp_path):
    state, context, model, _, work = state_with_script(tmp_path, [{"content": "no repair performed"}])
    context.begin_attempt(1)
    context.provider_calls = 15
    context.closeout.claim_invoke(CloseoutPurpose.REPAIR)
    context.closeout.record_usage(CloseoutPurpose.REPAIR, 0)
    context.reported_tokens = 10
    calls = []
    context.task_gateway = type("Gateway", (), {"set_attempt": lambda self, n: calls.append(n)})()
    nodes.planner_node({**state, "attempts": 1, "verifier_explicit_failure": True, "max_attempts": 3})
    assert calls == [2] and context.current_attempt == 2
    assert model.calls == 1 and context.provider_calls == 16 and context.reported_tokens == 12
    assert context.closeout.estimate(CloseoutPurpose.REPAIR) == 3840
    assert (work / "src/a.py").read_bytes() == b"original\n"


@pytest.mark.parametrize("closeout_calls", [3, 5, 7])
def test_real_graph_repairs_selftests_then_reserved_closeout(tmp_path, monkeypatch, closeout_calls):
    import json
    from langchain_core.messages import AIMessage, ToolMessage
    from test_task_context_flow import GraphScript, graph_fixture
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    context, _, services, work, decisions, receipts = graph_fixture(tmp_path)
    baseline_text = (work / "src/a.py").read_bytes() + b"\n"
    (work / "src/a.py").write_bytes(baseline_text)
    claims = []
    original_claim = context.closeout.claim_invoke
    def observe_claim(purpose):
        original_claim(purpose)
        claims.append(purpose)
    monkeypatch.setattr(context.closeout, "claim_invoke", observe_claim)

    class GraphModel(GraphScript):
        def __init__(self):
            super().__init__()
            self.planner_close_calls = 0
            self.verifier_read = False
            self.compress_calls = 0
            self.names = []

        def bind_tools(self, tools, **kwargs):
            root = self
            names = tuple(t.name for t in tools)
            class Binding:
                def invoke(self, messages, **options):
                    return root.respond(messages, names)
            return Binding()

        def invoke(self, messages, **options):
            return self.respond(messages, ())

        def respond(self, messages, names):
            from mokioclaw.prompts.stage4 import CONTEXT_COMPRESSION_PROMPT
            system = messages[0].content
            self.names.append(names)
            if "planner/supervisor" in system and any(isinstance(m, ToolMessage) for m in messages):
                self.calls += 1
                self.planner_close_calls += 1
                # The earlier response that delegated CodeAgent is adopted as
                # the first planner slot. This is already the final reply.
                if closeout_calls >= 5:
                    assert names == ()
                content = "planner closed" + ("x" * 1600100 if closeout_calls == 7 else "")
            elif system == CONTEXT_COMPRESSION_PROMPT:
                self.calls += 1
                self.compress_calls += 1
                content = '{"summary":"synthetic compressed state"}'
            elif "You are verifier" in system and closeout_calls >= 5 and not self.verifier_read:
                self.calls += 1
                self.verifier_read = True
                return AIMessage(content="", tool_calls=[{"id": "formal-read", "name": "FileReadTool",
                    "args": {"file_path": "src/a.py"}}],
                    usage_metadata={"total_tokens": 2, "input_tokens": 1, "output_tokens": 1})
            else:
                response = super().invoke(messages)
                if closeout_calls >= 5 and "codeAgent" in system and response.tool_calls:
                    last = messages[-1] if isinstance(messages[-1], ToolMessage) else None
                    if last is not None and last.name == "FileEditTool":
                        # This response requests the final self-test; force closeout
                        # immediately after its complete tool group, using numeric usage.
                        response.usage_metadata = {"total_tokens": 20000, "input_tokens": 19999, "output_tokens": 1}
                if "You are verifier" in system and closeout_calls == 7:
                    response.content = json.dumps({"passed": True, "reason": "synthetic", "padding": "x" * 1600100})
                return response
            return AIMessage(content=content, usage_metadata={"total_tokens": 2, "input_tokens": 1, "output_tokens": 1})

    model = GraphModel()
    context._model_factory = lambda: model
    events = []
    run_projected_workflow("synthetic task", work, context, events.append, max_attempts=1)
    assert (work / "src/a.py").read_bytes() == b"good\n"
    assert [r.exit_code for r in receipts] == [1, 0, 0]
    assert len({d[0] for d in decisions}) == len({d[1] for d in decisions}) == 3
    assert context.provider_calls == model.calls == {3: 12, 5: 13, 7: 15}[closeout_calls]
    closing_claims = [p for p in claims if p != CloseoutPurpose.REPAIR]
    if closeout_calls >= 5:
        # Five/seven slots include the once-adopted planner response, which
        # actually started before its nested repair, not another model call.
        assert len(closing_claims) == closeout_calls
        assert closing_claims.count(CloseoutPurpose.PLANNER) == 2
        assert closing_claims.count(CloseoutPurpose.HANDOFF) == 1
    else:
        assert closing_claims == [CloseoutPurpose.VERIFIER]
    assert model.compress_calls == (2 if closeout_calls == 7 else 0)
    assert len(context.usage_snapshot()) == 12
    assert context.closeout.remaining_calls == 0 and services.session is None
    assert events[-1]["phase"] == "complete"
    result = projected_result(tmp_path / "result", events, decisions, receipts,
                              baseline_text, (work / "src/a.py").read_bytes())
    assert result.status == "completed" and result.verification_status == "passed"
    assert result.changed_files == ("src/a.py",)
    assert result.verification_results[0].command_request_id == receipts[-1].command_request_id
    assert all(s not in repr(result) for s in ("SOURCE_SENTINEL", "PROVIDER_SENTINEL", "COMMAND_SENTINEL"))


def projected_result(path, events, decisions, receipts, before, after, *, failure=None, attempt=1):
    """The existing result builder consumes actual graph projections/receipts."""
    from dataclasses import replace
    from test_task_result import _event, _prepared, _record, _spec
    from mokioclaw.dashboard.task_result import build_task_result
    prepared = _prepared(path)
    (prepared.baseline / "src/a.py").write_bytes(before)
    (prepared.work / "src/a.py").write_bytes(after)
    public = []
    for request_id, digest, _ in decisions:
        public.extend([
            _event(len(public) + 1, "approval_request", {"status": "waiting", "request_id": request_id,
                                                       "execution_digest": digest}),
            _event(len(public) + 2, "approval_decision", {"decision": "approved", "request_id": request_id}),
        ])
    public.extend(_event(len(public) + n + 1, e["kind"], {k: v for k, v in e.items()
                  if k not in {"kind", "attempt_id"}}, e["attempt_id"]) for n, e in enumerate(events))
    record = _record("failed" if failure else "completed", tuple(public), failure=failure,
                     receipts=tuple(receipts), attempt=attempt)
    return build_task_result(record, replace(_spec(), max_provider_calls=24, max_total_tokens=150000,
                                            max_output_tokens_per_call=3072), prepared)


@pytest.mark.parametrize("stage", ["handoff", "planner", "verifier", "pre", "post"])
@pytest.mark.parametrize("fault", ["usage", "hard"])
def test_real_graph_closeout_failure_preserves_formal_evidence(tmp_path, stage, fault):
    from langchain_core.messages import AIMessage, ToolMessage
    from test_task_context_flow import GraphScript, graph_fixture
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    from mokioclaw.providers.openai_provider import TaskProviderError
    from mokioclaw.prompts.stage4 import CONTEXT_COMPRESSION_PROMPT
    context, _, services, work, decisions, receipts = graph_fixture(tmp_path)
    before = (work / "src/a.py").read_bytes() + b"\n"
    (work / "src/a.py").write_bytes(before)
    class Model(GraphScript):
        def __init__(self):
            super().__init__()
            self.compress_calls = 0
            self.stopped_call = None
        def invoke(self, messages, **options):
            system = messages[0].content
            if system == CONTEXT_COMPRESSION_PROMPT:
                self.calls += 1
                self.compress_calls += 1
                current = "pre" if self.compress_calls == 1 else "post"
                response = AIMessage(content='{"summary":"synthetic"}',
                                     usage_metadata={"total_tokens": 2, "input_tokens": 1, "output_tokens": 1})
            else:
                response = super().invoke(messages)
                current = None
                if "codeAgent" in system:
                    if not response.tool_calls:
                        current = "handoff"
                    elif isinstance(messages[-1], ToolMessage) and messages[-1].name == "FileEditTool":
                        current = "final_selftest"
                        response.usage_metadata = {"total_tokens": 20000, "input_tokens": 19999, "output_tokens": 1}
                elif "planner/supervisor" in system and not response.tool_calls:
                    current = "planner"
                    if stage in {"pre", "post"}:
                        response.content += "x" * 1600100
                elif "You are verifier" in system:
                    current = "verifier"
                    response.content = '{"passed":true,"padding":"' + "x" * 1600100 + '"}'
            # Hard gates apply before the requested next invoke. A response
            # overshoot is not retroactively charged as another model call.
            target = stage if fault == "usage" else {
                "handoff": "final_selftest", "planner": "handoff", "verifier": "planner",
                "pre": "planner", "post": "verifier"}[stage]
            if current == target:
                self.stopped_call = self.calls
                response.usage_metadata = None if fault == "usage" else {
                    "total_tokens": 150000, "input_tokens": 150000, "output_tokens": 0}
            return response
    model = Model()
    context._model_factory = lambda: model
    events = []
    failure = "usage_unavailable" if fault == "usage" else "provider_budget_exhausted"
    with pytest.raises(TaskProviderError, match=f"^{failure}$"):
        run_projected_workflow("synthetic", work, context, events.append, max_attempts=1)
    assert model.calls == model.stopped_call == context.provider_calls
    assert services.session is None
    assert [e["kind"] for e in events].count("budget_usage") == 1
    assert not any(e.get("phase") == "complete" for e in events)
    result = projected_result(tmp_path / "result", events, decisions, receipts, before,
                              (work / "src/a.py").read_bytes(), failure=failure)
    assert result.status == "failed" and result.failure_kind == failure
    formal_ran = stage in {"verifier", "post"}
    assert len(receipts) == (3 if formal_ran else 2)
    assert result.verification_status == ("passed" if formal_ran else "not_run")
    if formal_ran:
        assert result.verification_results[0].command_request_id == receipts[-1].command_request_id
    assert all(s not in repr(result) for s in ("SOURCE_SENTINEL", "PROVIDER_SENTINEL", "COMMAND_SENTINEL"))


def test_projection_failure_marks_local_workflow_failed(tmp_path):
    from mokioclaw.dashboard.task_worker import run_projected_workflow
    from mokioclaw.core.task_closeout import CloseoutMode
    _, context, _, _, _ = state_with_script(tmp_path, [])
    def stream(*args, **kwargs):
        yield {"type": "custom_event", "event": {"type": "workflow_complete"}}
    def emit(event):
        raise RuntimeError("synthetic projection failure")
    with pytest.raises(RuntimeError):
        run_projected_workflow("synthetic", tmp_path, context, emit, stream=stream)
    assert context.closeout.mode == CloseoutMode.FAILED


def test_retry_started_then_no_formal_checks_keeps_old_receipt(tmp_path, monkeypatch):
    from task_closeout_fakes import ScriptedCloseoutModel
    from test_task_closeout_agents import delegation
    from test_task_closeout_verifier import verifier_fixture
    from mokioclaw.dashboard.task_events import summarize_agent_event
    script = [
        {"content": '{"passed":false,"reason":"synthetic negative verdict"}'},
        {"tool_calls": [{"id": "retry-plan", "name": "TodoWriteTool", "args": {
            "todos": ["repair still needed"], "acceptance_criteria": ["repair verified"]}}]},
        {"tool_calls": [delegation("retry-delegate")]},
    ]
    state, context, _, decisions, receipts = verifier_fixture(tmp_path, script)
    # Install before first model creation; all three stages share immutable bindings.
    model = ScriptedCloseoutModel(script)
    context._model_factory = lambda: model
    raw = []
    monkeypatch.setattr(nodes, "_get_writer", lambda: raw.append)
    returned = nodes.verifier_node(state)
    assert returned["verifier_explicit_failure"] is True and len(receipts) == 1
    events = []
    for item in raw:
        events.extend({"attempt_id": 1, **summary} for summary in summarize_agent_event(
            {"type": "custom_event", "event": item}, context.fixed_verification_commands))
    # Seed a trusted numeric remaining-call boundary, without any real invocation.
    context.provider_calls = 15
    with pytest.raises(TaskCloseoutError, match="^task_closeout_incomplete$"):
        nodes.planner_node({**state, **returned, "max_attempts": 2})
    assert context.current_attempt == 2 and context.provider_calls == 17 and model.calls == 3
    assert context.task_gateway.attempt_id == 2 and len(receipts) == 1
    result = projected_result(tmp_path / "result", events, decisions, receipts, b"original\n", b"good\n",
                              failure="task_closeout_incomplete", attempt=2)
    assert result.verification_status == "not_run" and result.failure_kind == "task_closeout_incomplete"
    prior = [r for r in result.verification_results if r.attempt_id == 1]
    assert len(prior) == 1 and prior[0].status == "passed"
    assert prior[0].command_request_id == receipts[0].command_request_id
