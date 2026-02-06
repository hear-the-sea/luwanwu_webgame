#!/usr/bin/env python3

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement


def _iter_root_requirements(requirements_file: Path) -> list[str]:
    names: list[str] = []
    for raw_line in requirements_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r") or line.startswith("--requirement"):
            continue
        req = Requirement(line)
        names.append(req.name)
    return names


def _iter_runtime_root_names() -> list[str]:
    return _iter_root_requirements(Path(__file__).resolve().parent.parent / "requirements.txt")


def _dist_for_name(name: str) -> metadata.Distribution:
    # importlib.metadata is case-insensitive, but normalize anyway.
    return metadata.distribution(name)


def _iter_deps(dist: metadata.Distribution, env: dict[str, str]) -> list[str]:
    out: list[str] = []
    for raw in dist.requires or []:
        try:
            req = Requirement(raw)
        except Exception:
            continue

        if req.marker and not req.marker.evaluate(env):
            continue
        out.append(req.name)
    return out


def main() -> int:
    env = default_environment()

    pending = list(_iter_runtime_root_names())
    visited: set[str] = set()
    pinned: dict[str, str] = {}

    while pending:
        name = pending.pop()
        key = name.lower()
        if key in visited:
            continue
        visited.add(key)

        try:
            dist = _dist_for_name(name)
        except metadata.PackageNotFoundError:
            sys.stderr.write(f"Missing distribution for requirement: {name}\n")
            return 2

        pinned[dist.metadata["Name"]] = dist.version
        pending.extend(_iter_deps(dist, env))

    for name in sorted(pinned, key=lambda n: n.lower()):
        sys.stdout.write(f"{name}=={pinned[name]}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
