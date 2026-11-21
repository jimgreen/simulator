"""renewable_control 拆分模块：交直流侧感知新能源恢复计划与平衡储能目标投影。"""

from __future__ import annotations

from .common import *  # noqa: F401,F403
from .common import (
    _CyclePerformanceWindow,
    _LinkedResourceSpec,
    _boolean,
    _clamp,
    _clamp_converter_target_kw,
    _command_number,
    _control_definition_rows,
    _control_rows,
    _converter_ac_balance_coefficient,
    _converter_ac_injection_bounds_kw,
    _converter_ac_injection_delta_kw,
    _converter_ac_injection_kw,
    _converter_direction,
    _converter_power_from_ac_injection_kw,
    _converter_row_sort_key,
    _converter_signed_bounds_kw,
    _converter_system_power_kw,
    _converter_target_from_ac_injection_kw,
    _deduplicate_dispatch_commands,
    _definition_device_rows,
    _derating_curve_payload,
    _derating_curve_point,
    _derating_curve_text,
    _derating_factor,
    _device_by_model_key,
    _device_index,
    _device_key,
    _device_map,
    _device_model_block,
    _device_model_key,
    _device_name,
    _device_state_rows,
    _device_type,
    _dispatch_setpoint_value,
    _duplicate_typed_identities,
    _finite_number,
    _hydrogen_pressure_states,
    _hydrogen_pressure_states_by_island,
    _indexed_device_matches,
    _is_grid_converter_row,
    _is_online,
    _json_safe_copy,
    _linked_resource_specs,
    _live_soc_ratio,
    _measured,
    _measurement_index,
    _natural_topology_identity,
    _normalized_derating_curve,
    _now_text,
    _number,
    _parameter_name,
    _parameter_rows,
    _performance_percentile,
    _positive,
    _preferred_set_type,
    _rated_capacity,
    _ratio,
    _run_status_control_keys,
    _simulation_control_interval_seconds,
    _storage_efficiency,
    _sum_known,
)
from .settings import *  # noqa: F401,F403
from .settings import (
    _Quality,
    _annotate_diesel_topology,
    _apply_grid_forming_fail_closed_scopes,
    _blocked_optimization_component_ids,
    _converter_rows,
    _curve_boundary_value,
    _diesel_rows,
    _effective_step_minutes,
    _load_boundary,
    _measurement_sample_clock,
    _normalized_generation_current,
    _observed_environment_value,
    _optimization_component_ids_for_row,
    _renewable_rows,
    _runtime_mode,
    _storage_control_horizon_minutes,
    _storage_rows,
    _topology_payload,
)
from .hydrogen import *  # noqa: F401,F403
from .hydrogen import (
    _allocate_converter_ac_injection_delta,
    _allocate_row_command_delta,
    _dcac_unavailable_detail,
    _hydrogen_electric_resource_refs,
    _hydrogen_island_pressure_state,
    _hydrogen_operating_metrics,
    _node_in_dc_transfer_group,
    _optimization_island_id_for_components,
    _optimize_hydrogen_within_topology_islands,
    _publish_final_acdc_coordination,
    _row_command_delta_margin,
    _topology_island_hydrogen_plans,
)


@dataclass(frozen=True)
class _RenewableStorageIslandComponent:
    grid_component_id: str
    dc_transfer_group_id: str
    renewable_rows: Tuple[Mapping[str, Any], ...]
    storage_rows: Tuple[Mapping[str, Any], ...]
    converter_rows: Tuple[Mapping[str, Any], ...]

def _dc_transfer_group_sort_key(
    topology: ResourceTopology,
    group_id: str,
) -> Tuple[Any, ...]:
    group = topology.dc_transfer_groups.get(group_id)
    nodes = tuple(
        _natural_topology_identity(node)
        for node in getattr(group, "dc_nodes", ())
    )
    return nodes, group_id

def _active_dc_transfer_group_ids(
    topology: ResourceTopology,
    rows: Sequence[Mapping[str, Any]],
) -> set[str]:
    rows_by_group: Dict[str, List[Mapping[str, Any]]] = {}
    for row in rows:
        group_id = str(row.get("dcTransferGroupId", ""))
        if group_id:
            rows_by_group.setdefault(group_id, []).append(row)

    active_group_ids: set[str] = set()
    for group_id in topology.dc_transfer_groups:
        group_rows = [row for row in rows_by_group.get(group_id, []) if row.get("online")]
        converters = [
            row
            for row in group_rows
            if _is_grid_converter_row(row)
            and row.get("commandable") is not False
        ]
        dc_rows = [row for row in group_rows if row.get("connectionSide") == "DC"]
        if group_rows and converters and dc_rows:
            active_group_ids.add(group_id)
    return active_group_ids

def _renewable_storage_island_components(
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
) -> List[_RenewableStorageIslandComponent]:
    storage_by_component: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for row in storage_rows:
        key = (
            str(row.get("gridComponentId", "")),
            str(row.get("dcTransferGroupId", "")),
        )
        if all(key):
            storage_by_component.setdefault(key, []).append(row)

    renewable_by_component: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    component_order: List[Tuple[str, str]] = []
    for row in renewable_rows:
        key = (
            str(row.get("gridComponentId", "")),
            str(row.get("dcTransferGroupId", "")),
        )
        if not all(key):
            continue
        if key not in renewable_by_component:
            component_order.append(key)
            renewable_by_component[key] = []
        renewable_by_component[key].append(row)

    converters_by_group: Dict[str, List[Mapping[str, Any]]] = {}
    for row in converter_rows:
        group_id = str(row.get("dcTransferGroupId", ""))
        if group_id:
            converters_by_group.setdefault(group_id, []).append(row)

    return [
        _RenewableStorageIslandComponent(
            grid_component_id=component_id,
            dc_transfer_group_id=group_id,
            renewable_rows=tuple(renewable_by_component[(component_id, group_id)]),
            storage_rows=tuple(storage_by_component[(component_id, group_id)]),
            converter_rows=tuple(converters_by_group.get(group_id, ())),
        )
        for component_id, group_id in component_order
        if (component_id, group_id) in storage_by_component
    ]

def _plan_renewable_storage_island_component(
    component: _RenewableStorageIslandComponent,
    settings: RenewableControlSettings,
) -> Dict[str, Any]:
    known_soc_rows = [
        row
        for row in component.storage_rows
        if row.get("socKnown") and row.get("soc") is not None
    ]
    storage_soc = _capacity_weighted_soc(known_soc_rows)
    total_soc_weight = sum(
        (
            _finite_number(row.get("capacityKwh"))
            if _finite_number(row.get("capacityKwh")) > EPSILON
            else 1.0
        )
        for row in known_soc_rows
    )
    storage_soc_upper_limit = (
        sum(
            _finite_number(row.get("socMax"))
            * (
                _finite_number(row.get("capacityKwh"))
                if _finite_number(row.get("capacityKwh")) > EPSILON
                else 1.0
            )
            for row in known_soc_rows
        )
        / total_soc_weight
        if total_soc_weight > EPSILON
        else None
    )
    raw_charge = sum(
        max(0.0, _finite_number(row.get("chargePower")))
        for row in component.storage_rows
    )
    storage_current = sum(
        _finite_number(row.get("currentKw"))
        for row in component.storage_rows
        if row.get("currentKw") is not None
    )
    converter_current = sum(
        min(0.0, _finite_number(row.get("currentKw")))
        for row in component.converter_rows
        if row.get("currentKw") is not None
    )
    projected_storage_charge = max(0.0, -(storage_current + converter_current))
    charge_residual = max(0.0, projected_storage_charge - raw_charge)

    if storage_soc is None or storage_soc_upper_limit is None:
        action = "hold_unknown_soc"
    elif storage_soc >= storage_soc_upper_limit - EPSILON:
        action = "curtail_one_step_storage_island_full_soc"
    elif raw_charge <= EPSILON:
        action = "curtail_one_step_storage_island_no_charge_capacity"
    elif charge_residual > EPSILON:
        action = "curtail_charge_safety"
    else:
        action = "recover_one_step_storage_island"

    targets: Dict[Tuple[str, str], Optional[float]] = {}
    renewable_states: List[MutableMapping[str, Any]] = []
    for row in component.renewable_rows:
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        planning_current = _number(row.get("planningCurrentKw"))
        if planning_current is None:
            targets[key] = None
            continue
        if not row.get("commandable"):
            targets[key] = planning_current
            continue
        capacity = max(0.0, _finite_number(row.get("capacityKw")))
        step = settings.step_coefficient * capacity
        if action == "recover_one_step_storage_island":
            renewable_states.append(
                {
                    "key": key,
                    "currentKw": planning_current,
                    "marginKw": min(step, max(0.0, capacity - planning_current)),
                }
            )
            target = planning_current
        elif action in {
            "curtail_one_step_storage_island_full_soc",
            "curtail_one_step_storage_island_no_charge_capacity",
            "curtail_charge_safety",
        }:
            target = max(0.0, planning_current - step)
        else:
            target = planning_current
        targets[key] = target

    if action == "recover_one_step_storage_island" and renewable_states:
        charge_headroom_kw = sum(
            max(
                0.0,
                _finite_number(row.get("chargePower"))
                - max(0.0, -_finite_number(row.get("currentKw"))),
            )
            for row in component.storage_rows
        )
        allocations = _allocate_by_margin(
            renewable_states,
            min(
                charge_headroom_kw,
                sum(_finite_number(state.get("marginKw")) for state in renewable_states),
            ),
            "marginKw",
        )
        for state, allocation_kw in zip(renewable_states, allocations):
            targets[state["key"]] = _finite_number(state.get("currentKw")) + allocation_kw

    return {
        "gridComponentId": component.grid_component_id,
        "dcTransferGroupId": component.dc_transfer_group_id,
        "action": action,
        "storageSoc": storage_soc,
        "storageSocUpperLimit": storage_soc_upper_limit,
        "renewableCurrentKw": sum(
            _finite_number(row.get("currentKw")) for row in component.renewable_rows
        ),
        "renewableTargetKw": sum(
            _finite_number(target) for target in targets.values()
        ),
        "renewableTargets": targets,
        "converterTargetKw": 0.0,
        "converterKeys": [
            (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            for row in component.converter_rows
        ],
    }

def _resolve_converter_capacities(
    rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    # Converter capability must come from the converter itself.  Storage power
    # boundaries are not a valid substitute for a missing ACDC nameplate limit.
    return [dict(source) for source in rows]

def _allocate(items: Sequence[Mapping[str, Any]], total: float, capacity_key: str) -> List[float]:
    target = max(0.0, total)
    capacities = [max(0.0, _number(item.get(capacity_key), 0.0) or 0.0) for item in items]
    total_capacity = sum(capacities)
    if target <= 0 or total_capacity <= 0:
        return [0.0 for _ in items]
    return [min(capacity, target * capacity / total_capacity) for capacity in capacities]

def _capacity_weighted_soc(rows: Sequence[Mapping[str, Any]]) -> Optional[float]:
    weighted_sum = 0.0
    total_weight = 0.0
    for row in rows:
        soc = _number(row.get("soc"))
        if not row.get("socKnown") or soc is None or not math.isfinite(soc):
            continue
        capacity = _number(row.get("capacityKwh"))
        weight = (
            capacity
            if capacity is not None and math.isfinite(capacity) and capacity > EPSILON
            else 1.0
        )
        weighted_sum += soc * weight
        total_weight += weight
    return weighted_sum / total_weight if total_weight > EPSILON else None

def _equal_margin_increments(rows: Sequence[Mapping[str, Any]], target: float) -> List[float]:
    increments = [0.0 for _ in rows]
    remaining = max(0.0, target)
    active = [index for index, row in enumerate(rows) if (_number(row.get("headroomKw"), 0.0) or 0.0) > EPSILON]
    while remaining > EPSILON and active:
        share = remaining / len(active)
        saturated = [
            index
            for index in active
            if (_number(rows[index].get("headroomKw"), 0.0) or 0.0) - increments[index] <= share + EPSILON
        ]
        if not saturated:
            for index in active:
                increments[index] += share
            break
        for index in saturated:
            addition = max(0.0, (_number(rows[index].get("headroomKw"), 0.0) or 0.0) - increments[index])
            increments[index] += addition
            remaining = max(0.0, remaining - addition)
        saturated_set = set(saturated)
        active = [index for index in active if index not in saturated_set]
    return increments

def _plan_recovery(
    rows: Sequence[Mapping[str, Any]],
    room_kw: float,
    settings: RenewableControlSettings,
) -> Dict[str, Any]:
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        capacity = max(0.0, _number(row.get("capacityKw"), 0.0) or 0.0)
        current = min(capacity, max(0.0, _number(row.get("planningCurrentKw", row.get("currentKw")), 0.0) or 0.0))
        normalized.append({**row, "capacityKw": capacity, "planningCurrentKw": current, "headroomKw": max(0.0, capacity - current)})
    total_headroom = sum(row["headroomKw"] for row in normalized)
    requested = min(max(0.0, room_kw), total_headroom)
    mode = "equal-margin" if requested > settings.large_step_threshold_kw else "capacity-step"
    if mode == "equal-margin":
        increments = _equal_margin_increments(normalized, requested)
    else:
        proposed = [min(row["headroomKw"], settings.step_coefficient * row["capacityKw"]) for row in normalized]
        proposed_total = sum(proposed)
        target = min(requested, proposed_total)
        scale = min(1.0, target / proposed_total) if target > EPSILON and proposed_total > EPSILON else 0.0
        increments = [value * scale for value in proposed]
    result_rows = []
    for row, increment in zip(normalized, increments):
        recovery = min(row["headroomKw"], max(0.0, increment))
        result_rows.append({**row, "recoveryKw": recovery, "setpointKw": row["planningCurrentKw"] + recovery})
    return {
        "mode": mode,
        "requestedKw": requested,
        "recoverableKw": sum(row["recoveryKw"] for row in result_rows),
        "totalHeadroomKw": total_headroom,
        "rows": result_rows,
    }

def _apply_storage_switch_deadband(
    current_kw: float,
    desired_kw: float,
    deadband_kw: float,
) -> Tuple[float, str]:
    deadband = max(0.0, deadband_kw)
    if deadband <= EPSILON:
        return desired_kw, "disabled"
    if abs(current_kw) <= EPSILON:
        return (0.0, "idle_deadband") if abs(desired_kw) < deadband else (desired_kw, "direction_start_allowed")
    if current_kw > 0.0 and desired_kw < 0.0:
        return (0.0, "discharge_to_charge_blocked") if abs(desired_kw) < deadband else (desired_kw, "direction_switch_allowed")
    if current_kw < 0.0 and desired_kw > 0.0:
        return (0.0, "charge_to_discharge_blocked") if desired_kw < deadband else (desired_kw, "direction_switch_allowed")
    return desired_kw, "same_direction"

def _move_toward(current: float, target: float, step: float) -> float:
    limit = max(0.0, step)
    if limit <= EPSILON:
        return current
    if target > current:
        return min(target, current + limit)
    if target < current:
        return max(target, current - limit)
    return current

def _diesel_boundary_violation(value_kw: float, minimum_kw: float, capacity_kw: float) -> float:
    if value_kw < minimum_kw:
        return minimum_kw - value_kw
    if capacity_kw > EPSILON and value_kw > capacity_kw:
        return value_kw - capacity_kw
    return 0.0

def _parallel_converter_limit(rows: Sequence[Mapping[str, Any]]) -> float:
    if not rows:
        return 0.0
    capacities = [max(0.0, _number(row.get("transferCapacityKw"), 0.0) or 0.0) for row in rows]
    return sum(capacities) if all(capacity > 0 for capacity in capacities) else math.inf

def _final_command_power_bounds_kw(
    row: Mapping[str, Any],
) -> Optional[Tuple[float, float]]:
    if row.get("category") == "氢能":
        return None
    if row.get("technology") in {"wind", "pv"}:
        capacity = _number(row.get("capacityKw"))
        if capacity is not None and capacity >= 0.0:
            return 0.0, float(capacity)
        return None
    if row.get("technology") == "storage":
        if row.get("limitsValid") and row.get("socKnown"):
            return _grid_storage_signed_power_bounds_kw(row)
        return None
    if row.get("category") == "柴油发电":
        minimum = _number(row.get("minKw"))
        maximum = _number(row.get("capacityKw"))
        if minimum is not None and maximum is not None and minimum <= maximum:
            return float(minimum), float(maximum)
        return None
    if _is_grid_converter_row(row) and row.get("limitsValid"):
        return _converter_signed_bounds_kw(row)
    return None

def _clamp_final_command_rows_to_boundaries(
    rows: Sequence[MutableMapping[str, Any]],
) -> List[str]:
    """Keep finite out-of-bound telemetry controllable and issue a safe target."""

    warnings: List[str] = []
    for row in rows:
        if (
            not row.get("online")
            or row.get("commandable") is False
            or not row.get("set_type")
        ):
            continue
        bounds = _final_command_power_bounds_kw(row)
        if bounds is None:
            continue
        minimum, maximum = bounds
        if not (
            math.isfinite(minimum)
            and math.isfinite(maximum)
            and minimum <= maximum
        ):
            continue
        current = _number(row.get("currentKw"))
        target = _number(row.get("commandKw"))
        if target is None:
            if current is None:
                continue
            target = current
        safe_target = _clamp(float(target), minimum, maximum)
        target_was_clamped = abs(safe_target - float(target)) > EPSILON
        current_outside = bool(
            current is not None
            and (current < minimum - EPSILON or current > maximum + EPSILON)
        )
        if not target_was_clamped and not current_outside:
            continue
        row["commandKw"] = safe_target
        for field in (
            "targetKw",
            "projectedTargetKw",
            "optimizationSuggestedKw",
        ):
            if field in row:
                row[field] = safe_target
        row["strategyCommand"] = True
        row["strategyTargetChanged"] = bool(
            current is not None and abs(safe_target - current) > EPSILON
        )
        reason = (
            "measurement_below_lower_limit_correction"
            if current is not None and current < minimum - EPSILON
            else "measurement_above_upper_limit_correction"
            if current is not None and current > maximum + EPSILON
            else "target_below_lower_limit_clamped"
            if target < minimum - EPSILON
            else "target_above_upper_limit_clamped"
        )
        row["boundaryCorrection"] = True
        row["boundaryCorrectionReason"] = reason
        name = str(row.get("dev_name", ""))
        def _fmt_num(v: float) -> str:
            return f"{v:.2f}".rstrip("0").rstrip(".")
        warnings.append(
            f"{name} 已限幅至 {_fmt_num(safe_target)} kW（允许范围 {_fmt_num(minimum)}~{_fmt_num(maximum)} kW）"
        )
    return warnings

def _converter_export_margins_kw(
    row: Mapping[str, Any],
    current_kw: Any,
    target_kw: Any,
    step_kw: Optional[float],
) -> Tuple[float, float]:
    current_ac_injection_kw = _converter_ac_injection_kw(row, current_kw)
    target_ac_injection_kw = _converter_ac_injection_kw(row, target_kw)
    _minimum_ac_injection_kw, maximum_ac_injection_kw = (
        _converter_ac_injection_bounds_kw(row)
    )
    remaining_step_kw = math.inf
    if step_kw is not None:
        remaining_step_kw = max(
            0.0,
            float(step_kw)
            - abs(_finite_number(target_kw) - _finite_number(current_kw)),
        )
    increase_margin_kw = (
        min(
            max(0.0, maximum_ac_injection_kw - target_ac_injection_kw),
            remaining_step_kw,
        )
        if current_ac_injection_kw >= -EPSILON
        and target_ac_injection_kw >= -EPSILON
        else 0.0
    )
    reduction_margin_kw = min(
        max(0.0, target_ac_injection_kw),
        remaining_step_kw,
    )
    return increase_margin_kw, reduction_margin_kw

def _allocate_converters(rows: Sequence[Mapping[str, Any]], total: float) -> List[float]:
    target = max(0.0, total)
    if not rows or target <= 0:
        return [0.0 for _ in rows]
    if all((_number(row.get("transferCapacityKw"), 0.0) or 0.0) > 0 for row in rows):
        return _allocate(rows, target, "transferCapacityKw")
    return [target / len(rows) for _ in rows]

def _allocate_signed_converter_target(
    rows: Sequence[Mapping[str, Any]],
    total_kw: float,
) -> List[float]:
    if not rows:
        return []
    if total_kw >= 0.0:
        states = [
            {"marginKw": max(0.0, _converter_signed_bounds_kw(row)[1])}
            for row in rows
        ]
        return _allocate_by_margin(states, total_kw, "marginKw")
    states = [
        {"marginKw": max(0.0, -_converter_signed_bounds_kw(row)[0])}
        for row in rows
    ]
    return [
        -value
        for value in _allocate_by_margin(states, -total_kw, "marginKw")
    ]

def _grid_storage_step_kw(row, settings):
    rated = max(_finite_number(row.get('maxChargePowerKw')), _finite_number(row.get('maxDischargePowerKw')))
    return max(0.0, settings.storage_step_ratio * rated)

def _grid_storage_sort_key(row: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        _natural_topology_identity(row.get("connectionSide", "")),
        _natural_topology_identity(row.get("dcTransferGroupId", "")),
        _natural_topology_identity(row.get("dev_type", "")),
        _natural_topology_identity(row.get("dev_name", "")),
    )

def _grid_storage_signed_power_bounds_kw(
    row: Mapping[str, Any],
) -> Tuple[float, float]:
    if not row.get("limitsValid") or not row.get("socKnown"):
        return 0.0, 0.0

    soc = _number(row.get("soc"))
    soc_min = _number(row.get("socMin"))
    soc_max = _number(row.get("socMax"))
    capacity_kwh = _number(row.get("capacityKwh"))
    efficiency = _number(row.get("efficiency"))
    horizon_minutes = _number(row.get("controlHorizonMinutes"))
    if (
        soc is None
        or soc_min is None
        or soc_max is None
        or capacity_kwh is None
        or capacity_kwh <= EPSILON
        or efficiency is None
        or efficiency <= EPSILON
        or horizon_minutes is None
        or horizon_minutes <= EPSILON
    ):
        return 0.0, 0.0

    # Apply direct-storage limits in the required order: model power limits,
    # configured SOC derating, then one-period energy margin.
    charge_limit_kw = max(0.0, _finite_number(row.get("maxChargePowerKw")))
    discharge_limit_kw = max(0.0, _finite_number(row.get("maxDischargePowerKw")))

    charge_derating_factor = _clamp(
        _finite_number(row.get("chargeDeratingFactor")),
        0.0,
        1.0,
    )
    discharge_derating_factor = _clamp(
        _finite_number(row.get("dischargeDeratingFactor")),
        0.0,
        1.0,
    )
    charge_limit_kw = min(
        charge_limit_kw,
        max(0.0, _finite_number(row.get("maxChargePowerKw")))
        * charge_derating_factor,
    )
    discharge_limit_kw = min(
        discharge_limit_kw,
        max(0.0, _finite_number(row.get("maxDischargePowerKw")))
        * discharge_derating_factor,
    )

    horizon_hours = max(EPSILON, horizon_minutes / 60.0)
    charge_energy_limit_kw = max(
        0.0,
        ((soc_max - soc) * capacity_kwh) / (efficiency * horizon_hours),
    )
    discharge_energy_limit_kw = max(
        0.0,
        ((soc - soc_min) * capacity_kwh * efficiency) / horizon_hours,
    )
    charge_limit_kw = min(charge_limit_kw, charge_energy_limit_kw)
    discharge_limit_kw = min(discharge_limit_kw, discharge_energy_limit_kw)
    return -charge_limit_kw, discharge_limit_kw

def _grid_storage_target_margins(
    row: Mapping[str, Any],
    settings: RenewableControlSettings,
    diesel_boundary_distance_kw: float,
) -> Dict[str, Any]:
    current_kw = _number(row.get("currentKw"))
    step_kw = _grid_storage_step_kw(row, settings)
    eligible = bool(
        row.get("role") == "grid_following"
        and row.get("commandable")
        and current_kw is not None
        and math.isfinite(current_kw)
        and step_kw > EPSILON
    )
    if not eligible:
        return {
            "eligible": False,
            "currentKw": current_kw,
            "targetKw": current_kw,
            "signedMinTargetKw": current_kw,
            "signedMaxTargetKw": current_kw,
            "stepKw": step_kw,
            "stepScale": 1.0,
            "chargeMarginKw": 0.0,
            "dischargeMarginKw": 0.0,
            "positiveReductionMarginKw": 0.0,
            "protectiveDeltaKw": 0.0,
        }

    signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
    bounded_current_kw = _clamp(current_kw, signed_min_kw, signed_max_kw)
    protective_target_kw = _move_toward(
        current_kw,
        bounded_current_kw,
        step_kw,
    )
    protective_delta_kw = protective_target_kw - current_kw
    protection_active = abs(protective_delta_kw) > EPSILON

    # Deadbands protect diesel/grid-forming power limits. They do not shrink
    # the ordinary storage adjustment step. The step is a continuous maximum
    # delta, so the optimizer may still choose any smaller movement.
    increase_step_scale = 1.0
    discharge_step_kw = step_kw * increase_step_scale

    if protection_active:
        charge_margin_kw = 0.0
        discharge_margin_kw = 0.0
        positive_reduction_margin_kw = 0.0
    else:
        charge_margin_kw = min(
            step_kw,
            max(0.0, current_kw - signed_min_kw),
        )
        discharge_margin_kw = min(
            discharge_step_kw,
            max(0.0, signed_max_kw - current_kw),
        )
        positive_reduction_margin_kw = min(
            step_kw,
            max(0.0, current_kw),
        )

    return {
        "eligible": True,
        "currentKw": current_kw,
        "targetKw": protective_target_kw,
        "signedMinTargetKw": signed_min_kw,
        "signedMaxTargetKw": signed_max_kw,
        "stepKw": step_kw,
        "stepScale": increase_step_scale,
        "chargeMarginKw": charge_margin_kw,
        "dischargeMarginKw": discharge_margin_kw,
        "positiveReductionMarginKw": positive_reduction_margin_kw,
        "protectiveDeltaKw": protective_delta_kw,
    }

def _allocate_by_margin(
    rows: Sequence[MutableMapping[str, Any]],
    total_kw: float,
    margin_key: str,
) -> List[float]:
    requested_kw = max(0.0, total_kw)
    margins = [max(0.0, _finite_number(row.get(margin_key))) for row in rows]
    total_margin_kw = sum(margins)
    accepted_kw = min(requested_kw, total_margin_kw)
    if accepted_kw <= EPSILON or total_margin_kw <= EPSILON:
        return [0.0 for _ in rows]

    allocations = [
        min(margin_kw, accepted_kw * margin_kw / total_margin_kw)
        for margin_kw in margins
    ]
    remainder_kw = max(0.0, accepted_kw - sum(allocations))
    if remainder_kw <= EPSILON:
        return allocations

    remaining_margins = [
        max(0.0, margin_kw - allocation_kw)
        for margin_kw, allocation_kw in zip(margins, allocations)
    ]
    remaining_total_kw = sum(remaining_margins)
    if remaining_total_kw <= EPSILON:
        return allocations
    for index, remaining_margin_kw in enumerate(remaining_margins):
        if remainder_kw <= EPSILON:
            break
        if remaining_margin_kw <= EPSILON:
            continue
        addition_kw = min(
            remaining_margin_kw,
            remainder_kw * remaining_margin_kw / remaining_total_kw,
        )
        allocations[index] += addition_kw
        remainder_kw = max(0.0, remainder_kw - addition_kw)
        remaining_total_kw = max(0.0, remaining_total_kw - remaining_margin_kw)
    return allocations

def _apply_ac_to_dc_renewable_absorption(
    resource_topology: ResourceTopology,
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    renewable_targets: Mapping[Tuple[str, str], Any],
    storage_targets: Mapping[Tuple[str, str], Any],
    converter_targets: Mapping[Tuple[str, str], Any],
    settings: RenewableControlSettings,
) -> Dict[str, Any]:
    """Pair AC renewable recovery with AC-to-DC transfer and DC storage charge.

    The three equal increments are power-neutral on both sides of the
    converter: AC renewable ``+x`` is consumed by ``p_ac_set +x`` because
    positive AC-terminal power means AC-to-DC transfer; the resulting DC-side
    injection is absorbed by storage ``-x``. No branch transfer rating is
    consulted; only each participating device's own one-step and operating
    limits are used.
    """
    final_renewable_targets = dict(renewable_targets)
    final_storage_targets = dict(storage_targets)
    final_converter_targets = dict(converter_targets)
    group_details: List[Dict[str, Any]] = []

    for group_id, group in sorted(
        resource_topology.dc_transfer_groups.items(),
        key=lambda item: _natural_topology_identity(item[0]),
    ):
        # A DC group coupled to several independent AC components needs a
        # converter-to-AC-component relation before a per-component neutral
        # dispatch can be proven.  Until that relation is explicit, fail closed.
        if len(group.ac_component_ids) != 1:
            continue
        ac_component_id = group.ac_component_ids[0]

        renewable_states: List[MutableMapping[str, Any]] = []
        for row in sorted(renewable_rows, key=_grid_storage_sort_key):
            if not (
                row.get("online")
                and row.get("commandable")
                and row.get("activelyConnected")
                and row.get("connectionSide") == "AC"
                and row.get("gridComponentId") == ac_component_id
            ):
                continue
            key = _device_key(row)
            current_kw = _number(row.get("planningCurrentKw", row.get("currentKw")))
            target_kw = _number(final_renewable_targets.get(key), current_kw)
            capacity_kw = _number(row.get("capacityKw"))
            if current_kw is None or target_kw is None or capacity_kw is None:
                continue
            # Never undo a curtailment selected by an earlier protection pass.
            if target_kw < current_kw - EPSILON:
                continue
            one_step_max_kw = min(
                max(0.0, capacity_kw),
                current_kw + settings.step_coefficient * max(0.0, capacity_kw),
            )
            margin_kw = max(0.0, one_step_max_kw - target_kw)
            if margin_kw > EPSILON:
                renewable_states.append(
                    {"row": row, "key": key, "targetKw": target_kw, "marginKw": margin_kw}
                )

        storage_states: List[MutableMapping[str, Any]] = []
        for row in sorted(storage_rows, key=_grid_storage_sort_key):
            if not (
                row.get("online")
                and row.get("commandable")
                and row.get("activelyConnected")
                and row.get("connectionSide") == "DC"
                and row.get("dcTransferGroupId") == group_id
                and row.get("role") == "grid_following"
            ):
                continue
            key = _device_key(row)
            current_kw = _number(row.get("currentKw"))
            target_kw = _number(final_storage_targets.get(key), current_kw)
            if current_kw is None or target_kw is None:
                continue
            signed_min_kw, _signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            one_step_min_kw = max(
                signed_min_kw,
                current_kw - _grid_storage_step_kw(row, settings),
            )
            margin_kw = max(0.0, target_kw - one_step_min_kw)
            if margin_kw > EPSILON:
                storage_states.append(
                    {"row": row, "key": key, "targetKw": target_kw, "marginKw": margin_kw}
                )

        converter_states: List[MutableMapping[str, Any]] = []
        for row in sorted(converter_rows, key=_converter_row_sort_key):
            if not (
                row.get("online")
                and row.get("commandable")
                and row.get("limitsValid")
                and row.get("dcTransferGroupId") == group_id
                and row.get("converterRole") == "grid"
            ):
                continue
            key = _device_key(row)
            current_kw = _number(row.get("currentKw"))
            target_kw = _number(final_converter_targets.get(key), current_kw)
            if current_kw is None or target_kw is None:
                continue
            minimum_ac_injection_kw, _maximum_ac_injection_kw = (
                _converter_ac_injection_bounds_kw(row)
            )
            current_transfer_kw = -_converter_ac_injection_kw(row, current_kw)
            target_transfer_kw = -_converter_ac_injection_kw(row, target_kw)
            one_step_max_kw = min(
                -minimum_ac_injection_kw,
                current_transfer_kw
                + settings.converter_step_ratio
                * max(0.0, _finite_number(row.get("transferCapacityKw"))),
            )
            margin_kw = max(0.0, one_step_max_kw - target_transfer_kw)
            if margin_kw > EPSILON:
                converter_states.append(
                    {
                        "row": row,
                        "key": key,
                        "targetKw": target_kw,
                        "targetTransferKw": target_transfer_kw,
                        "marginKw": margin_kw,
                    }
                )

        paired_kw = min(
            sum(_finite_number(state.get("marginKw")) for state in renewable_states),
            sum(_finite_number(state.get("marginKw")) for state in storage_states),
            sum(_finite_number(state.get("marginKw")) for state in converter_states),
        )
        if paired_kw <= EPSILON:
            continue

        renewable_allocations = _allocate_by_margin(
            renewable_states,
            paired_kw,
            "marginKw",
        )
        storage_allocations = _allocate_by_margin(
            storage_states,
            paired_kw,
            "marginKw",
        )
        converter_allocations = _allocate_by_margin(
            converter_states,
            paired_kw,
            "marginKw",
        )
        for state, allocation_kw in zip(renewable_states, renewable_allocations):
            final_renewable_targets[state["key"]] = _finite_number(state.get("targetKw")) + allocation_kw
        for state, allocation_kw in zip(storage_states, storage_allocations):
            final_storage_targets[state["key"]] = _finite_number(state.get("targetKw")) - allocation_kw
        for state, allocation_kw in zip(converter_states, converter_allocations):
            final_converter_targets[state["key"]] = _converter_target_from_ac_injection_kw(
                state["row"],
                -(
                    _finite_number(state.get("targetTransferKw"))
                    + allocation_kw
                ),
            )
        group_details.append(
            {
                "dcTransferGroupId": group_id,
                "acComponentId": ac_component_id,
                "pairedKw": paired_kw,
            }
        )

    return {
        "renewableTargets": final_renewable_targets,
        "storageTargets": final_storage_targets,
        "converterTargets": final_converter_targets,
        "groups": group_details,
        "pairedKw": sum(_finite_number(item.get("pairedKw")) for item in group_details),
    }

@dataclass(frozen=True)
class _DcGroupBudget:
    group_id: str
    renewable_current_kw: float
    renewable_recovery_kw: float
    local_net_demand_kw: float
    grid_storage_charge_margin_kw: float
    grid_storage_discharge_margin_kw: float
    balance_storage_charge_margin_kw: float
    balance_storage_discharge_margin_kw: float
    balance_storage_current_kw: float
    acdc_current_export_kw: float
    acdc_export_headroom_kw: float
    acdc_step_headroom_kw: float

@dataclass(frozen=True)
class _AcSideBudget:
    renewable_current_kw: float
    renewable_recovery_kw: float
    local_net_demand_kw: float
    diesel_down_margin_kw: float
    grid_storage_charge_margin_kw: float
    grid_storage_discharge_margin_kw: float
    balance_storage_charge_margin_kw: float
    balance_storage_discharge_margin_kw: float
    balance_storage_current_kw: float
    accepted_acdc_export_kw: float

def _active_load_budgets(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    dc_transfer_groups: Mapping[str, DcTransferGroup],
) -> Tuple[float, Dict[str, float]]:
    ac_total_kw = 0.0
    dc_totals_kw = {group_id: 0.0 for group_id in dc_transfer_groups}
    dc_group_by_node = {
        str(node): group_id
        for group_id, group in dc_transfer_groups.items()
        for node in group.dc_nodes
    }
    model = (
        snapshot.get("definitions", {}).get("model", {})
        if isinstance(snapshot.get("definitions"), Mapping)
        else {}
    )
    model_nodes: Dict[Tuple[str, str], str] = {}
    if (type(model) is dict or isinstance(model, Mapping)):
        for dev_type in ("ACLoad", "DCLoad"):
            block = model.get(dev_type)
            rows = block.get("rows") if (type(block) is dict or isinstance(block, Mapping)) else []
            for row in rows or []:
                if (type(row) is dict or isinstance(row, Mapping)) and str(row.get("name", "")):
                    model_nodes[(dev_type, str(row.get("name")))] = str(
                        row.get("node", "")
                    )

    for device in snapshot.get("devices", []) or []:
        if not (type(device) is dict or isinstance(device, Mapping)):
            continue
        model_block = _device_model_block(device)
        if model_block not in {"ACLoad", "DCLoad"} or not _is_online(
            device, measurements
        ):
            continue
        dev_type = _device_type(device)
        dead_island = _number(device.get("dead_island"), 0.0)
        if dead_island is not None and dead_island != 0.0:
            continue
        dev_name = _device_name(device)
        measured = _measured(
            measurements,
            dev_type,
            dev_name,
            ("P_LOAD", "P", "P_AC", "P_DC"),
        )
        if measured is None:
            continue
        if model_block == "ACLoad":
            ac_total_kw += measured.value
            continue
        raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
        node = model_nodes.get((model_block, dev_name), str(raw.get("node", "")))
        group_id = dc_group_by_node.get(str(node), "")
        if group_id:
            dc_totals_kw[group_id] += measured.value
    return ac_total_kw, dc_totals_kw

def _active_load_side_metrics(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
) -> Dict[str, Any]:
    totals = {"AC": 0.0, "DC": 0.0}
    active_counts = {"AC": 0, "DC": 0}
    measured_counts = {"AC": 0, "DC": 0}
    for device in snapshot.get("devices", []) or []:
        if not (type(device) is dict or isinstance(device, Mapping)):
            continue
        dev_type = _device_type(device)
        model_block = _device_model_block(device)
        side = "AC" if model_block == "ACLoad" else "DC" if model_block == "DCLoad" else ""
        if not side or not _is_online(device, measurements):
            continue
        dead_island = _number(device.get("dead_island"), 0.0)
        if dead_island is not None and dead_island != 0.0:
            continue
        active_counts[side] += 1
        measured = _measured(
            measurements,
            dev_type,
            _device_name(device),
            ("P_LOAD", "P", "P_AC", "P_DC"),
        )
        if measured is None:
            continue
        totals[side] += measured.value
        measured_counts[side] += 1

    def side_value(side: str) -> Optional[float]:
        if active_counts[side] == 0:
            return 0.0
        return totals[side] if measured_counts[side] > 0 else None

    return {
        "acLoadKw": side_value("AC"),
        "dcLoadKw": side_value("DC"),
        "onlineAcLoadCount": active_counts["AC"],
        "onlineDcLoadCount": active_counts["DC"],
    }

def _side_aware_storage_state(
    row: Mapping[str, Any],
    settings: RenewableControlSettings,
    initial_target_kw: Any,
    *,
    preserve_initial: bool = True,
) -> MutableMapping[str, Any]:
    current_kw = _number(row.get("currentKw"))
    state = _grid_storage_target_margins(row, settings, 0.0)
    state.update(
        {
            "row": row,
            "key": (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
            "side": str(row.get("connectionSide", "")),
            "groupId": str(row.get("dcTransferGroupId", "")),
        }
    )
    if current_kw is None or not state.get("eligible"):
        state["targetKw"] = current_kw
        return state
    candidate_kw = _number(initial_target_kw, current_kw)
    state["targetKw"] = (
        candidate_kw
        if preserve_initial
        and candidate_kw is not None
        and candidate_kw >= min(current_kw, 0.0) - EPSILON
        else current_kw
    )
    return state

def _project_balance_storage_targets(
    balance_rows: Sequence[Mapping[str, Any]],
    renewable_states: Sequence[Mapping[str, Any]],
    storage_states: Sequence[Mapping[str, Any]],
    converter_states: Sequence[Mapping[str, Any]],
    *,
    ac_balance_delta_kw: Optional[float] = None,
    dc_balance_delta_by_group: Optional[Mapping[str, float]] = None,
) -> Tuple[
    Dict[Tuple[str, str], float],
    Dict[Tuple[str, str], List[Dict[str, str]]],
]:
    projected_targets: Dict[Tuple[str, str], float] = {}
    indirect_devices: Dict[Tuple[str, str], List[Dict[str, str]]] = {}

    def changed_device_keys(states: Sequence[Mapping[str, Any]]) -> List[Tuple[str, str]]:
        keys = set()
        for state in states:
            row = state.get("row") if isinstance(state.get("row"), Mapping) else state
            current_kw = _number(state.get("currentKw", row.get("currentKw")))
            target_kw = _number(state.get("targetKw", state.get("commandKw")))
            if (
                current_kw is None
                or target_kw is None
                or abs(target_kw - current_kw) <= EPSILON
            ):
                continue
            keys.add(
                (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            )
        return sorted(keys)

    def allocate_rows(
        rows: Sequence[Mapping[str, Any]],
        delta_kw: float,
        changed_states: Sequence[Mapping[str, Any]],
    ) -> None:
        candidates: List[MutableMapping[str, Any]] = []
        margin_key = "upMarginKw" if delta_kw >= 0.0 else "downMarginKw"
        for row in sorted(rows, key=_grid_storage_sort_key):
            current_kw = _finite_number(row.get("currentKw"))
            signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            candidates.append(
                {
                    "row": row,
                    "upMarginKw": max(0.0, signed_max_kw - current_kw),
                    "downMarginKw": max(0.0, current_kw - signed_min_kw),
                }
            )
        allocations = _allocate_by_margin(candidates, abs(delta_kw), margin_key)
        direction = 1.0 if delta_kw >= 0.0 else -1.0
        devices = changed_device_keys(changed_states)
        for candidate, allocation_kw in zip(candidates, allocations):
            row = candidate["row"]
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            current_kw = _finite_number(row.get("currentKw"))
            signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            candidate_kw = current_kw + direction * allocation_kw
            if current_kw < signed_min_kw - EPSILON:
                projected_targets[key] = _clamp(
                    candidate_kw,
                    current_kw,
                    signed_max_kw,
                )
            elif current_kw > signed_max_kw + EPSILON:
                projected_targets[key] = _clamp(
                    candidate_kw,
                    signed_min_kw,
                    current_kw,
                )
            else:
                projected_targets[key] = _clamp(
                    candidate_kw,
                    signed_min_kw,
                    signed_max_kw,
                )
            indirect_devices[key] = [
                {"dev_type": dev_type, "dev_name": dev_name}
                for dev_type, dev_name in devices
                if (dev_type, dev_name) != key
            ]

    ac_rows = [
        row for row in balance_rows if row.get("connectionSide") == "AC"
    ]
    if ac_rows:
        ac_renewable_delta_kw = sum(
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw"))
            for state in renewable_states
            if state.get("side") == "AC"
        )
        ac_storage_delta_kw = sum(
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw"))
            for state in storage_states
            if state.get("side") == "AC"
        )
        export_delta_kw = sum(
            _converter_ac_injection_delta_kw(
                state["row"],
                state.get("currentKw"),
                state.get("targetKw"),
            )
            for state in converter_states
            if state.get("currentKw") is not None
            and state.get("targetKw") is not None
        )
        projected_delta_kw = (
            ac_balance_delta_kw
            if ac_balance_delta_kw is not None
            else -(ac_renewable_delta_kw + ac_storage_delta_kw + export_delta_kw)
        )
        allocate_rows(
            ac_rows,
            projected_delta_kw,
            [*renewable_states, *storage_states, *converter_states],
        )

    group_ids = sorted(
        {
            str(row.get("dcTransferGroupId", ""))
            for row in balance_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", ""))
        },
        key=_natural_topology_identity,
    )
    for group_id in group_ids:
        rows = [
            row
            for row in balance_rows
            if row.get("connectionSide") == "DC"
            and row.get("dcTransferGroupId") == group_id
        ]
        group_renewables = [
            state
            for state in renewable_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_storage = [
            state
            for state in storage_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_converters = [
            state
            for state in converter_states
            if state.get("groupId") == group_id
        ]
        renewable_delta_kw = sum(
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw"))
            for state in group_renewables
        )
        storage_delta_kw = sum(
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw"))
            for state in group_storage
        )
        export_delta_kw = sum(
            _converter_ac_injection_delta_kw(
                state["row"],
                state.get("currentKw"),
                state.get("targetKw"),
            )
            for state in group_converters
            if state.get("currentKw") is not None
            and state.get("targetKw") is not None
        )
        projected_delta_kw = (
            _finite_number(dc_balance_delta_by_group.get(group_id))
            if dc_balance_delta_by_group is not None
            and group_id in dc_balance_delta_by_group
            else -(renewable_delta_kw + storage_delta_kw) + export_delta_kw
        )
        allocate_rows(
            rows,
            projected_delta_kw,
            [*group_renewables, *group_storage, *group_converters],
        )
    return projected_targets, indirect_devices

def _side_aware_renewable_recovery_plan_without_balance(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    settings: RenewableControlSettings,
    resource_topology: ResourceTopology,
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    initial_storage_targets: Mapping[Tuple[str, str], Any],
    initial_converter_targets: Mapping[Tuple[str, str], Any],
    initial_renewable_targets: Mapping[Tuple[str, str], Any],
    allow_topology_recovery_fallback: bool,
    *,
    diesel_current_kw: float,
    diesel_min_kw: float,
    diesel_deadband_upper_kw: Optional[float] = None,
) -> Dict[str, Any]:
    preserve_state_machine_recovery_budget = any(
        row.get("role") == "balance" and row.get("stateEligible")
        for row in storage_rows
    )
    high_soc_dc_group_ids = {
        str(row.get("dcTransferGroupId", ""))
        for row in storage_rows
        if row.get("role") == "balance"
        and row.get("connectionSide") == "DC"
        and str(row.get("dcTransferGroupId", ""))
        and _number(row.get("soc")) is not None
        and _number(row.get("socMax")) is not None
        and _finite_number(row.get("soc"))
        > _finite_number(row.get("socMax")) + EPSILON
    }
    high_soc_ac_component_ids = {
        str(row.get("gridComponentId", ""))
        for row in storage_rows
        if row.get("role") == "balance"
        and row.get("connectionSide") == "AC"
        and str(row.get("gridComponentId", ""))
        and _number(row.get("soc")) is not None
        and _number(row.get("socMax")) is not None
        and _finite_number(row.get("soc"))
        > _finite_number(row.get("socMax")) + EPSILON
    }
    initial_curtail_request_kw = sum(
        max(
            0.0,
            _finite_number(row.get("planningCurrentKw"))
            - _finite_number(
                initial_renewable_targets.get(
                    (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                    row.get("planningCurrentKw"),
                )
            ),
        )
        for row in renewable_rows
        if _number(row.get("planningCurrentKw")) is not None
    )
    high_soc_curtail_rows = [
        row
        for row in renewable_rows
        if _number(row.get("planningCurrentKw")) is not None
        and (
            row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) in high_soc_dc_group_ids
            or row.get("connectionSide") == "AC"
            and str(row.get("gridComponentId", "")) in high_soc_ac_component_ids
        )
    ]
    high_soc_curtail_allocations = _allocate(
        high_soc_curtail_rows,
        min(
            initial_curtail_request_kw,
            sum(
                max(0.0, _finite_number(row.get("planningCurrentKw")))
                for row in high_soc_curtail_rows
            ),
        ),
        "planningCurrentKw",
    )
    high_soc_curtail_by_key = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): allocation_kw
        for row, allocation_kw in zip(
            high_soc_curtail_rows,
            high_soc_curtail_allocations,
        )
    }
    renewable_states: List[MutableMapping[str, Any]] = []
    for row in sorted(
        renewable_rows,
        key=lambda item: (
            str(item.get("connectionSide", "")),
            str(item.get("dcTransferGroupId", "")),
            str(item.get("technology", "")),
            str(item.get("dev_type", "")),
            str(item.get("dev_name", "")),
        ),
    ):
        current_kw = _number(row.get("planningCurrentKw"))
        capacity_kw = _number(row.get("capacityKw"))
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        initial_target_kw = _number(
            initial_renewable_targets.get(key),
            current_kw,
        )
        preserved_curtailment_kw = _finite_number(
            high_soc_curtail_by_key.get(key)
        )
        eligible = bool(
            row.get("commandable")
            and current_kw is not None
            and capacity_kw is not None
            and capacity_kw > EPSILON
            and current_kw >= -EPSILON
            and current_kw <= capacity_kw + EPSILON
        )
        initial_recovery_margin_kw = max(
            0.0,
            _finite_number(initial_target_kw, current_kw) - current_kw,
        ) if current_kw is not None else 0.0
        margin_kw = (
            min(
                max(0.0, capacity_kw - current_kw),
                initial_recovery_margin_kw
                if initial_recovery_margin_kw > EPSILON
                else settings.step_coefficient * capacity_kw
                if allow_topology_recovery_fallback
                or not preserve_state_machine_recovery_budget
                else 0.0,
            )
            if eligible
            else 0.0
        )
        renewable_states.append(
            {
                "row": row,
                "key": key,
                "side": str(row.get("connectionSide", "")),
                "groupId": str(row.get("dcTransferGroupId", "")),
                "technology": str(row.get("technology", "")),
                "currentKw": current_kw,
                "targetKw": (
                    max(0.0, current_kw - preserved_curtailment_kw)
                    if current_kw is not None
                    and preserved_curtailment_kw > EPSILON
                    else current_kw
                ),
                "marginKw": margin_kw,
                "acceptedKw": 0.0,
            }
        )

    storage_states = [
        _side_aware_storage_state(
            row,
            settings,
            initial_storage_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                row.get("currentKw"),
            ),
        )
        for row in sorted(storage_rows, key=_grid_storage_sort_key)
        if row.get("role") == "grid_following"
    ]
    converter_states: List[MutableMapping[str, Any]] = []
    for row in sorted(converter_rows, key=_converter_row_sort_key):
        current_kw = _number(row.get("currentKw"))
        capacity_kw = _number(row.get("transferCapacityKw"))
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        target_kw = _number(initial_converter_targets.get(key), current_kw)
        if current_kw is None or target_kw is None:
            target_kw = current_kw
        if target_kw is not None:
            target_kw = _clamp_converter_target_kw(row, target_kw)
        step_kw = (
            settings.converter_step_ratio * capacity_kw
            if capacity_kw is not None and capacity_kw > EPSILON
            else 0.0
        )
        export_margin_kw = 0.0
        export_reduction_margin_kw = 0.0
        if (
            row.get("commandable")
            and current_kw is not None
            and target_kw is not None
            and capacity_kw is not None
            and capacity_kw > EPSILON
        ):
            export_margin_kw, export_reduction_margin_kw = (
                _converter_export_margins_kw(
                    row,
                    current_kw,
                    target_kw,
                    step_kw,
                )
            )
        converter_states.append(
            {
                "row": row,
                "key": key,
                "groupId": str(row.get("dcTransferGroupId", "")),
                "currentKw": current_kw,
                "targetKw": target_kw,
                "capacityKw": capacity_kw,
                "exportMarginKw": export_margin_kw,
                "exportReductionMarginKw": export_reduction_margin_kw,
            }
        )

    # Near the diesel deadband boundary, the ACDC and AC-renewable candidates
    # would otherwise consume the same small diesel margin twice.  Prefer the
    # directly connected AC renewable recovery for this one-step correction and
    # keep ACDC at its measured export; clearly high diesel output still uses
    # the normal ACDC discharge path below.
    diesel_boundary_kw = max(
        diesel_min_kw,
        _finite_number(diesel_deadband_upper_kw, diesel_min_kw),
    )
    converter_base_step_kw = sum(
        max(0.0, _finite_number(state.get("capacityKw")))
        * settings.converter_step_ratio
        for state in converter_states
    )
    ac_renewable_has_headroom = any(
        state.get("side") == "AC"
        and _number(state.get("currentKw")) is not None
        and _finite_number(state.get("marginKw")) > EPSILON
        for state in renewable_states
    )
    if (
        ac_renewable_has_headroom
        and converter_base_step_kw > EPSILON
        and diesel_current_kw > diesel_boundary_kw + EPSILON
        and diesel_current_kw - diesel_boundary_kw
        <= converter_base_step_kw + EPSILON
    ):
        for state in converter_states:
            current_kw = _number(state.get("currentKw"))
            target_kw = _number(state.get("targetKw"))
            capacity_kw = _number(state.get("capacityKw"))
            if (
                current_kw is None
                or target_kw is None
                or capacity_kw is None
                or target_kw >= current_kw - EPSILON
            ):
                continue
            state["targetKw"] = current_kw
            (
                state["exportMarginKw"],
                state["exportReductionMarginKw"],
            ) = _converter_export_margins_kw(
                state["row"],
                current_kw,
                current_kw,
                settings.converter_step_ratio * capacity_kw,
            )

    def allocate_renewable(
        states: Sequence[MutableMapping[str, Any]],
        request_kw: float,
        accepted_key: str = "",
    ) -> float:
        allocations = _allocate_by_margin(states, request_kw, "marginKw")
        for state, allocation_kw in zip(states, allocations):
            if _number(state.get("targetKw")) is None:
                continue
            state["targetKw"] = _finite_number(state.get("targetKw")) + allocation_kw
            state["marginKw"] = max(0.0, _finite_number(state.get("marginKw")) - allocation_kw)
            state["acceptedKw"] = _finite_number(state.get("acceptedKw")) + allocation_kw
            if accepted_key:
                state[accepted_key] = _finite_number(state.get(accepted_key)) + allocation_kw
        return sum(allocations)

    def charge_storage(states: Sequence[MutableMapping[str, Any]], request_kw: float) -> float:
        allocations = _allocate_by_margin(states, request_kw, "chargeMarginKw")
        for state, allocation_kw in zip(states, allocations):
            if _number(state.get("targetKw")) is None:
                continue
            state["targetKw"] = _finite_number(state.get("targetKw")) - allocation_kw
            state["chargeMarginKw"] = max(
                0.0, _finite_number(state.get("chargeMarginKw")) - allocation_kw
            )
        return sum(allocations)

    def increase_group_export(group_id: str, request_kw: float) -> float:
        states = [state for state in converter_states if state.get("groupId") == group_id]
        allocations = _allocate_by_margin(states, request_kw, "exportMarginKw")
        for state, allocation_kw in zip(states, allocations):
            if _number(state.get("targetKw")) is None:
                continue
            target_ac_injection_kw = _converter_ac_injection_kw(
                state["row"],
                state.get("targetKw"),
            )
            state["targetKw"] = _converter_target_from_ac_injection_kw(
                state["row"],
                target_ac_injection_kw + allocation_kw,
            )
            state["exportMarginKw"] = max(
                0.0, _finite_number(state.get("exportMarginKw")) - allocation_kw
            )
        return sum(allocations)

    ac_load_kw, dc_load_kw = _active_load_budgets(
        snapshot,
        measurements,
        resource_topology.dc_transfer_groups,
    )
    initial_ac_storage_effect_kw = sum(
        _finite_number(state.get("targetKw")) - _finite_number(state.get("currentKw"))
        for state in storage_states
        if state.get("side") == "AC" and state.get("currentKw") is not None
    )
    initial_export_effect_kw = sum(
        _converter_ac_injection_delta_kw(
            state["row"],
            state.get("currentKw"),
            state.get("targetKw"),
        )
        for state in converter_states
        if state.get("currentKw") is not None and state.get("targetKw") is not None
    )
    diesel_margin_kw = max(
        0.0,
        diesel_current_kw
        - max(
            diesel_min_kw,
            _finite_number(diesel_deadband_upper_kw, diesel_min_kw),
        )
        - max(0.0, initial_ac_storage_effect_kw)
        - max(0.0, initial_export_effect_kw),
    )
    direct_balance_rows = [
        row
        for row in storage_rows
        if row.get("role") == "balance"
        and row.get("stateEligible")
    ]
    ac_balance_rows = [
        row for row in direct_balance_rows if row.get("connectionSide") == "AC"
    ]

    ac_renewables = [state for state in renewable_states if state.get("side") == "AC"]
    ac_recovery_margin_kw = sum(_finite_number(state.get("marginKw")) for state in ac_renewables)
    ac_diesel_recovery_kw = allocate_renewable(
        ac_renewables,
        min(ac_recovery_margin_kw, diesel_margin_kw),
        "dieselAcceptedKw",
    )
    diesel_margin_kw = max(0.0, diesel_margin_kw - ac_diesel_recovery_kw)
    ac_storage_states = [state for state in storage_states if state.get("side") == "AC"]
    ac_charge_request_kw = min(
        sum(_finite_number(state.get("marginKw")) for state in ac_renewables),
        sum(_finite_number(state.get("chargeMarginKw")) for state in ac_storage_states),
    )
    ac_charge_source_kw = allocate_renewable(
        ac_renewables,
        ac_charge_request_kw,
        "acGridStorageAcceptedKw",
    )
    ac_storage_charge_kw = charge_storage(ac_storage_states, ac_charge_source_kw)
    if ac_storage_charge_kw + EPSILON < ac_charge_source_kw:
        rollback_kw = ac_charge_source_kw - ac_storage_charge_kw
        for state in reversed(ac_renewables):
            amount_kw = min(rollback_kw, _finite_number(state.get("acceptedKw")))
            state["targetKw"] = _finite_number(state.get("targetKw")) - amount_kw
            state["acceptedKw"] = _finite_number(state.get("acceptedKw")) - amount_kw
            state["acGridStorageAcceptedKw"] = max(
                0.0,
                _finite_number(state.get("acGridStorageAcceptedKw")) - amount_kw,
            )
            state["marginKw"] = _finite_number(state.get("marginKw")) + amount_kw
            rollback_kw -= amount_kw
            if rollback_kw <= EPSILON:
                break
    ac_balance_charge_request_kw = min(
        sum(_finite_number(state.get("marginKw")) for state in ac_renewables),
        sum(
            max(
                0.0,
                _finite_number(row.get("currentKw"))
                - _grid_storage_signed_power_bounds_kw(row)[0],
            )
            for row in ac_balance_rows
        ),
    )
    ac_balance_charge_accepted_kw = allocate_renewable(
        ac_renewables,
        ac_balance_charge_request_kw,
        "acBalanceAcceptedKw",
    )

    dc_budgets: List[_DcGroupBudget] = []
    dc_balance_delta_by_group: Dict[str, float] = {}
    paired_export_kw = 0.0
    for group_id in sorted(
        resource_topology.dc_transfer_groups,
        key=_natural_topology_identity,
    ):
        group_renewables = [
            state
            for state in renewable_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_storage = [
            state
            for state in storage_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_balance = [
            row
            for row in storage_rows
            if row.get("role") == "balance"
            and row.get("connectionSide") == "DC"
            and row.get("dcTransferGroupId") == group_id
            and row.get("stateEligible")
        ]
        renewable_current_kw = sum(
            _finite_number(state.get("currentKw")) for state in group_renewables
        )
        balance_current_kw = sum(
            _finite_number(row.get("currentKw")) for row in group_balance
        )
        local_deficit_kw = max(
            0.0,
            _finite_number(dc_load_kw.get(group_id))
            - renewable_current_kw
            - sum(
                _finite_number(state.get("currentKw"))
                for state in group_storage
            ),
        )
        local_recovery_kw = allocate_renewable(
            group_renewables,
            local_deficit_kw,
            "dcLocalLoadAcceptedKw",
        )
        charge_request_kw = min(
            sum(_finite_number(state.get("marginKw")) for state in group_renewables),
            sum(_finite_number(state.get("chargeMarginKw")) for state in group_storage),
        )
        charge_source_kw = allocate_renewable(
            group_renewables,
            charge_request_kw,
            "dcGridStorageAcceptedKw",
        )
        local_storage_charge_kw = charge_storage(group_storage, charge_source_kw)
        balance_charge_request_kw = min(
            sum(_finite_number(state.get("marginKw")) for state in group_renewables),
            sum(
                max(
                    0.0,
                    _finite_number(row.get("currentKw"))
                    - _grid_storage_signed_power_bounds_kw(row)[0],
                )
                for row in group_balance
            ),
        )
        balance_charge_source_kw = allocate_renewable(
            group_renewables,
            balance_charge_request_kw,
            "dcBalanceAcceptedKw",
        )
        dc_balance_delta_by_group[group_id] = -balance_charge_source_kw
        export_request_kw = min(
            sum(_finite_number(state.get("marginKw")) for state in group_renewables),
            diesel_margin_kw,
            sum(
                _finite_number(state.get("exportMarginKw"))
                for state in converter_states
                if state.get("groupId") == group_id
            ),
        )
        export_source_kw = allocate_renewable(
            group_renewables,
            export_request_kw,
            "dcAcdcExportAcceptedKw",
        )
        accepted_export_kw = increase_group_export(group_id, export_source_kw)
        paired_export_kw += accepted_export_kw
        diesel_margin_kw = max(0.0, diesel_margin_kw - accepted_export_kw)
        dc_budgets.append(
            _DcGroupBudget(
                group_id=group_id,
                renewable_current_kw=renewable_current_kw,
                renewable_recovery_kw=sum(
                    _finite_number(state.get("acceptedKw")) for state in group_renewables
                ),
                local_net_demand_kw=_finite_number(dc_load_kw.get(group_id)),
                grid_storage_charge_margin_kw=sum(
                    _finite_number(state.get("chargeMarginKw")) for state in group_storage
                ),
                grid_storage_discharge_margin_kw=sum(
                    _finite_number(state.get("dischargeMarginKw")) for state in group_storage
                ),
                balance_storage_charge_margin_kw=sum(
                    max(0.0, _finite_number(row.get("currentKw")) - _grid_storage_signed_power_bounds_kw(row)[0])
                    for row in group_balance
                ),
                balance_storage_discharge_margin_kw=sum(
                    max(0.0, _grid_storage_signed_power_bounds_kw(row)[1] - _finite_number(row.get("currentKw")))
                    for row in group_balance
                ),
                balance_storage_current_kw=balance_current_kw,
                acdc_current_export_kw=sum(
                    max(0.0, -_finite_number(state.get("currentKw")))
                    for state in converter_states
                    if state.get("groupId") == group_id
                ),
                acdc_export_headroom_kw=sum(
                    _finite_number(state.get("exportMarginKw"))
                    for state in converter_states
                    if state.get("groupId") == group_id
                ),
                acdc_step_headroom_kw=sum(
                    _finite_number(state.get("exportMarginKw"))
                    for state in converter_states
                    if state.get("groupId") == group_id
                ),
            )
        )

    ac_renewable_delta_kw = sum(
        _finite_number(state.get("targetKw")) - _finite_number(state.get("currentKw"))
        for state in ac_renewables
    )
    ac_storage_delta_kw = sum(
        _finite_number(state.get("targetKw")) - _finite_number(state.get("currentKw"))
        for state in ac_storage_states
    )
    export_delta_kw = sum(
        _converter_ac_injection_delta_kw(
            state["row"],
            state.get("currentKw"),
            state.get("targetKw"),
        )
        for state in converter_states
        if state.get("currentKw") is not None and state.get("targetKw") is not None
    )
    diesel_effect_kw = (
        ac_renewable_delta_kw
        - ac_balance_charge_accepted_kw
        + ac_storage_delta_kw
        + export_delta_kw
    )
    projected_targets, indirect_devices = _project_balance_storage_targets(
        direct_balance_rows,
        renewable_states,
        storage_states,
        converter_states,
        ac_balance_delta_kw=-ac_balance_charge_accepted_kw,
        dc_balance_delta_by_group=dc_balance_delta_by_group,
    )
    ac_balance = [
        row for row in direct_balance_rows if row.get("connectionSide") == "AC"
    ]
    ac_budget = _AcSideBudget(
        renewable_current_kw=sum(
            _finite_number(state.get("currentKw")) for state in ac_renewables
        ),
        renewable_recovery_kw=ac_renewable_delta_kw,
        local_net_demand_kw=ac_load_kw,
        diesel_down_margin_kw=max(0.0, diesel_current_kw - diesel_min_kw),
        grid_storage_charge_margin_kw=sum(
            _finite_number(state.get("chargeMarginKw")) for state in ac_storage_states
        ),
        grid_storage_discharge_margin_kw=sum(
            _finite_number(state.get("dischargeMarginKw")) for state in ac_storage_states
        ),
        balance_storage_charge_margin_kw=sum(
            max(
                0.0,
                _finite_number(row.get("currentKw"))
                - _grid_storage_signed_power_bounds_kw(row)[0],
            )
            for row in direct_balance_rows
            if row.get("connectionSide") == "AC"
        ),
        balance_storage_discharge_margin_kw=sum(
            max(
                0.0,
                _grid_storage_signed_power_bounds_kw(row)[1]
                - _finite_number(row.get("currentKw")),
            )
            for row in direct_balance_rows
            if row.get("connectionSide") == "AC"
        ),
        balance_storage_current_kw=sum(
            _finite_number(row.get("currentKw"))
            for row in storage_rows
            if row.get("role") == "balance" and row.get("connectionSide") == "AC"
        ),
        accepted_acdc_export_kw=paired_export_kw,
    )
    return {
        "renewableTargets": {
            state["key"]: state.get("targetKw") for state in renewable_states
        },
        "storageTargets": {
            state["key"]: state.get("targetKw") for state in storage_states
        },
        "storageStates": {state["key"]: state for state in storage_states},
        "converterTargets": {
            state["key"]: _clamp_converter_target_kw(
                state["row"],
                state.get("targetKw"),
            )
            for state in converter_states
            if state.get("targetKw") is not None
        },
        "dieselEffectKw": diesel_effect_kw,
        "dieselTargetKw": diesel_current_kw - diesel_effect_kw,
        "acBudget": ac_budget,
        "dcBudgets": tuple(dc_budgets),
        "projectedBalanceTargets": projected_targets,
        "indirectControlDevices": indirect_devices,
    }

def _side_aware_renewable_recovery_plan(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    settings: RenewableControlSettings,
    resource_topology: ResourceTopology,
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    initial_storage_targets: Mapping[Tuple[str, str], Any],
    initial_converter_targets: Mapping[Tuple[str, str], Any],
    initial_renewable_targets: Mapping[Tuple[str, str], Any],
    allow_topology_recovery_fallback: bool,
    *,
    diesel_current_kw: float,
    diesel_min_kw: float,
    diesel_deadband_upper_kw: Optional[float] = None,
) -> Dict[str, Any]:
    balance_rows = [
        row
        for row in storage_rows
        if row.get("role") == "balance"
        and row.get("stateEligible")
    ]
    protective_rows: List[Mapping[str, Any]] = []
    for row in balance_rows:
        current_kw = _number(row.get("currentKw"))
        if current_kw is None:
            continue
        signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
        if current_kw < signed_min_kw - EPSILON or current_kw > signed_max_kw + EPSILON:
            protective_rows.append(row)
    if not protective_rows:
        return _side_aware_renewable_recovery_plan_without_balance(
            snapshot,
            measurements,
            settings,
            resource_topology,
            renewable_rows,
            storage_rows,
            converter_rows,
            initial_storage_targets,
            initial_converter_targets,
            initial_renewable_targets,
            allow_topology_recovery_fallback,
            diesel_current_kw=diesel_current_kw,
            diesel_min_kw=diesel_min_kw,
            diesel_deadband_upper_kw=diesel_deadband_upper_kw,
        )

    protected_ac_present = any(
        row.get("connectionSide") == "AC" for row in protective_rows
    )
    protected_dc_group_ids = {
        str(row.get("dcTransferGroupId", ""))
        for row in protective_rows
        if row.get("connectionSide") == "DC"
        and str(row.get("dcTransferGroupId", ""))
    }

    def preserve_initial_storage_candidate(row: Mapping[str, Any]) -> bool:
        current_kw = _number(row.get("currentKw"))
        if current_kw is not None:
            signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            if (
                current_kw < signed_min_kw - EPSILON
                or current_kw > signed_max_kw + EPSILON
            ):
                return True
        if row.get("connectionSide") == "AC" and protected_ac_present:
            return False
        if (
            row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) in protected_dc_group_ids
        ):
            return False
        return True

    renewable_states: List[MutableMapping[str, Any]] = []
    for row in sorted(
        renewable_rows,
        key=lambda item: (
            str(item.get("connectionSide", "")),
            str(item.get("dcTransferGroupId", "")),
            str(item.get("technology", "")),
            str(item.get("dev_type", "")),
            str(item.get("dev_name", "")),
        ),
    ):
        current_kw = _number(row.get("planningCurrentKw"))
        capacity_kw = _number(row.get("capacityKw"))
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        initial_target_kw = _number(
            initial_renewable_targets.get(key),
            current_kw,
        )
        eligible = bool(
            row.get("commandable")
            and current_kw is not None
            and capacity_kw is not None
            and capacity_kw > EPSILON
            and -EPSILON <= current_kw <= capacity_kw + EPSILON
        )
        renewable_states.append(
            {
                "row": row,
                "key": key,
                "side": str(row.get("connectionSide", "")),
                "groupId": str(row.get("dcTransferGroupId", "")),
                "currentKw": current_kw,
                "targetKw": current_kw,
                "recoveryMarginKw": (
                    min(
                        max(0.0, capacity_kw - current_kw),
                        (
                            max(
                                0.0,
                                _finite_number(initial_target_kw, current_kw)
                                - current_kw,
                            )
                            or (
                                settings.step_coefficient * capacity_kw
                                if allow_topology_recovery_fallback
                                else 0.0
                            )
                        ),
                    )
                    if eligible
                    else 0.0
                ),
                "curtailMarginKw": (
                    max(0.0, current_kw)
                    if eligible
                    else 0.0
                ),
            }
        )
    storage_states = [
        _side_aware_storage_state(
            row,
            settings,
            initial_storage_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                row.get("currentKw"),
            ),
            preserve_initial=preserve_initial_storage_candidate(row),
        )
        for row in sorted(storage_rows, key=_grid_storage_sort_key)
        if row.get("role") == "grid_following"
    ]
    reduce_export_protective_group_ids = {
        str(row.get("dcTransferGroupId", ""))
        for row in balance_rows
        if row.get("connectionSide") == "DC"
        and str(row.get("dcTransferGroupId", ""))
        and _number(row.get("currentKw")) is not None
        and _finite_number(row.get("currentKw"))
        > _grid_storage_signed_power_bounds_kw(row)[1] + EPSILON
    }
    emergency_stop_export_group_ids = {
        str(row.get("dcTransferGroupId", ""))
        for row in balance_rows
        if row.get("connectionSide") == "DC"
        and str(row.get("dcTransferGroupId", ""))
        and _number(row.get("soc")) is not None
        and _number(row.get("socMin")) is not None
        and _finite_number(row.get("soc"))
        <= _finite_number(row.get("socMin")) + EPSILON
    }
    increase_export_protective_group_ids = {
        str(row.get("dcTransferGroupId", ""))
        for row in balance_rows
        if row.get("connectionSide") == "DC"
        and str(row.get("dcTransferGroupId", ""))
        and _number(row.get("currentKw")) is not None
        and _finite_number(row.get("currentKw"))
        < _grid_storage_signed_power_bounds_kw(row)[0] - EPSILON
    }
    converter_states: List[MutableMapping[str, Any]] = []
    for row in sorted(converter_rows, key=_converter_row_sort_key):
        current_kw = _number(row.get("currentKw"))
        capacity_kw = _number(row.get("transferCapacityKw"))
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        target_kw = _number(initial_converter_targets.get(key), current_kw)
        step_kw = (
            settings.converter_step_ratio * capacity_kw
            if capacity_kw is not None and capacity_kw > EPSILON
            else 0.0
        )
        if target_kw is not None:
            target_kw = _clamp_converter_target_kw(row, target_kw)
        group_id = str(row.get("dcTransferGroupId", ""))
        if (
            group_id in emergency_stop_export_group_ids
            and group_id not in increase_export_protective_group_ids
        ):
            target_kw = 0.0
        preserve_immediate_stop = bool(
            current_kw is not None
            and target_kw is not None
            and target_kw > current_kw + EPSILON
            and (
                group_id in emergency_stop_export_group_ids
                or current_kw > EPSILON
            )
        )
        if (
            current_kw is not None
            and target_kw is not None
            and not preserve_immediate_stop
        ):
            target_kw = _move_toward(current_kw, target_kw, step_kw)
        used_step_kw = (
            abs(target_kw - current_kw)
            if target_kw is not None and current_kw is not None
            else step_kw
        )
        remaining_step_kw = max(0.0, step_kw - used_step_kw)
        converter_states.append(
            {
                "row": row,
                "key": key,
                "groupId": group_id,
                "currentKw": current_kw,
                "targetKw": target_kw,
                "capacityKw": capacity_kw,
                "exportMarginKw": (
                    max(0.0, capacity_kw + target_kw)
                    if group_id in increase_export_protective_group_ids
                    and group_id not in reduce_export_protective_group_ids
                    else min(max(0.0, capacity_kw + target_kw), remaining_step_kw)
                    if row.get("commandable")
                    and current_kw is not None
                    and current_kw <= EPSILON
                    and target_kw is not None
                    and capacity_kw is not None
                    and capacity_kw > EPSILON
                    else 0.0
                ),
                "exportReductionMarginKw": (
                    max(0.0, -target_kw)
                    if row.get("commandable")
                    and target_kw is not None
                    and group_id in reduce_export_protective_group_ids
                    and group_id not in increase_export_protective_group_ids
                    else min(max(0.0, -target_kw), remaining_step_kw)
                    if row.get("commandable") and target_kw is not None
                    else 0.0
                ),
            }
        )

    def apply_margin(
        states: Sequence[MutableMapping[str, Any]],
        request_kw: float,
        margin_key: str,
        target_sign: float,
    ) -> float:
        allocations = _allocate_by_margin(states, request_kw, margin_key)
        for state, allocation_kw in zip(states, allocations):
            if _number(state.get("targetKw")) is None:
                continue
            state["targetKw"] = _finite_number(state.get("targetKw")) + target_sign * allocation_kw
            state[margin_key] = max(
                0.0, _finite_number(state.get(margin_key)) - allocation_kw
            )
        return sum(allocations)

    def group_converters(group_id: str) -> List[MutableMapping[str, Any]]:
        return [
            state
            for state in converter_states
            if state.get("groupId") == group_id
        ]

    initial_ac_storage_effect_kw = sum(
        _finite_number(state.get("targetKw"))
        - _finite_number(state.get("currentKw"))
        for state in storage_states
        if state.get("side") == "AC"
        and state.get("currentKw") is not None
        and state.get("targetKw") is not None
    )
    initial_export_effect_kw = sum(
        _converter_ac_injection_delta_kw(
            state["row"],
            state.get("currentKw"),
            state.get("targetKw"),
        )
        for state in converter_states
        if state.get("currentKw") is not None
        and state.get("targetKw") is not None
    )
    diesel_margin_kw = max(
        0.0,
        diesel_current_kw
        - max(
            diesel_min_kw,
            _finite_number(diesel_deadband_upper_kw, diesel_min_kw),
        )
        - max(0.0, initial_ac_storage_effect_kw)
        - max(0.0, initial_export_effect_kw),
    )
    protected_ac = [
        row for row in protective_rows if row.get("connectionSide") == "AC"
    ]
    protected_groups = sorted(
        protected_dc_group_ids,
        key=_natural_topology_identity,
    )
    initial_projected_targets, _initial_indirect_devices = (
        _project_balance_storage_targets(
            balance_rows,
            renewable_states,
            storage_states,
            converter_states,
        )
    )
    ac_load_kw, dc_load_kw = _active_load_budgets(
        snapshot,
        measurements,
        resource_topology.dc_transfer_groups,
    )
    healthy_ac_balance_charge_kw = 0.0
    healthy_dc_local_recovery_by_group: Dict[str, float] = {}

    if protected_ac:
        ac_renewables = [
            state for state in renewable_states if state.get("side") == "AC"
        ]
        ac_grid = [state for state in storage_states if state.get("side") == "AC"]
        low_request_kw = sum(
            max(
                0.0,
                _finite_number(
                    initial_projected_targets.get(
                        (
                            str(row.get("dev_type", "")),
                            str(row.get("dev_name", "")),
                        ),
                        row.get("currentKw"),
                    )
                )
                - _grid_storage_signed_power_bounds_kw(row)[1],
            )
            for row in protected_ac
        )
        high_request_kw = sum(
            max(
                0.0,
                _grid_storage_signed_power_bounds_kw(row)[0]
                - _finite_number(
                    initial_projected_targets.get(
                        (
                            str(row.get("dev_type", "")),
                            str(row.get("dev_name", "")),
                        ),
                        row.get("currentKw"),
                    )
                ),
            )
            for row in protected_ac
        )
        if low_request_kw > EPSILON:
            recovered_kw = apply_margin(
                ac_renewables,
                min(low_request_kw, diesel_margin_kw),
                "recoveryMarginKw",
                1.0,
            )
            diesel_margin_kw -= recovered_kw
            remaining_kw = max(0.0, low_request_kw - recovered_kw)
            discharged_kw = apply_margin(
                ac_grid,
                min(remaining_kw, diesel_margin_kw),
                "dischargeMarginKw",
                1.0,
            )
            diesel_margin_kw -= discharged_kw
            remaining_kw = max(0.0, remaining_kw - discharged_kw)
            for group_id in sorted(
                resource_topology.dc_transfer_groups,
                key=_natural_topology_identity,
            ):
                if remaining_kw <= EPSILON or diesel_margin_kw <= EPSILON:
                    break
                exported_kw = apply_margin(
                    group_converters(group_id),
                    min(remaining_kw, diesel_margin_kw),
                    "exportMarginKw",
                    -1.0,
                )
                diesel_margin_kw -= exported_kw
                remaining_kw -= exported_kw
        if any(
            _number(row.get("soc")) is not None
            and _number(row.get("socMin")) is not None
            and _finite_number(row.get("soc"))
            < _finite_number(row.get("socMin")) - EPSILON
            for row in protected_ac
        ):
            recovered_kw = apply_margin(
                ac_renewables,
                min(
                    diesel_margin_kw,
                    sum(
                        _finite_number(state.get("recoveryMarginKw"))
                        for state in ac_renewables
                    ),
                ),
                "recoveryMarginKw",
                1.0,
            )
            diesel_margin_kw = max(0.0, diesel_margin_kw - recovered_kw)
        if high_request_kw > EPSILON:
            verified_surplus_kw = min(
                high_request_kw,
                sum(
                    max(0.0, -_finite_number(row.get("currentKw")))
                    for row in protected_ac
                ),
                sum(
                    max(0.0, _finite_number(state.get("currentKw")))
                    for state in ac_renewables
                ),
            )
            charged_kw = apply_margin(
                ac_grid,
                verified_surplus_kw,
                "chargeMarginKw",
                -1.0,
            )
            remaining_kw = max(0.0, high_request_kw - charged_kw)
            curtailed_kw = apply_margin(
                ac_renewables,
                remaining_kw,
                "curtailMarginKw",
                -1.0,
            )
            remaining_kw -= curtailed_kw
            for group_id in sorted(
                resource_topology.dc_transfer_groups,
                key=_natural_topology_identity,
            ):
                if remaining_kw <= EPSILON:
                    break
                remaining_kw -= apply_margin(
                    group_converters(group_id),
                    remaining_kw,
                    "exportReductionMarginKw",
                    1.0,
                )

    for group_id in protected_groups:
        group_balance = [
            row
            for row in protective_rows
            if row.get("connectionSide") == "DC"
            and row.get("dcTransferGroupId") == group_id
        ]
        group_renewables = [
            state
            for state in renewable_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_grid = [
            state
            for state in storage_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        low_request_kw = sum(
            max(
                0.0,
                _finite_number(
                    initial_projected_targets.get(
                        (
                            str(row.get("dev_type", "")),
                            str(row.get("dev_name", "")),
                        ),
                        row.get("currentKw"),
                    )
                )
                - _grid_storage_signed_power_bounds_kw(row)[1],
            )
            for row in group_balance
        )
        high_request_kw = sum(
            max(
                0.0,
                _grid_storage_signed_power_bounds_kw(row)[0]
                - _finite_number(
                    initial_projected_targets.get(
                        (
                            str(row.get("dev_type", "")),
                            str(row.get("dev_name", "")),
                        ),
                        row.get("currentKw"),
                    )
                ),
            )
            for row in group_balance
        )
        if low_request_kw > EPSILON:
            reduced_export_kw = apply_margin(
                group_converters(group_id),
                low_request_kw,
                "exportReductionMarginKw",
                1.0,
            )
            remaining_kw = max(0.0, low_request_kw - reduced_export_kw)
            recovered_kw = apply_margin(
                group_renewables,
                remaining_kw,
                "recoveryMarginKw",
                1.0,
            )
            remaining_kw -= recovered_kw
            apply_margin(
                group_grid,
                remaining_kw,
                "dischargeMarginKw",
                1.0,
            )
        if any(
            _number(row.get("soc")) is not None
            and _number(row.get("socMin")) is not None
            and _finite_number(row.get("soc"))
            < _finite_number(row.get("socMin")) - EPSILON
            for row in group_balance
        ):
            apply_margin(
                group_renewables,
                sum(
                    _finite_number(state.get("recoveryMarginKw"))
                    for state in group_renewables
                ),
                "recoveryMarginKw",
                1.0,
            )
        if high_request_kw > EPSILON:
            exported_kw = apply_margin(
                group_converters(group_id),
                min(high_request_kw, diesel_margin_kw),
                "exportMarginKw",
                -1.0,
            )
            diesel_margin_kw -= exported_kw
            remaining_kw = max(0.0, high_request_kw - exported_kw)
            apply_margin(
                group_renewables,
                remaining_kw,
                "curtailMarginKw",
                -1.0,
            )

    # Protection is scoped to the affected side or DC transfer group.  A
    # protective action elsewhere must not suppress ordinary renewable
    # recovery where a healthy local storage or load can absorb the increase.
    if not protected_ac_present:
        healthy_ac_renewables = [
            state for state in renewable_states if state.get("side") == "AC"
        ]
        healthy_ac_grid_storage = [
            state for state in storage_states if state.get("side") == "AC"
        ]
        healthy_ac_balance_storage = [
            row
            for row in balance_rows
            if row.get("connectionSide") == "AC"
        ]
        recovered_kw = apply_margin(
            healthy_ac_renewables,
            min(
                diesel_margin_kw,
                sum(
                    _finite_number(state.get("recoveryMarginKw"))
                    for state in healthy_ac_renewables
                ),
            ),
            "recoveryMarginKw",
            1.0,
        )
        diesel_margin_kw = max(0.0, diesel_margin_kw - recovered_kw)
        grid_charge_request_kw = min(
            sum(
                _finite_number(state.get("recoveryMarginKw"))
                for state in healthy_ac_renewables
            ),
            sum(
                _finite_number(state.get("chargeMarginKw"))
                for state in healthy_ac_grid_storage
            ),
        )
        grid_charge_source_kw = apply_margin(
            healthy_ac_renewables,
            grid_charge_request_kw,
            "recoveryMarginKw",
            1.0,
        )
        apply_margin(
            healthy_ac_grid_storage,
            grid_charge_source_kw,
            "chargeMarginKw",
            -1.0,
        )
        balance_charge_request_kw = min(
            sum(
                _finite_number(state.get("recoveryMarginKw"))
                for state in healthy_ac_renewables
            ),
            sum(
                max(
                    0.0,
                    _finite_number(row.get("currentKw"))
                    - _grid_storage_signed_power_bounds_kw(row)[0],
                )
                for row in healthy_ac_balance_storage
            ),
        )
        healthy_ac_balance_charge_kw = apply_margin(
            healthy_ac_renewables,
            balance_charge_request_kw,
            "recoveryMarginKw",
            1.0,
        )

    for group_id in sorted(
        resource_topology.dc_transfer_groups,
        key=_natural_topology_identity,
    ):
        if group_id in protected_dc_group_ids:
            continue
        healthy_group_renewables = [
            state
            for state in renewable_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        healthy_group_grid_storage = [
            state
            for state in storage_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        healthy_group_balance_storage = [
            row
            for row in balance_rows
            if row.get("connectionSide") == "DC"
            and row.get("dcTransferGroupId") == group_id
        ]
        renewable_current_kw = sum(
            _finite_number(state.get("currentKw"))
            for state in healthy_group_renewables
        )
        local_deficit_kw = max(
            0.0,
            _finite_number(dc_load_kw.get(group_id))
            - renewable_current_kw
            - sum(
                _finite_number(state.get("currentKw"))
                for state in healthy_group_grid_storage
            ),
        )
        healthy_dc_local_recovery_by_group[group_id] = apply_margin(
            healthy_group_renewables,
            local_deficit_kw,
            "recoveryMarginKw",
            1.0,
        )
        grid_charge_request_kw = min(
            sum(
                _finite_number(state.get("recoveryMarginKw"))
                for state in healthy_group_renewables
            ),
            sum(
                _finite_number(state.get("chargeMarginKw"))
                for state in healthy_group_grid_storage
            ),
        )
        grid_charge_source_kw = apply_margin(
            healthy_group_renewables,
            grid_charge_request_kw,
            "recoveryMarginKw",
            1.0,
        )
        apply_margin(
            healthy_group_grid_storage,
            grid_charge_source_kw,
            "chargeMarginKw",
            -1.0,
        )
        balance_charge_request_kw = min(
            sum(
                _finite_number(state.get("recoveryMarginKw"))
                for state in healthy_group_renewables
            ),
            sum(
                max(
                    0.0,
                    _finite_number(row.get("currentKw"))
                    - _grid_storage_signed_power_bounds_kw(row)[0],
                )
                for row in healthy_group_balance_storage
            ),
        )
        apply_margin(
            healthy_group_renewables,
            balance_charge_request_kw,
            "recoveryMarginKw",
            1.0,
        )
        export_request_kw = min(
            sum(
                _finite_number(state.get("recoveryMarginKw"))
                for state in healthy_group_renewables
            ),
            diesel_margin_kw,
            sum(
                _finite_number(state.get("exportMarginKw"))
                for state in group_converters(group_id)
            ),
        )
        export_source_kw = apply_margin(
            healthy_group_renewables,
            export_request_kw,
            "recoveryMarginKw",
            1.0,
        )
        exported_kw = apply_margin(
            group_converters(group_id),
            export_source_kw,
            "exportMarginKw",
            -1.0,
        )
        diesel_margin_kw = max(0.0, diesel_margin_kw - exported_kw)

    ac_renewable_delta_kw = sum(
        _finite_number(state.get("targetKw")) - _finite_number(state.get("currentKw"))
        for state in renewable_states
        if state.get("side") == "AC"
    )
    ac_storage_delta_kw = sum(
        _finite_number(state.get("targetKw")) - _finite_number(state.get("currentKw"))
        for state in storage_states
        if state.get("side") == "AC"
    )
    export_delta_kw = sum(
        _converter_ac_injection_delta_kw(
            state["row"],
            state.get("currentKw"),
            state.get("targetKw"),
        )
        for state in converter_states
        if state.get("currentKw") is not None and state.get("targetKw") is not None
    )

    healthy_dc_balance_delta_by_group: Dict[str, float] = {}
    for group_id, local_recovery_kw in healthy_dc_local_recovery_by_group.items():
        group_renewables = [
            state
            for state in renewable_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_storage = [
            state
            for state in storage_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_converter_states = group_converters(group_id)
        renewable_delta_kw = sum(
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw"))
            for state in group_renewables
        )
        storage_delta_kw = sum(
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw"))
            for state in group_storage
        )
        export_delta_kw = sum(
            _converter_ac_injection_delta_kw(
                state["row"],
                state.get("currentKw"),
                state.get("targetKw"),
            )
            for state in group_converter_states
            if state.get("currentKw") is not None
            and state.get("targetKw") is not None
        )
        healthy_dc_balance_delta_by_group[group_id] = (
            -(renewable_delta_kw + storage_delta_kw)
            + export_delta_kw
            + local_recovery_kw
        )

    projected_targets, indirect_devices = _project_balance_storage_targets(
        balance_rows,
        renewable_states,
        storage_states,
        converter_states,
        ac_balance_delta_kw=(
            -healthy_ac_balance_charge_kw
            if not protected_ac_present
            else None
        ),
        dc_balance_delta_by_group=(
            healthy_dc_balance_delta_by_group
            if healthy_dc_balance_delta_by_group
            else None
        ),
    )

    dc_budgets = []
    for group_id in sorted(resource_topology.dc_transfer_groups):
        group_renewables = [
            state
            for state in renewable_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_grid = [
            state
            for state in storage_states
            if state.get("side") == "DC" and state.get("groupId") == group_id
        ]
        group_balance = [
            row
            for row in balance_rows
            if row.get("connectionSide") == "DC"
            and row.get("dcTransferGroupId") == group_id
        ]
        dc_budgets.append(
            _DcGroupBudget(
                group_id=group_id,
                renewable_current_kw=sum(
                    _finite_number(state.get("currentKw")) for state in group_renewables
                ),
                renewable_recovery_kw=sum(
                    max(
                        0.0,
                        _finite_number(state.get("targetKw"))
                        - _finite_number(state.get("currentKw")),
                    )
                    for state in group_renewables
                ),
                local_net_demand_kw=_finite_number(dc_load_kw.get(group_id)),
                grid_storage_charge_margin_kw=sum(
                    _finite_number(state.get("chargeMarginKw")) for state in group_grid
                ),
                grid_storage_discharge_margin_kw=sum(
                    _finite_number(state.get("dischargeMarginKw")) for state in group_grid
                ),
                balance_storage_charge_margin_kw=sum(
                    max(
                        0.0,
                        _finite_number(row.get("currentKw"))
                        - _grid_storage_signed_power_bounds_kw(row)[0],
                    )
                    for row in group_balance
                ),
                balance_storage_discharge_margin_kw=sum(
                    max(
                        0.0,
                        _grid_storage_signed_power_bounds_kw(row)[1]
                        - _finite_number(row.get("currentKw")),
                    )
                    for row in group_balance
                ),
                balance_storage_current_kw=sum(
                    _finite_number(row.get("currentKw")) for row in group_balance
                ),
                acdc_current_export_kw=sum(
                    max(0.0, -_finite_number(state.get("currentKw")))
                    for state in group_converters(group_id)
                ),
                acdc_export_headroom_kw=sum(
                    _finite_number(state.get("exportMarginKw"))
                    for state in group_converters(group_id)
                ),
                acdc_step_headroom_kw=sum(
                    _finite_number(state.get("exportMarginKw"))
                    for state in group_converters(group_id)
                ),
            )
        )
    ac_balance = [
        row for row in balance_rows if row.get("connectionSide") == "AC"
    ]
    ac_budget = _AcSideBudget(
        renewable_current_kw=sum(
            _finite_number(state.get("currentKw"))
            for state in renewable_states
            if state.get("side") == "AC"
        ),
        renewable_recovery_kw=ac_renewable_delta_kw,
        local_net_demand_kw=ac_load_kw,
        diesel_down_margin_kw=max(0.0, diesel_current_kw - diesel_min_kw),
        grid_storage_charge_margin_kw=sum(
            _finite_number(state.get("chargeMarginKw"))
            for state in storage_states
            if state.get("side") == "AC"
        ),
        grid_storage_discharge_margin_kw=sum(
            _finite_number(state.get("dischargeMarginKw"))
            for state in storage_states
            if state.get("side") == "AC"
        ),
        balance_storage_charge_margin_kw=sum(
            max(
                0.0,
                _finite_number(row.get("currentKw"))
                - _grid_storage_signed_power_bounds_kw(row)[0],
            )
            for row in ac_balance
        ),
        balance_storage_discharge_margin_kw=sum(
            max(
                0.0,
                _grid_storage_signed_power_bounds_kw(row)[1]
                - _finite_number(row.get("currentKw")),
            )
            for row in ac_balance
        ),
        balance_storage_current_kw=sum(
            _finite_number(row.get("currentKw")) for row in ac_balance
        ),
        accepted_acdc_export_kw=export_delta_kw,
    )
    diesel_effect_kw = (
        ac_renewable_delta_kw
        - (
            healthy_ac_balance_charge_kw
            if not protected_ac_present
            else 0.0
        )
        + ac_storage_delta_kw
        + export_delta_kw
    )
    return {
        "renewableTargets": {
            state["key"]: state.get("targetKw") for state in renewable_states
        },
        "storageTargets": {
            state["key"]: state.get("targetKw") for state in storage_states
        },
        "storageStates": {state["key"]: state for state in storage_states},
        "converterTargets": {
            state["key"]: _clamp_converter_target_kw(
                state["row"],
                state.get("targetKw"),
            )
            for state in converter_states
            if state.get("targetKw") is not None
        },
        "dieselEffectKw": diesel_effect_kw,
        "dieselTargetKw": diesel_current_kw - diesel_effect_kw,
        "acBudget": ac_budget,
        "dcBudgets": tuple(dc_budgets),
        "projectedBalanceTargets": projected_targets,
        "indirectControlDevices": indirect_devices,
    }

def _converter_direct_state(
    row: Mapping[str, Any],
    base_target_kw: Any,
    settings: RenewableControlSettings,
) -> Dict[str, Any]:
    current_kw = _number(row.get("currentKw"))
    capacity_kw = _number(row.get("transferCapacityKw"))
    parsed_base_target_kw = _number(base_target_kw)
    if (
        not row.get("commandable")
        or current_kw is None
        or capacity_kw is None
        or capacity_kw <= EPSILON
    ):
        return {
            "row": row,
            "groupId": str(row.get("dcTransferGroupId", "")),
            "currentKw": current_kw,
            "targetKw": (
                _clamp_converter_target_kw(row, parsed_base_target_kw)
                if parsed_base_target_kw is not None
                else _clamp_converter_target_kw(row, current_kw)
                if current_kw is not None
                else None
            ),
            "exportMarginKw": 0.0,
            "exportReductionMarginKw": 0.0,
            "eligible": False,
        }

    signed_min_kw, signed_max_kw = _converter_signed_bounds_kw(row)
    bounded_base_target_kw = _clamp(
        _finite_number(base_target_kw, current_kw),
        signed_min_kw,
        signed_max_kw,
    )
    step_kw = max(0.0, settings.converter_step_ratio * capacity_kw)
    export_margin_kw, export_reduction_margin_kw = (
        _converter_export_margins_kw(
            row,
            current_kw,
            bounded_base_target_kw,
            step_kw,
        )
    )
    return {
        "row": row,
        "groupId": str(row.get("dcTransferGroupId", "")),
        "currentKw": current_kw,
        "targetKw": bounded_base_target_kw,
        "capacityKw": capacity_kw,
        "stepKw": step_kw,
        "exportMarginKw": export_margin_kw,
        "exportReductionMarginKw": export_reduction_margin_kw,
        "eligible": bool(str(row.get("dcTransferGroupId", ""))),
    }

def _apply_converter_group_adjustment(
    converter_states: Sequence[MutableMapping[str, Any]],
    group_id: str,
    request_kw: float,
    *,
    increase_export: bool,
) -> float:
    margin_key = "exportMarginKw" if increase_export else "exportReductionMarginKw"
    group_states = [
        state
        for state in converter_states
        if state.get("eligible") and state.get("groupId") == group_id
    ]
    allocations = _allocate_by_margin(group_states, request_kw, margin_key)
    for state, allocation_kw in zip(group_states, allocations):
        row = state["row"]
        target_ac_injection_kw = _converter_ac_injection_kw(
            row,
            state.get("targetKw"),
        )
        if increase_export:
            target_ac_injection_kw += allocation_kw
        else:
            target_ac_injection_kw = max(
                0.0,
                target_ac_injection_kw - allocation_kw,
            )
        state["targetKw"] = _converter_target_from_ac_injection_kw(
            row,
            target_ac_injection_kw,
        )
        state[margin_key] = max(
            0.0,
            _finite_number(state.get(margin_key)) - allocation_kw,
        )
    return sum(allocations)
