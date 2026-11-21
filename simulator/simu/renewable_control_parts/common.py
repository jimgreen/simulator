"""Shared trainee-side renewable-priority control engine.

The browser is only a client of this module.  One controller state is kept per
trainee model so every browser page sees and operates the same algorithm.
"""

from __future__ import annotations

import copy

import json

import math

import re

import threading

import time

from collections import deque

from concurrent.futures import ThreadPoolExecutor

from contextlib import nullcontext

from dataclasses import dataclass, field, replace

from datetime import datetime

from functools import lru_cache

from pathlib import Path

from typing import Any, Callable, ContextManager, Deque, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from simu.device_roles import (
    AC_TO_DC,
    converter_balance_coefficients,
    converter_control_mode,
    converter_power_in_ac_terminal_convention,
    converter_power_in_dc_to_ac_convention,
    converter_power_setpoint_fields,
    converter_setpoint_from_p_ac_convention,
)

from simu.control_config import (
    default_boolean,
    default_derating_curve,
    default_integer,
    default_number,
)

from simu.fuel_cell_control import (
    FuelCellControlDecision,
    FuelCellControlInputs,
    FuelCellControlParameters,
    calculate_fuel_cell_power_decision,
)

from simu.model_semantics import (
    energy_coupling_control_bindings,
    grid_converter_keys as structured_grid_converter_keys,
    model_rows,
)

from simu.renewable_capability import (
    renewable_weather_available_kw as _renewable_weather_available_kw,
)

from simu.renewable_optimization import (
    RenewableDispatchOptimizationResult,
    optimize_topology_islands,
)

from simu.resource_topology import (
    DcTransferGroup,
    ResourceConnection,
    ResourceRef,
    ResourceTopology,
    ResourceTopologyStaticContext,
    prepare_resource_topology_static_context,
    resolve_resource_topology,
)

from simu.trainee_exchange import TraineeControlSnapshot

EPSILON = 1e-9

RENEWABLE_CONTROL_STRATEGY_ID = "renewable_priority"

DEFAULT_TRAINEE_BACKEND_REFRESH_SECONDS = 1.0

MINIMUM_CONTROL_INTERVAL_SECONDS = default_number(
    "minimum_simulation_control_interval_seconds"
)

MINIMUM_COMMAND_VALID_MINUTES = default_number(
    "minimum_command_valid_minutes"
)

MAXIMUM_POWER_PROTECTION_RATIO = default_number(
    "maximum_power_protection_ratio"
)

SIMULATION_DEFAULT_STEP_MINUTES = default_number(
    "simulation_default_step_minutes"
)

SIMULATION_MINIMUM_STEP_MINUTES = default_number(
    "simulation_minimum_step_minutes"
)

def _simulation_control_interval_seconds(value: Any) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("自动控制周期必须为有效的仿真秒数。") from exc
    if (
        not math.isfinite(interval)
        or interval < MINIMUM_CONTROL_INTERVAL_SECONDS
    ):
        raise ValueError(
            "自动控制周期必须不少于 "
            f"{MINIMUM_CONTROL_INTERVAL_SECONDS:g} 仿真秒。"
        )
    return interval

SIMULATION_DEFAULT_SPEED = default_number("simulation_default_speed")

SIMULATION_MINIMUM_SPEED = default_number("simulation_minimum_speed")

STORAGE_MINIMUM_CONTROL_HORIZON_HOURS = default_number(
    "storage_minimum_control_horizon_hours"
)

POWER_CONTROL_MODES = {"P", "PQ", "PV", "PH", "ACP"}

AC_DC_CONVERTER_TYPES = frozenset({"ACDCConverter", "DCACConverter"})

RENEWABLE_PARAMETER_SPECS = (
    ("wind", "ACWindGen", "ACGenerator", "idx_acgenerator"),
    ("wind", "DCWindGen", "DCGenerator", "idx_dcgenerator"),
    ("pv", "ACPVGen", "ACGenerator", "idx_acgenerator"),
    ("pv", "DCPVGen", "DCGenerator", "idx_dcgenerator"),
)

STORAGE_PARAMETER_SPECS = (
    ("ACStorageGen", "ACGenerator", "idx_acgenerator"),
    ("DCStorageGen", "DCGenerator", "idx_dcgenerator"),
)

GRID_FOLLOWING_STORAGE_MODES = {"P", "PQ"}

BALANCE_STORAGE_MODES = {"SLACK", "V", "VF", "V/F", "PH"}

RENEWABLE_CONTROL_STATE_FILE = "renewable_control.json"

RENEWABLE_CONTROL_TREND_FILE = "renewable_control_trend.jsonl"

DEFAULT_STORAGE_CHARGE_DERATING_CURVE = default_derating_curve(
    "storage_charge_derating_curve"
)

DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE = default_derating_curve(
    "storage_discharge_derating_curve"
)

DEFAULT_GRID_FOLLOWING_STORAGE_STEP_RATIO = default_number(
    "grid_following_storage_step_ratio"
)

CYCLE_PERFORMANCE_HISTORY_LIMIT = 120

def _performance_percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * min(1.0, max(0.0, float(percentile)))
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = position - lower_index
    return ordered[lower_index] + (
        ordered[upper_index] - ordered[lower_index]
    ) * fraction

class _CyclePerformanceWindow:
    """Bounded completed-cycle timings used by the trainee diagnostics UI."""

    def __init__(self, limit: int = CYCLE_PERFORMANCE_HISTORY_LIMIT) -> None:
        self.limit = max(1, int(limit))
        self.samples: Deque[Dict[str, Any]] = deque(maxlen=self.limit)
        self.revision = 0

    def record(self, sample: Mapping[str, Any]) -> None:
        self.samples.append(_json_safe_copy(dict(sample)))
        self.revision += 1

    def payload(self) -> Dict[str, Any]:
        samples = list(self.samples)
        latest = copy.deepcopy(samples[-1]) if samples else None
        phase_names = sorted(
            {
                str(name)
                for sample in samples
                for name in (
                    sample.get("phasesMs", {}).keys()
                    if isinstance(sample.get("phasesMs"), Mapping)
                    else ()
                )
            }
        )
        phase_stats: Dict[str, Dict[str, Any]] = {}
        for name in phase_names:
            values = [
                float(value)
                for sample in samples
                for value in [
                    sample.get("phasesMs", {}).get(name)
                    if isinstance(sample.get("phasesMs"), Mapping)
                    else None
                ]
                if isinstance(value, (int, float)) and math.isfinite(float(value))
            ]
            if not values:
                continue
            phase_stats[name] = {
                "sampleCount": len(values),
                "latestMs": values[-1],
                "p50Ms": _performance_percentile(values, 0.50),
                "p95Ms": _performance_percentile(values, 0.95),
                "maxMs": max(values),
            }
        return {
            "historyLimit": self.limit,
            "sampleCount": len(samples),
            "latest": latest,
            "phaseStats": phase_stats,
        }

def _now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")

def _number(value: Any, default: Optional[float] = None) -> Optional[float]:
    value_type = type(value)
    if value_type is float:
        return value if math.isfinite(value) else default
    if value_type is int:
        return float(value)
    if value is None:
        return default
    if value_type is str:
        stripped = value.strip()
        if not stripped:
            return default
        try:
            number = float(stripped)
            return number if math.isfinite(number) else default
        except ValueError:
            pass
    elif str(value).strip() == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        match = re.search(r"[-+]?\d*\.?\d+(?:e[-+]?\d+)?", str(value).replace(",", ""), re.I)
        if not match:
            return default
        try:
            number = float(match.group(0))
        except ValueError:
            return default
    return number if math.isfinite(number) else default

def _finite_number(value: Any, default: float = 0.0) -> float:
    value_type = type(value)
    if value_type is float:
        return value if math.isfinite(value) else default
    if value_type is int:
        return float(value)
    number = _number(value)
    return number if number is not None else default

def _boolean(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    number = _number(value)
    if number is not None:
        return number != 0.0
    normalized = str(value or "").strip().lower()
    if normalized in {"true", "yes", "on", "enabled"}:
        return True
    if normalized in {"false", "no", "off", "disabled", ""}:
        return False
    return default

def _sum_known(values: Iterable[Any]) -> Optional[float]:
    numbers = [_number(value) for value in values]
    if any(number is None for number in numbers):
        return None
    return sum(number for number in numbers if number is not None)

def _converter_direction(row: Mapping[str, Any]) -> str:
    del row
    return AC_TO_DC

def _is_grid_converter_row(row: Mapping[str, Any]) -> bool:
    return (
        str(row.get("converterRole", "")).strip().lower() == "grid"
        and str(row.get("converterDirection", "")).strip().upper() == AC_TO_DC
    )

def _converter_ac_balance_coefficient(row: Mapping[str, Any]) -> float:
    ac_coefficient, _dc_coefficient = converter_balance_coefficients(
        _converter_direction(row)
    )
    return ac_coefficient

def _converter_ac_injection_kw(row: Mapping[str, Any], power_kw: Any) -> float:
    """Convert declared converter power into AC-side signed injection."""
    return _converter_ac_balance_coefficient(row) * _finite_number(power_kw)

def _converter_system_power_kw(
    row: Mapping[str, Any],
    power_kw: Any,
) -> Optional[float]:
    """Convert the planner's internal P_AC value to the system P_DC convention."""
    number = _number(power_kw)
    if number is None:
        return None
    return converter_power_in_dc_to_ac_convention(
        number,
        _converter_direction(row),
        "P_AC",
    )

def _converter_power_from_ac_injection_kw(
    row: Mapping[str, Any],
    ac_injection_kw: Any,
) -> float:
    coefficient = _converter_ac_balance_coefficient(row)
    return _finite_number(ac_injection_kw) / coefficient

def _converter_ac_injection_delta_kw(
    row: Mapping[str, Any],
    current_kw: Any,
    target_kw: Any,
) -> float:
    """Return the AC-side injection change using the row's declared direction."""
    return _converter_ac_balance_coefficient(row) * (
        _finite_number(target_kw) - _finite_number(current_kw)
    )

def _positive(values: Iterable[Any], default: float = 0.0) -> float:
    for value in values:
        number = _number(value)
        if number is not None and number > 0:
            return number
    return default

def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))

def _ratio(value: Any, default: Optional[float]) -> Optional[float]:
    number = _number(value)
    if number is None:
        return default
    if number > 1:
        number /= 100.0
    return _clamp(number, 0.0, 1.0)

def _storage_efficiency(parameter: Mapping[str, Any]) -> float:
    efficiency = _number(parameter.get("charge_discharge_efficiency"))
    return efficiency if efficiency is not None and efficiency > EPSILON else 1.0

def _live_soc_ratio(value: Any, default: Optional[float] = None) -> Optional[float]:
    number = _number(value)
    if number is None:
        return default
    if isinstance(value, str) and "%" in value:
        return number / 100.0
    return number

def _derating_curve_point(value: Any) -> Optional[Tuple[float, float]]:
    if (type(value) is dict or isinstance(value, Mapping)):
        soc_value = value.get("soc", value.get("socRatio", value.get("soc_ratio")))
        power_value = value.get(
            "powerRatio",
            value.get("power_ratio", value.get("ratio", value.get("power"))),
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 2:
        soc_value, power_value = value[0], value[1]
    else:
        return None
    soc = _ratio(soc_value, None)
    power_ratio = _ratio(power_value, None)
    if soc is None or power_ratio is None:
        return None
    return soc, power_ratio

def _normalized_derating_curve(
    value: Any,
    fallback: Tuple[Tuple[float, float], ...],
    *,
    increasing: bool,
) -> Tuple[Tuple[float, float], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return fallback
    parsed = [point for item in value if (point := _derating_curve_point(item)) is not None]
    if len(parsed) < 2:
        return fallback
    deduplicated: Dict[float, float] = {}
    for soc, power_ratio in parsed:
        deduplicated[soc] = power_ratio
    ordered = sorted(deduplicated.items())
    if len(ordered) < 2:
        return fallback
    normalized: List[Tuple[float, float]] = []
    previous = 0.0 if increasing else 1.0
    for soc, power_ratio in ordered:
        monotonic_ratio = max(previous, power_ratio) if increasing else min(previous, power_ratio)
        normalized.append((soc, monotonic_ratio))
        previous = monotonic_ratio
    return tuple(normalized)

def _derating_factor(soc: float, curve: Sequence[Tuple[float, float]]) -> float:
    if not curve:
        return 1.0
    if soc <= curve[0][0] + EPSILON:
        return _clamp(float(curve[0][1]), 0.0, 1.0)
    if soc >= curve[-1][0] - EPSILON:
        return _clamp(float(curve[-1][1]), 0.0, 1.0)
    for (lower_soc, lower_ratio), (upper_soc, upper_ratio) in zip(curve, curve[1:]):
        if soc > upper_soc + EPSILON:
            continue
        width = upper_soc - lower_soc
        if width <= EPSILON:
            return _clamp(float(upper_ratio), 0.0, 1.0)
        fraction = _clamp((soc - lower_soc) / width, 0.0, 1.0)
        return _clamp(lower_ratio + (upper_ratio - lower_ratio) * fraction, 0.0, 1.0)
    return _clamp(float(curve[-1][1]), 0.0, 1.0)

def _derating_curve_payload(curve: Sequence[Tuple[float, float]]) -> List[Dict[str, float]]:
    return [{"soc": soc, "powerRatio": power_ratio} for soc, power_ratio in curve]

def _derating_curve_text(curve: Sequence[Tuple[float, float]]) -> str:
    return "、".join(f"{soc * 100:.1f}%:{power_ratio * 100:.1f}%" for soc, power_ratio in curve)

def _command_number(value: float) -> float:
    normalized = 0.0 if abs(value) < 0.0005 else value
    return round(normalized, 3)

def _dispatch_setpoint_value(row: Mapping[str, Any]) -> float:
    """Return a field-specific command from the planner's P_AC target."""
    value = float(row["commandKw"])
    direction = str(row.get("converterDirection", "")).strip().upper()
    if not direction:
        return value
    return converter_setpoint_from_p_ac_convention(
        value,
        direction,
        row.get("set_type", "p_ac_set"),
    )

def _deduplicate_dispatch_commands(
    commands: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    ordered_keys: List[Tuple[str, str, str]] = []
    selected: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    values_by_key: Dict[Tuple[str, str, str], List[float]] = {}
    for row in commands:
        key = (
            str(row.get("dev_type", "")),
            str(row.get("dev_name", "")),
            str(row.get("set_type", "")),
        )
        value = _number(row.get("set_value"))
        if not all(key) or value is None or not math.isfinite(value):
            continue
        if key not in selected:
            ordered_keys.append(key)
        selected[key] = {
            "dev_type": key[0],
            "dev_name": key[1],
            "set_type": key[2],
            "set_value": _command_number(value),
        }
        values_by_key.setdefault(key, []).append(value)

    duplicates = [
        {
            "dev_type": key[0],
            "dev_name": key[1],
            "set_type": key[2],
            "duplicateCount": len(values),
            "candidateValues": [_command_number(value) for value in values],
            "selectedValue": selected[key]["set_value"],
            "conflict": any(
                abs(value - values[-1]) > EPSILON for value in values[:-1]
            ),
        }
        for key, values in values_by_key.items()
        if len(values) > 1
    ]
    return [selected[key] for key in ordered_keys], duplicates

def _device_type(device: Mapping[str, Any]) -> str:
    return str(device.get("dev_type", device.get("type", "")))

def _device_model_block(device: Mapping[str, Any]) -> str:
    return str(device.get("model_block", "")).strip()

def _device_name(device: Mapping[str, Any]) -> str:
    return str(device.get("dev_name", device.get("name", "")))

def _device_index(device: Mapping[str, Any]) -> str:
    raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
    return str(device.get("idx", raw.get("idx", ""))).strip()

def _device_key(device: Mapping[str, Any]) -> Tuple[str, str]:
    return _device_type(device), _device_name(device)

def _device_model_key(device: Mapping[str, Any]) -> Tuple[str, str]:
    return _device_model_block(device), _device_name(device)

def _parameter_rows(snapshot: Mapping[str, Any], block_name: str) -> List[Mapping[str, Any]]:
    parameters = snapshot.get("device_parameters")
    wanted = block_name.lower()
    if (type(parameters) is dict or isinstance(parameters, Mapping)):
        for name, rows in parameters.items():
            if str(name).lower() == wanted and isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
                return [row for row in rows if (type(row) is dict or isinstance(row, Mapping))]

    definitions = snapshot.get("definitions")
    if not (type(definitions) is dict or isinstance(definitions, Mapping)):
        return []
    for section_name in ("device", "model"):
        section = definitions.get(section_name)
        if not (type(section) is dict or isinstance(section, Mapping)):
            continue
        for name, block in section.items():
            if str(name).lower() != wanted:
                continue
            rows = block.get("rows") if (type(block) is dict or isinstance(block, Mapping)) else block
            if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
                return [row for row in rows if (type(row) is dict or isinstance(row, Mapping))]
    return []

def _parameter_name(row: Mapping[str, Any]) -> str:
    return str(row.get("name", row.get("dev_name", "")))

def _build_indexed_device_lookup(
    snapshot: Mapping[str, Any],
) -> Tuple[
    Dict[Tuple[str, str], List[Mapping[str, Any]]],
    Dict[Tuple[str, str], List[Mapping[str, Any]]],
]:
    """一次构建 (model_block, idx) 查表索引，将关联资源匹配从 O(N*M) 降至 O(N+M)。"""
    runtime_by_key: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for device in snapshot.get("devices", []) or []:
        if not (type(device) is dict or isinstance(device, Mapping)):
            continue
        idx = _device_index(device)
        if not idx:
            continue
        runtime_by_key.setdefault((_device_model_block(device), idx), []).append(device)

    model_by_key: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    definitions = snapshot.get("definitions")
    model = definitions.get("model") if (type(definitions) is dict or isinstance(definitions, Mapping)) else None
    if type(model) is dict or isinstance(model, Mapping):
        for dev_type, block in model.items():
            rows = block.get("rows") if (type(block) is dict or isinstance(block, Mapping)) else block
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                continue
            dev_type_text = str(dev_type)
            for row in rows:
                if not (type(row) is dict or isinstance(row, Mapping)):
                    continue
                idx = str(row.get("idx", "")).strip()
                if idx:
                    model_by_key.setdefault((dev_type_text, idx), []).append(row)
    return runtime_by_key, model_by_key


def _indexed_device_matches(
    snapshot: Mapping[str, Any],
    dev_type: str,
    index: Any,
    *,
    lookup: Optional[
        Tuple[
            Dict[Tuple[str, str], List[Mapping[str, Any]]],
            Dict[Tuple[str, str], List[Mapping[str, Any]]],
        ]
    ] = None,
) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]:
    target = str(index if index is not None else "").strip()
    if not target:
        return [], []
    if lookup is not None:
        runtime_by_key, model_by_key = lookup
        key = (dev_type, target)
        return runtime_by_key.get(key, []), model_by_key.get(key, [])
    runtime_matches = [
        device
        for device in snapshot.get("devices", []) or []
        if (type(device) is dict or isinstance(device, Mapping))
        and _device_model_block(device) == dev_type
        and _device_index(device) == target
    ]
    definitions = snapshot.get("definitions")
    model = definitions.get("model") if (type(definitions) is dict or isinstance(definitions, Mapping)) else None
    block = model.get(dev_type) if (type(model) is dict or isinstance(model, Mapping)) else None
    rows = block.get("rows") if (type(block) is dict or isinstance(block, Mapping)) else block
    model_matches = [
        row
        for row in rows
        if (type(row) is dict or isinstance(row, Mapping)) and str(row.get("idx", "")).strip() == target
    ] if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)) else []
    return runtime_matches, model_matches

def _device_map(snapshot: Mapping[str, Any]) -> Dict[Tuple[str, str], Mapping[str, Any]]:
    return {
        _device_key(device): device
        for device in snapshot.get("devices", []) or []
        if (type(device) is dict or isinstance(device, Mapping))
    }

def _duplicate_typed_identities(
    snapshot: Mapping[str, Any],
) -> Dict[Tuple[str, str], str]:
    runtime_counts: Dict[Tuple[str, str], int] = {}
    for device in snapshot.get("devices", []) or []:
        if not (type(device) is dict or isinstance(device, Mapping)):
            continue
        key = _device_key(device)
        if all(key):
            runtime_counts[key] = runtime_counts.get(key, 0) + 1

    model_counts: Dict[Tuple[str, str], int] = {}
    definitions = snapshot.get("definitions")
    model = definitions.get("model") if (type(definitions) is dict or isinstance(definitions, Mapping)) else None
    if (type(model) is dict or isinstance(model, Mapping)):
        for dev_type, block in model.items():
            rows = block.get("rows") if (type(block) is dict or isinstance(block, Mapping)) else block
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                continue
            for row in rows:
                if not (type(row) is dict or isinstance(row, Mapping)):
                    continue
                dev_name = str(row.get("name", row.get("dev_name", ""))).strip()
                key = (str(dev_type), dev_name)
                if all(key):
                    model_counts[key] = model_counts.get(key, 0) + 1

    diagnostics: Dict[Tuple[str, str], str] = {}
    for key in runtime_counts.keys() | model_counts.keys():
        reasons = []
        if runtime_counts.get(key, 0) > 1:
            reasons.append(f"运行设备列表存在{runtime_counts[key]}个同身份设备")
        if model_counts.get(key, 0) > 1:
            reasons.append(f"definitions.model存在{model_counts[key]}个同身份模型行")
        if reasons:
            diagnostics[key] = (
                f"资源{key[0]}.{key[1]}设备身份重复（{'；'.join(reasons)}），"
                "自动命令地址不唯一，本轮仅保留诊断"
            )
    return diagnostics

def _device_state_rows(snapshot: Mapping[str, Any], dev_type: str) -> List[Mapping[str, Any]]:
    return [
        row
        for row in snapshot.get("device_states", []) or []
        if (type(row) is dict or isinstance(row, Mapping)) and _device_model_block(row) == dev_type
    ]

@dataclass(frozen=True)
class _LinkedResourceSpec:
    technology: str
    parameter_block: str
    parameter: Mapping[str, Any]
    device: Mapping[str, Any]
    identity_diagnostic: str = ""

    @property
    def dev_type(self) -> str:
        return _device_type(self.device)

    @property
    def model_block(self) -> str:
        return _device_model_block(self.device)

    @property
    def dev_name(self) -> str:
        return _device_name(self.device)

    @property
    def topology_key(self) -> Tuple[str, str]:
        return self.model_block, self.dev_name

def _linked_resource_specs(
    snapshot: Mapping[str, Any],
    quality: "_Quality",
    identity_diagnostics: Optional[Mapping[Tuple[str, str], str]] = None,
) -> Tuple[List[_LinkedResourceSpec], List[_LinkedResourceSpec], List[ResourceRef]]:
    renewable_specs: List[_LinkedResourceSpec] = []
    storage_specs: List[_LinkedResourceSpec] = []
    linked_keys: set[Tuple[str, str]] = set()
    if identity_diagnostics is None:
        identity_diagnostics = _duplicate_typed_identities(snapshot)
    device_lookup = _build_indexed_device_lookup(snapshot)

    def indexed_device(
        block_name: str,
        position: int,
        dev_type: str,
        index_name: str,
        index_value: Any,
    ) -> Optional[Mapping[str, Any]]:
        runtime_matches, model_matches = _indexed_device_matches(
            snapshot,
            dev_type,
            index_value,
            lookup=device_lookup,
        )
        index_text = str(
            index_value if index_value is not None else ""
        ).strip() or "--"
        if not runtime_matches:
            quality.add(
                f"{block_name}参数行{position}引用的{dev_type}.{index_name}="
                f"{index_text}不存在，已忽略"
            )
            return None
        if len(runtime_matches) > 1 or len(model_matches) > 1:
            candidate_names = sorted(
                {
                    *(_device_name(device) for device in runtime_matches),
                    *(
                        str(row.get("name", row.get("dev_name", ""))).strip()
                        for row in model_matches
                    ),
                }
                - {""},
                key=lambda name: _natural_topology_identity(name),
            )
            source_counts = []
            if len(runtime_matches) > 1:
                source_counts.append(f"运行设备{len(runtime_matches)}行")
            if len(model_matches) > 1:
                source_counts.append(f"模型{len(model_matches)}行")
            candidates_text = "、".join(
                f"{dev_type}.{name}" for name in candidate_names
            ) or "--"
            quality.add(
                f"{block_name}参数行{position}引用的{dev_type}.{index_name}="
                f"{index_text}匹配到多个候选（{'、'.join(source_counts)}："
                f"{candidates_text}），引用歧义，已忽略"
            )
            return None
        return runtime_matches[0]

    def add_spec(
        technology: str,
        parameter_block: str,
        parameter: Mapping[str, Any],
        device: Mapping[str, Any],
    ) -> None:
        key = _device_key(device)
        if key in linked_keys:
            quality.add(
                f"资源{key[0]}.{key[1]}被多个技术参数行重复引用，保留首个有效引用"
            )
            return
        linked_keys.add(key)
        spec = _LinkedResourceSpec(
            technology=technology,
            parameter_block=parameter_block,
            parameter=parameter,
            device=device,
            identity_diagnostic=identity_diagnostics.get(key, ""),
        )
        if spec.identity_diagnostic:
            quality.add(spec.identity_diagnostic)
        (storage_specs if technology == "storage" else renewable_specs).append(spec)

    for technology, block_name, dev_type, index_name in RENEWABLE_PARAMETER_SPECS:
        for position, parameter in enumerate(_parameter_rows(snapshot, block_name), start=1):
            index_value = parameter.get(index_name)
            device = indexed_device(
                block_name,
                position,
                dev_type,
                index_name,
                index_value,
            )
            if device is None:
                continue
            add_spec(technology, block_name, parameter, device)

    for block_name, dev_type, index_name in STORAGE_PARAMETER_SPECS:
        for position, parameter in enumerate(_parameter_rows(snapshot, block_name), start=1):
            index_value = parameter.get(index_name)
            device = indexed_device(
                block_name,
                position,
                dev_type,
                index_name,
                index_value,
            )
            if device is None:
                continue
            add_spec("storage", block_name, parameter, device)

    refs = [
        ResourceRef(spec.technology, spec.model_block, spec.dev_name)
        for spec in (*renewable_specs, *storage_specs)
    ]
    return renewable_specs, storage_specs, refs

@dataclass(frozen=True)
class MeasurementValue:
    value: float
    source: str
    row: Mapping[str, Any]

def _measurement_index(snapshot: Mapping[str, Any]) -> Dict[Tuple[str, str, str], MeasurementValue]:
    measurements = snapshot.get("measurements")
    if not (type(measurements) is dict or isinstance(measurements, Mapping)):
        return {}
    index: Dict[Tuple[str, str, str], MeasurementValue] = {}
    for source in ("scada", "real"):
        rows = measurements.get(source)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            continue
        is_fallback_source = source != "scada"
        for row in rows:
            if not (type(row) is dict or isinstance(row, Mapping)):
                continue
            key = (
                str(row.get("dev_type", "")),
                str(row.get("dev_name", "")),
                str(row.get("meas_type", "")).upper(),
            )
            if is_fallback_source and key in index:
                continue
            raw_valid = row.get("valid", 1)
            if raw_valid != 1 and int(_number(raw_valid, 1.0) or 0) != 1:
                continue
            value = _number(row.get("value"))
            if value is None:
                continue
            if key not in index:
                index[key] = MeasurementValue(value=value, source=source, row=row)
    return index

def _measured(
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    dev_type: str,
    dev_name: str,
    meas_types: Sequence[str],
) -> Optional[MeasurementValue]:
    for meas_type in meas_types:
        found = measurements.get((dev_type, dev_name, meas_type.upper()))
        if found is not None:
            return found
    return None

def _is_online(
    device: Optional[Mapping[str, Any]],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
) -> bool:
    if not device:
        return False
    run_measurement = _measured(measurements, _device_type(device), _device_name(device), ("RUN_STAT",))
    run_stat = run_measurement.value if run_measurement else _number(device.get("run_stat"), 1.0)
    status = _number(device.get("status"), 1.0)
    return int(run_stat or 0) == 1 and int(status or 0) != 0

def _raw_control_definition_rows(
    snapshot: Mapping[str, Any],
    block_name: str,
) -> Optional[Sequence[Any]]:
    definitions = snapshot.get("definitions")
    control = definitions.get("control") if (type(definitions) is dict or isinstance(definitions, Mapping)) else None
    block = control.get(block_name) if (type(control) is dict or isinstance(control, Mapping)) else None
    rows = block.get("rows") if (type(block) is dict or isinstance(block, Mapping)) else block
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return None
    return rows


def _control_definition_rows(
    snapshot: Mapping[str, Any],
    block_name: str,
) -> List[Mapping[str, Any]]:
    rows = _raw_control_definition_rows(snapshot, block_name)
    if not rows:
        return []
    return [row for row in rows if (type(row) is dict or isinstance(row, Mapping))]

def _control_rows(snapshot: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return _control_definition_rows(snapshot, "SetValue")

def _run_status_control_keys(snapshot: Mapping[str, Any]) -> set[Tuple[str, str]]:
    return {
        (
            str(row.get("dev_type", "")).strip(),
            str(row.get("dev_name", row.get("name", ""))).strip(),
        )
        for row in _control_definition_rows(snapshot, "RunStat")
        if str(row.get("dev_type", "")).strip()
        and str(row.get("dev_name", row.get("name", ""))).strip()
    }

_CONTROL_ROWS_SET_TYPE_CACHE: Dict[Tuple[int, int, int], Dict[Tuple[str, str], set[str]]] = {}


def _control_set_types_by_device(rows: Sequence[Any]) -> Dict[Tuple[str, str], set[str]]:
    """按原始控制表对象身份缓存每台设备允许的 set_type 集合，消除 O(N*M) 重复扫描。"""
    if not rows:
        return {}
    key = (id(rows), len(rows), id(rows[0]))
    cached = _CONTROL_ROWS_SET_TYPE_CACHE.get(key)
    if cached is not None:
        return cached
    indexed: Dict[Tuple[str, str], set[str]] = {}
    for row in rows:
        if not (type(row) is dict or isinstance(row, Mapping)):
            continue
        dev_key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        indexed.setdefault(dev_key, set()).add(str(row.get("set_type", "")))
    if len(_CONTROL_ROWS_SET_TYPE_CACHE) >= 32:
        _CONTROL_ROWS_SET_TYPE_CACHE.clear()
    _CONTROL_ROWS_SET_TYPE_CACHE[key] = indexed
    return indexed


def _preferred_set_type(
    snapshot: Mapping[str, Any],
    device: Optional[Mapping[str, Any]],
    candidates: Sequence[str],
) -> str:
    if not device:
        return ""
    rows = _raw_control_definition_rows(snapshot, "SetValue")
    if rows:
        defined = _control_set_types_by_device(rows).get(
            (_device_type(device), _device_name(device)),
            (),
        )
        for candidate in candidates:
            if candidate in defined:
                return candidate
        return ""
    set_types = {str(value) for value in device.get("set_types", []) or []}
    return next((candidate for candidate in candidates if candidate in set_types), "")

def _definition_device_rows(
    snapshot: Mapping[str, Any],
    block_names: Sequence[str],
) -> Dict[Tuple[str, str], Mapping[str, Any]]:
    rows: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    for block_name in block_names:
        for row in _parameter_rows(snapshot, block_name):
            name = _parameter_name(row).strip()
            if name:
                rows[(block_name, name)] = row
    return rows

def _device_by_model_key(
    snapshot: Mapping[str, Any],
) -> Dict[Tuple[str, str], Mapping[str, Any]]:
    return {
        _device_model_key(device): device
        for device in snapshot.get("devices", []) or []
        if (type(device) is dict or isinstance(device, Mapping)) and all(_device_model_key(device))
    }

def _hydrogen_pressure_states(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    settings: RenewableControlSettings,
) -> List[Dict[str, Any]]:
    devices = _device_by_model_key(snapshot)
    states: List[Dict[str, Any]] = []
    for row in _parameter_rows(snapshot, "HydroStorage"):
        name = _parameter_name(row).strip()
        device = devices.get(("HydroStorage", name))
        pressure_measurement = (
            _measured(measurements, _device_type(device), name, ("PRESSURE", "PRESS"))
            if device
            else _measured(measurements, "HydroStorage", name, ("PRESSURE", "PRESS"))
        )
        pressure = pressure_measurement.value if pressure_measurement else None
        soc_measurement = (
            _measured(measurements, _device_type(device), name, ("SOC",))
            if device
            else _measured(measurements, "HydroStorage", name, ("SOC",))
        )
        soc = _live_soc_ratio(soc_measurement.value) if soc_measurement else None
        pressure_min = _number(row.get("pressure_min"))
        pressure_max = _number(row.get("pressure_max"))
        limits_valid = bool(
            pressure_min is not None
            and pressure_max is not None
            and pressure_max > pressure_min + EPSILON
        )
        deadband = (
            settings.hydrogen_pressure_deadband_ratio
            * (float(pressure_max) - float(pressure_min))
            if limits_valid
            else None
        )
        online = bool(device and _is_online(device, measurements))
        states.append(
            {
                "devType": _device_type(device) if device else "HydroStorage",
                "devName": name,
                "online": online,
                "pressure": pressure,
                "pressureKnown": pressure is not None,
                "pressureSource": pressure_measurement.source if pressure_measurement else "missing",
                "soc": soc,
                "socKnown": soc is not None and math.isfinite(float(soc)),
                "socSource": soc_measurement.source if soc_measurement else "missing",
                "pressureMin": pressure_min,
                "pressureMax": pressure_max,
                "pressureDeadband": deadband,
                "lowGuard": float(pressure_min) + float(deadband) if limits_valid else None,
                "highGuard": float(pressure_max) - float(deadband) if limits_valid else None,
                "limitsValid": limits_valid,
                "hydrogenIslandId": "",
            }
        )
    return states

def _hydrogen_pressure_states_by_island(
    pressure_states: Sequence[MutableMapping[str, Any]],
    resource_topology: ResourceTopology,
) -> Dict[str, List[MutableMapping[str, Any]]]:
    result: Dict[str, List[MutableMapping[str, Any]]] = {}
    for row in pressure_states:
        key = (str(row.get("devType", "")), str(row.get("devName", "")))
        island_id = str(
            resource_topology.hydrogen_device_island_ids.get(key, "")
        )
        row["hydrogenIslandId"] = island_id
        if island_id:
            result.setdefault(island_id, []).append(row)
    return result

def _rated_capacity(row: Mapping[str, Any], device: Optional[Mapping[str, Any]], category: str) -> float:
    del category
    raw = device.get("raw") if device and isinstance(device.get("raw"), Mapping) else {}
    return _positive(
        (
            row.get("rated_power"),
            row.get("rated_capacity"),
            row.get("p_max"),
            raw.get("rated_capacity"),
            raw.get("rated_power"),
            raw.get("p_max"),
        )
    )

@lru_cache(maxsize=1024)
def _natural_topology_identity_str(text: str) -> Tuple[Tuple[int, Any], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", text)
        if part
    )


def _natural_topology_identity(value: Any) -> Tuple[Tuple[int, Any], ...]:
    return _natural_topology_identity_str(value if type(value) is str else str(value))

def _converter_row_sort_key(row: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        _natural_topology_identity(row.get("dcTransferGroupId", "")),
        _natural_topology_identity(row.get("dev_type", "")),
        _natural_topology_identity(row.get("dev_name", "")),
    )

def _json_safe_copy(value: Any) -> Any:
    if (type(value) is dict or isinstance(value, Mapping)):
        return {str(key): _json_safe_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_copy(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None
        return value
    return str(value)

def _converter_signed_bounds_kw(row: Mapping[str, Any]) -> Tuple[float, float]:
    minimum = _number(row.get("signedMinTargetKw"))
    maximum = _number(row.get("signedMaxTargetKw"))
    if minimum is None or maximum is None or minimum > maximum:
        return 0.0, 0.0
    return minimum, maximum

def _clamp_converter_target_kw(row: Mapping[str, Any], target_kw: Any) -> float:
    minimum, maximum = _converter_signed_bounds_kw(row)
    return _clamp(_finite_number(target_kw), minimum, maximum)

def _converter_ac_injection_bounds_kw(
    row: Mapping[str, Any],
) -> Tuple[float, float]:
    minimum_kw, maximum_kw = _converter_signed_bounds_kw(row)
    converted = sorted(
        (
            _converter_ac_injection_kw(row, minimum_kw),
            _converter_ac_injection_kw(row, maximum_kw),
        )
    )
    return converted[0], converted[1]

def _converter_target_from_ac_injection_kw(
    row: Mapping[str, Any],
    ac_injection_kw: Any,
) -> float:
    return _clamp_converter_target_kw(
        row,
        _converter_power_from_ac_injection_kw(row, ac_injection_kw),
    )
