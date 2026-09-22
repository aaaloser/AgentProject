from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mokioclaw.evals.analysis_spec import canonical_json_bytes
from mokioclaw.providers.call_journal import atomic_json_replace


IDENTITY_DOMAINS = frozenset({"framework", "provider", "repository", "environment", "experiment"})
UNORDERED_LIST_FIELDS = frozenset({"architectures", "case_ids"})
FORBIDDEN_FIELDS = frozenset(
    {"api_key", "authorization", "secret", "token", "password", "prompt", "response", "headers", "payload", "query", "endpoint"}
)
PER_ATTEMPT_FIELDS = frozenset({"worker_attempt_id", "started_at", "ended_at", "exit_code", "artifact_path"})
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True)
class ExperimentFingerprint:
    schema_version: int
    identity: dict[str, Any]
    canonical_bytes: bytes
    sha256: str


def _canonicalize(value: Any, *, field: str = "") -> Any:
    if isinstance(value, dict):
        return {key: _canonicalize(value[key], field=key) for key in sorted(value)}
    if isinstance(value, list):
        normalized = [_canonicalize(item) for item in value]
        return sorted(normalized) if field in UNORDERED_LIST_FIELDS else normalized
    return value


def _validate_identity(value: Any, *, location: str = "identity") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key in FORBIDDEN_FIELDS:
                raise ValueError(f"forbidden secret-bearing identity field at {location}.{key}")
            if key in PER_ATTEMPT_FIELDS:
                raise ValueError(f"per-worker-attempt field is not identity: {key}")
            _validate_identity(item, location=f"{location}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_identity(item, location=f"{location}[{index}]")
        return
    if isinstance(value, str):
        if WINDOWS_ABSOLUTE.match(value) or value.startswith("/"):
            raise ValueError(f"absolute path is not allowed in identity at {location}")
        if location.endswith("provider.host") and any(marker in value for marker in ("://", "/", "?", "@")):
            raise ValueError("provider.host must contain only the sanitized host")


def build_experiment_fingerprint(domains: dict[str, Any]) -> ExperimentFingerprint:
    if not isinstance(domains, dict) or set(domains) != IDENTITY_DOMAINS:
        raise ValueError(f"identity must contain exactly these domains: {sorted(IDENTITY_DOMAINS)}")
    _validate_identity(domains)
    identity = _canonicalize(domains)
    canonical = canonical_json_bytes(identity)
    return ExperimentFingerprint(4, identity, canonical, hashlib.sha256(canonical).hexdigest())


def write_experiment_fingerprint(
    root: Path,
    fingerprint: ExperimentFingerprint,
    *,
    metadata: dict[str, Any],
    worker_attempt: dict[str, Any] | None = None,
) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    identity_path = root / "experiment-fingerprint.json"
    audit_path = root / "fingerprint-audit.json"
    identity_payload = {
        "identity": fingerprint.identity,
        "identity_sha256": fingerprint.sha256,
        "schema_version": fingerprint.schema_version,
    }
    atomic_json_replace(identity_path, identity_payload)
    atomic_json_replace(audit_path, {"metadata": metadata, "worker_attempt": worker_attempt})
    return {"identity": identity_path, "audit": audit_path}


def verify_experiment_fingerprint(path: Path, candidate: ExperimentFingerprint) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 4:
        raise RuntimeError("experiment fingerprint schema mismatch")
    stored_identity = payload.get("identity")
    stored_hash = payload.get("identity_sha256")
    if not isinstance(stored_identity, dict) or stored_hash != hashlib.sha256(canonical_json_bytes(stored_identity)).hexdigest():
        raise RuntimeError("experiment fingerprint integrity failure")
    if stored_hash != candidate.sha256 or stored_identity != candidate.identity:
        raise RuntimeError("experiment identity drift")
