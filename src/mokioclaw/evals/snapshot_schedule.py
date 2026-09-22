from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from mokioclaw.evals.analysis_spec import canonical_json_bytes
from mokioclaw.evals.worker_ledger import scheduled_run_id


SNAPSHOT_CELLS = (
    "anchor-b40-t600",
    "cell-b80-t600",
    "cell-b40-t900",
    "cell-b80-t900",
)
SNAPSHOT_ARCHITECTURES = ("react", "plan-execute", "multi-agent")
CLICK_SCHEDULE_SEED = 20260922
CLICK_PROTOCOL_VERSION = 2


def _hash_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: value for key, value in payload.items() if key != "schedule_sha256"}
    normalized["slots"] = [
        {key: value for key, value in slot.items() if key != "scheduled_run_id"}
        for slot in normalized.get("slots", [])
    ]
    return normalized


def schedule_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(_hash_payload(payload))).hexdigest()


def build_snapshot_schedule(
    seed: int = CLICK_SCHEDULE_SEED,
    *,
    case_ids: list[str] | tuple[str, ...] = (),
    architectures: list[str] | tuple[str, ...] = SNAPSHOT_ARCHITECTURES,
) -> dict[str, Any]:
    stable_cases = sorted(set(case_ids))
    stable_architectures = list(architectures)
    if len(stable_cases) > 2:
        raise ValueError("snapshot protocol supports at most two Cases")
    if len(stable_cases) != len(case_ids):
        raise ValueError("Case IDs must be unique")
    base = list(SNAPSHOT_CELLS)
    random.Random(seed).shuffle(base)
    rounds = {f"R{index + 1}": base[index:] + base[:index] for index in range(3)}
    payload: dict[str, Any] = {
        "schema_version": 2,
        "protocol_version": CLICK_PROTOCOL_VERSION,
        "seed": seed,
        "cells": list(SNAPSHOT_CELLS),
        "architectures": stable_architectures,
        "case_ids": stable_cases,
        "base_permutation": base,
        "rounds": rounds,
        "run_budget": len(stable_cases) * len(stable_architectures) * len(SNAPSHOT_CELLS) * 3,
        "slots": [],
    }
    slots: list[dict[str, Any]] = []
    for round_index, (round_name, cells) in enumerate(rounds.items(), start=1):
        for cell in cells:
            for case_id in stable_cases:
                for architecture in stable_architectures:
                    slots.append(
                        {
                            "round": round_name,
                            "architecture": architecture,
                            "case_id": case_id,
                            "cell": cell,
                            "repeat": round_index,
                            "base_position": base.index(cell),
                        }
                    )
    payload["slots"] = slots
    payload["schedule_sha256"] = schedule_sha256(payload)
    for slot in slots:
        slot["scheduled_run_id"] = scheduled_run_id(
            case_id=slot["case_id"],
            architecture=slot["architecture"],
            cell=slot["cell"],
            repeat=slot["repeat"],
            schedule_sha256=payload["schedule_sha256"],
        )
    return payload


def write_snapshot_schedule(
    path: Path,
    seed: int = CLICK_SCHEDULE_SEED,
    *,
    case_ids: list[str] | tuple[str, ...] = (),
    architectures: list[str] | tuple[str, ...] = SNAPSHOT_ARCHITECTURES,
) -> Path:
    payload = build_snapshot_schedule(seed, case_ids=case_ids, architectures=architectures)
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != payload:
            raise RuntimeError("existing snapshot schedule mismatch; use a new batch root")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a preregistered Mokioclaw snapshot schedule")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=CLICK_SCHEDULE_SEED)
    parser.add_argument("--cases", required=True, help="Comma-separated frozen Case IDs")
    args = parser.parse_args()
    case_ids = [item.strip() for item in args.cases.split(",") if item.strip()]
    print(write_snapshot_schedule(args.output, args.seed, case_ids=case_ids))


if __name__ == "__main__":
    main()
