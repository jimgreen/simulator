"""Run the trainee console independently of the caller's working directory."""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
ROLE = "trainee"


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if any(arg == "--role" or arg.startswith("--role=") for arg in args):
        raise SystemExit(f"This launcher runs the {ROLE} role.")
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or newer is required.")
    settings = json.loads((ROOT / "startup.json").read_text(encoding="utf-8"))
    # An absolute script path also works with python -I and from another cwd.
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    try:
        # The package sets numeric thread limits before NumPy/BLAS is loaded.
        from simu.server import main as serve, parse_args
        import numpy
        import scipy
        from algorithm_parameters import DEFAULT_LF_PARAMETER_FILE
    except ImportError as exc:
        raise SystemExit(
            f"Missing dependency: {exc}. Install with: "
            f'"{sys.executable}" -m pip install -r "{ROOT / "requirements.txt"}"'
        ) from exc
    defaults = [
        "--role", ROLE, "--sim-dir", str(ROOT),
        "--host", settings["host"], "--port", str(settings["port"]),
        "--models-dir", str((ROOT / settings["models_dir"]).resolve()),
        "--runtime-dir", str((ROOT / settings["runtime_dir"]).resolve()),
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
