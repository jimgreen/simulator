from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import linprog, lsq_linear, minimize

from .control_config import default_integer, default_number
from .device_roles import (
    AC_TO_DC,
    converter_balance_coefficients,
    converter_power_in_dc_to_ac_convention,
)
from .resource_topology import DeviceKey, ResourceTopology


EPSILON = 1e-9
BALANCE_TOLERANCE_KW = default_number("optimization_balance_tolerance_kw")
BOUND_TOLERANCE_KW = default_number("optimization_bound_tolerance_kw")
BALANCE_DELTA_SQUARE_WEIGHT = default_number(
    "optimization_balance_delta_square_weight"
)
BALANCE_DELTA_WARNING_KW = default_number(
    "optimization_balance_delta_warning_kw"
)
RENEWABLE_CURTAILMENT_WEIGHT = default_number(
    "optimization_renewable_curtailment_weight"
)
DIESEL_OUTPUT_WEIGHT = default_number("optimization_diesel_output_weight")
CURTAILMENT_SQUARE_WEIGHT = default_number(
    "optimization_curtailment_square_weight"
)
SOURCE_STORAGE_ADJUSTMENT_SQUARE_WEIGHT = default_number(
    "optimization_source_storage_adjustment_square_weight"
)
OPTIMIZATION_FTOL = default_number("optimization_ftol")
OPTIMIZATION_MAX_ITERATIONS = default_integer("optimization_max_iterations")
MAXIMUM_POWER_PROTECTION_RATIO = default_number(
    "maximum_power_protection_ratio"
)
OPTIMIZATION_RANK_TOLERANCE = default_number("optimization_rank_tolerance")
OPTIMIZATION_ZERO_SNAP_TOLERANCE_KW = default_number(
    "optimization_zero_snap_tolerance_kw"
)


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _device_key(row: Mapping[str, Any]) -> DeviceKey:
    return str(row.get("dev_type", "")), str(row.get("dev_name", ""))


def _component_id(row: Mapping[str, Any]) -> str:
    side = str(row.get("connectionSide", "")).strip().upper()
    if side == "AC":
        return str(row.get("gridComponentId", "")).strip()
    if side == "DC":
        return str(
            row.get("dcTransferGroupId") or row.get("gridComponentId") or ""
        ).strip()
    return ""


@dataclass(frozen=True)
class _Variable:
    key: DeviceKey
    kind: str
    current_kw: float
    lower_kw: float
    upper_kw: float
    side: str = ""
    component_id: str = ""
    ac_component_id: str = ""
    dc_component_id: str = ""
    ac_balance_coefficient: float = 0.0
    dc_balance_coefficient: float = 0.0
    allocation_capacity_kw: float = 0.0
    renewable_available_kw: Optional[float] = None
    safety_lower_kw: Optional[float] = None
    safety_upper_kw: Optional[float] = None
    requires_safety_correction: bool = False
    normal_step_kw: float = 0.0
    storage_soc: Optional[float] = None
    storage_forced_direction: str = ""
    storage_commandable: bool = True
    converter_efficiency: float = 1.0
    converter_base_dc_coefficient: float = 0.0


@dataclass(frozen=True)
class IslandOptimizationResult:
    island_id: str
    component_ids: Tuple[str, ...]
    device_keys: Tuple[DeviceKey, ...]
    success: bool
    status: str
    message: str
    target_by_device: Mapping[DeviceKey, float]
    active_lower_by_device: Mapping[DeviceKey, float]
    active_upper_by_device: Mapping[DeviceKey, float]
    balance_residual_by_component: Mapping[str, float]
    objective_value: Optional[float]
    renewable_curtailment_kw: float
    diesel_target_kw: float
    curtailment_square_weight: float
    adjustment_square_weight: float
    balance_delta_square_weight: float
    balance_delta_by_side: Mapping[str, float]
    max_balance_delta_kw: float
    step_override_applied: bool
    step_override_devices: Tuple[DeviceKey, ...]
    iterations: int
    variable_count: int
    constraint_count: int
    equality_constraint_count: int
    inequality_constraint_count: int
    bound_count: int
    build_seconds: float
    solver_seconds: float
    storage_balance_seconds: float
    postprocess_seconds: float
    solve_seconds: float


@dataclass(frozen=True)
class RenewableDispatchOptimizationResult:
    targets: Mapping[DeviceKey, float]
    available_by_renewable: Mapping[DeviceKey, float]
    curtailment_by_renewable: Mapping[DeviceKey, float]
    islands: Tuple[IslandOptimizationResult, ...]
    unassigned_devices: Tuple[DeviceKey, ...]
    all_success: bool
    max_balance_residual_kw: float
    balance_delta_warning_kw: float
    iterations: int
    variable_count: int
    constraint_count: int
    equality_constraint_count: int
    inequality_constraint_count: int
    bound_count: int
    build_seconds: float
    solver_seconds: float
    storage_balance_seconds: float
    postprocess_seconds: float
    solve_seconds: float


class _DisjointSet:
    def __init__(self) -> None:
        self._parent: Dict[str, str] = {}

    def add(self, value: str) -> None:
        if value:
            self._parent.setdefault(value, value)

    def find(self, value: str) -> str:
        parent = self._parent[value]
        while parent != self._parent[parent]:
            parent = self._parent[parent]
        while value != parent:
            next_value = self._parent[value]
            self._parent[value] = parent
            value = next_value
        return parent

    def union(self, left: str, right: str) -> None:
        self.add(left)
        self.add(right)
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if left_root < right_root:
            self._parent[right_root] = left_root
        else:
            self._parent[left_root] = right_root


def _renewable_variable(
    row: Mapping[str, Any],
    step_coefficient: float,
) -> Optional[_Variable]:
    if not row.get("online") or not row.get("commandable"):
        return None
    current = _number(row.get("planningCurrentKw", row.get("currentKw")))
    capacity = _number(row.get("capacityKw"))
    component_id = _component_id(row)
    key = _device_key(row)
    if current is None or capacity is None or capacity < 0.0 or not all(key) or not component_id:
        return None
    step_kw = step_coefficient * max(0.0, capacity)
    normal_available = min(max(0.0, capacity), max(0.0, current) + step_kw)
    # 物理自然资源上限（有效气象前馈或电侧闭环饱和）同时收窄弃电基准与变量上界，
    # 避免夜间无光/无风时误产生弃风弃光惩罚或虚算增发额度去压柴发。
    natural_upper = _number(row.get("naturalUpperKw"))
    if natural_upper is not None:
        normal_available = min(normal_available, max(0.0, natural_upper))
    available = normal_available
    dispatch_upper = _number(row.get("dispatchUpperKw"))
    if dispatch_upper is not None:
        available = min(available, max(0.0, dispatch_upper))
    lower = max(0.0, current - step_kw)
    if lower > available + EPSILON:
        lower = available
    return _Variable(
        key=key,
        kind="renewable",
        current_kw=current,
        lower_kw=lower,
        upper_kw=max(0.0, available),
        side=str(row.get("connectionSide", "")).strip().upper(),
        component_id=component_id,
        renewable_available_kw=max(0.0, normal_available),
        safety_lower_kw=0.0,
        safety_upper_kw=max(0.0, available),
        requires_safety_correction=bool(
            current < lower - EPSILON or current > available + EPSILON
        ),
        normal_step_kw=step_kw,
    )


def _diesel_variable(
    row: Mapping[str, Any],
    diesel_step_ratio: float,
    protection_ratio: float,
) -> Optional[_Variable]:
    if (
        not row.get("online")
        or row.get("automaticControlBlocked")
        or not (row.get("commandable") or row.get("stateEligible"))
    ):
        return None
    current = _number(row.get("currentKw"))
    minimum = _number(row.get("minKw"))
    maximum = _number(row.get("capacityKw"))
    component_id = _component_id(row)
    key = _device_key(row)
    if (
        current is None
        or minimum is None
        or maximum is None
        or minimum > maximum
        or not all(key)
        or not component_id
    ):
        return None
    guard_kw = min(
        max(0.0, protection_ratio) * max(0.0, maximum),
        max(0.0, maximum - minimum) * 0.5,
    )
    protected_minimum = minimum + guard_kw
    protected_maximum = maximum - guard_kw
    requires_safety = bool(
        current < protected_minimum - EPSILON
        or current > protected_maximum + EPSILON
    )
    # 恢复柴发常规爬坡步长限制（0 或 >=1 时退化为不限步长；安全越限时自动由两阶段机制放开）
    if 0.0 < diesel_step_ratio < 1.0 - EPSILON and maximum > EPSILON:
        normal_step_kw = diesel_step_ratio * max(0.0, maximum)
        lower = max(protected_minimum, current - normal_step_kw)
        upper = min(protected_maximum, current + normal_step_kw)
        if lower > upper + EPSILON:
            # 当前功率已深度越出保护区超过 1 步长时，常规阶段按步长向保护区平滑收敛，
            # 避免单拍直接放开至 [protected_min, protected_max] 发生大幅突跳（安全阶段再做兜底）。
            if current < protected_minimum:
                step_toward = min(protected_minimum, current + normal_step_kw)
                lower = step_toward
                upper = min(protected_maximum, max(protected_minimum, step_toward))
            else:
                step_toward = max(protected_maximum, current - normal_step_kw)
                lower = max(protected_minimum, min(protected_maximum, step_toward))
                upper = step_toward
    else:
        normal_step_kw = math.inf
        lower = protected_minimum
        upper = protected_maximum
    return _Variable(
        key=key,
        kind="diesel",
        current_kw=current,
        lower_kw=lower,
        upper_kw=upper,
        side=str(row.get("connectionSide", "")).strip().upper(),
        component_id=component_id,
        safety_lower_kw=protected_minimum,
        safety_upper_kw=protected_maximum,
        requires_safety_correction=requires_safety,
        normal_step_kw=normal_step_kw,
    )


def _storage_variable(
    row: Mapping[str, Any],
    grid_forming_protection_ratio: float,
    storage_step_ratio: float,
    storage_soc_correction_step_scale: float,
    soc_deadband: float,
) -> Optional[_Variable]:
    state_eligible = bool(
        row.get("role") == "balance" and row.get("stateEligible")
    )
    if (
        not row.get("online")
        or row.get("automaticControlBlocked")
        or not (row.get("commandable") or state_eligible)
    ):
        return None
    current = _number(row.get("currentKw"))
    charge = _number(row.get("chargePower"))
    discharge = _number(row.get("dischargePower"))
    component_id = _component_id(row)
    key = _device_key(row)
    if (
        current is None
        or charge is None
        or discharge is None
        or charge < 0.0
        or discharge < 0.0
        or not all(key)
        or not component_id
    ):
        return None
    rated_charge = _number(row.get("maxChargePowerKw"))
    rated_discharge = _number(row.get("maxDischargePowerKw"))
    rated_charge_kw = (
        max(0.0, rated_charge) if rated_charge is not None else charge
    )
    rated_discharge_kw = (
        max(0.0, rated_discharge) if rated_discharge is not None else discharge
    )
    charge_derating_factor = _number(row.get("chargeDeratingFactor"))
    discharge_derating_factor = _number(row.get("dischargeDeratingFactor"))
    if charge_derating_factor is not None:
        charge = min(
            charge,
            rated_charge_kw * min(1.0, max(0.0, charge_derating_factor)),
        )
    if discharge_derating_factor is not None:
        discharge = min(
            discharge,
            rated_discharge_kw
            * min(1.0, max(0.0, discharge_derating_factor)),
        )

    safety_lower = -charge
    safety_upper = discharge
    if row.get("role") == "balance":
        protection_ratio = min(
            MAXIMUM_POWER_PROTECTION_RATIO,
            max(0.0, grid_forming_protection_ratio),
        )
        safety_lower = max(
            safety_lower,
            -rated_charge_kw * (1.0 - protection_ratio),
        )
        safety_upper = min(
            safety_upper,
            rated_discharge_kw * (1.0 - protection_ratio),
        )

    explicit_step_kw = next(
        (
            value
            for key_name in ("stepKw", "powerStepKw", "pStepKw")
            if (value := _number(row.get(key_name))) is not None and value >= 0.0
        ),
        None,
    )
    rated_power = max(
        charge,
        discharge,
        rated_charge_kw,
        rated_discharge_kw,
    )
    step_kw = (
        explicit_step_kw
        if explicit_step_kw is not None
        else max(0.0, storage_step_ratio) * rated_power
    )
    correction_scale = min(
        1.0,
        max(0.10, storage_soc_correction_step_scale),
    )
    correction_step_kw = step_kw * correction_scale
    soc = _number(row.get("soc"))
    soc_min = _number(row.get("socMin"))
    soc_max = _number(row.get("socMax"))
    capacity_kwh = _number(row.get("capacityKwh"))
    efficiency = _number(row.get("efficiency"))
    horizon_minutes = _number(row.get("controlHorizonMinutes"))
    horizon_hours = (
        horizon_minutes / 60.0
        if horizon_minutes is not None and horizon_minutes > EPSILON
        else None
    )

    def violation_correction_kw(boundary: Optional[float], *, charge: bool) -> float:
        minimum_correction_kw = correction_step_kw
        if (
            soc is None
            or boundary is None
            or capacity_kwh is None
            or capacity_kwh <= EPSILON
            or efficiency is None
            or efficiency <= EPSILON
            or horizon_hours is None
        ):
            return minimum_correction_kw
        violation = max(0.0, boundary - soc if charge else soc - boundary)
        energy_correction_kw = (
            violation * capacity_kwh / (efficiency * horizon_hours)
            if charge
            else violation * capacity_kwh * efficiency / horizon_hours
        )
        return min(
            step_kw,
            max(minimum_correction_kw, energy_correction_kw),
        )

    def step_limited_target_kw(desired_kw: float) -> float:
        if desired_kw > current:
            stepped_kw = min(desired_kw, current + step_kw)
        else:
            stepped_kw = max(desired_kw, current - step_kw)
        # Hard power/SOC bounds remain stronger than the ordinary step. This
        # immediately stops charging above the SOC ceiling or discharging
        # below the SOC floor, then subsequent cycles continue by one step.
        return min(safety_upper, max(safety_lower, stepped_kw))

    forced_direction = ""
    forced_boundary_kw: Optional[float] = None
    forced_direct_reversal = False
    # First calculate the desired correction from the energy outside the SOC
    # boundary, then move the target by at most one configured storage step.
    # Repeated control cycles therefore accelerate severe correction without
    # issuing a single oversized setpoint jump.
    if soc is not None and soc_min is not None and soc < soc_min - soc_deadband - EPSILON:
        forced_charge_kw = min(
            violation_correction_kw(soc_min, charge=True),
            max(0.0, -safety_lower),
        )
        if forced_charge_kw > EPSILON:
            if current >= -EPSILON:
                # A storage unit below its SOC floor must cross from
                # discharging/idle directly into charging in this control
                # cycle. The corrective target magnitude itself is bounded
                # by the configured fraction of one step and one full step.
                forced_boundary_kw = -forced_charge_kw
                forced_direct_reversal = True
            else:
                desired_charge_target_kw = current - forced_charge_kw
                forced_boundary_kw = step_limited_target_kw(
                    desired_charge_target_kw
                )
            forced_direction = "charge"
    elif soc is not None and soc_max is not None and soc > soc_max + soc_deadband + EPSILON:
        forced_discharge_kw = min(
            violation_correction_kw(soc_max, charge=False),
            max(0.0, safety_upper),
        )
        if forced_discharge_kw > EPSILON:
            if current <= EPSILON:
                # Symmetrically, a unit above its SOC ceiling must cross from
                # charging/idle directly into positive discharge this cycle.
                forced_boundary_kw = forced_discharge_kw
                forced_direct_reversal = True
            else:
                desired_discharge_target_kw = current + forced_discharge_kw
                forced_boundary_kw = step_limited_target_kw(
                    desired_discharge_target_kw
                )
            forced_direction = "discharge"
    if safety_lower > safety_upper + EPSILON:
        return None

    # SOC segment limits define the hard feasible power range. Normal
    # dispatch may move only one configured step inside that range. When the
    # live point is already outside the range, project directly back to the
    # nearest safe boundary instead of preserving an unsafe value merely to
    # satisfy the ordinary step limit.
    step_lower = max(safety_lower, current - step_kw)
    step_upper = min(safety_upper, current + step_kw)
    anti_drift_applied = False
    if forced_direct_reversal and forced_direction == "charge":
        if current > step_kw + EPSILON:
            # 深度放电越下限时，常规阶段先按步长快速向零/充电方向回撤，避免单拍跨零数倍步长硬反转。
            lower = max(safety_lower, current - step_kw)
            upper = min(safety_upper, max(0.0, current - forced_charge_kw))
            if lower > upper + EPSILON:
                lower = upper
        else:
            lower = max(safety_lower, -step_kw)
            upper = min(safety_upper, forced_boundary_kw)
        normal_step_kw = step_kw
    elif forced_direct_reversal and forced_direction == "discharge":
        if current < -step_kw - EPSILON:
            # 深度充电越上限时，常规阶段先按步长快速向零/放电方向回撤，避免单拍跨零数倍步长硬反转。
            lower = max(safety_lower, min(0.0, current + forced_discharge_kw))
            upper = min(safety_upper, current + step_kw)
            if lower > upper + EPSILON:
                upper = lower
        else:
            lower = max(safety_lower, forced_boundary_kw)
            upper = min(safety_upper, step_kw)
        normal_step_kw = step_kw
    elif forced_boundary_kw is not None and step_lower > step_upper + EPSILON:
        # The live point is already on the forbidden side of a hard SOC/power
        # boundary. Project to that boundary immediately; only the subsequent
        # movement deeper into the corrective direction is step-limited.
        projected_kw = min(safety_upper, max(safety_lower, current))
        lower = projected_kw
        upper = projected_kw
        normal_step_kw = step_kw
    elif forced_direction == "charge" and forced_boundary_kw is not None:
        lower = step_lower
        upper = min(step_upper, forced_boundary_kw)
        normal_step_kw = step_kw
    elif forced_direction == "discharge" and forced_boundary_kw is not None:
        lower = max(step_lower, forced_boundary_kw)
        upper = step_upper
        normal_step_kw = step_kw
    elif row.get("role") == "balance":
        # 构网平衡储能受保护区间与 SOC 边界约束；当直流侧构网储能紧贴 SOC 上下限且因 DCAC 变流器
        # 线性效率/潮流网损偏差仍在向越界方向微小漂移（0.02 ~ 5.0 kW）时，施加温和反向防漂移缓冲，
        # 避免长期卡边触发边界告警，同时不干扰交流构网储能或大功率应急工况。
        lower = safety_lower
        upper = safety_upper
        normal_step_kw = math.inf
        side_tag = str(row.get("connectionSide", "")).strip().upper()
        edge_band = max(0.002, soc_deadband)
        anti_drift_cap_kw = step_kw * 0.25 if step_kw > EPSILON else 2.0
        if (
            side_tag == "DC"
            and soc is not None
            and soc_min is not None
            and soc <= soc_min + edge_band + EPSILON
            and 0.02 < current <= 5.0
            and safety_lower < -EPSILON
        ):
            anti_drift_charge_kw = min(
                -safety_lower,
                max(0.5, min(anti_drift_cap_kw, current * 1.5 + 0.5)),
            )
            candidate_upper = min(upper, -anti_drift_charge_kw)
            if candidate_upper >= lower - EPSILON:
                upper = candidate_upper
                anti_drift_applied = True
        elif (
            side_tag == "DC"
            and soc is not None
            and soc_max is not None
            and soc >= soc_max - edge_band - EPSILON
            and -5.0 <= current < -0.02
            and safety_upper > EPSILON
        ):
            anti_drift_discharge_kw = min(
                safety_upper,
                max(0.5, min(anti_drift_cap_kw, abs(current) * 1.5 + 0.5)),
            )
            candidate_lower = max(lower, anti_drift_discharge_kw)
            if candidate_lower <= upper + EPSILON:
                lower = candidate_lower
                anti_drift_applied = True
    elif current < safety_lower - EPSILON:
        lower = safety_lower
        upper = safety_lower
        normal_step_kw = step_kw
    elif current > safety_upper + EPSILON:
        lower = safety_upper
        upper = safety_upper
        normal_step_kw = step_kw
    else:
        lower = max(safety_lower, current - step_kw)
        upper = min(safety_upper, current + step_kw)
        normal_step_kw = step_kw
    at_soc_floor_discharging = bool(
        soc is not None
        and soc_min is not None
        and soc <= soc_min + EPSILON
        and current > EPSILON
    )
    at_soc_ceiling_charging = bool(
        soc is not None
        and soc_max is not None
        and soc >= soc_max - EPSILON
        and current < -EPSILON
    )
    return _Variable(
        key=key,
        kind="storage",
        current_kw=current,
        lower_kw=lower,
        upper_kw=upper,
        side=str(row.get("connectionSide", "")).strip().upper(),
        component_id=component_id,
        safety_lower_kw=safety_lower,
        safety_upper_kw=safety_upper,
        requires_safety_correction=bool(
            (
                forced_boundary_kw is not None
                and (current < lower - EPSILON or current > upper + EPSILON)
            )
            or at_soc_floor_discharging
            or at_soc_ceiling_charging
            or anti_drift_applied
            or current < safety_lower - EPSILON
            or current > safety_upper + EPSILON
        ),
        normal_step_kw=normal_step_kw,
        storage_soc=soc,
        storage_forced_direction=forced_direction,
        storage_commandable=bool(row.get("commandable")),
    )


def _rebalance_storage_targets_by_soc(
    values: np.ndarray,
    variables: Sequence[_Variable],
    lower: np.ndarray,
    upper: np.ndarray,
    balance_matrix: np.ndarray,
    parallel_matrix: np.ndarray,
    tolerance_kw: float,
    optimization_ftol: float,
    optimization_max_iterations: int,
    soc_rebalance_deadband: float = 0.02,
) -> np.ndarray:
    """在保持总储能功率守恒的前提下，按 SOC 差异死区与平滑权重比例分摊多储能功率，消除乒乓倒手。"""

    original = np.asarray(values, dtype=float).copy()
    tolerance = max(EPSILON, float(tolerance_kw))
    # 仅对可直接下发 p_set 的可控储能执行 SOC 互挪，不对无 p_set 的构网平衡储能做无效纸面再平衡
    storage_indexes = [
        index
        for index, item in enumerate(variables)
        if item.kind == "storage" and item.storage_commandable
    ]
    if len(storage_indexes) < 2:
        return original
    # 按电气分量分组，仅对同分量内包含 >= 2 台可调灵活储能的分量执行再平衡；
    # 避免“AC 1 台 + DC 1 台”跨分量隔离场景白跑 SLSQP 迭代。
    storage_indexes_by_component: Dict[str, list[int]] = {}
    for idx in storage_indexes:
        comp_key = str(variables[idx].component_id or variables[idx].side or "")
        storage_indexes_by_component.setdefault(comp_key, []).append(idx)

    rebalance_components: list[tuple[list[int], list[int], list[int]]] = []
    for comp_storage_indexes in storage_indexes_by_component.values():
        comp_forced = [
            idx for idx in comp_storage_indexes if variables[idx].storage_forced_direction
        ]
        comp_flexible = [
            idx for idx in comp_storage_indexes if not variables[idx].storage_forced_direction
        ]
        if len(comp_flexible) >= 2:
            rebalance_components.append((comp_storage_indexes, comp_forced, comp_flexible))
    if not rebalance_components:
        return original

    desired = original.copy()
    deadband = max(0.0, float(soc_rebalance_deadband))
    active_flexible_indexes: list[int] = []

    for comp_storage_indexes, comp_forced, comp_flexible in rebalance_components:
        storage_total_kw = float(np.sum(original[comp_storage_indexes]))
        forced_total_kw = float(np.sum(original[comp_forced]))
        flexible_total_kw = storage_total_kw - forced_total_kw
        candidate = {
            index: min(max(0.0, float(lower[index])), float(upper[index]))
            for index in comp_flexible
        }
        remaining_kw = flexible_total_kw - sum(candidate.values())

        known_socs = [
            float(variables[idx].storage_soc)
            for idx in comp_flexible
            if variables[idx].storage_soc is not None
            and math.isfinite(float(variables[idx].storage_soc))
        ]
        soc_min = min(known_socs) if known_socs else 0.0
        soc_max = max(known_socs) if known_socs else 0.0
        soc_span = soc_max - soc_min

        def _smooth_distribute(request_kw: float, *, charging: bool) -> float:
            rem = float(request_kw)
            if rem <= tolerance:
                return 0.0
            headrooms: Dict[int, float] = {}
            weights: Dict[int, float] = {}
            for idx in comp_flexible:
                hr = (
                    max(0.0, candidate[idx] - float(lower[idx]))
                    if charging
                    else max(0.0, float(upper[idx]) - candidate[idx])
                )
                headrooms[idx] = hr
                if hr <= EPSILON:
                    weights[idx] = 0.0
                    continue
                soc_val = variables[idx].storage_soc
                if (
                    soc_span <= deadband + EPSILON
                    or soc_val is None
                    or not math.isfinite(float(soc_val))
                ):
                    # SOC 差异在死区内：按可用调节裕度比例均分，彻底杜绝相近 SOC 机台乒乓倒手
                    weights[idx] = hr
                else:
                    norm_bias = (
                        (soc_max - float(soc_val)) / max(soc_span, EPSILON)
                        if charging
                        else (float(soc_val) - soc_min) / max(soc_span, EPSILON)
                    )
                    weights[idx] = (0.15 + max(0.0, norm_bias)) * hr

            active = [
                idx
                for idx in comp_flexible
                if headrooms[idx] > EPSILON and weights[idx] > EPSILON
            ]
            for _ in range(len(comp_flexible) + 2):
                if rem <= tolerance or not active:
                    break
                total_w = sum(weights[idx] for idx in active)
                if total_w <= EPSILON:
                    break
                next_active: list[int] = []
                allocated_this_round = 0.0
                for idx in active:
                    share = rem * (weights[idx] / total_w)
                    take = min(headrooms[idx], share)
                    if charging:
                        candidate[idx] -= take
                    else:
                        candidate[idx] += take
                    headrooms[idx] -= take
                    allocated_this_round += take
                    if headrooms[idx] > tolerance:
                        next_active.append(idx)
                rem -= allocated_this_round
                if allocated_this_round <= EPSILON:
                    break
                active = next_active
            return rem

        if remaining_kw > tolerance:
            remaining_kw = _smooth_distribute(remaining_kw, charging=False)
        elif remaining_kw < -tolerance:
            remaining_kw = -_smooth_distribute(-remaining_kw, charging=True)

        if abs(remaining_kw) > tolerance:
            continue
        for index, target_kw in candidate.items():
            desired[index] = target_kw
        active_flexible_indexes.extend(comp_flexible)

    if not active_flexible_indexes:
        return original
    if np.max(np.abs(desired[storage_indexes] - original[storage_indexes])) <= tolerance:
        return original

    projection_lower = original.copy()
    projection_upper = original.copy()
    adjustable_indexes = set(active_flexible_indexes)
    adjustable_indexes.update(
        index for index, item in enumerate(variables) if item.kind == "converter"
    )
    for index in adjustable_indexes:
        projection_lower[index] = lower[index]
        projection_upper[index] = upper[index]

    # 按电气分量分别保持储能总功率守恒，禁止跨电气隔离分量隔空互挪储能功率。
    storage_total_rows = []
    storage_total_rhs_vals = []
    for comp_indexes in storage_indexes_by_component.values():
        comp_row = np.zeros(len(variables), dtype=float)
        comp_row[comp_indexes] = 1.0
        storage_total_rows.append(comp_row)
        storage_total_rhs_vals.append(float(np.sum(original[comp_indexes])))
    equality_rows = [balance_matrix, np.vstack(storage_total_rows)]
    equality_rhs = [balance_matrix @ original, np.array(storage_total_rhs_vals, dtype=float)]
    if parallel_matrix.shape[0]:
        equality_rows.append(parallel_matrix)
        equality_rhs.append(np.zeros(parallel_matrix.shape[0], dtype=float))
    full_matrix = np.vstack(equality_rows)
    full_rhs = np.concatenate(equality_rhs)
    constraint_matrix, constraint_rhs = _independent_equality_rows(
        full_matrix,
        full_rhs,
    )

    flexible_array = np.array(active_flexible_indexes, dtype=int)

    def objective(projected: np.ndarray) -> float:
        delta = projected[flexible_array] - desired[flexible_array]
        return float(np.dot(delta, delta))

    def gradient(projected: np.ndarray) -> np.ndarray:
        result = np.zeros(len(variables), dtype=float)
        result[flexible_array] = 2.0 * (
            projected[flexible_array] - desired[flexible_array]
        )
        return result

    constraints = ()
    if constraint_matrix.shape[0]:
        constraints = (
            {
                "type": "eq",
                "fun": lambda projected: constraint_matrix @ projected
                - constraint_rhs,
                "jac": lambda _projected: constraint_matrix,
            },
        )
    projection = minimize(
        objective,
        original,
        jac=gradient,
        bounds=list(zip(projection_lower.tolist(), projection_upper.tolist())),
        constraints=constraints,
        method="SLSQP",
        options={
            "ftol": optimization_ftol,
            "maxiter": optimization_max_iterations,
            "disp": False,
        },
    )
    projected = np.asarray(getattr(projection, "x", original), dtype=float)
    if projected.shape != original.shape or not np.all(np.isfinite(projected)):
        return original
    projected = np.clip(projected, projection_lower, projection_upper)
    equality_error = (
        float(np.max(np.abs(constraint_matrix @ projected - constraint_rhs)))
        if constraint_matrix.shape[0]
        else 0.0
    )
    if not projection.success or equality_error > tolerance:
        return original
    return projected


def _converter_variable(
    row: Mapping[str, Any],
    topology: ResourceTopology,
    converter_step_ratio: float,
    converter_efficiency: float = 1.0,
) -> Optional[_Variable]:
    """Build a converter variable using positive DC-to-AC system power."""

    if not row.get("online") or not row.get("commandable"):
        return None
    key = _device_key(row)
    endpoints = topology.converter_component_ids.get(key)
    current_p_ac = _number(row.get("currentKw"))
    minimum_p_ac = _number(row.get("signedMinTargetKw"))
    maximum_p_ac = _number(row.get("signedMaxTargetKw"))
    if (
        endpoints is None
        or current_p_ac is None
        or minimum_p_ac is None
        or maximum_p_ac is None
        or minimum_p_ac > maximum_p_ac
        or not all(key)
    ):
        return None
    try:
        # Runtime rows use the P_AC terminal convention. The optimizer exposes
        # one system convention instead: positive DC-to-AC, negative AC-to-DC.
        p_ac_ac_coefficient, p_ac_dc_coefficient = (
            converter_balance_coefficients(AC_TO_DC)
        )
        current = converter_power_in_dc_to_ac_convention(
            current_p_ac,
            AC_TO_DC,
            "P_AC",
        )
        converted_limits = (
            converter_power_in_dc_to_ac_convention(
                minimum_p_ac,
                AC_TO_DC,
                "P_AC",
            ),
            converter_power_in_dc_to_ac_convention(
                maximum_p_ac,
                AC_TO_DC,
                "P_AC",
            ),
        )
    except ValueError:
        return None
    minimum = min(converted_limits)
    maximum = max(converted_limits)
    ac_balance_coefficient = -p_ac_ac_coefficient
    dc_balance_coefficient = -p_ac_dc_coefficient
    if (
        abs(abs(ac_balance_coefficient) - 1.0) > EPSILON
        or abs(abs(dc_balance_coefficient) - 1.0) > EPSILON
        or abs(ac_balance_coefficient + dc_balance_coefficient) > EPSILON
    ):
        return None
    # 变流器效率损耗建模：优先读取设备自身效率；无显式效率且模型 r1=r2=0（无损）时对齐模拟台取 1.0，
    # 避免对无损变流器凭空引入 4% 虚假平衡偏差。
    row_eff = _number(row.get("efficiency"))
    raw_row = row.get("raw") if isinstance(row.get("raw"), Mapping) else {}
    if row_eff is None:
        row_eff = _number(raw_row.get("efficiency"))
    if row_eff is not None and 0.5 <= float(row_eff) <= 1.0:
        eff = float(row_eff)
    else:
        r1_val = _number(row.get("r1", raw_row.get("r1")))
        r2_val = _number(row.get("r2", raw_row.get("r2")))
        if (
            r1_val is not None
            and r2_val is not None
            and abs(r1_val) <= EPSILON
            and abs(r2_val) <= EPSILON
        ):
            eff = 1.0
        else:
            eff = float(converter_efficiency)
    eff = min(1.0, max(0.5, eff))
    base_dc_balance_coefficient = dc_balance_coefficient
    if eff < 1.0 - EPSILON:
        # 约定 current >= 0 表示 DC->AC（DC 侧须多供 1/eff），current < 0 表示 AC->DC（DC 侧仅获得 eff）
        if current >= -EPSILON:
            dc_balance_coefficient = base_dc_balance_coefficient / eff
        else:
            dc_balance_coefficient = base_dc_balance_coefficient * eff

    allocation_capacity_kw = _number(row.get("transferCapacityKw"))
    if allocation_capacity_kw is None or allocation_capacity_kw <= EPSILON:
        allocation_capacity_kw = max(abs(minimum), abs(maximum))
    if allocation_capacity_kw <= EPSILON:
        return None
    requires_safety = bool(
        current < minimum - EPSILON or current > maximum + EPSILON
    )
    # 恢复变流器常规爬坡步长限制（0 或 >=1 时不限步长；安全越限或平衡需要时由两阶段机制自动放开）
    if 0.0 < converter_step_ratio < 1.0 - EPSILON:
        normal_step_kw = converter_step_ratio * allocation_capacity_kw
        lower = max(minimum, current - normal_step_kw)
        upper = min(maximum, current + normal_step_kw)
        if lower > upper + EPSILON:
            lower = minimum
            upper = maximum
    else:
        normal_step_kw = math.inf
        lower = minimum
        upper = maximum
    # 计入双向效率损耗（eff < 1）时，单拍约束在同号半区（先归零下一拍再换向），
    # 杜绝单拍跨零线性化时把能量损耗误算为凭空增益（常规步长与安全放开区间均遵守）。
    safety_minimum = minimum
    safety_maximum = maximum
    if eff < 1.0 - EPSILON:
        if current > EPSILON and lower < 0.0 <= upper:
            lower = 0.0
        elif current < -EPSILON and upper > 0.0 >= lower:
            upper = 0.0
        if current > EPSILON and safety_minimum < 0.0 <= safety_maximum:
            safety_minimum = 0.0
        elif current < -EPSILON and safety_maximum > 0.0 >= safety_minimum:
            safety_maximum = 0.0
    return _Variable(
        key=key,
        kind="converter",
        current_kw=current,
        lower_kw=lower,
        upper_kw=upper,
        ac_component_id=endpoints[0],
        dc_component_id=endpoints[1],
        ac_balance_coefficient=ac_balance_coefficient,
        dc_balance_coefficient=dc_balance_coefficient,
        allocation_capacity_kw=allocation_capacity_kw,
        safety_lower_kw=safety_minimum,
        safety_upper_kw=safety_maximum,
        requires_safety_correction=requires_safety,
        normal_step_kw=normal_step_kw,
        converter_efficiency=eff,
        converter_base_dc_coefficient=base_dc_balance_coefficient,
    )


def _independent_equality_rows(matrix: np.ndarray, rhs: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    if matrix.size == 0:
        return matrix, rhs
    if matrix.shape[0] <= 1:
        if float(np.linalg.norm(matrix[0])) <= OPTIMIZATION_RANK_TOLERANCE:
            return np.zeros((0, matrix.shape[1]), dtype=float), np.zeros(0, dtype=float)
        return matrix, rhs
    # 单次列主元 QR 分解 O(m*n*min(m,n))，取代循环内逐行重复 SVD 分解 O(m^2*n*min(m,n))
    try:
        from scipy.linalg import qr as _scipy_qr

        r_mat, piv = _scipy_qr(matrix.T, mode="r", pivoting=True)
        diag = np.abs(np.diag(r_mat)) if r_mat.size else np.zeros(0, dtype=float)
        if diag.size == 0 or float(diag[0]) <= OPTIMIZATION_RANK_TOLERANCE:
            return np.zeros((0, matrix.shape[1]), dtype=float), np.zeros(0, dtype=float)
        tol = max(OPTIMIZATION_RANK_TOLERANCE, float(diag[0]) * max(matrix.shape) * 1e-12)
        rank = int(np.sum(diag > tol))
        selected = sorted(int(idx) for idx in piv[:rank])
        if not selected:
            return np.zeros((0, matrix.shape[1]), dtype=float), np.zeros(0, dtype=float)
        return matrix[selected, :], rhs[selected]
    except Exception:
        selected: list[int] = []
        rank = 0
        for index in range(matrix.shape[0]):
            candidate = matrix[selected + [index], :]
            candidate_rank = int(
                np.linalg.matrix_rank(
                    candidate,
                    tol=OPTIMIZATION_RANK_TOLERANCE,
                )
            )
            if candidate_rank > rank:
                selected.append(index)
                rank = candidate_rank
        if not selected:
            return np.zeros((0, matrix.shape[1]), dtype=float), np.zeros(0, dtype=float)
        return matrix[selected, :], rhs[selected]


def _island_id(component_ids: Sequence[str]) -> str:
    payload = "\n".join(component_ids).encode("utf-8")
    return f"HYBRID:{hashlib.sha256(payload).hexdigest()[:16]}"


def _blocked_island_result(
    component_ids: Tuple[str, ...],
    variables: Sequence[_Variable],
    reason: str,
) -> IslandOptimizationResult:
    ordered = sorted(
        variables,
        key=lambda item: (
            {"renewable": 0, "diesel": 1, "storage": 2, "converter": 3}.get(
                item.kind,
                9,
            ),
            item.key,
        ),
    )
    return IslandOptimizationResult(
        island_id=_island_id(component_ids),
        component_ids=component_ids,
        device_keys=tuple(item.key for item in ordered),
        success=False,
        status="blocked",
        message=reason,
        target_by_device={},
        active_lower_by_device={item.key: item.lower_kw for item in ordered},
        active_upper_by_device={item.key: item.upper_kw for item in ordered},
        balance_residual_by_component={},
        objective_value=0.0,
        renewable_curtailment_kw=0.0,
        diesel_target_kw=sum(
            item.current_kw for item in ordered if item.kind == "diesel"
        ),
        curtailment_square_weight=0.0,
        adjustment_square_weight=0.0,
        balance_delta_square_weight=0.0,
        balance_delta_by_side={},
        max_balance_delta_kw=0.0,
        step_override_applied=False,
        step_override_devices=(),
        iterations=0,
        variable_count=len(ordered),
        constraint_count=0,
        equality_constraint_count=0,
        inequality_constraint_count=0,
        bound_count=len(ordered),
        build_seconds=0.0,
        solver_seconds=0.0,
        storage_balance_seconds=0.0,
        postprocess_seconds=0.0,
        solve_seconds=0.0,
    )


from collections import OrderedDict as _OrderedDict
import threading as _threading

_ISLAND_WARM_START_LOCK = _threading.Lock()
_ISLAND_WARM_START_CACHE: "_OrderedDict[Tuple[str, Tuple[DeviceKey, ...]], np.ndarray]" = _OrderedDict()
_ISLAND_WARM_START_CACHE_MAX = 64


def _select_slsqp_initial_guess(
    island_id: str,
    variables: Sequence[_Variable],
    fallback: np.ndarray,
    active_lower: np.ndarray,
    active_upper: np.ndarray,
    secondary_matrix: np.ndarray,
    secondary_rhs: np.ndarray,
    base_objective: Any,
    balance_tolerance_kw: float,
) -> np.ndarray:
    """复用上一周期同拓扑可行解作为 SLSQP 热启动初值，仅在严格可行且不劣于基准解时采用（线程安全 LRU）。"""
    key = (str(island_id), tuple(v.key for v in variables))
    with _ISLAND_WARM_START_LOCK:
        cached = _ISLAND_WARM_START_CACHE.get(key)
        if cached is not None:
            _ISLAND_WARM_START_CACHE.move_to_end(key)
            cached = cached.copy()
    if cached is None or cached.shape != fallback.shape:
        return fallback
    candidate = np.clip(cached, active_lower, active_upper)
    if not np.all(np.isfinite(candidate)):
        return fallback
    if secondary_matrix.shape[0]:
        residual = float(np.max(np.abs(secondary_matrix @ candidate - secondary_rhs)))
        if residual > balance_tolerance_kw:
            return fallback
    try:
        if float(base_objective(candidate)) <= float(base_objective(fallback)) + 1e-9:
            return candidate
    except Exception:
        return fallback
    return fallback


def _record_slsqp_warm_start(
    island_id: str,
    variables: Sequence[_Variable],
    solution: np.ndarray,
) -> None:
    key = (str(island_id), tuple(v.key for v in variables))
    arr = np.array(solution, dtype=float, copy=True)
    with _ISLAND_WARM_START_LOCK:
        if key in _ISLAND_WARM_START_CACHE:
            _ISLAND_WARM_START_CACHE.move_to_end(key)
        elif len(_ISLAND_WARM_START_CACHE) >= _ISLAND_WARM_START_CACHE_MAX:
            _ISLAND_WARM_START_CACHE.popitem(last=False)
        _ISLAND_WARM_START_CACHE[key] = arr


def _solve_island(
    component_ids: Tuple[str, ...],
    variables: Sequence[_Variable],
    *,
    renewable_curtailment_weight: float,
    diesel_output_weight: float,
    curtailment_square_weight: float,
    adjustment_square_weight: float,
    balance_delta_square_weight: float,
    balance_tolerance_kw: float,
    bound_tolerance_kw: float,
    optimization_ftol: float,
    optimization_max_iterations: int,
    storage_soc_rebalance_deadband: float = 0.02,
    external_injection_delta_by_side: Optional[Mapping[str, float]] = None,
    external_injection_delta_by_component: Optional[Mapping[Tuple[str, str], float]] = None,
    balance_delta_warning_kw: float = 0.0,
) -> IslandOptimizationResult:
    started = time.perf_counter()
    island_id = _island_id(component_ids)
    ordered = sorted(
        variables,
        key=lambda item: (
            {"renewable": 0, "diesel": 1, "storage": 2, "converter": 3}.get(item.kind, 9),
            item.key,
        ),
    )
    count = len(ordered)
    if count == 0:
        total_seconds = time.perf_counter() - started
        return IslandOptimizationResult(
            island_id=island_id,
            component_ids=component_ids,
            device_keys=(),
            success=True,
            status="empty",
            message="拓扑岛没有可调设备",
            target_by_device={},
            active_lower_by_device={},
            active_upper_by_device={},
            balance_residual_by_component={},
            objective_value=0.0,
            renewable_curtailment_kw=0.0,
            diesel_target_kw=0.0,
            curtailment_square_weight=0.0,
            adjustment_square_weight=0.0,
            balance_delta_square_weight=balance_delta_square_weight,
            balance_delta_by_side={},
            max_balance_delta_kw=0.0,
            step_override_applied=False,
            step_override_devices=(),
            iterations=0,
            variable_count=0,
            constraint_count=0,
            equality_constraint_count=0,
            inequality_constraint_count=0,
            bound_count=0,
            build_seconds=total_seconds,
            solver_seconds=0.0,
            storage_balance_seconds=0.0,
            postprocess_seconds=0.0,
            solve_seconds=total_seconds,
        )

    # 按独立电气分量（component_id）逐行建立功率平衡方程，杜绝将电气隔离的多直流/多交流分量折叠为单行隔空配平。
    balance_component_entries: list[Tuple[str, str]] = []
    seen_components: set[str] = set()
    for item in ordered:
        if item.kind == "converter":
            for comp_id, side_label in (
                (item.ac_component_id or "AC", "AC"),
                (item.dc_component_id or "DC", "DC"),
            ):
                if comp_id not in seen_components:
                    seen_components.add(comp_id)
                    balance_component_entries.append((comp_id, side_label))
        else:
            comp_id = item.component_id or item.side
            if comp_id not in seen_components:
                seen_components.add(comp_id)
                balance_component_entries.append((comp_id, item.side))
    balance_components = tuple(balance_component_entries)
    index_by_component = {
        comp_id: index for index, (comp_id, _side) in enumerate(balance_components)
    }
    dc_row_indexes = [
        index for index, (_comp_id, side) in enumerate(balance_components) if side == "DC"
    ]
    ac_row_indexes = [
        index for index, (_comp_id, side) in enumerate(balance_components) if side == "AC"
    ]
    matrix = np.zeros((len(balance_components), count), dtype=float)
    current = np.array([item.current_kw for item in ordered], dtype=float)
    normal_lower = np.array([item.lower_kw for item in ordered], dtype=float)
    normal_upper = np.array([item.upper_kw for item in ordered], dtype=float)
    for column, item in enumerate(ordered):
        if item.kind == "converter":
            matrix[index_by_component[item.ac_component_id or "AC"], column] += item.ac_balance_coefficient
            matrix[index_by_component[item.dc_component_id or "DC"], column] += item.dc_balance_coefficient
        else:
            matrix[index_by_component[item.component_id or item.side], column] += 1.0

    external_delta_list: list[float] = []
    if external_injection_delta_by_component:
        for comp_id, side in balance_components:
            external_delta_list.append(
                float(external_injection_delta_by_component.get((comp_id, side), 0.0))
            )
    else:
        side_counts: Dict[str, int] = {}
        for _comp_id, side in balance_components:
            side_counts[side] = side_counts.get(side, 0) + 1
        for _comp_id, side in balance_components:
            raw_ext = float((external_injection_delta_by_side or {}).get(side, 0.0))
            external_delta_list.append(raw_ext / max(1, side_counts.get(side, 1)))
    external_delta_vector = np.array(external_delta_list, dtype=float)
    # 外部已知注入增量（如氢能单拍协同：制氢增耗电为负注入、燃料电池增发电为正注入）
    rhs = matrix @ current - external_delta_vector
    parallel_rows: list[np.ndarray] = []
    parallel_groups: Dict[Tuple[str, str], list[int]] = {}
    for index, item in enumerate(ordered):
        if item.kind != "converter":
            continue
        parallel_groups.setdefault(
            (item.ac_component_id, item.dc_component_id),
            [],
        ).append(index)
    for indexes in parallel_groups.values():
        if len(indexes) < 2:
            continue
        reference_index = indexes[0]
        reference_capacity = ordered[reference_index].allocation_capacity_kw
        for index in indexes[1:]:
            cap_i = ordered[index].allocation_capacity_kw
            # 按容量归一化均流等式系数至 [-1, 1]，确保矩阵条件数稳定且残差量纲严格为 kW
            scale = max(EPSILON, abs(reference_capacity), abs(cap_i))
            row = np.zeros(count, dtype=float)
            row[index] = reference_capacity / scale
            row[reference_index] = -cap_i / scale
            parallel_rows.append(row)
    parallel_matrix = (
        np.vstack(parallel_rows)
        if parallel_rows
        else np.zeros((0, count), dtype=float)
    )
    parallel_rhs = np.zeros(parallel_matrix.shape[0], dtype=float)
    equality_constraint_count = len(balance_components) + int(parallel_matrix.shape[0])
    inequality_constraint_count = 0
    bound_count = count
    build_seconds = time.perf_counter() - started
    solver_started = time.perf_counter()

    def combined_equalities(
        balance_matrix: np.ndarray,
        balance_rhs: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        if parallel_matrix.shape[0] == 0:
            return balance_matrix, balance_rhs
        if balance_matrix.shape[0] == 0:
            return parallel_matrix, parallel_rhs
        return (
            np.vstack((balance_matrix, parallel_matrix)),
            np.concatenate((balance_rhs, parallel_rhs)),
        )

    def exact_balance_feasibility(
        active_lower: np.ndarray,
        active_upper: np.ndarray,
    ) -> Any:
        equality_matrix, equality_rhs = combined_equalities(matrix, rhs)
        return linprog(
            np.zeros(count, dtype=float),
            A_eq=equality_matrix if equality_matrix.shape[0] else None,
            b_eq=equality_rhs if equality_matrix.shape[0] else None,
            bounds=list(zip(active_lower.tolist(), active_upper.tolist())),
            method="highs",
        )

    def already_feasible(
        values: np.ndarray,
        active_lower: np.ndarray,
        active_upper: np.ndarray,
    ) -> bool:
        if (
            values.shape != active_lower.shape
            or not np.all(np.isfinite(values))
            or np.any(values < active_lower)
            or np.any(values > active_upper)
        ):
            return False
        equality_matrix, equality_rhs = combined_equalities(matrix, rhs)
        if equality_matrix.shape[0] == 0:
            return True
        residual = equality_matrix @ values - equality_rhs
        return bool(
            np.all(np.isfinite(residual))
            and np.max(np.abs(residual)) <= EPSILON
        )

    def box_proven_infeasible(
        active_lower: np.ndarray,
        active_upper: np.ndarray,
    ) -> bool:
        """基于区间算术的严格必要条件检查：若任意平衡行或总和行必然越界，则直接短路 HiGHS 求解。"""
        if matrix.shape[0] == 0:
            return False
        tol = 1e-6
        pos = np.maximum(matrix, 0.0)
        neg = np.minimum(matrix, 0.0)
        row_min = pos @ active_lower + neg @ active_upper
        row_max = pos @ active_upper + neg @ active_lower
        if bool(np.any(row_min > rhs + tol) or np.any(row_max < rhs - tol)):
            return True
        if matrix.shape[0] >= 2:
            total_row = np.sum(matrix, axis=0)
            total_rhs = float(np.sum(rhs))
            t_pos = np.maximum(total_row, 0.0)
            t_neg = np.minimum(total_row, 0.0)
            total_min = float(t_pos @ active_lower + t_neg @ active_upper)
            total_max = float(t_pos @ active_upper + t_neg @ active_lower)
            if total_min > total_rhs + tol or total_max < total_rhs - tol:
                return True
        return False

    warm_cache_key = (str(island_id), tuple(item.key for item in ordered))
    with _ISLAND_WARM_START_LOCK:
        raw_warm = _ISLAND_WARM_START_CACHE.get(warm_cache_key)
        warm_cached = raw_warm.copy() if raw_warm is not None else None

    feasibility_values: Optional[np.ndarray] = None
    feasibility_success = already_feasible(current, normal_lower, normal_upper)
    if feasibility_success:
        # ``rhs`` is built from the current operating point. In the common
        # topology-stable case that point is already inside all active bounds,
        # so a separate HiGHS feasibility solve would only rediscover it.
        feasibility_values = current.copy()
    elif warm_cached is not None and already_feasible(warm_cached, normal_lower, normal_upper):
        feasibility_success = True
        feasibility_values = warm_cached.copy()
    elif not box_proven_infeasible(normal_lower, normal_upper):
        feasibility = exact_balance_feasibility(normal_lower, normal_upper)
        feasibility_success = bool(feasibility.success and feasibility.x is not None)
        if feasibility_success:
            feasibility_values = np.asarray(feasibility.x, dtype=float)
    active_lower = normal_lower
    active_upper = normal_upper
    has_safety_correction = any(
        item.kind in {"storage", "diesel"} and item.requires_safety_correction
        for item in ordered
    )
    if not feasibility_success and has_safety_correction:
        # 阶段 1 应急放开：优先允许新能源应急弃电至硬下限（应对储能过充/满荷），其余设备保持常规爬坡。
        safety_lower = normal_lower.copy()
        for index, item in enumerate(ordered):
            if item.kind == "renewable" and item.safety_lower_kw is not None:
                safety_lower[index] = item.safety_lower_kw
        if warm_cached is not None and already_feasible(warm_cached, safety_lower, normal_upper):
            feasibility_success = True
            feasibility_values = warm_cached.copy()
            active_lower = safety_lower
        elif not box_proven_infeasible(safety_lower, normal_upper):
            safety_feasibility = exact_balance_feasibility(
                safety_lower,
                normal_upper,
            )
            if safety_feasibility.success and safety_feasibility.x is not None:
                feasibility_success = True
                feasibility_values = np.asarray(safety_feasibility.x, dtype=float)
                active_lower = safety_lower
        # 阶段 2 应急放开：若仍不可行（例如夜间无新能源且构网储能贴底急需柴发/变流器快速顶上止放），
        # 放开柴发与变流器爬坡步长至其安全区间，杜绝强留平衡松弛砸向构网储能造成过放告警。
        if not feasibility_success:
            emergency_lower = safety_lower.copy()
            emergency_upper = normal_upper.copy()
            for index, item in enumerate(ordered):
                if item.kind in {"diesel", "converter"}:
                    if item.safety_lower_kw is not None:
                        emergency_lower[index] = min(emergency_lower[index], item.safety_lower_kw)
                    if item.safety_upper_kw is not None:
                        emergency_upper[index] = max(emergency_upper[index], item.safety_upper_kw)
            if warm_cached is not None and already_feasible(
                warm_cached, emergency_lower, emergency_upper
            ):
                feasibility_success = True
                feasibility_values = warm_cached.copy()
                active_lower = emergency_lower
                active_upper = emergency_upper
            elif not box_proven_infeasible(emergency_lower, emergency_upper):
                emergency_feasibility = exact_balance_feasibility(
                    emergency_lower,
                    emergency_upper,
                )
                if emergency_feasibility.success and emergency_feasibility.x is not None:
                    feasibility_success = True
                    feasibility_values = np.asarray(emergency_feasibility.x, dtype=float)
                    active_lower = emergency_lower
                    active_upper = emergency_upper
            # 阶段 3 兜底：若极端孤岛无足够外部余量满足构网储能贴边防漂移软缓冲，
            # 退回构网储能硬安全边界（仍严守 0 kW 禁止越界方向），确保优化问题保持可行。
            if not feasibility_success:
                relaxed_lower = emergency_lower.copy()
                relaxed_upper = emergency_upper.copy()
                changed_balance_bound = False
                for index, item in enumerate(ordered):
                    if item.kind == "storage" and not item.storage_forced_direction:
                        if (
                            item.safety_lower_kw is not None
                            and item.safety_lower_kw < relaxed_lower[index] - EPSILON
                        ):
                            relaxed_lower[index] = item.safety_lower_kw
                            changed_balance_bound = True
                        if (
                            item.safety_upper_kw is not None
                            and item.safety_upper_kw > relaxed_upper[index] + EPSILON
                        ):
                            relaxed_upper[index] = item.safety_upper_kw
                            changed_balance_bound = True
                if changed_balance_bound and not box_proven_infeasible(
                    relaxed_lower, relaxed_upper
                ):
                    relaxed_feasibility = exact_balance_feasibility(
                        relaxed_lower,
                        relaxed_upper,
                    )
                    if relaxed_feasibility.success and relaxed_feasibility.x is not None:
                        feasibility_success = True
                        feasibility_values = np.asarray(
                            relaxed_feasibility.x, dtype=float
                        )
                        active_lower = relaxed_lower
                        active_upper = relaxed_upper

    renewable_indexes = [index for index, item in enumerate(ordered) if item.kind == "renewable"]
    diesel_indexes = [index for index, item in enumerate(ordered) if item.kind == "diesel"]
    adjustment_indexes = [
        index for index, item in enumerate(ordered) if item.kind in {"diesel", "storage"}
    ]
    renewable_available = np.array(
        [ordered[index].renewable_available_kw or 0.0 for index in renewable_indexes],
        dtype=float,
    )
    def base_objective(device_values: np.ndarray) -> float:
        value = 0.0
        if renewable_indexes:
            curtailment = renewable_available - device_values[renewable_indexes]
            value += renewable_curtailment_weight * float(np.sum(curtailment))
            value += curtailment_square_weight * float(np.dot(curtailment, curtailment))
        if diesel_indexes:
            value += diesel_output_weight * float(np.sum(device_values[diesel_indexes]))
        if adjustment_indexes:
            adjustment = (
                device_values[adjustment_indexes] - current[adjustment_indexes]
            )
            value += adjustment_square_weight * float(np.dot(adjustment, adjustment))
        return value

    def base_gradient(device_values: np.ndarray) -> np.ndarray:
        result = np.zeros(count, dtype=float)
        if renewable_indexes:
            curtailment = renewable_available - device_values[renewable_indexes]
            result[renewable_indexes] = (
                -renewable_curtailment_weight
                - 2.0 * curtailment_square_weight * curtailment
            )
        if diesel_indexes:
            result[diesel_indexes] += diesel_output_weight
        if adjustment_indexes:
            result[adjustment_indexes] += (
                2.0
                * adjustment_square_weight
                * (
                    device_values[adjustment_indexes]
                    - current[adjustment_indexes]
                )
            )
        return result

    def balance_delta(device_values: np.ndarray) -> np.ndarray:
        # A * P + delta = A * P_current.  Eliminating delta from the two
        # balance equations gives this exact expression while leaving only
        # box-constrained device targets for the numerical optimizer.
        return rhs - matrix @ device_values

    def dc_priority_minimum_delta(
        active_lower: np.ndarray,
        active_upper: np.ndarray,
    ) -> Tuple[np.ndarray, bool]:
        """Minimize DC slack first, then AC slack for converter conflicts.

        This priority is only used after exact AC/DC balance has proved
        infeasible in an island containing a grid-boundary converter. It does
        not enter the normal dispatch objective, so AC and DC renewables still
        compete for feasible headroom under the same curtailment objective.
        """
        device_bounds = list(zip(active_lower.tolist(), active_upper.tolist()))
        extended_bounds = device_bounds + [(0.0, None)]
        extended_parallel_matrix = (
            np.hstack(
                (
                    parallel_matrix,
                    np.zeros((parallel_matrix.shape[0], 1), dtype=float),
                )
            )
            if parallel_matrix.shape[0]
            else None
        )

        stage_one_rows = []
        stage_one_rhs_vals = []
        for dc_index in dc_row_indexes:
            dc_row = matrix[dc_index]
            stage_one_rows.append(np.append(-dc_row, -1.0))
            stage_one_rows.append(np.append(dc_row, -1.0))
            stage_one_rhs_vals.extend((-rhs[dc_index], rhs[dc_index]))
        stage_one_inequalities = np.vstack(stage_one_rows)
        stage_one_rhs = np.array(stage_one_rhs_vals, dtype=float)
        stage_one_objective = np.zeros(count + 1, dtype=float)
        stage_one_objective[-1] = 1.0
        stage_one = linprog(
            stage_one_objective,
            A_ub=stage_one_inequalities,
            b_ub=stage_one_rhs,
            A_eq=extended_parallel_matrix,
            b_eq=parallel_rhs if parallel_matrix.shape[0] else None,
            bounds=extended_bounds,
            method="highs",
        )
        if not stage_one.success or stage_one.x is None:
            return np.clip(current, active_lower, active_upper), False

        minimum_dc_delta = max(0.0, float(stage_one.x[-1]))
        priority_tolerance = max(EPSILON, min(1e-6, optimization_ftol))
        dc_delta_limit = minimum_dc_delta + priority_tolerance
        stage_two_rows = []
        stage_two_rhs_vals = []
        for ac_index in ac_row_indexes:
            ac_row = matrix[ac_index]
            stage_two_rows.append(np.append(-ac_row, -1.0))
            stage_two_rows.append(np.append(ac_row, -1.0))
            stage_two_rhs_vals.extend((-rhs[ac_index], rhs[ac_index]))
        for dc_index in dc_row_indexes:
            dc_row = matrix[dc_index]
            stage_two_rows.append(np.append(-dc_row, 0.0))
            stage_two_rows.append(np.append(dc_row, 0.0))
            stage_two_rhs_vals.extend((dc_delta_limit - rhs[dc_index], dc_delta_limit + rhs[dc_index]))
        stage_two_inequalities = np.vstack(stage_two_rows)
        stage_two_rhs = np.array(stage_two_rhs_vals, dtype=float)
        stage_two_objective = np.zeros(count + 1, dtype=float)
        stage_two_objective[-1] = 1.0
        stage_two = linprog(
            stage_two_objective,
            A_ub=stage_two_inequalities,
            b_ub=stage_two_rhs,
            A_eq=extended_parallel_matrix,
            b_eq=parallel_rhs if parallel_matrix.shape[0] else None,
            bounds=extended_bounds,
            method="highs",
        )
        if not stage_two.success or stage_two.x is None:
            return np.asarray(stage_one.x[:count], dtype=float), False
        return np.asarray(stage_two.x[:count], dtype=float), True

    def objective(device_values: np.ndarray) -> float:
        delta = balance_delta(device_values)
        return base_objective(device_values) + balance_delta_square_weight * float(
            np.dot(delta, delta)
        )

    def solve_with_bounds(
        active_lower: np.ndarray,
        active_upper: np.ndarray,
        initial: Optional[np.ndarray] = None,
    ) -> Tuple[Any, np.ndarray, np.ndarray, bool, bool]:
        primary_converged = True
        if initial is not None:
            minimum_delta_values = np.clip(
                initial,
                active_lower,
                active_upper,
            )
        elif (
            ac_row_indexes
            and dc_row_indexes
            and any(item.kind == "converter" for item in ordered)
        ):
            minimum_delta_values, primary_converged = dc_priority_minimum_delta(
                active_lower,
                active_upper,
            )
        elif parallel_matrix.shape[0]:
            parallel_feasibility = linprog(
                np.zeros(count, dtype=float),
                A_eq=parallel_matrix,
                b_eq=parallel_rhs,
                bounds=list(zip(active_lower.tolist(), active_upper.tolist())),
                method="highs",
            )
            minimum_delta_values = np.asarray(
                parallel_feasibility.x
                if parallel_feasibility.success
                else np.clip(current, active_lower, active_upper),
                dtype=float,
            )
            parallel_constraints = (
                {
                    "type": "eq",
                    "fun": lambda values: parallel_matrix @ values,
                    "jac": lambda _values: parallel_matrix,
                },
            )
            primary_result = minimize(
                lambda values: float(
                    np.dot(balance_delta(values), balance_delta(values))
                ),
                minimum_delta_values,
                jac=lambda values: -2.0 * matrix.T @ balance_delta(values),
                bounds=list(zip(active_lower.tolist(), active_upper.tolist())),
                constraints=parallel_constraints,
                method="SLSQP",
                options={
                    "ftol": optimization_ftol,
                    "maxiter": optimization_max_iterations,
                    "disp": False,
                },
            )
            primary_values = np.asarray(
                getattr(primary_result, "x", minimum_delta_values),
                dtype=float,
            )
            if (
                primary_values.shape == minimum_delta_values.shape
                and np.all(np.isfinite(primary_values))
            ):
                minimum_delta_values = np.clip(
                    primary_values,
                    active_lower,
                    active_upper,
                )
            primary_converged = bool(primary_result.success)
        else:
            minimum_delta_values = np.clip(
                current,
                active_lower,
                active_upper,
            )
            free_indexes = np.flatnonzero(
                active_upper - active_lower > bound_tolerance_kw
            )
            fixed_indexes = np.flatnonzero(
                active_upper - active_lower <= bound_tolerance_kw
            )
            if free_indexes.size:
                reduced_rhs = rhs.copy()
                if fixed_indexes.size:
                    reduced_rhs -= (
                        matrix[:, fixed_indexes]
                        @ active_lower[fixed_indexes]
                    )
                    minimum_delta_values[fixed_indexes] = active_lower[
                        fixed_indexes
                    ]
                least_squares = lsq_linear(
                    matrix[:, free_indexes],
                    reduced_rhs,
                    bounds=(
                        active_lower[free_indexes],
                        active_upper[free_indexes],
                    ),
                    tol=optimization_ftol,
                    lsmr_tol="auto",
                    max_iter=optimization_max_iterations,
                )
                if least_squares.x is not None and np.all(
                    np.isfinite(least_squares.x)
                ):
                    minimum_delta_values[free_indexes] = least_squares.x
                primary_converged = bool(least_squares.success)
        minimum_delta = balance_delta(minimum_delta_values)
        target_balance = matrix @ minimum_delta_values
        target_matrix, target_rhs = combined_equalities(
            matrix,
            target_balance,
        )
        secondary_matrix, secondary_rhs = _independent_equality_rows(
            target_matrix,
            target_rhs,
        )
        constraints = []
        if secondary_matrix.shape[0]:
            constraints.append(
                {
                    "type": "eq",
                    "fun": lambda values: secondary_matrix @ values
                    - secondary_rhs,
                    "jac": lambda _values: secondary_matrix,
                }
            )
        active_bounds = list(zip(active_lower.tolist(), active_upper.tolist()))
        initial_guess = _select_slsqp_initial_guess(
            island_id,
            ordered,
            minimum_delta_values,
            active_lower,
            active_upper,
            secondary_matrix,
            secondary_rhs,
            base_objective,
            balance_tolerance_kw,
        )
        solved_result = minimize(
            base_objective,
            initial_guess,
            jac=base_gradient,
            bounds=active_bounds,
            constraints=constraints,
            method="SLSQP",
            options={
                "ftol": optimization_ftol,
                "maxiter": optimization_max_iterations,
                "disp": False,
            },
        )
        raw_values = np.asarray(
            getattr(solved_result, "x", minimum_delta_values),
            dtype=float,
        )
        if raw_values.shape != minimum_delta_values.shape or not np.all(
            np.isfinite(raw_values)
        ):
            raw_values = minimum_delta_values
        solved_device_values = np.clip(
            raw_values,
            active_lower,
            active_upper,
        )
        solved_balance_delta = balance_delta(solved_device_values)
        delta_drift = float(
            np.max(np.abs(solved_balance_delta - minimum_delta))
        ) if minimum_delta.size else 0.0
        if not solved_result.success or delta_drift > balance_tolerance_kw:
            solved_device_values = minimum_delta_values
            solved_balance_delta = minimum_delta
        else:
            _record_slsqp_warm_start(island_id, ordered, solved_device_values)
        bounds_valid = bool(
            np.all(solved_device_values >= active_lower - bound_tolerance_kw)
            and np.all(solved_device_values <= active_upper + bound_tolerance_kw)
        )
        parallel_valid = bool(
            parallel_matrix.shape[0] == 0
            or np.max(np.abs(parallel_matrix @ solved_device_values))
            <= bound_tolerance_kw
        )
        valid = bool(
            primary_converged
            and np.all(np.isfinite(solved_device_values))
            and np.all(np.isfinite(solved_balance_delta))
            and bounds_valid
            and parallel_valid
        )
        return (
            solved_result,
            solved_device_values,
            solved_balance_delta,
            valid,
            bool(primary_converged and solved_result.success),
        )

    solved, values, solved_balance_delta, success, solver_converged = solve_with_bounds(
        active_lower,
        active_upper,
        feasibility_values if feasibility_success else None,
    )
    # 修正有损变流器空载（current==0）反向充电时的分段线性化系数：
    # 初始按 DC->AC (1/eff) 求解，若解出 AC->DC 充电方向（values < 0），切换为 AC->DC 系数 (eff) 并锁上界 0 重解，
    # 杜绝 >100% 效率凭空造电。
    if success:
        zero_reversed_cols = [
            col
            for col, item in enumerate(ordered)
            if item.kind == "converter"
            and item.converter_efficiency < 1.0 - EPSILON
            and abs(item.current_kw) <= EPSILON
            and float(values[col]) < -EPSILON
        ]
        if zero_reversed_cols:
            for col in zero_reversed_cols:
                item = ordered[col]
                dc_row_idx = index_by_component[item.dc_component_id or "DC"]
                matrix[dc_row_idx, col] = (
                    item.converter_base_dc_coefficient * item.converter_efficiency
                )
                active_upper = active_upper.copy()
                active_upper[col] = min(float(active_upper[col]), 0.0)
            rhs = matrix @ current - external_delta_vector
            solved, values, solved_balance_delta, success, solver_converged = solve_with_bounds(
                active_lower,
                active_upper,
                None,
            )
    solver_seconds = time.perf_counter() - solver_started
    if not success:
        total_seconds = time.perf_counter() - started
        return IslandOptimizationResult(
            island_id=island_id,
            component_ids=component_ids,
            device_keys=tuple(item.key for item in ordered),
            success=False,
            status="failed",
            message=str(solved.message),
            target_by_device={},
            active_lower_by_device={
                item.key: float(active_lower[index])
                for index, item in enumerate(ordered)
            },
            active_upper_by_device={
                item.key: float(active_upper[index])
                for index, item in enumerate(ordered)
            },
            balance_residual_by_component={},
            objective_value=None,
            renewable_curtailment_kw=0.0,
            diesel_target_kw=0.0,
            curtailment_square_weight=curtailment_square_weight,
            adjustment_square_weight=adjustment_square_weight,
            balance_delta_square_weight=balance_delta_square_weight,
            balance_delta_by_side={},
            max_balance_delta_kw=0.0,
            step_override_applied=False,
            step_override_devices=(),
            iterations=int(getattr(solved, "nit", 0) or 0) if solved is not None else 0,
            variable_count=count,
            constraint_count=equality_constraint_count + inequality_constraint_count,
            equality_constraint_count=equality_constraint_count,
            inequality_constraint_count=inequality_constraint_count,
            bound_count=bound_count,
            build_seconds=build_seconds,
            solver_seconds=solver_seconds,
            storage_balance_seconds=0.0,
            postprocess_seconds=max(
                0.0,
                total_seconds - build_seconds - solver_seconds,
            ),
            solve_seconds=total_seconds,
        )

    storage_balance_started = time.perf_counter()
    values = _rebalance_storage_targets_by_soc(
        values,
        ordered,
        active_lower,
        active_upper,
        matrix,
        parallel_matrix,
        max(balance_tolerance_kw, bound_tolerance_kw),
        optimization_ftol,
        optimization_max_iterations,
        soc_rebalance_deadband=storage_soc_rebalance_deadband,
    )
    storage_balance_seconds = time.perf_counter() - storage_balance_started
    solved_balance_delta = balance_delta(values)

    values[np.abs(values) < OPTIMIZATION_ZERO_SNAP_TOLERANCE_KW] = 0.0
    solved_balance_delta[
        np.abs(solved_balance_delta) < OPTIMIZATION_ZERO_SNAP_TOLERANCE_KW
    ] = 0.0
    step_override_devices = tuple(
        item.key
        for index, item in enumerate(ordered)
        if abs(values[index] - item.current_kw)
        > item.normal_step_kw + bound_tolerance_kw
    )
    step_override_applied = bool(step_override_devices)
    targets = {item.key: float(values[index]) for index, item in enumerate(ordered)}
    physical_residual_vector = matrix @ values - rhs
    residuals = {
        comp_id: float(physical_residual_vector[index])
        for index, (comp_id, _side) in enumerate(balance_components)
    }
    balance_delta_by_side: Dict[str, float] = {}
    for index, (_comp_id, side) in enumerate(balance_components):
        delta_val = float(solved_balance_delta[index])
        prev_val = balance_delta_by_side.get(side)
        if prev_val is None or abs(delta_val) > abs(prev_val):
            balance_delta_by_side[side] = delta_val
    max_balance_delta_kw = max(
        (abs(float(val)) for val in solved_balance_delta.tolist()),
        default=0.0,
    )
    if (
        not solver_converged
        and not has_safety_correction
        and balance_delta_warning_kw > EPSILON
        and max_balance_delta_kw > balance_delta_warning_kw + balance_tolerance_kw
    ):
        total_seconds = time.perf_counter() - started
        return IslandOptimizationResult(
            island_id=island_id,
            component_ids=component_ids,
            device_keys=tuple(item.key for item in ordered),
            success=False,
            status="failed",
            message=(
                f"optimizer did not converge and residual {max_balance_delta_kw:.3f} kW "
                f"exceeds warning limit {balance_delta_warning_kw:.3f} kW"
            ),
            target_by_device={},
            active_lower_by_device={
                item.key: float(active_lower[index])
                for index, item in enumerate(ordered)
            },
            active_upper_by_device={
                item.key: float(active_upper[index])
                for index, item in enumerate(ordered)
            },
            balance_residual_by_component=residuals,
            objective_value=None,
            renewable_curtailment_kw=0.0,
            diesel_target_kw=0.0,
            curtailment_square_weight=curtailment_square_weight,
            adjustment_square_weight=adjustment_square_weight,
            balance_delta_square_weight=balance_delta_square_weight,
            balance_delta_by_side=balance_delta_by_side,
            max_balance_delta_kw=max_balance_delta_kw,
            step_override_applied=False,
            step_override_devices=(),
            iterations=int(getattr(solved, "nit", 0) or 0) if solved is not None else 0,
            variable_count=count,
            constraint_count=equality_constraint_count + inequality_constraint_count,
            equality_constraint_count=equality_constraint_count,
            inequality_constraint_count=inequality_constraint_count,
            bound_count=bound_count,
            build_seconds=build_seconds,
            solver_seconds=solver_seconds,
            storage_balance_seconds=storage_balance_seconds,
            postprocess_seconds=max(
                0.0,
                total_seconds - build_seconds - solver_seconds - storage_balance_seconds,
            ),
            solve_seconds=total_seconds,
        )
    balance_delta_active = max_balance_delta_kw > balance_tolerance_kw
    renewable_curtailment = sum(
        max(0.0, (item.renewable_available_kw or 0.0) - targets[item.key])
        for item in ordered
        if item.kind == "renewable"
    )
    diesel_target = sum(
        targets[item.key] for item in ordered if item.kind == "diesel"
    )
    if not solver_converged:
        status = "feasible_balance_delta_fallback"
    elif step_override_applied and balance_delta_active:
        status = "optimal_safety_override_with_balance_slack"
    elif balance_delta_active:
        status = "optimal_with_balance_slack"
    elif step_override_applied:
        status = "optimal_safety_override"
    else:
        status = "optimal"
    message = str(solved.message)
    if balance_delta_active:
        message = (
            f"{message}; max(delta_ac, delta_dc)="
            f"{max_balance_delta_kw:.6g} kW"
        )
    total_seconds = time.perf_counter() - started
    return IslandOptimizationResult(
        island_id=island_id,
        component_ids=component_ids,
        device_keys=tuple(item.key for item in ordered),
        success=True,
        status=status,
        message=message,
        target_by_device=targets,
        active_lower_by_device={
            item.key: float(active_lower[index])
            for index, item in enumerate(ordered)
        },
        active_upper_by_device={
            item.key: float(active_upper[index])
            for index, item in enumerate(ordered)
        },
        balance_residual_by_component=residuals,
        objective_value=float(objective(values)),
        renewable_curtailment_kw=renewable_curtailment,
        diesel_target_kw=diesel_target,
        curtailment_square_weight=curtailment_square_weight,
        adjustment_square_weight=adjustment_square_weight,
        balance_delta_square_weight=balance_delta_square_weight,
        balance_delta_by_side=balance_delta_by_side,
        max_balance_delta_kw=max_balance_delta_kw,
        step_override_applied=step_override_applied,
        step_override_devices=step_override_devices,
        iterations=int(getattr(solved, "nit", 0) or 0),
        variable_count=count,
        constraint_count=equality_constraint_count + inequality_constraint_count,
        equality_constraint_count=equality_constraint_count,
        inequality_constraint_count=inequality_constraint_count,
        bound_count=bound_count,
        build_seconds=build_seconds,
        solver_seconds=solver_seconds,
        storage_balance_seconds=storage_balance_seconds,
        postprocess_seconds=max(
            0.0,
            total_seconds
            - build_seconds
            - solver_seconds
            - storage_balance_seconds,
        ),
        solve_seconds=total_seconds,
    )


def optimize_topology_islands(
    topology: ResourceTopology,
    *,
    renewable_rows: Sequence[Mapping[str, Any]],
    diesel_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    step_coefficient: float = default_number("renewable_step_ratio"),
    diesel_step_ratio: float = default_number("diesel_step_ratio"),
    converter_step_ratio: float = default_number("legacy_converter_step_ratio"),
    converter_ramp_step_ratio: float = default_number("converter_ramp_step_ratio"),
    converter_efficiency: float = default_number("converter_efficiency"),
    storage_step_ratio: float = default_number(
        "grid_following_storage_step_ratio"
    ),
    storage_soc_rebalance_deadband: float = default_number(
        "storage_soc_rebalance_deadband"
    ),
    storage_soc_correction_step_scale: float = default_number(
        "storage_soc_correction_step_scale"
    ),
    diesel_power_protection_ratio: float = default_number(
        "diesel_power_protection_ratio"
    ),
    grid_forming_storage_protection_ratio: float = default_number(
        "grid_forming_storage_protection_ratio"
    ),
    soc_deadband: float = default_number("soc_deadband"),
    renewable_curtailment_weight: float = RENEWABLE_CURTAILMENT_WEIGHT,
    diesel_output_weight: float = DIESEL_OUTPUT_WEIGHT,
    curtailment_square_weight: float = CURTAILMENT_SQUARE_WEIGHT,
    source_storage_adjustment_square_weight: float = SOURCE_STORAGE_ADJUSTMENT_SQUARE_WEIGHT,
    balance_delta_square_weight: float = BALANCE_DELTA_SQUARE_WEIGHT,
    balance_delta_warning_kw: float = BALANCE_DELTA_WARNING_KW,
    balance_tolerance_kw: float = BALANCE_TOLERANCE_KW,
    bound_tolerance_kw: float = BOUND_TOLERANCE_KW,
    optimization_ftol: float = OPTIMIZATION_FTOL,
    optimization_max_iterations: int = OPTIMIZATION_MAX_ITERATIONS,
    blocked_component_ids: Iterable[str] = (),
    blocked_reason: str = "拓扑岛包含状态无效设备，按 fail closed 保持当前值",
    external_injection_delta_by_component: Optional[Mapping[Tuple[str, str], float]] = None,
) -> RenewableDispatchOptimizationResult:
    started = time.perf_counter()
    step_coefficient = max(0.0, float(step_coefficient))
    diesel_step_ratio = min(1.0, max(0.0, float(diesel_step_ratio)))
    converter_step_ratio = max(0.0, float(converter_step_ratio))
    effective_converter_step_ratio = (
        min(1.0, max(0.0, float(converter_ramp_step_ratio)))
        if converter_ramp_step_ratio > EPSILON
        else min(1.0, converter_step_ratio)
    )
    converter_efficiency = min(1.0, max(0.5, float(converter_efficiency)))
    storage_step_ratio = max(0.0, float(storage_step_ratio))
    storage_soc_rebalance_deadband = min(0.5, max(0.0, float(storage_soc_rebalance_deadband)))
    storage_soc_correction_step_scale = min(
        1.0,
        max(0.10, float(storage_soc_correction_step_scale)),
    )
    diesel_power_protection_ratio = min(
        MAXIMUM_POWER_PROTECTION_RATIO,
        max(0.0, float(diesel_power_protection_ratio)),
    )
    grid_forming_storage_protection_ratio = min(
        MAXIMUM_POWER_PROTECTION_RATIO,
        max(0.0, float(grid_forming_storage_protection_ratio)),
    )
    soc_deadband = max(0.0, float(soc_deadband))
    renewable_curtailment_weight = max(
        0.0, float(renewable_curtailment_weight)
    )
    diesel_output_weight = max(0.0, float(diesel_output_weight))
    curtailment_square_weight = max(0.0, float(curtailment_square_weight))
    source_storage_adjustment_square_weight = max(
        0.0, float(source_storage_adjustment_square_weight)
    )
    balance_delta_square_weight = max(
        EPSILON, float(balance_delta_square_weight)
    )
    balance_delta_warning_kw = max(0.0, float(balance_delta_warning_kw))
    balance_tolerance_kw = max(EPSILON, float(balance_tolerance_kw))
    bound_tolerance_kw = max(EPSILON, float(bound_tolerance_kw))
    optimization_ftol = max(EPSILON, float(optimization_ftol))
    optimization_max_iterations = max(1, int(optimization_max_iterations))
    blocked_components = {
        str(component_id).strip()
        for component_id in blocked_component_ids
        if str(component_id).strip()
    }
    variables: list[_Variable] = []
    expected_keys: set[DeviceKey] = set()

    for row in renewable_rows:
        if row.get("online") and row.get("commandable"):
            expected_keys.add(_device_key(row))
        variable = _renewable_variable(row, step_coefficient)
        if variable is not None:
            variables.append(variable)
    for row in diesel_rows:
        if (
            row.get("online")
            and not row.get("automaticControlBlocked")
            and (row.get("commandable") or row.get("stateEligible"))
        ):
            expected_keys.add(_device_key(row))
        variable = _diesel_variable(
            row,
            diesel_step_ratio,
            diesel_power_protection_ratio,
        )
        if variable is not None:
            variables.append(variable)
    for row in storage_rows:
        if (
            row.get("online")
            and not row.get("automaticControlBlocked")
            and (
                row.get("commandable")
                or row.get("role") == "balance"
                and row.get("stateEligible")
            )
        ):
            expected_keys.add(_device_key(row))
        variable = _storage_variable(
            row,
            grid_forming_storage_protection_ratio,
            storage_step_ratio,
            storage_soc_correction_step_scale,
            soc_deadband,
        )
        if variable is not None:
            variables.append(variable)
    for row in converter_rows:
        if row.get("online") and row.get("commandable"):
            expected_keys.add(_device_key(row))
        variable = _converter_variable(
            row,
            topology,
            effective_converter_step_ratio,
            converter_efficiency,
        )
        if variable is not None:
            variables.append(variable)

    variable_keys = {item.key for item in variables}
    unassigned = tuple(sorted(expected_keys - variable_keys))
    components = _DisjointSet()
    for item in variables:
        if item.kind == "converter":
            components.union(item.ac_component_id, item.dc_component_id)
        else:
            components.add(item.component_id)
    for ac_component_id, dc_component_id in topology.converter_component_ids.values():
        components.union(ac_component_id, dc_component_id)

    variables_by_root: Dict[str, list[_Variable]] = {}
    components_by_root: Dict[str, set[str]] = {}
    for component_id in list(components._parent):
        root = components.find(component_id)
        components_by_root.setdefault(root, set()).add(component_id)
    for item in variables:
        component_id = item.ac_component_id if item.kind == "converter" else item.component_id
        root = components.find(component_id)
        variables_by_root.setdefault(root, []).append(item)

    outer_build_seconds = time.perf_counter() - started
    blocked_roots = {
        components.find(component_id)
        for component_id in blocked_components
        if component_id in components._parent
    }
    island_results_list: list[IslandOptimizationResult] = []
    for root in sorted(components_by_root):
        island_variables = variables_by_root.get(root, ())
        if not island_variables:
            continue
        component_ids = tuple(sorted(components_by_root[root]))
        if root in blocked_roots:
            island_results_list.append(
                _blocked_island_result(
                    component_ids,
                    island_variables,
                    blocked_reason,
                )
            )
            continue
        island_ext_delta_by_component: Dict[Tuple[str, str], float] = {}
        island_ext_delta_by_side: Dict[str, float] = {}
        if external_injection_delta_by_component:
            comp_set = set(component_ids)
            for (ext_comp, ext_side), ext_kw in external_injection_delta_by_component.items():
                if ext_comp in comp_set and ext_side in {"AC", "DC"}:
                    island_ext_delta_by_component[(ext_comp, ext_side)] = (
                        island_ext_delta_by_component.get((ext_comp, ext_side), 0.0)
                        + float(ext_kw)
                    )
                    island_ext_delta_by_side[ext_side] = (
                        island_ext_delta_by_side.get(ext_side, 0.0) + float(ext_kw)
                    )
        island_results_list.append(
            _solve_island(
                component_ids,
                island_variables,
                renewable_curtailment_weight=renewable_curtailment_weight,
                diesel_output_weight=diesel_output_weight,
                curtailment_square_weight=curtailment_square_weight,
                adjustment_square_weight=source_storage_adjustment_square_weight,
                balance_delta_square_weight=balance_delta_square_weight,
                balance_tolerance_kw=balance_tolerance_kw,
                bound_tolerance_kw=bound_tolerance_kw,
                optimization_ftol=optimization_ftol,
                optimization_max_iterations=optimization_max_iterations,
                storage_soc_rebalance_deadband=storage_soc_rebalance_deadband,
                external_injection_delta_by_side=island_ext_delta_by_side or None,
                external_injection_delta_by_component=island_ext_delta_by_component or None,
                balance_delta_warning_kw=balance_delta_warning_kw,
            )
        )
    island_results = tuple(island_results_list)
    targets: Dict[DeviceKey, float] = {}
    for island in island_results:
        if island.success:
            targets.update(island.target_by_device)
    available_by_renewable = {
        item.key: float(item.renewable_available_kw or 0.0)
        for item in variables
        if item.kind == "renewable"
    }
    curtailment_by_renewable = {
        key: max(0.0, available - targets.get(key, available))
        for key, available in available_by_renewable.items()
        if key in targets
    }
    max_residual = max(
        (
            abs(residual)
            for island in island_results
            for residual in island.balance_residual_by_component.values()
        ),
        default=0.0,
    )
    total_seconds = time.perf_counter() - started
    build_seconds = outer_build_seconds + sum(
        island.build_seconds for island in island_results
    )
    solver_seconds = sum(island.solver_seconds for island in island_results)
    storage_balance_seconds = sum(
        island.storage_balance_seconds for island in island_results
    )
    return RenewableDispatchOptimizationResult(
        targets=targets,
        available_by_renewable=available_by_renewable,
        curtailment_by_renewable=curtailment_by_renewable,
        islands=island_results,
        unassigned_devices=unassigned,
        all_success=bool(island_results)
        and all(island.success for island in island_results)
        and not unassigned,
        max_balance_residual_kw=max_residual,
        balance_delta_warning_kw=balance_delta_warning_kw,
        iterations=sum(island.iterations for island in island_results),
        variable_count=sum(island.variable_count for island in island_results),
        constraint_count=sum(island.constraint_count for island in island_results),
        equality_constraint_count=sum(
            island.equality_constraint_count for island in island_results
        ),
        inequality_constraint_count=sum(
            island.inequality_constraint_count for island in island_results
        ),
        bound_count=sum(island.bound_count for island in island_results),
        build_seconds=build_seconds,
        solver_seconds=solver_seconds,
        storage_balance_seconds=storage_balance_seconds,
        postprocess_seconds=max(
            0.0,
            total_seconds
            - build_seconds
            - solver_seconds
            - storage_balance_seconds,
        ),
        solve_seconds=total_seconds,
    )
