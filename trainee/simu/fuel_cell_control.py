"""Pure fuel-cell power state machine used by renewable control."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


EPSILON = 1e-9


@dataclass(frozen=True)
class FuelCellControlParameters:
    """Fuel-cell thresholds configured independently from electrolyzer control."""

    power_step_kw: float
    diesel_power_limit_ratio: float
    diesel_power_stop_minimum_ratio: float
    electric_storage_soc_limit: float
    hydrogen_storage_soc_start_limit: float
    hydrogen_storage_soc_stop_limit: float
    electric_storage_soc_deadband: float = 0.0


@dataclass(frozen=True)
class FuelCellControlInputs:
    current_power_kw: float
    maximum_power_kw: float
    minimum_power_kw: float
    start_threshold_kw: float
    stop_threshold_kw: float
    diesel_power_kw: float
    diesel_capacity_kw: float
    electric_storage_soc_average: Optional[float]
    hydrogen_storage_soc_average: Optional[float]
    allow_zero_diesel: bool = False


@dataclass(frozen=True)
class FuelCellControlDecision:
    action: str
    requested_delta_kw: float = 0.0
    required_start_delta_kw: Optional[float] = None
    reason: str = "hold_region"
    diesel_raise_margin_kw: float = 0.0
    diesel_reduce_margin_kw: float = 0.0


def _finite(value: Optional[float]) -> bool:
    return value is not None and math.isfinite(float(value))


def calculate_fuel_cell_power_decision(
    parameters: FuelCellControlParameters,
    inputs: FuelCellControlInputs,
) -> FuelCellControlDecision:
    """Return one-cycle start/increase/decrease/stop decision for a fuel cell.

    Diesel thresholds use aggregate power divided by aggregate rated capacity.
    Electric-storage SOC uses the complete online fleet average, while hydrogen
    SOC uses the complete average of online tanks in the fuel cell's island.
    """

    electric_soc = inputs.electric_storage_soc_average
    hydrogen_soc = inputs.hydrogen_storage_soc_average
    if not _finite(electric_soc) or not _finite(hydrogen_soc):
        return FuelCellControlDecision(
            action="hold",
            reason="incomplete_average_input",
        )

    current_power = max(0.0, float(inputs.current_power_kw))
    maximum_power = max(0.0, float(inputs.maximum_power_kw))
    minimum_power = max(0.0, float(inputs.minimum_power_kw))
    start_threshold = max(minimum_power, float(inputs.start_threshold_kw))
    # 停机门槛不得低于最小允许运行功率，杜绝输出落入低载禁区
    stop_threshold = max(minimum_power, max(0.0, float(inputs.stop_threshold_kw)))
    step_kw = max(0.0, float(parameters.power_step_kw))
    diesel_capacity = max(0.0, float(inputs.diesel_capacity_kw))
    if diesel_capacity <= EPSILON:
        if not inputs.allow_zero_diesel:
            return FuelCellControlDecision(action="hold", reason="invalid_diesel_capacity")
        # 零柴发构网运行模式：按电储 SOC 与氢储 SOC 独立驱动燃料电池启停与步长调功
        diesel_raise_margin_kw = max(maximum_power, start_threshold)
        diesel_reduce_margin_kw = 0.0
    else:
        diesel_power = float(inputs.diesel_power_kw)
        diesel_start_limit = float(parameters.diesel_power_limit_ratio)
        diesel_stop_limit = float(parameters.diesel_power_stop_minimum_ratio)
        diesel_raise_margin_kw = max(
            0.0,
            diesel_power - diesel_start_limit * diesel_capacity,
        )
        diesel_reduce_margin_kw = max(
            0.0,
            diesel_stop_limit * diesel_capacity - diesel_power,
        )

    electric_soc_deadband = max(0.0, float(parameters.electric_storage_soc_deadband))
    electric_soc_low = (
        float(electric_soc)
        < float(parameters.electric_storage_soc_limit) - EPSILON
    )
    # 增补电储 SOC 上行回差死区，防止在限值附近高频启停/抖动
    electric_soc_high = (
        float(electric_soc)
        > float(parameters.electric_storage_soc_limit) + electric_soc_deadband + EPSILON
    )
    hydrogen_soc_above_start = (
        float(hydrogen_soc)
        > float(parameters.hydrogen_storage_soc_start_limit) + EPSILON
    )
    hydrogen_soc_above_stop = (
        float(hydrogen_soc)
        > float(parameters.hydrogen_storage_soc_stop_limit) + EPSILON
    )
    hydrogen_soc_below_stop = (
        float(hydrogen_soc)
        < float(parameters.hydrogen_storage_soc_stop_limit) - EPSILON
    )

    # A small positive telemetry residue below the stop threshold is still an
    # operationally stopped fuel cell.  Treating any value above EPSILON as
    # running traps the controller in a stop loop instead of allowing a start.
    running = bool(
        current_power > EPSILON
        and current_power >= stop_threshold - EPSILON
    )
    if not running:
        start_allowed = bool(
            diesel_raise_margin_kw > EPSILON
            and electric_soc_low
            and hydrogen_soc_above_start
        )
        if not start_allowed:
            return FuelCellControlDecision(
                action="hold",
                reason="start_conditions_not_met",
                diesel_raise_margin_kw=diesel_raise_margin_kw,
                diesel_reduce_margin_kw=diesel_reduce_margin_kw,
            )
        # 启机属于状态切换而非普通爬坡：柴发启机线是准入条件，只需校核起步降载后不跌破停机线，
        # 对齐电制氢启机裕度语义，消除 50%~53% 启机死区。
        required_start = max(0.0, start_threshold - current_power)
        diesel_stop_headroom_kw = (
            max(maximum_power, start_threshold)
            if diesel_capacity <= EPSILON
            else max(0.0, diesel_power - diesel_stop_limit * diesel_capacity)
        )
        if (
            required_start > diesel_stop_headroom_kw + EPSILON
            or start_threshold > maximum_power + EPSILON
        ):
            return FuelCellControlDecision(
                action="hold",
                required_start_delta_kw=required_start,
                reason="start_margin_insufficient",
                diesel_raise_margin_kw=diesel_raise_margin_kw,
                diesel_reduce_margin_kw=diesel_reduce_margin_kw,
            )
        return FuelCellControlDecision(
            action="start",
            requested_delta_kw=required_start,
            required_start_delta_kw=required_start,
            reason="start_conditions_met",
            diesel_raise_margin_kw=diesel_raise_margin_kw,
            diesel_reduce_margin_kw=diesel_reduce_margin_kw,
        )

    raise_allowed = bool(
        diesel_raise_margin_kw > EPSILON
        and electric_soc_low
        and hydrogen_soc_above_stop
    )
    storage_reduce_required = bool(electric_soc_high or hydrogen_soc_below_stop)
    diesel_reduce_required = diesel_reduce_margin_kw > EPSILON

    if raise_allowed:
        delta_kw = min(
            diesel_raise_margin_kw,
            step_kw,
            max(0.0, maximum_power - current_power),
        )
        return FuelCellControlDecision(
            action="increase" if delta_kw > EPSILON else "hold",
            requested_delta_kw=delta_kw,
            reason="raise_conditions_met" if delta_kw > EPSILON else "upper_power_limit",
            diesel_raise_margin_kw=diesel_raise_margin_kw,
            diesel_reduce_margin_kw=diesel_reduce_margin_kw,
        )

    if storage_reduce_required or diesel_reduce_required:
        delta_kw = -min(step_kw, current_power)
        proposed_power = max(0.0, current_power + delta_kw)
        if proposed_power < stop_threshold - EPSILON:
            return FuelCellControlDecision(
                action="stop",
                requested_delta_kw=-current_power,
                reason=(
                    "storage_soc_stop"
                    if storage_reduce_required
                    else "diesel_power_stop"
                ),
                diesel_raise_margin_kw=diesel_raise_margin_kw,
                diesel_reduce_margin_kw=diesel_reduce_margin_kw,
            )
        return FuelCellControlDecision(
            action="decrease",
            requested_delta_kw=delta_kw,
            reason=(
                "storage_soc_reduce"
                if storage_reduce_required
                else "diesel_power_reduce"
            ),
            diesel_raise_margin_kw=diesel_raise_margin_kw,
            diesel_reduce_margin_kw=diesel_reduce_margin_kw,
        )

    return FuelCellControlDecision(
        action="hold",
        reason="hold_region",
        diesel_raise_margin_kw=diesel_raise_margin_kw,
        diesel_reduce_margin_kw=diesel_reduce_margin_kw,
    )
