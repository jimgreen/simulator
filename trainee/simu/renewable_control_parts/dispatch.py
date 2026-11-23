"""renewable_control 拆分模块：构网/直接储能调度规划、交流分量校核与直流传输组重平衡。"""

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


def _plan_direct_grid_storage_dispatch(
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    base_converter_targets: Mapping[Tuple[str, str], float],
    settings: RenewableControlSettings,
    *,
    diesel_current_kw: float,
    diesel_min_kw: float,
    diesel_deadband_upper_kw: float,
    balance_effect_kw: float,
    enabled: bool,
) -> Dict[str, Any]:
    predicted_after_balance_kw = diesel_current_kw - balance_effect_kw
    diesel_boundary_distance_kw = max(
        0.0,
        predicted_after_balance_kw - diesel_deadband_upper_kw,
    )
    grid_rows = sorted(
        (
            row
            for row in storage_rows
            if row.get("role") == "grid_following"
        ),
        key=_grid_storage_sort_key,
    )
    storage_states: List[MutableMapping[str, Any]] = []
    for row in grid_rows:
        state = _grid_storage_target_margins(
            row,
            settings,
            diesel_boundary_distance_kw,
        )
        state.update(
            {
                "row": row,
                "key": (
                    str(row.get("dev_type", "")),
                    str(row.get("dev_name", "")),
                ),
                "side": str(row.get("connectionSide", "")),
                "groupId": str(row.get("dcTransferGroupId", "")),
            }
        )
        if not enabled and state.get("currentKw") is not None:
            state["targetKw"] = state["currentKw"]
            state["chargeMarginKw"] = 0.0
            state["dischargeMarginKw"] = 0.0
            state["positiveReductionMarginKw"] = 0.0
            state["protectiveDeltaKw"] = 0.0
        storage_states.append(state)

    converter_states = [
        _converter_direct_state(
            row,
            base_converter_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                row.get("currentKw"),
            ),
            settings,
        )
        for row in sorted(converter_rows, key=_converter_row_sort_key)
    ]

    if enabled:
        # AC protective corrections are direct. DC protective corrections are
        # paired with an equal same-group ACDC target change.
        for state in storage_states:
            if state.get("side") != "AC" or not state.get("eligible"):
                continue
            state["targetKw"] = _finite_number(state.get("targetKw"))

        for group_id in sorted(
            {
                str(state.get("groupId", ""))
                for state in storage_states
                if state.get("side") == "DC" and state.get("groupId")
            },
            key=_natural_topology_identity,
        ):
            group_states = [
                state
                for state in storage_states
                if state.get("side") == "DC"
                and state.get("groupId") == group_id
                and state.get("eligible")
            ]
            for increase_export in (True, False):
                candidates: List[MutableMapping[str, Any]] = []
                for state in group_states:
                    protective_delta_kw = _finite_number(state.get("protectiveDeltaKw"))
                    requested_kw = (
                        max(0.0, protective_delta_kw)
                        if increase_export
                        else max(0.0, -protective_delta_kw)
                    )
                    if requested_kw <= EPSILON:
                        continue
                    candidates.append({"state": state, "marginKw": requested_kw})
                if not candidates:
                    continue
                converter_accepted_kw = _apply_converter_group_adjustment(
                    converter_states,
                    group_id,
                    sum(_finite_number(item.get("marginKw")) for item in candidates),
                    increase_export=increase_export,
                )
                storage_allocations = _allocate_by_margin(
                    candidates,
                    converter_accepted_kw,
                    "marginKw",
                )
                for item, allocation_kw in zip(candidates, storage_allocations):
                    state = item["state"]
                    current_kw = _finite_number(state.get("currentKw"))
                    state["targetKw"] = (
                        current_kw + allocation_kw
                        if increase_export
                        else current_kw - allocation_kw
                    )

    def ac_effect_kw() -> float:
        return sum(
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw"))
            for state in storage_states
            if state.get("side") == "AC"
            and state.get("currentKw") is not None
            and state.get("targetKw") is not None
        )

    def converter_effect_kw() -> float:
        return sum(
            _finite_number(
                base_converter_targets.get(
                    (
                        str(state["row"].get("dev_type", "")),
                        str(state["row"].get("dev_name", "")),
                    ),
                    state.get("currentKw"),
                )
            )
            - _finite_number(state.get("targetKw"))
            for state in converter_states
            if state.get("targetKw") is not None
        )

    predicted_kw = (
        predicted_after_balance_kw
        - ac_effect_kw()
        - converter_effect_kw()
    )
    action = "hold"
    requested_kw = 0.0
    if enabled and predicted_kw < diesel_min_kw - EPSILON:
        action = "reduce_discharge"
        requested_kw = diesel_min_kw - predicted_kw
        ac_states = [
            state
            for state in storage_states
            if state.get("side") == "AC"
            and state.get("eligible")
            and _finite_number(state.get("positiveReductionMarginKw")) > EPSILON
        ]
        ac_allocations = _allocate_by_margin(
            ac_states,
            requested_kw,
            "positiveReductionMarginKw",
        )
        for state, allocation_kw in zip(ac_states, ac_allocations):
            state["targetKw"] = _finite_number(state.get("targetKw")) - allocation_kw
        remaining_kw = max(0.0, requested_kw - sum(ac_allocations))

        group_budgets: List[MutableMapping[str, Any]] = []
        for group_id in sorted(
            {
                str(state.get("groupId", ""))
                for state in storage_states
                if state.get("side") == "DC" and state.get("groupId")
            },
            key=_natural_topology_identity,
        ):
            storage_margin_kw = sum(
                _finite_number(state.get("positiveReductionMarginKw"))
                for state in storage_states
                if state.get("side") == "DC"
                and state.get("groupId") == group_id
                and state.get("eligible")
            )
            converter_margin_kw = sum(
                _finite_number(state.get("exportReductionMarginKw"))
                for state in converter_states
                if state.get("groupId") == group_id and state.get("eligible")
            )
            group_budgets.append(
                {
                    "groupId": group_id,
                    "marginKw": min(storage_margin_kw, converter_margin_kw),
                }
            )
        group_allocations = _allocate_by_margin(
            group_budgets,
            remaining_kw,
            "marginKw",
        )
        for group_budget, group_request_kw in zip(group_budgets, group_allocations):
            group_id = str(group_budget.get("groupId", ""))
            converter_accepted_kw = _apply_converter_group_adjustment(
                converter_states,
                group_id,
                group_request_kw,
                increase_export=False,
            )
            group_storage_states = [
                state
                for state in storage_states
                if state.get("side") == "DC"
                and state.get("groupId") == group_id
                and state.get("eligible")
            ]
            storage_allocations = _allocate_by_margin(
                group_storage_states,
                converter_accepted_kw,
                "positiveReductionMarginKw",
            )
            for state, allocation_kw in zip(group_storage_states, storage_allocations):
                state["targetKw"] = _finite_number(state.get("targetKw")) - allocation_kw
    elif enabled and predicted_kw > diesel_deadband_upper_kw + EPSILON:
        action = "increase_discharge"
        requested_kw = predicted_kw - diesel_deadband_upper_kw
        ac_states = [
            state
            for state in storage_states
            if state.get("side") == "AC"
            and state.get("eligible")
            and _finite_number(state.get("dischargeMarginKw")) > EPSILON
        ]
        ac_allocations = _allocate_by_margin(
            ac_states,
            requested_kw,
            "dischargeMarginKw",
        )
        for state, allocation_kw in zip(ac_states, ac_allocations):
            state["targetKw"] = _finite_number(state.get("targetKw")) + allocation_kw
        remaining_kw = max(0.0, requested_kw - sum(ac_allocations))

        group_budgets = []
        for group_id in sorted(
            {
                str(state.get("groupId", ""))
                for state in storage_states
                if state.get("side") == "DC" and state.get("groupId")
            },
            key=_natural_topology_identity,
        ):
            storage_margin_kw = sum(
                _finite_number(state.get("dischargeMarginKw"))
                for state in storage_states
                if state.get("side") == "DC"
                and state.get("groupId") == group_id
                and state.get("eligible")
            )
            converter_margin_kw = sum(
                _finite_number(state.get("exportMarginKw"))
                for state in converter_states
                if state.get("groupId") == group_id and state.get("eligible")
            )
            group_budgets.append(
                {
                    "groupId": group_id,
                    "marginKw": min(storage_margin_kw, converter_margin_kw),
                }
            )
        group_allocations = _allocate_by_margin(
            group_budgets,
            remaining_kw,
            "marginKw",
        )
        for group_budget, group_request_kw in zip(group_budgets, group_allocations):
            group_id = str(group_budget.get("groupId", ""))
            converter_accepted_kw = _apply_converter_group_adjustment(
                converter_states,
                group_id,
                group_request_kw,
                increase_export=True,
            )
            group_storage_states = [
                state
                for state in storage_states
                if state.get("side") == "DC"
                and state.get("groupId") == group_id
                and state.get("eligible")
            ]
            storage_allocations = _allocate_by_margin(
                group_storage_states,
                converter_accepted_kw,
                "dischargeMarginKw",
            )
            for state, allocation_kw in zip(group_storage_states, storage_allocations):
                state["targetKw"] = _finite_number(state.get("targetKw")) + allocation_kw

    final_ac_effect_kw = ac_effect_kw()
    final_converter_effect_kw = converter_effect_kw()
    final_predicted_kw = (
        predicted_after_balance_kw
        - final_ac_effect_kw
        - final_converter_effect_kw
    )
    accepted_correction_kw = (
        max(0.0, predicted_kw - final_predicted_kw)
        if action == "increase_discharge"
        else max(0.0, final_predicted_kw - predicted_kw)
        if action == "reduce_discharge"
        else 0.0
    )

    storage_targets = {
        state["key"]: state.get("targetKw")
        for state in storage_states
    }
    converter_targets = {
        (
            str(state["row"].get("dev_type", "")),
            str(state["row"].get("dev_name", "")),
        ): _clamp_converter_target_kw(state["row"], state.get("targetKw"))
        for state in converter_states
        if state.get("targetKw") is not None
    }
    group_summaries = []
    for group_id in sorted(
        {
            str(state.get("groupId", ""))
            for state in storage_states
            if state.get("side") == "DC" and state.get("groupId")
        },
        key=_natural_topology_identity,
    ):
        group_summaries.append(
            {
                "dcTransferGroupId": group_id,
                "storageDeltaKw": sum(
                    _finite_number(state.get("targetKw"))
                    - _finite_number(state.get("currentKw"))
                    for state in storage_states
                    if state.get("side") == "DC"
                    and state.get("groupId") == group_id
                    and state.get("currentKw") is not None
                    and state.get("targetKw") is not None
                ),
                "acdcDeltaKw": sum(
                    _finite_number(
                        base_converter_targets.get(
                            (
                                str(state["row"].get("dev_type", "")),
                                str(state["row"].get("dev_name", "")),
                            ),
                            state.get("currentKw"),
                        )
                    )
                    - _finite_number(state.get("targetKw"))
                    for state in converter_states
                    if state.get("groupId") == group_id
                    and state.get("targetKw") is not None
                ),
                "exportHeadroomKw": sum(
                    _finite_number(state.get("exportMarginKw"))
                    for state in converter_states
                    if state.get("groupId") == group_id
                ),
            }
        )

    return {
        "action": action,
        "requestedKw": requested_kw,
        "acceptedKw": accepted_correction_kw,
        "residualKw": max(0.0, requested_kw - accepted_correction_kw),
        "storageStates": {
            state["key"]: state
            for state in storage_states
        },
        "storageTargets": storage_targets,
        "converterTargets": converter_targets,
        "acEffectKw": final_ac_effect_kw,
        "acdcEffectKw": final_converter_effect_kw,
        "predictedDieselKw": final_predicted_kw,
        "groups": group_summaries,
    }

def _plan_direct_grid_forming_dispatch(
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    renewable_targets: Mapping[Tuple[str, str], Any],
    grid_storage_targets: Mapping[Tuple[str, str], Any],
    converter_targets: Mapping[Tuple[str, str], Any],
    projected_balance_targets: Mapping[Tuple[str, str], Any],
    settings: RenewableControlSettings,
    *,
    diesel_current_kw: float,
    diesel_min_kw: float,
    diesel_deadband_upper_kw: float,
    enabled: bool,
    dc_load_kw: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    renewable_target_map = {}
    for row in renewable_rows:
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        if key not in renewable_targets:
            continue
        renewable_target_map[key] = _number(
            renewable_targets.get(key),
            row.get("planningCurrentKw", row.get("currentKw")),
        )
    grid_target_map = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): _number(
            grid_storage_targets.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                row.get("currentKw"),
            )
        )
        for row in storage_rows
        if row.get("role") == "grid_following"
    }
    protective_grid_storage_keys = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        for row in storage_rows
        if row.get("role") == "grid_following"
        and _number(row.get("currentKw")) is not None
        and (
            _finite_number(row.get("currentKw"))
            < _grid_storage_signed_power_bounds_kw(row)[0] - EPSILON
            or _finite_number(row.get("currentKw"))
            > _grid_storage_signed_power_bounds_kw(row)[1] + EPSILON
        )
    }
    converter_target_map = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", ""))): (
            _clamp_converter_target_kw(
                row,
                converter_targets.get(
                    (str(row.get("dev_type", "")), str(row.get("dev_name", ""))),
                    row.get("currentKw"),
                ),
            )
        )
        for row in converter_rows
        if _number(row.get("currentKw")) is not None
    }
    balance_rows = sorted(
        (row for row in storage_rows if row.get("role") == "balance"),
        key=_grid_storage_sort_key,
    )
    direct_balance_rows = [
        row
        for row in balance_rows
        if row.get("commandable") and row.get("stateEligible")
    ]
    direct_balance_keys = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        for row in direct_balance_rows
    }
    protective_balance_keys = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        for row in balance_rows
        if _number(row.get("currentKw")) is not None
        and (
            _finite_number(row.get("currentKw"))
            < _grid_storage_signed_power_bounds_kw(row)[0] - EPSILON
            or _finite_number(row.get("currentKw"))
            > _grid_storage_signed_power_bounds_kw(row)[1] + EPSILON
        )
    }
    projected_balance_keys = {
        (str(key[0]), str(key[1]))
        for key in projected_balance_targets
        if isinstance(key, tuple) and len(key) == 2
    }
    balance_target_map: Dict[Tuple[str, str], Optional[float]] = {}
    for row in balance_rows:
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        current_kw = _number(row.get("currentKw"))
        requested_kw = _number(projected_balance_targets.get(key), current_kw)
        if current_kw is None:
            balance_target_map[key] = None
            continue
        if row.get("stateEligible"):
            signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            requested_target_kw = _finite_number(requested_kw, current_kw)
            soc = _number(row.get("soc"))
            soc_min = _number(row.get("socMin"))
            soc_max = _number(row.get("socMax"))
            emergency_charge_stop = bool(
                current_kw < signed_min_kw - EPSILON
                and soc is not None
                and soc_max is not None
                and soc >= soc_max - EPSILON
            )
            emergency_discharge_stop = bool(
                current_kw > signed_max_kw + EPSILON
                and soc is not None
                and soc_min is not None
                and soc <= soc_min + EPSILON
            )
            if emergency_charge_stop or emergency_discharge_stop:
                balance_target_map[key] = _clamp(
                    requested_target_kw,
                    signed_min_kw,
                    signed_max_kw,
                )
            elif current_kw < signed_min_kw - EPSILON:
                balance_target_map[key] = _clamp(
                    requested_target_kw,
                    current_kw,
                    signed_max_kw,
                )
            elif current_kw > signed_max_kw + EPSILON:
                balance_target_map[key] = _clamp(
                    requested_target_kw,
                    signed_min_kw,
                    current_kw,
                )
            else:
                balance_target_map[key] = _clamp(
                    requested_target_kw,
                    signed_min_kw,
                    signed_max_kw,
                )
        else:
            balance_target_map[key] = current_kw

    renewable_states = [
        {
            "row": row,
            "side": str(row.get("connectionSide", "")),
            "groupId": str(row.get("dcTransferGroupId", "")),
            "currentKw": _number(row.get("planningCurrentKw", row.get("currentKw"))),
            "targetKw": renewable_target_map.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            ),
        }
        for row in renewable_rows
        if (
            str(row.get("dev_type", "")),
            str(row.get("dev_name", "")),
        )
        in renewable_target_map
    ]
    grid_states = [
        {
            "row": row,
            "side": str(row.get("connectionSide", "")),
            "groupId": str(row.get("dcTransferGroupId", "")),
            "currentKw": _number(row.get("currentKw")),
            "targetKw": grid_target_map.get(
                (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            ),
        }
        for row in storage_rows
        if row.get("role") == "grid_following"
    ]
    converter_states: List[MutableMapping[str, Any]] = []
    for row in sorted(converter_rows, key=_converter_row_sort_key):
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        state = _converter_direct_state(
            row,
            converter_target_map.get(key, row.get("currentKw")),
            settings,
        )
        if state.get("currentKw") is None or state.get("targetKw") is None:
            continue
        converter_states.append({**state, "key": key})

    def sync_candidate_states() -> None:
        for state in renewable_states:
            row = state["row"]
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            state["targetKw"] = renewable_target_map.get(key, state.get("currentKw"))
        for state in grid_states:
            row = state["row"]
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            state["targetKw"] = grid_target_map.get(key, state.get("currentKw"))

    # A side-aware state-machine projection is authoritative: it may represent
    # an SOC hard-protection action or local-load absorption that cannot be
    # reconstructed from deltas alone. Only synthesize targets for directly
    # dispatchable DC balancing storage that does not already have such a
    # projection.
    def recalculate_dc_balance_targets() -> None:
        sync_candidate_states()
        group_ids = sorted(
            {
                str(row.get("dcTransferGroupId", ""))
                for row in balance_rows
                if row.get("connectionSide") == "DC"
                and str(row.get("dcTransferGroupId", ""))
                and (
                    (key := (
                        str(row.get("dev_type", "")),
                        str(row.get("dev_name", "")),
                    ))
                    in protective_balance_keys
                    or key in direct_balance_keys
                    and key not in projected_balance_keys
                )
            },
            key=_natural_topology_identity,
        )
        for group_id in group_ids:
            group_rows = [
                row
                for row in balance_rows
                if row.get("connectionSide") == "DC"
                and row.get("dcTransferGroupId") == group_id
                and (
                    (
                        str(row.get("dev_type", "")),
                        str(row.get("dev_name", "")),
                    )
                    in direct_balance_keys
                    and (
                        str(row.get("dev_type", "")),
                        str(row.get("dev_name", "")),
                    )
                    not in projected_balance_keys
                    or (
                        str(row.get("dev_type", "")),
                        str(row.get("dev_name", "")),
                    )
                    in protective_balance_keys
                )
            ]
            if not group_rows:
                continue
            group_renewables = [
                state
                for state in renewable_states
                if state.get("side") == "DC" and state.get("groupId") == group_id
            ]
            group_storage = [
                state
                for state in grid_states
                if state.get("side") == "DC" and state.get("groupId") == group_id
            ]
            group_converters = [
                state for state in converter_states if state.get("groupId") == group_id
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
            nonbalance_delta_kw = renewable_delta_kw + storage_delta_kw
            current_renewable_kw = sum(
                _finite_number(state.get("currentKw"))
                for state in group_renewables
            )
            current_grid_storage_kw = sum(
                _finite_number(state.get("currentKw"))
                for state in group_storage
            )
            local_sink_headroom_kw = max(
                0.0,
                _finite_number((dc_load_kw or {}).get(group_id))
                - current_renewable_kw
                - current_grid_storage_kw,
            )
            locally_absorbed_kw = min(
                max(0.0, nonbalance_delta_kw),
                local_sink_headroom_kw,
            )
            effective_nonbalance_delta_kw = (
                nonbalance_delta_kw - locally_absorbed_kw
            )
            export_delta_kw = sum(
                _converter_ac_injection_delta_kw(
                    state["row"],
                    state.get("currentKw"),
                    state.get("targetKw"),
                )
                for state in group_converters
            )
            balance_delta_kw = export_delta_kw - effective_nonbalance_delta_kw
            recalculated_targets, _indirect = _project_balance_storage_targets(
                group_rows,
                group_renewables,
                group_storage,
                group_converters,
                dc_balance_delta_by_group={group_id: balance_delta_kw},
            )
            balance_target_map.update(recalculated_targets)

    recalculate_dc_balance_targets()

    def ac_effect_kw() -> float:
        renewable_effect = sum(
            _finite_number(renewable_target_map.get(key), current_kw) - current_kw
            for row in renewable_rows
            if row.get("connectionSide") == "AC"
            and (current_kw := _number(row.get("planningCurrentKw", row.get("currentKw"))))
            is not None
            and (
                key := (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            )
        )
        grid_effect = sum(
            _finite_number(grid_target_map.get(key), current_kw) - current_kw
            for row in storage_rows
            if row.get("role") == "grid_following"
            and row.get("connectionSide") == "AC"
            and (current_kw := _number(row.get("currentKw"))) is not None
            and (
                key := (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            )
        )
        balance_effect = sum(
            _finite_number(balance_target_map.get(key), current_kw) - current_kw
            for row in balance_rows
            if row.get("connectionSide") == "AC"
            and (current_kw := _number(row.get("currentKw"))) is not None
            and (key := (
                str(row.get("dev_type", "")),
                str(row.get("dev_name", "")),
            ))
            in (
                direct_balance_keys | projected_balance_keys
            )
        )
        converter_effect = sum(
            _converter_ac_injection_delta_kw(
                state["row"],
                state.get("currentKw"),
                state.get("targetKw"),
            )
            for state in converter_states
        )
        return renewable_effect + grid_effect + balance_effect + converter_effect

    predicted_diesel_kw = diesel_current_kw - ac_effect_kw()
    action = "hold"
    if (
        enabled
        and diesel_current_kw > diesel_deadband_upper_kw + EPSILON
        and predicted_diesel_kw > diesel_deadband_upper_kw + EPSILON
    ):
        action = "increase_grid_forming_discharge"
        remaining_kw = predicted_diesel_kw - diesel_deadband_upper_kw
        ac_candidates: List[MutableMapping[str, Any]] = []
        for row in balance_rows:
            if (
                row.get("connectionSide") != "AC"
                or not row.get("commandable")
                or not row.get("stateEligible")
            ):
                continue
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            target_kw = _number(balance_target_map.get(key))
            if target_kw is None:
                continue
            _signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            ac_candidates.append(
                {
                    "row": row,
                    "key": key,
                    "marginKw": max(0.0, signed_max_kw - target_kw),
                }
            )
        allocations = _allocate_by_margin(ac_candidates, remaining_kw, "marginKw")
        for candidate, allocation_kw in zip(ac_candidates, allocations):
            key = candidate["key"]
            balance_target_map[key] = _finite_number(balance_target_map.get(key)) + allocation_kw
        remaining_kw = max(0.0, remaining_kw - sum(allocations))

        dc_group_ids = sorted(
            {
                str(row.get("dcTransferGroupId", ""))
                for row in balance_rows
                if row.get("connectionSide") == "DC"
                and row.get("commandable")
                and row.get("stateEligible")
                and str(row.get("dcTransferGroupId", ""))
            },
            key=_natural_topology_identity,
        )
        for group_id in dc_group_ids:
            if remaining_kw <= EPSILON:
                break
            balance_candidates = []
            for row in balance_rows:
                if (
                    row.get("connectionSide") != "DC"
                    or row.get("dcTransferGroupId") != group_id
                    or not row.get("commandable")
                    or not row.get("stateEligible")
                ):
                    continue
                key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
                target_kw = _number(balance_target_map.get(key))
                if target_kw is None:
                    continue
                _signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
                balance_candidates.append(
                    {
                        "row": row,
                        "key": key,
                        "marginKw": max(0.0, signed_max_kw - target_kw),
                    }
                )
            converter_margin_kw = sum(
                _finite_number(state.get("exportMarginKw"))
                for state in converter_states
                if state.get("groupId") == group_id
            )
            group_request_kw = min(
                remaining_kw,
                converter_margin_kw,
                sum(_finite_number(item.get("marginKw")) for item in balance_candidates),
            )
            exported_kw = _apply_converter_group_adjustment(
                converter_states,
                group_id,
                group_request_kw,
                increase_export=True,
            )
            balance_allocations = _allocate_by_margin(
                balance_candidates,
                exported_kw,
                "marginKw",
            )
            for candidate, allocation_kw in zip(balance_candidates, balance_allocations):
                key = candidate["key"]
                balance_target_map[key] = _finite_number(balance_target_map.get(key)) + allocation_kw
            remaining_kw = max(0.0, remaining_kw - sum(balance_allocations))

    predicted_after_forming_kw = diesel_current_kw - ac_effect_kw()
    helpful_diesel_raise_kw = sum(
        max(
            0.0,
            current_kw
            - _finite_number(renewable_target_map.get(key), current_kw),
        )
        for row in renewable_rows
        if row.get("connectionSide") == "AC"
        and (current_kw := _number(row.get("planningCurrentKw", row.get("currentKw"))))
        is not None
        and (key := (str(row.get("dev_type", "")), str(row.get("dev_name", ""))))
    )
    helpful_diesel_raise_kw += sum(
        max(
            0.0,
            current_kw
            - _finite_number(
                (
                    grid_target_map
                    if row.get("role") == "grid_following"
                    else balance_target_map
                ).get(key),
                current_kw,
            ),
        )
        for row in storage_rows
        if row.get("connectionSide") == "AC"
        and (current_kw := _number(row.get("currentKw"))) is not None
        and (key := (str(row.get("dev_type", "")), str(row.get("dev_name", ""))))
        and (
            row.get("role") == "grid_following"
            or key in direct_balance_keys
        )
    )
    helpful_diesel_raise_kw += sum(
        max(
            0.0,
            _finite_number(state.get("targetKw"))
            - _finite_number(state.get("currentKw")),
        )
        for state in converter_states
    )
    validation_floor_kw = (
        diesel_min_kw
        if diesel_current_kw >= diesel_min_kw - EPSILON
        else min(diesel_min_kw, diesel_current_kw + helpful_diesel_raise_kw)
    )
    if enabled and predicted_after_forming_kw < validation_floor_kw - EPSILON:
        action = "restore_diesel_floor"
        remaining_kw = validation_floor_kw - predicted_after_forming_kw
        converter_candidates = []
        for state in converter_states:
            current_kw = _finite_number(state.get("currentKw"))
            target_kw = _finite_number(state.get("targetKw"))
            rollback_margin_kw = max(0.0, current_kw - target_kw)
            converter_candidates.append(
                {"state": state, "marginKw": rollback_margin_kw}
            )
        converter_allocations = _allocate_by_margin(
            converter_candidates,
            remaining_kw,
            "marginKw",
        )
        for candidate, allocation_kw in zip(
            converter_candidates,
            converter_allocations,
        ):
            state = candidate["state"]
            state["targetKw"] = _clamp_converter_target_kw(
                state["row"],
                _finite_number(state.get("targetKw")) + allocation_kw,
            )
        remaining_kw = max(0.0, remaining_kw - sum(converter_allocations))
        recalculate_dc_balance_targets()

        rollback_candidates: List[MutableMapping[str, Any]] = []
        for row in renewable_rows:
            if row.get("connectionSide") != "AC":
                continue
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            current_kw = _number(row.get("planningCurrentKw", row.get("currentKw")))
            target_kw = _number(renewable_target_map.get(key))
            if current_kw is None or target_kw is None:
                continue
            rollback_candidates.append(
                {
                    "kind": "renewable",
                    "key": key,
                    "marginKw": max(0.0, target_kw - current_kw),
                }
            )
        for row in storage_rows:
            if row.get("connectionSide") != "AC":
                continue
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            if key in protective_grid_storage_keys:
                continue
            current_kw = _number(row.get("currentKw"))
            targets = (
                grid_target_map
                if row.get("role") == "grid_following"
                else balance_target_map
            )
            if row.get("role") == "balance" and key not in direct_balance_keys:
                continue
            target_kw = _number(targets.get(key))
            if current_kw is None or target_kw is None:
                continue
            rollback_candidates.append(
                {
                    "kind": str(row.get("role", "")),
                    "key": key,
                    "marginKw": max(0.0, target_kw - current_kw),
                }
            )
        rollback_allocations = _allocate_by_margin(
            rollback_candidates,
            remaining_kw,
            "marginKw",
        )
        for candidate, allocation_kw in zip(
            rollback_candidates,
            rollback_allocations,
        ):
            key = candidate["key"]
            if candidate["kind"] == "renewable":
                renewable_target_map[key] = _finite_number(
                    renewable_target_map.get(key)
                ) - allocation_kw
            elif candidate["kind"] == "grid_following":
                grid_target_map[key] = _finite_number(
                    grid_target_map.get(key)
                ) - allocation_kw
            else:
                balance_target_map[key] = _finite_number(
                    balance_target_map.get(key)
                ) - allocation_kw

        recalculate_dc_balance_targets()

    converter_target_map.update(
        {
            state["key"]: _clamp_converter_target_kw(
                state["row"],
                state.get("targetKw"),
            )
            for state in converter_states
        }
    )
    final_effect_kw = ac_effect_kw()
    final_predicted_diesel_kw = diesel_current_kw - final_effect_kw
    balance_states = {}
    for row in balance_rows:
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        current_kw = _number(row.get("currentKw"))
        target_kw = _number(balance_target_map.get(key), current_kw)
        signed_min_kw, signed_max_kw = (
            _grid_storage_signed_power_bounds_kw(row)
            if row.get("stateEligible")
            else (current_kw or 0.0, current_kw or 0.0)
        )
        balance_states[key] = {
            "row": row,
            "currentKw": current_kw,
            "targetKw": target_kw,
            "signedMinTargetKw": signed_min_kw,
            "signedMaxTargetKw": signed_max_kw,
            "directDispatchEligible": bool(
                enabled
                and row.get("commandable")
                and row.get("stateEligible")
                and row.get("set_type") == "p_set"
            ),
        }

    group_residuals = []
    group_ids = sorted(
        {
            str(row.get("dcTransferGroupId", ""))
            for row in (*renewable_rows, *storage_rows)
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", ""))
        },
        key=_natural_topology_identity,
    )
    for group_id in group_ids:
        renewable_delta_kw = sum(
            _finite_number(renewable_target_map.get(key), current_kw) - current_kw
            for row in renewable_rows
            if row.get("connectionSide") == "DC"
            and row.get("dcTransferGroupId") == group_id
            and (current_kw := _number(row.get("planningCurrentKw", row.get("currentKw"))))
            is not None
            and (
                key := (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            )
        )
        storage_delta_kw = sum(
            _finite_number(
                (
                    grid_target_map
                    if row.get("role") == "grid_following"
                    else balance_target_map
                ).get(key),
                current_kw,
            )
            - current_kw
            for row in storage_rows
            if row.get("connectionSide") == "DC"
            and row.get("dcTransferGroupId") == group_id
            and row.get("role") in {"grid_following", "balance"}
            and (current_kw := _number(row.get("currentKw"))) is not None
            and (
                key := (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            )
        )
        export_delta_kw = sum(
            _converter_ac_injection_delta_kw(
                state["row"],
                state.get("currentKw"),
                state.get("targetKw"),
            )
            for state in converter_states
            if state.get("groupId") == group_id
        )
        group_residuals.append(
            {
                "dcTransferGroupId": group_id,
                "renewableDeltaKw": renewable_delta_kw,
                "storageDeltaKw": storage_delta_kw,
                "acdcExportDeltaKw": export_delta_kw,
                "residualKw": renewable_delta_kw + storage_delta_kw - export_delta_kw,
            }
        )

    return {
        "action": action,
        "renewableTargets": renewable_target_map,
        "gridStorageTargets": grid_target_map,
        "balanceTargets": balance_target_map,
        "balanceStates": balance_states,
        "converterTargets": converter_target_map,
        "dieselEffectKw": final_effect_kw,
        "dieselTargetKw": final_predicted_diesel_kw,
        "dcGroups": group_residuals,
    }

def _storage_target_is_hard_protection(
    row: Mapping[str, Any],
    target_kw: Any,
) -> bool:
    current_kw = _number(row.get("currentKw"))
    parsed_target_kw = _number(target_kw)
    if (
        current_kw is None
        or parsed_target_kw is None
        or not row.get("limitsValid")
        or not row.get("socKnown")
    ):
        return False
    signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
    return bool(
        current_kw < signed_min_kw - EPSILON
        and parsed_target_kw > current_kw + EPSILON
        or current_kw > signed_max_kw + EPSILON
        and parsed_target_kw < current_kw - EPSILON
    )

def _clamp_direct_balance_targets_to_soc_bounds(
    storage_rows: Sequence[Mapping[str, Any]],
    balance_targets: Mapping[Tuple[str, str], Any],
) -> Dict[Tuple[str, str], Any]:
    """Keep directly controllable balance storage commands inside SOC limits.

    Indirect grid-forming projections may remain outside the instantaneous
    bound while the surrounding DC group is being rebalanced. That is useful
    feedback, but it is not safe to send as a direct p_set command. Direct
    balance storage therefore gets a final local SOC/power projection before
    AC-component and DC-group validation continue.
    """
    final_targets = dict(balance_targets)
    for row in storage_rows:
        if (
            row.get("role") != "balance"
            or row.get("set_type") != "p_set"
            or not row.get("commandable")
            or not row.get("stateEligible")
            or not row.get("limitsValid")
            or not row.get("socKnown")
        ):
            continue
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        current_kw = _number(row.get("currentKw"))
        target_kw = _number(final_targets.get(key), current_kw)
        if current_kw is None or target_kw is None:
            continue
        signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
        final_targets[key] = _clamp(target_kw, signed_min_kw, signed_max_kw)
    return final_targets

def _validate_dispatch_by_ac_component(
    topology: ResourceTopology,
    diesel_rows: Sequence[Mapping[str, Any]],
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    renewable_targets: Mapping[Tuple[str, str], Any],
    grid_storage_targets: Mapping[Tuple[str, str], Any],
    balance_targets: Mapping[Tuple[str, str], Any],
    converter_targets: Mapping[Tuple[str, str], Any],
    settings: RenewableControlSettings,
    *,
    dc_load_kw: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    final_renewable_targets = dict(renewable_targets)
    final_grid_storage_targets = dict(grid_storage_targets)
    final_balance_targets = dict(balance_targets)
    final_converter_targets = dict(converter_targets)

    diesels_by_component: Dict[str, List[Mapping[str, Any]]] = {}
    for row in diesel_rows:
        component_id = str(row.get("gridComponentId", ""))
        if (
            not component_id
            or not row.get("online")
            or _number(row.get("currentKw")) is None
        ):
            continue
        diesels_by_component.setdefault(component_id, []).append(row)

    group_component_ids = {
        group_id: str(group.ac_component_ids[0])
        for group_id, group in topology.dc_transfer_groups.items()
        if len(group.ac_component_ids) == 1
    }

    def row_key(row: Mapping[str, Any]) -> Tuple[str, str]:
        return str(row.get("dev_type", "")), str(row.get("dev_name", ""))

    def storage_target(row: Mapping[str, Any]) -> Optional[float]:
        key = row_key(row)
        targets = (
            final_grid_storage_targets
            if row.get("role") == "grid_following"
            else final_balance_targets
        )
        return _number(targets.get(key), row.get("currentKw"))

    # A diesel correction belongs only to its own AC electrical component.
    # When a DC transfer group reaches an AC component with no online diesel,
    # discard ordinary discharge/export candidates inherited from another
    # component. Keep SOC hard-protection moves and positive-ACDC correction.
    for group_id, component_id in sorted(
        group_component_ids.items(),
        key=lambda item: _natural_topology_identity(item[0]),
    ):
        if component_id in diesels_by_component:
            continue
        hard_storage_delta_kw = 0.0
        for row in storage_rows:
            if (
                row.get("connectionSide") != "DC"
                or str(row.get("dcTransferGroupId", "")) != group_id
                or row.get("role") not in {"grid_following", "balance"}
            ):
                continue
            key = row_key(row)
            current_kw = _number(row.get("currentKw"))
            target_kw = storage_target(row)
            if current_kw is None or target_kw is None:
                continue
            if _storage_target_is_hard_protection(row, target_kw):
                hard_storage_delta_kw += target_kw - current_kw
                continue
            if target_kw > current_kw + EPSILON:
                targets = (
                    final_grid_storage_targets
                    if row.get("role") == "grid_following"
                    else final_balance_targets
                )
                targets[key] = current_kw

        group_converters = [
            row
            for row in converter_rows
            if str(row.get("dcTransferGroupId", "")) == group_id
            and _number(row.get("currentKw")) is not None
        ]
        if not group_converters:
            continue
        current_total_kw = sum(
            _finite_number(row.get("currentKw")) for row in group_converters
        )
        signed_min_total_kw = sum(
            _converter_signed_bounds_kw(row)[0] for row in group_converters
        )
        signed_max_total_kw = sum(
            _converter_signed_bounds_kw(row)[1] for row in group_converters
        )
        target_total_kw = _clamp(
            current_total_kw - hard_storage_delta_kw,
            signed_min_total_kw,
            signed_max_total_kw,
        )
        allocations = _allocate_signed_converter_target(
            group_converters,
            target_total_kw,
        )
        for row, allocation_kw in zip(group_converters, allocations):
            final_converter_targets[row_key(row)] = allocation_kw

    def component_effect_kw(component_id: str) -> float:
        effect_kw = 0.0
        for row in renewable_rows:
            if (
                row.get("connectionSide") != "AC"
                or str(row.get("gridComponentId", "")) != component_id
            ):
                continue
            current_kw = _number(row.get("planningCurrentKw", row.get("currentKw")))
            target_kw = _number(final_renewable_targets.get(row_key(row)))
            if current_kw is not None and target_kw is not None:
                effect_kw += target_kw - current_kw
        for row in storage_rows:
            if (
                row.get("connectionSide") != "AC"
                or str(row.get("gridComponentId", "")) != component_id
                or row.get("role") not in {"grid_following", "balance"}
            ):
                continue
            current_kw = _number(row.get("currentKw"))
            target_kw = storage_target(row)
            if current_kw is not None and target_kw is not None:
                effect_kw += target_kw - current_kw
        for row in converter_rows:
            group_id = str(row.get("dcTransferGroupId", ""))
            if group_component_ids.get(group_id) != component_id:
                continue
            current_kw = _number(row.get("currentKw"))
            target_kw = _number(final_converter_targets.get(row_key(row)))
            if current_kw is not None and target_kw is not None:
                effect_kw += current_kw - target_kw
        return effect_kw

    def rollback_dc_group_source(group_id: str, request_kw: float) -> float:
        sink_candidates: List[MutableMapping[str, Any]] = []
        for row in storage_rows:
            if (
                row.get("connectionSide") != "DC"
                or str(row.get("dcTransferGroupId", "")) != group_id
                or row.get("role") not in {"grid_following", "balance"}
            ):
                continue
            current_kw = _number(row.get("currentKw"))
            target_kw = storage_target(row)
            if current_kw is None or target_kw is None:
                continue
            signed_min_kw, _signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            if (
                target_kw <= signed_min_kw + EPSILON
                or _storage_target_is_hard_protection(row, target_kw)
            ):
                continue
            sink_candidates.append(
                {
                    "kind": str(row.get("role", "")),
                    "key": row_key(row),
                    "marginKw": target_kw - signed_min_kw,
                }
            )
        sink_allocations = _allocate_by_margin(
            sink_candidates,
            request_kw,
            "marginKw",
        )
        for candidate, allocation_kw in zip(sink_candidates, sink_allocations):
            key = candidate["key"]
            targets = (
                final_grid_storage_targets
                if candidate["kind"] == "grid_following"
                else final_balance_targets
            )
            targets[key] = _finite_number(targets.get(key)) - allocation_kw
        absorbed_kw = sum(sink_allocations)
        remaining_request_kw = max(0.0, request_kw - absorbed_kw)

        candidates: List[MutableMapping[str, Any]] = []
        for row in storage_rows:
            if (
                row.get("connectionSide") != "DC"
                or str(row.get("dcTransferGroupId", "")) != group_id
                or row.get("role") not in {"grid_following", "balance"}
            ):
                continue
            current_kw = _number(row.get("currentKw"))
            target_kw = storage_target(row)
            if (
                current_kw is None
                or target_kw is None
                or target_kw <= current_kw + EPSILON
                or _storage_target_is_hard_protection(row, target_kw)
            ):
                continue
            candidates.append(
                {
                    "kind": str(row.get("role", "")),
                    "key": row_key(row),
                    "marginKw": target_kw - current_kw,
                }
            )
        for row in renewable_rows:
            if (
                row.get("connectionSide") != "DC"
                or str(row.get("dcTransferGroupId", "")) != group_id
            ):
                continue
            key = row_key(row)
            current_kw = _number(row.get("planningCurrentKw", row.get("currentKw")))
            target_kw = _number(final_renewable_targets.get(key))
            if current_kw is None or target_kw is None or target_kw <= current_kw + EPSILON:
                continue
            candidates.append(
                {
                    "kind": "renewable",
                    "key": key,
                    "marginKw": target_kw - current_kw,
                }
            )
        allocations = _allocate_by_margin(
            candidates,
            remaining_request_kw,
            "marginKw",
        )
        for candidate, allocation_kw in zip(candidates, allocations):
            key = candidate["key"]
            if candidate["kind"] == "renewable":
                final_renewable_targets[key] = _finite_number(
                    final_renewable_targets.get(key)
                ) - allocation_kw
            elif candidate["kind"] == "grid_following":
                final_grid_storage_targets[key] = _finite_number(
                    final_grid_storage_targets.get(key)
                ) - allocation_kw
            else:
                final_balance_targets[key] = _finite_number(
                    final_balance_targets.get(key)
                ) - allocation_kw
        return absorbed_kw + sum(allocations)

    component_rollbacks: Dict[str, float] = {}
    for component_id in sorted(diesels_by_component, key=_natural_topology_identity):
        component_diesels = diesels_by_component[component_id]
        diesel_current_kw = sum(
            _finite_number(row.get("currentKw")) for row in component_diesels
        )
        diesel_min_kw = sum(
            max(0.0, _finite_number(row.get("minKw"))) for row in component_diesels
        )
        diesel_capacity_kw = sum(
            max(0.0, _finite_number(row.get("capacityKw")))
            for row in component_diesels
        )
        deadband_upper_kw = (
            diesel_min_kw
            + settings.diesel_power_protection_ratio * diesel_capacity_kw
        )
        allowed_effect_kw = max(0.0, diesel_current_kw - deadband_upper_kw)
        rollback_request_kw = max(
            0.0,
            component_effect_kw(component_id) - allowed_effect_kw,
        )
        original_request_kw = rollback_request_kw

        for row in sorted(converter_rows, key=_converter_row_sort_key):
            if rollback_request_kw <= EPSILON:
                break
            group_id = str(row.get("dcTransferGroupId", ""))
            if group_component_ids.get(group_id) != component_id:
                continue
            key = row_key(row)
            current_kw = _number(row.get("currentKw"))
            target_kw = _number(final_converter_targets.get(key))
            if current_kw is None or target_kw is None:
                continue
            export_increase_kw = max(0.0, current_kw - target_kw)
            if export_increase_kw <= EPSILON:
                continue
            paired_rollback_kw = rollback_dc_group_source(
                group_id,
                min(rollback_request_kw, export_increase_kw),
            )
            if paired_rollback_kw <= EPSILON:
                continue
            final_converter_targets[key] = _clamp_converter_target_kw(
                row,
                target_kw + paired_rollback_kw,
            )
            rollback_request_kw = max(0.0, rollback_request_kw - paired_rollback_kw)

        ac_storage_candidates: List[MutableMapping[str, Any]] = []
        for row in storage_rows:
            if (
                row.get("connectionSide") != "AC"
                or str(row.get("gridComponentId", "")) != component_id
                or row.get("role") not in {"grid_following", "balance"}
            ):
                continue
            current_kw = _number(row.get("currentKw"))
            target_kw = storage_target(row)
            if (
                current_kw is None
                or target_kw is None
                or target_kw <= current_kw + EPSILON
                or _storage_target_is_hard_protection(row, target_kw)
            ):
                continue
            ac_storage_candidates.append(
                {
                    "row": row,
                    "key": row_key(row),
                    "marginKw": target_kw - current_kw,
                }
            )
        allocations = _allocate_by_margin(
            ac_storage_candidates,
            rollback_request_kw,
            "marginKw",
        )
        for candidate, allocation_kw in zip(ac_storage_candidates, allocations):
            row = candidate["row"]
            key = candidate["key"]
            targets = (
                final_grid_storage_targets
                if row.get("role") == "grid_following"
                else final_balance_targets
            )
            targets[key] = _finite_number(targets.get(key)) - allocation_kw
        rollback_request_kw = max(0.0, rollback_request_kw - sum(allocations))

        ac_renewable_candidates = []
        for row in renewable_rows:
            if (
                row.get("connectionSide") != "AC"
                or str(row.get("gridComponentId", "")) != component_id
            ):
                continue
            key = row_key(row)
            current_kw = _number(row.get("planningCurrentKw", row.get("currentKw")))
            target_kw = _number(final_renewable_targets.get(key))
            if current_kw is None or target_kw is None or target_kw <= current_kw + EPSILON:
                continue
            ac_renewable_candidates.append(
                {"key": key, "marginKw": target_kw - current_kw}
            )
        allocations = _allocate_by_margin(
            ac_renewable_candidates,
            rollback_request_kw,
            "marginKw",
        )
        for candidate, allocation_kw in zip(ac_renewable_candidates, allocations):
            key = candidate["key"]
            final_renewable_targets[key] = _finite_number(
                final_renewable_targets.get(key)
            ) - allocation_kw
        rollback_request_kw = max(0.0, rollback_request_kw - sum(allocations))
        component_rollbacks[component_id] = max(
            0.0,
            original_request_kw - rollback_request_kw,
        )

    for group_id in sorted(topology.dc_transfer_groups, key=_natural_topology_identity):
        group_renewables = [
            row
            for row in renewable_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
        ]
        group_converters = [
            row
            for row in converter_rows
            if str(row.get("dcTransferGroupId", "")) == group_id
        ]
        group_renewable_delta_kw = sum(
            _finite_number(final_renewable_targets.get(row_key(row)))
            - _finite_number(row.get("planningCurrentKw", row.get("currentKw")))
            for row in renewable_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
            and _number(row.get("planningCurrentKw", row.get("currentKw")))
            is not None
            and _number(final_renewable_targets.get(row_key(row))) is not None
        )
        group_grid_storage_delta_kw = sum(
            _finite_number(storage_target(row)) - _finite_number(row.get("currentKw"))
            for row in storage_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
            and row.get("role") == "grid_following"
            and _number(row.get("currentKw")) is not None
            and storage_target(row) is not None
        )
        group_balance_delta_kw = sum(
            _finite_number(storage_target(row)) - _finite_number(row.get("currentKw"))
            for row in storage_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
            and row.get("role") == "balance"
            and _number(row.get("currentKw")) is not None
            and storage_target(row) is not None
        )
        group_export_delta_kw = sum(
            _converter_ac_injection_delta_kw(
                row,
                row.get("currentKw"),
                final_converter_targets.get(row_key(row)),
            )
            for row in converter_rows
            if str(row.get("dcTransferGroupId", "")) == group_id
            and _number(row.get("currentKw")) is not None
            and _number(final_converter_targets.get(row_key(row))) is not None
        )
        local_sink_headroom_kw = max(
            0.0,
            _finite_number((dc_load_kw or {}).get(group_id))
            - sum(
                _finite_number(row.get("planningCurrentKw", row.get("currentKw")))
                for row in renewable_rows
                if row.get("connectionSide") == "DC"
                and str(row.get("dcTransferGroupId", "")) == group_id
            )
            - sum(
                _finite_number(row.get("currentKw"))
                for row in storage_rows
                if row.get("connectionSide") == "DC"
                and str(row.get("dcTransferGroupId", "")) == group_id
                and row.get("role") == "grid_following"
            ),
        )
        locally_absorbed_kw = min(
            max(0.0, group_renewable_delta_kw + group_grid_storage_delta_kw),
            local_sink_headroom_kw,
        )
        residual_kw = (
            group_renewable_delta_kw
            + group_grid_storage_delta_kw
            - locally_absorbed_kw
            + group_balance_delta_kw
            - group_export_delta_kw
        )
        if abs(residual_kw) <= EPSILON:
            continue
        candidates: List[MutableMapping[str, Any]] = []
        for row in storage_rows:
            if (
                row.get("connectionSide") != "DC"
                or str(row.get("dcTransferGroupId", "")) != group_id
                or row.get("role") not in {"balance", "grid_following"}
            ):
                continue
            current_kw = _number(row.get("currentKw"))
            target_kw = storage_target(row)
            if current_kw is None or target_kw is None:
                continue
            if _storage_target_is_hard_protection(row, target_kw):
                # A DC balance storage already outside its SOC power bound is
                # being moved back toward safety. Do not re-expand that
                # target just to close a temporary group residual; let the
                # same-group renewable or ACDC candidate absorb the residual.
                continue
            signed_min_kw, signed_max_kw = _grid_storage_signed_power_bounds_kw(row)
            lower_target_kw = current_kw if current_kw < signed_min_kw - EPSILON else signed_min_kw
            upper_target_kw = current_kw if current_kw > signed_max_kw + EPSILON else signed_max_kw
            margin_kw = (
                max(0.0, target_kw - lower_target_kw)
                if residual_kw > 0.0
                else max(0.0, upper_target_kw - target_kw)
            )
            if margin_kw <= EPSILON:
                continue
            candidates.append(
                {
                    "kind": str(row.get("role", "")),
                    "key": row_key(row),
                    "marginKw": margin_kw,
                }
            )
        allocations = _allocate_by_margin(
            candidates,
            abs(residual_kw),
            "marginKw",
        )
        for candidate, allocation_kw in zip(candidates, allocations):
            key = candidate["key"]
            targets = (
                final_grid_storage_targets
                if candidate["kind"] == "grid_following"
                else final_balance_targets
            )
            targets[key] = _finite_number(targets.get(key)) + (
                -allocation_kw if residual_kw > 0.0 else allocation_kw
            )

        remaining_residual_kw = max(0.0, abs(residual_kw) - sum(allocations))
        if remaining_residual_kw > EPSILON:
            renewable_candidates: List[MutableMapping[str, Any]] = []
            for row in renewable_rows:
                if (
                    row.get("connectionSide") != "DC"
                    or str(row.get("dcTransferGroupId", "")) != group_id
                ):
                    continue
                key = row_key(row)
                target_kw = _number(final_renewable_targets.get(key))
                capacity_kw = _number(row.get("capacityKw"))
                if target_kw is None or capacity_kw is None:
                    continue
                margin_kw = (
                    max(0.0, target_kw)
                    if residual_kw > 0.0
                    else max(0.0, capacity_kw - target_kw)
                )
                if margin_kw > EPSILON:
                    renewable_candidates.append(
                        {"key": key, "marginKw": margin_kw}
                    )
            renewable_allocations = _allocate_by_margin(
                renewable_candidates,
                remaining_residual_kw,
                "marginKw",
            )
            for candidate, allocation_kw in zip(
                renewable_candidates,
                renewable_allocations,
            ):
                key = candidate["key"]
                target_kw = _finite_number(final_renewable_targets.get(key))
                final_renewable_targets[key] = max(
                    0.0,
                    target_kw - allocation_kw
                    if residual_kw > 0.0
                    else target_kw + allocation_kw,
                )

            accepted_renewable_kw = sum(renewable_allocations)
            residual_kw = (
                residual_kw - accepted_renewable_kw
                if residual_kw > 0.0
                else residual_kw + accepted_renewable_kw
            )

    diesel_targets: Dict[str, float] = {}
    component_summaries: List[Dict[str, Any]] = []
    for component_id in sorted(diesels_by_component, key=_natural_topology_identity):
        component_diesels = diesels_by_component[component_id]
        diesel_current_kw = sum(
            _finite_number(row.get("currentKw")) for row in component_diesels
        )
        diesel_min_kw = sum(
            max(0.0, _finite_number(row.get("minKw"))) for row in component_diesels
        )
        diesel_capacity_kw = sum(
            max(0.0, _finite_number(row.get("capacityKw")))
            for row in component_diesels
        )
        effect_kw = component_effect_kw(component_id)
        predicted_kw = diesel_current_kw - effect_kw
        bounded_target_kw = _clamp(predicted_kw, diesel_min_kw, diesel_capacity_kw)
        per_device_targets = {
            str(row.get("dev_name", "")): _finite_number(row.get("currentKw"))
            for row in component_diesels
        }
        if bounded_target_kw < diesel_current_kw - EPSILON:
            candidates = [
                {
                    "name": str(row.get("dev_name", "")),
                    "marginKw": max(
                        0.0,
                        _finite_number(row.get("currentKw"))
                        - _finite_number(row.get("minKw")),
                    ),
                }
                for row in component_diesels
            ]
            allocations = _allocate_by_margin(
                candidates,
                diesel_current_kw - bounded_target_kw,
                "marginKw",
            )
            for candidate, allocation_kw in zip(candidates, allocations):
                per_device_targets[candidate["name"]] -= allocation_kw
        elif bounded_target_kw > diesel_current_kw + EPSILON:
            candidates = [
                {
                    "name": str(row.get("dev_name", "")),
                    "marginKw": max(
                        0.0,
                        _finite_number(row.get("capacityKw"))
                        - _finite_number(row.get("currentKw")),
                    ),
                }
                for row in component_diesels
            ]
            allocations = _allocate_by_margin(
                candidates,
                bounded_target_kw - diesel_current_kw,
                "marginKw",
            )
            for candidate, allocation_kw in zip(candidates, allocations):
                per_device_targets[candidate["name"]] += allocation_kw
        diesel_targets.update(per_device_targets)
        component_summaries.append(
            {
                "gridComponentId": component_id,
                "dieselCurrentKw": diesel_current_kw,
                "dieselMinKw": diesel_min_kw,
                "dieselCapacityKw": diesel_capacity_kw,
                "dieselDeadbandUpperKw": (
                    diesel_min_kw
                    + settings.diesel_power_protection_ratio
                    * diesel_capacity_kw
                ),
                "candidatePowerEffectKw": effect_kw,
                "predictedDieselKw": predicted_kw,
                "commandedDieselKw": bounded_target_kw,
                "rollbackKw": _finite_number(component_rollbacks.get(component_id)),
                "boundaryResidualKw": max(0.0, diesel_min_kw - predicted_kw),
            }
        )

    dc_group_summaries: List[Dict[str, Any]] = []
    for group_id in sorted(topology.dc_transfer_groups, key=_natural_topology_identity):
        group_renewables = [
            row
            for row in renewable_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
        ]
        group_storage = [
            row
            for row in storage_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
            and row.get("role") in {"grid_following", "balance"}
        ]
        group_converters = [
            row
            for row in converter_rows
            if str(row.get("dcTransferGroupId", "")) == group_id
        ]
        renewable_current_kw = _sum_known(
            row.get("planningCurrentKw", row.get("currentKw"))
            for row in group_renewables
        )
        renewable_target_kw = _sum_known(
            final_renewable_targets.get(
                row_key(row),
                row.get("planningCurrentKw", row.get("currentKw")),
            )
            for row in group_renewables
        )
        storage_current_kw = _sum_known(
            row.get("currentKw") for row in group_storage
        )
        storage_target_kw = _sum_known(
            storage_target(row) for row in group_storage
        )
        acdc_current_kw = _sum_known(
            _converter_system_power_kw(row, row.get("currentKw"))
            for row in group_converters
        )
        acdc_target_kw = _sum_known(
            _converter_system_power_kw(
                row,
                final_converter_targets.get(row_key(row), row.get("currentKw")),
            )
            for row in group_converters
        )
        if any(
            value is None
            for value in (
                renewable_current_kw,
                renewable_target_kw,
                storage_current_kw,
                storage_target_kw,
                acdc_current_kw,
                acdc_target_kw,
            )
        ):
            dc_group_summaries.append(
                {
                    "dcTransferGroupId": group_id,
                    "acComponentIds": list(
                        topology.dc_transfer_groups[group_id].ac_component_ids
                    ),
                    "renewableCurrentKw": renewable_current_kw,
                    "renewableTargetKw": renewable_target_kw,
                    "renewableDeltaKw": None,
                    "storageCurrentKw": storage_current_kw,
                    "storageTargetKw": storage_target_kw,
                    "storageDeltaKw": None,
                    "localLoadKw": _number((dc_load_kw or {}).get(group_id)),
                    "locallyAbsorbedKw": None,
                    "acdcCurrentKw": acdc_current_kw,
                    "acdcTargetKw": acdc_target_kw,
                    "acdcExportDeltaKw": None,
                    "residualKw": None,
                    "dataComplete": False,
                }
            )
            continue
        renewable_delta_kw = renewable_target_kw - renewable_current_kw
        storage_delta_kw = storage_target_kw - storage_current_kw
        grid_storage_delta_kw = sum(
            _finite_number(storage_target(row)) - _finite_number(row.get("currentKw"))
            for row in group_storage
            if row.get("role") == "grid_following"
        )
        balance_storage_delta_kw = sum(
            _finite_number(storage_target(row)) - _finite_number(row.get("currentKw"))
            for row in group_storage
            if row.get("role") == "balance"
        )
        acdc_export_delta_kw = sum(
            _converter_ac_injection_delta_kw(
                row,
                row.get("currentKw"),
                final_converter_targets.get(row_key(row), row.get("currentKw")),
            )
            for row in group_converters
        )
        local_load_value_kw = _finite_number((dc_load_kw or {}).get(group_id))
        local_sink_headroom_kw = max(
            0.0,
            local_load_value_kw
            - renewable_current_kw
            - sum(
                _finite_number(row.get("currentKw"))
                for row in group_storage
                if row.get("role") == "grid_following"
            ),
        )
        locally_absorbed_kw = min(
            max(0.0, renewable_delta_kw + grid_storage_delta_kw),
            local_sink_headroom_kw,
        )
        dc_group_summaries.append(
            {
                "dcTransferGroupId": group_id,
                "acComponentIds": list(
                    topology.dc_transfer_groups[group_id].ac_component_ids
                ),
                "renewableCurrentKw": renewable_current_kw,
                "renewableTargetKw": renewable_target_kw,
                "renewableDeltaKw": renewable_delta_kw,
                "storageCurrentKw": storage_current_kw,
                "storageTargetKw": storage_target_kw,
                "storageDeltaKw": storage_delta_kw,
                "localLoadKw": local_load_value_kw,
                "locallyAbsorbedKw": locally_absorbed_kw,
                "acdcCurrentKw": acdc_current_kw,
                "acdcTargetKw": acdc_target_kw,
                "acdcExportDeltaKw": acdc_export_delta_kw,
                "residualKw": (
                    renewable_delta_kw
                    + grid_storage_delta_kw
                    - locally_absorbed_kw
                    + balance_storage_delta_kw
                    - acdc_export_delta_kw
                ),
                "dataComplete": True,
            }
        )

    converter_rows_by_key = {
        row_key(row): row for row in converter_rows
    }
    return {
        "renewableTargets": final_renewable_targets,
        "gridStorageTargets": final_grid_storage_targets,
        "balanceTargets": final_balance_targets,
        "converterTargets": {
            key: _clamp_converter_target_kw(
                converter_rows_by_key.get(key, {}),
                target_kw,
            )
            for key, target_kw in final_converter_targets.items()
        },
        "dieselTargets": diesel_targets,
        "components": component_summaries,
        "dcGroups": dc_group_summaries,
        "dieselEffectKw": sum(
            _finite_number(row.get("candidatePowerEffectKw"))
            for row in component_summaries
        ),
        "dieselTargetKw": sum(
            _finite_number(row.get("predictedDieselKw"))
            for row in component_summaries
        ),
    }

def _metric_target(row: Mapping[str, Any], fallback_key: str = "currentKw") -> Optional[float]:
    for key in ("commandKw", "targetKw", "projectedTargetKw", fallback_key):
        value = _number(row.get(key))
        if value is not None and math.isfinite(value):
            return value
    return None

def _sum_metric(
    rows: Sequence[Mapping[str, Any]],
    key: str,
    *,
    fallback_key: str = "currentKw",
) -> float:
    total = 0.0
    for row in rows:
        value = (
            _metric_target(row, fallback_key)
            if key == "target"
            else _number(row.get(key))
        )
        if value is not None and math.isfinite(value):
            total += value
    return total

def _sum_optional_metric(
    rows: Sequence[Mapping[str, Any]],
    key: str,
) -> Optional[float]:
    if not rows:
        return 0.0
    values = [_number(row.get(key)) for row in rows]
    if any(value is None or not math.isfinite(value) for value in values):
        return None
    return sum(float(value) for value in values if value is not None)

def _task8_side_metrics(command_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    online = [row for row in command_rows if row.get("online")]

    def storage_inventory(side: str, role: str) -> List[Mapping[str, Any]]:
        return [
            row
            for row in command_rows
            if row.get("technology") == "storage"
            and row.get("role") == role
            and row.get("connectionSide") == side
        ]

    def renewable(side: str, technology: str) -> List[Mapping[str, Any]]:
        return [
            row
            for row in online
            if row.get("technology") == technology
            and row.get("connectionSide") == side
        ]

    def storage(side: str, role: str) -> List[Mapping[str, Any]]:
        return [
            row
            for row in online
            if row.get("role") == role
            and row.get("connectionSide") == side
        ]

    def diesel(side: str) -> List[Mapping[str, Any]]:
        return [
            row
            for row in online
            if row.get("category") == "柴油发电"
            and row.get("connectionSide") == side
        ]

    ac_wind = renewable("AC", "wind")
    dc_wind = renewable("DC", "wind")
    ac_pv = renewable("AC", "pv")
    dc_pv = renewable("DC", "pv")
    ac_grid = storage("AC", "grid_following")
    dc_grid = storage("DC", "grid_following")
    ac_balance = storage("AC", "balance")
    dc_balance = storage("DC", "balance")
    ac_grid_inventory = storage_inventory("AC", "grid_following")
    dc_grid_inventory = storage_inventory("DC", "grid_following")
    ac_balance_inventory = storage_inventory("AC", "balance")
    dc_balance_inventory = storage_inventory("DC", "balance")
    ac_diesel = diesel("AC")
    dc_diesel = diesel("DC")

    ac_wind_current = _sum_metric(ac_wind, "currentKw")
    ac_wind_target = _sum_metric(ac_wind, "target")
    dc_wind_current = _sum_metric(dc_wind, "currentKw")
    dc_wind_target = _sum_metric(dc_wind, "target")
    ac_pv_current = _sum_metric(ac_pv, "currentKw")
    ac_pv_target = _sum_metric(ac_pv, "target")
    dc_pv_current = _sum_metric(dc_pv, "currentKw")
    dc_pv_target = _sum_metric(dc_pv, "target")
    ac_wind_max_available = _sum_optional_metric(ac_wind, "weatherAvailableKw")
    dc_wind_max_available = _sum_optional_metric(dc_wind, "weatherAvailableKw")
    ac_pv_max_available = _sum_optional_metric(ac_pv, "weatherAvailableKw")
    dc_pv_max_available = _sum_optional_metric(dc_pv, "weatherAvailableKw")
    ac_renewable_max_available = _sum_known(
        (ac_wind_max_available, ac_pv_max_available)
    )
    dc_renewable_max_available = _sum_known(
        (dc_wind_max_available, dc_pv_max_available)
    )
    total_wind_max_available = _sum_known(
        (ac_wind_max_available, dc_wind_max_available)
    )
    total_pv_max_available = _sum_known(
        (ac_pv_max_available, dc_pv_max_available)
    )
    total_renewable_max_available = _sum_known(
        (ac_renewable_max_available, dc_renewable_max_available)
    )
    ac_renewable_current = ac_wind_current + ac_pv_current
    ac_renewable_target = ac_wind_target + ac_pv_target
    dc_renewable_current = dc_wind_current + dc_pv_current
    dc_renewable_target = dc_wind_target + dc_pv_target
    ac_grid_current = _sum_metric(ac_grid, "currentKw")
    ac_grid_target = _sum_metric(ac_grid, "target")
    dc_grid_current = _sum_metric(dc_grid, "currentKw")
    dc_grid_target = _sum_metric(dc_grid, "target")
    ac_balance_current = _sum_metric(ac_balance, "currentKw")
    ac_balance_target = _sum_metric(ac_balance, "target")
    dc_balance_current = _sum_metric(dc_balance, "currentKw")
    dc_balance_target = _sum_metric(dc_balance, "target")
    ac_grid_soc = _capacity_weighted_soc(ac_grid)
    dc_grid_soc = _capacity_weighted_soc(dc_grid)
    ac_balance_soc = _capacity_weighted_soc(ac_balance)
    dc_balance_soc = _capacity_weighted_soc(dc_balance)
    ac_diesel_current = _sum_metric(ac_diesel, "currentKw")
    ac_diesel_min = _sum_metric(ac_diesel, "minKw")
    ac_diesel_target = _sum_metric(ac_diesel, "target")
    dc_diesel_current = _sum_metric(dc_diesel, "currentKw")
    dc_diesel_min = _sum_metric(dc_diesel, "minKw")
    dc_diesel_target = _sum_metric(dc_diesel, "target")
    return {
        "onlineAcRenewableCount": len(ac_wind) + len(ac_pv),
        "onlineDcRenewableCount": len(dc_wind) + len(dc_pv),
        "onlineAcWindCount": len(ac_wind),
        "onlineDcWindCount": len(dc_wind),
        "onlineAcPvCount": len(ac_pv),
        "onlineDcPvCount": len(dc_pv),
        "acGridFollowingStorageCount": len(ac_grid_inventory),
        "dcGridFollowingStorageCount": len(dc_grid_inventory),
        "acGridFormingStorageCount": len(ac_balance_inventory),
        "dcGridFormingStorageCount": len(dc_balance_inventory),
        "onlineAcGridFollowingStorageCount": len(ac_grid),
        "onlineDcGridFollowingStorageCount": len(dc_grid),
        "onlineAcGridFormingStorageCount": len(ac_balance),
        "onlineDcGridFormingStorageCount": len(dc_balance),
        "onlineAcDieselCount": len(ac_diesel),
        "onlineDcDieselCount": len(dc_diesel),
        "acWindCurrentKw": ac_wind_current,
        "acWindTargetKw": ac_wind_target,
        "acWindMaxAvailableKw": ac_wind_max_available,
        "dcWindCurrentKw": dc_wind_current,
        "dcWindTargetKw": dc_wind_target,
        "dcWindMaxAvailableKw": dc_wind_max_available,
        "acPvCurrentKw": ac_pv_current,
        "acPvTargetKw": ac_pv_target,
        "acPvMaxAvailableKw": ac_pv_max_available,
        "dcPvCurrentKw": dc_pv_current,
        "dcPvTargetKw": dc_pv_target,
        "dcPvMaxAvailableKw": dc_pv_max_available,
        "acGridStorageCurrentKw": ac_grid_current,
        "acGridStorageTargetKw": ac_grid_target,
        "acGridStorageSoc": ac_grid_soc,
        "dcGridStorageCurrentKw": dc_grid_current,
        "dcGridStorageTargetKw": dc_grid_target,
        "dcGridStorageSoc": dc_grid_soc,
        "acBalanceStorageCurrentKw": ac_balance_current,
        "acBalanceStorageTargetKw": ac_balance_target,
        "dcBalanceStorageCurrentKw": dc_balance_current,
        "dcBalanceStorageTargetKw": dc_balance_target,
        "acBalanceStorageSoc": ac_balance_soc,
        "dcBalanceStorageSoc": dc_balance_soc,
        "acRenewableCurrentKw": ac_renewable_current,
        "acRenewableTargetKw": ac_renewable_target,
        "acRenewableMaxAvailableKw": ac_renewable_max_available,
        "dcRenewableCurrentKw": dc_renewable_current,
        "dcRenewableTargetKw": dc_renewable_target,
        "dcRenewableMaxAvailableKw": dc_renewable_max_available,
        "acGridFollowingStorageCurrentKw": ac_grid_current,
        "acGridFollowingStorageTargetKw": ac_grid_target,
        "acGridFollowingStorageSoc": ac_grid_soc,
        "dcGridFollowingStorageCurrentKw": dc_grid_current,
        "dcGridFollowingStorageTargetKw": dc_grid_target,
        "dcGridFollowingStorageSoc": dc_grid_soc,
        "acGridFormingStorageCurrentKw": ac_balance_current,
        "acGridFormingStorageTargetKw": ac_balance_target,
        "acGridFormingStorageSoc": ac_balance_soc,
        "dcGridFormingStorageCurrentKw": dc_balance_current,
        "dcGridFormingStorageTargetKw": dc_balance_target,
        "dcGridFormingStorageSoc": dc_balance_soc,
        "acStorageCurrentKw": ac_grid_current + ac_balance_current,
        "acStorageTargetKw": ac_grid_target + ac_balance_target,
        "acStorageSoc": _capacity_weighted_soc([*ac_grid, *ac_balance]),
        "dcStorageCurrentKw": dc_grid_current + dc_balance_current,
        "dcStorageTargetKw": dc_grid_target + dc_balance_target,
        "dcStorageSoc": _capacity_weighted_soc([*dc_grid, *dc_balance]),
        "acDieselCurrentKw": ac_diesel_current,
        "acDieselMinKw": ac_diesel_min,
        "acDieselTargetKw": ac_diesel_target,
        "dcDieselCurrentKw": dc_diesel_current,
        "dcDieselMinKw": dc_diesel_min,
        "dcDieselTargetKw": dc_diesel_target,
        "totalRenewableCurrentKw": ac_renewable_current + dc_renewable_current,
        "totalRenewableTargetKw": ac_renewable_target + dc_renewable_target,
        "totalRenewableMaxAvailableKw": total_renewable_max_available,
        "totalWindCurrentKw": ac_wind_current + dc_wind_current,
        "totalWindTargetKw": ac_wind_target + dc_wind_target,
        "totalWindMaxAvailableKw": total_wind_max_available,
        "totalPvCurrentKw": ac_pv_current + dc_pv_current,
        "totalPvTargetKw": ac_pv_target + dc_pv_target,
        "totalPvMaxAvailableKw": total_pv_max_available,
        "totalGridFollowingStorageCurrentKw": ac_grid_current + dc_grid_current,
        "totalGridFollowingStorageTargetKw": ac_grid_target + dc_grid_target,
        "totalGridFollowingStorageSoc": _capacity_weighted_soc([*ac_grid, *dc_grid]),
        "totalGridFormingStorageCurrentKw": ac_balance_current + dc_balance_current,
        "totalGridFormingStorageTargetKw": ac_balance_target + dc_balance_target,
        "totalGridFormingStorageSoc": _capacity_weighted_soc([*ac_balance, *dc_balance]),
        "totalStorageCurrentKw": (
            ac_grid_current + dc_grid_current + ac_balance_current + dc_balance_current
        ),
        "totalStorageTargetKw": (
            ac_grid_target + dc_grid_target + ac_balance_target + dc_balance_target
        ),
        "totalStorageSoc": _capacity_weighted_soc(
            [*ac_grid, *dc_grid, *ac_balance, *dc_balance]
        ),
        "totalDieselCurrentKw": ac_diesel_current + dc_diesel_current,
        "totalDieselMinKw": ac_diesel_min + dc_diesel_min,
        "totalDieselTargetKw": ac_diesel_target + dc_diesel_target,
    }

def _dc_transfer_group_metrics(
    topology: ResourceTopology,
    command_rows: Sequence[Mapping[str, Any]],
    dc_load_kw: Mapping[str, float],
    *,
    converter_step_ratio: float,
) -> Tuple[List[Dict[str, Any]], float]:
    groups: List[Dict[str, Any]] = []
    dc_renewable_to_ac_kw = 0.0
    active_group_ids = _active_dc_transfer_group_ids(topology, command_rows)
    rows_by_group: Dict[str, List[Mapping[str, Any]]] = {}
    for row in command_rows:
        group_id = str(row.get("dcTransferGroupId", ""))
        if group_id:
            rows_by_group.setdefault(group_id, []).append(row)

    for group_id in sorted(topology.dc_transfer_groups, key=_natural_topology_identity):
        rows = [row for row in rows_by_group.get(group_id, []) if row.get("online")]
        converters = [
            row
            for row in rows
            if _is_grid_converter_row(row)
            and row.get("commandable") is not False
        ]
        group = topology.dc_transfer_groups[group_id]
        dc_rows = [row for row in rows if row.get("connectionSide") == "DC"]
        renewables = [
            row for row in dc_rows if row.get("technology") in {"wind", "pv"}
        ]
        wind = [row for row in renewables if row.get("technology") == "wind"]
        pv = [row for row in renewables if row.get("technology") == "pv"]
        all_storage = [
            row
            for row in dc_rows
            if row.get("technology") == "storage"
            and row.get("resourceIdentityValid") is not False
        ]
        grid_storage = [row for row in dc_rows if row.get("role") == "grid_following"]
        balance_storage = [row for row in dc_rows if row.get("role") == "balance"]
        affected = sorted(
            (*renewables, *all_storage, *converters),
            key=lambda item: (
                _natural_topology_identity(item.get("dev_type", "")),
                _natural_topology_identity(item.get("dev_name", "")),
            ),
        )
        if group_id not in active_group_ids:
            reasons = {
                str(row.get("statusLabel", ""))
                for row in affected
                if str(row.get("statusLabel", "")).strip()
            }
            if not rows:
                reasons.add("no online resources in transfer group")
            if not converters:
                reasons.add("no active ACDC transfer path")
            if not dc_rows:
                reasons.add("no active DC resources in transfer group")
            renewable_current_kw = _sum_metric(renewables, "currentKw")
            renewable_target_kw = _sum_metric(renewables, "target")
            groups.append(
                _json_safe_copy(
                    {
                        "groupId": group_id,
                        "active": False,
                        "dcNodes": list(group.dc_nodes),
                        "acComponentIds": list(group.ac_component_ids),
                        "converterDevices": [
                            {"dev_type": dev_type, "dev_name": dev_name}
                            for dev_type, dev_name in group.converter_keys
                        ],
                        "currentWindKw": _sum_metric(wind, "currentKw"),
                        "targetWindKw": _sum_metric(wind, "target"),
                        "currentPvKw": _sum_metric(pv, "currentKw"),
                        "targetPvKw": _sum_metric(pv, "target"),
                        "currentRenewableKw": renewable_current_kw,
                        "targetRenewableKw": renewable_target_kw,
                        "localLoadKw": max(0.0, _finite_number(dc_load_kw.get(group_id))),
                        "currentGridStorageKw": _sum_metric(grid_storage, "currentKw"),
                        "targetGridStorageKw": _sum_metric(grid_storage, "target"),
                        "gridStorageSoc": _capacity_weighted_soc(grid_storage),
                        "currentBalanceStorageKw": _sum_metric(balance_storage, "currentKw"),
                        "targetBalanceStorageKw": sum(
                            _finite_number(row.get("projectedTargetKw"))
                            for row in balance_storage
                            if _number(row.get("projectedTargetKw")) is not None
                        ),
                        "balanceStorageSoc": _capacity_weighted_soc(balance_storage),
                        "currentAcdcExportKw": 0.0,
                        "finalAcdcExportKw": 0.0,
                        "acdcCapacityKw": 0.0,
                        "remainingAcdcHeadroomKw": 0.0,
                        "stepAcdcHeadroomKw": 0.0,
                        "renewableDeliveredThroughAcdcKw": 0.0,
                        "currentRenewableDeliveredThroughAcdcKw": 0.0,
                        "finalRenewableDeliveredThroughAcdcKw": 0.0,
                        "curtailedRenewableKw": max(
                            0.0,
                            renewable_current_kw - renewable_target_kw,
                        ),
                        "blockedRenewableKw": 0.0,
                        "reasons": sorted(reasons),
                        "affectedDevices": [
                            {
                                "dev_type": str(row.get("dev_type", "")),
                                "dev_name": str(row.get("dev_name", "")),
                                "side": str(row.get("connectionSide", "")),
                                "role": str(row.get("role", "")),
                                "technology": str(row.get("technology", "")),
                                "bus": str(row.get("busbarName", "")),
                            }
                            for row in affected
                        ],
                    }
                )
            )
            continue
        current_export_kw = sum(
            max(0.0, -_finite_number(row.get("currentKw")))
            for row in converters
            if row.get("currentKw") is not None
        )
        final_export_kw = sum(
            max(0.0, -_finite_number(row.get("commandKw")))
            for row in converters
            if _number(row.get("commandKw")) is not None
        )
        capacity_kw = sum(
            max(0.0, _finite_number(row.get("transferCapacityKw")))
            for row in converters
        )
        renewable_current_kw = _sum_metric(renewables, "currentKw")
        renewable_target_kw = _sum_metric(renewables, "target")
        local_load_kw = max(0.0, _finite_number(dc_load_kw.get(group_id)))
        current_storage_charge_kw = sum(
            max(0.0, -_finite_number(row.get("currentKw")))
            for row in all_storage
            if row.get("currentKw") is not None
        )
        final_storage_charge_kw = sum(
            max(0.0, -_finite_number(_metric_target(row)))
            for row in all_storage
        )
        current_renewable_exportable_kw = max(
            0.0,
            renewable_current_kw - local_load_kw - current_storage_charge_kw,
        )
        final_renewable_exportable_kw = max(
            0.0,
            renewable_target_kw - local_load_kw - final_storage_charge_kw,
        )
        delivered_through_acdc_kw = min(current_export_kw, current_renewable_exportable_kw)
        final_delivered_through_acdc_kw = min(final_export_kw, final_renewable_exportable_kw)
        dc_renewable_to_ac_kw += delivered_through_acdc_kw
        blocked_kw = sum(
            max(
                0.0,
                _finite_number(row.get("capacityKw"))
                - _finite_number(_metric_target(row)),
            )
            for row in renewables
        )
        step_headroom_kw = sum(
            min(
                max(
                    0.0,
                    _finite_number(row.get("transferCapacityKw"))
                    - max(0.0, -_finite_number(row.get("commandKw"))),
                ),
                max(
                    0.0,
                    converter_step_ratio
                    * _finite_number(row.get("transferCapacityKw")),
                ),
            )
            for row in converters
        )
        groups.append(
            _json_safe_copy(
                {
                    "groupId": group_id,
                    "active": True,
                    "dcNodes": list(group.dc_nodes),
                    "acComponentIds": list(group.ac_component_ids),
                    "converterDevices": [
                        {"dev_type": dev_type, "dev_name": dev_name}
                        for dev_type, dev_name in group.converter_keys
                    ],
                    "currentWindKw": _sum_metric(wind, "currentKw"),
                    "targetWindKw": _sum_metric(wind, "target"),
                    "currentPvKw": _sum_metric(pv, "currentKw"),
                    "targetPvKw": _sum_metric(pv, "target"),
                    "currentRenewableKw": renewable_current_kw,
                    "targetRenewableKw": renewable_target_kw,
                    "localLoadKw": local_load_kw,
                    "currentGridStorageKw": _sum_metric(grid_storage, "currentKw"),
                    "targetGridStorageKw": _sum_metric(grid_storage, "target"),
                    "gridStorageSoc": _capacity_weighted_soc(grid_storage),
                    "currentBalanceStorageKw": _sum_metric(balance_storage, "currentKw"),
                    "targetBalanceStorageKw": sum(
                        _finite_number(row.get("projectedTargetKw"))
                        for row in balance_storage
                        if _number(row.get("projectedTargetKw")) is not None
                    ),
                    "balanceStorageSoc": _capacity_weighted_soc(balance_storage),
                    "currentAcdcExportKw": current_export_kw,
                    "finalAcdcExportKw": final_export_kw,
                    "acdcCapacityKw": capacity_kw,
                    "remainingAcdcHeadroomKw": max(0.0, capacity_kw - final_export_kw),
                    "stepAcdcHeadroomKw": step_headroom_kw,
                    "renewableDeliveredThroughAcdcKw": delivered_through_acdc_kw,
                    "currentRenewableDeliveredThroughAcdcKw": delivered_through_acdc_kw,
                    "finalRenewableDeliveredThroughAcdcKw": final_delivered_through_acdc_kw,
                    "curtailedRenewableKw": max(0.0, renewable_current_kw - renewable_target_kw),
                    "blockedRenewableKw": blocked_kw,
                    "reasons": sorted(
                        {
                            str(row.get("statusLabel", ""))
                            for row in affected
                            if str(row.get("statusLabel", "")).strip()
                        }
                    ),
                    "affectedDevices": [
                        {
                            "dev_type": str(row.get("dev_type", "")),
                            "dev_name": str(row.get("dev_name", "")),
                            "side": str(row.get("connectionSide", "")),
                            "role": str(row.get("role", "")),
                            "technology": str(row.get("technology", "")),
                            "bus": str(row.get("busbarName", "")),
                        }
                        for row in affected
                    ],
                }
            )
        )
    return groups, dc_renewable_to_ac_kw

def _rebalance_dc_projection_targets(
    topology: ResourceTopology,
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    renewable_targets: Mapping[Tuple[str, str], Any],
    grid_storage_targets: Mapping[Tuple[str, str], Any],
    balance_targets: Mapping[Tuple[str, str], Any],
    converter_targets: Mapping[Tuple[str, str], Any],
    *,
    dc_load_kw: Optional[Mapping[str, float]] = None,
) -> Tuple[
    Dict[Tuple[str, str], Any],
    Dict[Tuple[str, str], Any],
    List[Dict[str, Any]],
]:
    """Close each DC group balance after AC-side rollback.

    Component validation can roll back an ACDC export or a renewable target
    after the first DC projection. Recompute the indirect balance-storage
    projection, and restore only a same-group ACDC export change when it is
    the remaining source of a group residual. Never borrow an actor from
    another DC transfer group.
    """
    final_balance_targets = dict(balance_targets)
    final_converter_targets = dict(converter_targets)
    group_summaries: List[Dict[str, Any]] = []

    def key_for(row: Mapping[str, Any]) -> Tuple[str, str]:
        return str(row.get("dev_type", "")), str(row.get("dev_name", ""))

    for group_id, group in sorted(
        topology.dc_transfer_groups.items(),
        key=lambda item: _natural_topology_identity(item[0]),
    ):
        group_renewables = [
            row
            for row in renewable_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
        ]
        group_storage = [
            row
            for row in storage_rows
            if row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) == group_id
            and row.get("role") in {"grid_following", "balance"}
        ]
        group_balance = [
            row
            for row in group_storage
            if row.get("role") == "balance"
            and row.get("stateEligible")
            and _number(row.get("currentKw")) is not None
        ]
        group_converters = [
            row
            for row in converter_rows
            if str(row.get("dcTransferGroupId", "")) == group_id
        ]

        def target_for(row: Mapping[str, Any]) -> Optional[float]:
            key = key_for(row)
            if row.get("role") == "grid_following":
                return _number(
                    grid_storage_targets.get(key), row.get("currentKw")
                )
            return _number(
                final_balance_targets.get(key), row.get("currentKw")
            )

        renewable_current_values = [
            _number(row.get("planningCurrentKw", row.get("currentKw")))
            for row in group_renewables
        ]
        renewable_target_values = [
            _number(
                renewable_targets.get(key_for(row)),
                row.get("planningCurrentKw", row.get("currentKw")),
            )
            for row in group_renewables
        ]
        storage_current_values = [
            _number(row.get("currentKw")) for row in group_storage
        ]
        storage_target_values = [target_for(row) for row in group_storage]
        converter_current_values = [
            _number(row.get("currentKw")) for row in group_converters
        ]
        converter_target_values = [
            _number(converter_targets.get(key_for(row)), row.get("currentKw"))
            for row in group_converters
        ]
        data_complete = not any(
            value is None
            for values in (
                renewable_current_values,
                renewable_target_values,
                storage_current_values,
                storage_target_values,
                converter_current_values,
                converter_target_values,
            )
            for value in values
        )
        local_load_value_kw = _finite_number((dc_load_kw or {}).get(group_id))
        if not data_complete:
            group_summaries.append(
                {
                    "dcTransferGroupId": group_id,
                    "acComponentIds": list(group.ac_component_ids),
                    "renewableCurrentKw": _sum_known(renewable_current_values),
                    "renewableTargetKw": _sum_known(renewable_target_values),
                    "renewableDeltaKw": None,
                    "storageCurrentKw": _sum_known(storage_current_values),
                    "storageTargetKw": _sum_known(storage_target_values),
                    "storageDeltaKw": None,
                    "localLoadKw": local_load_value_kw,
                    "locallyAbsorbedKw": None,
                    "acdcCurrentKw": _sum_known(
                        _converter_system_power_kw(row, value)
                        for row, value in zip(group_converters, converter_current_values)
                    ),
                    "acdcTargetKw": _sum_known(
                        _converter_system_power_kw(row, value)
                        for row, value in zip(group_converters, converter_target_values)
                    ),
                    "acdcExportDeltaKw": None,
                    "residualKw": None,
                    "dataComplete": False,
                }
            )
            continue

        renewable_delta = sum(
            target - current
            for target, current in zip(
                renewable_target_values,
                renewable_current_values,
            )
        )
        grid_storage_delta = sum(
            target - current
            for row, target, current in zip(
                group_storage,
                storage_target_values,
                storage_current_values,
            )
            if row.get("role") == "grid_following"
        )
        storage_delta = sum(
            target - current
            for target, current in zip(
                storage_target_values,
                storage_current_values,
            )
        )
        export_delta = sum(
            _converter_ac_injection_delta_kw(row, current, target)
            for row, current, target in zip(
                group_converters,
                converter_current_values,
                converter_target_values,
            )
        )
        local_sink_headroom_kw = max(
            0.0,
            local_load_value_kw
            - sum(
                current for current in renewable_current_values
            )
            - sum(
                current
                for row, current in zip(group_storage, storage_current_values)
                if row.get("role") == "grid_following"
            ),
        )
        locally_absorbed_kw = min(
            max(0.0, renewable_delta + grid_storage_delta),
            local_sink_headroom_kw,
        )
        residual = (
            renewable_delta
            + storage_delta
            - locally_absorbed_kw
            - export_delta
        )

        if group_balance and abs(residual) > EPSILON:
            remaining = abs(residual)
            candidates: List[Tuple[Mapping[str, Any], float]] = []
            for row in group_balance:
                key = key_for(row)
                current = _finite_number(row.get("currentKw"))
                target = _finite_number(final_balance_targets.get(key), current)
                signed_min, signed_max = _grid_storage_signed_power_bounds_kw(row)
                margin = (
                    max(0.0, signed_max - target)
                    if residual < 0.0
                    else max(0.0, target - signed_min)
                )
                if margin > EPSILON:
                    candidates.append((row, margin))
            total_margin = sum(margin for _, margin in candidates)
            if total_margin > EPSILON:
                accepted = min(remaining, total_margin)
                for row, margin in candidates:
                    allocation = accepted * margin / total_margin
                    key = key_for(row)
                    current = _finite_number(row.get("currentKw"))
                    target = _finite_number(final_balance_targets.get(key), current)
                    final_balance_targets[key] = target + (
                        allocation if residual < 0.0 else -allocation
                    )
                residual = residual + accepted if residual < 0.0 else residual - accepted

        # Re-read every final target after the balance-storage projection. The
        # projection above mutates final_balance_targets, so keeping the
        # original storage_target_values would make the reported residual
        # inconsistent with the targets that will be published.
        storage_target_values = [target_for(row) for row in group_storage]
        storage_delta = sum(
            target - current
            for target, current in zip(storage_target_values, storage_current_values)
        )
        grid_storage_delta = sum(
            target - current
            for row, target, current in zip(
                group_storage,
                storage_target_values,
                storage_current_values,
            )
            if row.get("role") == "grid_following"
        )
        locally_absorbed_kw = min(
            max(0.0, renewable_delta + grid_storage_delta),
            local_sink_headroom_kw,
        )
        residual = (
            renewable_delta
            + storage_delta
            - locally_absorbed_kw
            - export_delta
        )

        # If the same DC group still has a residual because its converter
        # target was reduced by AC-side validation, restore only that change.
        # Do not restore renewable or storage candidates here: those are the
        # local control actions selected by the side-specific policy.
        if abs(residual) > EPSILON:
            for row in group_converters:
                if abs(residual) <= EPSILON:
                    break
                key = key_for(row)
                current_kw = _number(row.get("currentKw"))
                target_kw = _number(final_converter_targets.get(key), current_kw)
                if current_kw is None or target_kw is None:
                    continue
                current_export_kw = max(
                    0.0,
                    _converter_ac_injection_kw(row, current_kw),
                )
                target_export_kw = max(
                    0.0,
                    _converter_ac_injection_kw(row, target_kw),
                )
                export_delta_kw = target_export_kw - current_export_kw
                if residual > 0.0 and export_delta_kw < -EPSILON:
                    restore_kw = min(residual, -export_delta_kw)
                    final_converter_targets[key] = _clamp_converter_target_kw(
                        row,
                        _converter_power_from_ac_injection_kw(
                            row,
                            target_export_kw + restore_kw,
                        ),
                    )
                    residual -= restore_kw
                elif residual < 0.0 and export_delta_kw > EPSILON:
                    restore_kw = min(-residual, export_delta_kw)
                    final_converter_targets[key] = _clamp_converter_target_kw(
                        row,
                        _converter_power_from_ac_injection_kw(
                            row,
                            max(0.0, target_export_kw - restore_kw),
                        ),
                    )
                    residual += restore_kw

        # The converter repair changes only the export term, but recompute all
        # terms once more so metrics and command validation use one equation.
        converter_target_values = [
            _number(final_converter_targets.get(key_for(row)), row.get("currentKw"))
            for row in group_converters
        ]
        export_delta = sum(
            _converter_ac_injection_delta_kw(row, current, target)
            for row, current, target in zip(
                group_converters,
                converter_current_values,
                converter_target_values,
            )
        )
        residual = (
            renewable_delta
            + storage_delta
            - locally_absorbed_kw
            - export_delta
        )

        group_summaries.append(
            {
                "dcTransferGroupId": group_id,
                "acComponentIds": list(group.ac_component_ids),
                "renewableCurrentKw": sum(renewable_current_values),
                "renewableTargetKw": sum(renewable_target_values),
                "renewableDeltaKw": renewable_delta,
                "storageCurrentKw": sum(storage_current_values),
                "storageTargetKw": sum(storage_target_values),
                "storageDeltaKw": storage_delta,
                "localLoadKw": local_load_value_kw,
                "locallyAbsorbedKw": locally_absorbed_kw,
                "acdcCurrentKw": sum(
                    _finite_number(_converter_system_power_kw(row, value))
                    for row, value in zip(group_converters, converter_current_values)
                ),
                "acdcTargetKw": sum(
                    _finite_number(_converter_system_power_kw(row, value))
                    for row, value in zip(group_converters, converter_target_values)
                ),
                "acdcExportDeltaKw": export_delta,
                "residualKw": residual,
                "dataComplete": True,
            }
        )
    return final_balance_targets, final_converter_targets, group_summaries

def _task8_decision_detail(
    command_rows: Sequence[Mapping[str, Any]],
    metrics: Mapping[str, Any],
) -> List[str]:
    rows = sorted(
        command_rows,
        key=lambda row: (
            _natural_topology_identity(row.get("connectionSide", "")),
            _natural_topology_identity(row.get("dcTransferGroupId", "")),
            _natural_topology_identity(row.get("dev_type", "")),
            _natural_topology_identity(row.get("dev_name", "")),
        ),
    )

    def path_text(row: Mapping[str, Any]) -> str:
        path = row.get("activePath") or row.get("structuralPath") or ()
        return ">".join(f"{dev_type}:{dev_name}" for dev_type, dev_name in path) or "local"

    def device_text(row: Mapping[str, Any]) -> str:
        current_kw = _number(row.get("currentKw"))
        target_kw = _metric_target(row)
        candidate_delta = (
            target_kw - current_kw
            if current_kw is not None and target_kw is not None
            else None
        )
        accepted_delta = candidate_delta if candidate_delta is not None else 0.0
        limit = (
            row.get("transferCapacityKw")
            if _is_grid_converter_row(row)
            else row.get("capacityKw", row.get("maxDischargePowerKw"))
        )
        return (
            f"device={row.get('dev_name', '')} type={row.get('dev_type', '')} "
            f"side={row.get('connectionSide', '')} bus={row.get('busbarName', '')} "
            f"group={row.get('dcTransferGroupId', '')} path={path_text(row)} "
            f"currentKw={current_kw if current_kw is not None else 'None'} "
            f"candidateDeltaKw={candidate_delta if candidate_delta is not None else 'None'} "
            f"acceptedDeltaKw={accepted_delta} limit={limit if limit is not None else 'None'} "
            f"reason={row.get('statusLabel', 'hold')}"
        )

    detail: List[str] = [
        f"phase=topology {device_text(row)}"
        for row in rows
        if row.get("technology") in {"wind", "pv", "storage"}
        or row.get("category") == "柴油发电"
        or _is_grid_converter_row(row)
    ]
    detail.extend(
        [
            "phase=side/role totals "
            f"side=AC windCurrentKw={metrics.get('acWindCurrentKw')} "
            f"pvCurrentKw={metrics.get('acPvCurrentKw')} "
            f"gridStorageCurrentKw={metrics.get('acGridStorageCurrentKw')} "
            f"balanceStorageCurrentKw={metrics.get('acBalanceStorageCurrentKw')}",
            "phase=side/role totals "
            f"side=DC windCurrentKw={metrics.get('dcWindCurrentKw')} "
            f"pvCurrentKw={metrics.get('dcPvCurrentKw')} "
            f"gridStorageCurrentKw={metrics.get('dcGridStorageCurrentKw')} "
            f"balanceStorageCurrentKw={metrics.get('dcBalanceStorageCurrentKw')}",
        ]
    )
    converters = [
        row for row in rows if _is_grid_converter_row(row)
    ]
    detail.extend(
        [f"phase=ACDC balance candidate {device_text(row)}" for row in converters]
        or ["phase=ACDC balance candidate device=none side= bus= group= path=local currentKw=None candidateDeltaKw=None acceptedDeltaKw=0.0 limit=None reason=hold"]
    )
    detail.extend(
        f"phase=direct-storage allocation {device_text(row)}"
        for row in rows
        if row.get("role") == "grid_following"
    )
    detail.extend(
        "phase=ac-component validation "
        f"component={row.get('gridComponentId', '')} "
        f"dieselCurrentKw={row.get('dieselCurrentKw')} "
        f"dieselMinKw={row.get('dieselMinKw')} "
        f"candidateEffectKw={row.get('candidatePowerEffectKw')} "
        f"predictedDieselKw={row.get('predictedDieselKw')} "
        f"commandedDieselKw={row.get('commandedDieselKw')} "
        f"rollbackKw={row.get('rollbackKw')} "
        f"residualKw={row.get('boundaryResidualKw')}"
        for row in metrics.get("acComponentDispatch", [])
        if (type(row) is dict or isinstance(row, Mapping))
    )
    detail.extend(
        "phase=direct-grid-forming group "
        f"group={row.get('dcTransferGroupId', '')} "
        f"renewableDeltaKw={row.get('renewableDeltaKw')} "
        f"storageDeltaKw={row.get('storageDeltaKw')} "
        f"acdcExportDeltaKw={row.get('acdcExportDeltaKw')} "
        f"residualKw={row.get('residualKw')}"
        for row in metrics.get("directGridFormingDcGroups", [])
        if (type(row) is dict or isinstance(row, Mapping))
    )
    detail.extend(
        "phase=direct-dispatch blocked "
        f"device={row.get('dev_name', '')} type={row.get('dev_type', '')} "
        f"side={row.get('side', '')} group={row.get('dcTransferGroupId', '')} "
        f"reason={row.get('reason', '')}"
        for row in metrics.get("directDispatchBlocks", [])
        if (type(row) is dict or isinstance(row, Mapping))
    )
    for row in rows:
        if row.get("technology") not in {"wind", "pv"}:
            continue
        sink = (
            "same-group-acdc"
            if row.get("connectionSide") == "DC" and row.get("dcTransferGroupId")
            else "local-ac"
            if row.get("connectionSide") == "AC"
            else "local"
        )
        detail.append(
            f"phase=renewable sink allocation legalSink={sink} "
            f"acdcReservationKw={metrics.get('dcRenewableToAcKw')} {device_text(row)}"
        )
    detail.extend(
        f"phase=unified validation {device_text(row)}"
        for row in rows
        if row.get("strategyCommand") is not False or row.get("role") == "balance"
    )
    commands = [
        row
        for row in rows
        if row.get("online")
        and row.get("commandable") is not False
        and row.get("strategyCommand") is not False
        and row.get("set_type")
    ]
    for loop in ("open-loop-preview", "closed-loop-command"):
        if not commands:
            detail.append(
                f"phase=dispatch result loop={loop} device=none side= bus= group= path=local currentKw=None candidateDeltaKw=None acceptedDeltaKw=0.0 limit=None reason=hold"
            )
            continue
        detail.extend(
            f"phase=dispatch result loop={loop} {device_text(row)}"
            for row in commands
        )
    return detail

def _source_label(source: str) -> str:
    return {
        "trainee-live": "学员台实时交换数据",
        "trainee-cache": "学员台最近一次有效交换数据",
        "remote": "实时快照",
        "cached": "最近一次有效实时快照",
        "local": "学员台本地数据",
    }.get(source, source)

def _optimization_supported_row(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("technology") in {"wind", "pv", "storage"}
        or row.get("category") == "柴油发电"
        or _is_grid_converter_row(row)
    )

def _apply_optimization_targets(
    command_rows: Sequence[MutableMapping[str, Any]],
    result: RenewableDispatchOptimizationResult,
    *,
    apply_targets: bool = True,
) -> None:
    island_by_device = {
        key: island.island_id
        for island in result.islands
        for key in island.device_keys
    }
    lower_by_device = {
        key: value
        for island in result.islands
        for key, value in island.active_lower_by_device.items()
    }
    upper_by_device = {
        key: value
        for island in result.islands
        for key, value in island.active_upper_by_device.items()
    }
    failed_devices = {
        key
        for island in result.islands
        if not island.success
        for key in island.device_keys
    }
    failed_devices.update(result.unassigned_devices)
    for row in command_rows:
        if not _optimization_supported_row(row):
            continue
        key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        current = _number(row.get("planningCurrentKw", row.get("currentKw")))
        optimization_target = _number(result.targets.get(key))
        optimization_lower = _number(lower_by_device.get(key))
        optimization_upper = _number(upper_by_device.get(key))
        target = optimization_target
        if _is_grid_converter_row(row):
            # Optimizer targets are positive DC-to-AC. Command rows retain the
            # P_AC convention until dispatch selects p_ac_set or p_dc_set.
            if optimization_lower is not None and optimization_upper is not None:
                row["optimizationLowerSystemKw"] = optimization_lower
                row["optimizationUpperSystemKw"] = optimization_upper
                converted_bounds = (
                    converter_power_in_ac_terminal_convention(
                        optimization_lower,
                        _converter_direction(row),
                        "P_DC",
                    ),
                    converter_power_in_ac_terminal_convention(
                        optimization_upper,
                        _converter_direction(row),
                        "P_DC",
                    ),
                )
                row["optimizationLowerKw"] = min(converted_bounds)
                row["optimizationUpperKw"] = max(converted_bounds)
            if optimization_target is not None:
                row["optimizationSuggestedSystemKw"] = optimization_target
                target = converter_power_in_ac_terminal_convention(
                    optimization_target,
                    _converter_direction(row),
                    "P_DC",
                )
        elif optimization_lower is not None and optimization_upper is not None:
            row["optimizationLowerKw"] = optimization_lower
            row["optimizationUpperKw"] = optimization_upper
        row["optimizationIslandId"] = island_by_device.get(key, "")
        row["optimizationStatus"] = (
            "optimal"
            if target is not None
            else "failed"
            if key in failed_devices
            else "not-dispatchable"
        )
        row["optimizationSuggestedKw"] = target
        if not apply_targets:
            continue
        if target is None:
            row["strategyCommand"] = False
            row["commandKw"] = current
            if row.get("technology") == "storage":
                row["targetKw"] = current
                row["projectedTargetKw"] = current
            continue
        direct_dispatch = bool(row.get("commandable") and row.get("set_type"))
        row["commandKw"] = target
        row["targetKw"] = target
        if row.get("technology") == "storage":
            row["projectedTargetKw"] = target
        if row.get("technology") in {"wind", "pv"}:
            available = result.available_by_renewable.get(key)
            if available is not None:
                row["availableKw"] = available
                row["optimizationAvailableKw"] = available
                row["optimizationCurtailmentKw"] = max(0.0, available - target)
            row["recoveryKw"] = (
                max(0.0, target - current) if current is not None else 0.0
            )
        changed = bool(
            current is not None
            and abs(target - current) > 1e-4
            and row.get("online")
            and direct_dispatch
        )
        row["strategyTargetChanged"] = changed
        # Each generation is a complete replacement snapshot.  A valid target
        # must remain present even when it equals the current measurement.
        row["strategyCommand"] = bool(row.get("online") and direct_dispatch)
        row["statusLabel"] = (
            f"{row.get('statusLabel', '')}·"
            f"{'拓扑岛优化' if direct_dispatch else '拓扑岛优化预测'}"
            if str(row.get("statusLabel", "")).strip()
            else "拓扑岛优化" if direct_dispatch else "拓扑岛优化预测"
        )

def _optimization_balance_delta_warnings(
    result: RenewableDispatchOptimizationResult,
) -> List[str]:
    warnings: List[str] = []
    for island in result.islands:
        if (
            island.max_balance_delta_kw <= EPSILON
            or (
                "balance_slack" not in island.status
                and "balance_delta_fallback" not in island.status
            )
        ):
            continue
        delta_ac = island.balance_delta_by_side.get("AC", 0.0)
        delta_dc = island.balance_delta_by_side.get("DC", 0.0)
        threshold_detail = (
            f"超过大失衡告警阈值{result.balance_delta_warning_kw:.3f} kW"
            if island.max_balance_delta_kw > result.balance_delta_warning_kw
            else f"未超过大失衡阈值{result.balance_delta_warning_kw:.3f} kW"
        )
        warnings.append(
            f"优化岛{island.island_id}在设备物理与安全边界内无法精确配平，"
            "按最小功率平衡松弛继续形成策略："
            f"delta_ac={delta_ac:.3f} kW，delta_dc={delta_dc:.3f} kW，"
            f"{threshold_detail}；"
            "请检查可调资源余量、设备边界、拓扑状态及实时量测一致性"
        )
    return warnings

def _optimization_metrics(
    result: RenewableDispatchOptimizationResult,
) -> Dict[str, Any]:
    step_override_devices = sorted(
        {
            key
            for island in result.islands
            for key in island.step_override_devices
        }
    )
    return {
        "optimizationEnabled": True,
        "optimizationApplied": True,
        "optimizationMode": "active",
        "optimizationMethod": "scipy-lsq-slsqp",
        "optimizationObjective": (
            "renewable_curtailment+diesel_output+"
            "curtailment_square+source_storage_adjustment_square+"
            "large_weight_balance_delta_square"
        ),
        "optimizationIslandCount": len(result.islands),
        "optimizationSuccessfulIslandCount": sum(
            1 for island in result.islands if island.success
        ),
        "optimizationAllIslandsSuccessful": result.all_success,
        "optimizationMaxBalanceResidualKw": result.max_balance_residual_kw,
        "optimizationMaxBalanceDeltaKw": max(
            (island.max_balance_delta_kw for island in result.islands),
            default=0.0,
        ),
        "optimizationBalanceDeltaWarningThresholdKw": (
            result.balance_delta_warning_kw
        ),
        "optimizationLargeBalanceDelta": any(
            island.max_balance_delta_kw > result.balance_delta_warning_kw
            for island in result.islands
        ),
        "optimizationIterations": result.iterations,
        "optimizationVariableCount": result.variable_count,
        "optimizationConstraintCount": result.constraint_count,
        "optimizationEqualityConstraintCount": result.equality_constraint_count,
        "optimizationInequalityConstraintCount": result.inequality_constraint_count,
        "optimizationBoundCount": result.bound_count,
        "optimizationBuildMilliseconds": result.build_seconds * 1000.0,
        "optimizationSolverMilliseconds": result.solver_seconds * 1000.0,
        "optimizationStorageBalanceMilliseconds": (
            result.storage_balance_seconds * 1000.0
        ),
        "optimizationPostprocessMilliseconds": result.postprocess_seconds * 1000.0,
        "optimizationSolveMilliseconds": result.solve_seconds * 1000.0,
        "optimizationStepOverrideApplied": any(
            island.step_override_applied for island in result.islands
        ),
        "optimizationStepOverrideDevices": [
            {"dev_type": dev_type, "dev_name": dev_name}
            for dev_type, dev_name in step_override_devices
        ],
        "optimizationUnassignedDevices": [
            {"dev_type": dev_type, "dev_name": dev_name}
            for dev_type, dev_name in result.unassigned_devices
        ],
        "optimizationIslands": [
            {
                "islandId": island.island_id,
                "componentIds": list(island.component_ids),
                "devices": [
                    {"dev_type": dev_type, "dev_name": dev_name}
                    for dev_type, dev_name in island.device_keys
                ],
                "success": island.success,
                "status": island.status,
                "message": island.message,
                "objectiveValue": island.objective_value,
                "renewableCurtailmentKw": island.renewable_curtailment_kw,
                "dieselTargetKw": island.diesel_target_kw,
                "balanceResidualByComponent": dict(
                    island.balance_residual_by_component
                ),
                "balanceResidualBySide": dict(
                    island.balance_residual_by_component
                ),
                "balanceDeltaBySide": dict(island.balance_delta_by_side),
                "deltaAcKw": island.balance_delta_by_side.get("AC", 0.0),
                "deltaDcKw": island.balance_delta_by_side.get("DC", 0.0),
                "maxBalanceDeltaKw": island.max_balance_delta_kw,
                "largeBalanceDelta": (
                    island.max_balance_delta_kw > result.balance_delta_warning_kw
                ),
                "balanceDeltaSquareWeight": island.balance_delta_square_weight,
                "curtailmentSquareWeight": island.curtailment_square_weight,
                "adjustmentSquareWeight": island.adjustment_square_weight,
                "stepOverrideApplied": island.step_override_applied,
                "stepOverrideDevices": [
                    {"dev_type": dev_type, "dev_name": dev_name}
                    for dev_type, dev_name in island.step_override_devices
                ],
                "iterations": island.iterations,
                "variableCount": island.variable_count,
                "constraintCount": island.constraint_count,
                "equalityConstraintCount": island.equality_constraint_count,
                "inequalityConstraintCount": island.inequality_constraint_count,
                "boundCount": island.bound_count,
                "buildMilliseconds": island.build_seconds * 1000.0,
                "solverMilliseconds": island.solver_seconds * 1000.0,
                "storageBalanceMilliseconds": (
                    island.storage_balance_seconds * 1000.0
                ),
                "postprocessMilliseconds": island.postprocess_seconds * 1000.0,
                "solveMilliseconds": island.solve_seconds * 1000.0,
            }
            for island in result.islands
        ],
    }

def _optimization_performance_diagnostics(
    result: RenewableDispatchOptimizationResult,
) -> Dict[str, Any]:
    solved_islands = sum(1 for island in result.islands if island.success)
    statuses = {str(island.status) for island in result.islands}
    if result.unassigned_devices:
        statuses.add("unassigned_devices")
    return {
        "success": result.all_success,
        "status": ",".join(sorted(statuses)) if statuses else "no_problem",
        "iterations": result.iterations,
        "variableCount": result.variable_count,
        "constraintCount": result.constraint_count,
        "equalityConstraintCount": result.equality_constraint_count,
        "inequalityConstraintCount": result.inequality_constraint_count,
        "boundCount": result.bound_count,
        "unassignedDeviceCount": len(result.unassigned_devices),
        "islandCount": len(result.islands),
        "solvedIslandCount": solved_islands,
        "failedIslandCount": len(result.islands) - solved_islands,
        "maxBalanceResidualKw": result.max_balance_residual_kw,
        "islands": [
            {
                "islandId": island.island_id,
                "success": island.success,
                "status": island.status,
                "iterations": island.iterations,
                "variableCount": island.variable_count,
                "constraintCount": island.constraint_count,
                "boundCount": island.bound_count,
                "solveMs": island.solve_seconds * 1000.0,
            }
            for island in result.islands
        ],
    }

def _optimization_decision_detail(
    result: RenewableDispatchOptimizationResult,
    command_rows: Sequence[Mapping[str, Any]],
    quality_payload: Mapping[str, Any],
    settings: RenewableControlSettings,
) -> List[str]:
    detail = [
        "控制架构：按活动开关、设备投退和AC/DC变流器连接关系构造交直流拓扑岛，逐岛调用SciPy求解",
        (
            "目标函数：最小化新能源弃电总和、柴发出力总和，附加小权重弃电平方项、"
            "更小权重的其他电源/储能调节平方项，以及大权重的delta_ac/delta_dc平方项"
        ),
        (
            "功率平衡：每个混合拓扑岛分别建立一条交流侧和一条直流侧方程；"
            "ACDC与DCAC采用相同端口符号：P_AC正向AC→DC，交流侧系数-1、直流侧系数+1；"
            "允许在设备有功上下限内双向调节；"
            "风机、储能和光伏内部变流器不作为边界变量"
        ),
        (
            "死区语义：柴发和构网储能的功率上下限向内收缩形成保护带；"
            "不缩放普通调节步长，也不因调节量较小而冻结控制指令"
        ),
        (
            "SOC分段限额：按配置曲线线性插值得到当前SOC下允许的最大充电、"
            "放电功率，并与物理边界、能量边界和单周期最大调节量取交集；"
            "低SOC不再另设目标必须为零的独立规则"
        ),
        (
            f"SOC越界约束：SOC低于下限-{settings.soc_deadband * 100:.2f}%或高于上限+"
            f"{settings.soc_deadband * 100:.2f}%时，先按越限能量折算纠偏功率；纠偏功率"
            f"最小值为有效储能步长的{settings.storage_soc_correction_step_scale * 100:.2f}%，"
            "最大值为一个有效储能步长，再据此限制每轮目标变化；若当前仍处于禁止充电或禁止放电区，"
            "则优先投影到硬安全边界；严重越限通过多轮连续纠偏逐步逼近设备保护带内的"
            "最大安全功率；"
            f"跟网储能单周期最大调节量按设备功率容量的{settings.storage_step_ratio * 100:.2f}%计算；"
            "构网储能正常配平不受普通步长约束，但SOC越界纠偏受上述储能步长约束；"
            "柴发和AC/DC变流器不受普通步长约束"
        ),
        (
            "步长可行性：先严格使用单周期普通步长；仅当SOC或设备保护边界"
            "要求强制校正且普通模型无解时，才在物理安全边界内放宽配平步长，"
            "SOC强制充放电边界始终不放宽"
        ),
        (
            f"求解汇总：拓扑岛 {len(result.islands)} 个，成功 "
            f"{sum(1 for island in result.islands if island.success)} 个，"
            f"最大调节功率平衡残差 {result.max_balance_residual_kw:.6g} kW，"
            f"总耗时 {result.solve_seconds * 1000.0:.3f} ms"
        ),
    ]
    for island in result.islands:
        override_text = ""
        if island.step_override_applied:
            override_names = ",".join(
                f"{dev_type}.{dev_name}"
                for dev_type, dev_name in island.step_override_devices
            )
            override_text = f"，安全步长回退设备 {override_names or '--'}"
        detail.append(
            f"优化岛 {island.island_id}：状态 {island.status}，"
            f"分量 {','.join(island.component_ids)}，弃电 "
            f"{island.renewable_curtailment_kw:.3f} kW，柴发目标 "
            f"{island.diesel_target_kw:.3f} kW，"
            f"delta_ac {island.balance_delta_by_side.get('AC', 0.0):.3f} kW，"
            f"delta_dc {island.balance_delta_by_side.get('DC', 0.0):.3f} kW，"
            f"迭代 {island.iterations} 次，"
            f"耗时 {island.solve_seconds * 1000.0:.3f} ms{override_text}"
        )
    for row in command_rows:
        if row.get("strategyCommand") is False:
            continue
        current = _number(row.get("planningCurrentKw", row.get("currentKw")))
        target = _number(row.get("commandKw"))
        if current is None or target is None:
            continue
        detail.append(
            f"优化指令：{row.get('dev_type', '')}.{row.get('dev_name', '')} "
            f"{current:.3f} -> {target:.3f} kW，调节量 {target - current:.3f} kW"
        )
    detail.extend(
        f"数据告警：{issue}"
        for issue in quality_payload.get("issues", [])
    )
    return detail

def _decision_value_text(value: Any, unit: str = "kW") -> str:
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


def _decision_signed_value_text(value: Any, unit: str = "kW") -> str:
    number = _number(value)
    if number is None or not math.isfinite(number):
        return "--"
    if abs(number) < 0.005:
        return f"0 {unit}" if unit else "0"
    digits = 1 if abs(number) >= 10.0 else 2
    text = f"{abs(number):.{digits}f}".rstrip("0").rstrip(".")
    sign = "+" if number > 0 else "-"
    return f"{sign}{text} {unit}" if unit else f"{sign}{text}"


def _decision_ratio_text(value: Any) -> str:
    number = _number(value)
    if number is None or not math.isfinite(number):
        return "--"
    pct = number * 100.0
    text = f"{pct:.1f}".rstrip("0").rstrip(".")
    return f"{text}%"


_DATA_QUALITY_LABELS: Dict[str, str] = {
    "ok": "正常",
    "degraded": "降级",
    "warning": "异常提示",
    "blocked": "受阻",
    "error": "异常",
}

_RENEWABLE_ACTION_LABELS: Dict[str, str] = {
    "hold": "保持当前出力",
    "hold_unknown_soc": "缺少储能 SOC，暂保持当前出力",
    "hold_low_diesel_no_charge": "柴发出力偏低、储能未充电，保持当前出力",
    "hold_full_soc_no_charge": "储能满电且已停充，保持当前出力",
    "hold_full_soc_high_diesel_charging": "储能满电且柴发偏高，等待变流器泄放",
    "hold_charge_derating_while_acdc_corrects": "储能充电降额中，交直流变流器优先调节",
    "hold_above_soc_upper_deadband_while_acdc_discharges": "SOC 偏高，变流器优先放电、新能源暂保持",
    "recover_one_step": "按步长增发新能源",
    "recover_optimize": "优化增发新能源",
    "recover_one_step_storage_island": "孤岛模式按步长增发新能源",
    "recover_one_step_below_soc_lower_deadband": "储能偏低，增发新能源补能",
    "curtail_one_step_full_soc": "储能满电，按步长压减新能源",
    "curtail_one_step_storage_island_full_soc": "孤岛储能满电，按步长压减新能源",
    "curtail_one_step_storage_island_no_charge_capacity": "孤岛储能无充电裕度，按步长压减新能源",
    "curtail_one_step_charge_derating": "触发储能充电降额，按步长压减新能源",
    "curtail_one_step_low_diesel_charging": "柴发偏低且储能仍在充电，按步长压减新能源",
    "curtail_one_step_above_soc_upper_deadband": "SOC 越上限，按步长压减新能源",
    "curtail_charge_safety": "触发充电安全保护，压减新能源",
    "curtail_safety_override": "安全边界纠偏，强制压减新能源维持功率平衡",
    "curtail_optimize": "协同功率平衡，压减部分新能源",
}

_STORAGE_ACTION_LABELS: Dict[str, str] = {
    "hold": "维持待机",
    "hold_low_diesel": "柴发偏低，暂维持待机",
    "hold_at_soc_lower": "已达 SOC 下限，维持待机",
    "hold_at_diesel_floor_above_soc_upper_deadband": "柴发已近下限，维持当前状态",
    "hold_acdc_zero_renewable_storage_island": "孤岛模式，变流器保持零送出",
    "stop_acdc_export_renewable_storage_island": "孤岛模式，停止变流器送出",
    "stop_discharge_below_soc_lower_deadband": "SOC 低于保护下限，停止放电",
    "reverse_power_forbidden_below_soc_lower_deadband": "SOC 过低，禁止反送电",
    "stop_discharge_at_soc_lower": "已达 SOC 下限，停止放电",
    "stop_reverse_power_at_soc_lower": "SOC 达下限，停止反送电",
    "stop_reverse_power_at_soc_upper": "SOC 达上限，停止充电",
    "stop_reverse_power_low_diesel": "柴发偏低，停止反送电",
    "stop_reverse_power": "停止反送电",
    "reduce_discharge_low_diesel": "柴发偏低，减少储能放电",
    "increase_discharge": "增加储能放电，压降柴发出力",
    "increase_discharge_above_soc_upper_deadband": "SOC 偏高，增加放电回落电量",
    "increase_charge_optimize": "加大储能充电，消纳系统富余功率",
    "reduce_discharge_optimize": "减少储能放电，配合系统平衡",
    "increase_discharge_optimize": "加大储能放电，补充系统出力",
    "reduce_charge_optimize": "减小储能充电，配合系统平衡",
}

_DIESEL_REGION_LABELS: Dict[str, str] = {
    "low": "低于最小安全出力",
    "deadband": "合理保护区",
    "high": "偏高、有下调空间",
    "offline": "停机",
}

_DIESEL_VALIDATION_LABELS: Dict[str, str] = {
    "within_bounds": "边界正常",
    "improved": "越界正在纠偏",
    "feedback_pending": "等待反馈收敛",
    "not_applicable": "无在线柴发",
}

_INTERLOCK_MODE_LABELS: Dict[str, str] = {
    "idle": "未启机",
    "electrolyzer": "电制氢运行中",
    "fuel_cell": "燃料电池运行中",
    "conflict": "互锁保护处理中",
}


def _natural_label(mapping: Mapping[str, str], raw: Any, fallback: str = "--") -> str:
    key = str(raw or "").strip()
    if not key:
        return fallback
    return mapping.get(key, key)


def _compress_device_names(names: Sequence[str]) -> str:
    """将同前缀连续编号设备合并为简洁区间，如 交流风电-1~10。"""
    unique_names = list(dict.fromkeys(str(n).strip() for n in names if str(n).strip()))
    if len(unique_names) <= 2:
        return "、".join(unique_names)
    parsed: List[Tuple[str, int, str]] = []
    pattern = re.compile(r"^(.*?)(\d+)$")
    for name in unique_names:
        m = pattern.match(name)
        if not m:
            return f"{'、'.join(unique_names[:2])} 等 {len(unique_names)} 台"
        parsed.append((m.group(1), int(m.group(2)), name))
    prefixes = {item[0] for item in parsed}
    if len(prefixes) != 1:
        return f"{'、'.join(unique_names[:2])} 等 {len(unique_names)} 台"
    prefix = next(iter(prefixes))
    nums = sorted(item[1] for item in parsed)
    ranges: List[str] = []
    start = prev = nums[0]
    for num in nums[1:]:
        if num == prev + 1:
            prev = num
        else:
            ranges.append(f"{prefix}{start}" if start == prev else f"{prefix}{start}~{prev}")
            start = prev = num
    ranges.append(f"{prefix}{start}" if start == prev else f"{prefix}{start}~{prev}")
    return "、".join(ranges)


def _merge_similar_warnings(warnings: Sequence[str]) -> List[str]:
    """合并相同提示模板的逐台设备告警（如 4 台柴发同边界限幅合为 1 条）。"""
    clamp_pattern = re.compile(r"^(.+?)\s+(已限幅至\s+.+)$")
    clamp_groups: Dict[str, List[str]] = {}
    others: List[str] = []
    seen_others: set[str] = set()
    for raw in warnings:
        text = str(raw or "").strip()
        if not text:
            continue
        m = clamp_pattern.match(text)
        if m:
            dev_name, suffix = m.group(1).strip(), m.group(2).strip()
            clamp_groups.setdefault(suffix, []).append(dev_name)
        elif text not in seen_others:
            seen_others.add(text)
            others.append(text)
    merged: List[str] = []
    for suffix, devs in clamp_groups.items():
        merged.append(f"{_compress_device_names(devs)} {suffix}")
    merged.extend(others)
    return merged


def _hydrogen_reason_text(reason: Any) -> str:
    normalized = str(reason or "").strip()
    labels = {
        "entry_conditions_met_direct_start": "已开机带载，加载至启机门槛",
        "start_conditions_met": "满足运行加载条件",
        "start_conditions_not_met": "未满足运行条件",
        "awaiting_manual_start": "已满足运行条件，等待人工下令开机",
        "hydrogen_soc_safety_stop": "氢储罐 SOC 极限保护停机",
        "hydrogen_tank_horizon_safety_stop": "氢储罐单拍余量不足，保护停机",
        "min_dwell_hold": "处于最小驻留冷却期，保持运行",
        "startup_grace_hold": "处于启机加载过渡期，保持加载",
        "raise_conditions_met": "满足升功率条件",
        "hold_region": "处于回差保持区",
        "upper_power_limit": "已达功率上限",
        "storage_soc_reduce": "储能 SOC 触发降功率",
        "storage_soc_stop": "储能 SOC 触发停机",
        "diesel_power_reduce": "柴发出力触发降功率",
        "diesel_power_stop": "柴发出力触发停机",
        "diesel_power_above_stop_threshold": "柴发负载率高于停机阈值",
        "electric_storage_soc_below_stop_threshold": "电储 SOC 低于停机阈值",
        "hydrogen_storage_soc_above_stop_threshold": "氢储 SOC 高于停机阈值",
        "start_margin_insufficient": "启机功率裕度不足",
        "atomic_start_margin_insufficient": "交直流或平衡设备协同裕度不足",
        "atomic_margin_unavailable": "协同调节裕度不足",
        "hydrogen_mode_interlock": "与另一氢能模式互锁",
        "pressure_safety_stop": "储氢压力保护停机",
        "below_stop_threshold": "低于停机阈值，执行停机",
        "incomplete_average_input": "SOC 平均值数据不完整",
        "invalid_operating_envelope": "运行功率区间无效",
        "active_setpoint_unavailable": "遥调点不可用",
        "dcac_control_margin_unavailable": "变流器调节裕度不足",
        "target_boundary_clamped_and_dispatched": "目标越界已限幅",
        "above_upper_power_limit_correction": "实时功率越上限，已纠偏",
    }
    if normalized in labels:
        return labels[normalized]
    if "+" in normalized:
        return "、".join(_hydrogen_reason_text(item) for item in normalized.split("+"))
    return normalized or "保持当前状态"


def _hydrogen_trace_action_text(trace: Mapping[str, Any]) -> str:
    action = str(trace.get("action", "hold"))
    if trace.get("controlReason") == "entry_conditions_met_direct_start":
        return "启机"
    delta = _finite_number(trace.get("electricDeltaKw"))
    target = _number(
        trace.get("targetElectricPowerKw", trace.get("electricPowerKw"))
    )
    current = _number(trace.get("currentElectricPowerKw"))
    if current is None and target is not None:
        current = target - delta
    if action == "blocked":
        return "闭锁"
    if action == "hold":
        return "保持停机" if (current is not None and current <= EPSILON) else "保持运行"
    if "pressure_safety_stop" in action or "interlock_stop" in action or "hysteresis_stop" in action:
        return "停机"
    if delta > EPSILON:
        return "启机" if current is not None and current <= EPSILON else "升功率"
    if delta < -EPSILON:
        return "停机" if target is not None and target <= EPSILON else "降功率"
    return "保持停机" if (current is not None and current <= EPSILON) else "保持运行"


def _hydrogen_business_decision_detail(
    hydrogen_plan: Mapping[str, Any],
    settings: RenewableControlSettings,
) -> List[str]:
    del settings
    loop_text = "闭环" if hydrogen_plan.get("closedLoopEnabled") else "开环（仅计算不下发）"
    interlock_text = _natural_label(_INTERLOCK_MODE_LABELS, hydrogen_plan.get("interlockMode", "idle"), "未启机")
    detail = [
        (
            f"【氢能】{loop_text} · {interlock_text}｜"
            f"柴发负载率 {_decision_ratio_text(hydrogen_plan.get('predictedDieselLoadRatioBefore'))}，"
            f"电储 SOC {_decision_ratio_text(hydrogen_plan.get('electricStorageSocAverage'))}，"
            f"氢储 SOC {_decision_ratio_text(hydrogen_plan.get('hydrogenStorageSoc'))}"
            f"（{_decision_value_text(hydrogen_plan.get('hydrogenStoragePressureMpa'), 'MPa')}）"
        ),
    ]
    traces = [
        row
        for row in hydrogen_plan.get("decisionTraces", [])
        if (type(row) is dict or isinstance(row, Mapping))
    ]
    for mode, label in (("electrolyzer", "电制氢"), ("fuel_cell", "燃料电池")):
        mode_traces = [row for row in traces if row.get("mode") == mode]
        if not mode_traces:
            continue
        for trace in mode_traces:
            target = _number(trace.get("targetElectricPowerKw", trace.get("electricPowerKw")))
            delta = _finite_number(trace.get("electricDeltaKw"))
            current = _number(trace.get("currentElectricPowerKw"))
            if current is None and target is not None:
                current = target - delta
            action_text = _hydrogen_trace_action_text(trace)
            blockers = [str(item).strip() for item in trace.get("blockers", []) if str(item).strip()]
            reason_text = "，".join(blockers) if blockers else _hydrogen_reason_text(trace.get("controlReason"))
            if abs(delta) > 0.01:
                power_part = f" {_decision_value_text(current)} → {_decision_value_text(target)}（{_decision_signed_value_text(delta)}）"
            else:
                power_part = ""
            detail.append(
                f"  · {label}（{trace.get('couplingName', '--')}）：{action_text}{power_part}（{reason_text}）"
            )
    return detail


def _business_decision_log_detail(
    command_rows: Sequence[Mapping[str, Any]],
    metrics: Mapping[str, Any],
    hydrogen_plan: Mapping[str, Any],
    settings: RenewableControlSettings,
    quality_payload: Mapping[str, Any],
    *,
    time_text: str,
    warnings: Sequence[str] = (),
) -> List[str]:
    renewable_max = _number(metrics.get("totalRenewableMaxAvailableKw"))
    renewable_current = _number(metrics.get("totalRenewableCurrentKw"))
    renewable_target = _number(metrics.get("totalRenewableTargetKw"))
    curtail_after = (
        max(0.0, renewable_max - renewable_target)
        if renewable_max is not None and renewable_target is not None
        else None
    )

    strategy_rows: List[Tuple[Mapping[str, Any], float, float]] = []
    for row in command_rows:
        if (
            not row.get("online")
            or row.get("commandable") is False
            or row.get("strategyCommand") is False
            or not str(row.get("set_type", "")).strip()
        ):
            continue
        current = _number(row.get("planningCurrentKw", row.get("currentKw")))
        target = _number(row.get("commandKw"))
        if current is None or target is None:
            continue
        strategy_rows.append((row, current, target))

    changed_rows = [item for item in strategy_rows if abs(item[2] - item[1]) > 0.01]
    unchanged_count = len(strategy_rows) - len(changed_rows)
    quality_text = _natural_label(_DATA_QUALITY_LABELS, quality_payload.get("status"), "正常")
    opt_ok = int(_number(metrics.get("optimizationSuccessfulIslandCount"), 0.0) or 0)
    opt_total = int(_number(metrics.get("optimizationIslandCount"), 0.0) or 0)
    opt_text = f"{opt_ok}/{opt_total} 岛求解收敛" if opt_total else "未启用优化岛"

    detail = [
        (
            f"【本轮概览】仿真时刻 {time_text}｜数据{quality_text}｜"
            f"共 {len(strategy_rows)} 台遥调目标（{len(changed_rows)} 台调整，{unchanged_count} 台维持不变）"
        ),
        (
            f"【新能源】风电 {_decision_value_text(metrics.get('totalWindCurrentKw'))} → "
            f"{_decision_value_text(metrics.get('totalWindTargetKw'))}，"
            f"光伏 {_decision_value_text(metrics.get('totalPvCurrentKw'))} → "
            f"{_decision_value_text(metrics.get('totalPvTargetKw'))}"
            f"（最大可发 {_decision_value_text(renewable_max)}，目标弃电 {_decision_value_text(curtail_after)}）；"
            f"{_natural_label(_RENEWABLE_ACTION_LABELS, metrics.get('renewableControlAction'), '保持当前出力')}"
        ),
        (
            f"【柴发】当前 {_decision_value_text(metrics.get('dieselCurrentKw'))} → "
            f"目标 {_decision_value_text(metrics.get('dieselTargetKw'))}"
            f"（{_natural_label(_DIESEL_REGION_LABELS, metrics.get('dieselControlRegion'), '--')}，"
            f"安全下限 {_decision_value_text(metrics.get('dieselMinKw'))}，"
            f"保护目标 {_decision_value_text(metrics.get('dieselDeadbandUpperKw'))}）；"
            f"{_natural_label(_DIESEL_VALIDATION_LABELS, metrics.get('dieselValidationStatus'), '--')}，{opt_text}"
        ),
        (
            f"【储能】交流 {_decision_value_text(metrics.get('acStorageCurrentKw'))} → "
            f"{_decision_value_text(metrics.get('acStorageTargetKw'))}，"
            f"直流 {_decision_value_text(metrics.get('dcStorageCurrentKw'))} → "
            f"{_decision_value_text(metrics.get('dcStorageTargetKw'))}"
            f"（SOC {_decision_ratio_text(metrics.get('acStorageSoc'))} / "
            f"{_decision_ratio_text(metrics.get('dcStorageSoc'))}，"
            f"允许 {_decision_ratio_text(metrics.get('storageSocLowerLimit'))}~{_decision_ratio_text(metrics.get('storageSocUpperLimit'))}）；"
            f"{_natural_label(_STORAGE_ACTION_LABELS, metrics.get('storageControlAction'), '维持待机')}"
        ),
    ]
    detail.extend(_hydrogen_business_decision_detail(hydrogen_plan, settings))

    if changed_rows:
        detail.append(f"【本轮调节明细（仅列变动的 {len(changed_rows)} 台）】")
        # 按 (类别, 单位, 四舍五入当前值, 四舍五入目标值) 合并完全一致的同类设备
        grouped_changes: Dict[str, List[Tuple[str, float, float, str]]] = {}
        for row, current, target in sorted(
            changed_rows,
            key=lambda item: (
                _natural_topology_identity(item[0].get("category", "")),
                _natural_topology_identity(item[0].get("dev_name", "")),
            ),
        ):
            category = str(row.get("category") or "设备")
            set_type = str(row.get("set_type", ""))
            unit = "Nm3/h" if set_type == "flow_set" else "kvar" if set_type == "q_set" else "kW"
            grouped_changes.setdefault(category, []).append(
                (str(row.get("dev_name") or "--"), current, target, unit)
            )
        for category, items in grouped_changes.items():
            sub_groups: Dict[Tuple[str, str, str], List[str]] = {}
            sub_meta: Dict[Tuple[str, str, str], Tuple[float, float, str]] = {}
            for dev_name, cur_val, tgt_val, unit in items:
                sig = (
                    _decision_value_text(cur_val, unit),
                    _decision_value_text(tgt_val, unit),
                    unit,
                )
                sub_groups.setdefault(sig, []).append(dev_name)
                sub_meta.setdefault(sig, (cur_val, tgt_val, unit))
            segments: List[str] = []
            for sig, names in sub_groups.items():
                cur_val, tgt_val, unit = sub_meta[sig]
                cur_s, tgt_s, _ = sig
                delta_s = _decision_signed_value_text(tgt_val - cur_val, unit)
                segments.append(
                    f"{_compress_device_names(names)}（{cur_s} → {tgt_s}，{delta_s}）"
                )
            detail.append(f"  · {category}（{len(items)} 台）：{'；'.join(segments)}")
    else:
        detail.append("【本轮调节明细】所有在线可控设备均维持当前出力，无需调节")

    # 合并边界/运行提示（自动过滤已在【氢能】行展示过的氢能未启动提示，避免重复）
    hydrogen_block_names = {
        str(trace.get("couplingName", "")).strip()
        for trace in hydrogen_plan.get("decisionTraces", [])
        if (type(trace) is dict or isinstance(trace, Mapping)) and trace.get("blockers")
    }
    filtered_warnings = [
        w
        for w in warnings
        if not (
            "暂未启动" in str(w)
            and any(name and name in str(w) for name in hydrogen_block_names)
        )
    ]
    merged_warnings = _merge_similar_warnings(filtered_warnings)
    if merged_warnings:
        shown = "；".join(merged_warnings[:5])
        if len(merged_warnings) > 5:
            shown += f"；另有 {len(merged_warnings) - 5} 条提示"
        detail.append(f"【边界提示】{shown}")

    issues = [str(item).strip() for item in quality_payload.get("issues", []) if str(item).strip()]
    if issues:
        shown = "；".join(issues[:3])
        if len(issues) > 3:
            shown += f"；另有 {len(issues) - 3} 条数据异常"
        detail.append(f"【数据提示】{shown}")
    return detail
