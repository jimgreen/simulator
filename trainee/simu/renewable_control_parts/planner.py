"""renewable_control 拆分模块：新能源综合控制计划主入口（calculate_renewable_control_plan）。"""

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
    _environment_measurement_status,
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
from .recovery import *  # noqa: F401,F403
from .recovery import (
    _AcSideBudget,
    _DcGroupBudget,
    _RenewableStorageIslandComponent,
    _active_dc_transfer_group_ids,
    _active_load_budgets,
    _active_load_side_metrics,
    _allocate,
    _allocate_by_margin,
    _allocate_converters,
    _allocate_signed_converter_target,
    _apply_ac_to_dc_renewable_absorption,
    _apply_converter_group_adjustment,
    _apply_storage_switch_deadband,
    _capacity_weighted_soc,
    _clamp_final_command_rows_to_boundaries,
    _converter_direct_state,
    _converter_export_margins_kw,
    _dc_transfer_group_sort_key,
    _diesel_boundary_violation,
    _equal_margin_increments,
    _final_command_power_bounds_kw,
    _grid_storage_signed_power_bounds_kw,
    _grid_storage_sort_key,
    _grid_storage_step_kw,
    _grid_storage_target_margins,
    _move_toward,
    _parallel_converter_limit,
    _plan_recovery,
    _plan_renewable_storage_island_component,
    _project_balance_storage_targets,
    _renewable_storage_island_components,
    _resolve_converter_capacities,
    _side_aware_renewable_recovery_plan,
    _side_aware_renewable_recovery_plan_without_balance,
    _side_aware_storage_state,
)
from .dispatch import *  # noqa: F401,F403
from .dispatch import (
    _apply_optimization_targets,
    _business_decision_log_detail,
    _clamp_direct_balance_targets_to_soc_bounds,
    _dc_transfer_group_metrics,
    _decision_ratio_text,
    _decision_value_text,
    _hydrogen_business_decision_detail,
    _hydrogen_reason_text,
    _hydrogen_trace_action_text,
    _metric_target,
    _optimization_balance_delta_warnings,
    _optimization_decision_detail,
    _optimization_metrics,
    _optimization_performance_diagnostics,
    _optimization_supported_row,
    _plan_direct_grid_forming_dispatch,
    _plan_direct_grid_storage_dispatch,
    _rebalance_dc_projection_targets,
    _source_label,
    _storage_target_is_hard_protection,
    _sum_metric,
    _sum_optional_metric,
    _task8_decision_detail,
    _task8_side_metrics,
    _validate_dispatch_by_ac_component,
)


def _plan_sim_time_seconds(snapshot: Mapping[str, Any]) -> Optional[float]:
    """从快照提取单调仿真时间（秒），优先数值字段，禁止对 HH:MM:SS 字符串误提取小时数。"""
    for block_name in ("measurement_clock", "clock", "compute"):
        block = snapshot.get(block_name)
        if not (type(block) is dict or isinstance(block, Mapping)):
            continue
        abs_sec = _number(block.get("absolute_second"))
        if abs_sec is not None and math.isfinite(abs_sec):
            return float(abs_sec)
        abs_min = _number(block.get("absolute_minute"))
        if abs_min is not None and math.isfinite(abs_min):
            return float(abs_min) * 60.0
        raw_simu_time = block.get("simu_time")
        if not (isinstance(raw_simu_time, str) and ":" in raw_simu_time):
            sim_sec = _number(raw_simu_time)
            if sim_sec is not None and math.isfinite(sim_sec):
                return float(sim_sec)
        minute_val = _number(block.get("minute"))
        if minute_val is not None and math.isfinite(minute_val):
            return float(minute_val) * 60.0
    return None


def _reset_runtime_memory_if_clock_rewound(
    runtime_memory: Optional[MutableMapping[str, Any]],
    sim_time_seconds: Optional[float],
    *,
    run_id: Optional[int] = None,
    step_count: Optional[int] = None,
) -> None:
    """仿真重启、跨日 run_id 切换、步数或时钟回退时清空跨周期状态机缓存，防止脏记忆跨轮次污染。"""
    if runtime_memory is None:
        return
    prev_run_id = runtime_memory.get("lastRunId")
    prev_step = runtime_memory.get("lastStepCount")
    prev_ts = _number(runtime_memory.get("lastSimTimeSeconds"))
    reset_needed = False
    if run_id is not None and prev_run_id is not None and int(run_id) != int(prev_run_id):
        reset_needed = True
    if step_count is not None and prev_step is not None and int(step_count) < int(prev_step):
        reset_needed = True
    if (
        sim_time_seconds is not None
        and math.isfinite(sim_time_seconds)
        and prev_ts is not None
        and sim_time_seconds < prev_ts - 1e-6
    ):
        reset_needed = True
    if reset_needed:
        runtime_memory.pop("hydrogen_dwell", None)
        runtime_memory.pop("renewable_saturation", None)
    if run_id is not None:
        runtime_memory["lastRunId"] = int(run_id)
    if step_count is not None:
        runtime_memory["lastStepCount"] = int(step_count)
    if sim_time_seconds is not None and math.isfinite(sim_time_seconds):
        runtime_memory["lastSimTimeSeconds"] = float(sim_time_seconds)


def _apply_renewable_natural_upper_bounds(
    online_renewable: Sequence[MutableMapping[str, Any]],
    renewable_target_by_device: MutableMapping[Tuple[str, str], float],
    settings: RenewableControlSettings,
    *,
    runtime_memory: Optional[MutableMapping[str, Any]],
    sim_time_seconds: Optional[float],
    wind_measurement_status: Mapping[str, Any],
    solar_measurement_status: Mapping[str, Any],
    diesel_guard_blocked: bool,
    boundary_backtracked: bool = False,
) -> Dict[str, Any]:
    """双层融合自然资源上限判断：
    1) 第一层（气象前馈）：严格受对应测点配置与可用状态门控——仅当太阳辐照量测值有效时进入光伏
       夜间/低光判断，仅当风速量测值有效时进入风电无风/低风判断；
    2) 第二层（电侧闭环指令-响应失配）：兜底测点停用、缺失或偏差场景，连续失配后在优化器中封顶，
       并按固定周期执行不影响柴发平衡的解耦小步长探顶。
    """
    saturation_store: Optional[MutableMapping[str, Any]] = None
    if runtime_memory is not None:
        raw_store = runtime_memory.get("renewable_saturation")
        if not isinstance(raw_store, dict):
            raw_store = {}
            runtime_memory["renewable_saturation"] = raw_store
        saturation_store = raw_store

    weather_limited_devices: List[str] = []
    saturated_devices: List[str] = []
    probing_devices: List[str] = []

    for row in online_renewable:
        if not row.get("commandable"):
            continue
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        tech = str(row.get("technology", ""))
        capacity = max(0.0, _finite_number(row.get("capacityKw")))
        current_kw = _number(row.get("planningCurrentKw", row.get("currentKw")))
        if current_kw is None or capacity <= EPSILON:
            continue
        current_kw = max(0.0, float(current_kw))
        step_kw = settings.step_coefficient * capacity
        cmd_deadband = max(1.0, 0.002 * capacity)
        release_deadband = max(1.0, 0.005 * capacity)

        weather_status = (
            wind_measurement_status
            if tech == "wind"
            else solar_measurement_status
            if tech == "pv"
            else {"available": False, "value": None}
        )
        weather_available = bool(
            row.get("weatherMeasurementAvailable") and weather_status.get("available")
        )
        weather_val = _number(weather_status.get("value")) if weather_available else None
        control_weather_kw = (
            _number(row.get("controlWeatherAvailableKw"))
            if weather_available
            else None
        )

        # 第一层：有效气象前馈自然上限（严控门控：仅对应测点有效时触发）
        # 仅确认零资源且实测接近 0 时硬置 0；正常发电区间取 max(current_kw, control_weather_kw)，
        # 只封堵虚假向上增发空间，杜绝量测噪声或传感器负偏导致“倒压正常实发、多烧柴油”。
        natural_upper: Optional[float] = None
        natural_reason = ""
        if control_weather_kw is not None:
            raw_weather_kw = max(0.0, min(capacity, float(control_weather_kw)))
            zero_meas_tol = max(1.0, 0.02 * capacity)
            if raw_weather_kw <= EPSILON and current_kw <= zero_meas_tol:
                natural_upper = 0.0
                natural_reason = "weather_zero_resource"
            else:
                natural_upper = min(capacity, max(current_kw, raw_weather_kw))
                natural_reason = "weather_available_limit"
            if natural_upper < min(capacity, current_kw + step_kw) - EPSILON:
                weather_limited_devices.append(key[1] or key[0])

        # 第二层：电侧闭环指令-响应失配判别（抗气象停用/故障/测点误差）
        saturated = False
        probe_step_kw = 0.0
        if saturation_store is not None:
            dev_mem_key = f"{key[0]}:{key[1]}"
            entry = saturation_store.get(dev_mem_key)
            if not isinstance(entry, dict):
                entry = {
                    "lastSimTime": None,
                    "lastCommandKw": None,
                    "lastMeasuredKw": None,
                    "mismatchCount": 0,
                    "saturated": False,
                    "saturatedBaselineKw": None,
                    "saturatedWeatherValue": None,
                    "probeCounter": 0,
                }
                saturation_store[dev_mem_key] = entry

            prev_ts = _number(entry.get("lastSimTime"))
            prev_cmd = _number(entry.get("lastCommandKw"))
            prev_meas = _number(entry.get("lastMeasuredKw"))
            clock_advanced = bool(
                sim_time_seconds is not None
                and prev_ts is not None
                and float(sim_time_seconds) > prev_ts + EPSILON
            )
            if clock_advanced and prev_cmd is not None and prev_meas is not None:
                cmd_delta = prev_cmd - prev_meas
                meas_delta = current_kw - prev_meas
                weather_rise_threshold = 0.3 if tech == "wind" else 15.0
                sat_weather = _number(entry.get("saturatedWeatherValue"))
                sat_baseline = _number(entry.get("saturatedBaselineKw"))

                weather_rose = bool(
                    weather_available
                    and weather_val is not None
                    and sat_weather is not None
                    and weather_val > sat_weather + weather_rise_threshold
                )
                output_rose = bool(
                    bool(entry.get("saturated"))
                    and sat_baseline is not None
                    and current_kw > sat_baseline + release_deadband
                )
                active_curtail_issued = cmd_delta < -cmd_deadband

                if weather_rose or output_rose or active_curtail_issued:
                    entry["saturated"] = False
                    entry["mismatchCount"] = 0
                    entry["probeCounter"] = 0
                    entry["saturatedBaselineKw"] = None
                    entry["saturatedWeatherValue"] = None
                elif cmd_delta > cmd_deadband:
                    if boundary_backtracked:
                        # 模拟台本拍潮流回溯未完整执行增量，冻结失配计数，防止误锁自然资源饱和。
                        pass
                    elif meas_delta >= 0.15 * cmd_delta:
                        # 增发指令获得有效实测响应 -> 解除饱和
                        entry["saturated"] = False
                        entry["mismatchCount"] = 0
                        entry["probeCounter"] = 0
                        entry["saturatedBaselineKw"] = None
                        entry["saturatedWeatherValue"] = None
                    else:
                        entry["mismatchCount"] = int(entry.get("mismatchCount", 0)) + 1
                        if entry["mismatchCount"] >= 2:
                            if not entry.get("saturated"):
                                entry["saturatedBaselineKw"] = current_kw
                                entry["saturatedWeatherValue"] = weather_val
                                entry["probeCounter"] = 0
                            entry["saturated"] = True

            saturated = bool(entry.get("saturated"))
            if saturated:
                saturated_devices.append(key[1] or key[0])
                if clock_advanced:
                    entry["probeCounter"] = int(entry.get("probeCounter", 0)) + 1
                # 若有效气象明确为 0（如夜间 0 辐照/无风）或柴发保护限电，则无需探顶
                weather_confirmed_zero = bool(
                    control_weather_kw is not None and control_weather_kw <= EPSILON
                )
                if (
                    not diesel_guard_blocked
                    and not weather_confirmed_zero
                    and int(entry.get("probeCounter", 0)) >= 10
                    and capacity - current_kw > cmd_deadband
                ):
                    probe_step_kw = min(
                        max(0.0, capacity - current_kw),
                        max(cmd_deadband * 1.5, 0.5 * step_kw),
                    )
                    entry["probeCounter"] = 0
                    probing_devices.append(key[1] or key[0])

        if saturated:
            natural_upper = (
                min(natural_upper, current_kw)
                if natural_upper is not None
                else current_kw
            )
            natural_reason = "electrical_response_saturated"

        if natural_upper is not None:
            row["naturalUpperKw"] = natural_upper
            row["naturalUpperReason"] = natural_reason
            existing_upper = _number(row.get("dispatchUpperKw"))
            row["dispatchUpperKw"] = (
                min(existing_upper, natural_upper)
                if existing_upper is not None
                else natural_upper
            )
            if not row.get("dispatchUpperReason"):
                row["dispatchUpperReason"] = natural_reason
            if key in renewable_target_by_device:
                renewable_target_by_device[key] = min(
                    float(renewable_target_by_device[key]),
                    natural_upper,
                )
        row["naturalResourceSaturated"] = saturated
        row["decoupledProbeStepKw"] = probe_step_kw

    return {
        "windMeasurement": dict(wind_measurement_status),
        "solarMeasurement": dict(solar_measurement_status),
        "weatherLimitedDevices": weather_limited_devices,
        "saturatedDevices": saturated_devices,
        "probingDevices": probing_devices,
    }


def _finalize_renewable_saturation_memory(
    command_rows: Sequence[MutableMapping[str, Any]],
    *,
    runtime_memory: Optional[MutableMapping[str, Any]],
    sim_time_seconds: Optional[float],
    quality_blocked: bool,
) -> None:
    """在主优化器与氢能联动完成后：
    1) 对标记了 decoupledProbeStepKw 的饱和新能源执行解耦小步长探顶（不改柴发/储能目标）；
    2) 将本拍下发给在线可控新能源的指令与当前实测写入 runtime_memory，供下一拍闭环评估。
    """
    if quality_blocked:
        return
    saturation_store = (
        runtime_memory.get("renewable_saturation")
        if runtime_memory is not None
        and isinstance(runtime_memory.get("renewable_saturation"), dict)
        else None
    )
    # 为防止多机同拍同时探顶产生大阶跃冲击平衡节点，每拍按岛最多允许 1 台饱和机组执行小步探顶，
    # 且必须确认对应分量未处于高 SOC 过充/闭锁保护态。
    probed_islands: set[str] = set()
    blocked_probe_components: set[str] = set()
    for row in command_rows:
        if row.get("technology") == "storage" and row.get("online"):
            if row.get("socConstraint") == "above_upper" or row.get("automaticControlBlocked"):
                comp = str(row.get("dcTransferGroupId") or row.get("gridComponentId") or "").strip()
                if comp:
                    blocked_probe_components.add(comp)
    for row in command_rows:
        if row.get("technology") not in {"wind", "pv"}:
            continue
        if not row.get("online") or row.get("commandable") is False or row.get("manualLocked"):
            continue
        current_kw = _number(row.get("planningCurrentKw", row.get("currentKw")))
        command_kw = _number(row.get("commandKw"))
        capacity = max(0.0, _finite_number(row.get("capacityKw")))
        if current_kw is None or command_kw is None:
            continue
        probe_step_kw = max(0.0, _finite_number(row.get("decoupledProbeStepKw")))
        probe_island = str(row.get("optimizationIslandId") or row.get("gridComponentId") or "")
        probe_comp = str(row.get("dcTransferGroupId") or row.get("gridComponentId") or "").strip()
        # 仅在系统未要求主动限电、未处高 SOC 保护且本岛本拍尚未有其他机组探顶时发出小步试探
        if (
            probe_step_kw > EPSILON
            and command_kw >= current_kw - EPSILON
            and row.get("strategyCommand") is not False
            and row.get("dispatchEnabled") is not False
            and not row.get("automaticControlBlocked")
            and probe_comp not in blocked_probe_components
            and probe_island not in probed_islands
        ):
            probed_kw = min(capacity, current_kw + probe_step_kw)
            if probed_kw > command_kw + EPSILON:
                row["commandKw"] = probed_kw
                row["targetKw"] = probed_kw
                row["decoupledProbeApplied"] = True
                command_kw = probed_kw
                probed_islands.add(probe_island)

        if saturation_store is not None and sim_time_seconds is not None:
            dev_mem_key = f"{row.get('dev_type', '')}:{row.get('dev_name', '')}"
            entry = saturation_store.get(dev_mem_key)
            if not isinstance(entry, dict):
                entry = {
                    "mismatchCount": 0,
                    "saturated": False,
                    "saturatedBaselineKw": None,
                    "saturatedWeatherValue": None,
                    "probeCounter": 0,
                }
                saturation_store[dev_mem_key] = entry
            entry["lastSimTime"] = float(sim_time_seconds)
            entry["lastCommandKw"] = float(command_kw)
            entry["lastMeasuredKw"] = float(current_kw)


def _prepare_plan_weather_and_resources(
    snapshot: Mapping[str, Any],
    quality: _Quality,
) -> Tuple[
    Dict[Tuple[str, str, str], MeasurementValue],
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[float],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Tuple[_LinkedResourceSpec, ...],
    Tuple[_LinkedResourceSpec, ...],
    Tuple[ResourceRef, ...],
    set[Tuple[str, str]],
    List[Dict[str, Any]],
    Tuple[ResourceRef, ...],
]:
    """阶段 1：单次索引量测、提取气象边界与测点可用状态、关联资源规格与待解析拓扑资源清单。"""
    measurements = _measurement_index(snapshot)
    load_kw = _load_boundary(snapshot, measurements, quality)
    wind_measurement_status = _environment_measurement_status(
        snapshot, measurements, "WIND_SPEED"
    )
    solar_measurement_status = _environment_measurement_status(
        snapshot, measurements, "SOLAR_IRRADIANCE"
    )
    wind_measurement = (
        MeasurementValue(
            value=float(wind_measurement_status["value"]),
            source=str(wind_measurement_status["source"]),
            row={},
        )
        if wind_measurement_status.get("available")
        and wind_measurement_status.get("value") is not None
        else None
    )
    irradiance_measurement = (
        MeasurementValue(
            value=float(solar_measurement_status["value"]),
            source=str(solar_measurement_status["source"]),
            row={},
        )
        if solar_measurement_status.get("available")
        and solar_measurement_status.get("value") is not None
        else None
    )
    temperature_measurement = _measured(measurements, "Environment", "weather", ("AIR_TEMP",))
    observed_wind_speed = _observed_environment_value(
        snapshot,
        wind_measurement,
        "wind_speed_mps",
    )
    observed_irradiance = _observed_environment_value(
        snapshot,
        irradiance_measurement,
        "solar_irradiance_w_m2",
    )
    observed_air_temperature = _observed_environment_value(
        snapshot,
        temperature_measurement,
        "air_temp_c",
    )
    quality.input(
        "windSpeed",
        observed_wind_speed,
        str(wind_measurement_status.get("source") or "curve_boundary"),
        bool(wind_measurement_status.get("available")),
    )
    quality.input(
        "solarIrradiance",
        observed_irradiance,
        str(solar_measurement_status.get("source") or "curve_boundary"),
        bool(solar_measurement_status.get("available")),
    )
    quality.input(
        "airTemperature",
        observed_air_temperature,
        "scada_or_curve_boundary",
        observed_air_temperature is not None,
    )

    identity_diagnostics = _duplicate_typed_identities(snapshot)
    renewable_specs, storage_specs, resource_refs = _linked_resource_specs(
        snapshot,
        quality,
        identity_diagnostics,
    )
    resource_keys = {
        (spec.dev_type, spec.dev_name)
        for spec in (*renewable_specs, *storage_specs)
    }
    diesel_rows = _diesel_rows(snapshot, measurements, resource_keys, quality)
    diesel_refs = [
        ResourceRef(
            "diesel",
            str(row.get("model_block", "")),
            str(row.get("dev_name", "")),
        )
        for row in diesel_rows
    ]
    hydrogen_electric_refs = _hydrogen_electric_resource_refs(snapshot)
    topology_resource_by_key = {
        (resource.dev_type, resource.dev_name): resource
        for resource in (*resource_refs, *diesel_refs)
    }
    for resource in hydrogen_electric_refs:
        topology_resource_by_key.setdefault(
            (resource.dev_type, resource.dev_name),
            resource,
        )
    topology_resources = tuple(topology_resource_by_key.values())
    return (
        measurements,
        load_kw,
        observed_wind_speed,
        observed_irradiance,
        observed_air_temperature,
        wind_measurement_status,
        solar_measurement_status,
        identity_diagnostics,
        tuple(renewable_specs),
        tuple(storage_specs),
        tuple(resource_refs),
        resource_keys,
        diesel_rows,
        topology_resources,
    )


def calculate_renewable_control_plan(
    snapshot: Mapping[str, Any],
    settings: Optional[RenewableControlSettings] = None,
    *,
    data_source: str = "remote",
    snapshot_age_seconds: float = 0.0,
    topology_static_context: Optional[ResourceTopologyStaticContext] = None,
    runtime_memory: Optional[MutableMapping[str, Any]] = None,
) -> Dict[str, Any]:
    plan_started = time.perf_counter()
    configured_settings = (settings or RenewableControlSettings()).normalized()
    renewable_effective_decision_step_ratio = configured_settings.step_coefficient
    storage_effective_decision_step_ratio = configured_settings.storage_step_ratio
    settings = configured_settings
    sim_time_seconds = _plan_sim_time_seconds(snapshot)
    sample_clock_for_mem = _measurement_sample_clock(snapshot)
    mem_run_id = (
        int(_number(sample_clock_for_mem.get("run_id"), 0.0) or 0)
        if sample_clock_for_mem.get("run_id") is not None
        else None
    )
    mem_step_count = (
        int(_number(sample_clock_for_mem.get("step_count"), 0.0) or 0)
        if sample_clock_for_mem.get("step_count") is not None
        else None
    )
    _reset_runtime_memory_if_clock_rewound(
        runtime_memory,
        sim_time_seconds,
        run_id=mem_run_id,
        step_count=mem_step_count,
    )
    quality = _Quality(data_source, snapshot_age_seconds)
    (
        measurements,
        load_kw,
        observed_wind_speed,
        observed_irradiance,
        observed_air_temperature,
        wind_measurement_status,
        solar_measurement_status,
        identity_diagnostics,
        renewable_specs,
        storage_specs,
        resource_refs,
        resource_keys,
        diesel_rows,
        topology_resources,
    ) = _prepare_plan_weather_and_resources(snapshot, quality)
    wind_speed = observed_wind_speed
    irradiance = observed_irradiance
    air_temperature = observed_air_temperature
    topology_started = time.perf_counter()
    input_processing_seconds = topology_started - plan_started
    if topology_static_context is None:
        resource_topology = resolve_resource_topology(snapshot, topology_resources)
    else:
        resource_topology = resolve_resource_topology(
            snapshot,
            topology_resources,
            static_context=topology_static_context,
        )
    topology_finished = time.perf_counter()
    topology_analysis_seconds = topology_finished - topology_started
    converter_group_ids = {
        converter_key: group_id
        for group_id, group in resource_topology.dc_transfer_groups.items()
        for converter_key in group.converter_keys
    }
    renewable_rows = _renewable_rows(
        snapshot,
        measurements,
        renewable_specs,
        resource_topology.resources,
        quality,
        observed_wind_speed=observed_wind_speed,
        observed_solar_irradiance=observed_irradiance,
        observed_air_temperature=observed_air_temperature,
        wind_measurement_available=bool(wind_measurement_status.get("available")),
        solar_measurement_available=bool(solar_measurement_status.get("available")),
        control_wind_speed=_number(wind_measurement_status.get("value")),
        control_solar_irradiance=_number(solar_measurement_status.get("value")),
    )
    _annotate_diesel_topology(
        diesel_rows,
        resource_topology.resources,
        resource_topology.device_component_ids,
    )
    storage_rows = _storage_rows(
        snapshot,
        measurements,
        settings,
        quality,
        storage_specs,
        resource_topology.resources,
        resource_topology.dc_transfer_groups,
    )
    internal_converter_keys = {
        converter_key
        for connection in resource_topology.resources.values()
        if connection.technology in {"wind", "pv", "storage"}
        for converter_key in connection.converter_path
    }
    dispatchable_converter_keys = structured_grid_converter_keys(snapshot)
    converter_inventory_rows = sorted(
        _converter_rows(
            snapshot,
            measurements,
            converter_group_ids=converter_group_ids,
            internal_converter_keys=internal_converter_keys,
            grid_converter_keys=dispatchable_converter_keys,
            identity_diagnostics=identity_diagnostics,
            quality=quality,
        ),
        key=_converter_row_sort_key,
    )
    fail_closed_scopes = _apply_grid_forming_fail_closed_scopes(
        renewable_rows,
        storage_rows,
        converter_inventory_rows,
        diesel_rows,
        quality,
    )
    all_converter_rows = [
        row for row in converter_inventory_rows if row.get("commandable")
    ]
    converter_validation_rows = [
        row
        for row in converter_inventory_rows
        if row.get("online")
        and row.get("converterRole") == "grid"
        and str(row.get("dcTransferGroupId", ""))
    ]
    diagnostic_converter_rows = [
        row for row in converter_inventory_rows if not row.get("commandable")
    ]

    strategy_online_renewable = [row for row in renewable_rows if row["online"]]
    online_diesel = [row for row in diesel_rows if row["online"]]
    measured_diesel = [row for row in online_diesel if row.get("currentKw") is not None]
    diesel_current = (
        sum(_finite_number(row.get("currentKw")) for row in measured_diesel)
        if measured_diesel
        else None
    )
    diesel_min = sum(max(0.0, _finite_number(row.get("minKw"))) for row in online_diesel)
    diesel_capacity = sum(
        max(0.0, _finite_number(row.get("capacityKw"))) for row in online_diesel
    )
    diesel_deadband_kw = (
        settings.diesel_power_protection_ratio * diesel_capacity
    )
    diesel_deadband_lower_kw = diesel_min
    diesel_deadband_upper_kw = diesel_min + diesel_deadband_kw

    online_ac_balance_storage = [
        row
        for row in storage_rows
        if row["online"] and row.get("role") == "balance" and row.get("connectionSide") == "AC"
    ]
    online_dc_balance_storage = [
        row
        for row in storage_rows
        if row["online"]
        and row.get("role") == "balance"
        and row.get("connectionSide") == "DC"
        and row.get("stateEligible")
    ]
    online_ac_grid_following_storage = [
        row
        for row in storage_rows
        if row["online"] and row.get("role") == "grid_following" and row.get("connectionSide") == "AC"
    ]
    online_dc_grid_following_storage = [
        row
        for row in storage_rows
        if row["online"] and row.get("role") == "grid_following" and row.get("connectionSide") == "DC"
    ]
    ac_balance_storage_current = sum(
        _finite_number(row.get("currentKw"))
        for row in online_ac_balance_storage
        if row.get("currentKw") is not None
    )
    dc_balance_storage_current = sum(
        _finite_number(row.get("currentKw"))
        for row in online_dc_balance_storage
        if row.get("currentKw") is not None
    )
    ac_grid_following_storage_current = sum(
        _finite_number(row.get("currentKw"))
        for row in online_ac_grid_following_storage
        if row.get("currentKw") is not None
    )
    dc_grid_following_storage_current = sum(
        _finite_number(row.get("currentKw"))
        for row in online_dc_grid_following_storage
        if row.get("currentKw") is not None
    )

    ac_bus_rows = _device_state_rows(snapshot, "ACRealBs")
    online_ac_buses = [row for row in ac_bus_rows if _is_online(row, measurements)]
    ac_load_devices = [
        device
        for device in snapshot.get("devices", []) or []
        if (type(device) is dict or isinstance(device, Mapping)) and _device_model_block(device) == "ACLoad"
    ]
    online_ac_loads = [device for device in ac_load_devices if _is_online(device, measurements)]
    ac_side_fully_offline = bool(ac_bus_rows) and not online_ac_buses and not online_diesel and not online_ac_loads

    storage_group_set = {
        str(row.get("dcTransferGroupId", ""))
        for row in online_dc_balance_storage
        if str(row.get("dcTransferGroupId", ""))
    }
    candidate_group_ids = sorted(
        (
            group_id
            for group_id in storage_group_set
            if group_id in resource_topology.dc_transfer_groups
        ),
        key=lambda group_id: _dc_transfer_group_sort_key(
            resource_topology,
            group_id,
        ),
    )
    primary_control_group_id = candidate_group_ids[0] if candidate_group_ids else ""
    if primary_control_group_id:
        normal_online_storage = [
            row
            for row in online_dc_balance_storage
            if row.get("dcTransferGroupId") == primary_control_group_id
        ]
        normal_converter_rows = [
            row
            for row in all_converter_rows
            if row.get("dcTransferGroupId") == primary_control_group_id
        ]
        held_normal_converter_rows = [
            row for row in all_converter_rows if row not in normal_converter_rows
        ]
    elif all_converter_rows:
        normal_online_storage = []
        normal_converter_rows = []
        held_normal_converter_rows = list(all_converter_rows)
    else:
        normal_online_storage = list(online_dc_balance_storage)
        normal_converter_rows = []
        held_normal_converter_rows = []

    dc_renewable_rows = [
        row
        for row in strategy_online_renewable
        if row.get("connectionSide") == "DC" and row.get("gridComponentId")
    ]
    island_components = _renewable_storage_island_components(
        dc_renewable_rows,
        online_dc_balance_storage,
        converter_validation_rows,
    )
    renewable_storage_island = bool(
        ac_side_fully_offline
        and island_components
    )
    primary_island_component = island_components[0] if renewable_storage_island else None
    island_online_renewable = [
        row
        for component in island_components
        for row in component.renewable_rows
    ]
    island_online_storage = [
        row
        for component in island_components
        for row in component.storage_rows
    ]
    island_converter_keys = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        for component in island_components
        for row in component.converter_rows
    }
    if primary_island_component is not None:
        online_storage = list(primary_island_component.storage_rows)
        online_renewable = list(primary_island_component.renewable_rows)
        converter_rows = list(primary_island_component.converter_rows)
        held_converter_rows = [
            row
            for row in all_converter_rows
            if (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            not in island_converter_keys
        ]
    else:
        online_storage = normal_online_storage
        online_renewable = strategy_online_renewable
        converter_rows = normal_converter_rows
        held_converter_rows = held_normal_converter_rows
    renewable_metric_rows = (
        island_online_renewable
        if renewable_storage_island
        else online_renewable
    )
    has_ac_grid_forming_storage = any(
        row.get("connectionSide") == "AC"
        and row.get("role") == "balance"
        and row.get("online")
        and not row.get("automaticControlBlocked")
        for row in storage_rows
    )
    operating_mode = (
        "renewable_storage_island"
        if renewable_storage_island
        else "diesel_reference"
        if online_diesel
        else "grid_forming_storage_reference"
        if has_ac_grid_forming_storage
        else "blocked_no_diesel"
    )

    missing_renewable_power = [
        row for row in renewable_metric_rows if row.get("currentKw") is None
    ]
    for row in missing_renewable_power:
        quality.add(
            f"{row['category']}{row['dev_name']}缺少有效实时有功，已仅闭锁该设备所在优化岛",
        )
    capability_unknown_rows = [
        row
        for row in renewable_metric_rows
        if row.get("environmentKnown") and not row.get("capabilityKnown")
    ]
    for row in capability_unknown_rows:
        quality.add(
            f"{row['category']}{row['dev_name']}缺少计算最大可发所需的有效模型参数，已仅闭锁该设备",
        )
    renewable_current = sum(
        _finite_number(row.get("currentKw")) for row in renewable_metric_rows
    )
    renewable_capacity = sum(
        max(0.0, _finite_number(row.get("capacityKw")))
        for row in renewable_metric_rows
    )
    wind_current = sum(
        _finite_number(row.get("currentKw"))
        for row in renewable_metric_rows
        if row.get("technology") == "wind"
    )
    pv_current = sum(
        _finite_number(row.get("currentKw"))
        for row in renewable_metric_rows
        if row.get("technology") == "pv"
    )

    measured_storage = [row for row in online_storage if row.get("currentKw") is not None]
    storage_current = (
        sum(_finite_number(row.get("currentKw")) for row in measured_storage)
        if measured_storage
        else None
    )
    grid_forming_storage_charge_capacity_kw = sum(
        max(0.0, _finite_number(row.get("maxChargePowerKw")))
        for row in online_storage
        if row.get("role") == "balance"
    )
    grid_forming_storage_discharge_capacity_kw = sum(
        max(0.0, _finite_number(row.get("maxDischargePowerKw")))
        for row in online_storage
        if row.get("role") == "balance"
    )
    grid_forming_storage_charge_protection_kw = (
        settings.grid_forming_storage_protection_ratio
        * grid_forming_storage_charge_capacity_kw
    )
    grid_forming_storage_discharge_protection_kw = (
        settings.grid_forming_storage_protection_ratio
        * grid_forming_storage_discharge_capacity_kw
    )
    storage_control_horizon_minutes = max(
        (_finite_number(row.get("controlHorizonMinutes")) for row in online_storage),
        default=_storage_control_horizon_minutes(snapshot, settings),
    )
    known_soc = [
        _finite_number(row.get("soc"))
        for row in online_storage
        if row.get("socKnown") and row.get("soc") is not None
    ]
    storage_soc = sum(known_soc) / len(known_soc) if known_soc else None
    known_soc_rows = [row for row in online_storage if row.get("socKnown") and row.get("soc") is not None]
    storage_soc_lower_limit = (
        sum(_finite_number(row.get("socMin")) for row in known_soc_rows) / len(known_soc_rows)
        if known_soc_rows
        else None
    )
    storage_soc_upper_limit = (
        sum(_finite_number(row.get("socMax")) for row in known_soc_rows) / len(known_soc_rows)
        if known_soc_rows
        else None
    )
    storage_soc_region = (
        "unknown"
        if storage_soc is None or storage_soc_lower_limit is None or storage_soc_upper_limit is None
        else "below_lower"
        if storage_soc < storage_soc_lower_limit
        else "low_guard"
        if storage_soc < storage_soc_lower_limit + settings.soc_deadband
        else "above_upper"
        if storage_soc > storage_soc_upper_limit
        else "high_guard"
        if storage_soc > storage_soc_upper_limit - settings.soc_deadband
        else "normal"
    )
    soc_upper_deadband_threshold = (
        min(1.0, storage_soc_upper_limit + settings.soc_deadband)
        if storage_soc_upper_limit is not None
        else None
    )
    soc_lower_deadband_threshold = (
        max(0.0, storage_soc_lower_limit - settings.soc_deadband)
        if storage_soc_lower_limit is not None
        else None
    )
    soc_above_upper_deadband = bool(
        storage_soc is not None
        and soc_upper_deadband_threshold is not None
        and (
            storage_soc > soc_upper_deadband_threshold + EPSILON
            or (
                soc_upper_deadband_threshold >= 1.0 - EPSILON
                and storage_soc >= 1.0 - EPSILON
            )
        )
    )
    soc_below_lower_deadband = bool(
        storage_soc is not None
        and soc_lower_deadband_threshold is not None
        and (
            storage_soc < soc_lower_deadband_threshold - EPSILON
            or (
                soc_lower_deadband_threshold <= EPSILON
                and storage_soc <= EPSILON
            )
        )
    )
    storage_above_upper = [row for row in online_storage if row.get("socConstraint") == "above_upper"]
    storage_below_lower = [row for row in online_storage if row.get("socConstraint") == "below_lower"]
    raw_charge_before_derating = sum(
        max(0.0, _finite_number(row.get("chargePowerBeforeDerating"))) for row in online_storage
    )
    raw_discharge_before_derating = sum(
        max(0.0, _finite_number(row.get("dischargePowerBeforeDerating"))) for row in online_storage
    )
    raw_charge = sum(max(0.0, _finite_number(row.get("chargePower"))) for row in online_storage)
    raw_discharge = sum(max(0.0, _finite_number(row.get("dischargePower"))) for row in online_storage)
    charge_derating_capacity = sum(
        max(0.0, _finite_number(row.get("maxChargePowerKw"))) for row in online_storage
    )
    discharge_derating_capacity = sum(
        max(0.0, _finite_number(row.get("maxDischargePowerKw"))) for row in online_storage
    )
    storage_charge_derating_factor = (
        sum(
            max(0.0, _finite_number(row.get("maxChargePowerKw")))
            * _clamp(_finite_number(row.get("chargeDeratingFactor")), 0.0, 1.0)
            for row in online_storage
        )
        / charge_derating_capacity
        if charge_derating_capacity > EPSILON
        else 1.0
    )
    storage_discharge_derating_factor = (
        sum(
            max(0.0, _finite_number(row.get("maxDischargePowerKw")))
            * _clamp(_finite_number(row.get("dischargeDeratingFactor")), 0.0, 1.0)
            for row in online_storage
        )
        / discharge_derating_capacity
        if discharge_derating_capacity > EPSILON
        else 1.0
    )
    storage_charge_derating_active = any(row.get("chargeDeratingActive") for row in online_storage)
    storage_discharge_derating_active = any(row.get("dischargeDeratingActive") for row in online_storage)
    converter_rows = _resolve_converter_capacities(converter_rows)

    measured_converters = [row for row in converter_rows if row.get("currentKw") is not None]
    converter_current = sum(_finite_number(row.get("currentKw")) for row in measured_converters) if measured_converters else None
    if converter_rows and len(measured_converters) != len(converter_rows):
        quality.add("部分在线功率控制型交直流变流器缺少有效实时有功，相关设备不参与本轮优化")
    if any(_finite_number(row.get("transferCapacityKw")) <= 0 for row in converter_rows):
        quality.add("部分在线功率控制型交直流变流器缺少有效容量边界，相关设备不参与本轮优化")
    converter_limit = _parallel_converter_limit(converter_rows)
    storage_power_capacity = max(raw_charge, raw_discharge)
    if converter_rows and math.isfinite(converter_limit):
        storage_power_capacity = (
            min(storage_power_capacity, converter_limit)
            if storage_power_capacity > EPSILON
            else converter_limit
        )
    converter_base_step_kw = (
        settings.converter_step_ratio * converter_limit
        if converter_rows and math.isfinite(converter_limit)
        else 0.0
    )
    if online_storage and not converter_rows and not renewable_storage_island:
        quality.add(
            "无在线功率控制型交直流变流器；交流侧设备仍可独立优化，直流分量按本地平衡约束处理",
        )
    if ac_side_fully_offline and not online_storage:
        quality.add(
            "交流侧全部退运且没有在线储能，相关优化岛将保持或闭锁",
            blocked=True,
        )
    if not online_diesel and not renewable_storage_island and not has_ac_grid_forming_storage:
        quality.add("没有在线柴油发电机或交流构网储能，优化器将由岛内其他构网电源或储能承担平衡")
    elif len(measured_diesel) != len(online_diesel):
        quality.add("部分在线柴油发电机缺少有效实时有功，相关柴油机不参与本轮优化")
    diesel_current_for_control = diesel_current if diesel_current is not None else diesel_min
    if online_storage and len(measured_storage) != len(online_storage):
        quality.add("部分在线储能缺少有效实时有功，相关储能不参与本轮优化")
    storage_current_for_control = (
        storage_current
        if storage_current is not None
        else -converter_current
        if converter_current is not None
        else 0.0
    )
    storage_charge_current_kw = max(0.0, -storage_current_for_control)
    storage_discharge_current_kw = max(0.0, storage_current_for_control)
    storage_charge_derating_excess_kw = max(0.0, storage_charge_current_kw - raw_charge)
    storage_discharge_derating_excess_kw = max(0.0, storage_discharge_current_kw - raw_discharge)
    storage_charge_derating_headroom_kw = max(0.0, raw_charge - storage_charge_current_kw)
    storage_discharge_derating_headroom_kw = max(0.0, raw_discharge - storage_discharge_current_kw)
    converter_current_for_control = (
        converter_current
        if converter_rows and converter_current is not None and len(measured_converters) == len(converter_rows)
        else -storage_current_for_control
        if converter_rows
        else 0.0
    )
    converter_reverse_power_detected = False
    diesel_down_margin = diesel_current_for_control - diesel_min
    diesel_floor_deficit_kw = max(0.0, diesel_min - diesel_current_for_control)
    diesel_deadband_entry_gap_kw = max(
        0.0,
        diesel_deadband_upper_kw - diesel_current_for_control,
    )
    diesel_floor_correction_request_kw = (
        min(
            diesel_deadband_entry_gap_kw,
            max(0.0, -converter_current_for_control),
        )
        if diesel_floor_deficit_kw > EPSILON
        else 0.0
    )
    diesel_up_margin = max(0.0, diesel_capacity - diesel_current_for_control) if diesel_capacity > EPSILON else 0.0
    storage_min_target = -raw_charge if converter_rows else storage_current_for_control
    storage_max_target = raw_discharge if converter_rows else storage_current_for_control
    converter_lower_target = sum(
        _converter_signed_bounds_kw(row)[0] for row in converter_rows
    )
    converter_upper_target = sum(
        _converter_signed_bounds_kw(row)[1] for row in converter_rows
    )
    if converter_rows and math.isfinite(converter_limit):
        # ACDC is an independent AC/DC coupling actuator, not a storage
        # inverter. Its signed target must be checked against its own
        # capacity, while storage SOC/power bounds remain local to storage.
        # Coupling the two aggregate targets here incorrectly assumes that
        # every storage-watt change must be supplied by ACDC, even when the
        # DC group can rebalance through local renewable output or load.
        if (
            converter_current_for_control < converter_lower_target - 0.001
            or converter_current_for_control > converter_upper_target + 0.001
        ):
            quality.add("交直流变流器实时有功已经超过并联容量边界，优化器将优先校正到物理边界")
        elif abs(converter_current_for_control) > EPSILON:
            # Preserve the legacy incremental capacity check only when the
            # converter is actually carrying power. A zero-power ACDC cannot
            # establish a storage/converter pairing for this projection.
            converter_storage_baseline = (
                storage_current_for_control + converter_current_for_control
            )
            converter_storage_min = converter_storage_baseline - converter_upper_target
            converter_storage_max = converter_storage_baseline - converter_lower_target
            storage_min_target = max(storage_min_target, converter_storage_min)
            storage_max_target = min(storage_max_target, converter_storage_max)
            if storage_min_target > storage_max_target + EPSILON:
                quality.add(
                    "旧投影策略的储能与变流器边界没有交集，最终指令改由逐岛优化可行性判定",
                )
                fallback_storage_target = _clamp(
                    storage_current_for_control,
                    -raw_charge,
                    raw_discharge,
                )
                storage_min_target = fallback_storage_target
                storage_max_target = fallback_storage_target
    total_charge = max(0.0, -storage_min_target) if converter_rows else 0.0
    total_discharge = max(0.0, storage_max_target) if converter_rows else 0.0
    renewable_balance_limit = 0.0
    diesel_control_region = (
        "high"
        if diesel_current_for_control > diesel_deadband_upper_kw + EPSILON
        else "low"
        if diesel_current_for_control < diesel_deadband_lower_kw - EPSILON
        else "deadband"
    )
    diesel_boundary_distance_kw = (
        diesel_floor_deficit_kw
        if diesel_control_region == "low"
        else max(0.0, diesel_current_for_control - diesel_deadband_upper_kw)
        if diesel_control_region == "high"
        else 0.0
    )
    lower_soc_deadband_active = (
        storage_soc is not None
        and storage_soc_lower_limit is not None
        and storage_soc_lower_limit - settings.soc_deadband - EPSILON
        <= storage_soc
        <= storage_soc_lower_limit + settings.soc_deadband + EPSILON
    )
    upper_soc_deadband_active = (
        storage_soc is not None
        and storage_soc_upper_limit is not None
        and storage_soc_upper_limit - settings.soc_deadband - EPSILON
        <= storage_soc
        <= storage_soc_upper_limit + settings.soc_deadband + EPSILON
    )
    diesel_deadband_active = diesel_control_region == "deadband"
    renewable_upper_boundary_distance = (
        max(0.0, storage_soc - storage_soc_upper_limit)
        if storage_soc is not None and storage_soc_upper_limit is not None
        else 0.0
    )
    renewable_storage_charge_excess_kw = max(
        0.0,
        -storage_current_for_control
        - grid_forming_storage_charge_protection_kw,
    )
    renewable_storage_charging_active = renewable_storage_charge_excess_kw > EPSILON
    renewable_recovery_boundary_scale = 1.0
    renewable_recovery_capacity_step_kw = sum(
        min(
            max(0.0, _finite_number(row.get("capacityKw")) - _finite_number(row.get("planningCurrentKw"))),
            settings.step_coefficient * max(0.0, _finite_number(row.get("capacityKw"))),
        )
        for row in online_renewable
        if row.get("commandable") and row.get("planningCurrentKw") is not None
    )
    renewable_recovery_derating_scale = (
        min(
            1.0,
            storage_charge_derating_headroom_kw / renewable_recovery_capacity_step_kw,
        )
        if storage_charge_derating_active and renewable_recovery_capacity_step_kw > EPSILON
        else 1.0
    )
    renewable_recovery_step_scale = min(
        renewable_recovery_boundary_scale,
        renewable_recovery_derating_scale,
    )
    renewable_recovery_effective_step_ratio = settings.step_coefficient * renewable_recovery_step_scale
    renewable_recovery_step_request_kw = sum(
        min(
            max(0.0, _finite_number(row.get("capacityKw")) - _finite_number(row.get("planningCurrentKw"))),
            renewable_recovery_effective_step_ratio * max(0.0, _finite_number(row.get("capacityKw"))),
        )
        for row in online_renewable
        if row.get("commandable") and row.get("planningCurrentKw") is not None
    )
    renewable_curtail_base_steps = {
        (row["dev_type"], row["dev_name"]): min(
            max(0.0, _finite_number(row.get("planningCurrentKw"))),
            settings.step_coefficient * max(0.0, _finite_number(row.get("capacityKw"))),
        )
        for row in online_renewable
        if row.get("commandable") and row.get("planningCurrentKw") is not None
    }
    renewable_commandable_rows = [
        row
        for row in online_renewable
        if row.get("commandable") and row.get("planningCurrentKw") is not None
    ]
    renewable_commandable_current_kw = sum(
        max(0.0, _finite_number(row.get("planningCurrentKw")))
        for row in renewable_commandable_rows
    )
    renewable_curtail_capacity_step_kw = sum(renewable_curtail_base_steps.values())
    renewable_curtail_step_request_kw = min(
        renewable_curtail_capacity_step_kw,
        renewable_storage_charge_excess_kw,
    )
    renewable_curtail_step_scale = (
        renewable_curtail_step_request_kw / renewable_curtail_capacity_step_kw
        if renewable_curtail_capacity_step_kw > EPSILON
        else 0.0
    )
    renewable_curtail_effective_step_ratio = settings.step_coefficient * renewable_curtail_step_scale
    renewable_derating_curtail_step_request_kw = min(
        renewable_curtail_capacity_step_kw,
        storage_charge_derating_excess_kw,
    )
    renewable_derating_curtail_step_scale = (
        renewable_derating_curtail_step_request_kw / renewable_curtail_capacity_step_kw
        if renewable_curtail_capacity_step_kw > EPSILON
        else 0.0
    )
    # 仅在柴发已跌破最小出力下限或储能无剩余充电空间时，才启用柴发保护限电启发式；
    # 柴发合规运行在保护带内且电池仍有充电空间时，交由逐岛优化器统筹新能源恢复与储能充电，避免限电死锁与倒弃绿电。
    has_storage_charge_headroom = any(
        row.get("online")
        and row.get("commandable")
        and row.get("socConstraint") != "above_upper"
        and _finite_number(row.get("chargePower")) - max(0.0, -_finite_number(row.get("currentKw"))) > EPSILON
        for row in storage_rows
    )
    renewable_raise_blocked_by_diesel_guard = bool(
        not renewable_storage_island
        and storage_soc is not None
        and storage_soc_lower_limit is not None
        and storage_soc > storage_soc_lower_limit + EPSILON
        and (
            diesel_current_for_control < diesel_min - EPSILON
            or (
                diesel_current_for_control < diesel_deadband_upper_kw - EPSILON
                and not has_storage_charge_headroom
            )
        )
    )
    renewable_curtailment_required_by_charging = bool(
        renewable_raise_blocked_by_diesel_guard
        and storage_charge_current_kw > EPSILON
        and (
            diesel_current_for_control < diesel_min - EPSILON
            or storage_soc_region in {"high_guard", "above_upper"}
        )
    )
    renewable_diesel_guard_curtail_request_kw = (
        min(renewable_curtail_capacity_step_kw, storage_charge_current_kw)
        if renewable_curtailment_required_by_charging
        else 0.0
    )
    renewable_diesel_guard_curtail_scale = (
        renewable_diesel_guard_curtail_request_kw
        / renewable_curtail_capacity_step_kw
        if renewable_curtail_capacity_step_kw > EPSILON
        else 0.0
    )
    high_soc_guard = storage_soc_region in {"high_guard", "above_upper"}
    soc_at_or_above_upper = (
        storage_soc is not None
        and storage_soc_upper_limit is not None
        and storage_soc >= storage_soc_upper_limit - EPSILON
    )
    soc_at_or_below_lower = (
        storage_soc is not None
        and storage_soc_lower_limit is not None
        and storage_soc <= storage_soc_lower_limit + EPSILON
    )
    storage_control_action = "hold"
    raw_converter_desired_target = converter_current_for_control
    emergency_charge_requested = bool(soc_below_lower_deadband)
    diesel_emergency_charge_allowed = False
    if renewable_storage_island and converter_rows:
        raw_converter_desired_target = 0.0
        storage_control_action = (
            "stop_acdc_export_renewable_storage_island"
            if converter_current_for_control < -EPSILON
            else "hold_acdc_zero_renewable_storage_island"
        )
    elif not converter_rows or storage_soc is None:
        storage_control_action = "hold"
    elif soc_below_lower_deadband:
        raw_converter_desired_target = 0.0
        storage_control_action = (
            "stop_discharge_below_soc_lower_deadband"
            if converter_current_for_control < -EPSILON
            else "reverse_power_forbidden_below_soc_lower_deadband"
        )
    elif soc_at_or_below_lower:
        raw_converter_desired_target = 0.0
        storage_control_action = (
            "stop_discharge_at_soc_lower"
            if converter_current_for_control < -EPSILON
            else "stop_reverse_power_at_soc_lower"
            if converter_current_for_control > EPSILON
            else "hold_at_soc_lower"
        )
    elif soc_above_upper_deadband and diesel_control_region != "low":
        high_soc_diesel_margin_kw = max(0.0, diesel_down_margin)
        raw_converter_desired_target = max(
            converter_lower_target,
            converter_current_for_control - high_soc_diesel_margin_kw,
        )
        storage_control_action = (
            "increase_discharge_above_soc_upper_deadband"
            if raw_converter_desired_target < converter_current_for_control - EPSILON
            else "hold_at_diesel_floor_above_soc_upper_deadband"
        )
    elif diesel_control_region == "low":
        raw_converter_desired_target = min(
            0.0,
            converter_current_for_control + diesel_floor_correction_request_kw,
        )
        storage_control_action = (
            "reduce_discharge_low_diesel"
            if diesel_floor_correction_request_kw > EPSILON
            else "stop_reverse_power_low_diesel"
            if converter_current_for_control > EPSILON
            else "hold_low_diesel"
        )
    elif diesel_control_region == "deadband":
        raw_converter_desired_target = converter_current_for_control
        storage_control_action = "hold"
    elif soc_at_or_above_upper:
        if converter_current_for_control > EPSILON:
            raw_converter_desired_target = 0.0
            storage_control_action = "stop_reverse_power_at_soc_upper"
        else:
            raw_converter_desired_target = max(
                converter_lower_target,
                converter_current_for_control - max(0.0, diesel_down_margin),
            )
            storage_control_action = "increase_discharge"
    elif diesel_control_region == "high":
        raw_converter_desired_target = max(
            converter_lower_target,
            converter_current_for_control - max(0.0, diesel_down_margin),
        )
        storage_control_action = "increase_discharge"

    if converter_reverse_power_detected and raw_converter_desired_target >= -EPSILON:
        storage_control_action = "stop_reverse_power"

    bounded_raw_converter_desired_target = _clamp(
        raw_converter_desired_target,
        converter_lower_target,
        converter_upper_target,
    )
    converter_hard_limit_applied = converter_reverse_power_detected or (
        abs(bounded_raw_converter_desired_target - raw_converter_desired_target) > 0.001
    )

    raw_desired_storage_target = (
        storage_current_for_control
        + converter_current_for_control
        - bounded_raw_converter_desired_target
        if converter_rows
        else storage_current_for_control
    )
    desired_storage_target = _clamp(
        raw_desired_storage_target,
        storage_min_target,
        storage_max_target,
    )
    unbounded_storage_constrained_converter_target = (
        storage_current_for_control
        + converter_current_for_control
        - desired_storage_target
        if converter_rows
        else 0.0
    )
    storage_constrained_converter_target = _clamp(
        unbounded_storage_constrained_converter_target,
        converter_lower_target,
        converter_upper_target,
    )
    converter_hard_limit_applied = converter_hard_limit_applied or (
        abs(
            storage_constrained_converter_target
            - unbounded_storage_constrained_converter_target
        )
        > 0.001
    )
    strategy_converter_delta = (
        bounded_raw_converter_desired_target - converter_current_for_control
    )
    storage_constrained_converter_delta = (
        storage_constrained_converter_target - converter_current_for_control
    )
    storage_charge_derating_candidate_limited = bool(
        storage_charge_derating_active
        and raw_desired_storage_target < storage_min_target - EPSILON
    )
    storage_discharge_derating_candidate_limited = bool(
        storage_discharge_derating_active
        and raw_desired_storage_target > storage_max_target + EPSILON
    )
    converter_storage_constraint_conflict = bool(
        abs(storage_constrained_converter_delta) > EPSILON
        and (
            abs(strategy_converter_delta) <= EPSILON
            or (
                strategy_converter_delta > EPSILON
                and storage_constrained_converter_delta < -EPSILON
            )
            or (
                strategy_converter_delta < -EPSILON
                and storage_constrained_converter_delta > EPSILON
            )
        )
    )
    converter_charge_safety_target = _clamp(
        storage_current_for_control + converter_current_for_control + raw_charge,
        converter_lower_target,
        converter_upper_target,
    )
    converter_charge_safety_storage_kw = (
        storage_current_for_control
        + converter_current_for_control
        - converter_charge_safety_target
    )
    storage_charge_derating_acdc_request_kw = max(
        0.0,
        converter_current_for_control - converter_charge_safety_target,
    )
    storage_charge_derating_acdc_allowed = bool(
        storage_charge_derating_acdc_request_kw > EPSILON
        and storage_charge_derating_acdc_request_kw <= diesel_down_margin + EPSILON
        and converter_charge_safety_storage_kw >= -raw_charge - EPSILON
    )
    storage_derating_constraint_override = False
    storage_charge_derating_actuator = "none"
    storage_discharge_derating_actuator = "none"
    if storage_discharge_derating_candidate_limited:
        converter_desired_target = storage_constrained_converter_target
        storage_derating_constraint_override = converter_storage_constraint_conflict
        storage_discharge_derating_actuator = "acdc"
    elif storage_charge_derating_candidate_limited and storage_charge_derating_acdc_allowed:
        converter_desired_target = storage_constrained_converter_target
        storage_derating_constraint_override = converter_storage_constraint_conflict
        storage_charge_derating_actuator = "acdc"
    elif storage_charge_derating_candidate_limited:
        converter_desired_target = bounded_raw_converter_desired_target
        storage_charge_derating_actuator = "renewable"
    else:
        converter_desired_target = (
            bounded_raw_converter_desired_target
            if converter_storage_constraint_conflict
            else storage_constrained_converter_target
        )
    if renewable_storage_island:
        converter_desired_target = 0.0
        storage_derating_constraint_override = False
        storage_charge_derating_actuator = (
            "renewable"
            if storage_charge_derating_candidate_limited or storage_charge_derating_excess_kw > EPSILON
            else "none"
        )
        storage_discharge_derating_actuator = "none"
    converter_step_direction = (
        "increase"
        if converter_desired_target > converter_current_for_control + EPSILON
        else "decrease"
        if converter_desired_target < converter_current_for_control - EPSILON
        else "hold"
    )
    # p_ac_set is positive from AC to DC, so a smaller target increases
    # physical DC-to-AC export.
    converter_export_step_direction = (
        "increase_export"
        if converter_desired_target < converter_current_for_control - EPSILON
        else "decrease_export"
        if converter_desired_target > converter_current_for_control + EPSILON
        else "hold"
    )
    diesel_boundary_action_toward_hold = (
        diesel_control_region == "low"
        and storage_control_action == "reduce_discharge_low_diesel"
        and converter_step_direction == "decrease"
    ) or (
        diesel_control_region == "high"
        and storage_control_action == "increase_discharge"
        and converter_step_direction == "increase"
    )
    diesel_boundary_approach_active = bool(
        diesel_boundary_action_toward_hold
        and converter_base_step_kw > EPSILON
        and diesel_boundary_distance_kw <= converter_base_step_kw + EPSILON
    )
    converter_slow_export_increase = False
    converter_emergency_stop_active = bool(
        soc_below_lower_deadband
        and converter_export_step_direction == "decrease_export"
    )
    converter_island_zero_override = bool(
        renewable_storage_island
        and converter_rows
        and abs(converter_current_for_control) > EPSILON
    )
    converter_step_scale = 1.0
    converter_step_kw = converter_base_step_kw * converter_step_scale
    normal_stepped_converter_target = (
        converter_desired_target
        if converter_emergency_stop_active or converter_island_zero_override
        else _move_toward(converter_current_for_control, converter_desired_target, converter_step_kw)
        if converter_rows
        else 0.0
    )
    converter_charge_derating_safety_override = bool(
        storage_charge_derating_excess_kw > EPSILON
        and storage_charge_derating_acdc_allowed
        and normal_stepped_converter_target > converter_charge_safety_target + EPSILON
    )
    stepped_converter_target = (
        converter_charge_safety_target
        if converter_charge_derating_safety_override
        else normal_stepped_converter_target
    )
    converter_target = _clamp(
        stepped_converter_target,
        converter_lower_target,
        converter_upper_target,
    )
    converter_hard_limit_applied = converter_hard_limit_applied or (
        abs(converter_target - stepped_converter_target) > 0.001
    )
    converter_applied_step_kw = abs(converter_target - converter_current_for_control)
    storage_target = (
        storage_current_for_control + converter_current_for_control - converter_target
        if converter_rows
        else storage_current_for_control
    )
    storage_predicted_charge_after_acdc_kw = max(0.0, -storage_target)
    storage_charge_derating_residual_kw = max(
        0.0,
        storage_predicted_charge_after_acdc_kw - raw_charge,
    )
    storage_high_soc_discharge_request_kw = (
        min(
            renewable_curtail_capacity_step_kw,
            max(
                0.0,
                renewable_commandable_current_kw - storage_charge_derating_residual_kw,
            ),
        )
        if soc_above_upper_deadband and storage_target <= EPSILON
        else 0.0
    )
    renewable_charge_safety_curtail_required_kw = (
        storage_charge_derating_residual_kw + storage_high_soc_discharge_request_kw
    )
    renewable_charge_safety_curtail_request_kw = min(
        renewable_commandable_current_kw,
        renewable_charge_safety_curtail_required_kw,
    )
    renewable_charge_safety_allocations = _allocate(
        renewable_commandable_rows,
        renewable_charge_safety_curtail_request_kw,
        "planningCurrentKw",
    )
    renewable_charge_safety_by_device = {
        (row["dev_type"], row["dev_name"]): amount
        for row, amount in zip(renewable_commandable_rows, renewable_charge_safety_allocations)
    }
    renewable_charge_safety_curtail_delivered_kw = sum(renewable_charge_safety_allocations)
    renewable_charge_safety_curtail_shortfall_kw = max(
        0.0,
        renewable_charge_safety_curtail_required_kw
        - renewable_charge_safety_curtail_delivered_kw,
    )
    storage_charge_derating_safety_override = bool(
        renewable_charge_safety_curtail_required_kw > EPSILON
        or converter_charge_derating_safety_override
    )
    if storage_charge_derating_excess_kw > EPSILON and storage_charge_derating_actuator == "none":
        storage_charge_derating_actuator = (
            "acdc"
            if converter_target < converter_current_for_control - EPSILON
            else "renewable"
        )
    if storage_discharge_derating_excess_kw > EPSILON and storage_discharge_derating_actuator == "none":
        storage_discharge_derating_actuator = "acdc"
    storage_candidate_target = desired_storage_target
    storage_deadband_action = storage_control_action
    converter_step_limited = (
        abs(converter_target - converter_desired_target)
        > settings.optimization_bound_tolerance_kw
    )

    # The ACDC and renewable controllers are independent feedback loops. Keep
    # the legacy metrics at zero for API compatibility, but do not use them to
    # replace, absorb, scale, or otherwise combine the two strategies.
    renewable_discharge_replacement_kw = 0.0
    renewable_absorption_required_kw = 0.0
    storage_renewable_coordination_kw = 0.0
    renewable_storage_coordination_active = False
    high_soc_storage_balance_limit_kw = 0.0
    high_soc_storage_balance_limited = False
    high_soc_required_curtail_kw = 0.0

    if renewable_storage_island:
        if storage_soc is None or storage_soc_upper_limit is None:
            renewable_control_action = "hold_unknown_soc"
        elif storage_soc >= storage_soc_upper_limit - EPSILON:
            renewable_control_action = "curtail_one_step_storage_island_full_soc"
        elif raw_charge <= EPSILON:
            renewable_control_action = "curtail_one_step_storage_island_no_charge_capacity"
        elif storage_charge_derating_residual_kw > EPSILON:
            renewable_control_action = "curtail_charge_safety"
        else:
            renewable_control_action = "recover_one_step_storage_island"
    elif storage_soc is None or storage_soc_upper_limit is None:
        renewable_control_action = "hold_unknown_soc"
    elif soc_below_lower_deadband:
        renewable_control_action = "recover_one_step_below_soc_lower_deadband"
    elif soc_above_upper_deadband:
        renewable_control_action = (
            "curtail_charge_safety"
            if renewable_charge_safety_curtail_required_kw > EPSILON
            else "hold_above_soc_upper_deadband_while_acdc_discharges"
            if storage_target > EPSILON
            else "curtail_one_step_above_soc_upper_deadband"
        )
    elif storage_charge_derating_residual_kw > EPSILON:
        renewable_control_action = "curtail_charge_safety"
    elif (
        storage_charge_derating_excess_kw > EPSILON
        and storage_charge_derating_actuator == "renewable"
    ):
        renewable_control_action = "curtail_one_step_charge_derating"
    elif (
        storage_charge_derating_excess_kw > EPSILON
        and storage_charge_derating_actuator == "acdc"
    ):
        renewable_control_action = "hold_charge_derating_while_acdc_corrects"
    elif renewable_curtailment_required_by_charging:
        renewable_control_action = "curtail_one_step_low_diesel_charging"
    elif renewable_raise_blocked_by_diesel_guard:
        renewable_control_action = "hold_low_diesel_no_charge"
    elif storage_soc < storage_soc_upper_limit - EPSILON:
        renewable_control_action = "recover_one_step"
    elif (
        renewable_storage_charging_active
        and diesel_current_for_control <= diesel_min + diesel_deadband_kw + EPSILON
    ):
        renewable_control_action = "curtail_one_step_full_soc"
    elif renewable_storage_charging_active:
        renewable_control_action = "hold_full_soc_high_diesel_charging"
    elif diesel_current_for_control <= diesel_min + diesel_deadband_kw + EPSILON:
        renewable_control_action = "hold_full_soc_no_charge"
    else:
        renewable_control_action = "recover_one_step"

    renewable_step_direction = (
        "increase"
        if renewable_control_action in {
            "recover_one_step",
            "recover_one_step_below_soc_lower_deadband",
            "recover_one_step_storage_island",
        }
        else "decrease"
        if renewable_control_action in {
            "curtail_one_step_full_soc",
            "curtail_one_step_storage_island_full_soc",
            "curtail_one_step_storage_island_no_charge_capacity",
            "curtail_one_step_above_soc_upper_deadband",
            "curtail_one_step_charge_derating",
            "curtail_one_step_low_diesel_charging",
            "curtail_charge_safety",
        }
        else "hold"
    )
    renewable_step_scale = (
        1.0
        if renewable_control_action in {
            "recover_one_step_below_soc_lower_deadband",
            "curtail_one_step_above_soc_upper_deadband",
            "curtail_one_step_storage_island_full_soc",
            "curtail_one_step_storage_island_no_charge_capacity",
        }
        else renewable_recovery_step_scale
        if renewable_control_action in {"recover_one_step", "recover_one_step_storage_island"}
        else renewable_curtail_step_scale
        if renewable_control_action == "curtail_one_step_full_soc"
        else renewable_derating_curtail_step_scale
        if renewable_control_action == "curtail_one_step_charge_derating"
        else renewable_diesel_guard_curtail_scale
        if renewable_control_action == "curtail_one_step_low_diesel_charging"
        else (
            renewable_charge_safety_curtail_delivered_kw
            / renewable_curtail_capacity_step_kw
        )
        if renewable_control_action == "curtail_charge_safety"
        and renewable_curtail_capacity_step_kw > EPSILON
        else 0.0
    )
    renewable_effective_step_ratio = settings.step_coefficient * renewable_step_scale
    renewable_target_by_device: Dict[Tuple[str, str], Optional[float]] = {}
    for row in online_renewable:
        key = (row["dev_type"], row["dev_name"])
        if row.get("planningCurrentKw") is None:
            renewable_target_by_device[key] = None
            continue
        current_kw = _finite_number(row.get("planningCurrentKw"))
        capacity_kw = max(0.0, _finite_number(row.get("capacityKw")))
        step_kw = renewable_effective_step_ratio * capacity_kw
        if not row.get("commandable"):
            renewable_target_by_device[key] = current_kw
            continue
        elif renewable_control_action == "curtail_charge_safety":
            target_kw = max(
                0.0,
                current_kw - renewable_charge_safety_by_device.get(key, 0.0),
            )
        elif renewable_control_action in {
            "curtail_one_step_above_soc_upper_deadband",
            "curtail_one_step_storage_island_full_soc",
            "curtail_one_step_storage_island_no_charge_capacity",
        }:
            target_kw = max(0.0, current_kw - step_kw)
        elif renewable_control_action == "curtail_one_step_full_soc":
            target_kw = max(
                0.0,
                current_kw
                - renewable_curtail_base_steps.get(key, 0.0) * renewable_curtail_step_scale,
            )
        elif renewable_control_action == "curtail_one_step_charge_derating":
            target_kw = max(
                0.0,
                current_kw
                - renewable_curtail_base_steps.get(key, 0.0)
                * renewable_derating_curtail_step_scale,
            )
        elif renewable_control_action == "curtail_one_step_low_diesel_charging":
            target_kw = max(
                0.0,
                current_kw
                - renewable_curtail_base_steps.get(key, 0.0)
                * renewable_diesel_guard_curtail_scale,
            )
        elif renewable_control_action in {
            "recover_one_step",
            "recover_one_step_below_soc_lower_deadband",
            "recover_one_step_storage_island",
        }:
            target_kw = min(capacity_kw, current_kw + step_kw)
        else:
            target_kw = current_kw
        renewable_target_by_device[key] = _clamp(target_kw, 0.0, capacity_kw) if capacity_kw > EPSILON else 0.0

    # Preserve the first-stage diesel/SOC decision as a hard renewable upper
    # bound for every later topology repair and optimization pass.
    if renewable_raise_blocked_by_diesel_guard:
        for row in online_renewable:
            key = (row["dev_type"], row["dev_name"])
            current_kw = _number(row.get("planningCurrentKw"))
            target_kw = _number(renewable_target_by_device.get(key))
            if current_kw is None:
                continue
            row["dispatchUpperKw"] = min(
                current_kw,
                target_kw if target_kw is not None else current_kw,
            )
            row["dispatchUpperReason"] = (
                "diesel_guard_storage_charging_curtailment"
                if renewable_curtailment_required_by_charging
                else "diesel_guard_no_renewable_recovery"
            )

    # 双层融合自然资源上限判断（对全部在线新能源含次孤岛统一生效，并识别潮流回溯拍冻结失配计数）
    all_online_renewable_for_limits = [
        row for row in renewable_rows if row.get("online")
    ]
    compute_block = snapshot.get("compute") if isinstance(snapshot.get("compute"), Mapping) else {}
    boundary_backtracked = bool(compute_block.get("boundary_backtracked"))
    renewable_natural_limit_diagnostics = _apply_renewable_natural_upper_bounds(
        all_online_renewable_for_limits,
        renewable_target_by_device,
        settings,
        runtime_memory=runtime_memory,
        sim_time_seconds=sim_time_seconds,
        wind_measurement_status=wind_measurement_status,
        solar_measurement_status=solar_measurement_status,
        diesel_guard_blocked=bool(renewable_raise_blocked_by_diesel_guard),
        boundary_backtracked=boundary_backtracked,
    )

    island_component_plans: List[Dict[str, Any]] = []
    island_control_action_by_component: Dict[Tuple[str, str], str] = {}
    island_control_action_by_resource: Dict[Tuple[str, str], str] = {}
    island_control_action_by_converter: Dict[Tuple[str, str], str] = {}
    secondary_island_converter_rows: List[Mapping[str, Any]] = []
    if primary_island_component is not None:
        primary_plan = _plan_renewable_storage_island_component(
            primary_island_component,
            settings,
        )
        primary_targets = {
            (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): renewable_target_by_device.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            )
            for row in primary_island_component.renewable_rows
        }
        primary_plan["action"] = renewable_control_action
        primary_plan["renewableTargets"] = primary_targets
        primary_plan["renewableTargetKw"] = sum(
            _finite_number(target) for target in primary_targets.values()
        )
        island_component_plans.append(primary_plan)

        for component in island_components:
            component_key = (
                component.grid_component_id,
                component.dc_transfer_group_id,
            )
            component_plan = (
                primary_plan
                if component is primary_island_component
                else _plan_renewable_storage_island_component(component, settings)
            )
            action = str(component_plan["action"])
            island_control_action_by_component[component_key] = action
            for row in component.renewable_rows:
                resource_key = (
                    str(row.get("dev_type", "")),
                    str(row.get("dev_name", "")),
                )
                island_control_action_by_resource[resource_key] = action
            for row in component.converter_rows:
                converter_key = (
                    str(row.get("dev_type", "")),
                    str(row.get("dev_name", "")),
                )
                island_control_action_by_converter[converter_key] = action

            if component is primary_island_component:
                continue
            renewable_target_by_device.update(component_plan["renewableTargets"])
            island_component_plans.append(component_plan)
            secondary_island_converter_rows.extend(component.converter_rows)

    renewable_target = sum(_finite_number(value) for value in renewable_target_by_device.values())
    renewable_delta = renewable_target - renewable_current
    storage_delta = storage_target - storage_current_for_control

    base_converter_direction = (
        1.0 if converter_target > 0 else -1.0 if converter_target < 0 else 0.0
    )
    base_converter_allocations = [
        value * base_converter_direction
        for value in _allocate_converters(converter_rows, abs(converter_target))
    ]
    converter_target = sum(base_converter_allocations) if converter_rows else 0.0
    base_converter_targets: Dict[Tuple[str, str], float] = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): allocation_kw
        for row, allocation_kw in zip(converter_rows, base_converter_allocations)
    }
    for row in secondary_island_converter_rows:
        base_converter_targets[
            (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        ] = 0.0
    for row in held_converter_rows:
        current_kw = _number(row.get("currentKw"))
        base_converter_targets[
            (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        ] = (
            _clamp_converter_target_kw(row, current_kw)
            if current_kw is not None
            else 0.0
        )
    for row in all_converter_rows:
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        current_kw = _number(row.get("currentKw"))
        base_converter_targets.setdefault(
            key,
            _clamp_converter_target_kw(row, current_kw)
            if current_kw is not None
            else 0.0,
        )
    base_converter_effect_kw = sum(
        _converter_ac_injection_delta_kw(
            row,
            current_kw,
            base_converter_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                current_kw,
            ),
        )
        for row in all_converter_rows
        if (current_kw := _number(row.get("currentKw"))) is not None
    )

    direct_storage_plan = _plan_direct_grid_storage_dispatch(
        storage_rows,
        all_converter_rows,
        base_converter_targets,
        settings,
        diesel_current_kw=diesel_current_for_control,
        diesel_min_kw=diesel_min,
        diesel_deadband_upper_kw=diesel_deadband_upper_kw,
        balance_effect_kw=base_converter_effect_kw,
        enabled=bool(online_diesel) and not renewable_storage_island,
    )
    direct_storage_states = direct_storage_plan["storageStates"]
    direct_storage_targets = direct_storage_plan["storageTargets"]
    final_converter_targets = {
        **base_converter_targets,
        **direct_storage_plan["converterTargets"],
    }
    # 常规并网模式下优化器（optimize_topology_islands）统一接管全部设备最终目标，
    # 原启发式 _side_aware_renewable_recovery_plan 的结果会在后续被全盘覆写，直接跳过以消除每轮 ~4 ms 冗余计算。
    side_aware_plan: Optional[Dict[str, Any]] = None
    projected_balance_targets: Dict[Tuple[str, str], float] = {}
    _ac_load_for_dispatch_validation, dc_load_for_dispatch_validation = (
        _active_load_budgets(
            snapshot,
            measurements,
            resource_topology.dc_transfer_groups,
        )
    )
    direct_grid_forming_plan = _plan_direct_grid_forming_dispatch(
        renewable_rows,
        storage_rows,
        all_converter_rows,
        renewable_target_by_device,
        direct_storage_targets,
        final_converter_targets,
        projected_balance_targets,
        settings,
        diesel_current_kw=diesel_current_for_control,
        diesel_min_kw=diesel_min,
        diesel_deadband_upper_kw=diesel_deadband_upper_kw,
        enabled=bool(
            online_diesel
            or renewable_storage_island
            or operating_mode == "grid_forming_storage_reference"
        ),
        dc_load_kw=dc_load_for_dispatch_validation,
    )
    renewable_target_by_device = direct_grid_forming_plan["renewableTargets"]
    renewable_target = sum(
        _finite_number(value) for value in renewable_target_by_device.values()
    )
    renewable_delta = renewable_target - renewable_current
    direct_storage_targets = direct_grid_forming_plan["gridStorageTargets"]
    for key, state in direct_storage_states.items():
        state["targetKw"] = direct_storage_targets.get(
            key,
            state.get("targetKw", state.get("currentKw")),
        )
    projected_balance_targets = direct_grid_forming_plan["balanceTargets"]
    projected_balance_targets = _clamp_direct_balance_targets_to_soc_bounds(
        storage_rows,
        projected_balance_targets,
    )
    direct_grid_forming_states = direct_grid_forming_plan["balanceStates"]
    final_converter_targets = direct_grid_forming_plan["converterTargets"]
    component_dispatch_plan = _validate_dispatch_by_ac_component(
        resource_topology,
        diesel_rows,
        renewable_rows,
        storage_rows,
        converter_validation_rows,
        renewable_target_by_device,
        direct_storage_targets,
        projected_balance_targets,
        final_converter_targets,
        settings,
        dc_load_kw=dc_load_for_dispatch_validation,
    )
    renewable_target_by_device = component_dispatch_plan["renewableTargets"]
    direct_storage_targets = component_dispatch_plan["gridStorageTargets"]
    projected_balance_targets = component_dispatch_plan["balanceTargets"]
    final_converter_targets = component_dispatch_plan["converterTargets"]
    projected_balance_targets, final_converter_targets, dc_projection_groups = (
        _rebalance_dc_projection_targets(
            resource_topology,
            renewable_rows,
            storage_rows,
            converter_validation_rows,
            renewable_target_by_device,
            direct_storage_targets,
            projected_balance_targets,
            final_converter_targets,
            dc_load_kw=dc_load_for_dispatch_validation,
        )
    )
    component_dispatch_plan["balanceTargets"] = projected_balance_targets
    component_dispatch_plan["dcGroups"] = dc_projection_groups

    # A DC-group repair may restore an ACDC target that AC-component
    # validation had temporarily rolled back. Refresh the AC-component
    # prediction from the targets that will actually be published; otherwise
    # diesel metrics and diesel commands can describe the pre-repair target.
    original_converter_targets = component_dispatch_plan.get(
        "converterTargets", {}
    )
    converter_target_changed = any(
        abs(
            _finite_number(final_converter_targets.get(key))
            - _finite_number(original_converter_targets.get(key))
        )
        > EPSILON
        for key in set(final_converter_targets) | set(original_converter_targets)
    )
    if converter_target_changed:
        refreshed_component_dispatch = _validate_dispatch_by_ac_component(
            resource_topology,
            diesel_rows,
            renewable_rows,
            storage_rows,
            converter_validation_rows,
            renewable_target_by_device,
            direct_storage_targets,
            projected_balance_targets,
            final_converter_targets,
            settings,
            dc_load_kw=dc_load_for_dispatch_validation,
        )
        component_dispatch_plan = refreshed_component_dispatch
        renewable_target_by_device = refreshed_component_dispatch["renewableTargets"]
        direct_storage_targets = refreshed_component_dispatch["gridStorageTargets"]
        projected_balance_targets = refreshed_component_dispatch["balanceTargets"]
        final_converter_targets = refreshed_component_dispatch["converterTargets"]
        component_dispatch_plan["dcGroups"] = dc_projection_groups

    ac_to_dc_absorption_plan = _apply_ac_to_dc_renewable_absorption(
        resource_topology,
        renewable_rows,
        storage_rows,
        all_converter_rows,
        renewable_target_by_device,
        direct_storage_targets,
        final_converter_targets,
        settings,
    )
    renewable_target_by_device = ac_to_dc_absorption_plan["renewableTargets"]
    direct_storage_targets = ac_to_dc_absorption_plan["storageTargets"]
    final_converter_targets = ac_to_dc_absorption_plan["converterTargets"]
    renewable_target = sum(
        _finite_number(value) for value in renewable_target_by_device.values()
    )
    renewable_delta = renewable_target - renewable_current
    for key, state in direct_storage_states.items():
        state["targetKw"] = direct_storage_targets.get(
            key,
            state.get("targetKw", state.get("currentKw")),
        )
    for key, state in direct_grid_forming_states.items():
        state["targetKw"] = projected_balance_targets.get(
            key,
            state.get("targetKw", state.get("currentKw")),
        )
    direct_grid_forming_plan["dieselEffectKw"] = component_dispatch_plan[
        "dieselEffectKw"
    ]
    direct_grid_forming_plan["dieselTargetKw"] = component_dispatch_plan[
        "dieselTargetKw"
    ]
    direct_grid_forming_plan["balanceTargets"] = projected_balance_targets
    direct_grid_forming_plan["dcGroups"] = component_dispatch_plan["dcGroups"]
    direct_converter_groups = {
        str(row.get("dcTransferGroupId", ""))
        for row in all_converter_rows
        if row.get("commandable")
        and str(row.get("dcTransferGroupId", ""))
        and _number(row.get("currentKw")) is not None
        and (_number(row.get("transferCapacityKw")) or 0.0) > EPSILON
    }
    for state in direct_storage_states.values():
        direct_dispatch_eligible = bool(
            state.get("eligible")
            and (
                state.get("side") == "AC"
                or state.get("side") == "DC"
                and state.get("groupId") in direct_converter_groups
            )
        )
        state["directDispatchEligible"] = direct_dispatch_eligible
        if (
            state.get("side") == "DC"
            and state.get("eligible")
            and not direct_dispatch_eligible
        ):
            row = state["row"]
            quality.add(
                f"直流跟网储能{row.get('dev_name', '')}缺少本传输组有效ACDC容量，"
                "本轮仅禁用该储能直接调节"
            )

    direct_ac_storage_effect_kw = _finite_number(
        direct_storage_plan.get("acEffectKw")
    )
    direct_acdc_effect_kw = _finite_number(
        direct_storage_plan.get("acdcEffectKw")
    )
    if side_aware_plan is not None:
        direct_ac_storage_effect_kw = sum(
            _finite_number(target_kw)
            - _finite_number(
                next(
                    row.get("currentKw")
                    for row in storage_rows
                    if (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
                    == key
                )
            )
            for key, target_kw in direct_storage_targets.items()
            if next(
                row.get("connectionSide")
                for row in storage_rows
                if (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
                == key
            )
            == "AC"
        )
        direct_acdc_effect_kw = sum(
            _finite_number(row.get("currentKw"))
            - _finite_number(
                final_converter_targets.get(
                    (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                    row.get("currentKw"),
                )
            )
            for row in all_converter_rows
            if row.get("currentKw") is not None
        )
    if renewable_storage_island:
        current_diesel_violation = 0.0
        candidate_effect = 0.0
        predicted_diesel = 0.0
        diesel_target = 0.0
        diesel_residual = 0.0
        diesel_boundary_error = 0.0
        predicted_diesel_violation = 0.0
        diesel_violation_improved = True
        diesel_validation_status = "not_applicable"
    else:
        current_diesel_violation = _diesel_boundary_violation(
            diesel_current_for_control,
            diesel_min,
            diesel_capacity,
        )
        candidate_effect = _finite_number(
            direct_grid_forming_plan.get("dieselEffectKw")
        )
        predicted_diesel = diesel_current_for_control - candidate_effect
        diesel_target = _finite_number(
            direct_grid_forming_plan.get("dieselTargetKw"),
            predicted_diesel,
        )
        diesel_residual = diesel_target
        diesel_boundary_error = diesel_target - diesel_min
        predicted_diesel_violation = _diesel_boundary_violation(diesel_target, diesel_min, diesel_capacity)
        diesel_violation_improved = (
            predicted_diesel_violation + 0.001 < current_diesel_violation
            if current_diesel_violation > 0.001
            else predicted_diesel_violation <= 0.001
        )
        if predicted_diesel_violation <= 0.001:
            diesel_validation_status = "within_bounds"
        elif current_diesel_violation > 0.001 and diesel_violation_improved:
            diesel_validation_status = "improved"
        else:
            diesel_validation_status = "feedback_pending"
    unserved_kw = 0.0
    surplus_kw = 0.0

    storage_allocations = (
        [-value for value in _allocate(online_storage, -storage_target, "chargePower")]
        if storage_target < 0
        else _allocate(online_storage, storage_target, "dischargePower")
    )
    storage_by_key = {
        (row["dev_type"], row["dev_name"]): storage_allocations[index]
        for index, row in enumerate(online_storage)
    }

    diesel_dispatch = [{**row, "headroomKw": max(0.0, row["capacityKw"] - row["minKw"])} for row in online_diesel]
    diesel_additional = max(0.0, diesel_target - diesel_min)
    diesel_headroom = sum(row["headroomKw"] for row in diesel_dispatch)
    diesel_additional_allocations = (
        _allocate(diesel_dispatch, diesel_additional, "headroomKw")
        if diesel_headroom > 0
        else [diesel_additional / max(1, len(diesel_dispatch)) for _ in diesel_dispatch]
    )
    fallback_diesel_by_name = {
        row["dev_name"]: row["minKw"] + diesel_additional_allocations[index]
        for index, row in enumerate(diesel_dispatch)
    }
    diesel_by_name = {
        **fallback_diesel_by_name,
        **component_dispatch_plan.get("dieselTargets", {}),
    }

    converter_allocations = [
        _clamp_converter_target_kw(
            row,
            final_converter_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                base_converter_allocations[index],
            ),
        )
        for index, row in enumerate(converter_rows)
    ]

    active_dc_transfer_group_ids = set(
        _active_dc_transfer_group_ids(
            resource_topology,
            (*renewable_rows, *storage_rows, *all_converter_rows),
        )
    )
    # 独立直流孤岛（不含在线 ACDC 变流器，但本地存在在线合格构网直流储能）同样允许本地直流可控设备协同。
    for s_row in storage_rows:
        if (
            s_row.get("connectionSide") == "DC"
            and s_row.get("role") == "balance"
            and s_row.get("online")
            and s_row.get("stateEligible")
        ):
            dc_gid = str(s_row.get("dcTransferGroupId") or s_row.get("gridComponentId") or "").strip()
            if dc_gid:
                active_dc_transfer_group_ids.add(dc_gid)

    command_rows: List[Dict[str, Any]] = []
    for row in renewable_rows:
        key = (row["dev_type"], row["dev_name"])
        dc_group_command_safe = (
            row.get("connectionSide") != "DC"
            or str(row.get("dcTransferGroupId") or row.get("gridComponentId") or "") in active_dc_transfer_group_ids
        )
        effective_commandable = bool(row["commandable"] and dc_group_command_safe)
        strategy_command = (
            effective_commandable and row["capabilityKnown"]
            if row["environmentKnown"]
            else effective_commandable and row.get("planningCurrentKw") is not None and _finite_number(row.get("capacityKw")) > 0
        )
        command_rows.append(
            {
                **row,
                "commandable": effective_commandable,
                "islandControlAction": island_control_action_by_resource.get(key, ""),
                "recoveryKw": max(
                    0.0,
                    _finite_number(renewable_target_by_device.get(key)) - _finite_number(row.get("currentKw")),
                ),
                "strategyCommand": strategy_command,
                "commandKw": (
                    renewable_target_by_device.get(key)
                    if row.get("online") and key in renewable_target_by_device
                    else _finite_number(row.get("planningCurrentKw"))
                    if row.get("online") and row.get("planningCurrentKw") is not None
                    else None
                    if row.get("online")
                    else 0.0
                ),
            }
        )
    for row in storage_rows:
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        current_kw = _number(row.get("currentKw"))
        is_grid_following = row.get("role") == "grid_following"
        is_grid_forming = row.get("role") == "balance"
        direct_state = (
            direct_storage_states.get(key, {})
            if is_grid_following
            else direct_grid_forming_states.get(key, {})
        )
        dc_group_command_safe = (
            row.get("connectionSide") != "DC"
            or str(row.get("dcTransferGroupId", "")) in active_dc_transfer_group_ids
        )
        direct_target_kw = (
            direct_storage_targets.get(key, current_kw)
            if is_grid_following
            else None
        )
        projected_target_kw = (
            projected_balance_targets.get(
                key,
                storage_by_key.get(
                    key,
                    current_kw if row.get("deviceOnline") else 0.0,
                ),
            )
            if is_grid_forming
            else None
        )
        direct_changed = bool(
            is_grid_following
            and row.get("commandable")
            and dc_group_command_safe
            and direct_state.get("directDispatchEligible")
            and current_kw is not None
            and direct_target_kw is not None
            and abs(_finite_number(direct_target_kw) - current_kw) > EPSILON
        )
        grid_forming_dispatch = bool(
            is_grid_forming
            and row.get("commandable")
            and dc_group_command_safe
            and direct_state.get("directDispatchEligible")
            and current_kw is not None
            and projected_target_kw is not None
        )
        command_kw = (
            direct_target_kw
            if is_grid_following
            else projected_target_kw
        )
        command_rows.append(
            {
                **row,
                "indirectControlDevices": (
                    side_aware_plan.get("indirectControlDevices", {}).get(
                        key,
                        row.get("indirectControlDevices", []),
                    )
                    if side_aware_plan is not None
                    else row.get("indirectControlDevices", [])
                ),
                "commandable": bool(
                    row.get("commandable")
                    and dc_group_command_safe
                    and (
                        (not is_grid_following and not is_grid_forming)
                        or direct_state.get("directDispatchEligible")
                    )
                ),
                "islandControlAction": island_control_action_by_component.get(
                    (
                        str(row.get("gridComponentId", "")),
                        str(row.get("dcTransferGroupId", "")),
                    ),
                    "",
                ),
                "planningCurrentKw": current_kw,
                "targetKw": (
                    direct_target_kw
                    if is_grid_following
                    else projected_target_kw
                ),
                "projectedTargetKw": projected_target_kw,
                "signedMinTargetKw": direct_state.get(
                    "signedMinTargetKw",
                    -max(0.0, _finite_number(row.get("chargePower"))),
                ),
                "signedMaxTargetKw": direct_state.get(
                    "signedMaxTargetKw",
                    max(0.0, _finite_number(row.get("dischargePower"))),
                ),
                "chargeMarginKw": _finite_number(
                    direct_state.get("chargeMarginKw")
                ),
                "dischargeMarginKw": _finite_number(
                    direct_state.get("dischargeMarginKw")
                ),
                "gridStorageStepKw": _finite_number(
                    direct_state.get("stepKw")
                ),
                "gridStorageStepScale": _finite_number(
                    direct_state.get("stepScale"),
                    1.0,
                ),
                "directDispatchEligible": bool(
                    direct_state.get("directDispatchEligible")
                ),
                "strategyCommand": direct_changed or grid_forming_dispatch,
                "availableKw": (
                    max(
                        _finite_number(row.get("chargePower")),
                        _finite_number(row.get("dischargePower")),
                    )
                    if row["online"]
                    else 0.0
                ),
                "commandKw": command_kw,
            }
        )
    command_rows.extend(
        {
            **row,
            "commandable": bool(
                row.get("commandable") and not renewable_storage_island
            ),
            "strategyCommand": bool(
                row.get("commandable") and not renewable_storage_island
            ),
            "availableKw": row["capacityKw"],
            "commandKw": diesel_by_name.get(row["dev_name"], row["minKw"]) if row["online"] else 0.0,
        }
        for row in diesel_rows
    )
    command_rows.extend(
        {
            **row,
            "islandControlAction": island_control_action_by_converter.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                "",
            ),
            "ratedAvailableKw": row["transferCapacityKw"]
            if row["transferCapacityKw"] > 0
            else max(total_charge, total_discharge) / max(1, len(converter_rows)),
            "availableKw": row["transferCapacityKw"]
            if row["transferCapacityKw"] > 0
            else max(total_charge, total_discharge) / max(1, len(converter_rows)),
            "strategyCommand": str(row.get("dcTransferGroupId", ""))
            in active_dc_transfer_group_ids,
            "commandKw": converter_allocations[index],
        }
        for index, row in enumerate(converter_rows)
    )
    command_rows.extend(
        {
            **row,
            "islandControlAction": island_control_action_by_converter.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                "",
            ),
            "ratedAvailableKw": row["transferCapacityKw"],
            "availableKw": row["transferCapacityKw"],
            "strategyCommand": str(row.get("dcTransferGroupId", ""))
            in active_dc_transfer_group_ids,
            "commandKw": 0.0,
            "statusLabel": f"{row.get('statusLabel', '')}·新能源储能孤岛归零",
        }
        for row in secondary_island_converter_rows
    )
    for row in held_converter_rows:
        current_kw = _number(row.get("currentKw"))
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        final_target_kw = _clamp_converter_target_kw(
            row,
            final_converter_targets.get(
                key,
                current_kw,
            ),
        )
        direct_changed = bool(
            current_kw is not None
            and abs(final_target_kw - current_kw) > EPSILON
        )
        dc_group_command_safe = (
            str(row.get("dcTransferGroupId", "")) in active_dc_transfer_group_ids
        )
        command_rows.append(
            {
                **row,
                "ratedAvailableKw": row["transferCapacityKw"],
                "availableKw": row["transferCapacityKw"],
                "strategyCommand": dc_group_command_safe
                and direct_changed,
                "commandKw": final_target_kw,
                "statusLabel": (
                    f"{row.get('statusLabel', '')}·直控储能同组配对"
                    if direct_changed
                    else f"{row.get('statusLabel', '')}·分组隔离保持"
                ),
            }
        )
    command_rows.extend(
        {
            **row,
            "ratedAvailableKw": row["transferCapacityKw"],
            "availableKw": row["transferCapacityKw"],
            "strategyCommand": False,
            "commandKw": row.get("currentKw") if row.get("online") else 0.0,
        }
        for row in diagnostic_converter_rows
    )

    blocked_optimization_component_ids = _blocked_optimization_component_ids(
        resource_topology,
        fail_closed_scopes,
        renewable_rows,
        storage_rows,
        diesel_rows,
        converter_inventory_rows,
        quality,
    )
    # 单一事实来源：将 command_rows 最终的 commandable 标志同步给优化器输入，彻底消除优化器与下发层的剪刀差。
    effective_commandable_by_key = {
        (str(r.get("dev_type", "")), str(r.get("dev_name", ""))): bool(r.get("commandable"))
        for r in command_rows
        if r.get("technology") in {"wind", "pv", "storage"}
    }
    opt_renewable_rows = [
        {**r, "commandable": effective_commandable_by_key.get((str(r.get("dev_type", "")), str(r.get("dev_name", ""))), bool(r.get("commandable")))}
        for r in renewable_rows
    ]
    opt_storage_rows = [
        {**r, "commandable": effective_commandable_by_key.get((str(r.get("dev_type", "")), str(r.get("dev_name", ""))), bool(r.get("commandable")))}
        for r in storage_rows
    ]
    optimization_started = time.perf_counter()
    strategy_preparation_seconds = optimization_started - topology_finished
    optimization_result = optimize_topology_islands(
        resource_topology,
        renewable_rows=opt_renewable_rows,
        diesel_rows=diesel_rows,
        storage_rows=opt_storage_rows,
        converter_rows=all_converter_rows,
        step_coefficient=settings.step_coefficient,
        diesel_step_ratio=settings.diesel_step_ratio,
        converter_step_ratio=settings.converter_step_ratio,
        converter_ramp_step_ratio=settings.converter_ramp_step_ratio,
        converter_efficiency=settings.converter_efficiency,
        storage_step_ratio=settings.storage_step_ratio,
        storage_soc_rebalance_deadband=settings.storage_soc_rebalance_deadband,
        storage_soc_correction_step_scale=(
            settings.storage_soc_correction_step_scale
        ),
        diesel_power_protection_ratio=(
            settings.diesel_power_protection_ratio
        ),
        grid_forming_storage_protection_ratio=(
            settings.grid_forming_storage_protection_ratio
        ),
        soc_deadband=settings.soc_deadband,
        renewable_curtailment_weight=(
            settings.optimization_renewable_curtailment_weight
        ),
        diesel_output_weight=settings.optimization_diesel_output_weight,
        curtailment_square_weight=(
            settings.optimization_curtailment_square_weight
        ),
        source_storage_adjustment_square_weight=(
            settings.optimization_source_storage_adjustment_square_weight
        ),
        balance_delta_square_weight=(
            settings.optimization_balance_delta_square_weight
        ),
        balance_delta_warning_kw=(
            settings.optimization_balance_delta_warning_kw
        ),
        balance_tolerance_kw=settings.optimization_balance_tolerance_kw,
        bound_tolerance_kw=settings.optimization_bound_tolerance_kw,
        optimization_ftol=settings.optimization_ftol,
        optimization_max_iterations=settings.optimization_max_iterations,
        blocked_component_ids=blocked_optimization_component_ids,
    )
    optimization_finished = time.perf_counter()
    optimization_total_seconds = optimization_finished - optimization_started
    # The optimizer owns the final per-device targets. Its variable bounds
    # already combine topology eligibility, physical limits, SOC segmented
    # limits, one-cycle maximum deltas, deadband guards and SOC emergency
    # correction. A failed or unassigned device is held at its live value.
    _apply_optimization_targets(
        command_rows,
        optimization_result,
        apply_targets=True,
    )

    # With the AC side fully retired, the island state machine is the only
    # source of a renewable ramp command. The steady-state optimizer preserves
    # the live island balance, so it would otherwise undo that one-step
    # curtail/recovery preview by returning both renewable and balance storage
    # to their live values. Reapply the state-machine target and its balancing
    # storage projection after optimization.
    if renewable_storage_island:
        island_plan_by_resource = {
            resource_key: component_plan
            for component_plan in island_component_plans
            for resource_key in component_plan.get("renewableTargets", {})
        }
        for row in command_rows:
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            component_plan = island_plan_by_resource.get(key)
            if component_plan is None:
                continue
            comp_ids_for_row = {
                str(row.get("gridComponentId", "")).strip(),
                str(row.get("dcTransferGroupId", "")).strip(),
            }
            if row.get("automaticControlBlocked") or bool(
                comp_ids_for_row.intersection(blocked_optimization_component_ids)
            ):
                continue
            target = _number(component_plan.get("renewableTargets", {}).get(key))
            current = _number(row.get("planningCurrentKw", row.get("currentKw")))
            if target is None:
                continue
            nat_upper = _number(row.get("naturalUpperKw"))
            if nat_upper is not None:
                target = min(target, nat_upper)
            row["commandKw"] = target
            row["targetKw"] = target
            row["optimizationSuggestedKw"] = target
            row["strategyTargetChanged"] = bool(
                row.get("online")
                and row.get("commandable")
                and row.get("set_type")
                and current is not None
                and abs(target - current) > EPSILON
            )
            row["strategyCommand"] = bool(
                row.get("online")
                and row.get("commandable")
                and row.get("set_type")
                and current is not None
            )
        for component_plan in island_component_plans:
            component_key = (
                str(component_plan.get("gridComponentId", "")),
                str(component_plan.get("dcTransferGroupId", "")),
            )
            if set(component_key).intersection(blocked_optimization_component_ids):
                continue
            renewable_delta_kw = sum(
                _finite_number(
                    next(
                        (
                            row.get("commandKw")
                            for row in command_rows
                            if (str(row.get("dev_type", "")), str(row.get("dev_name", ""))) == resource_key
                        ),
                        target,
                    )
                )
                - _finite_number(
                    next(
                        (
                            row.get("planningCurrentKw", row.get("currentKw"))
                            for row in command_rows
                            if (
                                str(row.get("dev_type", "")),
                                str(row.get("dev_name", "")),
                            )
                            == resource_key
                        ),
                        0.0,
                    )
                )
                for resource_key, target in component_plan.get(
                    "renewableTargets", {}
                ).items()
            )
            balance_rows = [
                row
                for row in command_rows
                if row.get("technology") == "storage"
                and row.get("role") == "balance"
                and row.get("online")
                and row.get("stateEligible")
                and (
                    str(row.get("gridComponentId", "")),
                    str(row.get("dcTransferGroupId", "")),
                )
                == component_key
            ]
            if not balance_rows or abs(renewable_delta_kw) <= EPSILON:
                continue
            total_capacity = sum(
                max(
                    EPSILON,
                    _finite_number(row.get("maxChargePowerKw")),
                    _finite_number(row.get("maxDischargePowerKw")),
                )
                for row in balance_rows
            )
            for row in balance_rows:
                current = _finite_number(row.get("currentKw"))
                capacity = max(
                    EPSILON,
                    _finite_number(row.get("maxChargePowerKw")),
                    _finite_number(row.get("maxDischargePowerKw")),
                )
                target = current - renewable_delta_kw * capacity / total_capacity
                lower = _number(row.get("signedMinTargetKw"))
                upper = _number(row.get("signedMaxTargetKw"))
                if lower is not None and upper is not None:
                    target = _clamp(target, lower, upper)
                row["commandKw"] = target
                row["targetKw"] = target
                row["projectedTargetKw"] = target
                row["optimizationSuggestedKw"] = target

    renewable_target_by_device = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): float(row["commandKw"])
        for row in command_rows
        if row.get("technology") in {"wind", "pv"}
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    }
    direct_storage_targets = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): float(row["commandKw"])
        for row in command_rows
        if row.get("technology") == "storage"
        and row.get("role") == "grid_following"
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    }
    projected_balance_targets = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): float(row["commandKw"])
        for row in command_rows
        if row.get("technology") == "storage"
        and row.get("role") == "balance"
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    }
    final_converter_targets = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): float(row["commandKw"])
        for row in command_rows
        if _is_grid_converter_row(row)
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    }
    diesel_by_name = {
        str(row.get("dev_name", "")): float(row["commandKw"])
        for row in command_rows
        if row.get("category") == "柴油发电"
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    }
    renewable_target = sum(renewable_target_by_device.values())
    renewable_delta = renewable_target - renewable_current
    storage_target = sum(
        float(row["commandKw"])
        for row in command_rows
        if row.get("technology") == "storage"
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    )
    diesel_target = sum(diesel_by_name.values())
    predicted_diesel = diesel_target
    diesel_residual = diesel_target
    candidate_effect = (
        diesel_current_for_control - diesel_target if online_diesel else 0.0
    )
    diesel_boundary_error = diesel_target - diesel_min
    current_diesel_violation = (
        _diesel_boundary_violation(
            diesel_current_for_control,
            diesel_min,
            diesel_capacity,
        )
        if online_diesel
        else 0.0
    )
    predicted_diesel_violation = (
        _diesel_boundary_violation(diesel_target, diesel_min, diesel_capacity)
        if online_diesel
        else 0.0
    )
    diesel_violation_improved = (
        predicted_diesel_violation + 0.001 < current_diesel_violation
        if current_diesel_violation > 0.001
        else predicted_diesel_violation <= 0.001
    )
    diesel_validation_status = (
        "not_applicable"
        if not online_diesel
        else "within_bounds"
        if predicted_diesel_violation <= 0.001
        else "improved"
        if diesel_violation_improved
        else "feedback_pending"
    )
    aggregate_converter_values = [
        (row, current_kw, target_kw)
        for row in command_rows
        if _is_grid_converter_row(row)
        and row.get("online")
        and row.get("commandable") is not False
        and (
            not renewable_storage_island
            or row.get("strategyCommand") is not False
        )
        and row.get("set_type")
        and (current_kw := _number(row.get("currentKw"))) is not None
        and (target_kw := _number(row.get("commandKw"))) is not None
    ]
    aggregate_converter_current_kw = (
        sum(
            _finite_number(_converter_system_power_kw(row, current_kw))
            for row, current_kw, _target_kw in aggregate_converter_values
        )
        if aggregate_converter_values
        else None
    )
    aggregate_converter_target_kw = sum(
        _finite_number(_converter_system_power_kw(row, target_kw))
        for row, _current_kw, target_kw in aggregate_converter_values
    )
    aggregate_converter_lower_limit_kw = sum(
        -_converter_signed_bounds_kw(row)[1] for row in all_converter_rows
    )
    aggregate_converter_upper_limit_kw = sum(
        -_converter_signed_bounds_kw(row)[0] for row in all_converter_rows
    )
    aggregate_converter_capacity_kw = sum(
        max(abs(lower_kw), abs(upper_kw))
        for row in all_converter_rows
        for lower_kw, upper_kw in [_converter_signed_bounds_kw(row)]
    )

    storage_charge_derating_residual_kw = sum(
        max(
            0.0,
            _finite_number(row.get("signedMinTargetKw"))
            - _finite_number(_metric_target(row), row.get("currentKw")),
        )
        for row in command_rows
        if row.get("technology") == "storage"
        and row.get("online")
        and _metric_target(row) is not None
    )

    if renewable_control_action == "curtail_charge_safety":
        final_safety_curtail_kw = sum(
            max(
                0.0,
                _finite_number(row.get("planningCurrentKw", row.get("currentKw")))
                - _finite_number(
                    renewable_target_by_device.get(
                        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                        row.get("planningCurrentKw", row.get("currentKw")),
                    )
                ),
            )
            for row in online_renewable
            if _number(row.get("planningCurrentKw", row.get("currentKw")))
            is not None
        )
        renewable_charge_safety_curtail_delivered_kw = min(
            renewable_charge_safety_curtail_required_kw,
            final_safety_curtail_kw,
        )
        renewable_charge_safety_curtail_shortfall_kw = max(
            0.0,
            renewable_charge_safety_curtail_required_kw
            - renewable_charge_safety_curtail_delivered_kw,
        )
        renewable_step_scale = (
            renewable_charge_safety_curtail_delivered_kw
            / renewable_curtail_capacity_step_kw
            if renewable_curtail_capacity_step_kw > EPSILON
            else 0.0
        )
        renewable_effective_step_ratio = settings.step_coefficient * renewable_step_scale

    hydrogen_plan = _optimize_hydrogen_within_topology_islands(
        snapshot,
        measurements,
        settings,
        resource_topology,
        command_rows,
        storage_rows,
        diesel_current_kw=diesel_target,
        diesel_capacity_kw=sum(
            _finite_number(row.get("ratedCapacityKw")) for row in online_diesel
        ),
        diesel_unit_count=len(online_diesel),
        diesel_input_valid=bool(
            online_diesel
            and len(measured_diesel) == len(online_diesel)
        ),
        apply_electrical_corrections=settings.hydrogen_closed_loop_enabled,
        optimization_result=optimization_result,
        runtime_memory=runtime_memory,
        sim_time_seconds=sim_time_seconds,
        zero_diesel_grid_forming=bool(
            operating_mode == "grid_forming_storage_reference"
        ),
        defer_dwell_commit=True,
    )
    # 氢能与主优化器单拍协同：氢能闭环发生非零电功率调节时，将氢能净电注入变更量回代重算主优化器，
    # 使新能源恢复、柴发出力、储能充放与变流器并联均流在同一控制周期内满足精确功率平衡。
    hydrogen_external_injection: Dict[Tuple[str, str], float] = {}
    hydrogen_external_cmds: List[Dict[str, Any]] = []
    if settings.hydrogen_closed_loop_enabled and not renewable_storage_island:
        for h_cmd in hydrogen_plan.get("commands", []) or []:
            h_delta = _number(h_cmd.get("electricDeltaKw"))
            h_side = str(h_cmd.get("electricSide", "") or "").strip().upper()
            # 与主优化器 _component_id 口径严格对齐：直流侧优先采用 dcTransferGroupId。
            h_comp = (
                str(h_cmd.get("dcTransferGroupId") or h_cmd.get("electricComponentId") or "").strip()
                if h_side == "DC"
                else str(h_cmd.get("electricComponentId") or "").strip()
            )
            if h_delta is None or abs(h_delta) <= 0.05 or not h_comp or h_side not in {"AC", "DC"}:
                continue
            # 电制氢为负荷（+delta 表示多耗电，净电源注入为 -delta）；燃料电池为电源（+delta 表示多发电）
            signed_injection = -float(h_delta) if h_cmd.get("mode") == "electrolyzer" else float(h_delta)
            comp_key = (h_comp, h_side)
            hydrogen_external_injection[comp_key] = (
                hydrogen_external_injection.get(comp_key, 0.0) + signed_injection
            )
            hydrogen_external_cmds.append(h_cmd)
    if hydrogen_external_injection:
        # 若某电气组件因电制氢增载产生净负荷增加（signed_injection < 0），在回代重算副本中临时释放
        # 仅由首轮柴发低载防倒送导致的向上恢复锁（保留物理自然上限与储能充电安全限电锁），
        # 使电制氢优先消纳弃风弃光而非拉高柴发。
        electrolyzer_load_components = {
            comp_id
            for (comp_id, _side), inj_kw in hydrogen_external_injection.items()
            if inj_kw < -0.05
        }
        electrolyzer_island_components: set[str] = set(electrolyzer_load_components)
        for isl in optimization_result.islands:
            if electrolyzer_load_components.intersection(isl.component_ids):
                electrolyzer_island_components.update(isl.component_ids)
        coordinated_renewable_rows = []
        for row in opt_renewable_rows:
            row_copy = dict(row)
            row_side = str(row_copy.get("connectionSide", "") or "").strip().upper()
            row_comp = (
                str(row_copy.get("dcTransferGroupId") or row_copy.get("gridComponentId") or "").strip()
                if row_side == "DC"
                else str(row_copy.get("gridComponentId") or "").strip()
            )
            if (
                row_comp in electrolyzer_island_components
                and row_copy.get("dispatchUpperReason") in {
                    "diesel_guard_no_renewable_recovery",
                    "diesel_guard_storage_charging_curtailment",
                }
            ):
                nat_upper = _number(row_copy.get("naturalUpperKw"))
                if nat_upper is not None:
                    row_copy["dispatchUpperKw"] = nat_upper
                    row_copy["dispatchUpperReason"] = str(
                        row_copy.get("naturalUpperReason", "natural_limit")
                    )
                else:
                    row_copy.pop("dispatchUpperKw", None)
                    row_copy.pop("dispatchUpperReason", None)
            coordinated_renewable_rows.append(row_copy)

        coordinated_opt = optimize_topology_islands(
            resource_topology,
            renewable_rows=coordinated_renewable_rows,
            diesel_rows=diesel_rows,
            storage_rows=opt_storage_rows,
            converter_rows=all_converter_rows,
            step_coefficient=settings.step_coefficient,
            diesel_step_ratio=settings.diesel_step_ratio,
            converter_step_ratio=settings.converter_step_ratio,
            converter_ramp_step_ratio=settings.converter_ramp_step_ratio,
            converter_efficiency=settings.converter_efficiency,
            storage_step_ratio=settings.storage_step_ratio,
            storage_soc_rebalance_deadband=settings.storage_soc_rebalance_deadband,
            storage_soc_correction_step_scale=settings.storage_soc_correction_step_scale,
            diesel_power_protection_ratio=settings.diesel_power_protection_ratio,
            grid_forming_storage_protection_ratio=settings.grid_forming_storage_protection_ratio,
            soc_deadband=settings.soc_deadband,
            renewable_curtailment_weight=settings.optimization_renewable_curtailment_weight,
            diesel_output_weight=settings.optimization_diesel_output_weight,
            curtailment_square_weight=settings.optimization_curtailment_square_weight,
            source_storage_adjustment_square_weight=settings.optimization_source_storage_adjustment_square_weight,
            balance_delta_square_weight=settings.optimization_balance_delta_square_weight,
            balance_delta_warning_kw=settings.optimization_balance_delta_warning_kw,
            balance_tolerance_kw=settings.optimization_balance_tolerance_kw,
            bound_tolerance_kw=settings.optimization_bound_tolerance_kw,
            optimization_ftol=settings.optimization_ftol,
            optimization_max_iterations=settings.optimization_max_iterations,
            blocked_component_ids=blocked_optimization_component_ids,
            external_injection_delta_by_component=hydrogen_external_injection,
        )
        # 仅在氢能所在岛求解成功且未引入恶化平衡残差时采纳单拍回代结果
        h_comp_set = {comp_id for comp_id, _side in hydrogen_external_injection}
        baseline_max_delta = max(
            (isl.max_balance_delta_kw for isl in optimization_result.islands if h_comp_set.intersection(isl.component_ids)),
            default=0.0,
        )
        coord_h_islands = [
            isl for isl in coordinated_opt.islands if h_comp_set.intersection(isl.component_ids)
        ]
        balance_acceptable = bool(
            coord_h_islands
            and all(
                isl.success
                and isl.max_balance_delta_kw
                <= max(
                    baseline_max_delta + 0.05,
                    settings.optimization_balance_tolerance_kw,
                    settings.optimization_balance_delta_warning_kw,
                )
                for isl in coord_h_islands
            )
        )
        if balance_acceptable:
            optimization_result = coordinated_opt
            non_hydrogen_rows = [
                row for row in command_rows if row.get("category") != "氢能"
            ]
            _apply_optimization_targets(
                non_hydrogen_rows,
                optimization_result,
                apply_targets=True,
            )
            hydrogen_plan["singleCycleCoordinated"] = True
            hydrogen_plan["coordinationSequence"] = [
                "renewable-diesel-storage",
                "hydrogen",
                "single-cycle-reoptimization",
            ]
            renewable_target_by_device = {
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): float(row["commandKw"])
                for row in command_rows
                if row.get("technology") in {"wind", "pv"}
                and row.get("online")
                and _number(row.get("commandKw")) is not None
            }
            renewable_target = sum(renewable_target_by_device.values())
            renewable_delta = renewable_target - renewable_current
            storage_target = sum(
                float(row["commandKw"])
                for row in command_rows
                if row.get("technology") == "storage"
                and row.get("online")
                and _number(row.get("commandKw")) is not None
            )
            coordinated_diesel_kw = sum(
                float(row["commandKw"])
                for row in command_rows
                if row.get("category") == "柴油发电"
                and row.get("online")
                and _number(row.get("commandKw")) is not None
            )
            diesel_cap_total = float(hydrogen_plan.get("dieselCapacityKw") or 0.0)
            diesel_cnt = max(1, int(hydrogen_plan.get("dieselUnitCount") or 1))
            hydrogen_plan["predictedDieselAfterKw"] = coordinated_diesel_kw
            hydrogen_plan["predictedDieselAverageAfterKw"] = coordinated_diesel_kw / diesel_cnt
            hydrogen_plan["predictedDieselLoadRatioAfter"] = (
                coordinated_diesel_kw / diesel_cap_total if diesel_cap_total > EPSILON else None
            )
            hydrogen_plan["balanceCorrectionKw"] = (
                coordinated_diesel_kw - float(hydrogen_plan.get("predictedDieselBeforeKw") or 0.0)
            )
        else:
            # 单拍协同回代未通过平衡校核时，保守撤回非硬安全停机的经济性氢能增量，
            # 防止未配平的氢能阶跃冲击构网储能；硬安全停机（压力/SOC/互锁）无条件保留。
            rollback_cmds = [
                h_cmd
                for h_cmd in hydrogen_external_cmds
                if not h_cmd.get("hardSafetyStop")
                and abs(float(_number(h_cmd.get("electricDeltaKw"), 0.0) or 0.0)) > 0.05
            ]
            if rollback_cmds:
                rollback_couplings = {
                    (str(h_cmd.get("couplingType", "")), str(h_cmd.get("couplingName", "")))
                    for h_cmd in rollback_cmds
                }
                rollback_active_keys = {
                    (
                        str(h_cmd.get("activeDevType", "")),
                        str(h_cmd.get("activeDevName", "")),
                        str(h_cmd.get("activeSetType", "")),
                    )
                    for h_cmd in rollback_cmds
                }
                for row in list(command_rows):
                    if (
                        row.get("category") == "氢能"
                        and row.get("commandKind") == "run_status"
                        and (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
                        in rollback_couplings
                    ):
                        command_rows.remove(row)
                    elif (
                        row.get("category") == "氢能"
                        and (
                            str(row.get("dev_type", "")),
                            str(row.get("dev_name", "")),
                            str(row.get("set_type", "")),
                        )
                        in rollback_active_keys
                    ):
                        row["commandKw"] = float(_number(row.get("currentKw"), 0.0) or 0.0)
                        row["strategyCommand"] = False
                # 同步恢复非氢能行：若存在保留的硬安全停机氢能扰动，基于硬安全停机注入量重算一次平衡，避免抹掉硬安全停机的电侧配平。
                hard_safety_injection: Dict[Tuple[str, str], float] = {}
                for h_cmd in hydrogen_external_cmds:
                    if not h_cmd.get("hardSafetyStop"):
                        continue
                    h_delta = _number(h_cmd.get("electricDeltaKw"))
                    h_side = str(h_cmd.get("electricSide", "") or "").strip().upper()
                    h_comp = (
                        str(h_cmd.get("dcTransferGroupId") or h_cmd.get("electricComponentId") or "").strip()
                        if h_side == "DC"
                        else str(h_cmd.get("electricComponentId") or "").strip()
                    )
                    if h_delta is None or abs(h_delta) <= 0.05 or not h_comp or h_side not in {"AC", "DC"}:
                        continue
                    signed_inj = -float(h_delta) if h_cmd.get("mode") == "electrolyzer" else float(h_delta)
                    hard_safety_injection[(h_comp, h_side)] = (
                        hard_safety_injection.get((h_comp, h_side), 0.0) + signed_inj
                    )
                if hard_safety_injection:
                    safety_reopt = optimize_topology_islands(
                        resource_topology,
                        renewable_rows=opt_renewable_rows,
                        diesel_rows=diesel_rows,
                        storage_rows=opt_storage_rows,
                        converter_rows=all_converter_rows,
                        step_coefficient=settings.step_coefficient,
                        diesel_step_ratio=settings.diesel_step_ratio,
                        converter_step_ratio=settings.converter_step_ratio,
                        converter_ramp_step_ratio=settings.converter_ramp_step_ratio,
                        converter_efficiency=settings.converter_efficiency,
                        storage_step_ratio=settings.storage_step_ratio,
                        storage_soc_rebalance_deadband=settings.storage_soc_rebalance_deadband,
                        storage_soc_correction_step_scale=settings.storage_soc_correction_step_scale,
                        diesel_power_protection_ratio=settings.diesel_power_protection_ratio,
                        grid_forming_storage_protection_ratio=settings.grid_forming_storage_protection_ratio,
                        soc_deadband=settings.soc_deadband,
                        renewable_curtailment_weight=settings.optimization_renewable_curtailment_weight,
                        diesel_output_weight=settings.optimization_diesel_output_weight,
                        curtailment_square_weight=settings.optimization_curtailment_square_weight,
                        source_storage_adjustment_square_weight=settings.optimization_source_storage_adjustment_square_weight,
                        balance_delta_square_weight=settings.optimization_balance_delta_square_weight,
                        balance_delta_warning_kw=settings.optimization_balance_delta_warning_kw,
                        balance_tolerance_kw=settings.optimization_balance_tolerance_kw,
                        bound_tolerance_kw=settings.optimization_bound_tolerance_kw,
                        optimization_ftol=settings.optimization_ftol,
                        optimization_max_iterations=settings.optimization_max_iterations,
                        blocked_component_ids=blocked_optimization_component_ids,
                        external_injection_delta_by_component=hard_safety_injection,
                    )
                    if safety_reopt.all_success:
                        optimization_result = safety_reopt
                non_hydrogen_rows = [
                    row for row in command_rows if row.get("category") != "氢能"
                ]
                _apply_optimization_targets(
                    non_hydrogen_rows,
                    optimization_result,
                    apply_targets=True,
                )
                for h_cmd in rollback_cmds:
                    prev_kw = float(_number(h_cmd.get("currentElectricPowerKw"), 0.0) or 0.0)
                    h_cmd["electricPowerKw"] = prev_kw
                    h_cmd["targetElectricPowerKw"] = prev_kw
                    h_cmd["electricDeltaKw"] = 0.0
                    h_cmd["action"] = "hold"
                    h_cmd["controlReason"] = "single_cycle_reoptimization_balance_rejected"
                # 撤回已回滚氢能设备的待提交驻留记忆，防止污染下一拍冷却计时器。
                pending_dwell = hydrogen_plan.get("pendingDwellMemory")
                if isinstance(pending_dwell, dict) and runtime_memory is not None:
                    prev_dwell = runtime_memory.get("hydrogen_dwell")
                    prev_dwell_map = prev_dwell if isinstance(prev_dwell, dict) else {}
                    for c_type, c_name in rollback_couplings:
                        d_key = f"{c_type}:{c_name}"
                        if d_key in prev_dwell_map:
                            pending_dwell[d_key] = copy.deepcopy(prev_dwell_map[d_key])
                        else:
                            pending_dwell.pop(d_key, None)
                hydrogen_plan["singleCycleCoordinated"] = False
                hydrogen_plan["electricPowerAdjustmentKw"] = sum(
                    float(_number(r.get("electricDeltaKw"), 0.0) or 0.0)
                    for r in (hydrogen_plan.get("commands") or [])
                )
                hydrogen_plan["targetElectricPowerKw"] = sum(
                    float(_number(r.get("electricPowerKw"), 0.0) or 0.0)
                    for r in (hydrogen_plan.get("commands") or [])
                )
                hydrogen_plan.setdefault("warnings", []).append(
                    "氢能经济性增量在单拍主优化器协同校核中无法满足电侧平衡，已保守保持当前氢能功率"
                )
    # 仅在未发生质量阻断且启用氢能闭环时，原子提交氢能驻留记忆（杜绝开环预览/回滚/阻断提前脏写）。
    if (
        runtime_memory is not None
        and not quality.blocked
        and settings.hydrogen_closed_loop_enabled
        and isinstance(hydrogen_plan.get("pendingDwellMemory"), dict)
    ):
        runtime_memory["hydrogen_dwell"] = hydrogen_plan["pendingDwellMemory"]
    strategy_boundary_warnings = _clamp_final_command_rows_to_boundaries(
        command_rows
    )
    _finalize_renewable_saturation_memory(
        command_rows,
        runtime_memory=runtime_memory,
        sim_time_seconds=sim_time_seconds,
        quality_blocked=bool(quality.blocked),
    )
    diesel_by_name = {
        str(row.get("dev_name", "")): float(row["commandKw"])
        for row in command_rows
        if row.get("category") == "柴油发电"
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    }
    diesel_target = sum(diesel_by_name.values())
    # 优化器接管最终目标后，同步修正与实际调节方向冲突的旧规则动作标签，避免“日志说保持、实际大调节”
    if not renewable_storage_island:
        safety_override_used = any(
            island.step_override_applied or island.status == "optimal_safety_override"
            for island in optimization_result.islands
        )
        if renewable_delta < -0.05 and str(renewable_control_action).startswith("hold"):
            renewable_control_action = (
                "curtail_safety_override" if safety_override_used else "curtail_optimize"
            )
            renewable_step_direction = "decrease"
        elif renewable_delta > 0.05 and str(renewable_control_action).startswith("hold"):
            renewable_control_action = "recover_optimize"
            renewable_step_direction = "increase"
        storage_net_delta = storage_target - storage_current_for_control
        if abs(storage_net_delta) > 0.05 and str(storage_control_action).startswith("hold"):
            if storage_net_delta < -0.05:
                storage_control_action = (
                    "increase_charge_optimize"
                    if storage_target < -0.05
                    else "reduce_discharge_optimize"
                )
            else:
                storage_control_action = (
                    "increase_discharge_optimize"
                    if storage_target > 0.05
                    else "reduce_charge_optimize"
                )
    predicted_diesel = diesel_target
    diesel_residual = diesel_target
    candidate_effect = (
        diesel_current_for_control - diesel_target if online_diesel else 0.0
    )
    diesel_boundary_error = diesel_target - diesel_min
    predicted_diesel_violation = (
        _diesel_boundary_violation(diesel_target, diesel_min, diesel_capacity)
        if online_diesel
        else 0.0
    )
    diesel_violation_improved = (
        predicted_diesel_violation + 0.001 < current_diesel_violation
        if current_diesel_violation > 0.001
        else predicted_diesel_violation <= 0.001
    )
    diesel_validation_status = (
        "not_applicable"
        if not online_diesel
        else "within_bounds"
        if predicted_diesel_violation <= 0.001
        else "improved"
        if diesel_violation_improved
        else "feedback_pending"
    )
    final_converter_targets = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): float(row["commandKw"])
        for row in command_rows
        if _is_grid_converter_row(row)
        and row.get("online")
        and _number(row.get("commandKw")) is not None
    }
    aggregate_converter_values = [
        (row, current_kw, target_kw)
        for row in command_rows
        if _is_grid_converter_row(row)
        and row.get("online")
        and row.get("commandable") is not False
        and row.get("set_type")
        and (current_kw := _number(row.get("currentKw"))) is not None
        and (target_kw := _number(row.get("commandKw"))) is not None
    ]
    aggregate_converter_target_kw = sum(
        _finite_number(_converter_system_power_kw(row, target_kw))
        for row, _current_kw, target_kw in aggregate_converter_values
    )
    converter_applied_step_kw = (
        abs(aggregate_converter_target_kw - aggregate_converter_current_kw)
        if aggregate_converter_current_kw is not None
        else 0.0
    )

    def dispatch_commands_from_rows(
        rows: Sequence[Mapping[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        candidates = [
            {
                "dev_type": row["dev_type"],
                "dev_name": row["dev_name"],
                "set_type": row["set_type"],
                "set_value": _command_number(_dispatch_setpoint_value(row)),
            }
            for row in rows
            if row.get("online")
            and row.get("commandable") is not False
            and row.get("strategyCommand") is not False
            and row.get("dispatchEnabled") is not False
            and row.get("set_type")
            and isinstance(row.get("commandKw"), (int, float))
            and math.isfinite(float(row["commandKw"]))
        ]
        return _deduplicate_dispatch_commands(candidates)

    def dispatch_run_commands_from_rows(
        rows: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        ordered_keys: List[Tuple[str, str]] = []
        selected: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for row in rows:
            if (
                row.get("commandKind") != "run_status"
                or row.get("commandable") is False
                or row.get("strategyCommand") is False
                or row.get("dispatchEnabled") is False
            ):
                continue
            key = (
                str(row.get("dev_type", "")).strip(),
                str(row.get("dev_name", "")).strip(),
            )
            run_stat = _number(row.get("run_stat"))
            # 允许自动控制策略下发氢能停机（run_stat=0）与开机（run_stat=1）遥控。
            if not all(key) or run_stat is None or int(run_stat) not in (0, 1):
                continue
            if key not in selected:
                ordered_keys.append(key)
            selected[key] = {
                "dev_type": key[0],
                "dev_name": key[1],
                "run_stat": int(run_stat),
            }
        return [selected[key] for key in ordered_keys]

    commands, duplicate_commands = dispatch_commands_from_rows(command_rows)
    run_commands = dispatch_run_commands_from_rows(command_rows)
    if quality.blocked:
        commands = []
        run_commands = []

    warnings: List[str] = []
    warnings.extend(str(item) for item in hydrogen_plan.get("warnings", []))
    warnings.extend(strategy_boundary_warnings)
    if any(
        row.get("technology") == "wind"
        and row.get("online")
        and not row.get("weatherAvailableKnown")
        for row in renewable_rows
    ):
        warnings.append(
            "风电理论可发统计缺少有效风速或设备风速参数；不影响本轮控制优化"
        )
    if any(
        row.get("technology") == "pv"
        and row.get("online")
        and not row.get("weatherAvailableKnown")
        for row in renewable_rows
    ):
        warnings.append(
            "光伏理论可发统计缺少有效辐照度或设备参考参数；不影响本轮控制优化"
        )
    warnings.extend(
        _optimization_balance_delta_warnings(optimization_result)
    )
    warnings.extend(
        f"优化岛{island.island_id}求解失败，岛内设备保持当前值：{island.message}"
        for island in optimization_result.islands
        if not island.success
    )
    if optimization_result.unassigned_devices:
        warnings.append(
            "部分在线可控设备缺少完整拓扑或边界，未纳入优化："
            + "、".join(
                f"{dev_type}.{dev_name}"
                for dev_type, dev_name in optimization_result.unassigned_devices
            )
        )
    # The pre-optimization renewable shortfall may be resolved by the unified
    # optimizer through storage or converter targets. Warn only when the final
    # SOC-derated storage target still remains outside its safe charging range.
    if storage_charge_derating_residual_kw > EPSILON:
        warnings.append(
            f"储能充电保护仍有 {storage_charge_derating_residual_kw:.2f} kW 未完成校正，已下发当前可实现的最大安全目标"
        )
    if any(row.get("conflict") for row in duplicate_commands):
        warnings.append("检测到同一遥调点存在多个候选值，已按最终校核结果去重")
    warnings.extend(issue for issue in quality.issues if issue not in warnings)

    wind_available = sum(
        max(0.0, _finite_number(row.get("capacityKw")))
        for row in renewable_rows
        if row.get("technology") == "wind" and row.get("online")
    )
    pv_available = sum(
        max(0.0, _finite_number(row.get("capacityKw")))
        for row in renewable_rows
        if row.get("technology") == "pv" and row.get("online")
    )
    available_renewable = sum(
        optimization_result.available_by_renewable.values()
    )
    curtail_kw = sum(
        optimization_result.curtailment_by_renewable.values()
    )
    recovery_kw = max(0.0, renewable_delta)
    recovery_candidate_count = sum(
        1
        for row in online_renewable
        if row.get("commandable") and _finite_number(row.get("capacityKw")) > _finite_number(row.get("currentKw")) + EPSILON
    )
    clock = _measurement_sample_clock(snapshot)
    time_text = str(clock.get("time", "--"))
    run_id = int(_number(clock.get("run_id"), 0.0) or 0)
    step_count_key = int(_number(clock.get("step_count"), 0.0) or 0)
    clock_key = f"{run_id}|{step_count_key}|{clock.get('absolute_minute', clock.get('minute', ''))}|{time_text}"
    quality_payload = quality.payload()
    island_component_metrics = [
        {
            "gridComponentId": str(plan.get("gridComponentId", "")),
            "dcTransferGroupId": str(plan.get("dcTransferGroupId", "")),
            "action": str(plan.get("action", "")),
            "storageSoc": plan.get("storageSoc"),
            "storageSocUpperLimit": plan.get("storageSocUpperLimit"),
            "renewableCurrentKw": _finite_number(plan.get("renewableCurrentKw")),
            "renewableTargetKw": _finite_number(plan.get("renewableTargetKw")),
            "converterTargetKw": _finite_number(plan.get("converterTargetKw")),
            "converterDevices": [
                {"dev_type": dev_type, "dev_name": dev_name}
                for dev_type, dev_name in plan.get("converterKeys", [])
            ],
        }
        for plan in island_component_plans
    ]
    ac_grid_following_storage_target = sum(
        _finite_number(
            direct_storage_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                row.get("currentKw"),
            )
        )
        for row in online_ac_grid_following_storage
        if row.get("currentKw") is not None
    )
    dc_grid_following_storage_target = sum(
        _finite_number(
            direct_storage_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                row.get("currentKw"),
            )
        )
        for row in online_dc_grid_following_storage
        if row.get("currentKw") is not None
    )
    task8_side_metrics = _task8_side_metrics(command_rows)
    direct_dispatch_blocks = [
        {
            "dev_type": str(row.get("dev_type", "")),
            "dev_name": str(row.get("dev_name", "")),
            "side": str(row.get("connectionSide", "")),
            "dcTransferGroupId": str(row.get("dcTransferGroupId", "")),
            "reason": str(row.get("directDispatchBlockedReason", "")),
        }
        for row in command_rows
        if str(row.get("directDispatchBlockedReason", "")).strip()
    ]
    _ac_load_for_transfer_metrics, dc_load_for_transfer_metrics = _active_load_budgets(
        snapshot,
        measurements,
        resource_topology.dc_transfer_groups,
    )
    load_side_metrics = _active_load_side_metrics(snapshot, measurements)
    side_total_load_kw = _sum_known(
        (load_side_metrics.get("acLoadKw"), load_side_metrics.get("dcLoadKw"))
    )
    dc_transfer_groups_metric, dc_renewable_to_ac_kw = _dc_transfer_group_metrics(
        resource_topology,
        command_rows,
        dc_load_for_transfer_metrics,
        converter_step_ratio=settings.converter_step_ratio,
    )
    online_storage_metric_rows = [
        row
        for row in command_rows
        if row.get("online")
        and row.get("technology") == "storage"
        and row.get("dev_type") in {"ACGenerator", "DCGenerator"}
        and row.get("resourceIdentityValid") is not False
    ]
    measured_storage_metric_rows = [
        row for row in online_storage_metric_rows if row.get("currentKw") is not None
    ]
    metric_storage_current = (
        sum(_finite_number(row.get("currentKw")) for row in measured_storage_metric_rows)
        if measured_storage_metric_rows
        else None
    )
    metric_storage_soc = _capacity_weighted_soc(online_storage_metric_rows)
    metrics = {
        **_optimization_metrics(optimization_result),
        "operatingMode": operating_mode,
        "acSideFullyOffline": ac_side_fully_offline,
        "renewableStorageIsland": renewable_storage_island,
        "renewableStorageIslandComponentCount": len(island_component_metrics),
        "renewableStorageIslandComponents": island_component_metrics,
        "acBusCount": len(ac_bus_rows),
        "onlineAcBusCount": len(online_ac_buses),
        "acLoadCount": len(ac_load_devices),
        "onlineAcLoadCount": len(online_ac_loads),
        "onlineDieselCount": len(online_diesel),
        "onlineStorageCount": len(island_online_storage) if renewable_storage_island else len(online_storage),
        "onlineAcBalanceStorageCount": len(online_ac_balance_storage),
        "onlineDcBalanceStorageCount": len(online_dc_balance_storage),
        "onlineAcGridFollowingStorageCount": len(online_ac_grid_following_storage),
        "onlineDcGridFollowingStorageCount": len(online_dc_grid_following_storage),
        "onlineAcdcConverterCount": len(
            [row for row in all_converter_rows if row.get("online")]
        ),
        "acBalanceStorageCurrentKw": ac_balance_storage_current,
        "dcBalanceStorageCurrentKw": dc_balance_storage_current,
        "acGridFollowingStorageCurrentKw": ac_grid_following_storage_current,
        "dcGridFollowingStorageCurrentKw": dc_grid_following_storage_current,
        "acGridFollowingStorageTargetKw": ac_grid_following_storage_target,
        "dcGridFollowingStorageTargetKw": dc_grid_following_storage_target,
        **task8_side_metrics,
        **load_side_metrics,
        "totalLoadKw": side_total_load_kw if side_total_load_kw is not None else load_kw,
        "dcRenewableToAcKw": dc_renewable_to_ac_kw,
        "dcTransferGroups": dc_transfer_groups_metric,
        "directStorageControlAction": direct_storage_plan["action"],
        "directStorageCorrectionRequestKw": _finite_number(
            direct_storage_plan.get("requestedKw")
        ),
        "directStorageCorrectionAcceptedKw": _finite_number(
            direct_storage_plan.get("acceptedKw")
        ),
        "directStorageCorrectionResidualKw": _finite_number(
            direct_storage_plan.get("residualKw")
        ),
        "directStorageAcEffectKw": direct_ac_storage_effect_kw,
        "directStorageAcdcEffectKw": direct_acdc_effect_kw,
        "directStorageDcGroups": copy.deepcopy(direct_storage_plan["groups"]),
        "directGridFormingAction": str(direct_grid_forming_plan.get("action", "hold")),
        "directGridFormingDcGroups": copy.deepcopy(
            direct_grid_forming_plan.get("dcGroups", [])
        ),
        "acComponentDispatch": copy.deepcopy(
            component_dispatch_plan.get("components", [])
        ),
        "duplicateDispatchCommands": copy.deepcopy(duplicate_commands),
        "directDispatchBlocks": copy.deepcopy(direct_dispatch_blocks),
        "dcBalanceControlGroupIds": (
            sorted(
                {
                    component.dc_transfer_group_id
                    for component in island_components
                }
            )
            if renewable_storage_island
            else sorted(
                {
                    str(row.get("dcTransferGroupId"))
                    for row in online_storage
                    if row.get("dcTransferGroupId")
                }
            )
        ),
        "onlineRenewableCount": len(renewable_metric_rows),
        "availableRenewable": available_renewable,
        "renewableCurrentKw": renewable_current,
        "windCurrentKw": wind_current,
        "pvCurrentKw": pv_current,
        "windAvailable": wind_available,
        "pvAvailable": pv_available,
        "windMaxAvailableKw": task8_side_metrics.get("totalWindMaxAvailableKw"),
        "pvMaxAvailableKw": task8_side_metrics.get("totalPvMaxAvailableKw"),
        "renewableMaxAvailableKw": task8_side_metrics.get(
            "totalRenewableMaxAvailableKw"
        ),
        "storageChargeAvailable": total_charge,
        "storageDischargeAvailable": total_discharge,
        "storageChargeBeforeDeratingKw": raw_charge_before_derating,
        "storageDischargeBeforeDeratingKw": raw_discharge_before_derating,
        "storageChargeDeratingActive": storage_charge_derating_active,
        "storageDischargeDeratingActive": storage_discharge_derating_active,
        "storageChargeDeratingFactor": storage_charge_derating_factor,
        "storageDischargeDeratingFactor": storage_discharge_derating_factor,
        "storageChargeDeratingLimitKw": raw_charge,
        "storageDischargeDeratingLimitKw": raw_discharge,
        "storageChargeDeratingExcessKw": storage_charge_derating_excess_kw,
        "storageDischargeDeratingExcessKw": storage_discharge_derating_excess_kw,
        "storageChargeDeratingHeadroomKw": storage_charge_derating_headroom_kw,
        "storageDischargeDeratingHeadroomKw": storage_discharge_derating_headroom_kw,
        "storageControlHorizonMinutes": storage_control_horizon_minutes,
        "storagePredictedChargeAfterAcdcKw": storage_predicted_charge_after_acdc_kw,
        "storageChargeDeratingResidualKw": storage_charge_derating_residual_kw,
        "storageHighSocDischargeRequestKw": storage_high_soc_discharge_request_kw,
        "storageChargeDeratingSafetyOverride": storage_charge_derating_safety_override,
        "storageChargeDeratingCurve": _derating_curve_payload(settings.storage_charge_derating_curve),
        "storageDischargeDeratingCurve": _derating_curve_payload(settings.storage_discharge_derating_curve),
        "storageChargeDeratingActuator": storage_charge_derating_actuator,
        "storageDischargeDeratingActuator": storage_discharge_derating_actuator,
        "storageChargeDeratingCandidateLimited": storage_charge_derating_candidate_limited,
        "storageDischargeDeratingCandidateLimited": storage_discharge_derating_candidate_limited,
        "storageChargeDeratingAcdcAllowed": storage_charge_derating_acdc_allowed,
        "storageDeratingConstraintOverride": storage_derating_constraint_override,
        "storageCurrentKw": metric_storage_current,
        "storageSoc": metric_storage_soc,
        "storageSocLowerLimit": storage_soc_lower_limit,
        "storageSocUpperLimit": storage_soc_upper_limit,
        "storageSocRegion": storage_soc_region,
        "socDeadband": settings.soc_deadband,
        "hydrogenClosedLoopEnabled": settings.hydrogen_closed_loop_enabled,
        "hydrogenPressureDeadbandRatio": settings.hydrogen_pressure_deadband_ratio,
        "hydrogenControl": hydrogen_plan,
        "configuredElectrolyzerCount": hydrogen_plan.get("configuredElectrolyzerCount", 0),
        "configuredFuelCellCount": hydrogen_plan.get("configuredFuelCellCount", 0),
        "configuredHydrogenStorageCount": hydrogen_plan.get("configuredHydrogenStorageCount", 0),
        "onlineElectrolyzerCount": hydrogen_plan.get("onlineElectrolyzerCount", 0),
        "onlineFuelCellCount": hydrogen_plan.get("onlineFuelCellCount", 0),
        "onlineHydrogenStorageCount": hydrogen_plan.get("onlineHydrogenStorageCount", 0),
        "electrolyzerCurrentKw": hydrogen_plan.get("electrolyzerCurrentKw"),
        "electrolyzerTargetKw": hydrogen_plan.get("electrolyzerTargetKw"),
        "electrolyzerFlowCurrentNm3h": hydrogen_plan.get("electrolyzerFlowCurrentNm3h"),
        "electrolyzerFlowTargetNm3h": hydrogen_plan.get("electrolyzerFlowTargetNm3h"),
        "fuelCellCurrentKw": hydrogen_plan.get("fuelCellCurrentKw"),
        "fuelCellTargetKw": hydrogen_plan.get("fuelCellTargetKw"),
        "fuelCellFlowCurrentNm3h": hydrogen_plan.get("fuelCellFlowCurrentNm3h"),
        "fuelCellFlowTargetNm3h": hydrogen_plan.get("fuelCellFlowTargetNm3h"),
        "hydrogenStoragePressureMpa": hydrogen_plan.get("hydrogenStoragePressureMpa"),
        "hydrogenStoragePressureLowGuardMpa": hydrogen_plan.get("hydrogenStoragePressureLowGuardMpa"),
        "hydrogenStoragePressureHighGuardMpa": hydrogen_plan.get("hydrogenStoragePressureHighGuardMpa"),
        "hydrogenStorageGasQuantityNm3": hydrogen_plan.get("hydrogenStorageGasQuantityNm3"),
        "hydrogenStorageSoc": hydrogen_plan.get("hydrogenStorageSoc"),
        "hydrogenStorageFlowNm3h": hydrogen_plan.get("hydrogenStorageFlowNm3h"),
        "lowerSocDeadbandActive": lower_soc_deadband_active,
        "upperSocDeadbandActive": upper_soc_deadband_active,
        "renewableUpperBoundaryDistance": renewable_upper_boundary_distance,
        "renewableStorageChargingActive": renewable_storage_charging_active,
        "renewableRaiseBlockedByDieselGuard": (
            renewable_raise_blocked_by_diesel_guard
        ),
        "renewableCurtailmentRequiredByCharging": (
            renewable_curtailment_required_by_charging
        ),
        "renewableDieselGuardCurtailRequestKw": (
            renewable_diesel_guard_curtail_request_kw
        ),
        "gridFormingStorageProtectionRatio": (
            settings.grid_forming_storage_protection_ratio
        ),
        "gridFormingStorageChargeProtectionKw": (
            grid_forming_storage_charge_protection_kw
        ),
        "gridFormingStorageDischargeProtectionKw": (
            grid_forming_storage_discharge_protection_kw
        ),
        "renewableStorageChargeExcessKw": renewable_storage_charge_excess_kw,
        "socAboveUpperDeadband": soc_above_upper_deadband,
        "socBelowLowerDeadband": soc_below_lower_deadband,
        "socUpperDeadbandThreshold": soc_upper_deadband_threshold,
        "socLowerDeadbandThreshold": soc_lower_deadband_threshold,
        "storageAboveUpperCount": len(storage_above_upper),
        "storageBelowLowerCount": len(storage_below_lower),
        "absorptionLimitKw": renewable_balance_limit,
        "renewableBalanceLimitKw": renewable_balance_limit,
        "renewableRecoveryStepRequestKw": renewable_recovery_step_request_kw,
        "renewableCurtailStepRequestKw": renewable_curtail_step_request_kw,
        "renewableCurtailCapacityStepKw": renewable_curtail_capacity_step_kw,
        "renewableChargeSafetyCurtailRequiredKw": renewable_charge_safety_curtail_required_kw,
        "renewableChargeSafetyCurtailRequestKw": renewable_charge_safety_curtail_request_kw,
        "renewableChargeSafetyCurtailDeliveredKw": renewable_charge_safety_curtail_delivered_kw,
        "renewableChargeSafetyCurtailShortfallKw": renewable_charge_safety_curtail_shortfall_kw,
        "renewableCurtailLimitedByStorageCharge": (
            renewable_curtail_step_request_kw + EPSILON < renewable_curtail_capacity_step_kw
        ),
        "renewableStorageCoordinationActive": renewable_storage_coordination_active,
        "renewableDischargeReplacementKw": renewable_discharge_replacement_kw,
        "renewableAbsorptionRequiredKw": renewable_absorption_required_kw,
        "storageRenewableCoordinationKw": storage_renewable_coordination_kw,
        "highSocStorageBalanceLimitKw": high_soc_storage_balance_limit_kw,
        "highSocStorageBalanceLimited": high_soc_storage_balance_limited,
        "highSocRequiredCurtailKw": high_soc_required_curtail_kw,
        "renewableDeltaKw": renewable_delta,
        "renewableBalancingDeltaKw": renewable_delta,
        "renewableTarget": renewable_target,
        "storageMinTargetKw": storage_min_target,
        "storageMaxTargetKw": storage_max_target,
        "dieselEmergencyChargeAllowed": diesel_emergency_charge_allowed,
        "emergencyChargeRequested": emergency_charge_requested,
        "extremeSocChargeRequested": soc_below_lower_deadband,
        "storageTarget": storage_target,
        "storageDesiredTargetKw": desired_storage_target,
        "storageCandidateTargetKw": storage_candidate_target,
        "storagePowerCapacityKw": storage_power_capacity,
        "storageControlAction": storage_control_action,
        "acdcControlAction": storage_control_action,
        "storageSwitchDeadbandAction": storage_deadband_action,
        "acdcCurrentKw": aggregate_converter_current_kw,
        "acdcCurrentForControlKw": converter_current_for_control,
        "acdcDesiredTargetKw": aggregate_converter_target_kw,
        "acdcTargetKw": aggregate_converter_target_kw,
        "acdcAdjustmentKw": (
            aggregate_converter_target_kw - aggregate_converter_current_kw
            if aggregate_converter_current_kw is not None
            else None
        ),
        "converterRatedCapacityKw": aggregate_converter_capacity_kw,
        "converterReversePowerForbidden": False,
        "converterReversePowerDetected": False,
        "converterBidirectionalEnabled": bool(all_converter_rows),
        "converterSystemPowerConvention": "P_DC",
        "converterSystemPositiveDirection": "DC_TO_AC",
        "converterPositiveDirection": AC_TO_DC,
        "converterDcPositiveDirection": "DC_TO_AC",
        "converterTargetLowerLimitKw": aggregate_converter_lower_limit_kw,
        "converterTargetUpperLimitKw": aggregate_converter_upper_limit_kw,
        "converterHardLimitApplied": converter_hard_limit_applied,
        "converterStorageConstraintTargetKw": storage_constrained_converter_target,
        "converterChargeSafetyTargetKw": converter_charge_safety_target,
        "converterChargeSafetyStorageKw": converter_charge_safety_storage_kw,
        "converterStorageConstraintConflict": converter_storage_constraint_conflict,
        "converterStepRatio": None,
        "converterBaseStepKw": None,
        "converterStepLimited": False,
        "gridFollowingStorageStepRatio": settings.storage_step_ratio,
        "storageEffectiveDecisionStepRatio": storage_effective_decision_step_ratio,
        "converterStepDirection": converter_step_direction,
        "converterExportStepDirection": converter_export_step_direction,
        "converterSlowIncrease": converter_slow_export_increase,
        "converterSlowExportIncrease": converter_slow_export_increase,
        "converterEmergencyStopActive": converter_emergency_stop_active,
        "converterIslandZeroOverride": converter_island_zero_override,
        "converterChargeDeratingSafetyOverride": converter_charge_derating_safety_override,
        "converterStepScale": None,
        "converterStepKw": None,
        "converterAppliedStepKw": converter_applied_step_kw,
        "converterStepLimited": False,
        "dieselResidual": diesel_residual,
        "dieselCurrentKw": diesel_current,
        "dieselMinKw": diesel_min,
        "dieselDownMarginKw": diesel_down_margin,
        "dieselUpMarginKw": diesel_up_margin,
        "dieselPowerProtectionRatio": settings.diesel_power_protection_ratio,
        "dieselDeadbandKw": diesel_deadband_kw,
        "dieselDeadbandLowerKw": diesel_deadband_lower_kw,
        "dieselDeadbandUpperKw": diesel_deadband_upper_kw,
        "dieselDeadbandActive": diesel_deadband_active,
        "dieselControlRegion": diesel_control_region,
        "dieselFloorDeficitKw": diesel_floor_deficit_kw,
        "dieselDeadbandEntryGapKw": diesel_deadband_entry_gap_kw,
        "dieselFloorCorrectionRequestKw": diesel_floor_correction_request_kw,
        "dieselBoundaryApproachActive": diesel_boundary_approach_active,
        "dieselBoundaryDistanceKw": diesel_boundary_distance_kw,
        "dieselTargetKw": diesel_target,
        "dieselBoundaryErrorKw": diesel_boundary_error,
        "dieselCapacityKw": diesel_capacity,
        "dieselCurrentViolationKw": current_diesel_violation,
        "dieselPredictedViolationKw": predicted_diesel_violation,
        "dieselViolationImproved": diesel_violation_improved,
        "dieselValidationStatus": diesel_validation_status,
        "candidatePowerEffectKw": candidate_effect,
        "curtailKw": curtail_kw,
        "loadKw": load_kw,
        "unservedKw": unserved_kw,
        "surplusKw": surplus_kw,
        "windSpeedKnown": wind_speed is not None,
        "solarIrradianceKnown": irradiance is not None,
        "recoveryMode": "capacity-step" if recovery_kw > EPSILON else "none",
        "renewableControlAction": renewable_control_action,
        "renewableCapacityKw": renewable_capacity,
        "renewableStepRatio": settings.step_coefficient,
        "renewableEffectiveDecisionStepRatio": renewable_effective_decision_step_ratio,
        "simulationControlIntervalSeconds": configured_settings.interval_seconds,
        "controlIntervalSeconds": configured_settings.interval_seconds,
        "controlIntervalClock": "simulation",
        "renewableStepDirection": renewable_step_direction,
        "renewableRecoveryStepScale": renewable_recovery_step_scale,
        "renewableRecoveryBoundaryScale": renewable_recovery_boundary_scale,
        "renewableRecoveryDeratingScale": renewable_recovery_derating_scale,
        "renewableRecoveryCapacityStepKw": renewable_recovery_capacity_step_kw,
        "renewableCurtailStepScale": renewable_curtail_step_scale,
        "renewableDeratingCurtailStepScale": renewable_derating_curtail_step_scale,
        "renewableDeratingCurtailStepRequestKw": renewable_derating_curtail_step_request_kw,
        "renewableStepScale": renewable_step_scale,
        "renewableEffectiveStepRatio": renewable_effective_step_ratio,
        "recoveryRequestedKw": recovery_kw,
        "recoveryKw": recovery_kw,
        "recoveryCandidateCount": recovery_candidate_count,
        "largeStepThresholdKw": settings.large_step_threshold_kw,
        "stepCoefficient": settings.step_coefficient,
        "storageConverterCount": len(converter_rows),
    }
    decision_log_detail = _business_decision_log_detail(
        command_rows,
        metrics,
        hydrogen_plan,
        settings,
        quality_payload,
        time_text=time_text,
        warnings=warnings,
    )
    decision_detail = decision_log_detail
    plan_finished = time.perf_counter()
    performance_diagnostics = {
        "phasesMs": {
            "inputProcessingMs": input_processing_seconds * 1000.0,
            "topologyAnalysisMs": topology_analysis_seconds * 1000.0,
            "strategyPreparationMs": strategy_preparation_seconds * 1000.0,
            "optimizationBuildMs": optimization_result.build_seconds * 1000.0,
            "optimizationSolveMs": optimization_result.solver_seconds * 1000.0,
            "storageBalanceMs": (
                optimization_result.storage_balance_seconds * 1000.0
            ),
            "optimizationPostprocessMs": (
                optimization_result.postprocess_seconds * 1000.0
            ),
            "optimizationTotalMs": optimization_total_seconds * 1000.0,
            "strategyPostprocessMs": (
                plan_finished - optimization_finished
            )
            * 1000.0,
            "planTotalMs": (plan_finished - plan_started) * 1000.0,
        },
        "solver": _optimization_performance_diagnostics(optimization_result),
    }
    return {
        "clockKey": clock_key,
        "time": time_text,
        "weather": {
            "minute": _number(clock.get("absolute_minute", clock.get("minute")), 0.0) or 0.0,
            "windSpeed": wind_speed,
            "windSpeedKnown": wind_speed is not None,
            "windMeasurementAvailable": bool(wind_measurement_status.get("available")),
            "windMeasurementReason": str(wind_measurement_status.get("reason", "")),
            "solarIrradiance": irradiance,
            "solarIrradianceKnown": irradiance is not None,
            "solarMeasurementAvailable": bool(solar_measurement_status.get("available")),
            "solarMeasurementReason": str(solar_measurement_status.get("reason", "")),
            "airTemp": air_temperature,
            "observedWindSpeed": observed_wind_speed,
            "observedSolarIrradiance": observed_irradiance,
            "observedAirTemp": observed_air_temperature,
            "loadKw": load_kw,
            "naturalLimitDiagnostics": renewable_natural_limit_diagnostics,
        },
        "commandRows": command_rows,
        "commands": commands,
        "runCommands": run_commands,
        "warnings": warnings,
        "metrics": metrics,
        "dataQuality": quality_payload,
        "decisionDetail": decision_detail,
        "decisionLogDetail": decision_log_detail,
        "performanceDiagnostics": performance_diagnostics,
    }

def _compact_log_number(value: Any, unit: str = "kW") -> str:
    number = _number(value)
    if number is None or not math.isfinite(number):
        return "--"
    if abs(number) < 0.005:
        number = 0.0
    digits = 1 if abs(number) >= 10.0 else 2
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return f"{text} {unit}" if unit else text

def _compact_decision_log_detail(plan: Mapping[str, Any]) -> List[str]:
    metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
    commands = plan.get("commands") if isinstance(plan.get("commands"), Sequence) else []
    run_commands = (
        plan.get("runCommands")
        if isinstance(plan.get("runCommands"), Sequence)
        else []
    )
    warnings = plan.get("warnings") if isinstance(plan.get("warnings"), Sequence) else []
    ren_cur = _compact_log_number(metrics.get("renewableCurrentKw"), "")
    ren_tgt = _compact_log_number(metrics.get("renewableTarget"), "")
    ren_max = _number(metrics.get("totalRenewableMaxAvailableKw"))
    ren_tgt_num = _number(metrics.get("totalRenewableTargetKw"))
    curtail_note = ""
    if ren_max is not None and ren_tgt_num is not None and (ren_max - ren_tgt_num) > 0.1:
        curtail_note = f"（弃电 {_compact_log_number(ren_max - ren_tgt_num, '')}）"
    diesel_cur = _compact_log_number(metrics.get("dieselCurrentKw"), "")
    diesel_tgt = _compact_log_number(metrics.get("dieselTargetKw"), "")
    stor_cur = _compact_log_number(metrics.get("storageCurrentKw"), "")
    stor_tgt = _compact_log_number(metrics.get("storageTarget"), "")
    cmd_parts = []
    if len(run_commands):
        cmd_parts.append(f"{len(run_commands)} 遥控")
    if len(commands):
        cmd_parts.append(f"{len(commands)} 遥调")
    cmd_text = "、".join(cmd_parts) if cmd_parts else "无指令"
    summary_line = (
        f"新能源 {ren_cur}→{ren_tgt} kW{curtail_note}｜"
        f"柴发 {diesel_cur}→{diesel_tgt} kW｜"
        f"储能 {stor_cur}→{stor_tgt} kW｜"
        f"指令 {cmd_text}"
    )
    detail = [summary_line]
    warning_text = [str(item).strip() for item in warnings if str(item).strip()]
    if warning_text:
        detail.append(f"提示：{warning_text[0]}" + (f"（另有 {len(warning_text) - 1} 条）" if len(warning_text) > 1 else ""))
    return detail

def _decision_log_level(plan: Mapping[str, Any]) -> str:
    quality = (
        plan.get("dataQuality")
        if isinstance(plan.get("dataQuality"), Mapping)
        else {}
    )
    warnings = plan.get("warnings")
    has_warning = bool(
        isinstance(warnings, Sequence)
        and not isinstance(warnings, (str, bytes))
        and any(str(item).strip() for item in warnings)
    )
    return "warn" if quality.get("status") != "ok" or has_warning else "info"

_RENEWABLE_READY_IDLE_STATUS = "请选择单次计算或启动实时控制。"

_RENEWABLE_AUTO_RESUMED_STATUS = "接收已就绪，新能源实时控制已自动恢复。"

_USER_CONTROL_BUSY_WAIT_SECONDS = 30.0

_COMPACT_TREND_FIELDS = (
    "sampleKey",
    "runId",
    "stepCount",
    "minute",
    "time",
    "loadKw",
    "dieselKw",
    "storageKw",
    "storageSocPercent",
    "renewableKw",
    "acLoadKw",
    "dcLoadKw",
    "dieselCurrentKw",
    "dieselTargetKw",
    "acRenewableCurrentKw",
    "acRenewableTargetKw",
    "acRenewableMaxAvailableKw",
    "acWindCurrentKw",
    "acWindTargetKw",
    "acWindMaxAvailableKw",
    "acPvCurrentKw",
    "acPvTargetKw",
    "acPvMaxAvailableKw",
    "acStorageCurrentKw",
    "acStorageTargetKw",
    "acStorageSocPercent",
    "dcRenewableCurrentKw",
    "dcRenewableTargetKw",
    "dcRenewableMaxAvailableKw",
    "dcWindCurrentKw",
    "dcWindTargetKw",
    "dcWindMaxAvailableKw",
    "dcPvCurrentKw",
    "dcPvTargetKw",
    "dcPvMaxAvailableKw",
    "dcStorageCurrentKw",
    "dcStorageTargetKw",
    "dcStorageSocPercent",
    "acGridFollowingStorageCurrentKw",
    "acGridFollowingStorageTargetKw",
    "acGridFollowingStorageSocPercent",
    "dcGridFollowingStorageCurrentKw",
    "dcGridFollowingStorageTargetKw",
    "dcGridFollowingStorageSocPercent",
    "acGridFormingStorageCurrentKw",
    "acGridFormingStorageTargetKw",
    "acGridFormingStorageSocPercent",
    "dcGridFormingStorageCurrentKw",
    "dcGridFormingStorageTargetKw",
    "dcGridFormingStorageSocPercent",
    "acDieselCurrentKw",
    "acDieselMinKw",
    "acDieselTargetKw",
    "dcDieselCurrentKw",
    "dcDieselMinKw",
    "dcDieselTargetKw",
    "totalRenewableCurrentKw",
    "totalRenewableTargetKw",
    "totalRenewableMaxAvailableKw",
    "totalWindCurrentKw",
    "totalWindTargetKw",
    "totalWindMaxAvailableKw",
    "totalPvCurrentKw",
    "totalPvTargetKw",
    "totalPvMaxAvailableKw",
    "totalStorageCurrentKw",
    "totalStorageTargetKw",
    "totalStorageSocPercent",
    "totalGridFollowingStorageCurrentKw",
    "totalGridFollowingStorageTargetKw",
    "totalGridFollowingStorageSocPercent",
    "totalGridFormingStorageCurrentKw",
    "totalGridFormingStorageTargetKw",
    "totalGridFormingStorageSocPercent",
    "totalDieselCurrentKw",
    "totalDieselMinKw",
    "totalDieselTargetKw",
    "totalLoadKw",
    "acdcCurrentKw",
    "acdcTargetKw",
    "electrolyzerCurrentKw",
    "electrolyzerTargetKw",
    "electrolyzerFlowCurrentNm3h",
    "electrolyzerFlowTargetNm3h",
    "fuelCellCurrentKw",
    "fuelCellTargetKw",
    "fuelCellFlowCurrentNm3h",
    "fuelCellFlowTargetNm3h",
    "hydrogenStoragePressureMpa",
    "hydrogenStoragePressureLowGuardMpa",
    "hydrogenStoragePressureHighGuardMpa",
    "hydrogenStorageGasQuantityNm3",
    "hydrogenStorageSocPercent",
    "hydrogenStorageFlowNm3h",
    "observedWindSpeed",
    "observedSolarIrradiance",
)

_TREND_ARRAY_ENCODING = "arrays-v1"

_TREND_IDENTITY_FIELDS = (
    "sampleKey",
    "runId",
    "stepCount",
    "minute",
    "time",
)

def _compact_trend_payload(
    trend: Sequence[Mapping[str, Any]],
    *,
    trend_encoding: str = "",
    include_fields: bool = True,
    fields: Sequence[str] = _COMPACT_TREND_FIELDS,
) -> Dict[str, Any]:
    field_names = tuple(str(field) for field in fields)
    if str(trend_encoding or "").strip().casefold() != _TREND_ARRAY_ENCODING:
        return {
            "trend": [
                {
                    key: _json_safe_copy(point.get(key))
                    for key in field_names
                    if key in point
                }
                for point in trend
            ]
        }

    rows: List[List[Any]] = []
    missing_rows: List[List[Any]] = []
    for row_index, point in enumerate(trend):
        rows.append(
            [
                _json_safe_copy(point.get(key))
                for key in field_names
            ]
        )
        missing_indices = [
            field_index
            for field_index, key in enumerate(field_names)
            if key not in point
        ]
        if missing_indices:
            missing_rows.append([row_index, missing_indices])

    payload: Dict[str, Any] = {
        "trendEncoding": _TREND_ARRAY_ENCODING,
        "trendRows": rows,
    }
    if include_fields:
        payload["trendFields"] = list(field_names)
    if missing_rows:
        payload["trendMissing"] = missing_rows
    return payload

def _compact_plan_for_ui(plan: Any) -> Any:
    """Project one optimizer plan onto fields consumed by the trainee browser."""

    if not (type(plan) is dict or isinstance(plan, Mapping)):
        return None
    payload = {
        key: _json_safe_copy(plan.get(key))
        for key in (
            "clockKey",
            "time",
            "weather",
            "commandRows",
            "metrics",
            "dataQuality",
        )
        if key in plan
    }
    commands = plan.get("commands")
    run_commands = plan.get("runCommands")
    payload["commandCount"] = (
        len(commands)
        if isinstance(commands, Sequence) and not isinstance(commands, (str, bytes))
        else 0
    )
    payload["runCommandCount"] = (
        len(run_commands)
        if isinstance(run_commands, Sequence) and not isinstance(run_commands, (str, bytes))
        else 0
    )
    return payload
