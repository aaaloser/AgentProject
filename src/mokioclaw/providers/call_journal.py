from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from mokioclaw.evals.provider_failures import FailureClassification
from mokioclaw.evals.telemetry import TelemetrySummary


def fsync_directory_best_effort(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except (AttributeError, OSError):
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def atomic_json_replace(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory_best_effort(path.parent)


def _empty_call_payload(model_call_index: int) -> dict[str, Any]:
    return {
        "failure_kind": None,
        "input_tokens": None,
        "model_call_index": model_call_index,
        "output_tokens": None,
        "status": "in_flight",
        "total_tokens": None,
        "transport_attempt_count": 0,
        "unavailable_reason": None,
        "usage_available": False,
        "usage_source": None,
    }


def _parse_index(path: Path) -> int | None:
    try:
        return int(path.stem)
    except ValueError:
        return None


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"unreadable journal file: {path.name} ({type(exc).__name__})") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"journal file is not an object: {path.name}")
    return payload


class CallJournal:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.usage_dir = self.root / "usage-calls"
        self.transport_dir = self.root / "transport-attempts"
        self.quarantine_dir = self.root / "quarantine"
        self.usage_dir.mkdir(parents=True, exist_ok=True)
        self.transport_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._quarantine_temporary_files()

    def _quarantine_temporary_files(self) -> None:
        stale = sorted([*self.usage_dir.glob("*.tmp"), *self.transport_dir.glob("*.tmp")], key=lambda path: str(path))
        if not stale:
            return
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        for path in stale:
            prefix = path.parent.name
            destination = self.quarantine_dir / f"{prefix}--{path.name}--{uuid4().hex}.quarantined"
            os.replace(path, destination)
        fsync_directory_best_effort(self.quarantine_dir)

    def _call_path(self, model_call_index: int) -> Path:
        if model_call_index <= 0:
            raise ValueError("model_call_index must be positive")
        return self.usage_dir / f"{model_call_index:06d}.json"

    def _transport_path(self, model_call_index: int, transport_attempt_index: int) -> Path:
        if model_call_index <= 0 or transport_attempt_index <= 0:
            raise ValueError("call and transport indexes must be positive")
        return self.transport_dir / f"{model_call_index:06d}-{transport_attempt_index:06d}.json"

    def _existing_call_indexes(self) -> list[int]:
        return [index for path in self.usage_dir.glob("*.json") if (index := _parse_index(path)) is not None]

    def begin_model_call(self) -> int:
        with self._lock:
            indexes = self._existing_call_indexes()
            model_call_index = max(indexes, default=0) + 1
            path = self._call_path(model_call_index)
            if path.exists():
                raise RuntimeError(f"model call file already exists: {path.name}")
            atomic_json_replace(path, _empty_call_payload(model_call_index))
            return model_call_index

    def begin_transport_attempt(self, model_call_index: int) -> int:
        with self._lock:
            call_path = self._call_path(model_call_index)
            call = _read_json_object(call_path)
            if call.get("status") != "in_flight":
                raise RuntimeError("transport attempt requires an in-flight model call")
            prefix = f"{model_call_index:06d}-"
            existing: list[int] = []
            for path in self.transport_dir.glob(f"{prefix}*.json"):
                suffix = path.stem.removeprefix(prefix)
                try:
                    existing.append(int(suffix))
                except ValueError:
                    continue
            transport_attempt_index = max(existing, default=0) + 1
            transport_path = self._transport_path(model_call_index, transport_attempt_index)
            payload = {
                "failure_kind": None,
                "model_call_index": model_call_index,
                "provider_phase": None,
                "provider_status": None,
                "retryable": False,
                "sanitized_reason": None,
                "status": "in_flight",
                "transport_attempt_index": transport_attempt_index,
            }
            atomic_json_replace(transport_path, payload)
            call["transport_attempt_count"] = transport_attempt_index
            atomic_json_replace(call_path, call)
            return transport_attempt_index

    def _close_transports(
        self,
        model_call_index: int,
        *,
        status: str,
        classification: FailureClassification | None = None,
    ) -> None:
        prefix = f"{model_call_index:06d}-"
        for path in sorted(self.transport_dir.glob(f"{prefix}*.json"), key=lambda candidate: candidate.name):
            payload = _read_json_object(path)
            if payload.get("status") != "in_flight":
                continue
            payload["status"] = status
            if classification is not None:
                payload["failure_kind"] = classification.failure_kind.value
                payload["provider_phase"] = classification.provider_phase
                payload["provider_status"] = classification.provider_status
                payload["retryable"] = classification.retryable
                payload["sanitized_reason"] = classification.sanitized_reason
            atomic_json_replace(path, payload)

    @staticmethod
    def _normalized_usage(usage: dict[str, Any] | None) -> tuple[dict[str, int] | None, str | None]:
        if not usage:
            return None, "provider_usage_missing"
        try:
            input_tokens = int(usage["input_tokens"])
            output_tokens = int(usage["output_tokens"])
            total_value = usage.get("total_tokens")
            total_tokens = input_tokens + output_tokens if total_value is None else int(total_value)
        except (KeyError, TypeError, ValueError, OverflowError):
            return None, "usage_parse_error"
        if any(isinstance(value, bool) for value in (usage.get("input_tokens"), usage.get("output_tokens"), total_value)):
            return None, "usage_parse_error"
        if input_tokens < 0 or output_tokens < 0 or total_tokens < 0 or total_tokens != input_tokens + output_tokens:
            return None, "usage_parse_error"
        return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens}, None

    def complete_model_call(self, model_call_index: int, usage: dict[str, Any] | None, source: str) -> None:
        with self._lock:
            path = self._call_path(model_call_index)
            payload = _read_json_object(path)
            if payload.get("status") != "in_flight":
                raise RuntimeError("model call is already terminal")
            normalized, unavailable_reason = self._normalized_usage(usage)
            payload["status"] = "completed"
            payload["usage_source"] = source
            payload["unavailable_reason"] = unavailable_reason
            if normalized is not None:
                payload.update(normalized)
                payload["usage_available"] = True
            atomic_json_replace(path, payload)
            self._close_transports(model_call_index, status="completed")

    def fail_model_call(self, model_call_index: int, classification: FailureClassification) -> None:
        with self._lock:
            path = self._call_path(model_call_index)
            payload = _read_json_object(path)
            if payload.get("status") != "in_flight":
                raise RuntimeError("model call is already terminal")
            payload["status"] = "error"
            payload["failure_kind"] = classification.failure_kind.value
            payload["unavailable_reason"] = "provider_error_before_usage"
            atomic_json_replace(path, payload)
            self._close_transports(model_call_index, status="error", classification=classification)

    def summarize(self) -> TelemetrySummary:
        calls = [_read_json_object(path) for path in sorted(self.usage_dir.glob("*.json"), key=lambda candidate: candidate.name)]
        transports = list(self.transport_dir.glob("*.json"))
        completed = [call for call in calls if call.get("status") == "completed"]
        errors = [call for call in calls if call.get("status") == "error"]
        in_flight = [call for call in calls if call.get("status") == "in_flight"]
        usable = [call for call in completed if call.get("usage_available") is True]
        reasons = {str(call.get("unavailable_reason")) for call in calls if call.get("unavailable_reason")}

        if not calls:
            coverage = "unavailable"
            unavailable_reason = "worker_killed_before_first_model_response"
        elif usable and len(usable) == len(calls) and not errors and not in_flight:
            coverage = "full"
            unavailable_reason = None
        elif usable:
            coverage = "partial"
            if "usage_parse_error" in reasons:
                unavailable_reason = "usage_parse_error"
            elif "provider_usage_missing" in reasons:
                unavailable_reason = "provider_usage_missing"
            elif in_flight:
                unavailable_reason = "worker_killed_during_call"
            elif errors:
                unavailable_reason = "provider_error_before_usage"
            else:
                unavailable_reason = None
        else:
            coverage = "unavailable"
            if "usage_parse_error" in reasons:
                unavailable_reason = "usage_parse_error"
            elif "provider_usage_missing" in reasons:
                unavailable_reason = "provider_usage_missing"
            elif errors:
                unavailable_reason = "provider_error_before_usage"
            elif in_flight:
                unavailable_reason = "worker_killed_during_call"
            else:
                unavailable_reason = "worker_killed_before_first_model_response"

        input_tokens = sum(int(call["input_tokens"]) for call in usable) if usable else None
        output_tokens = sum(int(call["output_tokens"]) for call in usable) if usable else None
        total_tokens = sum(int(call["total_tokens"]) for call in usable) if usable else None
        temporary_count = len(list(self.quarantine_dir.glob("*.quarantined"))) if self.quarantine_dir.exists() else 0
        return TelemetrySummary(
            coverage=coverage,
            unavailable_reason=unavailable_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            model_call_count=len(calls),
            completed_call_count=len(completed),
            error_call_count=len(errors),
            in_flight_call_count=len(in_flight),
            transport_attempt_count=len(transports),
            incomplete_temporary_file_count=temporary_count,
        )

    def latest_failure(self) -> dict[str, Any] | None:
        failures: list[dict[str, Any]] = []
        for path in sorted(self.transport_dir.glob("*.json"), key=lambda candidate: candidate.name):
            payload = _read_json_object(path)
            if payload.get("status") == "error" and payload.get("failure_kind"):
                failures.append(payload)
        return failures[-1] if failures else None
