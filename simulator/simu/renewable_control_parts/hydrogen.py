"""renewable_control 拆分模块：氢能运行指标与拓扑孤岛氢能优化。"""

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


def _hydrogen_operating_metrics(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    pressure_states: Sequence[Mapping[str, Any]],
    hydrogen_commands: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    devices = _device_by_model_key(snapshot)
    bindings_by_coupling = energy_coupling_control_bindings(snapshot)
    command_by_coupling = {
        (
            str(row.get("couplingType", "")),
            str(row.get("couplingName", "")),
        ): row
        for row in hydrogen_commands
        if (type(row) is dict or isinstance(row, Mapping))
    }
    category_values: Dict[str, Dict[str, List[float]]] = {
        "electrolyzer": {"currentPower": [], "targetPower": [], "currentFlow": [], "targetFlow": []},
        "fuelCell": {"currentPower": [], "targetPower": [], "currentFlow": [], "targetFlow": []},
    }
    configured_counts = {"electrolyzer": 0, "fuelCell": 0}
    online_counts = {"electrolyzer": 0, "fuelCell": 0}

    def append_inactive_metrics(
        values: MutableMapping[str, List[float]],
        command: Mapping[str, Any],
    ) -> None:
        target_power = _number(command.get("electricPowerKw"), 0.0) or 0.0
        target_flow = _number(command.get("equivalentFlow"), 0.0) or 0.0
        values["currentPower"].append(0.0)
        values["targetPower"].append(float(target_power))
        values["currentFlow"].append(0.0)
        values["targetFlow"].append(float(target_flow))

    for coupling_type in ("AcE2Hydro", "DcE2Hydro", "Hydro2AcE", "Hydro2DcE"):
        category = "electrolyzer" if coupling_type in {"AcE2Hydro", "DcE2Hydro"} else "fuelCell"
        coefficient_field = "e2h_coeff" if category == "electrolyzer" else "h2e_coeff"
        for coupling in _parameter_rows(snapshot, coupling_type):
            configured_counts[category] += 1
            coupling_name = _parameter_name(coupling).strip()
            coupling_device = devices.get((coupling_type, coupling_name))
            bindings = bindings_by_coupling.get((coupling_type, coupling_name), ())
            values = category_values[category]
            command = command_by_coupling.get((coupling_type, coupling_name), {})
            if coupling_device and not _is_online(coupling_device, measurements):
                append_inactive_metrics(values, command)
                continue
            if not coupling_device or len(bindings) != 2:
                continue
            power_binding = next((row for row in bindings if row.get("set_type") == "p_set"), None)
            flow_binding = next((row for row in bindings if row.get("set_type") == "flow_set"), None)
            if not power_binding or not flow_binding:
                continue
            power_key = (
                str(power_binding.get("target_dev_type", "")),
                str(power_binding.get("target_dev_name", "")),
            )
            flow_key = (
                str(flow_binding.get("target_dev_type", "")),
                str(flow_binding.get("target_dev_name", "")),
            )
            power_device = devices.get(power_key)
            flow_device = devices.get(flow_key)
            if (
                not power_device
                or not flow_device
                or not _is_online(power_device, measurements)
                or not _is_online(flow_device, measurements)
            ):
                if power_device and flow_device:
                    append_inactive_metrics(values, command)
                continue
            online_counts[category] += 1
            power_measurement = _measured(
                measurements,
                _device_type(power_device),
                power_key[1],
                ("P_LOAD", "P_GEN", "P", "P_AC", "P_DC"),
            )
            flow_measurement = _measured(
                measurements,
                _device_type(flow_device),
                flow_key[1],
                ("FLOW",),
            )
            coefficient = _number(coupling.get(coefficient_field))
            current_power = abs(power_measurement.value) if power_measurement else None
            current_flow = abs(flow_measurement.value) if flow_measurement else None
            if coefficient is not None and coefficient > EPSILON:
                if current_power is None and current_flow is not None:
                    current_power = (
                        current_flow / coefficient
                        if category == "electrolyzer"
                        else current_flow * coefficient
                    )
                if current_flow is None and current_power is not None:
                    current_flow = (
                        current_power * coefficient
                        if category == "electrolyzer"
                        else current_power / coefficient
                    )
            target_power = _number(command.get("electricPowerKw"))
            target_flow = _number(command.get("equivalentFlow"))
            if target_power is None:
                target_power = current_power
            if target_flow is None:
                target_flow = current_flow
            if current_power is not None and math.isfinite(current_power):
                values["currentPower"].append(float(current_power))
            if target_power is not None and math.isfinite(target_power):
                values["targetPower"].append(float(target_power))
            if current_flow is not None and math.isfinite(current_flow):
                values["currentFlow"].append(float(current_flow))
            if target_flow is not None and math.isfinite(target_flow):
                values["targetFlow"].append(float(target_flow))

    def total(values: Sequence[float]) -> Optional[float]:
        return sum(values) if values else None

    storage_pressures: List[float] = []
    storage_low_guards: List[float] = []
    storage_high_guards: List[float] = []
    storage_gas_quantities: List[float] = []
    storage_soc_values: List[float] = []
    storage_flows: List[float] = []
    online_storage_count = 0
    pressure_by_key = {
        (str(row.get("devType", "")), str(row.get("devName", ""))): row
        for row in pressure_states
        if (type(row) is dict or isinstance(row, Mapping))
    }
    configured_storage_count = 0
    for storage in _parameter_rows(snapshot, "HydroStorage"):
        configured_storage_count += 1
        storage_name = _parameter_name(storage).strip()
        storage_device = devices.get(("HydroStorage", storage_name))
        if not storage_device or not _is_online(storage_device, measurements):
            continue
        online_storage_count += 1
        device_type = _device_type(storage_device)
        state = pressure_by_key.get((device_type, storage_name), {})
        for key, target in (
            ("pressure", storage_pressures),
            ("lowGuard", storage_low_guards),
            ("highGuard", storage_high_guards),
        ):
            value = _number(state.get(key))
            if value is not None and math.isfinite(value):
                target.append(float(value))
        gas_quantity = _measured(measurements, device_type, storage_name, ("GAS_QUANTITY", "GAS_VOLUME"))
        soc = _measured(measurements, device_type, storage_name, ("SOC",))
        flow = _measured(measurements, device_type, storage_name, ("FLOW",))
        if gas_quantity is not None and math.isfinite(gas_quantity.value):
            storage_gas_quantities.append(float(gas_quantity.value))
        if soc is not None:
            soc_ratio = _live_soc_ratio(soc.value)
            if soc_ratio is not None and math.isfinite(soc_ratio):
                storage_soc_values.append(float(soc_ratio))
        if flow is not None and math.isfinite(flow.value):
            storage_flows.append(float(flow.value))

    def average(values: Sequence[float]) -> Optional[float]:
        return sum(values) / len(values) if values else None

    electrolyzer = category_values["electrolyzer"]
    fuel_cell = category_values["fuelCell"]
    return {
        "configuredElectrolyzerCount": configured_counts["electrolyzer"],
        "configuredFuelCellCount": configured_counts["fuelCell"],
        "configuredHydrogenStorageCount": configured_storage_count,
        "onlineElectrolyzerCount": online_counts["electrolyzer"],
        "onlineFuelCellCount": online_counts["fuelCell"],
        "onlineHydrogenStorageCount": online_storage_count,
        "electrolyzerCurrentKw": total(electrolyzer["currentPower"]),
        "electrolyzerTargetKw": total(electrolyzer["targetPower"]),
        "electrolyzerFlowCurrentNm3h": total(electrolyzer["currentFlow"]),
        "electrolyzerFlowTargetNm3h": total(electrolyzer["targetFlow"]),
        "fuelCellCurrentKw": total(fuel_cell["currentPower"]),
        "fuelCellTargetKw": total(fuel_cell["targetPower"]),
        "fuelCellFlowCurrentNm3h": total(fuel_cell["currentFlow"]),
        "fuelCellFlowTargetNm3h": total(fuel_cell["targetFlow"]),
        "hydrogenStoragePressureMpa": average(storage_pressures),
        "hydrogenStoragePressureLowGuardMpa": average(storage_low_guards),
        "hydrogenStoragePressureHighGuardMpa": average(storage_high_guards),
        "hydrogenStorageGasQuantityNm3": total(storage_gas_quantities),
        "hydrogenStorageSoc": average(storage_soc_values),
        "hydrogenStorageFlowNm3h": total(storage_flows),
    }

def _hydrogen_island_pressure_state(
    resource_topology: ResourceTopology,
    pressure_by_island: Mapping[str, Sequence[Mapping[str, Any]]],
    flow_key: Tuple[str, str],
) -> Tuple[str, Sequence[Mapping[str, Any]], str]:
    island_id = str(
        resource_topology.hydrogen_device_island_ids.get(flow_key, "")
    )
    if flow_key in set(resource_topology.hydrogen_invalid_devices):
        return "", (), "氢端设备节点或稳定身份无效"
    if not island_id:
        return "", (), "氢端设备未接入唯一有效氢网分岛"
    tanks = tuple(pressure_by_island.get(island_id, ()))
    if not tanks:
        return island_id, (), "所属氢网分岛没有在线储氢罐"
    if not all(row.get("pressureKnown") and row.get("limitsValid") for row in tanks):
        return island_id, tanks, "所属氢网分岛储氢罐压力或上下限无效"
    return island_id, tanks, ""

def _node_in_dc_transfer_group(
    resource_topology: ResourceTopology,
    node: Any,
) -> str:
    node_id = str(node if node is not None else "").strip()
    matches = [
        group_id
        for group_id, group in resource_topology.dc_transfer_groups.items()
        if node_id and node_id in group.dc_nodes
    ]
    return matches[0] if len(matches) == 1 else ""

def _dcac_unavailable_detail(
    snapshot: Mapping[str, Any],
    resource_topology: ResourceTopology,
    command_rows: Sequence[Mapping[str, Any]],
    dc_group_id: str,
) -> str:
    if not dc_group_id:
        return "直流设备未接入唯一有效直流拓扑组"

    group = resource_topology.dc_transfer_groups.get(dc_group_id)
    if group is None:
        return "直流设备所属拓扑组已失效"

    diagnostic_rows = [
        row
        for row in command_rows
        if _is_grid_converter_row(row)
        and str(row.get("dcTransferGroupId", "")) == dc_group_id
    ]
    if diagnostic_rows:
        details = sorted(
            {
                str(row.get("statusLabel", "")).split("·仅保留诊断", 1)[0].strip()
                for row in diagnostic_rows
                if str(row.get("statusLabel", "")).strip()
            }
        )
        suffix = f"（{'；'.join(details)}）" if details else ""
        return f"直流拓扑组DCAC当前不可调{suffix}"

    dc_nodes = set(group.dc_nodes)
    structural_keys = {
        (block_name, str(row.get("name", "")).strip())
        for block_name in ("ACDCConverter", "DCACConverter")
        for row in model_rows(snapshot, block_name)
        if str(row.get("name", "")).strip()
        and str(row.get("dc_node", "")).strip() in dc_nodes
    }
    if not structural_keys:
        return "直流拓扑组未配置DCAC"

    dispatchable_keys = structured_grid_converter_keys(snapshot)
    if not structural_keys.intersection(dispatchable_keys):
        return "直流拓扑组已配置DCAC，但其交/直流端未同时接入有效真实母线"

    active_keys = set(group.converter_keys)
    if not structural_keys.intersection(active_keys):
        return "直流拓扑组已配置DCAC，但当前离线或未活动接入交流电网"

    return "直流拓扑组DCAC已活动接入，但运行设备或遥调定义缺失"

def _allocate_converter_ac_injection_delta(
    converter_rows: Sequence[MutableMapping[str, Any]],
    delta_kw: float,
    *,
    step_ratio: Optional[float] = None,
) -> float:
    remaining = float(delta_kw)
    if abs(remaining) <= EPSILON:
        return 0.0
    ordered = sorted(converter_rows, key=_converter_row_sort_key)
    while abs(remaining) > EPSILON:
        margins = []
        for row in ordered:
            target_kw = _finite_number(row.get("commandKw"), row.get("currentKw"))
            target_injection = _converter_ac_injection_kw(row, target_kw)
            minimum, maximum = _converter_ac_injection_bounds_kw(row)
            physical_margin = (
                max(0.0, maximum - target_injection)
                if remaining > 0.0
                else max(0.0, target_injection - minimum)
            )
            step_kw = _number(row.get("stepKw"))
            if (
                step_kw is None
                and step_ratio is not None
                and step_ratio > EPSILON
            ):
                capacity_kw = _number(row.get("transferCapacityKw"))
                if capacity_kw is not None and capacity_kw > EPSILON:
                    step_kw = max(0.0, float(step_ratio) * capacity_kw)
            remaining_step_kw = (
                max(
                    0.0,
                    float(step_kw)
                    - abs(
                        _finite_number(row.get("commandKw"), row.get("currentKw"))
                        - _finite_number(row.get("currentKw"))
                    ),
                )
                if step_kw is not None
                else math.inf
            )
            margin = min(physical_margin, remaining_step_kw)
            margins.append(margin)
        total_margin = sum(margins)
        if total_margin <= EPSILON:
            break
        requested = min(abs(remaining), total_margin)
        allocations = [requested * margin / total_margin for margin in margins]
        delivered = 0.0
        for row, allocation in zip(ordered, allocations):
            if allocation <= EPSILON:
                continue
            old_target = _finite_number(row.get("commandKw"), row.get("currentKw"))
            old_injection = _converter_ac_injection_kw(row, old_target)
            new_injection = old_injection + (allocation if remaining > 0.0 else -allocation)
            new_target = _converter_target_from_ac_injection_kw(row, new_injection)
            row["commandKw"] = new_target
            row["strategyCommand"] = True
            delivered += abs(
                _converter_ac_injection_kw(row, new_target) - old_injection
            )
        if delivered <= EPSILON:
            break
        remaining -= delivered if remaining > 0.0 else -delivered
    return float(delta_kw) - remaining

def _row_command_delta_margin(
    rows: Sequence[Mapping[str, Any]],
    *,
    increase: bool,
) -> float:
    margin = 0.0
    for row in rows:
        current = _number(row.get("commandKw"))
        lower = _number(row.get("minKw"))
        upper = _number(row.get("capacityKw"))
        if current is None or lower is None or upper is None or lower > upper:
            continue
        margin += max(0.0, upper - current) if increase else max(0.0, current - lower)
    return margin

def _allocate_row_command_delta(
    rows: Sequence[MutableMapping[str, Any]],
    delta_kw: float,
) -> float:
    increase = delta_kw > 0.0
    remaining = abs(float(delta_kw))
    eligible = []
    for row in rows:
        current = _number(row.get("commandKw"))
        lower = _number(row.get("minKw"))
        upper = _number(row.get("capacityKw"))
        if current is None or lower is None or upper is None or lower > upper:
            continue
        margin = max(0.0, upper - current) if increase else max(0.0, current - lower)
        if margin > EPSILON:
            eligible.append((row, current, margin))
    total_margin = sum(item[2] for item in eligible)
    delivered = min(remaining, total_margin)
    if delivered <= EPSILON:
        return 0.0
    for row, current, margin in eligible:
        allocation = delivered * margin / total_margin
        row["commandKw"] = current + allocation if increase else current - allocation
        row["strategyCommand"] = True
        row["statusLabel"] = f"{row.get('statusLabel', '')}·综合能源原子平衡校核"
    return delivered if increase else -delivered

def _optimization_island_id_for_components(
    optimization_result: Optional[RenewableDispatchOptimizationResult],
    *component_ids: str,
) -> str:
    candidates = {
        str(component_id).strip()
        for component_id in component_ids
        if str(component_id).strip()
    }
    if optimization_result is not None and candidates:
        for island in optimization_result.islands:
            if candidates.intersection(island.component_ids):
                return island.island_id
    return next(iter(sorted(candidates)), "UNRESOLVED")

def _publish_final_acdc_coordination(
    command_rows: Sequence[MutableMapping[str, Any]],
    coordinated_converter_rows: Sequence[Mapping[str, Any]],
) -> None:
    """Publish AC/DC targets only after all island hydrogen decisions finish."""

    coordinated_by_key = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): row
        for row in coordinated_converter_rows
        if _is_grid_converter_row(row)
    }
    for row in command_rows:
        if not _is_grid_converter_row(row):
            continue
        coordinated = coordinated_by_key.get(
            (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        )
        if coordinated is None:
            continue
        row["commandKw"] = coordinated.get("commandKw", row.get("commandKw"))
        row["strategyCommand"] = coordinated.get(
            "strategyCommand",
            row.get("strategyCommand"),
        )

def _topology_island_hydrogen_plans(
    planned: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in planned:
        island_id = str(row.get("topologyIslandId", "UNRESOLVED")) or "UNRESOLVED"
        grouped.setdefault(island_id, []).append(dict(row))
    return [
        {
            "topologyIslandId": island_id,
            "hydrogenCommands": grouped[island_id],
            "acdcCoordinationStage": "final",
        }
        for island_id in sorted(grouped)
    ]

def _hydrogen_electric_resource_refs(
    snapshot: Mapping[str, Any],
) -> Tuple[ResourceRef, ...]:
    """Resolve hydrogen electric endpoints through the same graph as wind/PV."""

    refs: Dict[Tuple[str, str], ResourceRef] = {}
    for bindings in energy_coupling_control_bindings(snapshot).values():
        power_binding = next(
            (row for row in bindings if row.get("set_type") == "p_set"),
            None,
        )
        if power_binding is None:
            continue
        dev_type = str(power_binding.get("target_dev_type", "")).strip()
        dev_name = str(power_binding.get("target_dev_name", "")).strip()
        if not dev_type or not dev_name:
            continue
        refs[(dev_type, dev_name)] = ResourceRef(
            "hydrogen",
            dev_type,
            dev_name,
        )
    return tuple(refs[key] for key in sorted(refs))

def _optimize_hydrogen_within_topology_islands(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    settings: RenewableControlSettings,
    resource_topology: ResourceTopology,
    command_rows: List[Dict[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    *,
    diesel_current_kw: float,
    diesel_capacity_kw: Optional[float] = None,
    diesel_unit_count: int = 1,
    diesel_input_valid: bool = True,
    apply_electrical_corrections: bool = True,
    optimization_result: Optional[RenewableDispatchOptimizationResult] = None,
) -> Dict[str, Any]:
    hydrogen_electric_refs = _hydrogen_electric_resource_refs(snapshot)
    hydrogen_electric_connections = dict(resource_topology.resources)
    missing_hydrogen_refs = tuple(
        resource
        for resource in hydrogen_electric_refs
        if (resource.dev_type, resource.dev_name)
        not in hydrogen_electric_connections
    )
    if missing_hydrogen_refs:
        # Direct algorithm callers may provide a topology resolved before
        # hydrogen endpoints were registered. Resolve only those endpoints
        # through the same graph instead of falling back to type/name guesses.
        supplemental_topology = resolve_resource_topology(
            snapshot,
            missing_hydrogen_refs,
        )
        hydrogen_electric_connections.update(supplemental_topology.resources)
    diesel_unit_count = max(1, int(diesel_unit_count))
    diesel_capacity_kw = (
        max(0.0, float(diesel_capacity_kw))
        if diesel_capacity_kw is not None
        else 100.0 * diesel_unit_count
    )
    electrolyzer_diesel_limit_ratio = (
        float(settings.electrolyzer_diesel_power_limit_kw)
        * diesel_unit_count
        / diesel_capacity_kw
        if settings.electrolyzer_diesel_power_limit_kw is not None
        and diesel_capacity_kw > EPSILON
        else settings.electrolyzer_diesel_power_limit_ratio
    )
    electrolyzer_diesel_stop_maximum_ratio = (
        settings.electrolyzer_diesel_power_stop_maximum_ratio
    )
    fuel_cell_diesel_limit_ratio = (
        float(settings.fuel_cell_diesel_power_limit_kw)
        * diesel_unit_count
        / diesel_capacity_kw
        if settings.fuel_cell_diesel_power_limit_kw is not None
        and diesel_capacity_kw > EPSILON
        else settings.fuel_cell_diesel_power_limit_ratio
    )
    fuel_cell_diesel_stop_minimum_ratio = (
        settings.fuel_cell_diesel_power_stop_minimum_ratio
    )
    pressure_states = _hydrogen_pressure_states(snapshot, measurements, settings)
    pressure_by_island = _hydrogen_pressure_states_by_island(
        pressure_states,
        resource_topology,
    )
    diagnostics: Dict[str, Any] = {
        "optimizationScope": "topology-island",
        "coordinationSequence": [
            "renewable-diesel-storage",
            "hydrogen",
            "acdc-final",
        ],
        "acdcCoordinationStage": "final",
        "topologyIslandPlans": [],
        "closedLoopEnabled": bool(apply_electrical_corrections),
        "dispatchMode": (
            "closed-loop-atomic"
            if apply_electrical_corrections
            else "open-loop-preview"
        ),
        "pressureDeadbandRatio": settings.hydrogen_pressure_deadband_ratio,
        "pressureStates": pressure_states,
        "action": "hold",
        "electricPowerAdjustmentKw": 0.0,
        "targetElectricPowerKw": 0.0,
        "targetEquivalentFlow": 0.0,
        "commands": [],
        "decisionTraces": [],
        "converterCorrectionKw": 0.0,
        "balanceCorrectionKw": 0.0,
        "predictedDieselBeforeKw": diesel_current_kw,
        "predictedDieselAfterKw": diesel_current_kw,
        "dieselCapacityKw": diesel_capacity_kw,
        "dieselUnitCount": diesel_unit_count,
        "predictedDieselAverageBeforeKw": diesel_current_kw / diesel_unit_count,
        "predictedDieselAverageAfterKw": diesel_current_kw / diesel_unit_count,
        "predictedDieselLoadRatioBefore": (
            diesel_current_kw / diesel_capacity_kw
            if diesel_capacity_kw > EPSILON
            else None
        ),
        "predictedDieselLoadRatioAfter": (
            diesel_current_kw / diesel_capacity_kw
            if diesel_capacity_kw > EPSILON
            else None
        ),
        "electricStorageSocAverage": None,
        "atomic": True,
        "warnings": [],
    }
    diagnostics.update(
        _hydrogen_operating_metrics(
            snapshot,
            measurements,
            pressure_states,
        )
    )
    if not diesel_input_valid or diesel_capacity_kw <= EPSILON:
        diagnostics["action"] = "blocked"
        diagnostics["warnings"].append(
            "氢能策略缺少全部在线柴发的有效实时有功或额定容量，已按 fail closed 禁止计算"
        )
        return diagnostics

    model_rows = _definition_device_rows(
        snapshot,
        (
            "ACGenerator",
            "DCGenerator",
            "ACLoad",
            "DCLoad",
            "HydroSource",
            "HydroLoad",
            "AcE2Hydro",
            "DcE2Hydro",
            "Hydro2AcE",
            "Hydro2DcE",
        ),
    )
    devices = _device_by_model_key(snapshot)
    bindings_by_coupling = energy_coupling_control_bindings(snapshot)
    run_status_control_keys = _run_status_control_keys(snapshot)
    current_command_by_key = {
        (
            str(row.get("dev_type", "")),
            str(row.get("dev_name", "")),
            str(row.get("set_type", "")),
        ): row
        for row in command_rows
        if row.get("set_type")
    }

    # The two hydrogen conversion directions are physically exclusive.  Build
    # the interlock from explicit coupling bindings and live endpoint values
    # before planning either direction, so iteration order cannot start an
    # electrolyzer while a fuel cell is already running (or vice versa).
    active_hydrogen_modes: set[str] = set()
    for coupling_type in ("AcE2Hydro", "DcE2Hydro", "Hydro2AcE", "Hydro2DcE"):
        mode = (
            "electrolyzer"
            if coupling_type in {"AcE2Hydro", "DcE2Hydro"}
            else "fuel_cell"
        )
        for coupling in _parameter_rows(snapshot, coupling_type):
            coupling_name = _parameter_name(coupling).strip()
            coupling_device = devices.get((coupling_type, coupling_name))
            bindings = bindings_by_coupling.get((coupling_type, coupling_name), ())
            power_binding = next(
                (row for row in bindings if row.get("set_type") == "p_set"),
                None,
            )
            flow_binding = next(
                (row for row in bindings if row.get("set_type") == "flow_set"),
                None,
            )
            if not power_binding or not flow_binding:
                continue
            power_type = str(power_binding.get("target_dev_type", ""))
            power_name = str(power_binding.get("target_dev_name", ""))
            flow_type = str(flow_binding.get("target_dev_type", ""))
            flow_name = str(flow_binding.get("target_dev_name", ""))
            power_device = devices.get((power_type, power_name))
            flow_device = devices.get((flow_type, flow_name))
            if (
                not coupling_device
                or not _is_online(coupling_device, measurements)
                or not power_device
                or not flow_device
                or not _is_online(power_device, measurements)
                or not _is_online(flow_device, measurements)
            ):
                continue
            live_power = _measured(
                measurements,
                _device_type(power_device),
                power_name,
                ("P_LOAD", "P_GEN", "P", "P_AC", "P_DC"),
            )
            live_flow = _measured(
                measurements,
                _device_type(flow_device),
                flow_name,
                ("FLOW",),
            )
            coefficient_field = "e2h_coeff" if mode == "electrolyzer" else "h2e_coeff"
            coefficient = _number(coupling.get(coefficient_field))
            if live_power is not None:
                current_power = abs(live_power.value)
            elif live_flow is not None and coefficient is not None and coefficient > EPSILON:
                current_power = (
                    abs(live_flow.value) / coefficient
                    if mode == "electrolyzer"
                    else abs(live_flow.value) * coefficient
                )
            else:
                current_power = 0.0

            # A tiny residual measurement below the device's stop threshold is
            # an off-state value, not proof that the conversion direction is
            # running.  Otherwise near-zero values on both conversion devices
            # create a false interlock conflict and block a valid direct start.
            running_threshold_kw = EPSILON
            power_row = model_rows.get((power_type, power_name), {})
            flow_row = model_rows.get((flow_type, flow_name), {})
            rated_power_kw = _rated_capacity(power_row, power_device, "hydrogen")
            power_min = _number(power_row.get("p_min"))
            flow_min = _number(flow_row.get("flow_min"))
            if (
                coefficient is not None
                and coefficient > EPSILON
                and rated_power_kw > EPSILON
                and power_min is not None
                and flow_min is not None
            ):
                if mode == "electrolyzer":
                    configured_minimum = (
                        float(settings.electrolyzer_power_min_kw)
                        if settings.electrolyzer_power_min_kw is not None
                        else settings.electrolyzer_power_min_ratio * rated_power_kw
                    )
                    power_deadband_kw = (
                        float(settings.electrolyzer_power_deadband_kw)
                        if settings.electrolyzer_power_deadband_kw is not None
                        else settings.electrolyzer_power_deadband_ratio
                        * rated_power_kw
                    )
                    running_hysteresis_kw = power_deadband_kw
                    flow_power_min = max(0.0, flow_min) / coefficient
                else:
                    configured_minimum = (
                        float(settings.fuel_cell_power_min_kw)
                        if settings.fuel_cell_power_min_kw is not None
                        else settings.fuel_cell_power_min_ratio * rated_power_kw
                    )
                    power_deadband_kw = (
                        float(settings.fuel_cell_power_deadband_kw)
                        if settings.fuel_cell_power_deadband_kw is not None
                        else settings.fuel_cell_power_deadband_ratio * rated_power_kw
                    )
                    running_hysteresis_kw = (
                        float(settings.fuel_cell_power_step_kw)
                        if settings.fuel_cell_power_step_kw is not None
                        else settings.fuel_cell_power_step_ratio * rated_power_kw
                    )
                    flow_power_min = max(0.0, flow_min) * coefficient
                physical_minimum_power = max(0.0, power_min, flow_power_min)
                minimum_running_power = max(
                    physical_minimum_power,
                    configured_minimum,
                )
                running_threshold_kw = max(
                    0.0,
                    minimum_running_power - running_hysteresis_kw,
                )
            running = bool(
                current_power > EPSILON
                and (
                    running_threshold_kw <= EPSILON
                    or current_power >= running_threshold_kw - EPSILON
                )
            )
            if running:
                active_hydrogen_modes.add(mode)

    hydrogen_mode_lock = (
        next(iter(active_hydrogen_modes))
        if len(active_hydrogen_modes) == 1
        else "conflict"
        if len(active_hydrogen_modes) > 1
        else ""
    )
    diagnostics["interlockMode"] = hydrogen_mode_lock or "idle"
    diagnostics["interlockActive"] = bool(hydrogen_mode_lock)
    conflict_stop_mode = ""
    conflict_keep_mode = ""
    if hydrogen_mode_lock == "conflict":
        initial_diesel_load_ratio = diesel_current_kw / diesel_capacity_kw
        conflict_stop_mode = (
            "electrolyzer"
            if initial_diesel_load_ratio
            > fuel_cell_diesel_limit_ratio + EPSILON
            else "fuel_cell"
        )
        conflict_keep_mode = (
            "fuel_cell" if conflict_stop_mode == "electrolyzer" else "electrolyzer"
        )
        diagnostics["interlockStopMode"] = conflict_stop_mode
        diagnostics["interlockKeepMode"] = conflict_keep_mode
        diagnostics["warnings"].append(
            "实时量测显示电制氢和燃料电池同时运行，"
            f"柴发负载率{initial_diesel_load_ratio * 100:.3f}%"
            f"{'高于' if conflict_stop_mode == 'electrolyzer' else '未高于'}"
            f"燃料电池柴发负载率限值{fuel_cell_diesel_limit_ratio * 100:.3f}%，"
            f"本轮停止{'电制氢' if conflict_stop_mode == 'electrolyzer' else '燃料电池'}，"
            f"保留{'燃料电池' if conflict_keep_mode == 'fuel_cell' else '电制氢'}运行"
        )

    online_storage = [row for row in storage_rows if row.get("online")]
    known_storage_soc = [
        float(row["soc"])
        for row in online_storage
        if row.get("socKnown")
        and _number(row.get("soc")) is not None
        and math.isfinite(float(row["soc"]))
    ]
    electric_storage_soc = (
        sum(known_storage_soc) / len(known_storage_soc)
        if online_storage and len(known_storage_soc) == len(online_storage)
        else None
    )
    diagnostics["electricStorageSocAverage"] = electric_storage_soc
    coupling_types = ("AcE2Hydro", "DcE2Hydro", "Hydro2AcE", "Hydro2DcE")
    planned: List[Dict[str, Any]] = []
    converter_correction = 0.0
    balance_correction = 0.0
    predicted_diesel_kw = float(diesel_current_kw)
    # Hydrogen feasibility probes and successive devices share a private AC/DC
    # working set.  The public command rows are left untouched until every
    # hydrogen decision has completed, so the converter is the final island
    # coordination stage instead of an input that is repeatedly published and
    # corrected during hydrogen planning.
    coordinated_converter_rows: List[MutableMapping[str, Any]] = [
        copy.deepcopy(row)
        for row in command_rows
        if _is_grid_converter_row(row)
    ]
    diesel_command_rows = [
        row
        for row in command_rows
        if row.get("category") == "柴油发电"
        and row.get("online")
        and row.get("commandable") is not False
    ]
    for coupling_type in coupling_types:
        is_electrolyzer = coupling_type in {"AcE2Hydro", "DcE2Hydro"}
        for coupling in _parameter_rows(snapshot, coupling_type):
            coupling_name = _parameter_name(coupling).strip()
            coupling_key = (coupling_type, coupling_name)
            coupling_device = devices.get((coupling_type, coupling_name))
            bindings = bindings_by_coupling.get((coupling_type, coupling_name), ())
            coupling_online = bool(
                coupling_device and _is_online(coupling_device, measurements)
            )
            if (
                not coupling_device
                or len(bindings) != 2
                or (
                    not coupling_online
                    and coupling_key not in run_status_control_keys
                )
            ):
                continue
            power_binding = next((row for row in bindings if row.get("set_type") == "p_set"), None)
            flow_binding = next((row for row in bindings if row.get("set_type") == "flow_set"), None)
            active_binding = next((row for row in bindings if row.get("active")), None)
            if not power_binding or not flow_binding or not active_binding:
                continue
            power_type = str(power_binding.get("target_dev_type", ""))
            power_name = str(power_binding.get("target_dev_name", ""))
            flow_type = str(flow_binding.get("target_dev_type", ""))
            flow_name = str(flow_binding.get("target_dev_name", ""))
            flow_key = (flow_type, flow_name)
            hydrogen_island_id, island_tanks, topology_error = (
                _hydrogen_island_pressure_state(
                    resource_topology,
                    pressure_by_island,
                    flow_key,
                )
            )
            if topology_error:
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}{topology_error}，本设备已按 fail closed 禁止自动调节"
                )
                continue
            pressure_blocked = bool(
                any(
                    float(row["pressure"]) >= float(row["highGuard"])
                    for row in island_tanks
                )
                if is_electrolyzer
                else any(
                    float(row["pressure"]) < float(row["lowGuard"])
                    for row in island_tanks
                )
            )
            island_soc_values = [
                float(row["soc"])
                for row in island_tanks
                if row.get("online")
                and row.get("socKnown")
                and _number(row.get("soc")) is not None
                and math.isfinite(float(row["soc"]))
            ]
            online_island_tanks = [row for row in island_tanks if row.get("online")]
            hydrogen_storage_soc = (
                sum(island_soc_values) / len(island_soc_values)
                if online_island_tanks
                and len(island_soc_values) == len(online_island_tanks)
                else None
            )
            power_row = model_rows.get((power_type, power_name), {})
            flow_row = model_rows.get((flow_type, flow_name), {})
            power_device = devices.get((power_type, power_name))
            flow_device = devices.get((flow_type, flow_name))
            if (
                not power_device
                or not flow_device
                or not _is_online(power_device, measurements)
                or not _is_online(flow_device, measurements)
            ):
                continue
            power_connection = hydrogen_electric_connections.get(
                (power_type, power_name)
            )
            if (
                power_connection is None
                or power_connection.connection_side not in {"AC", "DC"}
                or not power_connection.actively_connected
                or not power_connection.grid_component_id
            ):
                topology_label = (
                    power_connection.topology_status_label
                    if power_connection is not None
                    else "未纳入资源拓扑"
                )
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}的电端{power_type}.{power_name}"
                    f"并网侧拓扑无效（{topology_label}），已按 fail closed 禁止自动调节"
                )
                continue
            # The final real-bus side is resolved from the active graph, exactly
            # like wind/PV.  Converter crossings are part of active_path; no
            # endpoint type or device-name prefix is used as a side heuristic.
            electric_side = power_connection.connection_side
            electric_component_id = power_connection.grid_component_id
            dc_group_id = (
                power_connection.dc_transfer_group_id
                if electric_side == "DC"
                else ""
            )
            coefficient_field = "e2h_coeff" if is_electrolyzer else "h2e_coeff"
            coefficient = _number(coupling.get(coefficient_field))
            if coefficient is None or coefficient <= EPSILON:
                continue
            power_min = _number(power_row.get("p_min"))
            power_max = _number(power_row.get("p_max"))
            rated_power_kw = _rated_capacity(power_row, power_device, "hydrogen")
            flow_min = _number(flow_row.get("flow_min"))
            flow_max = _number(flow_row.get("flow_max"))
            if (
                power_min is None
                or power_max is None
                or power_min > power_max
                or rated_power_kw <= EPSILON
                or flow_min is None
                or flow_max is None
                or flow_min > flow_max
            ):
                continue
            power_measurement = _measured(
                measurements,
                _device_type(power_device),
                power_name,
                ("P_LOAD", "P_GEN", "P", "P_AC", "P_DC"),
            )
            flow_measurement = _measured(
                measurements,
                _device_type(flow_device),
                flow_name,
                ("FLOW",),
            )
            if not coupling_online:
                # RunStat is authoritative for an explicitly stopped coupling.
                # Endpoint measurements can lag for one collection cycle and
                # must not make an off device look operationally running.
                current_power = 0.0
            elif power_measurement is not None:
                current_power = abs(power_measurement.value)
            elif flow_measurement is not None:
                current_power = (
                    abs(flow_measurement.value) / float(coefficient)
                    if is_electrolyzer
                    else abs(flow_measurement.value) * float(coefficient)
                )
            else:
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}缺少实时电功率和氢流量量测，已按 fail closed 保持当前状态"
                )
                continue
            if is_electrolyzer:
                flow_power_max = max(0.0, float(flow_max)) / float(coefficient)
                flow_power_min = max(0.0, float(flow_min)) / float(coefficient)
                configured_minimum = (
                    float(settings.electrolyzer_power_min_kw)
                    if settings.electrolyzer_power_min_kw is not None
                    else settings.electrolyzer_power_min_ratio * rated_power_kw
                )
                configured_maximum = (
                    float(settings.electrolyzer_power_max_kw)
                    if settings.electrolyzer_power_max_kw is not None
                    else settings.electrolyzer_power_max_ratio * rated_power_kw
                )
                power_deadband_kw = (
                    float(settings.electrolyzer_power_deadband_kw)
                    if settings.electrolyzer_power_deadband_kw is not None
                    else settings.electrolyzer_power_deadband_ratio * rated_power_kw
                )
                step_kw = (
                    float(settings.electrolyzer_power_step_kw)
                    if settings.electrolyzer_power_step_kw is not None
                    else settings.electrolyzer_power_step_ratio * rated_power_kw
                )
            else:
                flow_power_max = max(0.0, float(flow_max)) * float(coefficient)
                flow_power_min = max(0.0, float(flow_min)) * float(coefficient)
                configured_minimum = (
                    float(settings.fuel_cell_power_min_kw)
                    if settings.fuel_cell_power_min_kw is not None
                    else settings.fuel_cell_power_min_ratio * rated_power_kw
                )
                configured_maximum = (
                    float(settings.fuel_cell_power_max_kw)
                    if settings.fuel_cell_power_max_kw is not None
                    else settings.fuel_cell_power_max_ratio * rated_power_kw
                )
                power_deadband_kw = (
                    float(settings.fuel_cell_power_deadband_kw)
                    if settings.fuel_cell_power_deadband_kw is not None
                    else settings.fuel_cell_power_deadband_ratio * rated_power_kw
                )
                step_kw = (
                    float(settings.fuel_cell_power_step_kw)
                    if settings.fuel_cell_power_step_kw is not None
                    else settings.fuel_cell_power_step_ratio * rated_power_kw
                )
            allowed_power = min(
                max(0.0, float(power_max)),
                flow_power_max,
                configured_maximum,
            )
            physical_minimum_power = max(
                0.0,
                float(power_min),
                flow_power_min,
            )
            minimum_running_power = max(
                physical_minimum_power,
                configured_minimum,
            )
            if is_electrolyzer:
                start_threshold_kw = minimum_running_power + power_deadband_kw
            else:
                # Fuel-cell startup keeps its dedicated minimum-plus-step rule.
                start_threshold_kw = minimum_running_power + step_kw
            # Both hydrogen devices stop only when the resulting strategy is
            # strictly below the effective lower limit minus the deadband.
            stop_threshold_kw = max(
                0.0,
                minimum_running_power - power_deadband_kw,
            )
            maintain_stopped_snapshot = not coupling_online
            predicted_diesel_load_ratio = predicted_diesel_kw / diesel_capacity_kw
            decision_trace: Dict[str, Any] = {
                "mode": "electrolyzer" if is_electrolyzer else "fuel_cell",
                "couplingType": coupling_type,
                "couplingName": coupling_name,
                "currentElectricPowerKw": current_power,
                "targetElectricPowerKw": current_power,
                "electricDeltaKw": 0.0,
                "dieselLoadRatioBefore": predicted_diesel_load_ratio,
                "dieselStartThresholdRatio": (
                    electrolyzer_diesel_limit_ratio
                    if is_electrolyzer
                    else fuel_cell_diesel_limit_ratio
                ),
                "dieselStopThresholdRatio": (
                    electrolyzer_diesel_stop_maximum_ratio
                    if is_electrolyzer
                    else fuel_cell_diesel_stop_minimum_ratio
                ),
                "electricStorageSocAverage": electric_storage_soc,
                "hydrogenStorageSocAverage": hydrogen_storage_soc,
                "startThresholdKw": start_threshold_kw,
                "stopThresholdKw": stop_threshold_kw,
                "stepLimitKw": step_kw,
                "minimumRunningPowerKw": minimum_running_power,
                "powerDeadbandKw": power_deadband_kw,
                "pressureSafetyStop": pressure_blocked,
                "action": "hold",
                "controlReason": "hold_region",
                "blockers": [],
            }
            if (
                minimum_running_power > allowed_power + EPSILON
            ):
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}配置上下限与模型功率/流量边界无有效运行区间，"
                    "本设备已按 fail closed 禁止自动调节"
                )
                decision_trace.update(
                    {
                        "action": "blocked",
                        "controlReason": "invalid_operating_envelope",
                        "blockers": ["配置上下限与模型功率/流量边界无有效运行区间"],
                    }
                )
                diagnostics["decisionTraces"].append(decision_trace)
                continue

            power_hysteresis_stop = False
            safety_stop = pressure_blocked and current_power > EPSILON
            device_action = "electrolyzer" if is_electrolyzer else "fuel_cell"
            device_action_reason = ""
            requested_delta_kw = 0.0
            required_start_delta_kw: Optional[float] = None
            fuel_cell_decision = None
            if is_electrolyzer:
                diesel_raise_margin_kw = max(
                    0.0,
                    electrolyzer_diesel_limit_ratio * diesel_capacity_kw
                    - predicted_diesel_kw,
                )
                # 氢储 SOC 启机/升功率引入回差死区（默认停机 90% - 死区 5% = 85%），避免在 90% 边界高频抖动
                h2_stop_limit = settings.electrolyzer_hydrogen_storage_soc_stop_minimum
                h2_deadband = max(0.0, float(settings.hydrogen_pressure_deadband_ratio))
                electrolyzer_h2_raise_limit = max(0.0, h2_stop_limit - h2_deadband)
                electrolyzer_raise_allowed = bool(
                    diesel_raise_margin_kw > EPSILON
                    and electric_storage_soc is not None
                    and electric_storage_soc
                    > settings.electrolyzer_storage_soc_start_minimum + EPSILON
                    and hydrogen_storage_soc is not None
                    and hydrogen_storage_soc
                    < electrolyzer_h2_raise_limit - EPSILON
                    and hydrogen_mode_lock != "fuel_cell"
                    and conflict_stop_mode != "electrolyzer"
                )
                electrolyzer_reduce_required = bool(
                    predicted_diesel_load_ratio
                    > electrolyzer_diesel_stop_maximum_ratio + EPSILON
                    or (
                        electric_storage_soc is not None
                        and electric_storage_soc
                        < settings.electrolyzer_storage_soc_stop_maximum - EPSILON
                    )
                    or (
                        hydrogen_storage_soc is not None
                        and hydrogen_storage_soc > h2_stop_limit + EPSILON
                    )
                )
            else:
                fuel_cell_decision = calculate_fuel_cell_power_decision(
                    FuelCellControlParameters(
                        power_step_kw=step_kw,
                        diesel_power_limit_ratio=fuel_cell_diesel_limit_ratio,
                        diesel_power_stop_minimum_ratio=(
                            fuel_cell_diesel_stop_minimum_ratio
                        ),
                        electric_storage_soc_limit=settings.fuel_cell_storage_soc_limit,
                        hydrogen_storage_soc_start_limit=(
                            settings.fuel_cell_hydrogen_storage_soc_upper_limit
                        ),
                        hydrogen_storage_soc_stop_limit=(
                            settings.fuel_cell_hydrogen_storage_soc_lower_limit
                        ),
                    ),
                    FuelCellControlInputs(
                        current_power_kw=current_power,
                        maximum_power_kw=allowed_power,
                        minimum_power_kw=minimum_running_power,
                        start_threshold_kw=start_threshold_kw,
                        stop_threshold_kw=stop_threshold_kw,
                        diesel_power_kw=predicted_diesel_kw,
                        diesel_capacity_kw=diesel_capacity_kw,
                        electric_storage_soc_average=electric_storage_soc,
                        hydrogen_storage_soc_average=hydrogen_storage_soc,
                    ),
                )
                if (
                    (
                        hydrogen_mode_lock == "electrolyzer"
                        or conflict_stop_mode == "fuel_cell"
                    )
                    and fuel_cell_decision.action in {"start", "increase"}
                ):
                    diagnostics["warnings"].append(
                        f"氢能设备{coupling_name}受电制氢运行互锁，已禁止燃料电池启动或升功率"
                    )
                    fuel_cell_decision = FuelCellControlDecision(
                        action="hold",
                        reason="hydrogen_mode_interlock",
                        diesel_raise_margin_kw=(
                            fuel_cell_decision.diesel_raise_margin_kw
                        ),
                        diesel_reduce_margin_kw=(
                            fuel_cell_decision.diesel_reduce_margin_kw
                        ),
                    )
            conflict_stops_device = bool(
                hydrogen_mode_lock == "conflict"
                and (
                    (is_electrolyzer and conflict_stop_mode == "electrolyzer")
                    or (not is_electrolyzer and conflict_stop_mode == "fuel_cell")
                )
            )
            if conflict_stops_device and current_power > EPSILON:
                requested_delta_kw = -current_power
                device_action = "hydrogen_interlock_stop"
                device_action_reason = (
                    f"simultaneous_operation_stop_{conflict_stop_mode}"
                )
            elif pressure_blocked:
                requested_delta_kw = -current_power
                device_action_reason = "pressure_safety_stop"
            elif current_power > allowed_power + EPSILON:
                requested_delta_kw = allowed_power - current_power
                device_action = (
                    "electrolyzer_reduce" if is_electrolyzer else "fuel_cell_reduce"
                )
                device_action_reason = "above_upper_power_limit_correction"
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}实时功率{current_power:.3f} kW高于有效上限"
                    f"{allowed_power:.3f} kW，本轮纠偏至上限并保留完整运行快照"
                )
            elif (
                is_electrolyzer
                and current_power > EPSILON
                and current_power < stop_threshold_kw - EPSILON
                and electrolyzer_raise_allowed
            ):
                # A sub-threshold residual is operationally stopped.  When all
                # electrolyzer entry predicates are true, recover it directly
                # to the complete start threshold in this same control cycle.
                required_start_delta_kw = max(
                    0.0,
                    start_threshold_kw - current_power,
                )
                requested_delta_kw = required_start_delta_kw
                device_action_reason = "entry_conditions_met_direct_start"
            elif (
                not is_electrolyzer
                and current_power > EPSILON
                and current_power < stop_threshold_kw - EPSILON
                and fuel_cell_decision is not None
                and fuel_cell_decision.action == "start"
            ):
                # A sub-threshold telemetry residue is operationally stopped.
                # If all fuel-cell entry predicates hold, bypass the normal
                # ramp limit and recover directly to minimum power plus one step.
                requested_delta_kw = fuel_cell_decision.requested_delta_kw
                required_start_delta_kw = fuel_cell_decision.required_start_delta_kw
                device_action_reason = fuel_cell_decision.reason
            elif current_power > EPSILON and current_power < stop_threshold_kw - EPSILON:
                requested_delta_kw = -current_power
                power_hysteresis_stop = True
                device_action = "power_hysteresis_stop"
                device_action_reason = "below_stop_threshold"
            elif electric_storage_soc is None or hydrogen_storage_soc is None:
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}缺少完整的在线电储平均SOC或本氢岛氢储平均SOC，已按 fail closed 保持当前功率"
                )
                if not maintain_stopped_snapshot:
                    decision_trace.update(
                        {
                            "action": "blocked",
                            "controlReason": "incomplete_average_input",
                            "blockers": ["缺少完整的在线电储平均SOC或本氢岛氢储平均SOC"],
                        }
                    )
                    diagnostics["decisionTraces"].append(decision_trace)
                    continue
                device_action = "hydrogen_stopped_hold"
                device_action_reason = "incomplete_average_input_fail_closed_stop"
            elif is_electrolyzer and current_power > EPSILON:
                if electrolyzer_raise_allowed:
                    device_action_reason = "raise_conditions_met"
                    requested_delta_kw = min(
                        diesel_raise_margin_kw,
                        step_kw,
                        max(0.0, allowed_power - current_power),
                    )
                elif electrolyzer_reduce_required:
                    device_action = "electrolyzer_reduce"
                    reduce_reasons: List[str] = []
                    if (
                        predicted_diesel_load_ratio
                        > electrolyzer_diesel_stop_maximum_ratio + EPSILON
                    ):
                        reduce_reasons.append("diesel_power_above_stop_threshold")
                    if (
                        electric_storage_soc
                        < settings.electrolyzer_storage_soc_stop_maximum - EPSILON
                    ):
                        reduce_reasons.append("electric_storage_soc_below_stop_threshold")
                    if (
                        hydrogen_storage_soc
                        > settings.electrolyzer_hydrogen_storage_soc_stop_minimum
                        + EPSILON
                    ):
                        reduce_reasons.append("hydrogen_storage_soc_above_stop_threshold")
                    device_action_reason = "+".join(reduce_reasons) or "reduce_condition_met"
                    requested_delta_kw = -min(
                        step_kw,
                        current_power,
                    )
            elif is_electrolyzer:
                if not electrolyzer_raise_allowed:
                    if (
                        hydrogen_mode_lock == "fuel_cell"
                        or conflict_stop_mode == "electrolyzer"
                    ):
                        start_blockers = ["与燃料电池运行互锁"]
                        diagnostics["warnings"].append(
                            f"{coupling_name} 暂未启动（与燃料电池互锁）"
                        )
                    else:
                        start_blockers = []
                        if diesel_raise_margin_kw <= EPSILON:
                            start_blockers.append(
                                f"柴发负载率 {predicted_diesel_load_ratio * 100:.1f}%、需低于 "
                                f"{electrolyzer_diesel_limit_ratio * 100:.0f}%"
                            )
                        if (
                            electric_storage_soc
                            <= settings.electrolyzer_storage_soc_start_minimum + EPSILON
                        ):
                            start_blockers.append(
                                f"电储 SOC {electric_storage_soc * 100:.1f}%、未达 "
                                f"{settings.electrolyzer_storage_soc_start_minimum * 100:.0f}% 启机线"
                            )
                        if (
                            hydrogen_storage_soc
                            >= electrolyzer_h2_raise_limit - EPSILON
                        ):
                            start_blockers.append(
                                f"氢储 SOC {hydrogen_storage_soc * 100:.1f}%、需低于 "
                                f"{electrolyzer_h2_raise_limit * 100:.0f}%"
                            )
                        diagnostics["warnings"].append(
                            f"{coupling_name} 暂未启动（"
                            f"{'，'.join(start_blockers) or '未满足启机条件'}）"
                        )
                    if maintain_stopped_snapshot:
                        device_action = "hydrogen_stopped_hold"
                        device_action_reason = "start_conditions_not_met"
                    else:
                        decision_trace.update(
                            {
                                "action": "hold",
                                "controlReason": "start_conditions_not_met",
                                "blockers": start_blockers,
                            }
                        )
                        diagnostics["decisionTraces"].append(decision_trace)
                        continue
                else:
                    required_start_delta_kw = start_threshold_kw
                    # The diesel limit is an entry condition, not a post-start target.
                    # Once all entry predicates hold, start directly at the complete
                    # hysteresis threshold even if that raises predicted diesel above
                    # the configured entry limit.
                    device_action_reason = "entry_conditions_met_direct_start"
                    requested_delta_kw = required_start_delta_kw
            else:
                if fuel_cell_decision is None:
                    continue
                requested_delta_kw = fuel_cell_decision.requested_delta_kw
                required_start_delta_kw = fuel_cell_decision.required_start_delta_kw
                device_action_reason = fuel_cell_decision.reason
                if fuel_cell_decision.action in {"decrease", "stop"}:
                    device_action = "fuel_cell_reduce"
                if fuel_cell_decision.reason == "start_margin_insufficient":
                    diagnostics["warnings"].append(
                        f"氢能设备{coupling_name}需要一次达到最小运行功率+步长"
                        f"{start_threshold_kw:.3f} kW，当前柴发调节裕度或设备功率上限不足，已保持停机"
                    )
                    decision_trace.update(
                        {
                            "action": "hold",
                            "controlReason": fuel_cell_decision.reason,
                            "blockers": ["柴发调节裕度或设备功率上限不足以一次达到最小运行功率+步长"],
                        }
                    )
                    diagnostics["decisionTraces"].append(decision_trace)
                    continue
                if fuel_cell_decision.action == "hold":
                    if maintain_stopped_snapshot:
                        device_action = "hydrogen_stopped_hold"
                        device_action_reason = fuel_cell_decision.reason
                    elif current_power > EPSILON:
                        device_action = "hold"
                        device_action_reason = fuel_cell_decision.reason or "hold_region"
                    else:
                        decision_trace.update(
                            {
                                "action": "hold",
                                "controlReason": fuel_cell_decision.reason,
                            }
                        )
                        diagnostics["decisionTraces"].append(decision_trace)
                        continue

            proposed_power = max(0.0, current_power + requested_delta_kw)
            if (
                not pressure_blocked
                and current_power > EPSILON
                and requested_delta_kw < -EPSILON
                and proposed_power < stop_threshold_kw - EPSILON
            ):
                requested_delta_kw = -current_power
                proposed_power = 0.0
                power_hysteresis_stop = True
                device_action = "power_hysteresis_stop"
            if (
                abs(requested_delta_kw) <= EPSILON
                and not pressure_blocked
                and not maintain_stopped_snapshot
            ):
                if current_power <= EPSILON:
                    decision_trace.update(
                        {
                            "action": "hold",
                            "controlReason": device_action_reason or "hold_region",
                        }
                    )
                    diagnostics["decisionTraces"].append(decision_trace)
                    continue
                device_action = "hold"
                device_action_reason = device_action_reason or "hold_region"
            active_set_type = str(
                active_binding.get("target_set_type", active_binding.get("set_type", ""))
            )
            current_active_value = (
                current_power
                if active_set_type == "p_set"
                else current_power * float(coefficient)
                if is_electrolyzer
                else current_power / float(coefficient)
            )
            active_type = str(active_binding.get("target_dev_type", ""))
            active_name = str(active_binding.get("target_dev_name", ""))
            active_device = devices.get((active_type, active_name))
            if (
                not active_device
                or _preferred_set_type(
                    snapshot,
                    active_device,
                    (active_set_type,),
                )
                != active_set_type
            ):
                decision_trace.update(
                    {
                        "action": "blocked",
                        "controlReason": "active_setpoint_unavailable",
                        "blockers": ["活动遥调点不可用"],
                    }
                )
                diagnostics["decisionTraces"].append(decision_trace)
                continue
            topology_island_id = _optimization_island_id_for_components(
                optimization_result,
                electric_component_id,
                dc_group_id,
            )
            accepted_delta_kw = requested_delta_kw
            adjustment_requested = abs(requested_delta_kw) > EPSILON
            atomic_hold_reason = ""
            atomic_hold_blockers: List[str] = []
            converter_rows: List[MutableMapping[str, Any]] = []
            converter_request_kw = 0.0
            if electric_side == "DC" and abs(accepted_delta_kw) > EPSILON:
                converter_rows = [
                    row
                    for row in coordinated_converter_rows
                    if _is_grid_converter_row(row)
                    and row.get("online")
                    and row.get("commandable") is not False
                    and str(row.get("dcTransferGroupId", "")) == dc_group_id
                ]
                if not dc_group_id or not converter_rows:
                    dcac_detail = _dcac_unavailable_detail(
                        snapshot,
                        resource_topology,
                        command_rows,
                        dc_group_id,
                    )
                    diagnostics["warnings"].append(
                        f"氢能设备{coupling_name}{dcac_detail}，已取消本设备氢能增量"
                    )
                    accepted_delta_kw = 0.0
                    atomic_hold_reason = "dcac_control_margin_unavailable"
                    atomic_hold_blockers = [dcac_detail]
                else:
                    converter_request_kw = (
                        -accepted_delta_kw if is_electrolyzer else accepted_delta_kw
                    )
                    converter_probe = [copy.deepcopy(row) for row in converter_rows]
                    converter_delivered_kw = _allocate_converter_ac_injection_delta(
                        converter_probe,
                        converter_request_kw,
                        step_ratio=settings.converter_step_ratio,
                    )
                    accepted_magnitude = min(
                        abs(accepted_delta_kw),
                        abs(converter_delivered_kw),
                    )
                    accepted_delta_kw = math.copysign(
                        accepted_magnitude,
                        accepted_delta_kw,
                    )
                    converter_request_kw = math.copysign(
                        accepted_magnitude,
                        converter_request_kw,
                    )

            diesel_delta_kw = (
                accepted_delta_kw if is_electrolyzer else -accepted_delta_kw
            )
            if diesel_command_rows and abs(diesel_delta_kw) > EPSILON:
                diesel_margin_kw = _row_command_delta_margin(
                    diesel_command_rows,
                    increase=diesel_delta_kw > 0.0,
                )
                accepted_magnitude = min(abs(accepted_delta_kw), diesel_margin_kw)
                accepted_delta_kw = math.copysign(
                    accepted_magnitude,
                    accepted_delta_kw,
                )
                diesel_delta_kw = math.copysign(
                    accepted_magnitude,
                    diesel_delta_kw,
                )
                if electric_side == "DC":
                    converter_request_kw = math.copysign(
                        accepted_magnitude,
                        converter_request_kw,
                    )
            if adjustment_requested and abs(accepted_delta_kw) <= EPSILON and not (
                (pressure_blocked and current_power <= EPSILON)
                or maintain_stopped_snapshot
            ):
                if not atomic_hold_reason:
                    diagnostics["warnings"].append(
                        f"氢能设备{coupling_name}的氢端、DCAC步长或平衡设备无共同调节裕度，已原子保持"
                    )
                    atomic_hold_reason = "atomic_margin_unavailable"
                    atomic_hold_blockers = ["氢端、DCAC或平衡设备无共同调节裕度"]
                device_action = "blocked"
                device_action_reason = atomic_hold_reason
                decision_trace["blockers"] = atomic_hold_blockers

            if (
                required_start_delta_kw is not None
                and accepted_delta_kw < required_start_delta_kw - EPSILON
            ):
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}当前氢端、DCAC或平衡设备共同裕度不足以一次达到"
                    f"最小运行功率+步长{start_threshold_kw:.3f} kW，已保持停机"
                )
                decision_trace.update(
                    {
                        "action": "hold",
                        "controlReason": "atomic_start_margin_insufficient",
                        "blockers": ["氢端、DCAC或平衡设备共同裕度不足以一次达到最小运行功率+步长"],
                    }
                )
                diagnostics["decisionTraces"].append(decision_trace)
                continue
            target_power = max(0.0, current_power + accepted_delta_kw)
            requested_target_power = target_power
            if power_hysteresis_stop:
                # A hysteresis stop is a device state transition: issue the
                # stop remote control and zero setpoint directly, even when
                # DCAC or balance-device headroom cannot pair the full delta.
                target_power = 0.0
            elif target_power > EPSILON:
                if target_power > allowed_power + EPSILON:
                    target_power = allowed_power
                elif target_power < physical_minimum_power - EPSILON:
                    if accepted_delta_kw > EPSILON:
                        target_power = physical_minimum_power
                    elif target_power < stop_threshold_kw - EPSILON:
                        target_power = 0.0
            if abs(target_power - requested_target_power) > EPSILON:
                setpoint_delta_kw = target_power - current_power
                unpaired_delta_kw = setpoint_delta_kw - accepted_delta_kw
                if power_hysteresis_stop:
                    diagnostics["warnings"].append(
                        f"{coupling_name} 功率低于停机线（{stop_threshold_kw:.1f} kW），已下发停机"
                        + (
                            f"（电侧余量 {unpaired_delta_kw:.1f} kW 由平衡设备承接）"
                            if abs(unpaired_delta_kw) > 0.05
                            else ""
                        )
                    )
                    device_action = "power_hysteresis_stop"
                    device_action_reason = "below_stop_threshold"
                else:
                    diagnostics["warnings"].append(
                        f"{coupling_name} 目标 {requested_target_power:.1f} kW 越界，已限幅至 {target_power:.1f} kW"
                        + (
                            f"（电侧余量 {unpaired_delta_kw:.1f} kW 由平衡设备承接）"
                            if abs(unpaired_delta_kw) > 0.05
                            else ""
                        )
                    )
                    device_action = (
                        "electrolyzer_boundary_correction"
                        if is_electrolyzer
                        else "fuel_cell_boundary_correction"
                    )
                    device_action_reason = "target_boundary_clamped_and_dispatched"
                decision_trace["boundaryRequestedPowerKw"] = requested_target_power
                decision_trace["boundaryClampedPowerKw"] = target_power
                decision_trace["unpairedElectricalDeltaKw"] = unpaired_delta_kw
                accepted_delta_kw = setpoint_delta_kw
            target_flow = (
                target_power * float(coefficient)
                if is_electrolyzer
                else target_power / float(coefficient)
            )
            set_value = target_power if active_set_type == "p_set" else target_flow
            run_stat_target: Optional[int] = None
            if target_power > EPSILON and not coupling_online:
                run_stat_target = 1
            elif target_power <= EPSILON and coupling_online:
                run_stat_target = 0
            if run_stat_target is not None:
                coupling_key = (coupling_type, coupling_name)
                if coupling_key not in run_status_control_keys:
                    diagnostics["warnings"].append(
                        f"氢能设备{coupling_name}需要"
                        f"{'启机' if run_stat_target else '停机'}，但模型未定义明确的RunStat遥控点，"
                        "已按 fail closed 取消本设备本轮功率与联动修正"
                    )
                    decision_trace.update(
                        {
                            "action": "blocked",
                            "controlReason": "run_status_control_unavailable",
                            "blockers": ["模型未定义明确的RunStat遥控点"],
                        }
                    )
                    diagnostics["decisionTraces"].append(decision_trace)
                    continue
                command_rows.append(
                    {
                        "category": "氢能",
                        "dev_type": coupling_type,
                        "model_block": coupling_type,
                        "dev_name": coupling_name,
                        "online": True,
                        "commandable": True,
                        "strategyCommand": True,
                        "dispatchEnabled": bool(apply_electrical_corrections),
                        "commandKind": "run_status",
                        "command_type": "run_stat",
                        "run_stat": run_stat_target,
                        "currentKw": 1.0 if _is_online(coupling_device, measurements) else 0.0,
                        "commandKw": float(run_stat_target),
                        "targetKw": float(run_stat_target),
                        "connectionStatusLabel": (
                            "启机遥控" if run_stat_target else "停机遥控"
                        ),
                        "statusLabel": "综合新能源策略",
                    }
                )
            active_key = (active_type, active_name, active_set_type)
            active_row = current_command_by_key.get(active_key)
            if active_row is None:
                active_row = {
                    "category": "氢能",
                    "dev_type": active_type,
                    "model_block": active_type,
                    "dev_name": active_name,
                    "online": True,
                    "commandable": True,
                    "strategyCommand": True,
                    "dispatchEnabled": bool(apply_electrical_corrections),
                    "set_type": active_set_type,
                    "currentKw": current_active_value,
                    "commandKw": set_value,
                    "statusLabel": "综合新能源策略",
                }
                command_rows.append(active_row)
                current_command_by_key[active_key] = active_row
            else:
                active_row["commandKw"] = set_value
                active_row["strategyCommand"] = True
                active_row["dispatchEnabled"] = bool(
                    apply_electrical_corrections
                )
            if (
                apply_electrical_corrections
                and electric_side == "DC"
                and abs(converter_request_kw) > EPSILON
            ):
                converter_correction += _allocate_converter_ac_injection_delta(
                    converter_rows,
                    converter_request_kw,
                    step_ratio=settings.converter_step_ratio,
                )
            if (
                apply_electrical_corrections
                and diesel_command_rows
                and abs(diesel_delta_kw) > EPSILON
            ):
                balance_correction += _allocate_row_command_delta(
                    diesel_command_rows,
                    diesel_delta_kw,
                )
            planned.append(
                {
                    "mode": "electrolyzer" if is_electrolyzer else "fuel_cell",
                    "action": (
                        f"{device_action}_pressure_safety_stop"
                        if safety_stop
                        else f"{device_action}_pressure_safe_zero"
                        if pressure_blocked
                        else device_action
                    ),
                    "couplingType": coupling_type,
                    "couplingName": coupling_name,
                    "activeDevType": active_type,
                    "activeDevName": active_name,
                    "activeSetType": active_set_type,
                    "setValue": set_value,
                    "electricSide": electric_side,
                    "electricBusbarType": power_connection.busbar_type,
                    "electricBusbarName": power_connection.busbar_name,
                    "electricConverterPath": list(power_connection.converter_path),
                    "currentElectricPowerKw": current_power,
                    "electricPowerKw": target_power,
                    "targetElectricPowerKw": target_power,
                    "electricDeltaKw": accepted_delta_kw,
                    "equivalentFlow": target_flow,
                    "dcTransferGroupId": dc_group_id,
                    "electricComponentId": electric_component_id,
                    "topologyIslandId": topology_island_id,
                    "hydrogenIslandId": hydrogen_island_id,
                    "dieselLoadRatioBefore": predicted_diesel_load_ratio,
                    "electricStorageSocAverage": electric_storage_soc,
                    "hydrogenStorageSocAverage": hydrogen_storage_soc,
                    "controlReason": device_action_reason,
                    "stepLimitKw": step_kw,
                    "minimumRunningPowerKw": minimum_running_power,
                    "physicalMinimumPowerKw": physical_minimum_power,
                    "configuredMinimumPowerKw": configured_minimum,
                    "configuredMaximumPowerKw": configured_maximum,
                    "ratedPowerKw": rated_power_kw,
                    "powerDeadbandKw": power_deadband_kw,
                    "startThresholdKw": start_threshold_kw,
                    "stopThresholdKw": stop_threshold_kw,
                    "pressureSafetyStop": pressure_blocked,
                    "powerHysteresisStop": power_hysteresis_stop,
                }
            )
            diagnostics["decisionTraces"].append(dict(planned[-1]))
            if accepted_delta_kw > EPSILON and not hydrogen_mode_lock:
                hydrogen_mode_lock = (
                    "electrolyzer" if is_electrolyzer else "fuel_cell"
                )
                diagnostics["interlockMode"] = hydrogen_mode_lock
                diagnostics["interlockActive"] = True
            predicted_diesel_kw += diesel_delta_kw
    if apply_electrical_corrections:
        _publish_final_acdc_coordination(
            command_rows,
            coordinated_converter_rows,
        )
    diagnostics.update(
        {
            "action": (
                "pressure_safety_stop"
                if planned and any(row.get("pressureSafetyStop") for row in planned)
                else "power_hysteresis_stop"
                if planned and any(row.get("powerHysteresisStop") for row in planned)
                else str(planned[0].get("action", "hold"))
                if planned
                else "blocked"
                if diagnostics["warnings"]
                else "hold"
            ),
            "electricPowerAdjustmentKw": sum(
                float(row["electricDeltaKw"]) for row in planned
            ),
            "targetElectricPowerKw": sum(
                float(row["electricPowerKw"]) for row in planned
            ),
            "targetEquivalentFlow": sum(
                float(row["equivalentFlow"]) for row in planned
            ),
            "commands": planned,
            "topologyIslandPlans": _topology_island_hydrogen_plans(planned),
            "converterCorrectionKw": converter_correction,
            "balanceCorrectionKw": balance_correction,
            "predictedDieselAfterKw": predicted_diesel_kw,
            "predictedDieselLoadRatioAfter": predicted_diesel_kw
            / diesel_capacity_kw,
            "predictedDieselAverageAfterKw": predicted_diesel_kw
            / diesel_unit_count,
        }
    )
    diagnostics.update(
        _hydrogen_operating_metrics(
            snapshot,
            measurements,
            pressure_states,
            planned,
        )
    )
    if not planned and not diagnostics["decisionTraces"]:
        diagnostics["warnings"].append(
            "氢能触发条件已满足，但耦合设备、遥调点、实时量测或设备边界不完整，未生成氢能策略"
        )
    return diagnostics
