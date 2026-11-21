"""教员端（simulator）与学员端（trainee）共享源码单一真源同步与防漂移校验工具。

两端应用在运行时均需独立可搬迁（由 test_standalone.py 的审计钩子强制验证），
因此通过本脚本将共享层以 simulator/ 为权威源镜像同步至 trainee/，并在测试中通过
``--check`` 强制校验零漂移。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "shared_manifest.json"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _should_ignore(path: Path, ignore_names: set[str], ignore_suffixes: set[str]) -> bool:
    if any(part in ignore_names for part in path.parts):
        return True
    return path.suffix.lower() in ignore_suffixes


def collect_shared_files(
    app_root: Path,
    shared_paths: Iterable[str],
    ignore_names: set[str],
    ignore_suffixes: set[str],
) -> dict[str, Path]:
    """收集应用目录下清单覆盖的全部共享文件（相对路径 -> 绝对路径）。"""
    collected: dict[str, Path] = {}
    for raw_rel in shared_paths:
        target = app_root / raw_rel
        if not target.exists():
            continue
        if target.is_file():
            if not _should_ignore(target, ignore_names, ignore_suffixes):
                collected[target.relative_to(app_root).as_posix()] = target
        elif target.is_dir():
            for item in sorted(target.rglob("*")):
                if item.is_file() and not _should_ignore(item, ignore_names, ignore_suffixes):
                    collected[item.relative_to(app_root).as_posix()] = item
    return collected


def compare_shared(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, list[str]]:
    """对比权威源与目标端的共享文件，返回缺失、多余和内容漂移列表。"""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_root = REPO_ROOT / manifest["source_app"]
    target_root = REPO_ROOT / manifest["target_app"]
    shared_paths = list(manifest["shared_paths"])
    ignore_names = set(manifest.get("ignore_names", ()))
    ignore_suffixes = {s.lower() for s in manifest.get("ignore_suffixes", ())}

    src_files = collect_shared_files(source_root, shared_paths, ignore_names, ignore_suffixes)
    dst_files = collect_shared_files(target_root, shared_paths, ignore_names, ignore_suffixes)

    missing = sorted(set(src_files) - set(dst_files))
    extra = sorted(set(dst_files) - set(src_files))
    drifted = sorted(
        rel
        for rel in (set(src_files) & set(dst_files))
        if _file_sha256(src_files[rel]) != _file_sha256(dst_files[rel])
    )
    return {
        "total_source": [str(len(src_files))],
        "missing": missing,
        "extra": extra,
        "drifted": drifted,
    }


def sync_shared(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, int]:
    """将权威源共享层镜像同步到目标端。"""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_root = REPO_ROOT / manifest["source_app"]
    target_root = REPO_ROOT / manifest["target_app"]
    shared_paths = list(manifest["shared_paths"])
    ignore_names = set(manifest.get("ignore_names", ()))
    ignore_suffixes = {s.lower() for s in manifest.get("ignore_suffixes", ())}

    src_files = collect_shared_files(source_root, shared_paths, ignore_names, ignore_suffixes)
    dst_files = collect_shared_files(target_root, shared_paths, ignore_names, ignore_suffixes)

    copied = 0
    removed = 0
    for rel, src_path in sorted(src_files.items()):
        dst_path = target_root / rel
        if dst_path.exists() and _file_sha256(src_path) == _file_sha256(dst_path):
            continue
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)
        copied += 1

    for rel in sorted(set(dst_files) - set(src_files)):
        dst_files[rel].unlink(missing_ok=True)
        removed += 1

    return {"total": len(src_files), "copied": copied, "removed": removed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="共享源码同步与防漂移校验")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sync", action="store_true", help="将 simulator 共享源码同步至 trainee")
    mode.add_argument("--check", action="store_true", help="校验 simulator 与 trainee 共享层零漂移")
    args = parser.parse_args(argv)

    if args.sync:
        summary = sync_shared(args.manifest)
        print(
            f"Shared sync complete: total={summary['total']}, "
            f"updated={summary['copied']}, removed={summary['removed']}"
        )
        return 0

    diff = compare_shared(args.manifest)
    has_issue = bool(diff["missing"] or diff["extra"] or diff["drifted"])
    if not has_issue:
        print(f"Shared sync check PASSED: {diff['total_source'][0]} shared files identical (0 drift).")
        return 0
    print("Shared sync check FAILED:")
    for key in ("missing", "extra", "drifted"):
        for item in diff[key]:
            print(f"  [{key}] {item}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
