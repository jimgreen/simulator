"""A small, deterministic environment-aware power-system digital twin.

The original polar-microgrid simulator contains a large E-file model and a
resident load-flow kernel.  This module keeps the parts needed by SCADA and
IEC 104 integration in a standalone process: weather/load driving, renewable
capability curves, a balance calculation, state evolution and a stable
IEC 104 point map.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
from copy import deepcopy
import hashlib
import math
import random
import threading
import time
from typing import Any

from model_import import _default_curves, generate_runtime_points, normalize_model, merge_curve_fields


def wind_available_power(
    speed_mps: float,
    rated_kw: float,
    rated_speed_mps: float = 15.0,
    cut_in_mps: float = 3.0,
    cut_out_mps: float = 30.0,
) -> float:
    """Cubic wind-turbine capability curve used by the source simulator."""

    speed = max(0.0, float(speed_mps))
    rated = max(0.0, float(rated_kw))
    if speed < cut_in_mps or speed >= cut_out_mps:
        return 0.0
    if speed >= rated_speed_mps:
        return rated
    span = max(1e-9, rated_speed_mps - cut_in_mps)
    return rated * ((speed - cut_in_mps) / span) ** 3


def pv_available_power(
    irradiance_w_m2: float,
    air_temp_c: float,
    rated_kw: float,
    temperature_coefficient: float = -0.004,
) -> float:
    """PV capability with a simple cell-temperature correction."""

    irradiance = max(0.0, float(irradiance_w_m2))
    temperature_factor = max(0.0, 1.0 + temperature_coefficient * (float(air_temp_c) - 25.0))
    return max(0.0, float(rated_kw) * irradiance / 1000.0 * temperature_factor)


def clamp(value: float, low: float, high: float) -> float:
    return max(float(low), min(float(high), float(value)))


def _as_bool(value: Any, default: bool = True) -> bool:
    """Parse the booleans commonly found in JSON and E-file exports."""

    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"0", "false", "off", "no", "open", "退出", "分"}:
            return False
        if token in {"1", "true", "on", "yes", "closed", "投入", "合"}:
            return True
    if value is None:
        return bool(default)
    return bool(value)


@dataclass(frozen=True)
class PointDefinition:
    kind: str
    point_no: int
    name: str
    unit: str
    data_type: int
    description: str


# The point numbers are intentionally stable so SCADA integrations can keep
# their address map while the implementation behind the values evolves.
POINTS: tuple[PointDefinition, ...] = (
    PointDefinition("yx", 1, "tie_breaker_closed", "bool", 1, "并网断路器合位"),
    PointDefinition("yx", 2, "diesel_running", "bool", 1, "柴油机运行状态"),
    PointDefinition("yx", 3, "battery_enabled", "bool", 1, "储能可用状态"),
    PointDefinition("yx", 4, "grid_available", "bool", 1, "外部电网可用"),
    PointDefinition("yc", 1, "frequency_hz", "Hz", 13, "系统频率"),
    PointDefinition("yc", 2, "bus1_voltage_kv", "kV", 13, "母线 1 电压"),
    PointDefinition("yc", 3, "bus2_voltage_kv", "kV", 13, "母线 2 电压"),
    PointDefinition("yc", 4, "load_kw", "kW", 13, "总负荷"),
    PointDefinition("yc", 5, "wind_kw", "kW", 13, "风电出力"),
    PointDefinition("yc", 6, "pv_kw", "kW", 13, "光伏出力"),
    PointDefinition("yc", 7, "diesel_kw", "kW", 13, "柴油机出力"),
    PointDefinition("yc", 8, "battery_kw", "kW", 13, "储能出力（放电为正）"),
    PointDefinition("yc", 9, "tie_flow_kw", "kW", 13, "联络线潮流（购电为正）"),
    PointDefinition("yc", 10, "soc_pct", "%", 13, "储能荷电状态"),
    PointDefinition("yc", 11, "phase_angle_deg", "deg", 13, "联络线相角"),
    PointDefinition("yk", 1, "tie_breaker_command", "bool", 45, "遥控并网断路器"),
    PointDefinition("yk", 2, "diesel_command", "bool", 45, "遥控柴油机启停"),
    PointDefinition("yk", 3, "battery_command", "bool", 45, "遥控储能投退"),
)


class DigitalTwin:
    """Thread-safe simulation state shared by Web and IEC 104 workers."""

    def __init__(self, *, seed: int = 104, step_seconds: float = 1.0, model: dict[str, Any] | None = None) -> None:
        self._lock = threading.RLock()
        self._rng = random.Random(seed)
        self.step_seconds = max(0.1, float(step_seconds))
        self.sim_seconds = 0.0
        self.running = True
        self.speed = 1.0
        self._last_wall = time.monotonic()
        self._last_step_wall = self._last_wall
        self._step_requested = False
        self._seq = 0
        self._alarms: deque[dict[str, Any]] = deque(maxlen=100)
        self._history: deque[dict[str, Any]] = deque(maxlen=600)
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self.model = normalize_model(model or {"name": "默认环境模型", "devices": [], "topology": {}, "curves": _default_curves()}, source_name="builtin")
        self.curves = self.model["curves"]
        self._curve_minutes: dict[str, list[float]] = {}
        self._device_index: dict[str, dict[str, Any]] = {}
        self._device_names: dict[str, dict[str, Any]] = {}
        self._family_index: dict[str, list[dict[str, Any]]] = {}
        self._topology_nodes: dict[str, dict[str, Any]] = {}
        self._topology_edges: dict[str, list[dict[str, Any]]] = {}
        self._rebuild_curve_index()
        self._rebuild_device_index()
        self._rebuild_topology_index()
        self._runtime_points = generate_runtime_points(self.model, [point.__dict__.copy() for point in POINTS])
        self._power_flow_count = 0
        self._last_power_flow: dict[str, Any] = {}
        self.tie_breaker_closed = True
        self.diesel_running = True
        self.battery_enabled = True
        self.grid_available = True
        self.soc = self._initial_soc()
        self._battery_energy_kwh = 240.0
        self._model_revision = 1
        self._revision = 0
        self._point_values_cache_revision = -1
        self._point_values_cache: dict[str, dict[int, Any]] | None = None
        self.diagram_svg = self.model.get("diagram", {}).get("svg", "")
        self.diagram_source = self.model.get("diagram", {}).get("source", "")
        self.boundary_source = self.model.get("source", "")
        self._state = self._calculate_state()

    def _weather(self) -> dict[str, float]:
        hour = (self.sim_seconds / 3600.0) % 24.0
        minute = self.sim_seconds / 60.0
        curve = self._curve_at("weather", minute)
        if curve:
            wind = curve.get("wind_speed_mps", 7.0)
            solar = curve.get("solar_irradiance_w_m2", 0.0)
            air_temp = curve.get("air_temp_c", -20.0)
            load = curve.get("load_kw", 160.0)
            load_curve = self._curve_at("load", minute)
            if load_curve and "load_kw" in load_curve:
                load = load_curve["load_kw"]
            return {
                "wind_speed_mps": round(max(0.0, wind), 3),
                "solar_irradiance_w_m2": round(max(0.0, solar), 2),
                "air_temp_c": round(air_temp, 2),
                "load_kw": round(max(0.0, load), 3),
                **{key: curve[key] for key in ("air_pressure_hpa", "humidity_pct") if key in curve},
            }
        solar_angle = math.pi * (hour - 6.0) / 12.0
        solar = max(0.0, math.sin(solar_angle)) ** 1.4 * 820.0
        wind = 7.0 + 1.8 * math.sin(2.0 * math.pi * (hour + 2.0) / 24.0)
        wind += 0.35 * math.sin(self.sim_seconds / 47.0)
        air_temp = -19.0 + 5.5 * math.sin(2.0 * math.pi * (hour - 8.0) / 24.0)
        load = 178.0 + 26.0 * math.sin(2.0 * math.pi * (hour - 7.0) / 24.0)
        load += 13.0 * math.sin(4.0 * math.pi * (hour - 5.0) / 24.0)
        load += self._rng.uniform(-1.5, 1.5)
        return {
            "wind_speed_mps": round(max(0.0, wind), 3),
            "solar_irradiance_w_m2": round(solar, 2),
            "air_temp_c": round(air_temp, 2),
            "load_kw": round(max(80.0, load), 2),
        }

    def _curve_at(self, name: str, minute: float) -> dict[str, float]:
        rows = self.curves.get(name, []) if isinstance(self.curves, dict) else []
        if not rows:
            return {}
        minutes = self._curve_minutes.get(name, [])
        if len(minutes) != len(rows):
            self._rebuild_curve_index()
            minutes = self._curve_minutes.get(name, [])
        position = float(minute) % 1440.0
        if not minutes or position <= minutes[0]:
            return dict(rows[0])
        if position >= minutes[-1]:
            return dict(rows[-1])
        right_index = bisect_right(minutes, position)
        left = rows[right_index - 1]
        right = rows[right_index]
        x0 = minutes[right_index - 1]
        x1 = minutes[right_index]
        ratio = (position - x0) / max(1e-9, x1 - x0)
        keys = set(left) | set(right)
        return {
            key: float(left.get(key, right.get(key, 0.0))) + (float(right.get(key, left.get(key, 0.0))) - float(left.get(key, right.get(key, 0.0)))) * ratio
            for key in keys if key != "minute"
        } | {"minute": position}

    def _rebuild_curve_index(self) -> None:
        """Cache sorted curve positions so each simulation step uses binary search."""

        self._curve_minutes = {
            name: [float(row.get("minute", 0.0)) for row in rows]
            for name, rows in self.curves.items()
            if isinstance(rows, list) and rows
        }
        self._device_curve_keys = {}
        for device in self.model.get("devices", []):
            key = ("load@" + device["name"]) if device["type"] == "load" else ("source@" + device.get("block", "") + "@" + device["name"])
            if key in self.curves:
                self._device_curve_keys[device["id"]] = key

    def _rebuild_device_index(self) -> None:
        """Index devices by id, name and family for fast per-step calculations."""

        devices = [item for item in self.model.get("devices", []) if isinstance(item, dict)]
        self._device_index = {str(item.get("id")): item for item in devices if item.get("id") is not None}
        self._device_names = {str(item.get("name")): item for item in devices if item.get("name")}
        families: dict[str, list[dict[str, Any]]] = {}
        for item in devices:
            families.setdefault(str(item.get("type", "")).lower(), []).append(item)
        self._family_index = families
        for item in devices:
            for alias in item.get("aliases", []):
                self._device_index.setdefault(alias, item)

    def _rebuild_topology_index(self) -> None:
        """Index topology once instead of scanning every edge per device measurement."""

        topology = self.model.get("topology", {})
        nodes = topology.get("nodes", []) if isinstance(topology, dict) else []
        edges = topology.get("edges", []) if isinstance(topology, dict) else []
        self._topology_nodes = {
            str(item.get("id", item.get("name", ""))): item
            for item in nodes
            if isinstance(item, dict) and str(item.get("id", item.get("name", ""))).strip()
        }
        linked: dict[str, list[dict[str, Any]]] = {}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            for endpoint in (edge.get("from", ""), edge.get("to", "")):
                key = str(endpoint).strip()
                if key:
                    linked.setdefault(key, []).append(edge)
        self._topology_edges = linked

    def _family_devices(self, family: str, *, running_only: bool = False) -> list[dict[str, Any]]:
        devices = self._family_index.get(family, [])
        if running_only:
            devices = [item for item in devices if _as_bool(item.get("run", True)) and self._topology_allows(item)]
        return devices

    def _family_capacity(self, family: str, default: float, *, running_only: bool = True) -> float:
        """Return the imported model capacity, with a sensible built-in fallback."""

        devices = self._family_devices(family, running_only=running_only)
        all_devices = self._family_devices(family, running_only=False)
        if not all_devices:
            return float(default)
        if not devices:
            return 0.0
        capacity = sum(max(0.0, float(item.get("rated_kw", item.get("p_max_kw", 0.0)) or 0.0)) for item in devices)
        return capacity if capacity > 0.0 else float(default)

    def _battery_energy_capacity(self) -> float:
        devices = self._family_devices("battery", running_only=False)
        capacity = sum(max(0.0, float(item.get("energy_kwh", item.get("capacity_kwh", 0.0)) or 0.0)) for item in devices)
        return capacity if capacity > 0.0 else self._battery_energy_kwh

    def _initial_soc(self):
        entries = []
        for device in self._family_devices("battery"):
            raw = device.get("parameters", {}).get("soc")
            if raw is not None:
                value = float(raw)
                if math.isfinite(value):
                    entries.append((clamp(value, 0, 1), max(device.get("energy_kwh", 0), 1)))
        return sum(value * weight for value, weight in entries) / sum(weight for _, weight in entries) if entries else .68

    def _device_outputs(self, family_outputs: dict[str, float]) -> dict[str, float]:
        """Split aggregate family outputs into per-device measurement values."""

        result: dict[str, float] = {}
        for family, output in family_outputs.items():
            devices = self._family_devices(family, running_only=True)
            if not devices:
                continue
            capacities = [max(0.0, float(item.get("rated_kw", item.get("p_max_kw", 0.0)) or 0.0)) for item in devices]
            total_capacity = sum(capacities)
            share = float(output) / len(devices) if total_capacity <= 0.0 else None
            for item, capacity in zip(devices, capacities):
                result[str(item.get("id"))] = round(share if share is not None else float(output) * capacity / total_capacity, 3)
        for item in self._device_index.values():
            result.setdefault(str(item.get("id")), 0.0)
        return result

    def _device_is_running(self, family: str, *, default: bool = True) -> bool:
        all_items = self._family_devices(family, running_only=False)
        if not all_items:
            return default
        return bool(self._family_devices(family, running_only=True))

    def _topology_allows(self, device: dict[str, Any]) -> bool:
        if device.get("type") in {"node", "switch", "other"}:
            return True
        node = str(device.get("node", "")).strip()
        if node:
            node_row = self._topology_nodes.get(node)
            if node_row is not None and not _as_bool(node_row.get("run", True)):
                return False
        edges = self._topology_edges.get(node, [])
        if not node or not edges:
            return True
        return any(_as_bool(edge.get("closed", edge.get("run", True))) and _as_bool(edge.get("run", True)) for edge in edges)

    def _imported_outputs(self, weather):
        """Evaluate each electrical source/load once using indexed boundary curves."""
        outputs, available = {}, {}
        loads = self._family_devices("load", running_only=True)
        total_rating = sum(d["rated_kw"] for d in self._family_devices("load"))
        has_total_load = bool(self.curves.get("load")) or any("load_kw" in r for r in self.curves.get("weather", []))
        for device in self.model["devices"]:
            family, identity = device["type"], device["id"]
            if family not in {"wind", "pv", "diesel", "battery", "generator", "load"}:
                continue
            running = device["run"] and self._topology_allows(device)
            rating = max(0, device.get("p_max_kw") or device["rated_kw"])
            parameters = device.get("parameters", {})
            capacity = rating
            if family == "wind":
                capacity = wind_available_power(weather["wind_speed_mps"], rating,
                    float(parameters.get("rated_wind_speed", 15)), float(parameters.get("cut_in_wind_speed", 3)),
                    float(parameters.get("cut_out_wind_speed", 30)))
            elif family == "pv":
                capacity = min(rating, pv_available_power(weather["solar_irradiance_w_m2"], weather["air_temp_c"], rating,
                    float(parameters.get("temperature_coefficient", -.004))))
            available[identity] = capacity if running else 0
            curve = self._curve_at(self._device_curve_keys.get(identity, ""), self.sim_seconds / 60)
            target = curve.get("p_kw", curve.get("value"))
            if target is None:
                family_curve = self._curve_at(family, self.sim_seconds / 60)
                family_target = family_curve.get(family + "_kw")
                if family_target is not None and family in {"diesel", "battery"}:
                    total = self._family_capacity(family, 0)
                    target = family_target * rating / total if total else 0
                elif family == "load" and has_total_load:
                    target = weather["load_kw"] * device["rated_kw"] / total_rating if total_rating else weather["load_kw"] / max(1, len(loads))
                elif family == "diesel" and "p_set_kw" not in device:
                    total = self._family_capacity("diesel", 0)
                    target = min(total, 145) * rating / total if total else 0
                else:
                    target = device.get("p_set_kw", capacity if family in {"wind", "pv"} else 0)
            if family == "battery":
                running = running and self.battery_enabled
                if (self.soc <= .1 and target > 0) or (self.soc >= .95 and target < 0):
                    target = 0
            if family == "diesel":
                running = running and self.diesel_running
            outputs[identity] = round(clamp(target, -rating if family == "battery" else 0, capacity) if running else 0, 3)
        return outputs, available

    def _calculate_state(self) -> dict[str, Any]:
        weather = self._weather()
        wind_capacity = self._family_capacity("wind", 92.0)
        pv_capacity = self._family_capacity("pv", 78.0)
        diesel_capacity = self._family_capacity("diesel", 220.0)
        wind = wind_available_power(weather["wind_speed_mps"], wind_capacity) if self._device_is_running("wind") else 0.0
        pv = pv_available_power(weather["solar_irradiance_w_m2"], weather["air_temp_c"], pv_capacity) if self._device_is_running("pv") else 0.0
        available_renewable = wind + pv
        demand = weather["load_kw"]
        diesel_curve = self._curve_at("diesel", self.sim_seconds / 60.0)
        diesel_target = diesel_curve.get("diesel_kw", min(diesel_capacity, 145.0)) if diesel_curve else min(diesel_capacity, 145.0)
        diesel = clamp(diesel_target, 0.0, diesel_capacity) if self.diesel_running and self._device_is_running("diesel") else 0.0
        battery_curve = self._curve_at("battery", self.sim_seconds / 60.0)
        battery_target = battery_curve.get("battery_kw", 0.0) if battery_curve else 0.0
        battery = clamp(battery_target, -self._family_capacity("battery", 80.0), self._family_capacity("battery", 80.0)) if self.battery_enabled and self._device_is_running("battery") else 0.0
        device_outputs, device_available = {}, {}
        other_generation = 0.0
        if self.model["devices"]:
            device_outputs, device_available = self._imported_outputs(weather)
            totals = {family: sum(device_outputs.get(d["id"], 0) for d in self._family_devices(family))
                      for family in ("wind", "pv", "diesel", "battery", "load", "generator")}
            wind, pv, diesel, battery, demand, other_generation = (totals[k] for k in ("wind", "pv", "diesel", "battery", "load", "generator"))
            if not self._family_devices("load"):
                demand = weather["load_kw"]
            available_renewable = sum(device_available.get(d["id"], 0) for family in ("wind", "pv") for d in self._family_devices(family))
            weather["load_kw"] = demand
        # A positive tie flow means importing from the external grid.  When the
        # breaker is open, the remaining balance error appears as a frequency
        # deviation.
        residual = demand - wind - pv - diesel - battery - other_generation
        tie_flow = residual if self.tie_breaker_closed and self.grid_available else 0.0
        frequency = 50.0 - (residual / 900.0 if not self.tie_breaker_closed else tie_flow / 5000.0)
        frequency = clamp(frequency, 47.0, 52.0)
        voltage1 = clamp(10.5 - abs(tie_flow) * 0.0018, 9.2, 10.8)
        voltage2 = clamp(0.4 - abs(battery) * 0.00055, 0.32, 0.42)
        phase_angle = clamp(tie_flow * 0.035, -30.0, 30.0)
        mismatch = residual - tie_flow
        self._power_flow_count += 1
        self._last_power_flow = {
            "converged": abs(mismatch) < 0.01,
            "iterations": 3 if abs(mismatch) < 0.01 else 8,
            "mismatch_kw": round(mismatch, 6),
            "calculation": "embedded-balance-power-flow",
            "sequence": self._seq + 1,
        }
        self._revision += 1
        return {
            "weather": weather,
            "generation": {
                "wind_kw": round(wind, 3),
                "pv_kw": round(pv, 3),
                "diesel_kw": round(diesel, 3),
                "battery_kw": round(battery, 3),
                "renewable_available_kw": round(available_renewable, 3),
            },
            "network": {
                "load_kw": round(demand, 3),
                "tie_flow_kw": round(tie_flow, 3),
                "frequency_hz": round(frequency, 4),
                "bus1_voltage_kv": round(voltage1, 4),
                "bus2_voltage_kv": round(voltage2, 4),
                "phase_angle_deg": round(phase_angle, 4),
            },
            "states": {
                "tie_breaker_closed": self.tie_breaker_closed,
                "diesel_running": self.diesel_running and self._device_is_running("diesel"),
                "battery_enabled": self.battery_enabled and self._device_is_running("battery"),
                "grid_available": self.grid_available,
            },
            "soc_pct": round(self.soc * 100.0, 3),
            "device_outputs": device_outputs if self.model["devices"] else self._device_outputs({"wind": wind, "pv": pv, "diesel": diesel, "battery": battery}),
            "device_available": device_available,
            "power_flow": dict(self._last_power_flow),
            "device_count": len(self.model.get("devices", [])),
        }

    def _measurement_values(self, state: dict[str, Any]) -> dict[str, float | bool]:
        network = state["network"]
        generation = state["generation"]
        states = state["states"]
        return {
            "tie_breaker_closed": states["tie_breaker_closed"],
            "diesel_running": states["diesel_running"],
            "battery_enabled": states["battery_enabled"],
            "grid_available": states["grid_available"],
            "frequency_hz": network["frequency_hz"],
            "bus1_voltage_kv": network["bus1_voltage_kv"],
            "bus2_voltage_kv": network["bus2_voltage_kv"],
            "load_kw": network["load_kw"],
            "wind_kw": generation["wind_kw"],
            "pv_kw": generation["pv_kw"],
            "diesel_kw": generation["diesel_kw"],
            "battery_kw": generation["battery_kw"],
            "tie_flow_kw": network["tie_flow_kw"],
            "soc_pct": state["soc_pct"],
            "phase_angle_deg": network["phase_angle_deg"],
        }

    def _record_alarm(self, code: str, message: str, severity: str = "warning") -> None:
        self._alarms.appendleft({
            "seq": self._seq,
            "time": round(self.sim_seconds, 1),
            "code": code,
            "severity": severity,
            "message": message,
        })

    def _record_event(self, kind: str, message: str, *, source: str = "system", details: dict[str, Any] | None = None) -> None:
        self._events.appendleft({
            "seq": self._seq,
            "sim_time": self.clock()["sim_time"],
            "kind": str(kind),
            "source": str(source),
            "message": str(message),
            "details": dict(details or {}),
        })

    def tick(self, elapsed_seconds: float | None = None, *, force: bool = False) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = self.step_seconds if elapsed_seconds is None else max(0.0, float(elapsed_seconds))
            should_run = self.running or self._step_requested or force
            if not should_run:
                self._last_wall = now
                return False
            if not force and not self._step_requested and now - self._last_step_wall < self.step_seconds / max(self.speed, 0.1):
                return False
            self._step_requested = False
            dt = elapsed * max(self.speed, 0.1)
            self.sim_seconds = (self.sim_seconds + dt) % 86400.0
            state_before = self._state
            battery_power = state_before["generation"]["battery_kw"]
            # Positive battery power discharges the storage.
            self.soc = clamp(self.soc - battery_power * dt / 3600.0 / max(1.0, self._battery_energy_capacity()), 0.1, 0.95)
            self._state = self._calculate_state()
            self._seq += 1
            self._last_step_wall = now
            values = self._measurement_values(self._state)
            self._history.append({
                "seq": self._seq,
                "sim_seconds": round(self.sim_seconds, 2),
                "frequency_hz": values["frequency_hz"],
                "load_kw": values["load_kw"],
                "wind_kw": values["wind_kw"],
                "pv_kw": values["pv_kw"],
                "diesel_kw": values["diesel_kw"],
                "battery_kw": values["battery_kw"],
                "tie_flow_kw": values["tie_flow_kw"],
                "soc_pct": values["soc_pct"],
            })
            if values["frequency_hz"] < 49.5 or values["frequency_hz"] > 50.5:
                self._record_alarm("FREQ_DEVIATION", f"系统频率 {values['frequency_hz']:.3f} Hz", "critical")
            if values["soc_pct"] < 20.0:
                self._record_alarm("LOW_SOC", f"储能 SOC {values['soc_pct']:.1f}%", "warning")
            return True

    def run_cycle(self) -> bool:
        return self.tick()

    def command_clock(self, action: str, value: Any = None) -> dict[str, Any]:
        with self._lock:
            action = str(action or "").lower()
            if action == "start":
                self.running = True
            elif action in {"pause", "stop"}:
                self.running = False
            elif action == "reset":
                self.sim_seconds = 0.0
                self.soc = 0.68
                self._state = self._calculate_state()
                self._history.clear()
                self._alarms.clear()
                self._record_event("clock", "仿真时钟归零", source="web")
            elif action == "step":
                self._step_requested = True
                self.tick(force=True)
            elif action == "speed":
                self.speed = clamp(float(value or 1.0), 0.1, 20.0)
            else:
                raise ValueError(f"未知时钟操作: {action}")
            if action in {"start", "pause", "stop", "step", "speed"}:
                self._record_event("clock", f"仿真时钟操作：{action}", source="web", details={"value": value, "speed": self.speed})
            return self.clock()

    def clock(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "speed": self.speed,
            "sim_seconds": round(self.sim_seconds, 2),
            "sim_time": time.strftime("%H:%M:%S", time.gmtime(self.sim_seconds)),
            "seq": self._seq,
        }

    def apply_command(self, kind: str, point_no: int, value: Any, *, selected: bool = False) -> dict[str, Any]:
        with self._lock:
            kind = str(kind).lower()
            point_no = int(point_no)
            if kind == "yk":
                if isinstance(value, str):
                    token = value.strip().lower()
                    if token in {"true", "on", "yes", "1", "合", "投入"}:
                        enabled = True
                    elif token in {"false", "off", "no", "0", "分", "退出"}:
                        enabled = False
                    else:
                        raise ValueError(f"无效遥控值: {value}")
                else:
                    enabled = bool(int(value)) if isinstance(value, (int, float)) else bool(value)
                if point_no == 1:
                    self.tie_breaker_closed = enabled
                elif point_no == 2:
                    self.diesel_running = enabled
                elif point_no == 3:
                    self.battery_enabled = enabled
                else:
                    raise ValueError(f"未知遥控点: {point_no}")
            else:
                raise ValueError("数字孪生只接受设备遥控命令")
            self._state = self._calculate_state()
            self._record_event("command", f"执行 {kind.upper()} 点 {point_no}", source="iec104" if selected else "web", details={"point_no": point_no, "value": value, "selected": bool(selected)})
            return {"accepted": True, "kind": kind, "point_no": point_no, "value": value, "selected": bool(selected)}

    def set_device_state(self, device_id: str, running: bool, *, source: str = "web") -> dict[str, Any]:
        with self._lock:
            wanted = str(device_id)
            changed = None
            item = self._device_index.get(wanted) or self._device_names.get(wanted)
            if item is not None:
                item["run"] = _as_bool(running)
                self._sync_device_topology(item)
                changed = dict(item)
            if changed is None:
                raise ValueError(f"未知设备: {device_id}")
            self.reconcile_topology()
            self._state = self._calculate_state()
            self._record_event("device", f"设备{'投入' if changed.get('run') else '退出'}：{changed.get('name', wanted)}", source=source, details={"device_id": changed.get("id"), "running": bool(changed.get("run"))})
            return {"accepted": True, "source": source, "device": changed}

    def set_devices_state(self, states: list[dict[str, Any]], *, source: str = "web") -> dict[str, Any]:
        """Apply several device state changes with one topology and power-flow pass."""

        if not isinstance(states, list) or not states:
            raise ValueError("states 必须是非空数组")
        with self._lock:
            changed = []
            resolved = []
            for entry in states:
                if not isinstance(entry, dict):
                    raise ValueError("states 项必须是对象")
                wanted = str(entry.get("device_id", entry.get("id", "")))
                item = self._device_index.get(wanted) or self._device_names.get(wanted)
                if item is None:
                    raise ValueError(f"未知设备: {wanted}")
                resolved.append((item, entry))
            for item, entry in resolved:
                item["run"] = _as_bool(entry.get("running", entry.get("run", True)))
                self._sync_device_topology(item)
                changed.append(dict(item))
            topology_changes = self.reconcile_topology()
            self._state = self._calculate_state()
            self._record_event("device-batch", f"批量更新 {len(changed)} 个设备状态", source=source, details={"count": len(changed), "topology_changes": len(topology_changes)})
            return {
                "accepted": True,
                "source": source,
                "devices": changed,
                "topology_changes": topology_changes,
                "sequence": self._seq,
            }

    def set_topology(self, topology: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if not isinstance(topology, dict):
                raise ValueError("topology 必须是对象")
            edges = topology.get("edges", [])
            if not isinstance(edges, list):
                raise ValueError("topology.edges 必须是数组")
            nodes = topology.get("nodes", [])
            if not isinstance(nodes, list) or not all(isinstance(row, dict) for row in nodes + edges):
                raise ValueError("拓扑节点和支路必须为对象数组")
            self.model["topology"] = deepcopy({"nodes": nodes, "edges": edges})
            for row in self.model["topology"]["nodes"] + self.model["topology"]["edges"]:
                device = self._device_index.get(str(row.get("id", "")))
                if device is not None:
                    device["run"] = _as_bool(row.get("run", device["run"]))
                    if device["type"] == "switch":
                        device["closed_status"] = _as_bool(row.get("closed", device["closed_status"]))
            self._rebuild_device_index()
            self._rebuild_topology_index()
            changes = self.reconcile_topology()
            self._state = self._calculate_state()
            self._record_event("topology", f"拓扑更新，联锁退出 {len(changes)} 个设备", source="web", details={"device_changes": len(changes)})
            return {"topology": self.model["topology"], "device_changes": changes}

    def reconcile_topology(self) -> list[dict[str, Any]]:
        # Keep requested run state: closing an isolating switch restores availability.
        return [{"device_id": d["id"], "run": False, "reason": "topology-isolated"}
                for d in self.model["devices"] if d["run"] and not self._topology_allows(d)]

    def _sync_device_topology(self, device):
        identity = device["id"]
        for row in self.model["topology"].get("nodes", []):
            if str(row.get("id")) == identity:
                row["run"] = device["run"]
        for row in self.model["topology"].get("edges", []):
            if str(row.get("id")) == identity:
                row["run"] = device["run"]
                if device["type"] == "switch":
                    row["closed"] = device["closed_status"]

    def operate_device(self, device_id, action, *, source="web-diagram", model_revision=None):
        with self._lock:
            if model_revision is not None and int(model_revision) != self._model_revision:
                raise ValueError("模型已更换，请刷新图形后重新操作")
            device = self._device_index.get(str(device_id))
            if device is None:
                raise ValueError(f"未知设备: {device_id}")
            if action in {"start", "stop"}:
                return self.set_device_state(device["id"], action == "start", source=source)
            if action not in {"open", "close"} or device["type"] != "switch":
                raise ValueError("此设备不支持该操作")
            if action == "close" and not device["run"]:
                raise ValueError("请先投入开关，再执行合闸")
            device["closed_status"] = action == "close"
            self._sync_device_topology(device)
            self._state = self._calculate_state()
            self._record_event("switch", f"{device['name']}：{'合闸' if action == 'close' else '分闸'}",
                               source=source, details={"device_id": device["id"], "closed_status": device["closed_status"]})
            return {"accepted": True, "device": deepcopy(device), "revision": self._revision}

    def _validate_boundary_devices(self, curves):
        names = {d["name"] for d in self.model["devices"] if d["type"] == "load"}
        sources = {d.get("block", "") + "@" + d["name"] for d in self.model["devices"]
                   if d["type"] in {"wind", "pv", "diesel", "battery", "generator"}}
        for key in curves:
            if key.startswith("load@") and key[5:] not in names:
                raise ValueError(f"负荷曲线未匹配当前模型设备: {key[5:]}")
            if key.startswith("source@") and key[7:] not in sources:
                raise ValueError(f"源曲线未匹配当前模型设备: {key[7:]}")

    def set_curves(self, payload: dict[str, Any]) -> dict[str, Any]:
        from model_import import _normalize_curves
        with self._lock:
            curves = _normalize_curves(payload)
            self._validate_boundary_devices(curves)
            self.curves = curves
            self.model["curves"] = curves
            self._rebuild_curve_index()
            self._state = self._calculate_state()
            self._record_event("curves", "环境与设备曲线已更新", source="web")
            return deepcopy(curves)

    def merge_curves(self, curves, *, source="web"):
        from model_import import _normalize_curves
        with self._lock:
            incoming = _normalize_curves(curves, defaults=False)
            self._validate_boundary_devices(incoming)
            merged = deepcopy(self.curves)
            for key, rows in incoming.items():
                if rows:
                    merged[key] = merge_curve_fields(merged.get(key, []), rows)
            # A newly imported total load channel overrides an older total load curve.
            if any("load_kw" in row for row in incoming.get("weather", [])) and "load" not in incoming:
                merged["load"] = []
            self.curves = merged
            self.model["curves"] = merged
            self.boundary_source = source
            self._rebuild_curve_index()
            self._state = self._calculate_state()
            self._record_event("boundary", "外部边界数据已加载", source=source,
                               details={"curve_counts": {k: len(v) for k, v in incoming.items()}})
            return deepcopy(merged)

    def _diagram_metadata(self):
        return {"available": bool(self.diagram_svg), "source": self.diagram_source,
                "bytes": len(self.diagram_svg.encode("utf-8")),
                "revision": hashlib.sha256(self.diagram_svg.encode("utf-8")).hexdigest(),
                "model_revision": self._model_revision}

    def set_diagram(self, diagram, *, source="web"):
        from model_import import sanitize_svg
        checked = sanitize_svg(str(diagram.get("svg", "")).encode(), source_name=diagram.get("source", "diagram.svg"))
        with self._lock:
            self.diagram_svg, self.diagram_source = checked["svg"], checked["source"]
            self.model["diagram"] = checked
            result = self._diagram_metadata()
            self._record_event("diagram", "电网 SVG 图形已加载", source=source, details=result)
            return result

    def diagram(self):
        with self._lock:
            return {**self._diagram_metadata(), "svg": self.diagram_svg}

    def load_model(self, model):
        candidate = normalize_model(model, source_name=str(model.get("source", "imported-model")))
        points = generate_runtime_points(candidate, [point.__dict__.copy() for point in POINTS])
        with self._lock:
            self.model = candidate
            self._model_revision += 1
            self.curves = self.model["curves"]
            self.diagram_svg = self.model.get("diagram", {}).get("svg", "")
            self.diagram_source = self.model.get("diagram", {}).get("source", "")
            self.boundary_source = self.model["source"]
            self._rebuild_curve_index()
            self._rebuild_device_index()
            self._rebuild_topology_index()
            self._battery_energy_kwh = self._battery_energy_capacity()
            self.soc = self._initial_soc()
            self._runtime_points = points
            self._state = self._calculate_state()
            self._history.clear()
            self._alarms.clear()
            self._record_event("model", f"模型已加载：{self.model.get('name')}", source="web",
                               details={"device_count": len(self.model["devices"])})
            return self.model_summary()

    def apply_scenario(self, name: str, *, source: str = "web") -> dict[str, Any]:
        """Apply a common operating mode atomically and recalculate once."""

        scenario = str(name or "").strip().lower()
        labels = {"grid": "并网模式", "island": "孤网模式", "restart": "设备恢复", "all_stop": "设备全停", "blackout": "外部电网失电"}
        if scenario not in labels:
            raise ValueError(f"未知运行场景: {name}")
        with self._lock:
            if scenario == "grid":
                self.tie_breaker_closed = True
                self.grid_available = True
            elif scenario == "island":
                self.tie_breaker_closed = False
                self.grid_available = True
            elif scenario == "blackout":
                self.tie_breaker_closed = False
                self.grid_available = False
            elif scenario == "restart":
                self.tie_breaker_closed = True
                self.grid_available = True
                self.diesel_running = True
                self.battery_enabled = True
                for item in self._device_index.values():
                    item["run"] = True
            elif scenario == "all_stop":
                self.tie_breaker_closed = False
                self.diesel_running = False
                self.battery_enabled = False
                for item in self._device_index.values():
                    item["run"] = False
            self.reconcile_topology()
            self._state = self._calculate_state()
            self._record_event("scenario", f"切换运行场景：{labels[scenario]}", source=source, details={"scenario": scenario})
            return {"accepted": True, "scenario": scenario, "label": labels[scenario], "clock": self.clock(), "states": self._state["states"]}

    def model_summary(self) -> dict[str, Any]:
        return {"name": self.model.get("name"), "source": self.model.get("source"), "metadata": self.model.get("metadata", {}), "device_count": len(self.model.get("devices", [])), "topology": self.model.get("topology", {}), "curve_counts": {key: len(value) for key, value in self.curves.items()}}

    def point_values(self) -> dict[str, dict[int, Any]]:
        with self._lock:
            return self._point_values_locked()

    def _point_values_locked(self):
        if self._point_values_cache_revision == self._revision and self._point_values_cache is not None:
            return {kind: dict(values) for kind, values in self._point_values_cache.items()}
        values = self._measurement_values(self._state)
        result: dict[str, dict[int, Any]] = {"yx": {}, "yc": {}, "yk": {}, "yt": {}}
        generation = self._state.get("generation", {})
        device_outputs = self._state.get("device_outputs", {})
        devices = {str(item.get("id")): item for item in self.model.get("devices", [])}
        for point in self._runtime_points:
            kind = str(point.get("kind"))
            point_no = int(point.get("point_no", point.get("pnt_no")))
            name = str(point.get("name", ""))
            if kind in {"yx", "yc"} and name in values:
                result[kind][point_no] = values[name]
            elif name == "tie_breaker_command":
                result[kind][point_no] = self.tie_breaker_closed
            elif name == "diesel_command":
                result[kind][point_no] = self.diesel_running
            elif name == "battery_command":
                result[kind][point_no] = self.battery_enabled
            elif point.get("device_id"):
                device = devices.get(str(point["device_id"]), {})
                family = str(device.get("type", "other"))
                if name.endswith("_running"):
                    result[kind][point_no] = _as_bool(device.get("run", True)) and self._topology_allows(device)
                elif name.endswith("_closed_status"):
                    result[kind][point_no] = bool(device.get("closed_status"))
                elif name.endswith("_p_kw"):
                    result[kind][point_no] = float(device_outputs.get(str(point["device_id"]), generation.get(f"{family}_kw", 0.0)) or 0.0)
        self._point_values_cache_revision = self._revision
        self._point_values_cache = result
        return {kind: dict(values) for kind, values in result.items()}

    def _diagram_measurements(self, devices):
        by_key = {(d.get("block"), d["name"]): d for d in devices}
        result = {}
        for definition in self.model.get("measurements", []):
            device = by_key.get((definition.get("dev_type"), definition.get("dev_name")))
            if not device:
                continue
            metric = str(definition.get("meas_type", "")).upper()
            value = None
            if metric == "RUN_STAT":
                value = int(device["running"])
            elif metric == "STATUS" and device["type"] == "switch":
                value = int(device["closed_status"])
            elif metric in {"P_GEN", "P_LOAD", "P"}:
                value = device["p_kw"]
            elif metric == "SOC" and device["soc_pct"] is not None:
                value = device["soc_pct"] / 100
            result[definition.get("name", "")] = {"value": value, "meas_type": metric}
        return result

    def snapshot(self, *, history_limit: int = 120) -> dict[str, Any]:
        with self._lock:
            state = self._state
            values = self._measurement_values(state)
            device_outputs = state.get("device_outputs", {})
            devices = []
            for item in self.model.get("devices", []):
                row = dict(item)
                row["running"] = _as_bool(item.get("run", True)) and self._topology_allows(item)
                row["p_kw"] = device_outputs.get(item["id"])
                row["available_kw"] = state.get("device_available", {}).get(item["id"])
                row["soc_pct"] = state["soc_pct"] if item["type"] == "battery" else None
                row.pop("parameters", None)
                row.pop("fields", None)
                devices.append(row)
            return {
                "clock": self.clock(),
                "weather": state["weather"],
                "generation": state["generation"],
                "network": state["network"],
                "states": state["states"],
                "soc_pct": state["soc_pct"],
                "measurements": values,
                "point_values": self.point_values(),
                "alarms": list(self._alarms),
                "events": list(self._events)[:30],
                "history": list(self._history)[-max(1, min(int(history_limit), 600)):],
                "sequence": self._seq,
                "model": self.model_summary(),
                "devices": devices,
                "topology": self.model.get("topology", {}),
                "power_flow": dict(self._last_power_flow),
                "diagram": self._diagram_metadata(),
                "boundary_source": self.boundary_source,
                "revision": self._revision,
                "diagram_measurements": self._diagram_measurements(devices),
            }

    def history(self, limit: int = 120) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)[-max(1, min(int(limit), 600)):]

    def events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)[:max(1, min(int(limit), 200))]

    def points(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._runtime_points]

    @staticmethod
    def point_definitions() -> list[dict[str, Any]]:
        return [point.__dict__.copy() for point in POINTS]

