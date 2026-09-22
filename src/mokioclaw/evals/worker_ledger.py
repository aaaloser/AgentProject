from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from mokioclaw.evals.analysis_spec import canonical_json_bytes


def scheduled_run_id(*, case_id: str, architecture: str, cell: str, repeat: int, schedule_sha256: str) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "architecture": architecture,
                "case_id": case_id,
                "cell": cell,
                "repeat": repeat,
                "schedule_sha256": schedule_sha256,
            }
        )
    ).hexdigest()


@dataclass(frozen=True)
class WorkerAttempt:
    scheduled_run_id: str
    worker_attempt_id: str
    directory: Path


class WorkerAttemptLedger:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "worker-attempt-ledger.jsonl"
        self.attempts_root = self.root / "worker-attempts"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise RuntimeError(f"worker ledger row {line_number} is not an object")
            events.append(payload)
        return events

    def _append(self, payload: dict[str, Any]) -> None:
        events = self.events()
        row = {"event_sequence": len(events) + 1, **payload}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def launch(self, scheduled_run_id: str, *, worker_attempt_id: str | None = None) -> WorkerAttempt:
        with self._lock:
            events = self.events()
            if any(event.get("scheduled_run_id") == scheduled_run_id for event in events):
                raise RuntimeError(f"scheduled run already launched or recorded: {scheduled_run_id}")
            attempt_id = worker_attempt_id or f"worker-{uuid4().hex}"
            if any(event.get("worker_attempt_id") == attempt_id for event in events):
                raise RuntimeError(f"worker attempt already exists: {attempt_id}")
            directory = self.attempts_root / attempt_id
            directory.mkdir(parents=True, exist_ok=False)
            self._append(
                {
                    "attempt_path": directory.relative_to(self.root).as_posix(),
                    "event": "launch",
                    "scheduled_run_id": scheduled_run_id,
                    "worker_attempt_id": attempt_id,
                }
            )
            return WorkerAttempt(scheduled_run_id, attempt_id, directory)

    def terminal(
        self,
        scheduled_run_id: str,
        worker_attempt_id: str,
        *,
        status: str,
        agent_attempt_count: int = 0,
    ) -> None:
        with self._lock:
            events = self.events()
            matching = [
                event
                for event in events
                if event.get("scheduled_run_id") == scheduled_run_id
                and event.get("worker_attempt_id") == worker_attempt_id
            ]
            if not matching or matching[0].get("event") != "launch":
                raise RuntimeError("terminal event requires a matching launch")
            if any(event.get("event") == "terminal" for event in matching):
                raise RuntimeError("worker attempt is already terminal")
            self._append(
                {
                    "agent_attempt_count": agent_attempt_count,
                    "event": "terminal",
                    "scheduled_run_id": scheduled_run_id,
                    "status": status,
                    "worker_attempt_id": worker_attempt_id,
                }
            )

    def mark_not_started(self, scheduled_run_id: str, *, reason: str) -> None:
        with self._lock:
            events = self.events()
            matching = [event for event in events if event.get("scheduled_run_id") == scheduled_run_id]
            if any(event.get("event") == "launch" for event in matching):
                raise RuntimeError("cannot mark a launched scheduled run not_started")
            if matching:
                raise RuntimeError("scheduled run is already recorded")
            self._append({"event": "not_started", "reason": reason, "scheduled_run_id": scheduled_run_id})
