"""守卫 shared/ 公共层提取后 simulator 与 trainee 零重复文件与严格角色边界。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SIMULATOR_ROOT = REPO_ROOT / "simulator"
TRAINEE_ROOT = REPO_ROOT / "trainee"
SHARED_ROOT = REPO_ROOT / "shared"


def _collect_py_files(base: Path) -> dict[str, Path]:
    return {
        p.relative_to(base).as_posix(): p
        for p in base.rglob("*.py")
        if "__pycache__" not in p.parts and "tests" not in p.parts
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SharedArchitectureGuardTests(unittest.TestCase):
    """验证提取公因数后双端无同名同内容 Python 文件且角色模块彻底隔离。"""

    def test_no_duplicate_python_files_between_simulator_and_trainee(self) -> None:
        sim_files = _collect_py_files(SIMULATOR_ROOT)
        trn_files = _collect_py_files(TRAINEE_ROOT)
        identical = sorted(
            rel
            for rel in (set(sim_files) & set(trn_files))
            if _sha256(sim_files[rel]) == _sha256(trn_files[rel])
        )
        self.assertEqual(
            identical,
            [],
            f"simulator 与 trainee 之间存在同名同内容重复 Python 文件：{identical}",
        )

    def test_simulator_has_no_trainee_control_modules(self) -> None:
        forbidden = (
            "simu/renewable_control.py",
            "simu/renewable_control_parts",
            "simu/renewable_optimization.py",
            "simu/fuel_cell_control.py",
            "simu/resource_topology.py",
            "simu/trainee_exchange.py",
            "simu/control_config.py",
            "simu/config",
        )
        for rel in forbidden:
            self.assertFalse(
                (SIMULATOR_ROOT / rel).exists(),
                f"模拟台目录不应包含学员台控制决策模块：{rel}",
            )

    def test_trainee_has_no_simulator_cluster_or_scada_modules(self) -> None:
        forbidden = (
            "scada104.py",
            "simu/simulator_cluster.py",
            "simu/simulator_proxy.py",
        )
        for rel in forbidden:
            self.assertFalse(
                (TRAINEE_ROOT / rel).exists(),
                f"学员台目录不应包含模拟台独占模块：{rel}",
            )

    def test_role_check_loads_only_shared_and_own_modules(self) -> None:
        sim_res = subprocess.run(
            [sys.executable, "-X", "utf8", str(SIMULATOR_ROOT / "run.py"), "--check"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(sim_res.returncode, 0, sim_res.stderr)
        sim_info = json.loads(sim_res.stdout)
        self.assertEqual(sim_info["role"], "simulator")
        for mod_name, mod_path in sim_info["modules"].items():
            resolved = Path(mod_path).resolve()
            self.assertFalse(
                resolved.is_relative_to(TRAINEE_ROOT),
                f"simulator 进程不应加载 trainee 模块：{mod_name} -> {resolved}",
            )
            self.assertTrue(
                resolved.is_relative_to(SIMULATOR_ROOT) or resolved.is_relative_to(SHARED_ROOT),
                f"simulator 模块路径越界：{mod_name} -> {resolved}",
            )

        trn_res = subprocess.run(
            [sys.executable, "-X", "utf8", str(TRAINEE_ROOT / "run.py"), "--check"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(trn_res.returncode, 0, trn_res.stderr)
        trn_info = json.loads(trn_res.stdout)
        self.assertEqual(trn_info["role"], "trainee")
        for mod_name, mod_path in trn_info["modules"].items():
            resolved = Path(mod_path).resolve()
            self.assertFalse(
                resolved.is_relative_to(SIMULATOR_ROOT),
                f"trainee 进程不应加载 simulator 模块：{mod_name} -> {resolved}",
            )
            self.assertTrue(
                resolved.is_relative_to(TRAINEE_ROOT) or resolved.is_relative_to(SHARED_ROOT),
                f"trainee 模块路径越界：{mod_name} -> {resolved}",
            )


if __name__ == "__main__":
    unittest.main()
