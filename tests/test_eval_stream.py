from pathlib import Path

from langgraph.graph import END, START, StateGraph

from mokioclaw.core.agent import stream_eval_workflow_events


class _State(dict):
    pass


def _noop_node(state):
    return {"task": state.get("task", "")}


def _build_trivial_graph():
    graph = StateGraph(dict)
    graph.add_node("noop", _noop_node)
    graph.add_edge(START, "noop")
    graph.add_edge("noop", END)
    return graph.compile()


def test_stream_eval_workflow_events_yields_expected_shapes(tmp_path: Path) -> None:
    events = list(
        stream_eval_workflow_events(
            _build_trivial_graph(),
            task="demo task",
            workspace=tmp_path / "ws",
            max_attempts=3,
            command_executor=None,
        )
    )

    assert events[0] == {"type": "workspace", "path": str(tmp_path / "ws")}
    types = [event["type"] for event in events]
    assert "graph_event" in types
    trace_dirs = [Path(event["event"]["trace_dir"]) for event in events if event["type"] == "custom_event" and "trace_dir" in event.get("event", {})]
    assert trace_dirs and trace_dirs[0].exists()
