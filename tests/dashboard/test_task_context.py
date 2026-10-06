import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from task_context_fakes import offline_context_guard


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_context_guard(monkeypatch):
        yield


def api():
    from mokioclaw.dashboard import task_context
    return task_context


def group(index, *, failure=False, content="small", revision="r", path="a.py"):
    call_id = f"read-{index}"
    ai = AIMessage(content="", tool_calls=[{
        "name": "FileReadTool", "args": {"file_path": path, "limit": 100}, "id": call_id,
    }])
    result = {"ok": not failure, "path": path, "revision": revision,
              "start": 0, "end": 100, "content": content}
    if failure:
        result["error"] = "task_edit_match_failed"
    return [ai, ToolMessage(content=json.dumps(result), tool_call_id=call_id, name="FileReadTool")]


def test_meter_counts_schemas_options_ids_and_args():
    ctx = api()
    binding = ctx.RequestBinding(({"type": "function", "function": {"name": "test", "parameters": {}}},),
                                 {"tool_choice": "auto"})
    messages = [SystemMessage(content="规约😀\n"), HumanMessage(content="task")] + group(1)
    raw = ctx.canonical_request_bytes(messages, binding, invocation_options={"stop": ["end"]})
    data = json.loads(raw)
    assert data["schemas"] == list(binding.schemas)
    assert data["binding_options"] == binding.options
    assert data["invocation_options"] == {"stop": ["end"]}
    assert data["messages"][2]["tool_calls"][0]["args"] == {"file_path": "a.py", "limit": 100}
    assert data["messages"][3]["tool_call_id"] == "read-1"
    assert raw == json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                            allow_nan=False).encode("utf-8")
    assert ctx.measure_request(messages, binding, invocation_options={"stop": ["end"]}) == len(raw) + 4096
    changed = messages[0].model_copy(update={"usage_metadata": {"total_tokens": 100}})
    assert ctx.measure_request([changed, *messages[1:]], binding) == ctx.measure_request(messages, binding)


def test_baseline_requires_real_anchors_and_tools():
    ctx = api()
    anchors = (SystemMessage(content="system"), HumanMessage(content="task/planner/acceptance/fixed commands"))
    binding = ctx.RequestBinding(({"name": "FileReadTool"},), {"tool_choice": "auto"})
    capsule = {"task_id": "fixture", "attempt_id": 1, "todos": [], "history_compacted": False}
    base = ctx.measure_baseline(anchors, capsule, binding)
    assert base == ctx.measure_request(ctx.prepare_request(anchors, [], capsule, binding), binding)
    assert base > ctx.measure_baseline(anchors, capsule, ctx.RequestBinding((), {}))
    ctx.assert_baseline_feasible(base, 100, 14000, 2000)
    for values in ((49152, 0, 0, 0), (49000, 24728, 0, 0), (49000, 1, 49304, 0)):
        with pytest.raises(ctx.TaskContextError, match="^task_context_error$"):
            ctx.assert_baseline_feasible(*values)


def test_threshold_boundaries():
    ctx = api()
    binding = ctx.RequestBinding((), {})
    anchors = (SystemMessage(content="s"), HumanMessage(content="t"))
    empty = ctx.prepare_request(anchors, [], {}, binding)
    overhead = ctx.measure_request(empty, binding)
    exact = (anchors[0], HumanMessage(content="t" + "x" * (98304 - overhead)))
    assert ctx.measure_request(ctx.prepare_request(exact, [], {}, binding), binding) == 98304
    with pytest.raises(ctx.TaskContextError):
        ctx.prepare_request((exact[0], HumanMessage(content=exact[1].content + "x")), [], {}, binding)
    history = sum((group(i, content="x" * 25000, path=f"{i}.py") for i in range(3)), [])
    output = ctx.prepare_request(anchors, history, {}, binding)
    assert [g.ai.tool_calls[0]["id"] for g in ctx.validate_groups(output[3:])] == ["read-1", "read-2"]


@pytest.mark.parametrize("case", ["orphan", "duplicate", "partial", "wrong_order", "missing_id"])
def test_groups_reject_orphan_duplicate_or_partial(case):
    ctx = api()
    valid = group(1)
    if case == "orphan":
        history = valid[1:]
    elif case == "duplicate":
        history = valid * 2
    elif case == "partial":
        history = valid[:1]
    elif case == "missing_id":
        history = [AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": None}])]
    else:
        history = [AIMessage(content="", tool_calls=[{"name": "a", "args": {}, "id": "a"},
                                                    {"name": "b", "args": {}, "id": "b"}]),
                   ToolMessage(content="{}", tool_call_id="b"), ToolMessage(content="{}", tool_call_id="a")]
    with pytest.raises(ctx.TaskContextError):
        ctx.validate_groups(history)


def test_prepare_is_idempotent():
    ctx = api()
    anchors = (SystemMessage(content="system"), HumanMessage(content="requirements"))
    binding = ctx.RequestBinding((), {})
    history = sum((group(i) for i in range(5)), [])
    one = ctx.prepare_request(anchors, history, {"todos": []}, binding)
    two = ctx.prepare_request(anchors, one, {"todos": []}, binding)
    assert one == two
    assert one[0] is anchors[0] and one[1] is anchors[1]


def test_repeat_reads_keep_latest_two_and_required_failure():
    ctx = api()
    history = group(0, failure=True) + sum((group(i) for i in range(1, 17)), [])
    output = ctx.prepare_request((SystemMessage(content="s"), HumanMessage(content="t")), history,
                                 {}, ctx.RequestBinding((), {}))
    groups = ctx.validate_groups(output[3:])
    assert [g.ai.tool_calls[0]["id"] for g in groups] == ["read-0", "read-15", "read-16"]
    assert groups[-1].ai is history[-2]
    assert groups[0].recoverable_failure
    assert "content" not in json.loads(output[2].content)


@pytest.mark.parametrize("content", [[{"type": "image_url", "image_url": "private"}], float("nan")])
def test_unsupported_content_is_fixed_and_private(content):
    ctx = api()
    value = HumanMessage(content=content) if isinstance(content, list) else {"role": "user", "content": "x", "extra": content}
    with pytest.raises(ctx.TaskContextError, match="^task_context_error$"):
        ctx.measure_request([value], ctx.RequestBinding((), {}))
