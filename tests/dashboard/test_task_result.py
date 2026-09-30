from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace
import hashlib

from mokioclaw.dashboard.task_models import ExecutionReceipt, PublicTaskEvent, TaskRecord, TaskSpec
from mokioclaw.dashboard.task_result import build_task_result


TASK = "task_1234567890123456"
REQUEST = "request_12345678901234"
COMMAND = "python -m pytest -q"
DIGEST = "f" * 64


def _receipt(*, exit_code: int = 0, duration_ms: int = 41,
             ok: bool = True, output_truncated: bool = False,
             command: str = COMMAND) -> ExecutionReceipt:
    return ExecutionReceipt(1, REQUEST, hashlib.sha256(command.encode()).hexdigest(),
                            DIGEST, exit_code, duration_ms, ok, output_truncated)


def _event(sequence: int, kind: str, data: dict, attempt: int = 1) -> PublicTaskEvent:
    return PublicTaskEvent(TASK, attempt, sequence, "2026-09-29T00:00:00Z", kind, data)


def _spec(commands: tuple[str, ...] = (COMMAND,)) -> TaskSpec:
    return TaskSpec(
        task_id=TASK, repo_id="repo_12345678", base_sha="a" * 40, anchor_sha="b" * 40,
        description="repair", source_read_scope=("src/",), source_write_scope=("src/",),
        task_scratch_scope=".mokioclaw/task-scratch/", manifest_digest="c" * 64,
        max_seconds=100, max_attempts=2, verification_commands=commands,
        max_provider_calls=2, max_total_tokens=100, max_output_tokens_per_call=20,
        created_at="2026-09-29T00:00:00Z",
    )


def _record(state: str, events: tuple[PublicTaskEvent, ...], *, failure: str | None = None,
            cleanup: bool = True, attempt: int = 1,
            receipts: tuple[ExecutionReceipt, ...] = ()) -> TaskRecord:
    return TaskRecord(
        task_id=TASK, repo_id="repo_12345678", base_sha="a" * 40, anchor_sha="b" * 40,
        manifest_digest="c" * 64, created_at="2026-09-29T00:00:00Z", state=state,
        attempt_id=attempt, sequence=len(events), request_digest="d" * 64,
        idempotency_digest="e" * 64, failure_kind=failure, cleanup_confirmed=cleanup,
        execution_started=True, events=events, execution_receipts=receipts,
    )


def _prepared(tmp_path: Path):
    root = tmp_path / TASK
    baseline = root / "workspace" / "baseline"
    work = root / "workspace" / "work"
    (baseline / "src").mkdir(parents=True)
    (work / "src").mkdir(parents=True)
    (baseline / "src" / "a.py").write_text("before\n", encoding="utf-8")
    (work / "src" / "a.py").write_text("after\n", encoding="utf-8")
    return SimpleNamespace(root=root, baseline=baseline, work=work)


def test_result_binds_command_to_approved_request_and_reports_patch_without_content(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path)
    events = (
        _event(1, "approval_request", {"status": "waiting", "request_id": REQUEST,
                                        "execution_digest": DIGEST}),
        _event(2, "approval_decision", {"decision": "approved", "request_id": REQUEST}),
        _event(3, "verification", {"status": "passed", "exit_code": 0, "duration_ms": 41,
                                   "command_index": 0, "request_id": REQUEST, "output_truncated": True}),
    )
    result = build_task_result(_record("completed", events,
                                       receipts=(_receipt(output_truncated=True),)), _spec(), prepared)
    assert result.base_sha == "a" * 40 and result.status == "completed"
    assert result.changed_files == ("src/a.py",)
    assert result.patch_summary.status == "available"
    assert result.verification_status == "passed"
    check = result.verification_results[0]
    assert check.command == COMMAND and check.command_request_id == REQUEST
    assert check.exit_code == 0 and check.duration_ms == 41
    assert check.status == "passed" and check.output_redacted and check.output_truncated
    assert "after" not in repr(result) and str(prepared.root) not in repr(result)


def test_completed_without_approved_evidence_is_not_verification_pass(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path)
    forged = (_event(1, "verification", {"status": "passed", "exit_code": 0,
                                             "command_index": 0, "request_id": REQUEST}),)
    result = build_task_result(_record("completed", forged), _spec(), prepared)
    assert result.verification_status == "not_run"
    assert result.verification_results[0].status == "not_run"
    assert "verification_evidence_incomplete" in result.limitations


def test_approved_event_without_parent_execution_receipt_is_not_a_pass(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path)
    events = (
        _event(1, "approval_request", {"status": "waiting", "request_id": REQUEST,
                                        "execution_digest": DIGEST}),
        _event(2, "approval_decision", {"decision": "approved", "request_id": REQUEST}),
        _event(3, "verification", {"status": "passed", "exit_code": 0, "duration_ms": 41,
                                   "command_index": 0, "request_id": REQUEST}),
    )
    result = build_task_result(_record("completed", events), _spec(), prepared)
    assert result.verification_status == "not_run"
    assert "verification_evidence_incomplete" in result.limitations


def test_verification_rejects_mismatched_parent_receipt(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path)
    events = (
        _event(1, "approval_request", {"status": "waiting", "request_id": REQUEST,
                                        "execution_digest": DIGEST}),
        _event(2, "approval_decision", {"decision": "approved", "request_id": REQUEST}),
        _event(3, "verification", {"status": "passed", "exit_code": 0, "duration_ms": 41,
                                   "command_index": 0, "request_id": REQUEST}),
    )
    variants = (
        replace(_receipt(), execution_digest="e" * 64),
        _receipt(command="another command"),
        replace(_receipt(), exit_code=2),
        replace(_receipt(), duration_ms=42),
        replace(_receipt(), ok=False),
    )
    for receipt in variants:
        result = build_task_result(_record("completed", events, receipts=(receipt,)), _spec(), prepared)
        assert result.verification_status == "not_run"
        assert "verification_evidence_incomplete" in result.limitations


def test_one_approved_execution_cannot_satisfy_two_fixed_checks(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path)
    events = (
        _event(1, "approval_request", {"status": "waiting", "request_id": REQUEST,
                                        "execution_digest": DIGEST}),
        _event(2, "approval_decision", {"decision": "approved", "request_id": REQUEST}),
        _event(3, "verification", {"status": "passed", "exit_code": 0, "duration_ms": 41,
                                   "command_index": 0, "request_id": REQUEST}),
        _event(4, "verification", {"status": "passed", "exit_code": 0, "duration_ms": 41,
                                   "command_index": 1, "request_id": REQUEST}),
    )
    result = build_task_result(_record("completed", events, receipts=(_receipt(),)),
                               _spec((COMMAND, COMMAND)), prepared)
    assert result.verification_status == "not_run"
    assert all(item.status == "not_run" for item in result.verification_results)
    assert "verification_evidence_incomplete" in result.limitations


def test_invalid_duplicate_verification_also_invalidates_approved_receipt(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path)
    events = (
        _event(1, "approval_request", {"status": "waiting", "request_id": REQUEST,
                                        "execution_digest": DIGEST}),
        _event(2, "approval_decision", {"decision": "approved", "request_id": REQUEST}),
        _event(3, "verification", {"status": "passed", "exit_code": 0, "duration_ms": 41,
                                   "command_index": 0, "request_id": REQUEST}),
        _event(4, "verification", {"status": "passed", "exit_code": 0, "duration_ms": 41,
                                   "command_index": 9, "request_id": REQUEST}),
    )
    result = build_task_result(_record("completed", events, receipts=(_receipt(),)),
                               _spec(), prepared)
    assert result.verification_status == "not_run"
    assert result.verification_results[0].status == "not_run"


def test_completed_with_real_failed_verification_remains_visibly_unverified(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path)
    events = (
        _event(1, "approval_request", {"status": "waiting", "request_id": REQUEST,
                                        "execution_digest": DIGEST}),
        _event(2, "approval_decision", {"decision": "approved", "request_id": REQUEST}),
        _event(3, "verification", {"status": "failed", "exit_code": 2, "duration_ms": 14,
                                   "command_index": 0, "request_id": REQUEST}),
    )
    result = build_task_result(_record("completed", events,
                                       receipts=(_receipt(exit_code=2, duration_ms=14, ok=False),)),
                               _spec(), prepared)
    assert result.status == "completed" and result.verification_status == "failed"
    assert result.verification_results[0].exit_code == 2
    assert "completion_unverified" in result.limitations


def test_cancelled_partial_and_failure_categories_stay_distinct(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path)
    events = (
        _event(1, "approval_request", {"status": "waiting", "request_id": REQUEST,
                                        "execution_digest": DIGEST}),
        _event(2, "approval_decision", {"decision": "approved", "request_id": REQUEST}),
        _event(3, "verification", {"status": "failed", "exit_code": 1, "duration_ms": 52,
                                   "command_index": 0, "request_id": REQUEST}),
    )
    cancelled = build_task_result(_record("cancelled", events,
                                          receipts=(_receipt(exit_code=1, duration_ms=52, ok=False),)),
                                  _spec(), prepared)
    assert cancelled.status == "cancelled" and cancelled.verification_status == "failed"
    assert "partial_evidence" in cancelled.limitations
    provider = build_task_result(_record("failed", (), failure="provider_failed"), _spec(), prepared)
    assert provider.failure_kind == "provider_failed" and provider.verification_status == "not_run"
    tool = build_task_result(_record("failed", (), failure="task_tool_failed"), _spec(), prepared)
    assert tool.failure_kind == "task_tool_failed"
    (prepared.work / "src" / "a.py").write_bytes(b"\xff")
    unsafe = build_task_result(_record("failed", (), failure="worker_failed"), _spec(), prepared)
    assert unsafe.patch_summary.status == "patch_unavailable" and unsafe.changed_files == ()


def test_result_never_collects_patch_before_cleanup(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path)
    result = build_task_result(_record("cleanup_failed", (), cleanup=False), _spec(), prepared)
    assert result.patch_summary.status == "patch_unavailable"
    assert result.patch_summary.reason == "cleanup_unconfirmed"
    assert not (prepared.root / "artifacts" / "patch.diff").exists()


def test_preparation_failure_does_not_claim_resource_cleanup_failed(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path)
    source = _record("failed", (), failure="preparation_failed", cleanup=False)
    source = replace(source, attempt_id=None, execution_started=False)
    result = build_task_result(source, _spec(), prepared)
    assert result.failure_kind == "preparation_failed"
    assert result.patch_summary.reason == "workspace_unavailable"
    assert "cleanup_unconfirmed" not in result.limitations
