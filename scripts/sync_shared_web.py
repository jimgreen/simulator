"""共享前端静态模块真源同步与一致性校验脚本。

以 shared/simu/web/common/ 为唯一真源，同步或校验教员端与学员端的共享脚本，
彻底杜绝双端副本手工拷贝产生的漂移风险。

用法：
  python scripts/sync_shared_web.py          # 将真源同步到教员端与学员端
  python scripts/sync_shared_web.py --check  # 仅校验字节级一致性（供 CI/测试调用）
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_DIR = REPO_ROOT / "shared" / "simu" / "web" / "common"

SHARED_ASSET_MAP: tuple[tuple[Path, tuple[Path, ...]], ...] = (
    (
        COMMON_DIR / "00-i18n.js",
        (
            REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "js" / "00-i18n.js",
            REPO_ROOT / "trainee" / "simu" / "web" / "trainee" / "js" / "00-i18n.js",
        ),
    ),
    (
        COMMON_DIR / "ux-enhancements.js",
        (
            REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "js" / "08-ux-enhancements.js",
            REPO_ROOT / "trainee" / "simu" / "web" / "trainee" / "js" / "09-ux-enhancements.js",
        ),
    ),
    (
        COMMON_DIR / "themes-common.css",
        (
            REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "themes-common.css",
            REPO_ROOT / "trainee" / "simu" / "web" / "trainee" / "themes-common.css",
        ),
    ),
    (
        COMMON_DIR / "scada-cockpit.css",
        (
            REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "scada-cockpit.css",
            REPO_ROOT / "trainee" / "simu" / "web" / "trainee" / "scada-cockpit.css",
        ),
    ),
    (
        COMMON_DIR / "scada-cockpit.js",
        (
            REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "js" / "10-scada-cockpit.js",
            REPO_ROOT / "trainee" / "simu" / "web" / "trainee" / "js" / "10-scada-cockpit.js",
        ),
    ),
    (
        COMMON_DIR / "assets" / "qinling-hero.jpg",
        (
            REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "assets" / "qinling-hero.jpg",
            REPO_ROOT / "trainee" / "simu" / "web" / "trainee" / "assets" / "qinling-hero.jpg",
        ),
    ),
    (
        COMMON_DIR / "assets" / "qinling-station-holo.png",
        (
            REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "assets" / "qinling-station-holo.png",
            REPO_ROOT / "trainee" / "simu" / "web" / "trainee" / "assets" / "qinling-station-holo.png",
        ),
    ),
)


def check_shared_assets() -> list[str]:
    """返回所有缺失或与真源不一致的目标路径列表。"""
    mismatches: list[str] = []
    for source, targets in SHARED_ASSET_MAP:
        if not source.is_file():
            mismatches.append(f"缺少共享真源：{source.relative_to(REPO_ROOT)}")
            continue
        source_bytes = source.read_bytes()
        for target in targets:
            if not target.is_file() or target.read_bytes() != source_bytes:
                mismatches.append(
                    f"{target.relative_to(REPO_ROOT)} 与 {source.relative_to(REPO_ROOT)} 不一致"
                )
    return mismatches


def sync_shared_assets() -> list[str]:
    """将共享真源覆盖复制到双端目标路径。"""
    updated: list[str] = []
    for source, targets in SHARED_ASSET_MAP:
        if not source.is_file():
            raise FileNotFoundError(f"共享真源不存在：{source}")
        source_bytes = source.read_bytes()
        for target in targets:
            if target.is_file() and target.read_bytes() == source_bytes:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            updated.append(str(target.relative_to(REPO_ROOT)))
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="共享 Web 静态脚本同步与一致性检查工具")
    parser.add_argument("--check", action="store_true", help="仅检查一致性，不写入文件")
    args = parser.parse_args()
    if args.check:
        issues = check_shared_assets()
        if issues:
            for item in issues:
                print(f"[FAIL] {item}", file=sys.stderr)
            return 1
        print("[OK] 所有共享 Web 静态模块与真源完全一致。")
        return 0
    updated = sync_shared_assets()
    if updated:
        print("[SYNC] 已更新以下共享前端模块：")
        for item in updated:
            print(f"  - {item}")
    else:
        print("[OK] 共享前端模块均已是最新，无需更新。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
