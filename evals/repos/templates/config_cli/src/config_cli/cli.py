from __future__ import annotations

import argparse
import json
import os
import tomllib
from pathlib import Path
from typing import Any

from config_cli.settings import resolve_settings


def _read_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="config-cli")
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("show", help="show resolved settings")
    show.add_argument("--config", type=Path, default=None, help="TOML settings file")
    show.add_argument("--host", default=None)
    show.add_argument("--retries", type=int, default=None)
    show.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = resolve_settings(
        cli={"host": args.host, "retries": args.retries},
        env={
            "host": os.getenv("CONFIG_CLI_HOST"),
            "retries": os.getenv("CONFIG_CLI_RETRIES"),
        },
        file=_read_config(args.config) if args.config else {},
    )
    if args.format == "json":
        print(json.dumps({"host": settings["host"], "retries": settings["retries"]}, sort_keys=True))
        return 0
    print(f"host={settings['host']}")
    print(f"retries={settings['retries']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
