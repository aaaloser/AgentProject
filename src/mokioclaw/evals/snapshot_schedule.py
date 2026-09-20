from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


SNAPSHOT_CELLS = (
    "anchor-b40-t600",
    "cell-b80-t600",
    "cell-b40-t900",
    "cell-b80-t900",
)


def build_snapshot_schedule(seed: int = 20260920) -> dict[str, Any]:
    base = list(SNAPSHOT_CELLS)
    random.Random(seed).shuffle(base)
    return {
        "schema_version": 1,
        "seed": seed,
        "cells": list(SNAPSHOT_CELLS),
        "rounds": {f"R{index + 1}": base[index:] + base[:index] for index in range(3)},
    }


def write_snapshot_schedule(path: Path, seed: int = 20260920) -> Path:
    payload = build_snapshot_schedule(seed)
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
    parser.add_argument("--seed", type=int, default=20260920)
    args = parser.parse_args()
    print(write_snapshot_schedule(args.output, args.seed))


if __name__ == "__main__":
    main()
