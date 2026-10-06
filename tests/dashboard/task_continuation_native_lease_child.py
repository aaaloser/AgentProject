"""Opt-in synthetic lock peer. Importing this module performs no I/O."""

import argparse
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    arguments = parser.parse_args(argv)
    try:
        if os.name != "nt" or os.environ.get("MOKIOCLAW_CONTINUATION_NATIVE_FILES") != "1":
            return 2
        supplied = Path(arguments.root)
        root = supplied.resolve(strict=True)
        temp = Path(tempfile.gettempdir()).resolve(strict=True)
        synthetic = root.parent if root.name == "tasks" else root
        if (not supplied.is_absolute() or root != Path(os.path.abspath(supplied)) or temp not in root.parents
                or re.fullmatch(r"mokioclaw-continuation-native-[0-9a-f]{32}", synthetic.name) is None):
            return 2
        for path in (root, *root.parents):
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                return 2
        lock = root / ".dashboard.lock"
        info = lock.lstat()
        if lock.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400 or info.st_nlink != 1:
            return 2
        import msvcrt
        with lock.open("r+b") as stream:
            if not stream.read(1):
                return 2
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                print("locked", flush=True)
                if sys.stdin.readline() != "release\n":
                    return 2
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            print("released", flush=True)
        return 0
    except (OSError, ValueError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
