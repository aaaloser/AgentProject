"""Synthetic closeout inputs; no provider/network/command fallback."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace

from langchain_core.messages import AIMessage
from task_context_fakes import offline_context_guard


@dataclass
class OfflineAudit:
    hits: list[str] = field(default_factory=list)


@contextmanager
def offline_closeout_guard(monkeypatch):
    audit = OfflineAudit()
    with offline_context_guard(monkeypatch, on_forbidden=lambda: audit.hits.append("forbidden")):
        try:
            yield audit
        finally:
            assert not audit.hits, "offline_boundary_touched"


class ScriptedCloseoutModel:
    """Bindings are independent; only script position/numeric observations shared."""

    def __init__(self, script, *, shared=None, tools=(), options=None):
        self.shared = shared if shared is not None else SimpleNamespace(
            script=list(script), calls=0, observations=[])
        self.tools = tuple(tools)
        self.options = dict(options or {})

    def bind_tools(self, tools, **kwargs):
        return ScriptedCloseoutModel([], shared=self.shared, tools=tools, options=kwargs)

    @property
    def calls(self):
        return self.shared.calls

    def invoke(self, messages, **kwargs):
        item = self.shared.script[self.shared.calls]
        self.shared.calls += 1
        self.shared.observations.append(tuple(t.name for t in self.tools))
        if "check" in item:
            item["check"](messages, self)
        if "error" in item:
            raise item["error"]
        response = AIMessage(content=item.get("content", ""), tool_calls=item.get("tool_calls", []))
        # Preserve missing/bool/negative usage exactly for wrapper validation.
        response.usage_metadata = item.get("usage", {
            "input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
        return response


class FakeCloseoutExecutor:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def execute(self, request):
        item = self.script[self.calls]
        self.calls += 1
        return dict(
            ok=item.get("exit_code", 0) == 0, exit_code=item.get("exit_code", 0), duration_ms=1,
            stdout=item.get("stdout", ""), stderr=item.get("stderr", ""),
            output_truncated=item.get("output_truncated", False))
