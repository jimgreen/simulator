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
        return island_id, tanks, "所属氢网分岛部分或全部储氢罐压力或上下限无效"
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

def _row_electrical_island_id(
    row: Mapping[str, Any],
    optimization_result: Optional[RenewableDispatchOptimizationResult],
) -> str:
    """解析电储/柴发设备行所属的电气拓扑岛标识。"""
    grid_component_id = str(row.get("gridComponentId", "") or "").strip()
    dc_group_id = str(row.get("dcTransferGroupId", "") or "").strip()
    if not grid_component_id and not dc_group_id:
        return ""
    return _optimization_island_id_for_components(
        optimization_result,
        grid_component_id,
        dc_group_id,
    )


def _island_electric_storage_soc(
    storage_rows: Sequence[Mapping[str, Any]],
    topology_island_id: str,
    optimization_result: Optional[RenewableDispatchOptimizationResult],
    warned_keys: set[Tuple[str, str]],
    warnings_out: List[str],
) -> Optional[float]:
    """按电气拓扑岛聚合在线电储平均 SOC，个别测点无效时仅剔除坏数并告警。"""
    online_storage = [row for row in storage_rows if row.get("online")]
    if not online_storage:
        return None
    has_topology_tags = any(
        bool(_row_electrical_island_id(row, optimization_result))
        for row in online_storage
    )
    if (
        has_topology_tags
        and topology_island_id
        and topology_island_id != "UNRESOLVED"
    ):
        scoped_storage = [
            row
            for row in online_storage
            if _row_electrical_island_id(row, optimization_result) == topology_island_id
        ]
    else:
        scoped_storage = online_storage
    if not scoped_storage:
        return None

    known_soc: List[float] = []
    for row in scoped_storage:
        soc_val = _number(row.get("soc"))
        if row.get("socKnown") and soc_val is not None and math.isfinite(float(soc_val)):
            known_soc.append(float(soc_val))
        else:
            dev_key = (
                str(row.get("dev_type", "")),
                str(row.get("dev_name", "")),
            )
            if dev_key not in warned_keys:
                warned_keys.add(dev_key)
                warnings_out.append(
                    f"电储{dev_key[1] or dev_key[0]} SOC量测无效，已在同岛氢能SOC均值计算中剔除"
                )
    if not known_soc:
        return None
    return sum(known_soc) / len(known_soc)


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
    runtime_memory: Optional[MutableMapping[str, Any]] = None,
    sim_time_seconds: Optional[float] = None,
    zero_diesel_grid_forming: bool = False,
    defer_dwell_commit: bool = False,
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
    if (not diesel_input_valid or diesel_capacity_kw <= EPSILON) and not zero_diesel_grid_forming:
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

    # 两个氢能转换方向在同一电气岛或同一氢网分岛内均物理互斥：
    # 按电气拓扑岛与氢网分岛双维度扫描在线运行态，杜绝跨电岛同氢岛互充，也避免跨孤岛互相误锁。
    active_hydrogen_modes: set[str] = set()
    active_hydrogen_modes_by_island: Dict[str, set[str]] = {}
    active_hydrogen_modes_by_hydro_island: Dict[str, set[str]] = {}
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

            # 运行态门槛与最小运行功率对齐，低于最小运行功率的残余量测视作停机态
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
                    flow_power_min = max(0.0, flow_min) / coefficient
                else:
                    configured_minimum = (
                        float(settings.fuel_cell_power_min_kw)
                        if settings.fuel_cell_power_min_kw is not None
                        else settings.fuel_cell_power_min_ratio * rated_power_kw
                    )
                    flow_power_min = max(0.0, flow_min) * coefficient
                physical_minimum_power = max(0.0, power_min, flow_power_min)
                minimum_running_power = max(
                    physical_minimum_power,
                    configured_minimum,
                )
                running_threshold_kw = max(0.0, minimum_running_power)
            elif rated_power_kw > EPSILON:
                # 缺少完整 p_min/flow_min 边界时用保守 5% 额定门槛，避免 1e-9 噪声残余误触发同岛互锁。
                running_threshold_kw = max(EPSILON, 0.05 * rated_power_kw)
            else:
                running_threshold_kw = math.inf
            running = bool(
                current_power > EPSILON
                and math.isfinite(running_threshold_kw)
                and (
                    running_threshold_kw <= EPSILON
                    or current_power >= running_threshold_kw - EPSILON
                )
            )
            if running:
                active_hydrogen_modes.add(mode)
                conn = hydrogen_electric_connections.get((power_type, power_name))
                conn_island_id = (
                    _optimization_island_id_for_components(
                        optimization_result,
                        conn.grid_component_id,
                        conn.dc_transfer_group_id if conn.connection_side == "DC" else "",
                    )
                    if conn is not None and conn.grid_component_id
                    else ""
                )
                active_hydrogen_modes_by_island.setdefault(conn_island_id, set()).add(mode)
                hydro_isl_id = str(
                    resource_topology.hydrogen_device_island_ids.get((flow_type, flow_name), "")
                )
                if hydro_isl_id:
                    active_hydrogen_modes_by_hydro_island.setdefault(hydro_isl_id, set()).add(mode)

    hydrogen_mode_lock = (
        next(iter(active_hydrogen_modes))
        if len(active_hydrogen_modes) == 1
        else "conflict"
        if len(active_hydrogen_modes) > 1
        else ""
    )
    diagnostics["interlockMode"] = hydrogen_mode_lock or "idle"
    diagnostics["interlockActive"] = bool(hydrogen_mode_lock)

    # 按电气岛预聚合柴发实时目标、额定容量与可控列表（旧调用方无拓扑标签时自动退回全站单岛）
    all_diesel_command_rows = [
        row
        for row in command_rows
        if row.get("category") == "柴油发电"
        and row.get("online")
        and row.get("commandable") is not False
    ]
    all_online_diesel_rows = [
        row
        for row in command_rows
        if row.get("category") == "柴油发电" and row.get("online")
    ]
    diesel_has_topology_tags = any(
        bool(_row_electrical_island_id(row, optimization_result))
        for row in all_online_diesel_rows
    )
    diesel_rows_by_island: Dict[str, List[MutableMapping[str, Any]]] = {}
    island_predicted_diesel_kw: Dict[str, float] = {}
    island_diesel_capacity_kw: Dict[str, float] = {}
    island_diesel_unit_count: Dict[str, int] = {}
    if diesel_has_topology_tags:
        for row in all_online_diesel_rows:
            d_island = _row_electrical_island_id(row, optimization_result)
            if not d_island:
                continue
            row_cmd_kw = _number(row.get("commandKw"))
            if row_cmd_kw is None:
                row_cmd_kw = _number(row.get("currentKw"), 0.0) or 0.0
            row_cap_kw = _number(row.get("ratedCapacityKw"))
            if row_cap_kw is None:
                row_cap_kw = _number(row.get("capacityKw"), 0.0) or 0.0
            island_predicted_diesel_kw[d_island] = (
                island_predicted_diesel_kw.get(d_island, 0.0) + float(row_cmd_kw)
            )
            island_diesel_capacity_kw[d_island] = (
                island_diesel_capacity_kw.get(d_island, 0.0) + max(0.0, float(row_cap_kw))
            )
            island_diesel_unit_count[d_island] = (
                island_diesel_unit_count.get(d_island, 0) + 1
            )
            if row.get("commandable") is not False:
                diesel_rows_by_island.setdefault(d_island, []).append(row)

    warned_invalid_storage_soc: set[Tuple[str, str]] = set()
    # 按电气岛预计算互锁冲突裁决（含零柴发构网/无柴发岛安全分支，严禁 0.0 / 0.0 崩溃）
    island_mode_lock: Dict[str, str] = {}
    island_conflict_stop: Dict[str, str] = {}
    for isl_id, modes_set in active_hydrogen_modes_by_island.items():
        if len(modes_set) == 1:
            island_mode_lock[isl_id] = next(iter(modes_set))
        elif len(modes_set) > 1:
            island_mode_lock[isl_id] = "conflict"
            isl_cap = (
                island_diesel_capacity_kw.get(isl_id, 0.0)
                if diesel_has_topology_tags and isl_id
                else diesel_capacity_kw
            )
            isl_cur = (
                island_predicted_diesel_kw.get(isl_id, 0.0)
                if diesel_has_topology_tags and isl_id
                else diesel_current_kw
            )
            if isl_cap > EPSILON:
                isl_ratio = isl_cur / isl_cap
                stop_mode = (
                    "electrolyzer"
                    if isl_ratio > fuel_cell_diesel_limit_ratio + EPSILON
                    else "fuel_cell"
                )
                keep_mode = "fuel_cell" if stop_mode == "electrolyzer" else "electrolyzer"
                island_conflict_stop[isl_id] = stop_mode
                diagnostics["interlockStopMode"] = stop_mode
                diagnostics["interlockKeepMode"] = keep_mode
                diagnostics["warnings"].append(
                    f"电气岛{isl_id or '主网'}实时量测显示电制氢和燃料电池同时运行，"
                    f"柴发负载率{isl_ratio * 100:.3f}%"
                    f"{'高于' if stop_mode == 'electrolyzer' else '未高于'}"
                    f"燃料电池柴发负载率限值{fuel_cell_diesel_limit_ratio * 100:.3f}%，"
                    f"本轮停止{'电制氢' if stop_mode == 'electrolyzer' else '燃料电池'}，"
                    f"保留{'燃料电池' if keep_mode == 'fuel_cell' else '电制氢'}运行"
                )
            else:
                # 零柴发构网或该孤岛无在线柴发：按本岛电储 SOC 裁决，无有效 SOC 时保守双停。
                isl_soc = _island_electric_storage_soc(
                    storage_rows,
                    isl_id,
                    optimization_result,
                    warned_invalid_storage_soc,
                    diagnostics["warnings"],
                )
                if isl_soc is None:
                    stop_mode = "both"
                    keep_mode = "none"
                elif isl_soc >= settings.electrolyzer_storage_soc_start_minimum - EPSILON:
                    stop_mode = "fuel_cell"
                    keep_mode = "electrolyzer"
                elif isl_soc <= settings.fuel_cell_storage_soc_limit + EPSILON:
                    stop_mode = "electrolyzer"
                    keep_mode = "fuel_cell"
                else:
                    stop_mode = "both"
                    keep_mode = "none"
                island_conflict_stop[isl_id] = stop_mode
                diagnostics["interlockStopMode"] = stop_mode
                diagnostics["interlockKeepMode"] = keep_mode
                diagnostics["warnings"].append(
                    f"无柴发电气岛{isl_id or '主网'}实时量测显示电制氢和燃料电池同时运行，"
                    f"按本岛电储SOC（{f'{isl_soc * 100:.1f}%' if isl_soc is not None else '未知'}）裁决："
                    f"本轮停止{'电制氢与燃料电池' if stop_mode == 'both' else ('电制氢' if stop_mode == 'electrolyzer' else '燃料电池')}"
                )

    hydro_island_mode_lock: Dict[str, str] = {}
    hydro_island_conflict_stop: Dict[str, str] = {}
    for h_isl_id, modes_set in active_hydrogen_modes_by_hydro_island.items():
        if len(modes_set) == 1:
            hydro_island_mode_lock[h_isl_id] = next(iter(modes_set))
        elif len(modes_set) > 1:
            hydro_island_mode_lock[h_isl_id] = "conflict"
            hydro_island_conflict_stop[h_isl_id] = "both"
            diagnostics["warnings"].append(
                f"氢网分岛{h_isl_id}同时存在运行中的电制氢与燃料电池，触发氢岛级防互充停机保护"
            )

    global_electric_storage_soc = _island_electric_storage_soc(
        storage_rows,
        "",
        optimization_result,
        warned_invalid_storage_soc,
        diagnostics["warnings"],
    )
    diagnostics["electricStorageSocAverage"] = global_electric_storage_soc
    hydrogen_dwell_memory: Optional[MutableMapping[str, Any]] = None
    if runtime_memory is not None:
        raw_dwell = runtime_memory.get("hydrogen_dwell")
        if not isinstance(raw_dwell, dict):
            raw_dwell = {}
            if not defer_dwell_commit and apply_electrical_corrections:
                runtime_memory["hydrogen_dwell"] = raw_dwell
        if defer_dwell_commit or not apply_electrical_corrections:
            hydrogen_dwell_memory = copy.deepcopy(raw_dwell)
        else:
            hydrogen_dwell_memory = raw_dwell
    coupling_types = ("AcE2Hydro", "DcE2Hydro", "Hydro2AcE", "Hydro2DcE")
    planned: List[Dict[str, Any]] = []
    converter_correction = 0.0
    balance_correction = 0.0
    predicted_diesel_kw = float(diesel_current_kw)
    control_horizon_hours = max(
        STORAGE_MINIMUM_CONTROL_HORIZON_HOURS,
        _storage_control_horizon_minutes(snapshot, settings) / 60.0,
    )
    # 跟踪同一氢网分岛在本拍内已分配的累计充/放氢流量（Nm³/h），防止多台氢能机组同罐叠加冲穿罐容。
    island_planned_charge_flow_nm3h: Dict[str, float] = {}
    island_planned_discharge_flow_nm3h: Dict[str, float] = {}
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
            # 融合运行态控制模式覆盖（如在线在 P / FLOW 模式间切换）
            runtime_coupling_mode = str(
                _runtime_mode(snapshot, coupling_device)
                or coupling_device.get("mode", "")
                or ""
            ).strip().upper()
            if runtime_coupling_mode in {"FLOW", "F"}:
                active_binding = flow_binding
            elif runtime_coupling_mode in {"P", "POWER"}:
                active_binding = power_binding
            power_type = str(power_binding.get("target_dev_type", ""))
            power_name = str(power_binding.get("target_dev_name", ""))
            flow_type = str(flow_binding.get("target_dev_type", ""))
            flow_name = str(flow_binding.get("target_dev_name", ""))
            flow_key = (flow_type, flow_name)
            # 业务硬边界前置：耦合设备已停机时模拟台会级联禁用端点，直接输出待人工开机状态而不刷无效氢岛报错。
            if not coupling_online:
                if hydrogen_dwell_memory is not None:
                    dwell_key_off = f"{coupling_type}:{coupling_name}"
                    off_entry = hydrogen_dwell_memory.get(dwell_key_off)
                    if isinstance(off_entry, dict):
                        off_entry["couplingOnline"] = False
                diagnostics["decisionTraces"].append(
                    {
                        "mode": "electrolyzer" if is_electrolyzer else "fuel_cell",
                        "couplingType": coupling_type,
                        "couplingName": coupling_name,
                        "action": "hold",
                        "currentElectricPowerKw": 0.0,
                        "targetElectricPowerKw": 0.0,
                        "electricDeltaKw": 0.0,
                        "controlReason": "awaiting_manual_start",
                        "blockers": ["当前处于停机状态，自动策略禁止开机，等待人工下令开机"],
                    }
                )
                continue
            hydrogen_island_id, island_tanks, topology_error = (
                _hydrogen_island_pressure_state(
                    resource_topology,
                    pressure_by_island,
                    flow_key,
                )
            )
            partial_pressure_invalid = bool(topology_error and island_tanks)
            if topology_error and not island_tanks:
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}{topology_error}，本设备已按 fail closed 禁止自动调节"
                )
                continue
            pressure_blocked = bool(
                any(
                    row.get("pressureKnown")
                    and row.get("pressureLimitsConsistent", True)
                    and row.get("highGuard") is not None
                    and float(row["pressure"]) >= float(row["highGuard"])
                    for row in island_tanks
                )
                if is_electrolyzer
                else any(
                    row.get("pressureKnown")
                    and row.get("pressureLimitsConsistent", True)
                    and row.get("lowGuard") is not None
                    and float(row["pressure"]) < float(row["lowGuard"])
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
            # 氢储罐 SOC 硬安全停机：独立于气压上限，并强制保留至少 2% 安全缓冲（上限 <= 0.98、下限 >= 0.02）。
            h2_deadband_ratio = max(0.0, float(settings.hydrogen_pressure_deadband_ratio))
            h2_soc_hard_high = min(
                0.98,
                max(
                    float(settings.electrolyzer_hydrogen_storage_soc_stop_minimum) + h2_deadband_ratio,
                    0.95,
                ),
            )
            h2_soc_hard_low = max(
                0.02,
                min(
                    float(settings.fuel_cell_hydrogen_storage_soc_lower_limit) - h2_deadband_ratio,
                    0.10,
                ),
            )
            soc_safety_blocked = bool(
                (
                    any(val >= h2_soc_hard_high - EPSILON for val in island_soc_values)
                    or (hydrogen_storage_soc is not None and hydrogen_storage_soc >= h2_soc_hard_high - EPSILON)
                )
                if is_electrolyzer
                else (
                    any(val <= h2_soc_hard_low + EPSILON for val in island_soc_values)
                    or (hydrogen_storage_soc is not None and hydrogen_storage_soc <= h2_soc_hard_low + EPSILON)
                )
            )
            # 核算同氢岛在线储氢罐在本拍 control_horizon_hours 内的保守安全余量（防多罐求和掩盖单罐短板冲穿）。
            tank_horizon_max_flow_nm3h: Optional[float] = None
            tank_qty_entries = [
                (
                    _number(row.get("ratedCapacityNm3")),
                    _number(row.get("gasQuantityNm3")),
                )
                for row in online_island_tanks
            ]
            if tank_qty_entries and all(
                cap is not None and cap > EPSILON and qty is not None and math.isfinite(qty)
                for cap, qty in tank_qty_entries
            ):
                if is_electrolyzer:
                    per_tank_headrooms = [
                        max(0.0, float(cap) * h2_soc_hard_high - float(qty))
                        for cap, qty in tank_qty_entries
                        if cap is not None and qty is not None
                    ]
                    conservative_headroom_nm3 = min(
                        sum(per_tank_headrooms),
                        min(per_tank_headrooms) * len(per_tank_headrooms),
                    )
                    used_nm3 = island_planned_charge_flow_nm3h.get(hydrogen_island_id, 0.0) * control_horizon_hours
                    remaining_nm3 = max(0.0, conservative_headroom_nm3 - used_nm3)
                    tank_horizon_max_flow_nm3h = remaining_nm3 / control_horizon_hours
                else:
                    per_tank_available = [
                        max(0.0, float(qty) - float(cap) * h2_soc_hard_low)
                        for cap, qty in tank_qty_entries
                        if cap is not None and qty is not None
                    ]
                    conservative_available_nm3 = min(
                        sum(per_tank_available),
                        min(per_tank_available) * len(per_tank_available),
                    )
                    used_nm3 = island_planned_discharge_flow_nm3h.get(hydrogen_island_id, 0.0) * control_horizon_hours
                    remaining_nm3 = max(0.0, conservative_available_nm3 - used_nm3)
                    tank_horizon_max_flow_nm3h = remaining_nm3 / control_horizon_hours
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
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}缺少有效的 p_min/p_max 或 flow_min/flow_max 边界，已按 fail closed 禁止自动调节"
                )
                diagnostics["decisionTraces"].append(
                    {
                        "mode": "electrolyzer" if is_electrolyzer else "fuel_cell",
                        "couplingType": coupling_type,
                        "couplingName": coupling_name,
                        "action": "blocked",
                        "controlReason": "missing_power_or_flow_bounds",
                        "blockers": ["缺少有效的 p_min/p_max 或 flow_min/flow_max 边界"],
                    }
                )
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
            tank_horizon_blocked = False
            if tank_horizon_max_flow_nm3h is not None:
                tank_horizon_power_max = (
                    tank_horizon_max_flow_nm3h / float(coefficient)
                    if is_electrolyzer
                    else tank_horizon_max_flow_nm3h * float(coefficient)
                )
                if tank_horizon_power_max < minimum_running_power - EPSILON:
                    tank_horizon_blocked = True
                else:
                    allowed_power = min(allowed_power, tank_horizon_power_max)
            hard_safety_blocked = bool(pressure_blocked or soc_safety_blocked or tank_horizon_blocked)
            if is_electrolyzer:
                start_threshold_kw = min(allowed_power, minimum_running_power + power_deadband_kw)
            else:
                # Fuel-cell startup keeps its dedicated minimum-plus-step rule, capped by allowed_power.
                start_threshold_kw = min(allowed_power, minimum_running_power + step_kw)
            # 停机门槛锁定为最小允许运行功率，将启停回差完全置于最小功率之上，杜绝低载禁区。
            stop_threshold_kw = max(0.0, minimum_running_power)
            topology_island_id = _optimization_island_id_for_components(
                optimization_result,
                electric_component_id,
                dc_group_id,
            )
            # 按氢能电端所属电气拓扑岛独立聚合电储 SOC、柴发负载/容量与氢能互锁态
            electric_storage_soc = _island_electric_storage_soc(
                storage_rows,
                topology_island_id,
                optimization_result,
                warned_invalid_storage_soc,
                diagnostics["warnings"],
            )
            if (
                diesel_has_topology_tags
                and topology_island_id
                and topology_island_id != "UNRESOLVED"
            ):
                scoped_diesel_capacity_kw = island_diesel_capacity_kw.get(
                    topology_island_id, 0.0
                )
                scoped_predicted_diesel_kw = island_predicted_diesel_kw.get(
                    topology_island_id, 0.0
                )
                diesel_command_rows = diesel_rows_by_island.get(
                    topology_island_id, []
                )
                scoped_hydrogen_mode_lock = island_mode_lock.get(
                    topology_island_id, ""
                )
                scoped_conflict_stop_mode = island_conflict_stop.get(
                    topology_island_id, ""
                )
            else:
                scoped_diesel_capacity_kw = diesel_capacity_kw
                scoped_predicted_diesel_kw = predicted_diesel_kw
                diesel_command_rows = all_diesel_command_rows
                scoped_hydrogen_mode_lock = hydrogen_mode_lock
                scoped_conflict_stop_mode = next(
                    iter(island_conflict_stop.values()), ""
                )
            # 合并氢网分岛级互锁：即使电端分属不同电气岛，同氢岛也不允许电制氢与燃料电池同时互充。
            if hydrogen_island_id:
                h_lock = hydro_island_mode_lock.get(hydrogen_island_id, "")
                h_stop = hydro_island_conflict_stop.get(hydrogen_island_id, "")
                if h_lock == "conflict":
                    scoped_hydrogen_mode_lock = "conflict"
                    if not scoped_conflict_stop_mode:
                        scoped_conflict_stop_mode = h_stop or "both"
                elif h_lock and not scoped_hydrogen_mode_lock:
                    scoped_hydrogen_mode_lock = h_lock

            maintain_stopped_snapshot = not coupling_online
            predicted_diesel_load_ratio = (
                scoped_predicted_diesel_kw / scoped_diesel_capacity_kw
                if scoped_diesel_capacity_kw > EPSILON
                else 0.0
            )
            decision_trace: Dict[str, Any] = {
                "mode": "electrolyzer" if is_electrolyzer else "fuel_cell",
                "couplingType": coupling_type,
                "couplingName": coupling_name,
                "topologyIslandId": topology_island_id,
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
            if scoped_diesel_capacity_kw <= EPSILON and not zero_diesel_grid_forming:
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}所属电气岛（{topology_island_id}）无在线柴发容量，"
                    "已按 fail closed 禁止自动调节"
                )
                decision_trace.update(
                    {
                        "action": "blocked",
                        "controlReason": "island_diesel_unavailable",
                        "blockers": ["所属电气岛无在线柴发容量"],
                    }
                )
                diagnostics["decisionTraces"].append(decision_trace)
                continue
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
            safety_stop = hard_safety_blocked and current_power > EPSILON
            device_action = "electrolyzer" if is_electrolyzer else "fuel_cell"
            device_action_reason = ""
            requested_delta_kw = 0.0
            required_start_delta_kw: Optional[float] = None
            fuel_cell_decision = None
            if is_electrolyzer:
                if scoped_diesel_capacity_kw <= EPSILON and zero_diesel_grid_forming:
                    # 零柴发构网运行：电制氢仅由电储高 SOC 与氢储未满驱动，不额外受柴发裕度阻断
                    diesel_raise_margin_kw = max(allowed_power, start_threshold_kw)
                else:
                    diesel_raise_margin_kw = max(
                        0.0,
                        electrolyzer_diesel_limit_ratio * scoped_diesel_capacity_kw
                        - scoped_predicted_diesel_kw,
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
                    and scoped_hydrogen_mode_lock != "fuel_cell"
                    and scoped_conflict_stop_mode != "electrolyzer"
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
                        electric_storage_soc_deadband=(
                            settings.fuel_cell_storage_soc_deadband
                        ),
                    ),
                    FuelCellControlInputs(
                        current_power_kw=current_power,
                        maximum_power_kw=allowed_power,
                        minimum_power_kw=minimum_running_power,
                        start_threshold_kw=start_threshold_kw,
                        stop_threshold_kw=stop_threshold_kw,
                        diesel_power_kw=scoped_predicted_diesel_kw,
                        diesel_capacity_kw=scoped_diesel_capacity_kw,
                        electric_storage_soc_average=electric_storage_soc,
                        hydrogen_storage_soc_average=hydrogen_storage_soc,
                        allow_zero_diesel=bool(
                            zero_diesel_grid_forming and scoped_diesel_capacity_kw <= EPSILON
                        ),
                    ),
                )
                if (
                    (
                        scoped_hydrogen_mode_lock == "electrolyzer"
                        or scoped_conflict_stop_mode == "fuel_cell"
                    )
                    and fuel_cell_decision.action in {"start", "increase"}
                ):
                    diagnostics["warnings"].append(
                        f"氢能设备{coupling_name}受同岛电制氢运行互锁，已禁止燃料电池启动或升功率"
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
                scoped_hydrogen_mode_lock == "conflict"
                and (
                    scoped_conflict_stop_mode == "both"
                    or (is_electrolyzer and scoped_conflict_stop_mode == "electrolyzer")
                    or (not is_electrolyzer and scoped_conflict_stop_mode == "fuel_cell")
                )
            )
            # 若同氢岛仅部分罐压力失效且尚未触发硬安全停机/互锁停机，仅禁止常规升载/维持经济调节，不阻塞硬安全停机。
            if partial_pressure_invalid and not (hard_safety_blocked or conflict_stops_device):
                diagnostics["warnings"].append(
                    f"氢能设备{coupling_name}{topology_error}，未触发已知罐硬安全停机，已按 fail closed 保持当前状态"
                )
                decision_trace.update(
                    {
                        "action": "blocked",
                        "controlReason": "partial_tank_pressure_invalid",
                        "blockers": [topology_error],
                    }
                )
                diagnostics["decisionTraces"].append(decision_trace)
                continue
            # 业务硬边界：学员台控制策略只能决定关机（停机）与已开机设备调功，禁止自动决定开机（开机等待人工下令）。
            if not coupling_online:
                ready_for_manual_start = bool(
                    not hard_safety_blocked
                    and not conflict_stops_device
                    and (
                        (is_electrolyzer and electrolyzer_raise_allowed)
                        or (
                            not is_electrolyzer
                            and fuel_cell_decision is not None
                            and fuel_cell_decision.action == "start"
                        )
                    )
                )
                if ready_for_manual_start:
                    diagnostics["warnings"].append(
                        f"{coupling_name} 已满足运行条件，但自动策略禁止开机，等待人工下令开机"
                    )
                    decision_trace.update(
                        {
                            "action": "hold",
                            "targetElectricPowerKw": 0.0,
                            "controlReason": "awaiting_manual_start",
                            "blockers": ["自动策略禁止开机，等待人工下令开机"],
                        }
                    )
                else:
                    stopped_reason = (
                        "pressure_safety_stop"
                        if pressure_blocked
                        else "hydrogen_soc_safety_stop"
                        if soc_safety_blocked
                        else "hydrogen_tank_horizon_safety_stop"
                        if tank_horizon_blocked
                        else (
                            "start_conditions_not_met"
                            if is_electrolyzer
                            else (
                                fuel_cell_decision.reason
                                if fuel_cell_decision is not None
                                else "start_conditions_not_met"
                            )
                        )
                    )
                    decision_trace.update(
                        {
                            "action": "hold",
                            "targetElectricPowerKw": 0.0,
                            "controlReason": stopped_reason,
                            "blockers": ["当前处于停机状态，等待人工下令开机"],
                        }
                    )
                diagnostics["decisionTraces"].append(decision_trace)
                continue

            is_hard_safety_stop = bool(conflict_stops_device or hard_safety_blocked)
            if conflict_stops_device and current_power > EPSILON:
                requested_delta_kw = -current_power
                device_action = "hydrogen_interlock_stop"
                device_action_reason = (
                    f"simultaneous_operation_stop_{scoped_conflict_stop_mode}"
                )
            elif hard_safety_blocked:
                requested_delta_kw = -current_power
                device_action_reason = (
                    "pressure_safety_stop"
                    if pressure_blocked
                    else "hydrogen_soc_safety_stop"
                    if soc_safety_blocked
                    else "hydrogen_tank_horizon_safety_stop"
                )
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
                # 氢能启机过渡确认期：刚发出启机指令或人工刚合闸爬坡期间，
                # 若仍在宽限期内或功率相对上一拍仍在正向爬升（模拟台一阶滞后），维持启机目标不误触发滞环停机。
                startup_grace_s = max(0.0, float(settings.hydrogen_startup_grace_seconds))
                in_startup_grace = False
                grace_target_kw = start_threshold_kw
                if (
                    hydrogen_dwell_memory is not None
                    and sim_time_seconds is not None
                    and startup_grace_s > EPSILON
                ):
                    raw_grace_entry = hydrogen_dwell_memory.get(f"{coupling_type}:{coupling_name}")
                    if isinstance(raw_grace_entry, dict):
                        last_start_ts = _number(raw_grace_entry.get("lastStartSimTime"))
                        prev_power_kw = _number(raw_grace_entry.get("lastObservedPowerKw"))
                        prev_online = raw_grace_entry.get("couplingOnline")
                        still_ramping_up = bool(
                            prev_power_kw is not None and current_power > prev_power_kw + 0.05
                        )
                        just_manually_started = prev_online is False and coupling_online
                        if just_manually_started:
                            raw_grace_entry["lastStartSimTime"] = float(sim_time_seconds)
                            raw_grace_entry["lastStartTargetKw"] = float(start_threshold_kw)
                            last_start_ts = float(sim_time_seconds)
                        if (
                            last_start_ts is not None
                            and (float(sim_time_seconds) - last_start_ts) >= -EPSILON
                            and (
                                (float(sim_time_seconds) - last_start_ts) < startup_grace_s - EPSILON
                                or still_ramping_up
                            )
                        ):
                            in_startup_grace = True
                            if still_ramping_up:
                                raw_grace_entry["lastStartSimTime"] = float(sim_time_seconds)
                            saved_target = _number(raw_grace_entry.get("lastStartTargetKw"))
                            if saved_target is not None and saved_target > EPSILON:
                                grace_target_kw = saved_target
                if in_startup_grace and coupling_online:
                    clamped_grace = min(allowed_power, max(minimum_running_power, grace_target_kw))
                    requested_delta_kw = max(0.0, clamped_grace - current_power)
                    device_action = "hold"
                    device_action_reason = "startup_grace_hold"
                else:
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
                        scoped_hydrogen_mode_lock == "fuel_cell"
                        or scoped_conflict_stop_mode == "electrolyzer"
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
                not hard_safety_blocked
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
                and not hard_safety_blocked
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
            # 移除此处重复的 topology_island_id 计算（已在决策前按电气岛前置解析）
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
                    if is_hard_safety_stop:
                        diagnostics["warnings"].append(
                            f"氢能设备{coupling_name}触发硬安全停机，{dcac_detail}，仍强制执行安全停机并由电侧平衡承接"
                        )
                    else:
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
                    converter_request_kw = math.copysign(
                        accepted_magnitude,
                        converter_request_kw,
                    )
                    if not is_hard_safety_stop:
                        accepted_delta_kw = math.copysign(
                            accepted_magnitude,
                            accepted_delta_kw,
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
                diesel_delta_kw = math.copysign(
                    accepted_magnitude,
                    diesel_delta_kw,
                )
                if not is_hard_safety_stop:
                    accepted_delta_kw = math.copysign(
                        accepted_magnitude,
                        accepted_delta_kw,
                    )
                    if electric_side == "DC":
                        converter_request_kw = math.copysign(
                            accepted_magnitude,
                            converter_request_kw,
                        )
            if adjustment_requested and abs(accepted_delta_kw) <= EPSILON and not (
                (hard_safety_blocked and current_power <= EPSILON)
                or maintain_stopped_snapshot
                or is_hard_safety_stop
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
            if is_hard_safety_stop and current_power > EPSILON:
                # 硬安全停机（气压越限/氢罐SOC极限/罐容单拍不足/互锁冲突）：无条件归零停机，不受经济裕度阻塞。
                target_power = 0.0
                accepted_delta_kw = -current_power
                decision_trace["safetyStopOverride"] = True
            elif power_hysteresis_stop:
                # 滞环停机属于状态切换：直接下发停机遥控与 0 设点
                target_power = 0.0
            elif target_power > EPSILON:
                if target_power > allowed_power + EPSILON:
                    target_power = allowed_power
                elif target_power < minimum_running_power - EPSILON:
                    if accepted_delta_kw > EPSILON:
                        target_power = minimum_running_power
                    else:
                        # 降功率跌破最小允许运行功率时直接停机，杜绝落入低载禁区
                        target_power = 0.0
                        power_hysteresis_stop = True
                        device_action = "power_hysteresis_stop"
                        device_action_reason = "below_minimum_running_power_stop"

            # 氢能启停最小驻留冷却时间（安全停机如氢压越限/氢罐SOC极限/互锁冲突不受阻塞）
            dwell_seconds = max(0.0, float(settings.hydrogen_min_dwell_seconds))
            dwell_blocked = False
            dwell_entry: Optional[Dict[str, Any]] = None
            observed_running = bool(
                coupling_online and current_power >= stop_threshold_kw - EPSILON
            )
            if (
                hydrogen_dwell_memory is not None
                and sim_time_seconds is not None
                and math.isfinite(float(sim_time_seconds))
            ):
                dwell_key = f"{coupling_type}:{coupling_name}"
                raw_entry = hydrogen_dwell_memory.get(dwell_key)
                if not isinstance(raw_entry, dict):
                    dwell_entry = {
                        "state": "running" if observed_running else "stopped",
                        "lastTransitionSimTime": None,
                    }
                    hydrogen_dwell_memory[dwell_key] = dwell_entry
                else:
                    dwell_entry = raw_entry
                    prev_state = str(dwell_entry.get("state", ""))
                    observed_state = "running" if observed_running else "stopped"
                    # 人工刚合闸开机（couplingOnline 由 False -> True 跳变）视为人工确认，解除停机驻留锁。
                    if dwell_entry.get("couplingOnline") is False and coupling_online:
                        dwell_entry["lastTransitionSimTime"] = None
                    if prev_state and prev_state != observed_state:
                        dwell_entry["state"] = observed_state
                        dwell_entry["lastTransitionSimTime"] = float(sim_time_seconds)
                dwell_entry["couplingOnline"] = bool(coupling_online)
                dwell_entry["lastObservedPowerKw"] = float(current_power)
                last_ts = _number(dwell_entry.get("lastTransitionSimTime"))
                in_dwell = bool(
                    dwell_seconds > EPSILON
                    and last_ts is not None
                    and (float(sim_time_seconds) - last_ts) >= -EPSILON
                    and (float(sim_time_seconds) - last_ts) < dwell_seconds - EPSILON
                )
                is_safety_override = bool(hard_safety_blocked or conflict_stops_device)
                if in_dwell and not is_safety_override:
                    remaining_s = max(
                        0.0,
                        dwell_seconds - (float(sim_time_seconds) - float(last_ts or 0.0)),
                    )
                    if not observed_running and target_power > EPSILON:
                        # 停机驻留未满：阻止常规经济启机
                        dwell_blocked = True
                        target_power = 0.0
                        accepted_delta_kw = -current_power if current_power > EPSILON else 0.0
                        converter_request_kw = 0.0
                        diesel_delta_kw = 0.0
                        device_action = "hold"
                        device_action_reason = "min_dwell_hold"
                        diagnostics["warnings"].append(
                            f"{coupling_name} 处于停机最小驻留冷却期（剩余 {remaining_s:.1f}s），暂缓启机"
                        )
                    elif observed_running and target_power <= EPSILON:
                        # 运行驻留未满：阻止常规经济停机，安全钳位至最小允许运行功率
                        dwell_blocked = True
                        target_power = min(allowed_power, minimum_running_power)
                        power_hysteresis_stop = False
                        clamped_delta = target_power - current_power
                        accepted_delta_kw = clamped_delta
                        diesel_delta_kw = (
                            clamped_delta if is_electrolyzer else -clamped_delta
                        )
                        if electric_side == "DC":
                            converter_request_kw = (
                                -clamped_delta if is_electrolyzer else clamped_delta
                            )
                        device_action = "hold"
                        device_action_reason = "min_dwell_hold"
                        diagnostics["warnings"].append(
                            f"{coupling_name} 处于运行最小驻留冷却期（剩余 {remaining_s:.1f}s），维持最小运行功率 {target_power:.1f} kW"
                        )
            if dwell_blocked and not observed_running and not maintain_stopped_snapshot:
                decision_trace.update(
                    {
                        "action": "hold",
                        "controlReason": "min_dwell_hold",
                        "blockers": ["氢能启停最小驻留冷却期未满"],
                    }
                )
                diagnostics["decisionTraces"].append(decision_trace)
                continue

            if not dwell_blocked and abs(target_power - requested_target_power) > EPSILON:
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
            # 在 target_power 最终确定后，统一按实际电侧净变化重算柴发与变流器联动账目（防截断/硬停/驻留钳位失配）。
            final_delta_kw = target_power - current_power
            accepted_delta_kw = final_delta_kw
            diesel_delta_kw = (
                final_delta_kw if is_electrolyzer else -final_delta_kw
            )
            if electric_side == "DC":
                converter_request_kw = (
                    -final_delta_kw if is_electrolyzer else final_delta_kw
                )
            else:
                converter_request_kw = 0.0
            target_flow = (
                target_power * float(coefficient)
                if is_electrolyzer
                else target_power / float(coefficient)
            )
            set_value = target_power if active_set_type == "p_set" else target_flow
            run_stat_target: Optional[int] = None
            # 自动策略只允许决定关机（run_stat=0），严禁下发开机遥控（run_stat=1）。
            if target_power <= EPSILON and coupling_online:
                run_stat_target = 0
            emit_analog_setpoint = True
            if run_stat_target is not None:
                coupling_key = (coupling_type, coupling_name)
                if coupling_key not in run_status_control_keys:
                    if is_hard_safety_stop:
                        # 触发硬安全停机但无 RunStat 遥控点时，降级压至物理最小安全功率/流量，绝不静默放任满载运行。
                        fallback_safe_power = max(0.0, float(physical_minimum_power))
                        target_power = min(current_power, fallback_safe_power)
                        final_delta_kw = target_power - current_power
                        accepted_delta_kw = final_delta_kw
                        diesel_delta_kw = final_delta_kw if is_electrolyzer else -final_delta_kw
                        converter_request_kw = (
                            (-final_delta_kw if is_electrolyzer else final_delta_kw)
                            if electric_side == "DC"
                            else 0.0
                        )
                        target_flow = (
                            target_power * float(coefficient)
                            if is_electrolyzer
                            else target_power / float(coefficient)
                        )
                        set_value = target_power if active_set_type == "p_set" else target_flow
                        run_stat_target = None
                        diagnostics["warnings"].append(
                            f"氢能设备{coupling_name}触发硬安全停机但未定义RunStat遥控点，"
                            f"已降级压至最小安全出力 {target_power:.1f} kW，请人工立即检查停机"
                        )
                    else:
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
                else:
                    # 下发停机遥控（run_stat=0）时不再同时向遥调端下发 set_value=0.0，
                    # 防止模拟台按 p_min/flow_min 将 0.0 抬升为正下限造成矛盾指令与合闸带载冲击。
                    emit_analog_setpoint = False
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
            if emit_analog_setpoint:
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
                    "pressureSafetyStop": hard_safety_blocked,
                    "hardSafetyStop": bool(is_hard_safety_stop),
                    "powerHysteresisStop": power_hysteresis_stop,
                }
            )
            if target_flow > EPSILON and hydrogen_island_id:
                if is_electrolyzer:
                    island_planned_charge_flow_nm3h[hydrogen_island_id] = (
                        island_planned_charge_flow_nm3h.get(hydrogen_island_id, 0.0)
                        + float(target_flow)
                    )
                else:
                    island_planned_discharge_flow_nm3h[hydrogen_island_id] = (
                        island_planned_discharge_flow_nm3h.get(hydrogen_island_id, 0.0)
                        + float(target_flow)
                    )
            diagnostics["decisionTraces"].append(dict(planned[-1]))
            if dwell_entry is not None and sim_time_seconds is not None and run_stat_target is not None:
                dwell_entry["state"] = "running" if run_stat_target == 1 else "stopped"
                dwell_entry["lastTransitionSimTime"] = float(sim_time_seconds)
                if run_stat_target == 1:
                    dwell_entry["lastStartSimTime"] = float(sim_time_seconds)
                    dwell_entry["lastStartTargetKw"] = float(target_power)
                else:
                    dwell_entry.pop("lastStartSimTime", None)
                    dwell_entry.pop("lastStartTargetKw", None)
            elif (
                dwell_entry is not None
                and sim_time_seconds is not None
                and required_start_delta_kw is not None
                and target_power > EPSILON
            ):
                dwell_entry["lastStartSimTime"] = float(sim_time_seconds)
                dwell_entry["lastStartTargetKw"] = float(target_power)
            if accepted_delta_kw > EPSILON:
                active_mode_name = "electrolyzer" if is_electrolyzer else "fuel_cell"
                if not scoped_hydrogen_mode_lock:
                    island_mode_lock[topology_island_id] = active_mode_name
                if not hydrogen_mode_lock:
                    hydrogen_mode_lock = active_mode_name
                    diagnostics["interlockMode"] = hydrogen_mode_lock
                    diagnostics["interlockActive"] = True
            if (
                diesel_has_topology_tags
                and topology_island_id
                and topology_island_id in island_predicted_diesel_kw
            ):
                island_predicted_diesel_kw[topology_island_id] += diesel_delta_kw
            predicted_diesel_kw += diesel_delta_kw
    if apply_electrical_corrections:
        _publish_final_acdc_coordination(
            command_rows,
            coordinated_converter_rows,
        )
    if hydrogen_dwell_memory is not None:
        diagnostics["pendingDwellMemory"] = hydrogen_dwell_memory
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
            "predictedDieselLoadRatioAfter": (
                predicted_diesel_kw / diesel_capacity_kw
                if diesel_capacity_kw > EPSILON
                else None
            ),
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
