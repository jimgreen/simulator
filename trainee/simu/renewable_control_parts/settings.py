"""renewable_control 拆分模块：新能源控制配置（RenewableControlSettings）、质量评估与储能/变流器设备行提取。"""

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
    _renewable_weather_available_kw,
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


def _runtime_mode(snapshot: Mapping[str, Any], device: Mapping[str, Any]) -> str:
    settings = snapshot.get("settings")
    modes = settings.get("modes", []) if (type(settings) is dict or isinstance(settings, Mapping)) else []
    override: Mapping[str, Any] = {}
    for row in modes if isinstance(modes, Sequence) else []:
        if not (type(row) is dict or isinstance(row, Mapping)):
            continue
        if str(row.get("dev_type", "")) == _device_type(device) and str(row.get("dev_name", "")) == _device_name(device):
            override = row
            break
    raw_domains = device.get("terminal_domains", ())
    terminal_domains = {
        str(value).strip().upper()
        for value in raw_domains
        if str(value).strip()
    } if isinstance(raw_domains, (list, tuple, set)) else set()
    raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
    if terminal_domains == {"AC", "DC"} or (
        "ac_node" in raw and "dc_node" in raw
    ):
        override_mode = str(
            override.get("mode") or override.get("control_type") or ""
        ).strip().upper()
        if override_mode and override_mode != "NONE":
            return override_mode
        return converter_control_mode(
            {
                **dict(raw),
                "mode": device.get("mode", raw.get("mode", "")),
            }
        )
    return str(
        override.get("mode")
        or override.get("control_type")
        or device.get("mode")
        or raw.get("ac_control_type")
        or raw.get("control_type")
        or raw.get("dc_control_type")
        or ""
    ).strip().upper()

@dataclass(frozen=True)
class RenewableControlSettings:
    # Simulation-clock seconds between automatic control decisions.
    interval_seconds: float = default_number("simulation_control_interval_seconds")
    soc_min: float = default_number("soc_min")
    soc_max: float = default_number("soc_max")
    large_step_threshold_kw: float = default_number("large_step_threshold_kw")
    step_coefficient: float = default_number("renewable_step_ratio")
    diesel_step_ratio: float = default_number("diesel_step_ratio")
    converter_ramp_step_ratio: float = default_number("converter_ramp_step_ratio")
    converter_efficiency: float = default_number("converter_efficiency")
    storage_step_ratio: float = default_number(
        "grid_following_storage_step_ratio"
    )
    storage_soc_rebalance_deadband: float = default_number(
        "storage_soc_rebalance_deadband"
    )
    storage_soc_correction_step_scale: float = default_number(
        "storage_soc_correction_step_scale"
    )
    grid_forming_storage_protection_ratio: float = default_number(
        "grid_forming_storage_protection_ratio"
    )
    diesel_power_protection_ratio: float = default_number(
        "diesel_power_protection_ratio"
    )
    soc_deadband: float = default_number("soc_deadband")
    hydrogen_closed_loop_enabled: bool = default_boolean(
        "hydrogen_closed_loop_enabled"
    )
    hydrogen_pressure_deadband_ratio: float = default_number(
        "hydrogen_pressure_deadband_ratio"
    )
    hydrogen_min_dwell_seconds: float = default_number(
        "hydrogen_min_dwell_seconds"
    )
    hydrogen_startup_grace_seconds: float = default_number(
        "hydrogen_startup_grace_seconds"
    )
    electrolyzer_power_min_ratio: float = default_number("electrolyzer_power_min_ratio")
    electrolyzer_power_max_ratio: float = default_number("electrolyzer_power_max_ratio")
    electrolyzer_power_deadband_ratio: float = default_number(
        "electrolyzer_power_deadband_ratio"
    )
    electrolyzer_power_step_ratio: float = default_number("electrolyzer_power_step_ratio")
    electrolyzer_diesel_power_limit_ratio: float = default_number(
        "electrolyzer_diesel_power_limit_ratio"
    )
    electrolyzer_diesel_power_deadband_ratio: float = default_number(
        "electrolyzer_diesel_power_deadband_ratio"
    )
    electrolyzer_diesel_power_stop_maximum_ratio: float = default_number(
        "electrolyzer_diesel_power_stop_maximum_ratio"
    )
    electrolyzer_storage_soc_start_minimum: float = default_number(
        "electrolyzer_storage_soc_start_minimum"
    )
    electrolyzer_storage_soc_stop_maximum: float = default_number(
        "electrolyzer_storage_soc_stop_maximum"
    )
    electrolyzer_hydrogen_storage_soc_stop_minimum: float = default_number(
        "electrolyzer_hydrogen_storage_soc_stop_minimum"
    )
    fuel_cell_power_min_ratio: float = default_number("fuel_cell_power_min_ratio")
    fuel_cell_power_max_ratio: float = default_number("fuel_cell_power_max_ratio")
    fuel_cell_power_deadband_ratio: float = default_number(
        "fuel_cell_power_deadband_ratio"
    )
    fuel_cell_power_step_ratio: float = default_number("fuel_cell_power_step_ratio")
    fuel_cell_diesel_power_limit_ratio: float = default_number(
        "fuel_cell_diesel_power_limit_ratio"
    )
    fuel_cell_diesel_power_stop_minimum_ratio: float = default_number(
        "fuel_cell_diesel_power_stop_minimum_ratio"
    )
    fuel_cell_storage_soc_limit: float = default_number(
        "fuel_cell_storage_soc_limit"
    )
    fuel_cell_storage_soc_deadband: float = default_number(
        "fuel_cell_storage_soc_deadband"
    )
    fuel_cell_hydrogen_storage_soc_upper_limit: float = default_number(
        "fuel_cell_hydrogen_storage_soc_upper_limit"
    )
    fuel_cell_hydrogen_storage_soc_lower_limit: float = default_number(
        "fuel_cell_hydrogen_storage_soc_lower_limit"
    )
    converter_step_ratio: float = default_number("legacy_converter_step_ratio")
    storage_charge_derating_curve: Tuple[Tuple[float, float], ...] = DEFAULT_STORAGE_CHARGE_DERATING_CURVE
    storage_discharge_derating_curve: Tuple[Tuple[float, float], ...] = DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE
    command_valid_minutes: float = default_number("command_valid_minutes")
    optimization_renewable_curtailment_weight: float = default_number(
        "optimization_renewable_curtailment_weight"
    )
    optimization_diesel_output_weight: float = default_number(
        "optimization_diesel_output_weight"
    )
    optimization_curtailment_square_weight: float = default_number(
        "optimization_curtailment_square_weight"
    )
    optimization_source_storage_adjustment_square_weight: float = default_number(
        "optimization_source_storage_adjustment_square_weight"
    )
    optimization_balance_delta_square_weight: float = default_number(
        "optimization_balance_delta_square_weight"
    )
    optimization_balance_delta_warning_kw: float = default_number(
        "optimization_balance_delta_warning_kw"
    )
    optimization_balance_tolerance_kw: float = default_number(
        "optimization_balance_tolerance_kw"
    )
    optimization_bound_tolerance_kw: float = default_number(
        "optimization_bound_tolerance_kw"
    )
    optimization_ftol: float = default_number("optimization_ftol")
    optimization_max_iterations: int = default_integer(
        "optimization_max_iterations"
    )
    # Constructor-only compatibility for older callers. Persisted settings and
    # WEB payloads are migrated to ratios and never emit these absolute fields.
    electrolyzer_power_min_kw: Optional[float] = None
    electrolyzer_power_max_kw: Optional[float] = None
    electrolyzer_power_deadband_kw: Optional[float] = None
    electrolyzer_power_step_kw: Optional[float] = None
    electrolyzer_diesel_power_limit_kw: Optional[float] = None
    electrolyzer_diesel_power_deadband_kw: Optional[float] = None
    fuel_cell_power_min_kw: Optional[float] = None
    fuel_cell_power_max_kw: Optional[float] = None
    fuel_cell_power_deadband_kw: Optional[float] = None
    fuel_cell_power_step_kw: Optional[float] = None
    fuel_cell_diesel_power_limit_kw: Optional[float] = None
    # Constructor-only compatibility. The legacy names described physical bounds,
    # but their actual planner semantics were upper -> start and lower -> stop.
    electrolyzer_storage_soc_lower_limit: Optional[float] = None
    electrolyzer_storage_soc_upper_limit: Optional[float] = None
    electrolyzer_hydrogen_storage_soc_upper_limit: Optional[float] = None

    def __post_init__(self) -> None:
        if self.electrolyzer_storage_soc_upper_limit is not None:
            object.__setattr__(
                self,
                "electrolyzer_storage_soc_start_minimum",
                float(self.electrolyzer_storage_soc_upper_limit),
            )
        if self.electrolyzer_storage_soc_lower_limit is not None:
            object.__setattr__(
                self,
                "electrolyzer_storage_soc_stop_maximum",
                float(self.electrolyzer_storage_soc_lower_limit),
            )
        if self.electrolyzer_hydrogen_storage_soc_upper_limit is not None:
            object.__setattr__(
                self,
                "electrolyzer_hydrogen_storage_soc_stop_minimum",
                float(self.electrolyzer_hydrogen_storage_soc_upper_limit),
            )

    def normalized(self) -> "RenewableControlSettings":
        minimum = _clamp(float(self.soc_min), 0.0, 1.0)
        maximum = _clamp(float(self.soc_max), minimum, 1.0)
        storage_step_ratio = max(0.0, float(self.storage_step_ratio))
        legacy_converter_step_ratio = max(0.0, float(self.converter_step_ratio))
        if (
            legacy_converter_step_ratio > EPSILON
            and abs(
                storage_step_ratio
                - DEFAULT_GRID_FOLLOWING_STORAGE_STEP_RATIO
            )
            <= EPSILON
        ):
            storage_step_ratio = legacy_converter_step_ratio
        electrolyzer_power_min_ratio = _clamp(
            float(self.electrolyzer_power_min_ratio), 0.0, 1.0
        )
        electrolyzer_power_max_ratio = _clamp(
            float(self.electrolyzer_power_max_ratio),
            electrolyzer_power_min_ratio,
            1.0,
        )
        fuel_cell_power_min_ratio = _clamp(
            float(self.fuel_cell_power_min_ratio), 0.0, 1.0
        )
        fuel_cell_power_max_ratio = _clamp(
            float(self.fuel_cell_power_max_ratio),
            fuel_cell_power_min_ratio,
            1.0,
        )
        electrolyzer_storage_soc_start_minimum = _clamp(
            float(self.electrolyzer_storage_soc_start_minimum), 0.0, 1.0
        )
        electrolyzer_storage_soc_stop_maximum = _clamp(
            float(self.electrolyzer_storage_soc_stop_maximum), 0.0, 1.0
        )
        fuel_cell_hydrogen_storage_soc_lower_limit = _clamp(
            float(self.fuel_cell_hydrogen_storage_soc_lower_limit), 0.0, 1.0
        )
        fuel_cell_hydrogen_storage_soc_upper_limit = _clamp(
            float(self.fuel_cell_hydrogen_storage_soc_upper_limit),
            fuel_cell_hydrogen_storage_soc_lower_limit,
            1.0,
        )
        return replace(
            self,
            interval_seconds=max(
                MINIMUM_CONTROL_INTERVAL_SECONDS,
                float(self.interval_seconds),
            ),
            soc_min=minimum,
            soc_max=maximum,
            large_step_threshold_kw=max(0.0, float(self.large_step_threshold_kw)),
            step_coefficient=max(0.0, float(self.step_coefficient)),
            diesel_step_ratio=_clamp(float(self.diesel_step_ratio), 0.0, 1.0),
            converter_ramp_step_ratio=_clamp(float(self.converter_ramp_step_ratio), 0.0, 1.0),
            converter_efficiency=_clamp(float(self.converter_efficiency), 0.5, 1.0),
            storage_step_ratio=storage_step_ratio,
            storage_soc_rebalance_deadband=_clamp(
                float(self.storage_soc_rebalance_deadband), 0.0, 0.5
            ),
            storage_soc_correction_step_scale=_clamp(
                float(self.storage_soc_correction_step_scale),
                0.10,
                1.0,
            ),
            grid_forming_storage_protection_ratio=_clamp(
                float(self.grid_forming_storage_protection_ratio),
                0.0,
                MAXIMUM_POWER_PROTECTION_RATIO,
            ),
            diesel_power_protection_ratio=_clamp(
                float(self.diesel_power_protection_ratio),
                0.0,
                MAXIMUM_POWER_PROTECTION_RATIO,
            ),
            soc_deadband=_clamp(float(self.soc_deadband), 0.0, 1.0),
            hydrogen_closed_loop_enabled=bool(
                self.hydrogen_closed_loop_enabled
            ),
            hydrogen_pressure_deadband_ratio=_clamp(
                float(self.hydrogen_pressure_deadband_ratio),
                0.0,
                0.5,
            ),
            hydrogen_min_dwell_seconds=max(
                0.0,
                float(self.hydrogen_min_dwell_seconds),
            ),
            hydrogen_startup_grace_seconds=max(
                0.0,
                float(self.hydrogen_startup_grace_seconds),
            ),
            electrolyzer_power_min_ratio=electrolyzer_power_min_ratio,
            electrolyzer_power_max_ratio=electrolyzer_power_max_ratio,
            electrolyzer_power_deadband_ratio=_clamp(
                float(self.electrolyzer_power_deadband_ratio),
                0.0,
                electrolyzer_power_max_ratio - electrolyzer_power_min_ratio,
            ),
            electrolyzer_power_step_ratio=_clamp(
                float(self.electrolyzer_power_step_ratio),
                EPSILON,
                1.0,
            ),
            electrolyzer_diesel_power_limit_ratio=_clamp(
                float(self.electrolyzer_diesel_power_limit_ratio), 0.0, 1.0
            ),
            electrolyzer_diesel_power_deadband_ratio=_clamp(
                float(self.electrolyzer_diesel_power_deadband_ratio), 0.0, 1.0
            ),
            electrolyzer_diesel_power_stop_maximum_ratio=_clamp(
                float(self.electrolyzer_diesel_power_stop_maximum_ratio),
                0.0,
                1.0,
            ),
            electrolyzer_storage_soc_start_minimum=electrolyzer_storage_soc_start_minimum,
            electrolyzer_storage_soc_stop_maximum=electrolyzer_storage_soc_stop_maximum,
            electrolyzer_hydrogen_storage_soc_stop_minimum=_clamp(
                float(self.electrolyzer_hydrogen_storage_soc_stop_minimum),
                0.0,
                1.0,
            ),
            fuel_cell_power_min_ratio=fuel_cell_power_min_ratio,
            fuel_cell_power_max_ratio=fuel_cell_power_max_ratio,
            fuel_cell_power_deadband_ratio=_clamp(
                float(self.fuel_cell_power_deadband_ratio),
                0.0,
                fuel_cell_power_max_ratio - fuel_cell_power_min_ratio,
            ),
            fuel_cell_power_step_ratio=_clamp(
                float(self.fuel_cell_power_step_ratio),
                EPSILON,
                1.0,
            ),
            fuel_cell_diesel_power_limit_ratio=_clamp(
                float(self.fuel_cell_diesel_power_limit_ratio), 0.0, 1.0
            ),
            fuel_cell_diesel_power_stop_minimum_ratio=_clamp(
                float(self.fuel_cell_diesel_power_stop_minimum_ratio),
                0.0,
                1.0,
            ),
            fuel_cell_storage_soc_limit=_clamp(
                float(self.fuel_cell_storage_soc_limit), 0.0, 1.0
            ),
            fuel_cell_storage_soc_deadband=_clamp(
                float(self.fuel_cell_storage_soc_deadband), 0.0, 0.5
            ),
            fuel_cell_hydrogen_storage_soc_upper_limit=fuel_cell_hydrogen_storage_soc_upper_limit,
            fuel_cell_hydrogen_storage_soc_lower_limit=fuel_cell_hydrogen_storage_soc_lower_limit,
            converter_step_ratio=0.0,
            storage_charge_derating_curve=_normalized_derating_curve(
                self.storage_charge_derating_curve,
                DEFAULT_STORAGE_CHARGE_DERATING_CURVE,
                increasing=False,
            ),
            storage_discharge_derating_curve=_normalized_derating_curve(
                self.storage_discharge_derating_curve,
                DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE,
                increasing=True,
            ),
            command_valid_minutes=max(
                MINIMUM_COMMAND_VALID_MINUTES,
                float(self.command_valid_minutes),
            ),
            optimization_renewable_curtailment_weight=max(
                0.0, float(self.optimization_renewable_curtailment_weight)
            ),
            optimization_diesel_output_weight=max(
                0.0, float(self.optimization_diesel_output_weight)
            ),
            optimization_curtailment_square_weight=max(
                0.0, float(self.optimization_curtailment_square_weight)
            ),
            optimization_source_storage_adjustment_square_weight=max(
                0.0,
                float(self.optimization_source_storage_adjustment_square_weight),
            ),
            optimization_balance_delta_square_weight=max(
                EPSILON, float(self.optimization_balance_delta_square_weight)
            ),
            optimization_balance_delta_warning_kw=max(
                0.0, float(self.optimization_balance_delta_warning_kw)
            ),
            optimization_balance_tolerance_kw=max(
                EPSILON, float(self.optimization_balance_tolerance_kw)
            ),
            optimization_bound_tolerance_kw=max(
                EPSILON, float(self.optimization_bound_tolerance_kw)
            ),
            optimization_ftol=max(EPSILON, float(self.optimization_ftol)),
            optimization_max_iterations=max(
                1, int(self.optimization_max_iterations)
            ),
            electrolyzer_storage_soc_lower_limit=None,
            electrolyzer_storage_soc_upper_limit=None,
            electrolyzer_hydrogen_storage_soc_upper_limit=None,
        )

    def updated(self, payload: Mapping[str, Any]) -> "RenewableControlSettings":
        aliases = {
            "interval_seconds": (
                "simulation_interval_seconds",
                "simulationIntervalSeconds",
                "interval_seconds",
                "intervalSeconds",
            ),
            "soc_min": ("soc_min", "socMin"),
            "soc_max": ("soc_max", "socMax"),
            "large_step_threshold_kw": ("large_step_threshold_kw", "largeStepThresholdKw"),
            "step_coefficient": (
                "step_coefficient",
                "stepCoefficient",
                "renewableStepRatePerMinute",
                "renewableStepRatio",
            ),
            "diesel_step_ratio": (
                "diesel_step_ratio",
                "dieselStepRatio",
            ),
            "converter_ramp_step_ratio": (
                "converter_ramp_step_ratio",
                "converterRampStepRatio",
            ),
            "converter_efficiency": (
                "converter_efficiency",
                "converterEfficiency",
            ),
            "storage_step_ratio": (
                "storage_step_ratio",
                "storageStepRatePerMinute",
                "storageStepRatio",
                "gridFollowingStorageStepRatio",
            ),
            "storage_soc_rebalance_deadband": (
                "storage_soc_rebalance_deadband",
                "storageSocRebalanceDeadband",
            ),
            "storage_soc_correction_step_scale": (
                "storage_soc_correction_step_scale",
                "storageSocCorrectionStepScale",
            ),
            "grid_forming_storage_protection_ratio": (
                "grid_forming_storage_protection_ratio",
                "gridFormingStorageProtectionRatio",
            ),
            "diesel_power_protection_ratio": (
                "diesel_power_protection_ratio",
                "dieselPowerProtectionRatio",
                "diesel_deadband_ratio",
                "dieselDeadbandRatio",
            ),
            "soc_deadband": ("soc_deadband", "socDeadband"),
            "hydrogen_pressure_deadband_ratio": (
                "hydrogen_pressure_deadband_ratio",
                "hydrogenPressureDeadbandRatio",
            ),
            "hydrogen_min_dwell_seconds": (
                "hydrogen_min_dwell_seconds",
                "hydrogenMinDwellSeconds",
            ),
            "hydrogen_startup_grace_seconds": (
                "hydrogen_startup_grace_seconds",
                "hydrogenStartupGraceSeconds",
            ),
            "electrolyzer_power_min_ratio": (
                "electrolyzer_power_min_ratio",
                "electrolyzerPowerMinRatio",
            ),
            "electrolyzer_power_max_ratio": (
                "electrolyzer_power_max_ratio",
                "electrolyzerPowerMaxRatio",
            ),
            "electrolyzer_power_deadband_ratio": (
                "electrolyzer_power_deadband_ratio",
                "electrolyzerPowerDeadbandRatio",
            ),
            "electrolyzer_power_step_ratio": (
                "electrolyzer_power_step_ratio",
                "electrolyzerPowerStepRatio",
            ),
            "electrolyzer_diesel_power_limit_ratio": (
                "electrolyzer_diesel_power_limit_ratio",
                "electrolyzerDieselPowerLimitRatio",
            ),
            "electrolyzer_diesel_power_deadband_ratio": (
                "electrolyzer_diesel_power_deadband_ratio",
                "electrolyzerDieselPowerDeadbandRatio",
            ),
            "electrolyzer_diesel_power_stop_maximum_ratio": (
                "electrolyzer_diesel_power_stop_maximum_ratio",
                "electrolyzerDieselPowerStopMaximumRatio",
            ),
            "electrolyzer_storage_soc_start_minimum": (
                "electrolyzer_storage_soc_start_minimum",
                "electrolyzerStorageSocStartMinimum",
                "electrolyzer_storage_soc_upper_limit",
                "electrolyzerStorageSocUpperLimit",
            ),
            "electrolyzer_storage_soc_stop_maximum": (
                "electrolyzer_storage_soc_stop_maximum",
                "electrolyzerStorageSocStopMaximum",
                "electrolyzer_storage_soc_lower_limit",
                "electrolyzerStorageSocLowerLimit",
            ),
            "electrolyzer_hydrogen_storage_soc_stop_minimum": (
                "electrolyzer_hydrogen_storage_soc_stop_minimum",
                "electrolyzerHydrogenStorageSocStopMinimum",
                "electrolyzer_hydrogen_storage_soc_upper_limit",
                "electrolyzerHydrogenStorageSocUpperLimit",
            ),
            "fuel_cell_power_min_ratio": (
                "fuel_cell_power_min_ratio",
                "fuelCellPowerMinRatio",
            ),
            "fuel_cell_power_max_ratio": (
                "fuel_cell_power_max_ratio",
                "fuelCellPowerMaxRatio",
            ),
            "fuel_cell_power_deadband_ratio": (
                "fuel_cell_power_deadband_ratio",
                "fuelCellPowerDeadbandRatio",
            ),
            "fuel_cell_power_step_ratio": (
                "fuel_cell_power_step_ratio",
                "fuelCellPowerStepRatio",
            ),
            "fuel_cell_diesel_power_limit_ratio": (
                "fuel_cell_diesel_power_limit_ratio",
                "fuelCellDieselPowerLimitRatio",
            ),
            "fuel_cell_diesel_power_stop_minimum_ratio": (
                "fuel_cell_diesel_power_stop_minimum_ratio",
                "fuelCellDieselPowerStopMinimumRatio",
            ),
            "fuel_cell_storage_soc_limit": (
                "fuel_cell_storage_soc_limit",
                "fuelCellStorageSocLimit",
            ),
            "fuel_cell_storage_soc_deadband": (
                "fuel_cell_storage_soc_deadband",
                "fuelCellStorageSocDeadband",
            ),
            "fuel_cell_hydrogen_storage_soc_upper_limit": (
                "fuel_cell_hydrogen_storage_soc_upper_limit",
                "fuelCellHydrogenStorageSocUpperLimit",
            ),
            "fuel_cell_hydrogen_storage_soc_lower_limit": (
                "fuel_cell_hydrogen_storage_soc_lower_limit",
                "fuelCellHydrogenStorageSocLowerLimit",
            ),
            "command_valid_minutes": ("command_valid_minutes", "commandValidMinutes"),
            "optimization_renewable_curtailment_weight": (
                "optimization_renewable_curtailment_weight",
                "optimizationRenewableCurtailmentWeight",
            ),
            "optimization_diesel_output_weight": (
                "optimization_diesel_output_weight",
                "optimizationDieselOutputWeight",
            ),
            "optimization_curtailment_square_weight": (
                "optimization_curtailment_square_weight",
                "optimizationCurtailmentSquareWeight",
            ),
            "optimization_source_storage_adjustment_square_weight": (
                "optimization_source_storage_adjustment_square_weight",
                "optimizationSourceStorageAdjustmentSquareWeight",
            ),
            "optimization_balance_delta_square_weight": (
                "optimization_balance_delta_square_weight",
                "optimizationBalanceDeltaSquareWeight",
            ),
            "optimization_balance_delta_warning_kw": (
                "optimization_balance_delta_warning_kw",
                "optimizationBalanceDeltaWarningKw",
            ),
            "optimization_balance_tolerance_kw": (
                "optimization_balance_tolerance_kw",
                "optimizationBalanceToleranceKw",
            ),
            "optimization_bound_tolerance_kw": (
                "optimization_bound_tolerance_kw",
                "optimizationBoundToleranceKw",
            ),
            "optimization_ftol": (
                "optimization_ftol",
                "optimizationFtol",
            ),
            "optimization_max_iterations": (
                "optimization_max_iterations",
                "optimizationMaxIterations",
            ),
        }
        values: Dict[str, Any] = {}
        for field_name, names in aliases.items():
            for name in names:
                if name in payload:
                    parsed = _number(payload.get(name))
                    if parsed is not None:
                        values[field_name] = parsed
                    break
        for name in (
            "hydrogen_closed_loop_enabled",
            "hydrogenClosedLoopEnabled",
        ):
            if name in payload:
                values["hydrogen_closed_loop_enabled"] = _boolean(
                    payload.get(name),
                    self.hydrogen_closed_loop_enabled,
                )
                break
        legacy_percent_aliases = {
            "electrolyzer_power_min_ratio": ("electrolyzer_power_min_kw", "electrolyzerPowerMinKw"),
            "electrolyzer_power_max_ratio": ("electrolyzer_power_max_kw", "electrolyzerPowerMaxKw"),
            "electrolyzer_power_deadband_ratio": ("electrolyzer_power_deadband_kw", "electrolyzerPowerDeadbandKw"),
            "electrolyzer_power_step_ratio": ("electrolyzer_power_step_kw", "electrolyzerPowerStepKw"),
            "electrolyzer_diesel_power_limit_ratio": ("electrolyzer_diesel_power_limit_kw", "electrolyzerDieselPowerLimitKw"),
            "electrolyzer_diesel_power_deadband_ratio": ("electrolyzer_diesel_power_deadband_kw", "electrolyzerDieselPowerDeadbandKw"),
            "fuel_cell_power_min_ratio": ("fuel_cell_power_min_kw", "fuelCellPowerMinKw"),
            "fuel_cell_power_max_ratio": ("fuel_cell_power_max_kw", "fuelCellPowerMaxKw"),
            "fuel_cell_power_deadband_ratio": ("fuel_cell_power_deadband_kw", "fuelCellPowerDeadbandKw"),
            "fuel_cell_power_step_ratio": ("fuel_cell_power_step_kw", "fuelCellPowerStepKw"),
            "fuel_cell_diesel_power_limit_ratio": ("fuel_cell_diesel_power_limit_kw", "fuelCellDieselPowerLimitKw"),
        }
        for field_name, names in legacy_percent_aliases.items():
            if field_name in values:
                continue
            for name in names:
                if name not in payload:
                    continue
                parsed = _number(payload.get(name))
                if parsed is not None:
                    values[field_name] = parsed / 100.0
                break
        if not any(
            name in payload
            for name in (
                "electrolyzer_diesel_power_stop_maximum_ratio",
                "electrolyzerDieselPowerStopMaximumRatio",
            )
        ):
            electrolyzer_start = float(
                values.get(
                    "electrolyzer_diesel_power_limit_ratio",
                    self.electrolyzer_diesel_power_limit_ratio,
                )
            )
            electrolyzer_stop = float(
                self.electrolyzer_diesel_power_stop_maximum_ratio
            )
            if (
                0.0 <= electrolyzer_start <= 1.0
                and electrolyzer_start >= electrolyzer_stop - EPSILON
            ):
                migration_gap = max(
                    0.01,
                    float(
                        values.get(
                            "electrolyzer_diesel_power_deadband_ratio",
                            self.electrolyzer_diesel_power_deadband_ratio,
                        )
                    ),
                )
                migrated_stop = min(1.0, electrolyzer_start + migration_gap)
                if migrated_stop <= electrolyzer_start + EPSILON:
                    electrolyzer_start = max(0.0, 1.0 - migration_gap)
                    values["electrolyzer_diesel_power_limit_ratio"] = (
                        electrolyzer_start
                    )
                    migrated_stop = 1.0
                values["electrolyzer_diesel_power_stop_maximum_ratio"] = (
                    migrated_stop
                )
        if not any(
            name in payload
            for name in (
                "fuel_cell_diesel_power_stop_minimum_ratio",
                "fuelCellDieselPowerStopMinimumRatio",
            )
        ):
            fuel_cell_start = float(
                values.get(
                    "fuel_cell_diesel_power_limit_ratio",
                    self.fuel_cell_diesel_power_limit_ratio,
                )
            )
            fuel_cell_stop = float(
                self.fuel_cell_diesel_power_stop_minimum_ratio
            )
            if (
                0.0 <= fuel_cell_start <= 1.0
                and fuel_cell_start <= fuel_cell_stop + EPSILON
            ):
                migration_gap = 0.01
                migrated_stop = max(0.0, fuel_cell_start - migration_gap)
                if migrated_stop >= fuel_cell_start - EPSILON:
                    fuel_cell_start = min(1.0, migration_gap)
                    values["fuel_cell_diesel_power_limit_ratio"] = fuel_cell_start
                    migrated_stop = 0.0
                values["fuel_cell_diesel_power_stop_minimum_ratio"] = (
                    migrated_stop
                )
        if not any(
            name in payload
            for name in (
                "storage_step_ratio",
                "storageStepRatePerMinute",
                "storageStepRatio",
                "gridFollowingStorageStepRatio",
            )
        ):
            legacy_storage_step = _number(
                payload.get(
                    "converter_step_ratio",
                    payload.get("converterStepRatio"),
                )
            )
            if legacy_storage_step is not None:
                values["storage_step_ratio"] = legacy_storage_step
        if not any(
            name in payload
            for name in (
                "grid_forming_storage_protection_ratio",
                "gridFormingStorageProtectionRatio",
            )
        ):
            legacy_storage_protection = _number(
                payload.get(
                    "storage_switch_deadband_kw",
                    payload.get("storageSwitchDeadbandKw"),
                )
            )
            if legacy_storage_protection is not None:
                values["grid_forming_storage_protection_ratio"] = (
                    legacy_storage_protection / 100.0
                )
        charge_curve = payload.get(
            "storage_charge_derating_curve",
            payload.get("storageChargeDeratingCurve"),
        )
        discharge_curve = payload.get(
            "storage_discharge_derating_curve",
            payload.get("storageDischargeDeratingCurve"),
        )
        if charge_curve is not None:
            values["storage_charge_derating_curve"] = _normalized_derating_curve(
                charge_curve,
                self.storage_charge_derating_curve,
                increasing=False,
            )
        if discharge_curve is not None:
            values["storage_discharge_derating_curve"] = _normalized_derating_curve(
                discharge_curve,
                self.storage_discharge_derating_curve,
                increasing=True,
            )
        return replace(self, **values).normalized()

    def payload(self) -> Dict[str, Any]:
        return {
            "simulationIntervalSeconds": self.interval_seconds,
            "intervalSeconds": self.interval_seconds,
            "socMin": self.soc_min,
            "socMax": self.soc_max,
            "largeStepThresholdKw": self.large_step_threshold_kw,
            "stepCoefficient": self.step_coefficient,
            "renewableStepRatio": self.step_coefficient,
            "dieselStepRatio": self.diesel_step_ratio,
            "converterRampStepRatio": self.converter_ramp_step_ratio,
            "converterEfficiency": self.converter_efficiency,
            "storageStepRatio": self.storage_step_ratio,
            "storageSocRebalanceDeadband": self.storage_soc_rebalance_deadband,
            "storageSocCorrectionStepScale": self.storage_soc_correction_step_scale,
            "gridFormingStorageProtectionRatio": self.grid_forming_storage_protection_ratio,
            "dieselPowerProtectionRatio": self.diesel_power_protection_ratio,
            "socDeadband": self.soc_deadband,
            "hydrogenClosedLoopEnabled": self.hydrogen_closed_loop_enabled,
            "hydrogenPressureDeadbandRatio": self.hydrogen_pressure_deadband_ratio,
            "hydrogenMinDwellSeconds": self.hydrogen_min_dwell_seconds,
            "hydrogenStartupGraceSeconds": self.hydrogen_startup_grace_seconds,
            "electrolyzerPowerMinRatio": self.electrolyzer_power_min_ratio,
            "electrolyzerPowerMaxRatio": self.electrolyzer_power_max_ratio,
            "electrolyzerPowerDeadbandRatio": self.electrolyzer_power_deadband_ratio,
            "electrolyzerPowerStepRatio": self.electrolyzer_power_step_ratio,
            "electrolyzerDieselPowerLimitRatio": self.electrolyzer_diesel_power_limit_ratio,
            "electrolyzerDieselPowerDeadbandRatio": self.electrolyzer_diesel_power_deadband_ratio,
            "electrolyzerDieselPowerStopMaximumRatio": self.electrolyzer_diesel_power_stop_maximum_ratio,
            "electrolyzerStorageSocStartMinimum": self.electrolyzer_storage_soc_start_minimum,
            "electrolyzerStorageSocStopMaximum": self.electrolyzer_storage_soc_stop_maximum,
            "electrolyzerHydrogenStorageSocStopMinimum": self.electrolyzer_hydrogen_storage_soc_stop_minimum,
            "fuelCellPowerMinRatio": self.fuel_cell_power_min_ratio,
            "fuelCellPowerMaxRatio": self.fuel_cell_power_max_ratio,
            "fuelCellPowerDeadbandRatio": self.fuel_cell_power_deadband_ratio,
            "fuelCellPowerStepRatio": self.fuel_cell_power_step_ratio,
            "fuelCellDieselPowerLimitRatio": self.fuel_cell_diesel_power_limit_ratio,
            "fuelCellDieselPowerStopMinimumRatio": self.fuel_cell_diesel_power_stop_minimum_ratio,
            "fuelCellStorageSocLimit": self.fuel_cell_storage_soc_limit,
            "fuelCellStorageSocDeadband": self.fuel_cell_storage_soc_deadband,
            "fuelCellHydrogenStorageSocUpperLimit": self.fuel_cell_hydrogen_storage_soc_upper_limit,
            "fuelCellHydrogenStorageSocLowerLimit": self.fuel_cell_hydrogen_storage_soc_lower_limit,
            "storageChargeDeratingCurve": _derating_curve_payload(self.storage_charge_derating_curve),
            "storageDischargeDeratingCurve": _derating_curve_payload(self.storage_discharge_derating_curve),
            "commandValidMinutes": self.command_valid_minutes,
            "optimizationRenewableCurtailmentWeight": self.optimization_renewable_curtailment_weight,
            "optimizationDieselOutputWeight": self.optimization_diesel_output_weight,
            "optimizationCurtailmentSquareWeight": self.optimization_curtailment_square_weight,
            "optimizationSourceStorageAdjustmentSquareWeight": self.optimization_source_storage_adjustment_square_weight,
            "optimizationBalanceDeltaSquareWeight": self.optimization_balance_delta_square_weight,
            "optimizationBalanceDeltaWarningKw": self.optimization_balance_delta_warning_kw,
            "optimizationBalanceToleranceKw": self.optimization_balance_tolerance_kw,
            "optimizationBoundToleranceKw": self.optimization_bound_tolerance_kw,
            "optimizationFtol": self.optimization_ftol,
            "optimizationMaxIterations": self.optimization_max_iterations,
        }

class _Quality:
    def __init__(self, source: str, snapshot_age_seconds: float) -> None:
        self.source = source
        self.snapshot_age_seconds = max(0.0, float(snapshot_age_seconds))
        self.issues: List[str] = []
        self.inputs: Dict[str, Dict[str, Any]] = {}
        self.blocked = False
        self.dispatch_forbidden = source not in {"remote", "trainee-live"}
        if source in {"cached", "trainee-cache"}:
            self.add("学员台实时交换更新失败，当前使用最近一次有效快照", dispatch_forbidden=True)
        elif source == "local":
            self.add("当前使用学员台本地模型数据，不允许闭环下发", dispatch_forbidden=True)

    def input(self, name: str, value: Any, source: str, valid: bool = True) -> None:
        self.inputs[name] = {"value": value, "source": source, "valid": bool(valid)}

    def add(self, message: str, *, blocked: bool = False, dispatch_forbidden: bool = False) -> None:
        if message and message not in self.issues:
            self.issues.append(message)
        self.blocked = self.blocked or blocked
        self.dispatch_forbidden = self.dispatch_forbidden or dispatch_forbidden or blocked

    def payload(self) -> Dict[str, Any]:
        status = "blocked" if self.blocked else "degraded" if self.issues else "ok"
        return {
            "status": status,
            "dispatchAllowed": not self.dispatch_forbidden,
            "source": self.source,
            "snapshotAgeSeconds": round(self.snapshot_age_seconds, 3),
            "issues": list(self.issues),
            "inputs": copy.deepcopy(self.inputs),
        }

def _curve_boundary_value(snapshot: Mapping[str, Any], key: str) -> Optional[float]:
    boundary = snapshot.get("curve_boundary")
    point = boundary.get("point") if (type(boundary) is dict or isinstance(boundary, Mapping)) else None
    return _number(point.get(key)) if (type(point) is dict or isinstance(point, Mapping)) else None

def _measurement_row_enabled(row: Mapping[str, Any]) -> bool:
    """检查单条测点配置行或实时量测行自身是否处于启用/有效状态。"""
    raw_status = str(row.get("status", "") or "").strip().lower()
    if raw_status in {"invalid", "disabled", "off", "0", "false"}:
        return False
    if "enabled" in row and not _boolean(row.get("enabled"), True):
        return False
    raw_valid = row.get("valid", 1)
    if raw_valid == 1 or raw_valid is True:
        return True
    parsed_valid = _number(raw_valid)
    return parsed_valid is not None and int(parsed_valid) == 1


def _environment_measurement_status(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    meas_type: str,
) -> Dict[str, Any]:
    """联合检查气象测点自身配置状态与实时量测可用状态，绝不回退曲线边界。"""
    target_type = str(meas_type or "").strip().upper()
    key = ("Environment", "weather", target_type)

    # 1. 检查测点自身定义配置（优先 definitions.measurement，其次 measurements.definitions）
    raw_definitions: Optional[Sequence[Any]] = None
    definitions_block = snapshot.get("definitions")
    if type(definitions_block) is dict or isinstance(definitions_block, Mapping):
        candidate = definitions_block.get("measurement")
        if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes)):
            raw_definitions = candidate
    if raw_definitions is None:
        raw_measurements = snapshot.get("measurements")
        if type(raw_measurements) is dict or isinstance(raw_measurements, Mapping):
            candidate = raw_measurements.get("definitions")
            if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes)):
                raw_definitions = candidate

    configured = True
    config_valid = True
    if raw_definitions is not None and len(raw_definitions) > 0:
        matched_def: Optional[Mapping[str, Any]] = None
        for row in raw_definitions:
            if not (type(row) is dict or isinstance(row, Mapping)):
                continue
            if (
                str(row.get("dev_type", "")) == key[0]
                and str(row.get("dev_name", "")) == key[1]
                and str(row.get("meas_type", "")).strip().upper() == key[2]
            ):
                matched_def = row
                break
        if matched_def is None:
            configured = False
            config_valid = False
        else:
            configured = True
            config_valid = _measurement_row_enabled(matched_def)

    if not configured:
        return {
            "available": False,
            "configured": False,
            "configValid": False,
            "liveValid": False,
            "value": None,
            "source": "none",
            "reason": "not_configured",
        }
    if not config_valid:
        return {
            "available": False,
            "configured": True,
            "configValid": False,
            "liveValid": False,
            "value": None,
            "source": "none",
            "reason": "config_disabled",
        }

    # 2. 检查实时量测通道：SCADA 显式标为无效/停用时严禁回退 real 或 curve_boundary
    raw_measurements = snapshot.get("measurements")
    scada_matched: Optional[Mapping[str, Any]] = None
    if type(raw_measurements) is dict or isinstance(raw_measurements, Mapping):
        scada_rows = raw_measurements.get("scada")
        if isinstance(scada_rows, Sequence) and not isinstance(scada_rows, (str, bytes)):
            for row in scada_rows:
                if not (type(row) is dict or isinstance(row, Mapping)):
                    continue
                if (
                    str(row.get("dev_type", "")) == key[0]
                    and str(row.get("dev_name", "")) == key[1]
                    and str(row.get("meas_type", "")).strip().upper() == key[2]
                ):
                    scada_matched = row
                    break

    if scada_matched is not None:
        if not _measurement_row_enabled(scada_matched):
            return {
                "available": False,
                "configured": True,
                "configValid": True,
                "liveValid": False,
                "value": None,
                "source": "scada",
                "reason": "scada_invalid",
            }
        scada_value = _number(scada_matched.get("value"))
        if scada_value is None or not math.isfinite(scada_value) or scada_value < 0.0:
            return {
                "available": False,
                "configured": True,
                "configValid": True,
                "liveValid": False,
                "value": None,
                "source": "scada",
                "reason": "scada_value_invalid",
            }
        return {
            "available": True,
            "configured": True,
            "configValid": True,
            "liveValid": True,
            "value": float(scada_value),
            "source": "scada",
            "reason": "valid",
        }

    indexed = measurements.get(key)
    if (
        indexed is not None
        and _measurement_row_enabled(indexed.row)
        and math.isfinite(indexed.value)
        and indexed.value >= 0.0
    ):
        return {
            "available": True,
            "configured": True,
            "configValid": True,
            "liveValid": True,
            "value": float(indexed.value),
            "source": str(indexed.source or "real"),
            "reason": "valid",
        }

    return {
        "available": False,
        "configured": True,
        "configValid": True,
        "liveValid": False,
        "value": None,
        "source": "none",
        "reason": "measurement_missing",
    }


def _observed_environment_value(
    snapshot: Mapping[str, Any],
    measurement: Optional[MeasurementValue],
    boundary_key: str,
) -> Optional[float]:
    if measurement is not None and math.isfinite(measurement.value):
        return measurement.value
    return _curve_boundary_value(snapshot, boundary_key)

def _load_boundary(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    quality: _Quality,
) -> float:
    total = 0.0
    sources: set[str] = set()
    measured_count = 0
    for device in snapshot.get("devices", []) or []:
        if not (type(device) is dict or isinstance(device, Mapping)) or _device_model_block(device) not in {"ACLoad", "DCLoad"}:
            continue
        if not _is_online(device, measurements):
            continue
        measured = _measured(
            measurements,
            _device_type(device),
            _device_name(device),
            ("P_LOAD", "P", "P_AC", "P_DC"),
        )
        if measured is None:
            continue
        total += measured.value
        measured_count += 1
        sources.add(measured.source)
    if measured_count:
        source = next(iter(sources)) if len(sources) == 1 else "mixed"
        quality.input("load", total, source, True)
        return total

    boundary = snapshot.get("curve_boundary")
    boundary_load = _number(boundary.get("load_total")) if (type(boundary) is dict or isinstance(boundary, Mapping)) else None
    if boundary_load is not None and boundary_load >= 0:
        quality.input("load", boundary_load, "curve_boundary", True)
        return boundary_load

    estimated = 0.0
    estimated_count = 0
    for device in snapshot.get("devices", []) or []:
        if not (type(device) is dict or isinstance(device, Mapping)) or _device_model_block(device) not in {"ACLoad", "DCLoad"}:
            continue
        if not _is_online(device, measurements):
            continue
        raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
        values = device.get("set_values") if isinstance(device.get("set_values"), Mapping) else {}
        value = _number(values.get("p_set", raw.get("pv0", raw.get("p_set"))))
        if value is not None and value >= 0:
            estimated += value
            estimated_count += 1
    if estimated_count:
        quality.input("load", estimated, "model_setpoint", True)
        return estimated

    quality.input("load", None, "missing", False)
    return 0.0

def _normalized_generation_current(
    measured: Optional[MeasurementValue],
    capacity_kw: float,
    quality: _Quality,
    label: str,
) -> Tuple[Optional[float], Optional[float]]:
    if measured is None:
        return None, None
    current = measured.value
    if current < 0.0:
        quality.add(f"{label}实时有功 {current:g} kW 低于新能源功率下限 0 kW")
    if capacity_kw > 0 and current > capacity_kw:
        quality.add(
            f"{label}实时有功 {current:g} kW 超过额定容量 {capacity_kw:g} kW"
        )
    return current, current

def _topology_payload(
    spec: _LinkedResourceSpec,
    connection: Optional[ResourceConnection],
) -> Dict[str, Any]:
    if connection is None:
        return {
            "technology": spec.technology,
            "resourceDevType": spec.dev_type,
            "resourceDevName": spec.dev_name,
            "connectionSide": "INVALID",
            "activelyConnected": False,
            "busbarType": "",
            "busbarName": "",
            "busbarNode": "",
            "structuralPath": [],
            "activePath": [],
            "converterPath": [],
            "gridComponentId": "",
            "dcTransferGroupId": "",
            "topologyStatusLabel": "资源模型引用或端子无效",
        }
    return {
        "technology": spec.technology,
        "resourceDevType": spec.dev_type,
        "resourceDevName": spec.dev_name,
        "connectionSide": connection.connection_side,
        "activelyConnected": bool(connection.actively_connected),
        "busbarType": connection.busbar_type,
        "busbarName": connection.busbar_name,
        "busbarNode": connection.busbar_node,
        "structuralPath": list(connection.structural_path),
        "activePath": list(connection.active_path),
        "converterPath": list(connection.converter_path),
        "gridComponentId": connection.grid_component_id,
        "dcTransferGroupId": connection.dc_transfer_group_id,
        "topologyStatusLabel": connection.topology_status_label,
    }

def _renewable_rows(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    resource_specs: Sequence[_LinkedResourceSpec],
    connections: Mapping[Tuple[str, str], ResourceConnection],
    quality: _Quality,
    *,
    observed_wind_speed: Optional[float] = None,
    observed_solar_irradiance: Optional[float] = None,
    observed_air_temperature: Optional[float] = None,
    wind_measurement_available: bool = False,
    solar_measurement_available: bool = False,
    control_wind_speed: Optional[float] = None,
    control_solar_irradiance: Optional[float] = None,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    categories = {
        ("wind", "AC"): "交流风电",
        ("wind", "DC"): "直流风电",
        ("pv", "AC"): "交流光伏",
        ("pv", "DC"): "直流光伏",
    }
    for spec in resource_specs:
        device = spec.device
        dev_type = spec.dev_type
        name = spec.dev_name
        topology = _topology_payload(spec, connections.get(spec.topology_key))
        connection_side = topology["connectionSide"]
        device_online = _is_online(device, measurements)
        online = device_online and topology["activelyConnected"]
        capacity = _rated_capacity(
            spec.parameter,
            device,
            "风电" if spec.technology == "wind" else "光伏",
        )
        weather_available_kw = _renewable_weather_available_kw(
            spec.technology,
            spec.parameter,
            capacity,
            wind_speed=observed_wind_speed,
            solar_irradiance=observed_solar_irradiance,
            air_temperature=observed_air_temperature,
        )
        # 仅当对应气象测点配置与实时状态均有效时，才计算用于控制决策的理论可发上限
        weather_measurement_available = bool(
            wind_measurement_available
            if spec.technology == "wind"
            else solar_measurement_available
            if spec.technology == "pv"
            else False
        )
        control_weather_available_kw: Optional[float] = None
        if weather_measurement_available:
            if (
                spec.technology == "pv"
                and control_solar_irradiance is not None
                and control_solar_irradiance <= 1.0
            ):
                control_weather_available_kw = 0.0
            else:
                control_weather_available_kw = _renewable_weather_available_kw(
                    spec.technology,
                    spec.parameter,
                    capacity,
                    wind_speed=control_wind_speed if spec.technology == "wind" else None,
                    solar_irradiance=(
                        control_solar_irradiance if spec.technology == "pv" else None
                    ),
                    air_temperature=observed_air_temperature,
                )
        measured = (
            _measured(measurements, dev_type, name, ("P_GEN", "P", "P_AC", "P_DC"))
            if device_online
            else None
        )
        category = categories.get(
            (spec.technology, connection_side),
            "拓扑未解析新能源",
        )
        current, planning_current = _normalized_generation_current(
            measured,
            capacity,
            quality,
            f"{category}{name}",
        )
        set_type = _preferred_set_type(snapshot, device, ("p_set",))
        capability_known = capacity > EPSILON
        recovery_ready = planning_current is not None and capability_known
        signed_baseline_valid = planning_current is None or planning_current >= 0.0
        capacity_baseline_valid = (
            planning_current is None
            or not capability_known
            or planning_current <= capacity
        )
        identity_valid = not spec.identity_diagnostic
        topology_valid = connection_side in {"AC", "DC"}
        commandable = bool(
            online
            and topology_valid
            and identity_valid
            and set_type
            and recovery_ready
        )

        if not topology_valid:
            quality.add(
                f"新能源{name}拓扑状态{connection_side}：{topology['topologyStatusLabel']}，本轮仅保留诊断"
            )
        elif device_online and not topology["activelyConnected"]:
            quality.add(f"新能源{name}当前拓扑断开，本轮不参与自动策略")
        if device_online and not set_type:
            quality.add(f"新能源{name}缺少有效p_set有功遥调点，本轮仅保留诊断")
        if online and planning_current is not None and planning_current < 0.0:
            quality.add(
                f"新能源{name}实时有功 {planning_current:g} kW 为负，按真实下限 0 kW 形成纠偏设点"
            )

        status_label = (
            topology["topologyStatusLabel"]
            if not topology_valid
            else "停用"
            if not device_online
            else "当前断开"
            if not topology["activelyConnected"]
            else "设备身份重复·仅保留诊断"
            if not identity_valid
            else "无遥调点"
            if not set_type
            else "额定容量无效"
            if not capability_known
            else "实时有功未知"
            if planning_current is None
            else "实时有功低于下限·校正至0"
            if not signed_baseline_valid
            else "实时有功超过容量·校正至额定上限"
            if not capacity_baseline_valid
            else "可控"
        )
        rows.append(
            {
                **topology,
                "category": category,
                "dev_type": dev_type,
                "dev_name": name,
                "source_name": name,
                "deviceOnline": device_online,
                "online": online,
                "environmentKnown": weather_measurement_available and control_weather_available_kw is not None,
                "weatherMeasurementAvailable": weather_measurement_available,
                "controlWeatherAvailableKw": control_weather_available_kw,
                "weatherAvailableKnown": weather_available_kw is not None,
                "weatherAvailableKw": weather_available_kw,
                "capabilityKnown": capability_known,
                "resourceIdentityValid": identity_valid,
                "resourceIdentityDiagnostic": spec.identity_diagnostic,
                "capacityKw": capacity,
                "currentKw": current if device_online else 0.0,
                "planningCurrentKw": planning_current if device_online else 0.0,
                "headroomKw": (
                    max(0.0, capacity - (planning_current or 0.0))
                    if recovery_ready
                    and signed_baseline_valid
                    else 0.0
                ),
                "commandable": commandable,
                "availableKw": capacity if capability_known else None,
                "set_type": set_type if topology_valid else "",
                "statusLabel": status_label,
            }
        )
    return rows

def _diesel_rows(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    resource_keys: Optional[set[Tuple[str, str]]] = None,
    quality: Optional[_Quality] = None,
) -> List[Dict[str, Any]]:
    wind_indexes = {
        str(row.get("idx_acgenerator", "")).strip()
        for row in _parameter_rows(snapshot, "ACWindGen")
        if str(row.get("idx_acgenerator", "")).strip()
    }
    relation_parameters = {
        str(row.get("idx_acgenerator", "")).strip(): row
        for row in _parameter_rows(snapshot, "ACDieselGen")
        if str(row.get("idx_acgenerator", "")).strip()
    }
    rows: List[Dict[str, Any]] = []
    for device in snapshot.get("devices", []) or []:
        if not (type(device) is dict or isinstance(device, Mapping)) or _device_model_block(device) != "ACGenerator":
            continue
        if resource_keys and _device_key(device) in resource_keys:
            continue
        if _device_index(device) in wind_indexes:
            continue
        name = _device_name(device)
        dev_type = _device_type(device)
        raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
        parameter = relation_parameters.get(_device_index(device), {})
        if not parameter:
            continue
        online = _is_online(device, measurements)
        capacity = _positive(
            (
                parameter.get("p_max"),
                parameter.get("rated_capacity"),
                parameter.get("rated_power"),
                raw.get("p_max"),
                raw.get("rated_capacity"),
                raw.get("rated_power"),
            )
        )
        rated_capacity = _positive(
            (
                parameter.get("rated_capacity"),
                parameter.get("rated_power"),
                raw.get("rated_capacity"),
                raw.get("rated_power"),
                parameter.get("p_max"),
                raw.get("p_max"),
            )
        )
        defined_min = max(
            0.0,
            _number(
                parameter.get(
                    "p_min",
                    parameter.get("min_power", parameter.get("minimum_power", raw.get("p_min", raw.get("min_power", raw.get("minimum_power"))))),
                ),
                0.0,
            )
            or 0.0,
        )
        minimum = min(defined_min, capacity) if online and capacity > 0 else defined_min if online else 0.0
        measured = _measured(measurements, dev_type, name, ("P_GEN", "P")) if online else None
        current = measured.value if measured else None
        set_type = _preferred_set_type(snapshot, device, ("p_set", "p_ac_set"))
        limits_valid = bool(capacity > EPSILON and minimum <= capacity + EPSILON)
        commandable = bool(
            online
            and current is not None
            and math.isfinite(current)
            and limits_valid
            and set_type
        )
        state_eligible = bool(
            online
            and current is not None
            and math.isfinite(current)
            and limits_valid
        )
        if online and current is None and quality is not None:
            quality.add(f"柴油发电机{name}缺少有效实时有功，本轮禁止直接下发有功策略")
        if online and not limits_valid and quality is not None:
            quality.add(f"柴油发电机{name}有功上下限无效，本轮禁止直接下发有功策略")
        rows.append(
            {
                "category": "柴油发电",
                "dev_type": dev_type,
                "model_block": "ACGenerator",
                "dev_name": name,
                "online": online,
                "commandable": commandable,
                "stateEligible": state_eligible,
                "currentKw": current if online else 0.0,
                "minKw": minimum,
                "capacityKw": capacity,
                "ratedCapacityKw": rated_capacity,
                "set_type": set_type,
                "directDispatchBlockedReason": (
                    "缺少有效p_set有功遥调点"
                    if online and not set_type
                    else "实时有功未知"
                    if online and current is None
                    else "有功上下限无效"
                    if online and not limits_valid
                    else ""
                ),
                "statusLabel": (
                    "停用"
                    if not online
                    else "实时有功未知"
                    if current is None
                    else "有功边界无效"
                    if not limits_valid
                    else "平衡运行·可直控"
                    if set_type
                    else "平衡运行·无有功遥调点"
                ),
            }
        )
    return rows

def _annotate_diesel_topology(
    rows: Sequence[MutableMapping[str, Any]],
    connections: Mapping[Tuple[str, str], ResourceConnection],
    device_component_ids: Mapping[Tuple[str, str], str],
) -> None:
    for row in rows:
        key = (str(row.get("model_block", "")), str(row.get("dev_name", "")))
        connection = connections.get(key)
        component_id = str(device_component_ids.get(key, ""))
        topology_valid = bool(
            connection is not None
            and connection.connection_side == "AC"
            and connection.actively_connected
            and connection.grid_component_id
        )
        row.update(
            {
                "connectionSide": (
                    connection.connection_side if connection is not None else "INVALID"
                ),
                "activelyConnected": bool(
                    connection is not None and connection.actively_connected
                ),
                "busbarType": connection.busbar_type if connection is not None else "",
                "busbarName": connection.busbar_name if connection is not None else "",
                "busbarNode": connection.busbar_node if connection is not None else "",
                "gridComponentId": (
                    connection.grid_component_id
                    if connection is not None
                    else component_id
                ),
                "topologyStatusLabel": (
                    connection.topology_status_label
                    if connection is not None
                    else "资源模型引用或端子无效"
                ),
                "stateEligible": bool(
                    row.get("stateEligible") and topology_valid
                ),
            }
        )
        if not topology_valid:
            row["commandable"] = False
            row["stateEligible"] = False
            row["set_type"] = ""
            row["directDispatchBlockedReason"] = (
                "设备拓扑无效或未活动接入交流分量"
            )
            row["statusLabel"] = "拓扑无效·禁止自动控制"

def _measurement_sample_clock(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    measurement_clock = snapshot.get("measurement_clock")
    if (
        (type(measurement_clock) is dict or isinstance(measurement_clock, Mapping))
        and (_number(measurement_clock.get("step_count"), 0.0) or 0.0) > 0.0
    ):
        return measurement_clock
    clock = snapshot.get("clock")
    return clock if (type(clock) is dict or isinstance(clock, Mapping)) else {}

def _effective_step_minutes(snapshot: Mapping[str, Any]) -> float:
    parameters = snapshot.get("system_parameters")
    if (type(parameters) is dict or isinstance(parameters, Mapping)):
        effective = _number(parameters.get("effective_step_minutes"))
        if effective is not None and effective > 0:
            return effective
    clock = _measurement_sample_clock(snapshot)
    step = max(
        SIMULATION_MINIMUM_STEP_MINUTES,
        _number(
            clock.get("step_minutes"),
            SIMULATION_DEFAULT_STEP_MINUTES,
        )
        or SIMULATION_DEFAULT_STEP_MINUTES,
    )
    speed = max(
        SIMULATION_MINIMUM_SPEED,
        _number(clock.get("speed"), SIMULATION_DEFAULT_SPEED)
        or SIMULATION_DEFAULT_SPEED,
    )
    return step * speed

def _storage_control_horizon_minutes(
    snapshot: Mapping[str, Any],
    settings: RenewableControlSettings,
) -> float:
    effective_step = _effective_step_minutes(snapshot)
    effective_step_seconds = effective_step * 60.0
    interval_seconds = _simulation_control_interval_seconds(
        settings.interval_seconds
    )
    simulator_steps = max(
        1,
        int(math.ceil(interval_seconds / effective_step_seconds)),
    )
    return effective_step * simulator_steps

def _storage_rows(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    settings: RenewableControlSettings,
    quality: _Quality,
    resource_specs: Sequence[_LinkedResourceSpec],
    connections: Mapping[Tuple[str, str], ResourceConnection],
    dc_transfer_groups: Mapping[str, DcTransferGroup],
) -> List[Dict[str, Any]]:
    control_horizon_minutes = _storage_control_horizon_minutes(snapshot, settings)
    step_hours = max(
        STORAGE_MINIMUM_CONTROL_HORIZON_HOURS,
        control_horizon_minutes / 60.0,
    )
    rows: List[Dict[str, Any]] = []
    categories = {
        ("AC", "grid_following"): "交流跟网储能",
        ("DC", "grid_following"): "直流跟网储能",
        ("AC", "balance"): "交流平衡储能",
        ("DC", "balance"): "直流平衡储能",
    }
    for spec in resource_specs:
        parameter = spec.parameter
        device = spec.device
        dev_type = spec.dev_type
        name = spec.dev_name
        topology = _topology_payload(spec, connections.get(spec.topology_key))
        connection_side = topology["connectionSide"]
        topology_valid = connection_side in {"AC", "DC"}
        identity_valid = not spec.identity_diagnostic
        device_online = _is_online(device, measurements)
        online = device_online and topology["activelyConnected"]
        mode = _runtime_mode(snapshot, device).strip().upper()
        preferred_set_type = _preferred_set_type(snapshot, device, ("p_set",))
        role = (
            "grid_following"
            if mode in GRID_FOLLOWING_STORAGE_MODES and preferred_set_type == "p_set"
            else "balance"
            if mode in BALANCE_STORAGE_MODES
            else "uncontrolled"
        )
        set_type = (
            preferred_set_type
            if role in {"grid_following", "balance"}
            else ""
        )
        category = categories.get(
            (connection_side, role),
            "拓扑未解析储能",
        )
        soc_measurement = (
            _measured(measurements, dev_type, name, ("SOC",))
            if device_online
            else None
        )
        live_soc = _live_soc_ratio(soc_measurement.value) if soc_measurement else None
        soc_weight = _number(soc_measurement.row.get("weight"), 0.0) if soc_measurement else 0.0
        soc_noise_sigma = 1.0 / math.sqrt(soc_weight) if soc_weight and soc_weight > 0 else 0.0
        soc = live_soc
        soc_known = live_soc is not None
        if online and not soc_known:
            quality.add(f"储能{name}缺少有效实时SOC，本轮禁止该储能参与充放电调节")
        power = (
            _measured(measurements, dev_type, name, ("P_GEN", "P", "P_AC", "P_DC"))
            if device_online
            else None
        )
        raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
        capacity_value = _positive(
            (
                parameter.get("energy_capacity"),
                parameter.get("capacity_kwh"),
                parameter.get("emva"),
                raw.get("energy_capacity"),
                raw.get("capacity_kwh"),
                raw.get("rated_capacity"),
            )
        )
        calculation_capacity = max(EPSILON, capacity_value)
        lower_value = parameter.get("soc_lower_limit", parameter.get("soc_min"))
        upper_value = parameter.get("soc_upper_limit", parameter.get("soc_max"))
        defined_min = _ratio(lower_value, None)
        defined_max = _ratio(upper_value, None)
        soc_min = _clamp(defined_min if defined_min is not None else settings.soc_min, 0.0, 1.0)
        soc_max = _clamp(defined_max if defined_max is not None else settings.soc_max, soc_min, 1.0)
        efficiency = _storage_efficiency(parameter)
        charge_limit_value = parameter.get(
            "max_charge_power",
            parameter.get("charge_p_max"),
        )
        discharge_limit_value = parameter.get(
            "max_discharge_power",
            parameter.get("dis_charge_p_max", parameter.get("discharge_p_max")),
        )
        parsed_charge_max = _number(charge_limit_value)
        parsed_discharge_max = _number(discharge_limit_value)
        charge_max = max(0.0, parsed_charge_max or 0.0)
        discharge_max = max(0.0, parsed_discharge_max or 0.0)
        lower_present = lower_value is not None and str(lower_value).strip() != ""
        upper_present = upper_value is not None and str(upper_value).strip() != ""
        limits_valid = bool(
            capacity_value > EPSILON
            and parsed_charge_max is not None
            and parsed_charge_max >= 0.0
            and parsed_discharge_max is not None
            and parsed_discharge_max >= 0.0
            and (parsed_charge_max > EPSILON or parsed_discharge_max > EPSILON)
            and (not lower_present or defined_min is not None)
            and (not upper_present or defined_max is not None)
            and soc_min < soc_max - EPSILON
        )
        charge_by_energy = (
            max(
                0.0,
                ((soc_max - (soc or 0.0)) * calculation_capacity)
                / (efficiency * step_hours),
            )
            if soc_known
            else 0.0
        )
        discharge_by_energy = (
            max(
                0.0,
                (((soc or 0.0) - soc_min) * calculation_capacity * efficiency)
                / step_hours,
            )
            if soc_known
            else 0.0
        )
        charge_before_derating = min(charge_max, charge_by_energy)
        discharge_before_derating = min(discharge_max, discharge_by_energy)
        charge_derating_factor = (
            0.0
            if not soc_known or (soc or 0.0) >= soc_max - EPSILON
            else _derating_factor(float(soc), settings.storage_charge_derating_curve)
        )
        discharge_derating_factor = (
            0.0
            if not soc_known or (soc or 0.0) <= soc_min + EPSILON
            else _derating_factor(float(soc), settings.storage_discharge_derating_curve)
        )
        charge_curve_limit = charge_max * charge_derating_factor
        discharge_curve_limit = discharge_max * discharge_derating_factor
        charge_power = min(charge_before_derating, charge_curve_limit)
        discharge_power = min(discharge_before_derating, discharge_curve_limit)
        soc_constraint = (
            "offline"
            if not device_online
            else "disconnected"
            if not topology["activelyConnected"]
            else "unknown"
            if not soc_known
            else "above_upper"
            if (soc or 0.0) >= soc_max
            else "below_lower"
            if (soc or 0.0) <= soc_min
            else "normal"
        )
        if not topology_valid:
            quality.add(
                f"储能{name}拓扑状态{connection_side}：{topology['topologyStatusLabel']}，本轮仅保留诊断"
            )
        elif device_online and not topology["activelyConnected"]:
            quality.add(f"储能{name}当前拓扑断开，本轮不参与自动策略")
        if online and power is None:
            quality.add(
                f"储能{name}缺少有效实时有功，本轮禁止该储能参与自动调节",
                blocked=role == "balance" and topology_valid,
            )
        if device_online and not limits_valid:
            quality.add(f"储能{name}功率边界、能量容量或SOC上下限无效，本轮仅禁用该储能")
        if device_online and role == "uncontrolled":
            quality.add(f"储能{name}控制模式{mode or '--'}或p_set遥调点无效，本轮仅保留诊断")

        group = dc_transfer_groups.get(topology["dcTransferGroupId"])
        indirect_control_devices = [
            {"dev_type": dev_type_value, "dev_name": dev_name_value}
            for dev_type_value, dev_name_value in getattr(group, "converter_keys", ())
        ]
        if not indirect_control_devices:
            indirect_control_devices = [
                {"dev_type": dev_type_value, "dev_name": dev_name_value}
                for dev_type_value, dev_name_value in topology["converterPath"]
                if (dev_type_value, dev_name_value)
                in {
                    key
                    for item in dc_transfer_groups.values()
                    for key in getattr(item, "converter_keys", ())
                }
            ]

        commandable = bool(
            role in {"grid_following", "balance"}
            and topology_valid
            and identity_valid
            and online
            and soc_known
            and power is not None
            and limits_valid
            and set_type == "p_set"
        )
        state_eligible = bool(
            role == "balance"
            and topology_valid
            and identity_valid
            and online
            and soc_known
            and power is not None
            and limits_valid
        )
        status_label = (
            topology["topologyStatusLabel"]
            if not topology_valid
            else "停用"
            if not device_online
            else "当前断开"
            if not topology["activelyConnected"]
            else "设备身份重复·仅保留诊断"
            if not identity_valid
            else "控制模式或遥调点无效"
            if role == "uncontrolled"
            else "SOC未知"
            if not soc_known
            else "实时有功未知"
            if power is None
            else "储能边界无效"
            if not limits_valid
            else "SOC达到上限·禁止充电"
            if soc_constraint == "above_upper"
            else "SOC达到下限·禁止放电"
            if soc_constraint == "below_lower"
            else "构网储能·可直控"
            if role == "balance" and commandable
            else "构网储能·间接校核"
            if role == "balance"
            else f"充电降额 {charge_derating_factor * 100:.0f}%"
            if charge_derating_factor < 1.0 - EPSILON
            else f"放电降额 {discharge_derating_factor * 100:.0f}%"
            if discharge_derating_factor < 1.0 - EPSILON
            else "可控"
        )
        rows.append(
            {
                **topology,
                "category": category,
                "dev_type": dev_type,
                "dev_name": name,
                "source_name": name,
                "deviceOnline": device_online,
                "online": online,
                "resourceIdentityValid": identity_valid,
                "resourceIdentityDiagnostic": spec.identity_diagnostic,
                "commandable": commandable,
                "stateEligible": state_eligible,
                "role": role,
                "mode": mode,
                "currentKw": power.value if power else 0.0 if not device_online else None,
                "soc": soc,
                "socKnown": soc_known,
                "socNoiseSigma": soc_noise_sigma,
                "socMin": soc_min,
                "socMax": soc_max,
                "socConstraint": soc_constraint,
                "capacityKwh": capacity_value,
                "maxChargePowerKw": charge_max,
                "maxDischargePowerKw": discharge_max,
                "limitsValid": limits_valid,
                "chargePowerBeforeDerating": charge_before_derating,
                "dischargePowerBeforeDerating": discharge_before_derating,
                "chargeDeratingFactor": charge_derating_factor,
                "dischargeDeratingFactor": discharge_derating_factor,
                "chargeDeratingCurveLimitKw": charge_curve_limit,
                "dischargeDeratingCurveLimitKw": discharge_curve_limit,
                "chargeDeratingActive": charge_max > EPSILON and charge_derating_factor < 1.0 - EPSILON,
                "dischargeDeratingActive": discharge_max > EPSILON and discharge_derating_factor < 1.0 - EPSILON,
                "chargePower": charge_power,
                "dischargePower": discharge_power,
                "efficiency": efficiency,
                "controlHorizonMinutes": control_horizon_minutes,
                "set_type": set_type,
                "directDispatchBlockedReason": (
                    "缺少有效p_set有功遥调点"
                    if role == "balance" and not set_type
                    else ""
                ),
                "indirectControlDevices": indirect_control_devices,
                "statusLabel": status_label,
            }
        )
    return rows

def _converter_rows(
    snapshot: Mapping[str, Any],
    measurements: Mapping[Tuple[str, str, str], MeasurementValue],
    converter_group_ids: Optional[Mapping[Tuple[str, str], str]] = None,
    internal_converter_keys: Optional[set[Tuple[str, str]]] = None,
    grid_converter_keys: Optional[set[Tuple[str, str]]] = None,
    identity_diagnostics: Optional[Mapping[Tuple[str, str], str]] = None,
    quality: Optional[_Quality] = None,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    devices_by_key: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    dispatchable_keys = set(grid_converter_keys or ())
    for device in snapshot.get("devices", []) or []:
        if not (type(device) is dict or isinstance(device, Mapping)):
            continue
        key = _device_model_key(device)
        if key in dispatchable_keys:
            devices_by_key.setdefault(key, []).append(device)

    for key, candidates in devices_by_key.items():
        if key in (internal_converter_keys or set()):
            continue
        if grid_converter_keys is not None and key not in grid_converter_keys:
            continue
        device = (
            candidates[0]
            if len(candidates) == 1
            else min(
                candidates,
                key=lambda item: (
                    _natural_topology_identity(_device_index(item)),
                    json.dumps(dict(item), ensure_ascii=False, sort_keys=True, default=str),
                ),
            )
        )
        identity_diagnostic = (identity_diagnostics or {}).get(key, "")
        if identity_diagnostic and quality is not None:
            quality.add(identity_diagnostic)
        raw = device.get("raw") if isinstance(device.get("raw"), Mapping) else {}
        converter_role = "grid"
        converter_direction = AC_TO_DC
        ac_balance_coefficient, dc_balance_coefficient = (
            converter_balance_coefficients(converter_direction)
        )
        mode = _runtime_mode(snapshot, device)
        set_type = _preferred_set_type(
            snapshot,
            device,
            converter_power_setpoint_fields(raw),
        )
        online = _is_online(device, measurements)
        measured = _measured(
            measurements,
            _device_type(device),
            _device_name(device),
            ("P_AC", "P_DC", "P"),
        )
        measured_p_ac_kw = None
        if measured is not None and converter_direction:
            measured_type = str(measured.row.get("meas_type", "P_AC") or "P_AC")
            measured_p_ac_kw = converter_power_in_ac_terminal_convention(
                measured.value,
                converter_direction,
                measured_type,
            )
        group_id = (converter_group_ids or {}).get(key, "")
        p_ac_min = _number(
            raw.get(
                "p_ac_min",
                raw.get("ac_p_min", device.get("p_ac_min", device.get("ac_p_min"))),
            )
        )
        p_ac_max = _number(
            raw.get(
                "p_ac_max",
                raw.get("ac_p_max", device.get("p_ac_max", device.get("ac_p_max"))),
            )
        )
        p_ac_limits_valid = bool(
            p_ac_min is not None
            and p_ac_max is not None
            and math.isfinite(p_ac_min)
            and math.isfinite(p_ac_max)
            and p_ac_min <= p_ac_max
        )
        if not p_ac_limits_valid:
            p_dc_min = _number(
                raw.get(
                    "p_dc_min",
                    raw.get("dc_p_min", device.get("p_dc_min", device.get("dc_p_min"))),
                )
            )
            p_dc_max = _number(
                raw.get(
                    "p_dc_max",
                    raw.get("dc_p_max", device.get("p_dc_max", device.get("dc_p_max"))),
                )
            )
            if (
                p_dc_min is not None
                and p_dc_max is not None
                and math.isfinite(p_dc_min)
                and math.isfinite(p_dc_max)
                and p_dc_min <= p_dc_max
            ):
                p_ac_min = -float(p_dc_max)
                p_ac_max = -float(p_dc_min)
        if p_ac_min is None or p_ac_max is None:
            rated_capacity = _positive(
                (
                    raw.get("rated_capacity"),
                    raw.get("rated_power"),
                    device.get("rated_capacity"),
                    device.get("rated_power"),
                )
            )
            if rated_capacity > EPSILON:
                p_ac_min = -rated_capacity
                p_ac_max = rated_capacity
        limits_valid = bool(
            p_ac_min is not None
            and p_ac_max is not None
            and math.isfinite(p_ac_min)
            and math.isfinite(p_ac_max)
            and p_ac_min <= p_ac_max
        )
        signed_min = float(p_ac_min) if limits_valid else 0.0
        signed_max = float(p_ac_max) if limits_valid else 0.0
        transfer_capacity = (
            max(abs(signed_min), abs(signed_max)) if limits_valid else 0.0
        )
        commandable = bool(
            not identity_diagnostic
            and online
            and mode in POWER_CONTROL_MODES
            and set_type
            and measured is not None
            and limits_valid
            and group_id
        )
        diagnostic = ""
        if identity_diagnostic:
            diagnostic = "设备身份重复"
        elif not online:
            diagnostic = "设备离线"
        elif mode not in POWER_CONTROL_MODES:
            diagnostic = f"控制模式{mode or '--'}不支持有功调节"
        elif not set_type:
            diagnostic = "缺少有效有功遥调点"
        elif measured is None:
            diagnostic = "缺少有效实时有功"
        elif not limits_valid:
            diagnostic = "设备有功上下限无效"
        elif not group_id:
            diagnostic = "拓扑无效或未活动接入直流传输组"
        if diagnostic and quality is not None:
            quality.add(
                f"交直流变流器{_device_name(device)}{diagnostic}，本轮禁止自动控制",
                blocked=bool(
                    online
                    and measured is None
                    and group_id
                ),
            )
        rows.append(
            {
                "category": "交直流变流器",
                "dev_type": _device_type(device),
                "model_block": _device_model_block(device),
                "dev_name": _device_name(device),
                "online": online,
                "commandable": commandable,
                "resourceIdentityValid": not identity_diagnostic,
                "resourceIdentityDiagnostic": identity_diagnostic,
                "explicitType": "",
                "converterRole": converter_role,
                "converterRoleSource": "topology",
                "converterDirection": converter_direction,
                "acBalanceCoefficient": ac_balance_coefficient,
                "dcBalanceCoefficient": dc_balance_coefficient,
                "mode": mode,
                "set_type": set_type if commandable else "",
                "currentKw": measured_p_ac_kw,
                "transferCapacityKw": transfer_capacity,
                "signedMinTargetKw": signed_min,
                "signedMaxTargetKw": signed_max,
                "limitsValid": limits_valid,
                "capacitySource": "device_limits" if limits_valid else "missing",
                "dcTransferGroupId": group_id,
                "statusLabel": (
                    f"{diagnostic}·仅保留诊断"
                    if diagnostic
                    else (
                        f"双向并联 {mode}·系统汇总P_DC正向DC→AC"
                    )
                ),
            }
        )
    return rows

def _apply_grid_forming_fail_closed_scopes(
    renewable_rows: Sequence[MutableMapping[str, Any]],
    storage_rows: Sequence[MutableMapping[str, Any]],
    converter_rows: Sequence[MutableMapping[str, Any]],
    diesel_rows: Sequence[MutableMapping[str, Any]],
    quality: _Quality,
) -> Dict[str, set[str]]:
    blocked_ac_components: set[str] = set()
    blocked_dc_groups: set[str] = set()
    for row in storage_rows:
        if (
            row.get("role") != "balance"
            or not row.get("deviceOnline")
            or not row.get("activelyConnected")
            or row.get("stateEligible")
        ):
            continue
        side = str(row.get("connectionSide", ""))
        scope_id = str(
            row.get("gridComponentId", "")
            if side == "AC"
            else row.get("dcTransferGroupId", "")
        )
        if not scope_id:
            continue
        missing = []
        if not row.get("socKnown"):
            missing.append("SOC")
        if _number(row.get("currentKw")) is None:
            missing.append("实时有功")
        if not row.get("limitsValid"):
            missing.append("功率/能量/SOC边界")
        if not missing:
            missing.append("设备身份或拓扑状态")
        if side == "AC":
            blocked_ac_components.add(scope_id)
            scope_label = f"交流分量闭锁（{scope_id}）"
        else:
            blocked_dc_groups.add(scope_id)
            scope_label = f"直流传输组闭锁（{scope_id}）"
        reason = (
            f"构网储能{row.get('dev_name', '')}缺少有效{'、'.join(missing)}，"
            f"{scope_label}，禁止该范围自动策略"
        )
        row["automaticControlBlocked"] = True
        row["automaticControlBlockedReason"] = reason
        quality.add(reason)

    def block_row(row: MutableMapping[str, Any], reason: str) -> None:
        row["commandable"] = False
        row["stateEligible"] = False
        row["automaticControlBlocked"] = True
        row["automaticControlBlockedReason"] = reason
        status = str(row.get("statusLabel", "")).strip()
        row["statusLabel"] = f"{status}·自动闭锁" if status else "自动闭锁"

    for row in (*renewable_rows, *storage_rows):
        side = str(row.get("connectionSide", ""))
        blocked = (
            side == "AC"
            and str(row.get("gridComponentId", "")) in blocked_ac_components
            or side == "DC"
            and str(row.get("dcTransferGroupId", "")) in blocked_dc_groups
        )
        if blocked:
            block_row(row, "所在构网储能控制范围的数据不完整")

    for row in converter_rows:
        group_id = str(row.get("dcTransferGroupId", ""))
        if group_id in blocked_dc_groups:
            block_row(row, "所在直流传输组的构网储能数据不完整")

    if blocked_ac_components:
        for row in diesel_rows:
            block_row(row, "交流构网储能控制范围的数据不完整")

    return {
        "acComponents": blocked_ac_components,
        "dcTransferGroups": blocked_dc_groups,
    }

def _optimization_component_ids_for_row(
    row: Mapping[str, Any],
    topology: ResourceTopology,
) -> Tuple[str, ...]:
    key = (
        str(row.get("model_block") or row.get("dev_type") or ""),
        str(row.get("dev_name") or ""),
    )
    endpoints = topology.converter_component_ids.get(key)
    if endpoints:
        return tuple(component_id for component_id in endpoints if component_id)
    side = str(row.get("connectionSide", "")).strip().upper()
    if side == "AC":
        component_id = str(row.get("gridComponentId", "")).strip()
    elif side == "DC":
        component_id = str(
            row.get("dcTransferGroupId") or row.get("gridComponentId") or ""
        ).strip()
    else:
        component_id = str(topology.device_component_ids.get(key, "")).strip()
    return (component_id,) if component_id else ()

def _blocked_optimization_component_ids(
    topology: ResourceTopology,
    fail_closed_scopes: Mapping[str, Iterable[str]],
    renewable_rows: Sequence[Mapping[str, Any]],
    storage_rows: Sequence[Mapping[str, Any]],
    diesel_rows: Sequence[Mapping[str, Any]],
    converter_rows: Sequence[Mapping[str, Any]],
    quality: _Quality,
) -> Tuple[str, ...]:
    blocked = {
        str(component_id).strip()
        for scope_name in ("acComponents", "dcTransferGroups")
        for component_id in fail_closed_scopes.get(scope_name, ())
        if str(component_id).strip()
    }
    for row in (*renewable_rows, *storage_rows, *diesel_rows, *converter_rows):
        if not row.get("online"):
            continue
        if (
            _number(row.get("currentKw")) is not None
            and not row.get("automaticControlBlocked")
        ):
            continue
        blocked.update(_optimization_component_ids_for_row(row, topology))
    if quality.blocked:
        blocked.update(
            str(component_id).strip()
            for component_id in topology.device_component_ids.values()
            if str(component_id).strip()
        )
        blocked.update(
            str(component_id).strip()
            for endpoints in topology.converter_component_ids.values()
            for component_id in endpoints
            if str(component_id).strip()
        )
    return tuple(sorted(blocked))
