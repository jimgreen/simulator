"""A small, deterministic environment-aware power-system digital twin.

The original polar-microgrid simulator contains a large E-file model and a
resident load-flow kernel.  This module keeps the parts needed by SCADA, AGC
and PAS integration in a standalone process: weather/load driving, renewable
capability curves, a dispatch/balance calculation, state evolution and a
stable IEC 104 point map.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import random
import threading
import time
from typing import Any

from model_import import _default_curves, generate_runtime_points, normalize_model


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


# The point numbers are intentionally stable.  SCADA/AGC/PAS integrations can
# keep their address map while the implementation behind the values evolves.
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
    PointDefinition("yc", 11, "ace_mw", "MW", 13, "区域控制偏差"),
    PointDefinition("yc", 12, "reserve_up_kw", "kW", 13, "上调备用"),
    PointDefinition("yc", 13, "reserve_down_kw", "kW", 13, "下调备用"),
    PointDefinition("yc", 14, "phase_angle_deg", "deg", 13, "联络线相角"),
    PointDefinition("yk", 1, "tie_breaker_command", "bool", 45, "遥控并网断路器"),
    PointDefinition("yk", 2, "diesel_command", "bool", 45, "遥控柴油机启停"),
    PointDefinition("yk", 3, "battery_command", "bool", 45, "遥控储能投退"),
    PointDefinition("yt", 1, "agc_generation_setpoint", "kW", 50, "AGC 发电目标"),
    PointDefinition("yt", 2, "battery_power_setpoint", "kW", 50, "AGC 储能功率目标"),
    PointDefinition("yt", 3, "load_shed_percent", "%", 50, "PAS 负荷切除比例"),
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
        self.model = normalize_model(model or {"name": "默认环境模型", "devices": [], "topology": {}, "curves": _default_curves()}, source_name="builtin")
        self.curves = self.model["curves"]
        self._runtime_points = generate_runtime_points(self.model, [point.__dict__.copy() for point in POINTS])
        self._power_flow_count = 0
        self._last_power_flow: dict[str, Any] = {}
        self.tie_breaker_closed = True
        self.diesel_running = True
        self.battery_enabled = True
        self.grid_available = True
        self.soc = 0.68
        self._battery_energy_kwh = 240.0
        self.agc_generation_setpoint_kw = 145.0
        self._agc_generation_commanded = False
        self.battery_power_setpoint_kw = 0.0
        self.load_shed_percent = 0.0
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
                "load_kw": round(max(20.0, load), 2),
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
        rows = sorted(rows, key=lambda row: float(row.get("minute", 0.0)))
        position = float(minute) % 1440.0
        if position <= float(rows[0].get("minute", 0.0)):
            return dict(rows[0])
        if position >= float(rows[-1].get("minute", 0.0)):
            return dict(rows[-1])
        for left, right in zip(rows, rows[1:]):
            x0 = float(left.get("minute", 0.0)); x1 = float(right.get("minute", 0.0))
            if x0 <= position <= x1:
                ratio = (position - x0) / max(1e-9, x1 - x0)
                keys = set(left) | set(right)
                return {
                    key: float(left.get(key, right.get(key, 0.0))) + (float(right.get(key, left.get(key, 0.0))) - float(left.get(key, right.get(key, 0.0)))) * ratio
                    for key in keys if key != "minute"
                } | {"minute": position}
        return dict(rows[-1])

    def _family_devices(self, family: str, *, running_only: bool = False) -> list[dict[str, Any]]:
        devices = [item for item in self.model.get("devices", []) if str(item.get("type", "")).lower() == family]
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
        for item in self.model.get("devices", []):
            result.setdefault(str(item.get("id")), 0.0)
        return result

    def _device_is_running(self, family: str, *, default: bool = True) -> bool:
        all_items = self._family_devices(family, running_only=False)
        if not all_items:
            return default
        return bool(self._family_devices(family, running_only=True))

    def _topology_allows(self, device: dict[str, Any]) -> bool:
        node = str(device.get("node", "")).strip()
        topology = self.model.get("topology", {})
        nodes = topology.get("nodes", []) if isinstance(topology, dict) else []
        if node and isinstance(nodes, list):
            node_row = next((item for item in nodes if isinstance(item, dict) and str(item.get("id", item.get("name", ""))) == node), None)
            if node_row is not None and not _as_bool(node_row.get("run", True)):
                return False
        edges = topology.get("edges", []) if isinstance(topology, dict) else []
        if not node or not edges:
            return True
        linked = [edge for edge in edges if str(edge.get("from", "")) == node or str(edge.get("to", "")) == node]
        return not linked or any(_as_bool(edge.get("closed", edge.get("run", True))) and _as_bool(edge.get("run", True)) for edge in linked)

    def _calculate_state(self) -> dict[str, Any]:
        weather = self._weather()
        wind_capacity = self._family_capacity("wind", 92.0)
        pv_capacity = self._family_capacity("pv", 78.0)
        diesel_capacity = self._family_capacity("diesel", 220.0)
        battery_capacity = self._family_capacity("battery", 80.0)
        wind = wind_available_power(weather["wind_speed_mps"], wind_capacity) if self._device_is_running("wind") else 0.0
        pv = pv_available_power(weather["solar_irradiance_w_m2"], weather["air_temp_c"], pv_capacity) if self._device_is_running("pv") else 0.0
        available_renewable = wind + pv
        demand = weather["load_kw"] * (1.0 - clamp(self.load_shed_percent, 0.0, 60.0) / 100.0)
        diesel_curve = self._curve_at("diesel", self.sim_seconds / 60.0)
        diesel_target = self.agc_generation_setpoint_kw
        if diesel_curve and not self._agc_generation_commanded:
            diesel_target = diesel_curve.get("diesel_kw", diesel_target)
        diesel = clamp(diesel_target, 0.0, diesel_capacity) if self.diesel_running and self._device_is_running("diesel") else 0.0
        battery = clamp(self.battery_power_setpoint_kw, -battery_capacity, battery_capacity) if self.battery_enabled and self._device_is_running("battery") else 0.0
        # A positive tie flow means importing from the external grid.  When the
        # breaker is open, the island controller uses the battery to balance the
        # residual and reports a frequency deviation instead.
        residual = demand - available_renewable - diesel - battery
        tie_flow = residual if self.tie_breaker_closed and self.grid_available else 0.0
        frequency = 50.0 - (residual / 900.0 if not self.tie_breaker_closed else tie_flow / 5000.0)
        frequency = clamp(frequency, 47.0, 52.0)
        voltage1 = clamp(10.5 - abs(tie_flow) * 0.0018, 9.2, 10.8)
        voltage2 = clamp(0.4 - abs(battery) * 0.00055, 0.32, 0.42)
        ace_mw = (frequency - 50.0) * 0.8 + tie_flow / 1000.0
        reserve_up = max(0.0, diesel_capacity - diesel) + (battery_capacity - max(0.0, battery))
        reserve_down = max(0.0, diesel) + (battery_capacity + min(0.0, battery))
        phase_angle = clamp(tie_flow * 0.035, -30.0, 30.0)
        mismatch = demand - available_renewable - diesel - battery - tie_flow
        self._power_flow_count += 1
        self._last_power_flow = {
            "converged": abs(mismatch) < 0.01,
            "iterations": 3 if abs(mismatch) < 0.01 else 8,
            "mismatch_kw": round(mismatch, 6),
            "calculation": "embedded-balance-power-flow",
            "sequence": self._seq + 1,
        }
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
                "ace_mw": round(ace_mw, 5),
            },
            "reserve": {
                "up_kw": round(reserve_up, 3),
                "down_kw": round(reserve_down, 3),
            },
            "states": {
                "tie_breaker_closed": self.tie_breaker_closed,
                "diesel_running": self.diesel_running and self._device_is_running("diesel"),
                "battery_enabled": self.battery_enabled and self._device_is_running("battery"),
                "grid_available": self.grid_available,
            },
            "soc_pct": round(self.soc * 100.0, 3),
            "device_outputs": self._device_outputs({"wind": wind, "pv": pv, "diesel": diesel, "battery": battery}),
            "power_flow": dict(self._last_power_flow),
            "device_count": len(self.model.get("devices", [])),
        }

    def _measurement_values(self, state: dict[str, Any]) -> dict[str, float | bool]:
        network = state["network"]
        generation = state["generation"]
        reserve = state["reserve"]
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
            "ace_mw": network["ace_mw"],
            "reserve_up_kw": reserve["up_kw"],
            "reserve_down_kw": reserve["down_kw"],
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
                self._agc_generation_commanded = False
                self._state = self._calculate_state()
                self._history.clear()
                self._alarms.clear()
            elif action == "step":
                self._step_requested = True
                self.tick(force=True)
            elif action == "speed":
                self.speed = clamp(float(value or 1.0), 0.1, 20.0)
            else:
                raise ValueError(f"未知时钟操作: {action}")
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
            elif kind == "yt":
                numeric = float(value)
                if point_no == 1:
                    self.agc_generation_setpoint_kw = clamp(numeric, 0.0, self._family_capacity("diesel", 220.0))
                    self._agc_generation_commanded = True
                elif point_no == 2:
                    capacity = self._family_capacity("battery", 80.0)
                    self.battery_power_setpoint_kw = clamp(numeric, -capacity, capacity)
                elif point_no == 3:
                    self.load_shed_percent = clamp(numeric, 0.0, 60.0)
                else:
                    raise ValueError(f"未知遥调点: {point_no}")
            else:
                raise ValueError("数字孪生只接受 yk/yt 控制命令")
            self._state = self._calculate_state()
            return {"accepted": True, "kind": kind, "point_no": point_no, "value": value, "selected": bool(selected)}

    def set_device_state(self, device_id: str, running: bool, *, source: str = "web") -> dict[str, Any]:
        with self._lock:
            wanted = str(device_id)
            changed = None
            for item in self.model.get("devices", []):
                if str(item.get("id")) == wanted or str(item.get("name")) == wanted:
                    item["run"] = _as_bool(running)
                    changed = dict(item)
                    break
            if changed is None:
                raise ValueError(f"未知设备: {device_id}")
            self.reconcile_topology()
            self._state = self._calculate_state()
            return {"accepted": True, "source": source, "device": changed}

    def set_topology(self, topology: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if not isinstance(topology, dict):
                raise ValueError("topology 必须是对象")
            edges = topology.get("edges", [])
            if not isinstance(edges, list):
                raise ValueError("topology.edges 必须是数组")
            self.model["topology"] = {"nodes": list(topology.get("nodes", [])), "edges": list(edges)}
            changes = self.reconcile_topology()
            self._state = self._calculate_state()
            return {"topology": self.model["topology"], "device_changes": changes}

    def reconcile_topology(self) -> list[dict[str, Any]]:
        changes = []
        for item in self.model.get("devices", []):
            allowed = self._topology_allows(item)
            if not allowed and item.get("run", True):
                item["run"] = False
                changes.append({"device_id": item.get("id"), "run": False, "reason": "topology-isolated"})
        return changes

    def set_curves(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            curves = payload.get("curves", payload) if isinstance(payload, dict) else None
            if not isinstance(curves, dict):
                raise ValueError("curves 必须是对象")
            from model_import import _normalize_curves
            self.curves = _normalize_curves({"curves": curves})
            self.model["curves"] = self.curves
            self._state = self._calculate_state()
            return self.curves

    def load_model(self, model: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.model = normalize_model(model, source_name=str(model.get("source", "imported-model")))
            self.curves = self.model["curves"]
            self._battery_energy_kwh = self._battery_energy_capacity()
            self._agc_generation_commanded = False
            self._runtime_points = generate_runtime_points(self.model, [point.__dict__.copy() for point in POINTS])
            self.reconcile_topology()
            self._state = self._calculate_state()
            self._history.clear()
            self._alarms.clear()
            return self.model_summary()

    def model_summary(self) -> dict[str, Any]:
        return {"name": self.model.get("name"), "source": self.model.get("source"), "metadata": self.model.get("metadata", {}), "device_count": len(self.model.get("devices", [])), "topology": self.model.get("topology", {}), "curve_counts": {key: len(value) for key, value in self.curves.items()}}

    def point_values(self) -> dict[str, dict[int, Any]]:
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
            elif name == "agc_generation_setpoint":
                result[kind][point_no] = self.agc_generation_setpoint_kw
            elif name == "battery_power_setpoint":
                result[kind][point_no] = self.battery_power_setpoint_kw
            elif name == "load_shed_percent":
                result[kind][point_no] = self.load_shed_percent
            elif point.get("device_id"):
                device = devices.get(str(point["device_id"]), {})
                family = str(device.get("type", "other"))
                if name.endswith("_running"):
                    result[kind][point_no] = _as_bool(device.get("run", True)) and self._topology_allows(device)
                elif name.endswith("_p_kw"):
                    result[kind][point_no] = float(device_outputs.get(str(point["device_id"]), generation.get(f"{family}_kw", 0.0)) or 0.0)
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
                row["p_kw"] = round(float(device_outputs.get(str(item.get("id")), 0.0)), 3)
                devices.append(row)
            return {
                "clock": self.clock(),
                "weather": state["weather"],
                "generation": state["generation"],
                "network": state["network"],
                "reserve": state["reserve"],
                "states": state["states"],
                "soc_pct": state["soc_pct"],
                "measurements": values,
                "point_values": self.point_values(),
                "controls": {
                    "agc_generation_setpoint_kw": self.agc_generation_setpoint_kw,
                    "battery_power_setpoint_kw": self.battery_power_setpoint_kw,
                    "load_shed_percent": self.load_shed_percent,
                },
                "alarms": list(self._alarms),
                "history": list(self._history)[-max(1, min(int(history_limit), 600)):],
                "sequence": self._seq,
                "model": self.model_summary(),
                "devices": devices,
                "topology": self.model.get("topology", {}),
                "power_flow": dict(self._last_power_flow),
            }

    def history(self, limit: int = 120) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)[-max(1, min(int(limit), 600)):]

    def points(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._runtime_points]

    @staticmethod
    def point_definitions() -> list[dict[str, Any]]:
        return [point.__dict__.copy() for point in POINTS]

