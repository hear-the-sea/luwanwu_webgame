"""
Lightweight top-level import cycle checker (no third-party deps).

It only considers *module-level* imports (not imports inside functions), which is
the typical source of hard import cycles and slow startup.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


PROJECT_PACKAGES = {
    "accounts",
    "battle",
    "battle_debugger",
    "common",
    "config",
    "core",
    "gameplay",
    "guests",
    "guilds",
    "tasks",
    "trade",
    "websocket",
}


def _module_name_for_path(py_path: Path) -> Optional[str]:
    if py_path.suffix != ".py":
        return None

    # Treat repo root as sys.path entry.
    parts = list(py_path.with_suffix("").parts)
    if not parts:
        return None

    if parts[0] not in PROJECT_PACKAGES:
        return None

    # __init__.py -> package module
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _resolve_relative(from_module: str, level: int, to_module: Optional[str]) -> Optional[str]:
    """
    Resolve ast.ImportFrom(level=N, module=...) into an absolute module string.
    """
    if level <= 0:
        return to_module

    base_parts = from_module.split(".")
    if len(base_parts) < level:
        return None
    prefix = base_parts[: len(base_parts) - level]

    if to_module:
        return ".".join(prefix + to_module.split("."))
    return ".".join(prefix) if prefix else None


def _top_level_imports(module: str, py_path: Path) -> Set[str]:
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    except Exception:
        return set()

    imported: Set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = _resolve_relative(module, node.level or 0, node.module)
            if mod:
                imported.add(mod)
    return imported


def _project_root_modules(imported: Iterable[str]) -> Set[str]:
    out: Set[str] = set()
    for name in imported:
        top = name.split(".", 1)[0]
        if top in PROJECT_PACKAGES:
            out.add(name)
    return out


@dataclass(frozen=True)
class Cycle:
    nodes: Tuple[str, ...]

    def normalized(self) -> Tuple[str, ...]:
        # rotate to a stable canonical representation
        nodes = list(self.nodes)
        if not nodes:
            return tuple()
        mins = min(range(len(nodes)), key=lambda i: nodes[i])
        rotated = nodes[mins:] + nodes[:mins]
        return tuple(rotated)


def _find_cycles(graph: Dict[str, Set[str]]) -> List[Cycle]:
    cycles: Set[Tuple[str, ...]] = set()

    visiting: Set[str] = set()
    visited: Set[str] = set()
    stack: List[str] = []

    def dfs(node: str) -> None:
        visiting.add(node)
        stack.append(node)

        for nxt in graph.get(node, set()):
            if nxt not in graph:
                continue
            if nxt in visiting:
                # capture cycle slice
                try:
                    idx = stack.index(nxt)
                except ValueError:
                    continue
                cyc = stack[idx:].copy()
                cyc.append(nxt)
                cycles.add(Cycle(tuple(cyc)).normalized())
                continue
            if nxt in visited:
                continue
            dfs(nxt)

        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for start in sorted(graph):
        if start not in visited:
            dfs(start)

    return [Cycle(c) for c in sorted(cycles)]


def build_graph(repo_root: Path) -> Dict[str, Set[str]]:
    modules: Dict[str, Path] = {}
    for py_path in repo_root.rglob("*.py"):
        mod = _module_name_for_path(py_path.relative_to(repo_root))
        if mod:
            modules[mod] = py_path

    graph: Dict[str, Set[str]] = {m: set() for m in modules}
    for mod, path in modules.items():
        imported = _project_root_modules(_top_level_imports(mod, path))
        # Keep edges only to known modules or their packages.
        for imp in imported:
            # If importing a package, it can correspond to __init__ module.
            if imp in modules:
                graph[mod].add(imp)
                continue
            # Try to collapse to the nearest existing parent module.
            parts = imp.split(".")
            while parts:
                candidate = ".".join(parts)
                if candidate in modules:
                    graph[mod].add(candidate)
                    break
                parts.pop()

    return graph


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    graph = build_graph(repo_root)
    cycles = _find_cycles(graph)

    if not cycles:
        print("OK: no top-level import cycles detected.")
        return 0

    print(f"FOUND {len(cycles)} top-level import cycle(s):")
    for cyc in cycles:
        print("  - " + " -> ".join(cyc.nodes))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
