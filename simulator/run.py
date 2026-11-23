"""Run the simulator console independently of the caller's working directory."""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
ROLE = "simulator"


def _resolve_shared_root() -> Path:
    env_shared = str(os.environ.get("POWER_SIMU_SHARED_ROOT", "") or "").strip()
    if env_shared:
        return Path(env_shared).resolve()
    for candidate in (ROOT.parent / "shared", ROOT / "shared"):
        if (candidate / "simu").is_dir():
            return candidate.resolve()
    return ROOT


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if any(arg == "--role" or arg.startswith("--role=") for arg in args):
        raise SystemExit(f"This launcher runs the {ROLE} role.")
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or newer is required.")
    shared_root = _resolve_shared_root()
    os.environ["POWER_SIMU_APP_ROOT"] = str(ROOT)
    os.environ["POWER_SIMU_SHARED_ROOT"] = str(shared_root)
    # 保证 shared_root 位于 sys.path 最前以加载 shared/simu/__init__.py（extend_path 合并本端 simu/）
    for entry in (str(ROOT), str(shared_root)):
        if entry in sys.path:
            sys.path.remove(entry)
        sys.path.insert(0, entry)
    os.chdir(ROOT)
    try:
        # The package sets numeric thread limits before NumPy/BLAS is loaded.
        from simu.server import main as serve, parse_args
        import numpy
        import scipy
        from algorithm_parameters import DEFAULT_LF_PARAMETER_FILE
        from paths import DATA_DIR, STARTUP_SETTINGS
    except ImportError as exc:
        req_file = shared_root / "requirements.txt" if (shared_root / "requirements.txt").is_file() else ROOT / "requirements.txt"
        raise SystemExit(
            f"Missing dependency: {exc}. Install with: "
            f'"{sys.executable}" -m pip install -r "{req_file}"'
        ) from exc
    settings = STARTUP_SETTINGS
    if not DEFAULT_LF_PARAMETER_FILE.is_file():
        raise SystemExit(f"Missing power-flow parameters: {DEFAULT_LF_PARAMETER_FILE}")
    models_dir = (ROOT / settings["models_dir"]).resolve() if "models_dir" in settings else DATA_DIR / "models"
    runtime_dir = (ROOT / settings["runtime_dir"]).resolve() if "runtime_dir" in settings else DATA_DIR / "runtime"
    defaults = [
        "--role", ROLE, "--sim-dir", str(ROOT),
        "--host", settings["host"], "--port", str(settings["port"]),
        "--models-dir", str(models_dir),
        "--runtime-dir", str(runtime_dir),
    ]
    if ROLE == "simulator":
        defaults += ["--first-service-port", str(settings["first_service_port"])]
    if "--check" in args:
        effective = parse_args(defaults + [arg for arg in args if arg != "--check"])
        modules = {
            name: str(Path(module.__file__).resolve())
            for name, module in list(sys.modules.items())
            if name in {"simu_loop", "ac_lf", "dc_lf", "hybrid_lf", "efile_read", "paths"}
            or name.startswith("simu.")
            if getattr(module, "__file__", None)
        }
        print(json.dumps({
            "role": ROLE, "root": str(ROOT), "python": sys.executable,
            "numpy": numpy.__version__, "scipy": scipy.__version__,
            "host": effective.host, "port": effective.port,
            "data_dir": str(DATA_DIR),
            "models_dir": effective.models_dir, "runtime_dir": effective.runtime_dir,
            "first_service_port": effective.first_service_port,
            "lf_parameters": str(DEFAULT_LF_PARAMETER_FILE),
            "modules": modules,
        }, ensure_ascii=False))
        return 0
    log_dir = ROOT / "log"
    log_dir.mkdir(exist_ok=True)
    logger = logging.getLogger("simu.web")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        log_dir / "web.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    try:
        return serve(defaults + args)
    except Exception:
        logger.exception("Web service failed")
        raise
    finally:
        logger.removeHandler(handler)
        handler.close()


if __name__ == "__main__":
    raise SystemExit(main())
