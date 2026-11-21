"""Project path helpers for the repository data layout."""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STARTUP_FILE = PROJECT_ROOT / "startup.json"
STARTUP_SETTINGS = json.loads(STARTUP_FILE.read_text(encoding="utf-8")) if STARTUP_FILE.is_file() else {}
DATA_DIR = (PROJECT_ROOT / STARTUP_SETTINGS.get("data_dir", "data")).resolve()
MODEL_DATA_DIR = DATA_DIR / "model"
MEAS_DATA_DIR = DATA_DIR / "meas"
LF_PARAMETER_DIR = DATA_DIR / "lf"
SE_PARAMETER_DIR = DATA_DIR / "se"


def _project_path(path: Path) -> Path:
    if path.parts and path.parts[0] == "data":
        return DATA_DIR.joinpath(*path.parts[1:])
    return PROJECT_ROOT / path


def model_file(case_type: str, name: str) -> Path:
    return MODEL_DATA_DIR / case_type / name


def measurement_file(case_type: str, name: str) -> Path:
    return MEAS_DATA_DIR / case_type / name


def resolve_project_file(path: str | Path) -> Path:
    """Resolve old repository-relative data paths to the current data layout."""
    candidate = Path(path)
    if candidate.exists():
        return candidate

    text = candidate.as_posix()
    suffix = candidate.suffix.lower()
    if suffix == ".meas":
        # Measurement files were historically mixed under model paths, so normalize
        # them before the generic data/model rewrites below.
        rewrites = (
            ("data/ac/", "data/meas/ac/"),
            ("data/dc/", "data/meas/dc/"),
            ("data/hybrid/", "data/meas/hybrid/"),
            ("data/model/ac/", "data/meas/ac/"),
            ("data/model/dc/", "data/meas/dc/"),
            ("data/model/hybrid/", "data/meas/hybrid/"),
        )
    else:
        rewrites = ()
    for old, new in rewrites:
        if old in text:
            rewritten = Path(text.replace(old, new))
            if rewritten.exists():
                return rewritten
            if not rewritten.is_absolute():
                absolute = _project_path(rewritten)
                if absolute.exists():
                    return absolute

    rewrites = (
        ("data/ac/", "data/model/ac/"),
        ("data/dc/", "data/model/dc/"),
        ("data/hybrid/", "data/model/hybrid/"),
        ("data/hybrid/", "data/ca/"),
        ("lf.para", "data/lf/lf.para"),
        ("se.para", "data/se/se.para"),
    )
    for old, new in rewrites:
        if old in text:
            rewritten = Path(text.replace(old, new))
            if rewritten.exists():
                return rewritten
            if not rewritten.is_absolute():
                absolute = _project_path(rewritten)
                if absolute.exists():
                    return absolute

    if not candidate.is_absolute():
        absolute = _project_path(candidate)
        if absolute.exists():
            return absolute
    return candidate
