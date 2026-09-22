from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mokioclaw.evals.provider_failures import FailureKind, classify_failure
from mokioclaw.providers.call_journal import CallJournal, atomic_json_replace


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_atomic_json_replace_uses_unique_same_directory_temporary_files(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "state.json"
    sources: list[Path] = []
    from mokioclaw.providers import call_journal

    real_replace = call_journal.os.replace

    def recording_replace(source, destination) -> None:
        sources.append(Path(source))
        real_replace(source, destination)

    monkeypatch.setattr(call_journal.os, "replace", recording_replace)

    atomic_json_replace(target, {"value": 1})
    atomic_json_replace(target, {"value": 2})

    assert read_json(target) == {"value": 2}
    assert len(sources) == 2
    assert sources[0] != sources[1]
    assert all(source.parent == target.parent and source.name.endswith(".tmp") for source in sources)
    assert not any(source.exists() for source in sources)


def test_model_call_and_transport_files_transition_in_place(tmp_path: Path) -> None:
    journal = CallJournal(tmp_path)

    call_index = journal.begin_model_call()
    transport_index = journal.begin_transport_attempt(call_index)

    call_path = tmp_path / "usage-calls" / "000001.json"
    transport_path = tmp_path / "transport-attempts" / "000001-000001.json"
    in_flight = read_json(call_path)
    assert call_index == transport_index == 1
    assert in_flight == {
        "failure_kind": None,
        "input_tokens": None,
        "model_call_index": 1,
        "output_tokens": None,
        "status": "in_flight",
        "total_tokens": None,
        "transport_attempt_count": 1,
        "unavailable_reason": None,
        "usage_available": False,
        "usage_source": None,
    }

    journal.complete_model_call(
        call_index,
        {"input_tokens": 11, "output_tokens": 4, "total_tokens": 15},
        "provider_response_metadata",
    )

    completed = read_json(call_path)
    assert completed["status"] == "completed"
    assert completed["usage_available"] is True
    assert completed["input_tokens"] == 11
    assert completed["output_tokens"] == 4
    assert completed["total_tokens"] == 15
    assert completed["transport_attempt_count"] == 1
    assert read_json(transport_path)["status"] == "completed"
    assert sorted(path.name for path in (tmp_path / "usage-calls").glob("*.json")) == ["000001.json"]


def test_provider_error_replaces_in_flight_call_with_null_tokens(tmp_path: Path) -> None:
    journal = CallJournal(tmp_path)
    call_index = journal.begin_model_call()
    journal.begin_transport_attempt(call_index)
    classification = classify_failure(
        TimeoutError("secret provider response must not persist"),
        at_provider_boundary=True,
        successful_model_responses=0,
        tool_activity_count=0,
        provider_host="provider.invalid",
    )

    journal.fail_model_call(call_index, classification)

    payload = read_json(tmp_path / "usage-calls" / "000001.json")
    assert payload["status"] == "error"
    assert payload["failure_kind"] == FailureKind.PROVIDER_TRANSPORT.value
    assert payload["usage_available"] is False
    assert payload["input_tokens"] is None
    assert payload["output_tokens"] is None
    assert payload["total_tokens"] is None
    serialized = json.dumps(payload)
    assert "secret provider response" not in serialized
    assert read_json(tmp_path / "transport-attempts" / "000001-000001.json")["status"] == "error"


def test_abandoned_in_flight_call_is_preserved_as_kill_evidence(tmp_path: Path) -> None:
    journal = CallJournal(tmp_path)
    assert journal.begin_model_call() == 1

    restarted = CallJournal(tmp_path)
    summary = restarted.summarize()

    assert read_json(tmp_path / "usage-calls" / "000001.json")["status"] == "in_flight"
    assert summary.coverage == "unavailable"
    assert summary.unavailable_reason == "worker_killed_during_call"
    assert summary.in_flight_call_count == 1


def test_stale_temporary_files_are_quarantined_and_not_counted(tmp_path: Path) -> None:
    usage_dir = tmp_path / "usage-calls"
    transport_dir = tmp_path / "transport-attempts"
    usage_dir.mkdir(parents=True)
    transport_dir.mkdir(parents=True)
    (usage_dir / ".000001.json.deadbeef.tmp").write_text("{broken", encoding="utf-8")
    (transport_dir / ".000001-000001.json.deadbeef.tmp").write_text("{broken", encoding="utf-8")

    journal = CallJournal(tmp_path)
    summary = journal.summarize()

    assert not list(usage_dir.glob("*.tmp"))
    assert not list(transport_dir.glob("*.tmp"))
    quarantined = sorted(path.name for path in (tmp_path / "quarantine").iterdir())
    assert len(quarantined) == 2
    assert summary.model_call_count == 0
    assert summary.transport_attempt_count == 0
    assert summary.incomplete_temporary_file_count == 2


def test_concurrent_model_call_indexes_are_unique_and_restart_never_reuses_them(tmp_path: Path) -> None:
    journal = CallJournal(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as executor:
        indexes = list(executor.map(lambda _: journal.begin_model_call(), range(24)))

    assert sorted(indexes) == list(range(1, 25))
    assert len(list((tmp_path / "usage-calls").glob("*.json"))) == 24
    assert CallJournal(tmp_path).begin_model_call() == 25


def test_summary_mechanically_recomputes_call_transport_and_token_totals(tmp_path: Path) -> None:
    journal = CallJournal(tmp_path)
    first = journal.begin_model_call()
    journal.begin_transport_attempt(first)
    journal.complete_model_call(first, {"input_tokens": 8, "output_tokens": 3}, "callback")
    second = journal.begin_model_call()
    journal.begin_transport_attempt(second)
    journal.complete_model_call(second, {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}, "callback")

    summary = journal.summarize()

    assert summary.coverage == "full"
    assert summary.model_call_count == 2
    assert summary.completed_call_count == 2
    assert summary.error_call_count == 0
    assert summary.in_flight_call_count == 0
    assert summary.transport_attempt_count == 2
    assert summary.input_tokens == 13
    assert summary.output_tokens == 5
    assert summary.total_tokens == 18
