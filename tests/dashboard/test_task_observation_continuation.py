"""Continuation proves disk state afresh and never imports legacy accounting."""

from dataclasses import asdict, replace
import hashlib
import importlib
import json
from pathlib import Path

import pytest

from task_continuation_fakes import NAMES, REPO, ROOT, SOURCE, TASK, SyntheticTask, offline_continuation_guard, raw


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_continuation_guard(monkeypatch):
        yield


@pytest.fixture
def case(monkeypatch):
    case = SyntheticTask()
    case.install(monkeypatch)
    try:
        yield case
    finally:
        case.backend.fail = None


def module():
    return importlib.import_module("mokioclaw.dashboard.task_observation_continuation")


def opened(case):
    options = module().ContinuationOptions(TASK, case.spec_sha, SOURCE)
    return module().PrestartObservationContinuation.open(options, ROOT, case.task_root, backend=case.backend)


def checked(case, continuation):
    return continuation.check(case.catalog, case.git, cached_record=case.record)


def preserved(case):
    return {name: hashlib.sha256(case.backend.nodes[case.obs / name][1]).hexdigest() for name in NAMES}


def test_metadata_whitelist_and_once(case):
    before = preserved(case)
    guard = opened(case)
    check = checked(case, guard)
    assert not any(event.startswith("create:") for event in case.backend.events)
    session = guard.create_session(check)
    metadata = json.loads(case.backend.nodes[session.directory.identity.final_path / "session.json"][1])
    assert set(metadata) == {"schema_version", "mode", "task_id", "session_id", "created_at", "expected_spec_sha256",
                             "record_sha256_at_bind", "manifest_digest", "previous_layout", "previous_files"}
    assert metadata["mode"] == "prestart_continuation" and metadata["previous_layout"] == "legacy"
    assert set(metadata["previous_files"]) == set(NAMES)
    assert all(set(row) == {"size_bytes", "sha256"} for row in metadata["previous_files"].values())
    assert {name: row["sha256"] for name, row in metadata["previous_files"].items()} == before
    assert len(session.session_id) == 32 and all(ch in "0123456789abcdef" for ch in session.session_id)
    assert metadata["task_id"] == TASK
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        guard.create_session(check)
    assert preserved(case) == before
    check.close()
    session.close()
    guard.close()
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        checked(case, opened(case))


@pytest.mark.parametrize("field,value", [("sequence", True), ("sequence", 2.0), ("state", "running"),
    ("execution_started", True), ("cleanup_confirmed", True), ("attempt_id", 1), ("worker_pid", 42),
    ("worker_created_at", "PRIVATE_SENTINEL"), ("instance_id", "PRIVATE_SENTINEL"),
    ("failure_kind", "x"), ("verification_status", "not_run"), ("owned_request_ids", ["x"]),
    ("execution_receipts", [{}]), ("request_digest", "0" * 64), ("events", []), ("extra", None)])
def test_never_executed_gate(case, field, value):
    record = asdict(case.record)
    record[field] = value
    case.backend.nodes[case.task_dir / "record.json"][1] = raw(record)
    before = preserved(case)
    guard = opened(case)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        checked(case, guard)
    assert preserved(case) == before
    assert not any(event.startswith("create:") for event in case.backend.events)
    guard.close()


@pytest.mark.parametrize("content", [b'{"sequence":2,"sequence":2}', b'{"value":NaN}', b'{"value":Infinity}', b'[]', b'bad'])
def test_strict_contract_and_record(case, content):
    case.backend.nodes[case.task_dir / "record.json"][1] = content
    guard = opened(case)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        checked(case, guard)
    guard.close()


@pytest.mark.parametrize("field,value", [("max_seconds", True), ("max_seconds", 1801), ("max_total_tokens", 300001),
    ("max_provider_calls", 25), ("max_output_tokens_per_call", 4097), ("max_attempts", 0), ("description", ""),
    ("source_write_scope", ["other.py"]), ("created_at", "yesterday"), ("manifest_digest", "0" * 64)])
def test_spec_schema_limits(case, field, value):
    data = asdict(case.spec)
    data[field] = value
    content = raw(data)
    case.backend.nodes[case.task_dir / "spec.json"][1] = content
    case.spec_sha = hashlib.sha256(content).hexdigest()
    guard = opened(case)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        checked(case, guard)
    guard.close()


def test_cached_full_record_drift(case):
    guard = opened(case)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        guard.check(case.catalog, case.git, cached_record=replace(case.record, idempotency_digest="0" * 64))
    guard.close()


@pytest.mark.parametrize("extra", ["work/extra-dir", "work/__pycache__", "baseline/empty"])
def test_scope_copies_exact(case, extra):
    case.backend.put(case.task_dir / "workspace" / extra)
    guard = opened(case)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        checked(case, guard)
    guard.close()


@pytest.mark.parametrize("path", ["baseline/file.py", "work/file.py", "work/.mokioclaw/task-scratch/NOTEPAD.md"])
def test_copies_reject_content_drift(case, path):
    case.backend.nodes[case.task_dir / "workspace" / path][1] = b"PRIVATE_SENTINEL"
    guard = opened(case)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        checked(case, guard)
    guard.close()


def test_legacy_finalize_allowed_strict_types(case):
    case.backend.nodes[case.obs / "scores.json"][1] = raw({"schema_version": 1, "task_id": TASK, "indexes": []})
    case.backend.nodes[case.obs / "status.json"][1] = raw({"schema_version": 1, "task_id": TASK, "valid": False,
        "event_count": 0, "started_calls": 0, "unknown_calls": 0, "reasons": ["cleanup_unconfirmed", "stream_incomplete"],
        "stream_closed": False, "cleanup_confirmed": False})
    guard = opened(case)
    check = checked(case, guard)
    before = preserved(case)
    guard.verify_preserved()
    assert preserved(case) == before
    check.close()
    guard.close()


@pytest.mark.parametrize("field,value", [("event_count", False), ("event_count", 0.0), ("valid", True),
    ("stream_closed", True), ("reasons", []), ("reasons", ["stream_incomplete", "cleanup_unconfirmed"]),
    ("reasons", ["observer_fault", "observer_fault"]), ("extra", "PRIVATE_SENTINEL")])
def test_legacy_final_invalid_types(case, field, value):
    data = {"schema_version": 1, "task_id": TASK, "valid": False, "event_count": 0, "started_calls": 0,
            "unknown_calls": 0, "reasons": ["cleanup_unconfirmed", "stream_incomplete"],
            "stream_closed": False, "cleanup_confirmed": False}
    data[field] = value
    case.backend.nodes[case.obs / "status.json"][1] = raw(data)
    guard = opened(case)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        checked(case, guard)
    guard.close()


def test_legacy_content_rejected_without_leak(case, caplog, capsys):
    case.backend.nodes[case.obs / "calls.jsonl"][1] = b"PRIVATE_SENTINEL"
    guard = opened(case)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        checked(case, guard)
    calls = [h for h in case.backend.handles if h.identity.final_path.name == "calls.jsonl"]
    assert all(h.stream.reads == 0 for h in calls)
    assert "PRIVATE_SENTINEL" not in caplog.text + str(capsys.readouterr())
    guard.close()


def test_restore_catalog_same_identity(case):
    restored = module().restore_continuation_catalog(case.catalog, case.spec, SOURCE)
    assert restored.get(REPO).root == SOURCE and restored.get("random_alias_0001") is None
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        module().restore_continuation_catalog(case.catalog, case.spec, Path("C:/other"))


def test_unknown_task_directory_rejected(case):
    case.backend.put(case.task_root / "unknown_terminal")
    guard = opened(case)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        checked(case, guard)
    assert not any(h.identity.final_path.name == "unknown_terminal" for h in case.backend.handles)
    guard.close()


def test_verified_store_never_path_reads(case, monkeypatch):
    from mokioclaw.dashboard.task_store import TaskStore
    hits = []
    def forbidden(*args, **kwargs):
        hits.append("path_read")
        raise AssertionError("unsafe_loader")
    with monkeypatch.context() as patch:
        for name in ("glob", "read_text", "mkdir"):
            patch.setattr(Path, name, forbidden)
        store = TaskStore(case.task_root, verified_records=(case.record,))
    assert store.get(TASK) == case.record and not hits


def service_for(case):
    from mokioclaw.dashboard.task_service import TaskService
    return TaskService(case.catalog, case.git, case.task_root,
                       continuation_options=module().ContinuationOptions(TASK, case.spec_sha, SOURCE), calibration_root=ROOT)


def test_service_preflight_order(case, monkeypatch):
    from mokioclaw.dashboard import task_service
    from task_continuation_fakes import FakeLease
    events = case.backend.events
    class Lease(FakeLease):
        def __init__(self, root, *, stream=None):
            events.append("lease")
            super().__init__(root, stream=stream)
    monkeypatch.setattr(task_service, "_TaskRootLease", Lease)
    service = service_for(case)
    try:
        assert service.store.get(TASK) == case.record
        assert service.catalog is service.source.catalog
        assert service.catalog.get(REPO).root == SOURCE and service.catalog.get("random_alias_0001") is None
        assert service.observation_manager is None and service._continuation.session is None
        assert events.index("pin:tasks") < events.index("lease") < events.index("verify:.dashboard.lock")
        assert sum(event == "pin:record.json" for event in events) == 2
    finally:
        service.close()


def test_verified_loading_rechecks_unknown_insertion(case):
    count = 0
    def drift():
        nonlocal count
        count += 1
        if count == 3:
            case.backend.put(case.task_root / "unknown_terminal")
    case.git.hook = drift
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        service_for(case)
    assert not any(event.startswith("create:") for event in case.backend.events)


def bound(case):
    service = service_for(case)
    manager = service.configure_calibration(ROOT)
    hello = {"schema_version": 1, "kind": "hello", "sequence": 1}
    assert service.receive_calibration_viewer(manager, hello)["accepted"] is True
    bind = {"schema_version": 1, "kind": "bind", "sequence": 2, "task_id": TASK}
    return service, manager, bind


def test_bind_new_session_only(case):
    before = preserved(case)
    service, manager, frame = bound(case)
    try:
        assert not manager.ready_for_start(TASK) and service._continuation.session is None
        assert manager.bind(TASK) is False
        state = service.receive_calibration_viewer(manager, frame)
        assert state["accepted"] is True and state["bound_task"] == TASK and manager.ready_for_start(TASK)
        session = service._continuation.session
        assert set(case.backend.children(session.directory, limit=4)) == {*NAMES, "session.json"}
        assert manager.journal.is_initial() is True
        assert manager._worker_bootstrap is None and service.store.get(TASK) == case.record
        assert preserved(case) == before
    finally:
        service.close()
    assert preserved(case) == before


@pytest.mark.parametrize("failure", ["create:sessions", "create:session.json", "write:session.json", "flush:session.json", "fsync",
    "create:calls.jsonl", "create:scores.json", "create:status.json", "write:status.json", "flush:status.json"])
def test_each_bind_failure_consumes_once(case, failure):
    before = preserved(case)
    service, manager, frame = bound(case)
    case.backend.fail = failure
    state = service.receive_calibration_viewer(manager, frame)
    assert state["accepted"] is False and not manager.ready_for_start(TASK)
    assert preserved(case) == before
    case.backend.fail = None
    consumed = case.obs / "sessions" in case.backend.nodes
    assert consumed is (failure != "create:sessions")
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        service.receive_calibration_viewer(manager, {**frame, "sequence": 3})
    assert sum(event == "create:sessions" for event in case.backend.events) == 1
    service.close()
    if consumed:
        with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
            service_for(case)


@pytest.mark.parametrize("fault", ["metadata", "extra", "external_session"])
def test_session_owned_not_disk_reloaded(case, fault):
    service, manager, frame = bound(case)
    assert service.receive_calibration_viewer(manager, frame)["accepted"] is True
    guard = service._continuation
    session = guard.session
    if fault == "metadata":
        case.backend.nodes[session.directory.identity.final_path / "session.json"][1] += b" "
    elif fault == "extra":
        case.backend.put(session.directory.identity.final_path / "extra")
    else:
        session = module().ObservationSession(guard, session.session_id, session.directory, session.metadata)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        guard.check(service.catalog, case.git, cached_record=case.record, session=session)
    # Explicitly restore synthetic drift so normal close can verify immutable metadata.
    if fault == "metadata":
        case.backend.nodes[guard.session.directory.identity.final_path / "session.json"][1] = session.metadata.stream.getvalue()
    if fault == "extra":
        del case.backend.nodes[session.directory.identity.final_path / "extra"]
    service.close()


@pytest.mark.parametrize("fault", ["record", "cache", "spec_cache", "source", "work", "old", "session", "nonempty_calls"])
def test_start_rejects_fresh_drift_before_image(case, fault):
    from types import SimpleNamespace
    from mokioclaw.dashboard.task_store import TaskConflict
    service, manager, frame = bound(case)
    assert service.receive_calibration_viewer(manager, frame)["accepted"] is True
    boundary_calls = []
    service.run_available = lambda: boundary_calls.append("image") or True
    service.task_image_digest = "sha256:" + "a" * 64
    def premature_start(task):
        boundary_calls.append("start")
        raise AssertionError("premature_worker_start")
    service.worker_controller = SimpleNamespace(broker=object(), start=premature_start, reconcile=lambda: None)
    snapshot = {path: list(data) for path, data in case.backend.nodes.items()}
    if fault == "record":
        data = asdict(case.record)
        data["execution_started"] = True
        case.backend.nodes[case.task_dir / "record.json"][1] = raw(data)
    elif fault == "cache":
        service.store._records[TASK] = replace(case.record, execution_started=True)
    elif fault == "spec_cache":
        service._specs[TASK] = replace(case.spec, max_total_tokens=1)
    elif fault == "source":
        case.git.state = replace(case.git.state, dirty=True)
    elif fault == "work":
        case.backend.nodes[case.task_dir / "workspace/work/file.py"][1] = b"changed"
    elif fault == "old":
        case.backend.nodes[case.obs / "scores.json"][1] = b"changed"
    elif fault == "session":
        case.backend.nodes[manager.session.directory.identity.final_path / "session.json"][1] += b" "
    else:
        manager.journal._owned_handles[0].stream.write(b"x")
    with pytest.raises(TaskConflict, match="^calibration_observation_invalid$"):
        service.start_agent(TASK)
    assert not boundary_calls and not manager.ready_for_start(TASK)
    case.backend.nodes = snapshot
    service.close()


def test_start_second_proof_after_image(case):
    from types import SimpleNamespace
    from mokioclaw.dashboard.task_store import TaskConflict
    service, manager, frame = bound(case)
    assert service.receive_calibration_viewer(manager, frame)["accepted"] is True
    calls = []
    def image():
        calls.append("image")
        case.backend.nodes[case.task_dir / "workspace/work/file.py"][1] = b"changed"
        return True
    service.run_available = image
    service.task_image_digest = "sha256:" + "a" * 64
    def premature_start(task):
        calls.append("start")
        raise AssertionError("premature_worker_start")
    service.worker_controller = SimpleNamespace(broker=object(), start=premature_start, reconcile=lambda: None)
    with pytest.raises(TaskConflict, match="^calibration_observation_invalid$"):
        service.start_agent(TASK)
    assert calls == ["image"]
    case.backend.nodes[case.task_dir / "workspace/work/file.py"][1] = case.git.content
    service.close()


@pytest.mark.parametrize("failure", ["close:calls.jsonl", "reconcile", "pool", "preserved", "close:session.json",
                                       "connection", "listener", "viewer"])
def test_close_barrier_retains_lease(case, failure):
    from types import SimpleNamespace
    service, manager, frame = bound(case)
    assert service.receive_calibration_viewer(manager, frame)["accepted"] is True
    def fail():
        raise OSError("PRIVATE_SENTINEL")
    if failure.startswith("close:"):
        case.backend.fail = failure
    elif failure == "reconcile":
        service.worker_controller = SimpleNamespace(reconcile=fail)
    elif failure == "pool":
        service.pool.shutdown = lambda **kw: fail()
    elif failure == "connection":
        manager._connections.append(SimpleNamespace(close=fail))
    elif failure == "listener":
        manager._listeners.append(SimpleNamespace(close=fail))
    elif failure == "viewer":
        manager._viewer_launch = SimpleNamespace(close=lambda: None, process=SimpleNamespace(poll=lambda: None))
    else:
        case.backend.nodes[case.obs / "scores.json"][1] = b"changed"
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        service.close()
    assert service._close_failed and service.lease.closed is False
    assert not manager.ready_for_start(TASK) and manager.journal._sealed
    assert not service._continuation.spec_handle.closed
    case.backend.fail = None
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        service.close()
    assert service.lease.closed is False


def test_close_guards_before_lease_and_late_callbacks(case):
    service, manager, frame = bound(case)
    assert service.receive_calibration_viewer(manager, frame)["accepted"] is True
    before = preserved(case)
    journal = manager.journal
    service.close()
    assert service.lease.closed and service._closed and journal._sealed
    assert all(handle.closed for handle in service._continuation.long_handles)
    assert manager.session.metadata.closed and manager.session.directory.closed
    events = case.backend.events
    assert events.index("close:session.json") < events.index("close:.dashboard.lock")
    last = len(events)
    manager.poll_terminal()
    assert manager.receive_worker({}) is False
    assert journal.set_indexes([]) is False
    assert len(events) == last and preserved(case) == before


def test_bind_eof_close_lock_order(case):
    from threading import Event, Thread
    service, manager, frame = bound(case)
    entered, release = Event(), Event()
    def slow():
        entered.set()
        assert release.wait(5)
    case.git.hook = slow
    result = []
    binder = Thread(target=lambda: result.append(service.receive_calibration_viewer(manager, frame)))
    binder.start()
    assert entered.wait(5)
    manager.invalidate()  # EOF must acquire manager lock during the slow Git proof.
    release.set()
    binder.join(5)
    assert not binder.is_alive() and result[0]["accepted"] is False and not manager.ready_for_start(TASK)
    service.close()


@pytest.mark.parametrize("changes", [
    {"task_id": None}, {"expected_spec_sha256": None}, {"expected_source_root": None},
    {"task_id": "bad"}, {"expected_spec_sha256": "A" * 64}, {"expected_source_root": Path("relative")},
    {"calibration_root": None}, {"task_root": ROOT / "wrong"}, {"enable_agent": False}, {"task_image": None},
    {"repo_paths": []}, {"repo_paths": [SOURCE, SOURCE]}, {"repo_paths": [Path("C:/other")]},
])
def test_continue_flags_group_and_raw_repo_count(case, changes):
    options = dict(task_id=TASK, expected_spec_sha256=case.spec_sha, expected_source_root=SOURCE,
                   calibration_root=ROOT, task_root=case.task_root, enable_agent=True,
                   task_image="sha256:" + "a" * 64, repo_paths=[SOURCE])
    options.update(changes)
    with pytest.raises(ValueError, match="^calibration_config_invalid$"):
        module().parse_continuation_options(**options)
    assert not case.backend.events


def test_cli_continuation_group_validates_before_launch(case, monkeypatch):
    from typer.testing import CliRunner
    from mokioclaw.cli.app import app
    from mokioclaw.dashboard import launcher
    calls = []
    monkeypatch.setattr(launcher, "launch_dashboard", lambda *args, **kw: calls.append((args, kw)))
    flags = ["dashboard", "--repo", str(SOURCE), "--task-root", str(case.task_root), "--calibration-root", str(ROOT),
             "--task-image", "sha256:" + "a" * 64, "--enable-agent", "--calibration-continue-task", TASK,
             "--calibration-expected-spec-sha256", case.spec_sha,
             "--calibration-expected-source-root", str(SOURCE), "--no-browser"]
    result = CliRunner().invoke(app, flags)
    assert result.exit_code == 0, result.output
    assert calls[0][1]["calibration_continue_task"] == TASK
    calls.clear()
    result = CliRunner().invoke(app, flags + ["--repo", str(SOURCE)])
    assert result.exit_code == 2 and "calibration_config_invalid" in result.output and not calls


def test_launcher_uses_restored_service_catalog(case, monkeypatch):
    from types import SimpleNamespace
    from mokioclaw.dashboard import launcher, task_diagnostics, task_diagnostic_viewer
    from mokioclaw.dashboard.task_service import TaskService
    from mokioclaw.providers.openai_provider import ProviderSettings
    events = []
    services = []
    class Service(TaskService):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            events.append("preflight")
            services.append(self)
        def configure_agent(self, settings, image):
            assert self.catalog is self.source.catalog
            assert settings is fake_settings
            events.append("configure")
    def startup(manager):
        events.append("viewer")
        manager._viewer_handler({"schema_version": 1, "kind": "hello", "sequence": 1})
    def settings():
        events.append("settings")
        return fake_settings
    fake_settings = object()
    viewer_state = {"alive": True}
    monkeypatch.setattr(launcher, "LocalGitReader", lambda: case.git)
    monkeypatch.setattr(launcher, "TaskService", Service)
    monkeypatch.setattr(task_diagnostic_viewer, "validate_calibration", lambda *args, **kw: None)
    monkeypatch.setattr(task_diagnostics.CalibrationObservationManager, "start_servers", startup)
    monkeypatch.setattr(task_diagnostic_viewer, "launch_viewer", lambda bootstrap: SimpleNamespace(
        process=SimpleNamespace(poll=lambda: None if viewer_state["alive"] else 0),
        close=lambda: viewer_state.update(alive=False)))
    # Stop after the real startup path presents its restored catalog; no socket.
    def create_app(catalog, reader, codec, *, task_service):
        assert catalog is task_service.catalog is task_service.source.catalog
        assert catalog.get(REPO).root == SOURCE and catalog.get("random_alias_0001") is None
        assert task_service._continuation.session is None
        events.append("app")
        raise KeyboardInterrupt
    monkeypatch.setattr(launcher, "create_dashboard_app", create_app)
    # Undo the fake before the outer sticky guard restores the original method.
    with monkeypatch.context() as settings_patch:
        settings_patch.setattr(ProviderSettings, "from_environment", settings)
        with pytest.raises(KeyboardInterrupt):
            launcher.launch_dashboard([SOURCE], open_browser=False, task_root=case.task_root, enable_agent=True,
                task_image="sha256:" + "a" * 64, calibration_root=ROOT, calibration_continue_task=TASK,
                calibration_expected_spec_sha256=case.spec_sha, calibration_expected_source_root=SOURCE)
    assert events == ["preflight", "viewer", "settings", "configure", "app"]
    assert services[0].lease.closed and services[0]._closed


def test_bind_short_handle_close_failure_never_ready(case):
    service, manager, frame = bound(case)
    case.backend.fail = "close:record.json"
    state = service.receive_calibration_viewer(manager, frame)
    assert state["accepted"] is False and not manager.ready_for_start(TASK)
    assert service._continuation.cleanup_failed
    case.backend.fail = None
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        service.close()
    assert service.lease.closed is False


def test_journal_close_failure_cannot_silently_retry(case):
    service, manager, frame = bound(case)
    assert service.receive_calibration_viewer(manager, frame)["accepted"]
    journal = manager.journal
    case.backend.fail = "close:calls.jsonl"
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        journal.seal_and_close()
    case.backend.fail = None
    before = len(case.backend.events)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        journal.seal_and_close()
    assert len(case.backend.events) == before
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        service.close()
    assert not service.lease.closed


@pytest.mark.parametrize("fault", ["spec_float", "status_bool"])
def test_initial_and_cached_spec_strict_types(case, fault):
    from types import SimpleNamespace
    from mokioclaw.dashboard.task_store import TaskConflict
    service, manager, frame = bound(case)
    assert service.receive_calibration_viewer(manager, frame)["accepted"]
    effects = []
    service.run_available = lambda: effects.append("image") or True
    def premature_start(task):
        effects.append("start")
        raise AssertionError("premature_worker_start")
    service.worker_controller = SimpleNamespace(broker=object(), start=premature_start, reconcile=lambda: None)
    service.task_image_digest = "sha256:" + "a" * 64
    if fault == "spec_float":
        service._specs[TASK] = replace(case.spec, max_total_tokens=150000.0)
    else:
        data = {"schema_version": True, "task_id": TASK, "valid": False, "reason": "stream_incomplete"}
        case.backend.nodes[manager.session.directory.identity.final_path / "status.json"][1] = raw(data)
    with pytest.raises(TaskConflict, match="^calibration_observation_invalid$"):
        service.start_agent(TASK)
    assert not effects
    service.close()


def memory_request(app, path, monkeypatch, *, method="GET", body=None):
    """ASGI router transport, immediate threadpool double; never makes a socket."""
    import fastapi.routing
    import starlette.routing
    from contextlib import AsyncExitStack
    async def immediate(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr(fastapi.routing, "run_in_threadpool", immediate)
    monkeypatch.setattr(starlette.routing, "run_in_threadpool", immediate)
    messages = []
    async def receive():
        return {"type": "http.request", "body": raw(body or {}), "more_body": False}
    async def send(message):
        messages.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
             "headers": [(b"host", b"127.0.0.1"), (b"content-type", b"application/json")],
             "server": ("127.0.0.1", 80), "client": ("127.0.0.1", 1), "root_path": "", "app": app}
    scope["fastapi_middleware_astack"] = AsyncExitStack()
    scope["fastapi_inner_astack"] = AsyncExitStack()
    scope["fastapi_function_astack"] = AsyncExitStack()
    coroutine = app.router(scope, receive, send)
    try:
        yielded = coroutine.send(None)
        raise AssertionError(f"unexpected_async_effect:{type(yielded).__name__}")
    except StopIteration:
        pass
    finally:
        coroutine.close()
    start = next(message for message in messages if message["type"] == "http.response.start")
    content = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], json.loads(content)


def test_restored_task_api_identity_strict(case, monkeypatch):
    from mokioclaw.dashboard.api import create_dashboard_app
    from mokioclaw.dashboard.pagination import CursorCodec
    service = service_for(case)
    app = create_dashboard_app(service.catalog, case.git, CursorCodec(), task_service=service)
    status, task = memory_request(app, "/api/tasks/" + TASK, monkeypatch)
    assert status == 200 and task["repo_id"] == REPO and task["base_sha"] == case.spec.base_sha
    status, repositories = memory_request(app, "/api/repositories", monkeypatch)
    assert status == 200 and repositories[0]["id"] == REPO
    status, _ = memory_request(app, "/api/tasks/bad", monkeypatch)
    assert status == 404
    # Static identity checks remain unchanged; this is not browser execution.
    from mokioclaw.dashboard import api
    script = Path(api.__file__).with_name("static").joinpath("app.js").read_text(encoding="utf-8")
    assert "record.repo_id !== state.repoId" in script
    assert "record.base_sha !== state.selectedSha" in script
    assert "record.anchor_sha !== state.anchorSha" in script
    service.close()


def test_api_run_rejects_drift_before_image(case, monkeypatch):
    from mokioclaw.dashboard.api import create_dashboard_app
    from mokioclaw.dashboard.pagination import CursorCodec
    service, manager, frame = bound(case)
    assert service.receive_calibration_viewer(manager, frame)["accepted"]
    effects = []
    service.run_available = lambda: effects.append("image") or True
    case.backend.nodes[case.task_dir / "workspace/work/file.py"][1] = b"changed"
    app = create_dashboard_app(service.catalog, case.git, CursorCodec(), task_service=service)
    status, response = memory_request(app, "/api/tasks/" + TASK + "/run", monkeypatch, method="POST")
    assert status == 409 and response["code"] == "task_conflict" and not effects
    service.close()


@pytest.mark.parametrize("name,limit", [("spec.json", 65536), ("record.json", 1048576),
                                        ("status.json", 4096), ("scores.json", 65536)])
@pytest.mark.parametrize("overflow", [0, 1])
def test_bounded_whole_file_not_truncated(case, name, limit, overflow):
    path = (case.task_dir if name in {"spec.json", "record.json"} else case.obs) / name
    content = case.backend.nodes[path][1]
    if name == "scores.json":
        content = raw({"schema_version": 1, "task_id": TASK, "indexes": []})
    case.backend.nodes[path][1] = content + b" " * (limit + overflow - len(content))
    if name == "spec.json":
        case.spec_sha = hashlib.sha256(case.backend.nodes[path][1]).hexdigest()
    guard = opened(case)
    if overflow:
        with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
            checked(case, guard)
    else:
        check = checked(case, guard)
        check.close()
    guard.close()


@pytest.mark.parametrize("failure", ["flush:calls.jsonl", "flush:scores.json", "session_dir", "short_write", 2, 3, 4, 5])
def test_remaining_bind_failure_points(case, monkeypatch, failure):
    from task_continuation_fakes import MemoryStream
    service, manager, frame = bound(case)
    counter = []
    if failure == "session_dir":
        def random_id(length):
            counter.append(length)
            return "a" * 32
        monkeypatch.setattr(module().secrets, "token_hex", random_id)
        case.backend.fail = "create:" + "a" * 32
    elif failure == "short_write":
        original = MemoryStream.write
        def short(self, value):
            size = original(self, value)
            return size - 1 if self.path.name == "session.json" else size
        monkeypatch.setattr(MemoryStream, "write", short)
    elif type(failure) is int:
        def fsync(fd):
            assert fd == -12345
            counter.append(fd)
            if len(counter) == failure:
                raise OSError("PRIVATE_SENTINEL")
        monkeypatch.setattr(os_module(), "fsync", fsync)
    else:
        case.backend.fail = failure
    state = service.receive_calibration_viewer(manager, frame)
    assert state["accepted"] is False and not manager.ready_for_start(TASK)
    assert case.obs / "sessions" in case.backend.nodes
    if failure == "session_dir":
        assert counter == [16]
    case.backend.fail = None
    service.close()
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        service_for(case)


def os_module():
    import os
    return os


def test_delayed_writer_references_cannot_write_after_close(case):
    from threading import Event, Thread
    service, manager, frame = bound(case)
    assert service.receive_calibration_viewer(manager, frame)["accepted"]
    journal = manager.journal
    ready, release, finished = Event(), Event(), Event()
    result = []
    def late():
        ready.set()
        assert release.wait(5)
        result.append(journal.emit(None))
        result.append(journal.set_indexes([]))
        manager.poll_terminal()
        finished.set()
    thread = Thread(target=late)
    thread.start()
    assert ready.wait(5)
    service.close()
    before = len(case.backend.events)
    release.set()
    assert finished.wait(5)
    thread.join(5)
    assert not thread.is_alive() and result == [False, False] and len(case.backend.events) == before


def test_initialization_close_failure_keeps_owner_alive(case):
    from mokioclaw.dashboard import task_service
    before = len(task_service._retained_close_failures)
    case.backend.fail = "close:record.json"
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        service_for(case)
    assert len(task_service._retained_close_failures) == before + 1
    owner = task_service._retained_close_failures[-1]
    assert owner._close_failed and not owner.lease.closed


@pytest.mark.parametrize("stage", ["factory", "reconcile"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_late_initialization_failure_closes_guards_before_lease(case, monkeypatch, stage, cleanup_fails):
    from types import SimpleNamespace
    from mokioclaw.dashboard import task_service
    from task_continuation_fakes import FakeLease
    before = len(task_service._retained_close_failures)
    leases = []
    class Lease(FakeLease):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            leases.append(self)
    monkeypatch.setattr(task_service, "_TaskRootLease", Lease)
    def fail():
        if cleanup_fails:
            case.backend.fail = "close:spec.json"
        raise RuntimeError("PRIVATE_SENTINEL")
    def factory(store):
        if stage == "factory":
            fail()
        return SimpleNamespace(reconcile=fail)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        task_service.TaskService(case.catalog, case.git, case.task_root,
            continuation_options=module().ContinuationOptions(TASK, case.spec_sha, SOURCE),
            calibration_root=ROOT, worker_controller_factory=factory)
    if cleanup_fails:
        assert len(task_service._retained_close_failures) == before + 1
        assert not leases[0].closed
    else:
        assert leases[0].closed
        assert all(handle.closed for handle in case.backend.handles)


def test_copy_file_cap_counts_across_directories_before_reading(case):
    guard = opened(case)
    files = {f"group{n % 2}/{n}.txt": b"" for n in range(5001)}
    temporary = []
    before = len(case.backend.events)
    with pytest.raises(ValueError, match="^calibration_observation_invalid$"):
        guard._copies(case.task_dir / "workspace/work", files, temporary)
    assert case.backend.events[before:] == []
    assert temporary == []
    guard.close()
