"""Polar microgrid time-series simulation service and web consoles."""

from __future__ import annotations

import os
from pathlib import Path
from pkgutil import extend_path

# 通过 pkgutil.extend_path 合并 shared/simu 与当前启动角色（simulator/simu 或 trainee/simu）
# 实现双端零重复文件，同时兼容所有既有 `simu.xxx` 导入路径。
__path__ = extend_path(__path__, __name__)


def resolve_app_root() -> Path:
    """解析当前启动应用根目录（simulator/ 或 trainee/）。"""
    env_root = str(os.environ.get("POWER_SIMU_APP_ROOT", "") or "").strip()
    if env_root:
        return Path(env_root).resolve()
    cwd = Path.cwd().resolve()
    if (cwd / "startup.json").is_file() or (cwd / "simu" / "web").is_dir():
        return cwd
    for entry in __path__:
        candidate = Path(entry).resolve().parent
        if (candidate / "startup.json").is_file() or (candidate / "simu" / "web").is_dir():
            return candidate
    return Path(__file__).resolve().parents[1]


def resolve_web_dir() -> Path:
    """解析当前应用角色对应的前端静态资源目录（<app_root>/simu/web）。"""
    app_web = resolve_app_root() / "simu" / "web"
    if app_web.is_dir():
        return app_web
    for entry in __path__:
        candidate = Path(entry).resolve() / "web"
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parent / "web"


NUMERIC_THREAD_ENV_NAMES = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


def _configure_numeric_thread_limits() -> str:
    raw_limit = str(os.environ.get("POWER_SIMU_NUMERIC_THREADS", "1") or "1").strip()
    try:
        limit = str(max(1, min(64, int(float(raw_limit)))))
    except (TypeError, ValueError):
        limit = "1"
    os.environ["POWER_SIMU_NUMERIC_THREADS"] = limit
    for name in NUMERIC_THREAD_ENV_NAMES:
        os.environ.setdefault(name, limit)
    return limit


NUMERIC_THREAD_LIMIT = _configure_numeric_thread_limits()

from .service import MultiModelSimulator, PolarMicrogridSimulator, SimulationModelSpec

__all__ = [
    "MultiModelSimulator",
    "PolarMicrogridSimulator",
    "SimulationModelSpec",
    "NUMERIC_THREAD_ENV_NAMES",
    "NUMERIC_THREAD_LIMIT",
]
