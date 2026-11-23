"""Service layer for the polar microgrid time-series simulation system.

The service deliberately keeps the web/API layer thin.  It owns the runtime
copies of the E files, projects curve/settings/trainee-command overlays into
those files, calls the existing load-flow kernel, and exposes JSON snapshots
that both the simulator console and trainee console can poll.
"""

from __future__ import annotations

import copy
import hashlib
import heapq
import json
import math
import os
import re
import shutil
import threading
import time
import uuid
from bisect import bisect_left
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from simu_loop import EBook
from efile_read import EBlock

import simu_loop

from simu.definition_editing import (
    clamp_setpoint_safety_bounds,
    DefinitionSnapshot,
    MEASUREMENT_STATUS_TOKENS,
    MEASUREMENT_STATUS_VALIDITY,
    SafetyBoundaryError,
    atomic_write_text,
    normalize_device_changes,
    normalize_measurement_changes,
    ratio_parameter_number,
    require_definition_revision,
)
from simu.device_roles import (
    AC_TO_DC,
    converter_control_mode,
    converter_power_in_dc_to_ac_convention,
    converter_power_setpoint_fields,
)
from simu.device_runtime_frame import compact_device_runtime_frame
from simu.model_semantics import (
    HYDROGEN_CONVERSION_BLOCKS,
    device_family_from_block,
    energy_coupling_control_bindings,
    grid_converter_keys,
    resolve_resource_reference,
    resource_keys_by_alias,
    resources_by_device_key,
    structured_resources,
    normalize_hydrogen_conversion_control_mode,
    resource_aliases,
    terminal_domains_from_block,
    validate_hydrogen_power_setpoint_safety,
)
from simu.measurement_delta import (
    compact_measurement_delta,
    measurement_definition_signature,
    measurement_row_index,
    measurement_rows_by_definition_index,
)
from simu.measurement_history import MeasurementHistoryStore
from simu.point_names import automatic_point_name
from simu.power_flow_worker import PowerFlowExecution, PowerFlowTimeoutError
from simu.renewable_capability import renewable_weather_available_kw
from simu.source_curves import (
    load_curve_catalog,
    load_curve_identity,
    source_curve_catalog,
    source_curve_catalog_by_identity,
    source_curve_catalog_by_key,
    source_curve_identity,
)
from simu.web_runtime_settings import runtime_settings_payload, updated_runtime_settings_entry


WEATHER_HEADER = (
    "time",
    "wind_speed_mps",
    "air_temp_c",
    "air_pressure_hpa",
    "solar_irradiance_w_m2",
    "humidity_pct",
    "load_kw",
)

RUNTIME_LOAD_POWER_HEADER = ("dev_type", "dev_name", "p_kw")

MEAS_HEADER = ("idx", "name", "dev_type", "dev_name", "meas_type", "weight", "valid", "value")

DEFAULT_WEATHER: Dict[str, Optional[float]] = {
    "wind_speed_mps": None,
    "air_temp_c": -18.0,
    "air_pressure_hpa": 960.0,
    "solar_irradiance_w_m2": None,
    "humidity_pct": 72.0,
    "load_kw": 100.0,
}
UNKNOWN_WEATHER_VALUE = "NA"

# A failed remote-adjustment step is retried against the last successful true
# measurement. The requested target remains active; only this calculation's
# movement toward it is reduced until a feasible load-flow boundary is found.
POWER_FLOW_BACKTRACK_FACTORS = (0.5, 0.25, 0.1, 0.0)


@dataclass(frozen=True)
class _MeasurementDefinitionLayout:
    snapshot: DefinitionSnapshot
    rows: Tuple[Dict[str, Any], ...]
    signature: str
    first_index: int
    contiguous: bool
    positions: Mapping[int, int]


class ServiceInstanceRetiredError(RuntimeError):
    """Raised when a request targets a service lifecycle that has been retired."""

WEATHER_MEASUREMENTS = (
    ("wind_speed_mps", "wind_speed", "WIND_SPEED"),
    ("air_temp_c", "air_temp", "AIR_TEMP"),
    ("humidity_pct", "humidity", "HUMIDITY"),
    ("air_pressure_hpa", "air_pressure", "AIR_PRESSURE"),
    ("solar_irradiance_w_m2", "solar_irradiance", "SOLAR_IRRADIANCE"),
)

WEATHER_MEASUREMENT_TYPE_SET = {item[2] for item in WEATHER_MEASUREMENTS}
SIGNAL_MEASUREMENT_TYPES = {"RUN_STAT", "STATUS"}
SIGNAL_MEASUREMENTS = (
    ("RunStat", "run_stat", "RUN_STAT", "run_stat"),
    ("CbOpenStat", "closed_status", "STATUS", "status"),
)
SNAPSHOT_STATIC_FIELDS = (
    "files",
    "source_files",
    "work_files",
    "definitions",
    "curves",
    "settings",
    "device_parameters",
    "diagram",
)

STAT_HEADERS = {
    "RunStat": ("dev_type", "dev_name", "run_stat"),
    "CbOpenStat": (
        "dev_type",
        "dev_name",
        "closed_status_set",
        "closed_status",
        "status",
    ),
    "SetValue": ("dev_type", "dev_name", "set_type", "set_value"),
    "StorageSoc": ("dev_type", "idx", "name", "soc_curr"),
    "HydroStorageState": (
        "dev_type",
        "idx",
        "name",
        "pressure",
        "flow",
        "gas_quantity",
        "soc",
    ),
}
RUNTIME_CONTROL_STATUS_FIELDS = frozenset(
    ("run_stat", "status", "closed_status_set")
)
RUNTIME_CONTROL_SETPOINT_FIELDS = frozenset(
    (
        "p_set",
        "q_set",
        "v_set",
        "i_set",
        "p_ac_set",
        "q_ac_set",
        "v_ac_set",
        "v_dc_set",
        "p_dc_set",
        "q_dc_set",
        "p_from_set",
        "q_from_set",
        "v_from_set",
        "p_to_set",
        "q_to_set",
        "v_to_set",
        "flow_set",
        "heat_power",
    )
)

EXTERNAL_REALTIME_WEATHER_FIELDS = (
    ("wind_speed_mps", "m/s"),
    ("solar_irradiance_w_m2", "W/m2"),
    ("air_temp_c", "degC"),
    ("air_pressure_hpa", "hPa"),
    ("humidity_pct", "%"),
)
EXTERNAL_REALTIME_WEATHER_FIELD_SET = {item[0] for item in EXTERNAL_REALTIME_WEATHER_FIELDS}
EXTERNAL_CURVE_ENVIRONMENT_SPECS = {
    "wind_speed_mps": "m/s",
    "solar_irradiance_w_m2": "W/m2",
    "air_temp_c": "℃",
}
RUNTIME_CONTROL_SETPOINT_ALIASES = {
    ("ACLoad", "pv0"): "p_set",
    ("ACLoad", "qv0"): "q_set",
    ("DCLoad", "pv0"): "p_set",
    ("DCLoad", "qv0"): "q_set",
}
DEFINITION_DEFAULTS_FILE = "definition_defaults.json"
SOURCE_DEFINITION_FILES = (
    "model.e",
    "meas.e",
    "stat.e",
    "control.e",
    "weather.e",
    "curves.e",
    DEFINITION_DEFAULTS_FILE,
)
LEGACY_RUNTIME_DEFINITION_FILES = SOURCE_DEFINITION_FILES + ("device.e",)
DIAGRAM_FILE_NAME = "diagram.svg"
MANUAL_DEFINITION_CHANGES_FILE = "manual_overrides.json"
CONTROL_DEFINITION_BLOCKS = ("RunStat", "CbOpenStat", "SetValue", "StorageSoc")
CLOCK_SPEED_LEVELS = (1.0, 5.0, 15.0, 30.0, 60.0, 300.0, 900.0, 1800.0, 3600.0)
SIMULATION_MODE_CONFIGS: Dict[str, Dict[str, float | int | str]] = {
    "hour": {
        "label": "时仿真",
        "duration_minutes": 60.0,
        "time_step_minutes": 1.0 / 60.0,
        "point_count": 3600,
        "default_clock_speed": 1.0,
        "day_count": 1,
    },
    "day": {
        "label": "日仿真",
        "duration_minutes": 24.0 * 60.0,
        "time_step_minutes": 1.0,
        "point_count": 1440,
        "default_clock_speed": 60.0,
        "day_count": 1,
    },
    "week": {
        "label": "周仿真",
        "duration_minutes": 7.0 * 24.0 * 60.0,
        "time_step_minutes": 1.0,
        "point_count": 7 * 1440,
        "default_clock_speed": 60.0,
        "day_count": 7,
    },
    "month": {
        "label": "月仿真",
        "duration_minutes": 30.0 * 24.0 * 60.0,
        "time_step_minutes": 60.0,
        "point_count": 30 * 24,
        "default_clock_speed": 3600.0,
        "day_count": 30,
    },
    "year": {
        "label": "年仿真",
        "duration_minutes": 365.0 * 24.0 * 60.0,
        "time_step_minutes": 60.0,
        "point_count": 365 * 24,
        "default_clock_speed": 3600.0,
        "day_count": 365,
    },
}
DEFAULT_CONTROL_VALID_MINUTES = 120.0
COMMAND_HISTORY_RECENT_LIMIT = 200
COMMAND_HISTORY_MEMORY_LIMIT = 1000
RUNTIME_LOG_HISTORY_LIMIT = 500
RUNTIME_LOG_JOURNAL_ENTRY_LIMIT = 256
RUNTIME_LOG_JOURNAL_BYTE_LIMIT = 256 * 1024
DEFAULT_COMPUTE_INTERVAL_SECONDS = 1.0
DEFAULT_STORAGE_INITIAL_SOC = 0.5
DEFAULT_REMOTE_ADJUSTMENT_RESPONSE_RATIO = 0.7
LOG_DECIMAL_PATTERN = re.compile(r"(?<![\w:])[-+]?\d+\.\d+(?:e[-+]?\d+)?(?![\w:])", re.IGNORECASE)


@dataclass
class ClockState:
    state: str = "stopped"
    minute: float = 0.0
    absolute_minute: float = 0.0
    speed: float = 1.0
    step_minutes: float = 1.0 / 60.0
    run_id: int = 0
    step_count: int = 0
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        def clock_number(value: int | float) -> int | float:
            rounded = round(float(value), 9)
            return int(rounded) if rounded.is_integer() else rounded

        effective_step_minutes = _effective_clock_step(self.step_minutes, self.speed)
        return {
            "state": self.state,
            "minute": clock_number(self.minute),
            "absolute_minute": clock_number(self.absolute_minute),
            "second": clock_number(self.minute * 60.0),
            "absolute_second": clock_number(self.absolute_minute * 60.0),
            "speed": self.speed,
            "step_minutes": clock_number(self.step_minutes),
            "step_seconds": clock_number(self.step_minutes * 60.0),
            "effective_step_minutes": clock_number(effective_step_minutes),
            "effective_step_seconds": clock_number(effective_step_minutes * 60.0),
            "run_id": self.run_id,
            "step_count": self.step_count,
            "time": minute_to_time(self.minute),
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class SimulationModelSpec:
    """Input model definition for one independent simulation instance."""

    model_id: str
    sim_dir: str | Path
    name: str = ""

    def normalized(self) -> "SimulationModelSpec":
        model_id = _safe_model_id(self.model_id)
        return SimulationModelSpec(model_id=model_id, sim_dir=Path(self.sim_dir).resolve(), name=self.name or model_id)


def minute_to_time(minute: int | float) -> str:
    total_seconds = int(round((float(minute) % 1440.0) * 60.0))
    hour = (total_seconds // 3600) % 24
    minute_part = (total_seconds // 60) % 60
    second = total_seconds % 60
    return f"{hour:02d}:{minute_part:02d}:{second:02d}"


def _align_minute_to_step(minute: int | float, step_minutes: int | float) -> float:
    step = max(1e-9, float(step_minutes))
    value = max(0.0, float(minute))
    quotient = math.ceil((value - 1e-9) / step)
    return round(max(0.0, quotient * step), 9)


def _effective_clock_step(step_minutes: int | float, speed: int | float) -> float:
    return max(1e-9, float(step_minutes) * float(speed))


def _normalize_simulation_mode(value: Any, fallback: str = "day") -> str:
    mode = str(value or fallback).strip().lower()
    if mode in SIMULATION_MODE_CONFIGS:
        return mode
    return fallback if fallback in SIMULATION_MODE_CONFIGS else "day"


def _simulation_mode_config(value: Any) -> Mapping[str, float | int | str]:
    return SIMULATION_MODE_CONFIGS[_normalize_simulation_mode(value)]


def _simulation_mode_duration_minutes(value: Any) -> float:
    return float(_simulation_mode_config(value)["duration_minutes"])


def _simulation_mode_curve_step_minutes(value: Any) -> float:
    return float(_simulation_mode_config(value)["time_step_minutes"])


def _simulation_mode_point_count(value: Any) -> int:
    return int(_simulation_mode_config(value)["point_count"])


def _simulation_mode_default_clock_speed(value: Any) -> float:
    return float(_simulation_mode_config(value)["default_clock_speed"])


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_scalar(value: Any) -> Any:
    if value in (None, ""):
        return value
    if isinstance(value, (int, float, bool)):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number.is_integer():
        return int(number)
    return number


def _nearest_clock_speed(value: Any) -> float:
    speed = _to_float(value, CLOCK_SPEED_LEVELS[0])
    if speed is None:
        return CLOCK_SPEED_LEVELS[0]
    return min(CLOCK_SPEED_LEVELS, key=lambda level: (abs(level - speed), level))


def _compute_interval_seconds(value: Any, default: float = DEFAULT_COMPUTE_INTERVAL_SECONDS) -> float:
    interval = _to_float(value, default)
    if interval is None or not math.isfinite(interval):
        interval = default
    return min(3600.0, max(0.1, float(interval)))


def _storage_initial_soc(value: Any, default: float = DEFAULT_STORAGE_INITIAL_SOC) -> float:
    try:
        soc = ratio_parameter_number(
            "state_of_charge",
            value,
            legacy_percent_points=True,
        )
    except (TypeError, ValueError):
        soc = default
    if not math.isfinite(soc):
        soc = default
    return min(1.0, max(0.0, float(soc)))


def _remote_adjustment_response_ratio(
    value: Any,
    default: float = DEFAULT_REMOTE_ADJUSTMENT_RESPONSE_RATIO,
) -> float:
    ratio = _to_float(value, default)
    if ratio is None or not math.isfinite(ratio):
        ratio = default
    return min(1.0, max(0.01, float(ratio)))


def _next_clock_speed(value: Any) -> float:
    speed = _to_float(value, CLOCK_SPEED_LEVELS[0]) or CLOCK_SPEED_LEVELS[0]
    for level in CLOCK_SPEED_LEVELS:
        if level > speed:
            return level
    return CLOCK_SPEED_LEVELS[-1]


def _previous_clock_speed(value: Any) -> float:
    speed = _to_float(value, CLOCK_SPEED_LEVELS[0]) or CLOCK_SPEED_LEVELS[0]
    for level in reversed(CLOCK_SPEED_LEVELS):
        if level < speed:
            return level
    return CLOCK_SPEED_LEVELS[0]


def _number_text(value: Any) -> str:
    number = _to_float(value, None)
    if number is None:
        return "" if value is None else str(value)
    return format_number(number)


def _value_with_unit(value: Any, unit: str) -> str:
    text = _number_text(value)
    return f"{text} {unit}" if text else "未知"


def format_number(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        return str(number)
    if abs(number) < 5e-13:
        number = 0.0
    text = f"{number:.10g}"
    return "0" if text == "-0" else text


def _format_log_number(value: Any, *, scientific: bool = False) -> str:
    number = _to_float(value, None)
    if number is None or not math.isfinite(number):
        return "" if value is None else str(value)
    if scientific:
        return re.sub(r"e([+-])0+(\d+)$", r"e\1\2", f"{number:.2e}")
    if abs(number) < 0.005:
        number = 0.0
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _format_log_text_numbers(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        return _format_log_number(token, scientific="e" in token.casefold())

    return LOG_DECIMAL_PATTERN.sub(repl, text)


def _format_log_detail(detail: Any) -> Any:
    if isinstance(detail, str):
        return _format_log_text_numbers(detail)
    if isinstance(detail, bool) or detail is None:
        return detail
    if isinstance(detail, (int, float)):
        return _format_log_number(detail)
    if isinstance(detail, list):
        return [_format_log_detail(item) for item in detail]
    if isinstance(detail, tuple):
        return [_format_log_detail(item) for item in detail]
    if (type(detail) is dict or isinstance(detail, Mapping)):
        return {key: _format_log_detail(value) for key, value in detail.items()}
    return detail


def parse_measurement_rows(meas_file: Path) -> Tuple[List[str], List[List[str]], List[str]]:
    before: List[str] = []
    rows: List[List[str]] = []
    after: List[str] = []
    in_measurement = False
    seen_measurement = False
    with meas_file.open("rt", encoding="utf-8") as fp:
        for raw_line in fp:
            line = raw_line.strip()
            if line == "<Measurement>":
                in_measurement = True
                seen_measurement = True
                continue
            if line == "</Measurement>":
                in_measurement = False
                continue
            if not in_measurement:
                if not seen_measurement:
                    before.append(raw_line.rstrip("\n"))
                elif line:
                    after.append(raw_line.rstrip("\n"))
                continue
            if not line or line.startswith("@"):
                continue
            if line.startswith("#"):
                parts = line[1:].split()
                if len(parts) != len(MEAS_HEADER):
                    raise RuntimeError(f"Invalid measurement row in {meas_file}: {line}")
                rows.append(parts)
    if not seen_measurement:
        raise RuntimeError(f"{meas_file} does not contain a <Measurement> block")
    return before, rows, after


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any, *, compact: bool = False) -> None:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":") if compact else None,
        indent=None if compact else 2,
    )
    atomic_write_text(path, content)


def _safe_model_id(value: Any) -> str:
    text = str(value or "default").strip()
    cleaned = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in text)
    return cleaned.strip("_") or "default"


def _model_key(value: Any) -> str:
    return _safe_model_id(value).casefold()


def _clear_directory_contents(directory: Path) -> int:
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    removed = 0
    for path in list(root.iterdir()):
        if path.is_symlink():
            path.unlink()
            removed += 1
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Refusing to clear path outside runtime directory: {path}") from exc
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed += 1
    return removed


def _make_book(blocks: Mapping[str, Tuple[Sequence[str], Sequence[Mapping[str, Any]]]]) -> EBook:
    book = EBook({})
    for name, (headers, rows) in blocks.items():
        block = EBlock(name)
        block.header_list = list(headers)
        block.data = [{key: row.get(key, "") for key in headers} for row in rows]
        book.data[name] = block
    return book


def _ensure_block(book: EBook, name: str, headers: Sequence[str]) -> EBlock:
    block = book.data.get(name)
    if block is None:
        block = EBlock(name)
        block.header_list = list(headers)
        block.data = []
        book.data[name] = block
        return block
    for header in headers:
        if header not in block.header_list:
            block.header_list.append(header)
            for row in block.data:
                row[header] = ""
    return block


def _dev_name(row: Mapping[str, Any]) -> str:
    return str(row.get("dev_name", row.get("name", "")))


def _find_dev_row(block: EBlock, dev_type: str, dev_name: str) -> Optional[dict]:
    for row in block.data:
        if str(row.get("dev_type", "")) == str(dev_type) and _dev_name(row) == str(dev_name):
            return row
    return None


def _find_set_row(block: EBlock, dev_type: str, dev_name: str, set_type: str) -> Optional[dict]:
    for row in block.data:
        if (
            str(row.get("dev_type", "")) == str(dev_type)
            and _dev_name(row) == str(dev_name)
            and str(row.get("set_type", "")) == str(set_type)
        ):
            return row
    return None


def _load_book(path: Path) -> EBook:
    return EBook(path) if path.exists() else EBook({})


def ensure_dcac_dcp_control_rows(model_book: EBook, control_book: EBook) -> int:
    converter_block = model_book.data.get("DCACConverter")
    if converter_block is None or "p_dc_set" not in getattr(converter_block, "header_list", []):
        return 0
    set_block = _ensure_block(control_book, "SetValue", STAT_HEADERS["SetValue"])
    added = 0
    for converter in getattr(converter_block, "data", []):
        name = str(converter.get("name", converter.get("dev_name", ""))).strip()
        if not name or "p_dc_set" not in converter:
            continue
        if _find_set_row(set_block, "DCACConverter", name, "p_dc_set") is not None:
            continue
        set_block.data.append(
            {
                "dev_type": "DCACConverter",
                "dev_name": name,
                "set_type": "p_dc_set",
                "set_value": converter.get("p_dc_set", 0),
            }
        )
        added += 1
    return added


def _reconcile_hydrogen_inline_flow_measurements(
    model_book: EBook,
    measurement_rows: Sequence[Sequence[Any]],
) -> Tuple[List[List[str]], int]:
    return simu_loop.reconcile_hydrogen_inline_flow_measurements(
        model_book,
        measurement_rows,
    )


def _active_window(
    item: Mapping[str, Any],
    minute: int | float,
    absolute_minute: Optional[int | float] = None,
    curve_mode: str = "day",
) -> bool:
    mode = _normalize_simulation_mode(curve_mode)
    day_count = int(_simulation_mode_config(mode)["day_count"])
    if mode in ("week", "month", "year"):
        absolute = float(minute if absolute_minute is None else absolute_minute)
        current_day = int(absolute // 1440) % day_count + 1
        start = min(day_count, max(1, int(_to_float(item.get("start_day", 1), 1) or 1)))
        clear_value = item.get("clear_day", item.get("end_day"))
        if clear_value in (None, ""):
            return current_day >= start
        clear = min(day_count, max(1, int(_to_float(clear_value, day_count) or day_count)))
        if start < clear:
            return start <= current_day <= clear
        if start > clear:
            return current_day >= start or current_day <= clear
        return current_day == start

    start = int(_to_float(item.get("start_minute", item.get("start", 0)), 0) or 0) % 1440
    clear_value = item.get("clear_minute", item.get("end_minute", item.get("clear")))
    if clear_value in (None, ""):
        return minute >= start
    clear = int(_to_float(clear_value, 1440) or 1440) % 1440
    if start < clear:
        return start <= minute < clear
    if start > clear:
        return minute >= start or minute < clear
    return True


def _is_trainee_command_source(source: Any) -> bool:
    text = str(source or "").strip().casefold()
    if not text:
        return False
    if "学员" in text:
        return True
    return text in {"student", "trainee"} or text.startswith("student-") or text.startswith("trainee-")


def _is_simulator_command_source(source: Any) -> bool:
    text = str(source or "").strip().casefold()
    if not text:
        return False
    if "模拟台" in text:
        return True
    return text in {"simulator", "teacher"} or text.startswith("simulator-") or text.startswith("teacher-")


def _has_cancel_command_payload(payload: Mapping[str, Any]) -> bool:
    for key in ("cancel_commands", "cancelCommands", "cancel_items", "cancelItems", "cancel_names", "cancelNames"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) > 0:
            return True
    action = str(payload.get("action", payload.get("operation", "")) or "").strip().casefold()
    if action in {
        "cancel_strategy_generation",
        "cancel-strategy-generation",
        "revoke_strategy_generation",
        "revoke-strategy-generation",
    }:
        return True
    if action in {"cancel", "cancel_command", "cancel_commands", "取消", "取消指令"}:
        return True
    return bool(payload.get("cancel") is True and any(key in payload for key in ("name", "names", "commands", "items", "controls")))


def _strategy_generation_metadata(payload: Mapping[str, Any]) -> Tuple[str, Any, bool]:
    strategy = payload.get("strategy")
    strategy_payload = strategy if (type(strategy) is dict or isinstance(strategy, Mapping)) else {}
    strategy_id = str(
        payload.get(
            "strategy_id",
            payload.get(
                "strategyId",
                strategy_payload.get("strategy_id", strategy_payload.get("strategyId", "")),
            ),
        )
        or ""
    ).strip()
    generation = payload.get(
        "generation",
        payload.get(
            "strategy_generation",
            payload.get(
                "strategyGeneration",
                strategy_payload.get(
                    "generation",
                    strategy_payload.get("strategy_generation", strategy_payload.get("strategyGeneration")),
                ),
            ),
        ),
    )
    if generation is not None and not isinstance(generation, (str, int, float)):
        generation = str(generation)
    if isinstance(generation, str):
        generation = generation.strip()
    replace_generation = bool(
        payload.get(
            "replace_strategy_generation",
            payload.get(
                "replaceStrategyGeneration",
                strategy_payload.get(
                    "replace_strategy_generation",
                    strategy_payload.get("replaceStrategyGeneration", False),
                ),
            ),
        )
    )
    return strategy_id, generation, replace_generation


def _strategy_generation_matches(left: Any, right: Any) -> bool:
    if left in (None, "") or right in (None, ""):
        return False
    left_number = _to_float(left, None)
    right_number = _to_float(right, None)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return str(left).strip() == str(right).strip()


def _explicit_command_origin(entry_or_payload: Mapping[str, Any]) -> str:
    payload = entry_or_payload.get("payload") if isinstance(entry_or_payload.get("payload"), Mapping) else entry_or_payload
    for candidate in (entry_or_payload, payload):
        if not (type(candidate) is dict or isinstance(candidate, Mapping)):
            continue
        value = str(
            candidate.get(
                "command_origin",
                candidate.get("commandOrigin", candidate.get("origin", candidate.get("priority", ""))),
            )
            or ""
        ).strip().casefold()
        if value in {"manual", "human", "operator", "人工"}:
            return "manual"
        if value in {"automatic", "auto", "strategy", "自动"}:
            return "automatic"
    return ""


def _manual_command_holds_across_clock_lifecycle(entry_or_payload: Mapping[str, Any], source: Any = "") -> bool:
    payload = entry_or_payload.get("payload") if isinstance(entry_or_payload.get("payload"), Mapping) else entry_or_payload
    text = str(
        source
        or entry_or_payload.get("source", "")
        or (payload.get("source", "") if (type(payload) is dict or isinstance(payload, Mapping)) else "")
        or ""
    ).strip().casefold()
    if ((type(payload) is dict or isinstance(payload, Mapping)) and isinstance(payload.get("strategy"), Mapping)) or "renewable" in text or "strategy" in text:
        return False
    explicit_origin = _explicit_command_origin(entry_or_payload)
    if explicit_origin:
        return explicit_origin == "manual"
    for candidate in (entry_or_payload, payload):
        if not (type(candidate) is dict or isinstance(candidate, Mapping)):
            continue
        if "manual_hold" in candidate:
            return bool(candidate.get("manual_hold"))
        if "hold_until_cancelled" in candidate:
            return bool(candidate.get("hold_until_cancelled"))
    return text in {"trainee-ui", "student-ui"} or text.startswith("trainee-ui-") or text.startswith("student-ui-") or "人工" in text


def _command_origin(entry_or_payload: Mapping[str, Any], source: Any = "") -> str:
    return "manual" if _manual_command_holds_across_clock_lifecycle(entry_or_payload, source) else "automatic"


def _cancel_command_origin_filter(payload: Mapping[str, Any]) -> str:
    value = str(
        payload.get(
            "command_origin",
            payload.get("commandOrigin", payload.get("origin", payload.get("priority", "all"))),
        )
        or "all"
    ).strip().casefold()
    if value in {"manual", "human", "operator", "人工"}:
        return "manual"
    if value in {"automatic", "auto", "strategy", "自动"}:
        return "automatic"
    return "all"


def _first_number(source: Mapping[str, Any], keys: Sequence[str]) -> Optional[float]:
    for key in keys:
        if key not in source:
            continue
        value = _to_float(source.get(key), None)
        if value is not None:
            return value
    return None


def _command_valid_minutes(payload: Mapping[str, Any], item: Optional[Mapping[str, Any]] = None) -> float:
    minute_keys = (
        "valid_for_minutes",
        "valid_minutes",
        "validity_minutes",
        "duration_minutes",
        "ttl_minutes",
    )
    second_keys = ("valid_for_seconds", "valid_seconds", "ttl_seconds", "duration_seconds")
    minute_value = _first_number(item or {}, minute_keys)
    if minute_value is None:
        minute_value = _first_number(payload, minute_keys)
    if minute_value is not None:
        return max(1e-6, minute_value)
    second_value = _first_number(item or {}, second_keys)
    if second_value is None:
        second_value = _first_number(payload, second_keys)
    if second_value is not None:
        return max(1e-6, second_value / 60.0)
    return DEFAULT_CONTROL_VALID_MINUTES


def _command_expires_at(payload: Mapping[str, Any], item: Optional[Mapping[str, Any]], issued_absolute_minute: float) -> float:
    absolute_keys = (
        "expires_at_absolute_minute",
        "expire_absolute_minute",
        "valid_until_absolute_minute",
        "end_absolute_minute",
    )
    day_minute_keys = ("expires_at_minute", "expire_minute", "valid_until_minute", "end_minute")
    absolute = _first_number(item or {}, absolute_keys)
    if absolute is None:
        absolute = _first_number(payload, absolute_keys)
    if absolute is not None and absolute > issued_absolute_minute:
        return absolute
    day_minute = _first_number(item or {}, day_minute_keys)
    if day_minute is None:
        day_minute = _first_number(payload, day_minute_keys)
    if day_minute is not None:
        current_day = issued_absolute_minute % 1440.0
        delta = (day_minute - current_day) % 1440.0
        if delta <= 1e-9:
            delta = 1440.0
        return issued_absolute_minute + delta
    return issued_absolute_minute + _command_valid_minutes(payload, item)


def _has_relative_command_validity(payload: Mapping[str, Any], item: Optional[Mapping[str, Any]] = None) -> bool:
    minute_keys = (
        "valid_for_minutes",
        "valid_minutes",
        "validity_minutes",
        "duration_minutes",
        "ttl_minutes",
    )
    second_keys = ("valid_for_seconds", "valid_seconds", "ttl_seconds", "duration_seconds")
    return (
        _first_number(item or {}, minute_keys) is not None
        or _first_number(payload, minute_keys) is not None
        or _first_number(item or {}, second_keys) is not None
        or _first_number(payload, second_keys) is not None
    )


def _has_stale_absolute_command_expiry(
    payload: Mapping[str, Any],
    issued_absolute_minute: float,
    item: Optional[Mapping[str, Any]] = None,
) -> bool:
    absolute_keys = (
        "expires_at_absolute_minute",
        "expire_absolute_minute",
        "valid_until_absolute_minute",
        "end_absolute_minute",
    )
    absolute = _first_number(item or {}, absolute_keys)
    if absolute is None:
        absolute = _first_number(payload, absolute_keys)
    return absolute is not None and absolute <= issued_absolute_minute


def _sender_command_valid_minutes(payload: Mapping[str, Any], item: Optional[Mapping[str, Any]] = None) -> Optional[float]:
    absolute_keys = (
        "expires_at_absolute_minute",
        "expire_absolute_minute",
        "valid_until_absolute_minute",
        "end_absolute_minute",
    )
    sent_keys = (
        "sent_absolute_minute",
        "trainee_sent_absolute_minute",
        "command_absolute_minute",
        "sender_absolute_minute",
    )
    absolute = _first_number(item or {}, absolute_keys)
    if absolute is None:
        absolute = _first_number(payload, absolute_keys)
    sent = _first_number(item or {}, sent_keys)
    if sent is None:
        sent = _first_number(payload, sent_keys)
    if absolute is None or sent is None:
        return None
    duration = absolute - sent
    return duration if duration > 0 else None


def _normalize_points(points: Any, value_aliases: Sequence[str]) -> List[Dict[str, Any]]:
    if points is None:
        return []
    if (type(points) is dict or isinstance(points, Mapping)):
        minutes = points.get("minute", points.get("minutes", []))
        if not isinstance(minutes, Sequence) or isinstance(minutes, (str, bytes)):
            minutes = []
        normalized: List[Dict[str, Any]] = []
        for idx, minute in enumerate(minutes):
            row: Dict[str, Any] = {"minute": _to_float(minute, 0.0) or 0.0}
            for key, values in points.items():
                if key in ("minute", "minutes"):
                    continue
                if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) and idx < len(values):
                    row[key] = values[idx]
            normalized.append(row)
        if normalized:
            return normalized
        row = {"minute": _to_float(points.get("minute", 0), 0.0) or 0.0}
        for key in value_aliases:
            if key in points:
                row[key] = points[key]
        return [row] if len(row) > 1 else []
    if isinstance(points, Sequence) and not isinstance(points, (str, bytes)):
        normalized = []
        for idx, item in enumerate(points):
            if (type(item) is dict or isinstance(item, Mapping)):
                row = dict(item)
                row["minute"] = _to_float(row.get("minute", idx), float(idx)) or 0.0
                normalized.append(row)
            else:
                normalized.append({"minute": float(idx), value_aliases[0]: item})
        return normalized
    return []


def _interpolate(
    points: Sequence[Mapping[str, Any]],
    minute: int | float,
    key: str,
    default: Optional[float],
    *,
    period_minutes: float = 1440.0,
) -> Optional[float]:
    series = _compile_interpolation_series(points, key, period_minutes)
    return _interpolate_compiled_series(
        series,
        minute,
        default,
        period_minutes=period_minutes,
    )


def _compile_interpolation_series(
    points: Sequence[Mapping[str, Any]],
    key: str,
    period_minutes: float,
) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    pairs: List[Tuple[float, float]] = []
    for point in points:
        value = _to_float(point.get(key), None)
        if value is None:
            continue
        pairs.append((float(point.get("minute", 0)) % period_minutes, value))
    pairs.sort(key=lambda item: item[0])
    return (
        tuple(item[0] for item in pairs),
        tuple(item[1] for item in pairs),
    )


def _interpolate_compiled_series(
    series: Tuple[Sequence[float], Sequence[float]],
    minute: int | float,
    default: Optional[float],
    *,
    period_minutes: float = 1440.0,
) -> Optional[float]:
    minutes, values = series
    if not minutes:
        return default
    m = float(minute % period_minutes)
    if len(minutes) == 1:
        return values[0]
    # Match the legacy linear scan: an exact timestamp, including duplicate
    # timestamps, uses the first point at that timestamp.
    position = bisect_left(minutes, m)
    if position == 0:
        prev_m, prev_v = minutes[-1] - period_minutes, values[-1]
        next_m, next_v = minutes[0], values[0]
    elif position >= len(minutes):
        prev_m, prev_v = minutes[-1], values[-1]
        next_m, next_v = minutes[0] + period_minutes, values[0]
    else:
        prev_m, prev_v = minutes[position - 1], values[position - 1]
        next_m, next_v = minutes[position], values[position]
    span = next_m - prev_m
    if span <= 1e-9:
        return prev_v
    ratio = (m - prev_m) / span
    return prev_v + ratio * (next_v - prev_v)


def _measurement_row_to_dict(row: Sequence[str]) -> Dict[str, Any]:
    item = dict(zip(MEAS_HEADER, row))
    item["idx"] = int(_to_float(item.get("idx"), 0) or 0)
    item["weight"] = _to_float(item.get("weight"), 0.0)
    item["valid"] = int(_to_float(item.get("valid"), 0) or 0)
    item["value"] = _to_float(item.get("value"), 0.0)
    return item


def _normalized_measurement_median_deviation_pairs(
    values: Mapping[str, Any] | Sequence[Sequence[Any]] | None,
) -> Tuple[Tuple[str, float], ...]:
    items = values.items() if (type(values) is dict or isinstance(values, Mapping)) else (values or ())
    normalized: Dict[str, float] = {}
    for raw_name, raw_value in items:
        name = str(raw_name).strip()
        number = _to_float(raw_value, None)
        if not name or number is None or not math.isfinite(number):
            continue
        if number == 0.0:
            normalized.pop(name, None)
        else:
            normalized[name] = float(number)
    return tuple(sorted(normalized.items()))


def _measurement_median_deviation_map(snapshot: DefinitionSnapshot) -> Dict[str, float]:
    return dict(snapshot.measurement_median_deviations)


def _measurement_definition_row_to_dict(
    row: Sequence[str],
    median_deviations: Mapping[str, float],
) -> Dict[str, Any]:
    item = _measurement_row_to_dict(row)
    item["median_deviation"] = float(median_deviations.get(str(item.get("name", "")), 0.0))
    return item


def _measurement_dict_to_row(item: Mapping[str, Any]) -> List[str]:
    return [str(item.get(key, "")) for key in MEAS_HEADER]


def _measurement_status_from_valid(value: Any) -> str:
    try:
        return "valid" if int(_to_float(value, 0) or 0) == 1 else "invalid"
    except (TypeError, ValueError):
        return "invalid"


