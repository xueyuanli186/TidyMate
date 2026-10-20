"""Scan throughput benchmark (read-only product code, write-capable test harness).

Two modes, because they answer different questions:

``--mode real``
    Creates ``--count`` empty files under ``--root`` (default: a fresh directory under
    %TEMP%) and scans them with real Win32 directory I/O. This measures what users feel.
    **This mode writes files** - it is a benchmark harness, not product code, and it never
    deletes anything afterwards.

``--mode synthetic``
    Builds an in-memory tree of ``--count`` entries and injects it into the walker. The
    numbers measure walker bookkeeping (path normalisation, entry construction, counters)
    with zero disk I/O. Useful for regression-testing the hot loop without filling a disk,
    and it is clearly labelled as synthetic in the output.

Usage::

    python scripts/bench_scan.py --mode real --count 10000
    python scripts/bench_scan.py --mode synthetic --count 100000 --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tidymate_core.scanning import ScanConfig, scan  # noqa: E402
from tidymate_core.scanning.walker import ScandirFn  # noqa: E402


def _temp_root(count: int) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Path(os.environ.get("TEMP", str(REPO_ROOT))) / f"tidymate-bench-{count}-{stamp}"


def build_real_tree(root: Path, count: int, per_directory: int = 500) -> int:
    """Create *count* empty files spread over a shallow directory tree."""
    created = 0
    directory_index = 0
    while created < count:
        directory = root / f"dir{directory_index:03d}"
        directory.mkdir(parents=True, exist_ok=True)
        directory_index += 1
        for file_index in range(per_directory):
            if created >= count:
                break
            (directory / f"file{file_index:04d}.txt").write_text("", encoding="utf-8")
            created += 1
    return created


class _FakeStat:
    __slots__ = ("st_dev", "st_file_attributes", "st_ino", "st_mtime", "st_size")

    def __init__(self, size: int) -> None:
        self.st_size = size
        self.st_file_attributes = 0x20
        self.st_mtime = 1_700_000_000.0
        self.st_dev = 1
        self.st_ino = 2


class _FakeEntry:
    __slots__ = ("_stat", "name", "path")

    def __init__(self, name: str, stat: _FakeStat) -> None:
        self.name = name
        self.path = name
        self._stat = stat

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        return False

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        return True

    def is_symlink(self) -> bool:
        return False

    def stat(self, *, follow_symlinks: bool = True) -> Any:
        return self._stat


class _FakeHandle:
    __slots__ = ("_entries",)

    def __init__(self, entries: list[_FakeEntry]) -> None:
        self._entries = entries

    def __enter__(self) -> Iterator[_FakeEntry]:
        return iter(self._entries)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


def synthetic_scandir(count: int, directories: int = 100) -> tuple[ScandirFn, str]:
    """Return a scandir replacement yielding *count* synthetic files under *directories*."""
    from tidymate_core.safety import paths

    root = "C:\\bench-root"
    per_directory = max(1, count // directories)
    stat = _FakeStat(size=128)
    tree: dict[str, list[_FakeEntry]] = {}

    class _DirEntry(_FakeEntry):
        __slots__ = ()

        def is_dir(self, *, follow_symlinks: bool = True) -> bool:
            return True

        def is_file(self, *, follow_symlinks: bool = True) -> bool:
            return False

    tree[paths.to_extended(root)] = [
        _DirEntry(f"dir{index:03d}", stat) for index in range(directories)
    ]
    for index in range(directories):
        directory = f"{root}\\dir{index:03d}"
        tree[paths.to_extended(directory)] = [
            _FakeEntry(f"file{item:05d}.txt", stat) for item in range(per_directory)
        ]

    def scandir(path: str) -> _FakeHandle:
        return _FakeHandle(tree.get(path, []))

    return cast("ScandirFn", scandir), root


def run_benchmark(mode: str, count: int) -> dict[str, object]:
    """Run one benchmark and return its measurements."""
    if mode == "real":
        bench_root = _temp_root(count)
        created = build_real_tree(bench_root, count)
        config = ScanConfig(roots=(str(bench_root),))
        started = time.perf_counter()
        result = scan(config)
        elapsed = time.perf_counter() - started
        return {
            "mode": "real",
            "requested": count,
            "created": created,
            "files": result.stats.files,
            "dirs": result.stats.dirs,
            "errors": result.stats.errors,
            "elapsed_s": round(elapsed, 3),
            "files_per_second": round(result.stats.files / elapsed) if elapsed else 0,
            "root": str(bench_root),
            "note": "real NTFS directory I/O; empty files created by the harness",
        }

    scandir_fn, synthetic_root = synthetic_scandir(count)
    config = ScanConfig(roots=(synthetic_root,))
    started = time.perf_counter()
    result = scan(config, scandir=scandir_fn)
    elapsed = time.perf_counter() - started
    return {
        "mode": "synthetic",
        "requested": count,
        "created": count,
        "files": result.stats.files,
        "dirs": result.stats.dirs,
        "errors": result.stats.errors,
        "elapsed_s": round(elapsed, 3),
        "files_per_second": round(result.stats.files / elapsed) if elapsed else 0,
        "root": synthetic_root,
        "note": "in-memory entries injected into the walker; no disk I/O",
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; prints JSON when ``--json`` is given."""
    parser = argparse.ArgumentParser(description="TidyMate scan benchmark")
    parser.add_argument("--mode", choices=("real", "synthetic"), default="real")
    parser.add_argument("--count", type=int, default=10_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = run_benchmark(str(args.mode), int(args.count))
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"{payload['mode']}: {payload['files']} files in {payload['elapsed_s']}s "
            f"({payload['files_per_second']} files/s), {payload['dirs']} dirs",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
