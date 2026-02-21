#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys

ALLOWED_ENV_EXAMPLES = {
    ".env.example",
    ".env.docker.example",
    ".env.docker.prod.example",
}


def _staged_paths() -> list[str]:
    out = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"])
    if not out:
        return []
    return [p.decode("utf-8") for p in out.split(b"\x00") if p]


def main() -> int:
    paths = _staged_paths()
    blocked: list[str] = []

    for path in paths:
        # Protect against committing real environment files.
        if path == ".env" or (path.startswith(".env") and path not in ALLOWED_ENV_EXAMPLES):
            blocked.append(path)
            continue

        # SQLite databases / local state should never be committed.
        if path in {"db.sqlite3", "db.sqlite3-journal", "webgame"}:
            blocked.append(path)
            continue

        if path.startswith("media/"):
            blocked.append(path)
            continue

    if not blocked:
        return 0

    sys.stderr.write("\nBlocked files in commit (repo safety):\n")
    for item in sorted(set(blocked)):
        sys.stderr.write(f"  - {item}\n")
    sys.stderr.write("\nUse example files like .env.example, and keep local DB/media out of git.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
