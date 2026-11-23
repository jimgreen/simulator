"""PolarMicrogridSimulator 拆分模块：量测布局、真实值/SCADA 生成、增量 delta 与历史查询能力。"""

from __future__ import annotations

from .common import *  # noqa: F401,F403
from .common import (
    _MeasurementDefinitionLayout,
    _active_window,
    _align_minute_to_step,
    _cancel_command_origin_filter,
    _clear_directory_contents,
    _command_expires_at,
    _command_origin,
    _command_valid_minutes,
    _compile_interpolation_series,
    _compute_interval_seconds,
    _dev_name,
    _effective_clock_step,
    _ensure_block,
    _explicit_command_origin,
    _find_dev_row,
    _find_set_row,
    _first_number,
    _format_log_detail,
    _format_log_number,
    _format_log_text_numbers,
    _has_cancel_command_payload,
    _has_relative_command_validity,
    _has_stale_absolute_command_expiry,
    _interpolate,
    _interpolate_compiled_series,
    _is_simulator_command_source,
    _is_trainee_command_source,
    _json_scalar,
    _load_book,
    _make_book,
    _manual_command_holds_across_clock_lifecycle,
    _measurement_definition_row_to_dict,
    _measurement_dict_to_row,
    _measurement_median_deviation_map,
    _measurement_row_to_dict,
    _measurement_status_from_valid,
    _model_key,
    _nearest_clock_speed,
    _next_clock_speed,
    _normalize_points,
    _normalize_simulation_mode,
    _normalized_measurement_median_deviation_pairs,
    _now_text,
    _number_text,
    _previous_clock_speed,
    _read_json,
    _reconcile_hydrogen_inline_flow_measurements,
    _remote_adjustment_response_ratio,
    _safe_model_id,
    _sender_command_valid_minutes,
    _simulation_mode_config,
    _simulation_mode_curve_step_minutes,
    _simulation_mode_default_clock_speed,
    _simulation_mode_duration_minutes,
    _simulation_mode_point_count,
    _storage_initial_soc,
    _strategy_generation_matches,
    _strategy_generation_metadata,
    _to_float,
    _value_with_unit,
    _write_json,
)


class _MeasurementsMixin:
    """量测布局、真实值/SCADA 生成、增量 delta 与历史查询能力。"""

    def _read_source_measurement_statuses(self) -> Dict[str, Dict[str, Any]]:
        payload = _read_json(self.source_files["definition_defaults"], {})
        raw_statuses = payload.get("measurement_statuses", {}) if (type(payload) is dict or isinstance(payload, Mapping)) else {}
        if not (type(raw_statuses) is dict or isinstance(raw_statuses, Mapping)):
            return {}
        statuses: Dict[str, Dict[str, Any]] = {}
        for raw_name, raw_value in raw_statuses.items():
            if not (type(raw_value) is dict or isinstance(raw_value, Mapping)):
                continue
            name = str(raw_name).strip()
            status = str(raw_value.get("status", "")).strip().casefold()
            if not name or status not in MEASUREMENT_STATUS_TOKENS:
                continue
            fixed_value = _to_float(raw_value.get("fixed_value"), None)
            statuses[name] = {
                "status": status,
                "fixed_value": fixed_value if status == "fixed" else None,
            }
        return statuses

    def _read_source_measurement_median_deviations(
        self,
        measurement_rows: Sequence[Sequence[Any]],
    ) -> Tuple[Tuple[str, float], ...]:
        payload = _read_json(self.source_files["definition_defaults"], {})
        raw_values = (
            payload.get("measurement_median_deviations", {})
            if (type(payload) is dict or isinstance(payload, Mapping))
            else {}
        )
        if not (type(raw_values) is dict or isinstance(raw_values, Mapping)):
            return ()
        measurement_names = {
            str(row[1]).strip()
            for row in measurement_rows
            if len(row) > 1 and str(row[1]).strip()
        }
        return _normalized_measurement_median_deviation_pairs(
            {
                str(name): value
                for name, value in raw_values.items()
                if str(name).strip() in measurement_names
            }
        )

    def _ensure_weather_measurements_in_file(self, meas_file: Path) -> bool:
        meas_file = Path(meas_file)
        if not meas_file.exists():
            before: List[str] = []
            rows: List[List[str]] = []
            after: List[str] = []
        else:
            try:
                before, rows, after = parse_measurement_rows(meas_file)
            except Exception:
                return False
        kept_rows = [
            row
            for row in rows
            if not self._is_weather_measurement_row(_measurement_row_to_dict(row))
            and not self._is_signal_measurement_row(_measurement_row_to_dict(row))
        ]
        max_idx = -1
        for row in kept_rows:
            max_idx = max(max_idx, int(_to_float(row[0], -1) or -1))
        weather_rows = [
            _measurement_dict_to_row(row)
            for row in self._weather_measurement_rows(max_idx + 1)
        ]
        signal_rows = [
            _measurement_dict_to_row(row)
            for row in self._signal_measurement_rows(max_idx + 1 + len(weather_rows))
        ]
        new_rows = [*kept_rows, *weather_rows, *signal_rows]
        if rows == new_rows:
            return False
        simu_loop.write_measurement_snapshot(meas_file, before, new_rows, after)
        return True

    def ensure_weather_measurements_in_definition_files(self) -> bool:
        return bool(self._ensure_weather_measurements_in_file(self.source_files["meas"]))

    def _sync_latest_storage_soc_measurement_rows(self) -> None:
        soc_values = self._runtime_storage_soc_values()
        if not soc_values:
            return
        resource_by_protocol_key = {
            protocol_key: resource_key
            for resource_key, protocol_keys in self._storage_runtime_protocol_keys().items()
            for protocol_key in protocol_keys
        }

        changed = False

        def sync_rows(rows: List[List[str]]) -> None:
            nonlocal changed
            for row in rows:
                if len(row) < len(MEAS_HEADER):
                    continue
                if str(row[4]).upper() != "SOC":
                    continue
                dev_type = str(row[2]).strip()
                dev_name = str(row[3]).strip()
                key = resource_by_protocol_key.get((dev_type, dev_name), (dev_type, dev_name))
                if key in soc_values:
                    value = _number_text(soc_values[key])
                    if row[7] != value:
                        row[7] = value
                        changed = True

        sync_rows(self.latest_real_rows)
        sync_rows(self.latest_scada_rows)
        if changed:
            self._invalidate_measurement_delta_cache()
        if changed and self.latest_measurements:
            self.latest_measurements = self.measurements()

    def _sync_latest_hydrogen_storage_measurement_rows(self) -> None:
        state_values = simu_loop.hydrogen_storage_state_values_from_book(
            self.runtime_stat_book
        )
        if not state_values:
            return
        definition_rows = self.definition_snapshot.measurement_rows

        field_by_measurement_type = {
            "PRESS": "pressure",
            "PRESSURE": "pressure",
            "FLOW": "flow",
            "GASQUANTITY": "gas_quantity",
            "GAS_QUANTITY": "gas_quantity",
            "SOC": "soc",
        }
        changed = False

        def sync_rows(rows: List[List[str]]) -> None:
            nonlocal changed
            if not rows:
                # 尚未完成首拍潮流计算时，不向空列表注入半残氢储罐行，保持冷启动帧完整一致。
                return
            populated_keys: set[Tuple[str, str]] = set()
            for row in rows:
                if len(row) < len(MEAS_HEADER):
                    continue
                if str(row[2]).strip() != "HydroStorage":
                    continue
                field = field_by_measurement_type.get(str(row[4]).strip().upper())
                if field is None:
                    continue
                dev_name = str(row[3]).strip()
                values = state_values.get(("HydroStorage", dev_name)) or state_values.get(dev_name)
                if not values or field not in values:
                    continue
                populated_keys.add((dev_name, field))
                value = _number_text(values[field])
                if row[7] != value:
                    row[7] = value
                    changed = True

            for definition in definition_rows:
                if len(definition) < len(MEAS_HEADER):
                    continue
                if str(definition[2]).strip() != "HydroStorage":
                    continue
                field = field_by_measurement_type.get(
                    str(definition[4]).strip().upper()
                )
                dev_name = str(definition[3]).strip()
                if field is None or (dev_name, field) in populated_keys:
                    continue
                values = state_values.get(("HydroStorage", dev_name)) or state_values.get(dev_name)
                if not values or field not in values:
                    continue
                row = list(definition)
                row[7] = _number_text(values[field])
                rows.append(row)
                populated_keys.add((dev_name, field))
                changed = True

        sync_rows(self.latest_real_rows)
        sync_rows(self.latest_scada_rows)
        if changed:
            self._invalidate_measurement_delta_cache()
        if changed and self.latest_measurements:
            self.latest_measurements = self.measurements()

    def _remote_adjustment_measurement_types(self, key: Tuple[str, str, str]) -> Tuple[str, ...]:
        dev_type, dev_name, set_type = key
        target_row = self._model_control_row(dev_type, dev_name)
        resolved_type = set_type
        if target_row is not None:
            resolved_type = simu_loop._set_value_target_column(dev_type, set_type, dict(target_row))

        direct_types = {
            "p_ac_set": ("P_AC",),
            "p_dc_set": ("P_DC",),
            "q_ac_set": ("Q_AC",),
            "q_dc_set": ("Q_DC",),
            "v_ac_set": ("V_AC",),
            "v_dc_set": ("V_DC",),
            "p_from_set": ("P_FROM",),
            "q_from_set": ("Q_FROM",),
            "v_from_set": ("V_FROM",),
            "p_to_set": ("P_TO",),
            "q_to_set": ("Q_TO",),
            "v_to_set": ("V_TO",),
        }
        if resolved_type in direct_types:
            return direct_types[resolved_type]
        if resolved_type in {"pv0", "p_set"}:
            if dev_type in {"ACGenerator", "DCGenerator"}:
                return ("P_GEN", "P")
            if dev_type in {"ACLoad", "DCLoad"}:
                return ("P_LOAD", "P")
            if dev_type == "ESS":
                return ("P", "P_GEN")
            if dev_type in {"DCDCConverter", "ACACConverter"}:
                return ("P_FROM", "P_TO", "P")
            return ("P", "P_GEN", "P_LOAD")
        if resolved_type in {"qv0", "q_set"}:
            if dev_type == "ACGenerator":
                return ("Q_GEN", "Q")
            if dev_type == "ACLoad":
                return ("Q_LOAD", "Q")
            if dev_type == "ESS":
                return ("Q", "Q_GEN")
            return ("Q", "Q_GEN", "Q_LOAD")
        if resolved_type == "v_set":
            if dev_type in {"ACGenerator", "DCGenerator"}:
                return ("V_GEN", "V")
            if dev_type in {"ACLoad", "DCLoad"}:
                return ("V_LOAD", "V")
            if dev_type in {"DCDCConverter", "ACACConverter"}:
                return ("V_TO", "V_FROM", "V")
            return ("V", "V_GEN", "V_LOAD")
        if resolved_type == "i_set":
            if dev_type in {"ACGenerator", "DCGenerator"}:
                return ("I_GEN", "I")
            if dev_type in {"ACLoad", "DCLoad"}:
                return ("I_LOAD", "I")
            return ("I", "I_FROM", "I_TO")
        return (resolved_type.removesuffix("_set").upper(),)

    def _store_kernel_measurement_rows(self, result: Optional[simu_loop.SimulationResult]) -> None:
        if result is None:
            return
        real_rows = getattr(result, "real_rows", None)
        scada_rows = getattr(result, "scada_rows", None)
        changed = False
        if real_rows is not None:
            self.latest_real_rows = [list(row) for row in real_rows]
            changed = True
        if scada_rows is not None:
            self.latest_scada_rows = [list(row) for row in scada_rows]
            self._base_scada_rows = [list(row) for row in scada_rows]
            changed = True
        if changed:
            self._invalidate_measurement_delta_cache()

    def _reapply_measurement_overlays_locked(self) -> None:
        """基于本拍原始加噪 SCADA 重新叠加量测故障与状态覆盖，支持暂停态即时生效与无损回退。"""
        base_rows = getattr(self, "_base_scada_rows", None)
        if not base_rows:
            return
        self.latest_scada_rows = [list(row) for row in base_rows]
        minute = float(self.clock.minute)
        absolute_minute = float(self.clock.absolute_minute)
        self._apply_measurement_faults(minute, absolute_minute)
        self._apply_measurement_statuses(minute, absolute_minute)
        self.latest_measurements = self._measurements_locked()
        self._latest_power_summary_cache_key = None
        self._latest_power_summary_cache_value = None

    def _apply_measurement_faults(self, minute: int | float, absolute_minute: int | float) -> None:
        faults = [fault for fault in self.local_settings.get("measurement_faults", []) if (type(fault) is dict or isinstance(fault, Mapping))]
        curve_mode = str(self.curves.get("mode", "day") or "day").lower()
        active_faults = [fault for fault in faults if _active_window(fault, minute, absolute_minute, curve_mode)]
        frozen_map = getattr(self, "_dead_fault_frozen_values", None)
        if not isinstance(frozen_map, dict):
            frozen_map = {}
            self._dead_fault_frozen_values = frozen_map
        if not active_faults or not self.latest_scada_rows:
            frozen_map.clear()
            return
        rows = [list(row) for row in self.latest_scada_rows]
        changed = False
        active_dead_keys: set[str] = set()
        for row in rows:
            row_key = self._measurement_key(row)
            for fault in active_faults:
                if not self._measurement_matches(row, fault):
                    continue
                fault_type = str(fault.get("fault_type", fault.get("type", "bias"))).lower()
                if fault_type in ("normal", "ok", "healthy", "none"):
                    continue
                current_value = _to_float(row[7], 0.0) or 0.0
                if fault_type in ("zero", "0", "zero_value"):
                    row[7] = "0"
                elif fault_type in ("dead", "deadband", "stuck", "stale"):
                    median = _to_float(
                        fault.get("median", fault.get("middle", fault.get("fixed_value", fault.get("value")))),
                        None,
                    )
                    bias = _to_float(fault.get("bias", fault.get("error", 0.0)), 0.0) or 0.0
                    if median is not None:
                        base_value = median
                    else:
                        # 首次进入卡滞故障时冻结未加偏的基值，避免每拍叠加 bias 造成无限线性漂移。
                        active_dead_keys.add(row_key)
                        if row_key not in frozen_map:
                            frozen_map[row_key] = float(self._last_scada_values.get(row_key, current_value))
                        base_value = frozen_map[row_key]
                    row[7] = _number_text(base_value + bias)
                else:
                    bias = _to_float(fault.get("bias", fault.get("error", fault.get("offset", 10.0))), 10.0) or 0.0
                    row[7] = _number_text(current_value + bias)
                changed = True
        for stale_key in list(frozen_map):
            if stale_key not in active_dead_keys:
                frozen_map.pop(stale_key, None)
        if changed:
            self.latest_scada_rows = rows
            self._invalidate_measurement_delta_cache()

    def _measurement_status_override(self, row: Mapping[str, Any] | Sequence[Any]) -> Tuple[str, Optional[float]]:
        if type(row) is dict or isinstance(row, Mapping):
            name = str(row.get("name", "")).strip()
            default_valid = row.get("valid", 1)
        else:
            name = str(row[1] if len(row) > 1 else "").strip()
            default_valid = row[6] if len(row) > 6 else 1
        statuses = self.local_settings.get("measurement_statuses")
        configured = statuses.get(name) if (type(statuses) is dict or isinstance(statuses, Mapping)) else None
        if not (type(configured) is dict or isinstance(configured, Mapping)):
            configured = self._source_measurement_statuses.get(name)
        if not (type(configured) is dict or isinstance(configured, Mapping)):
            status = _measurement_status_from_valid(default_valid)
            return status, None
        status = str(configured.get("status", "")).strip().casefold()
        if status not in MEASUREMENT_STATUS_TOKENS:
            status = _measurement_status_from_valid(default_valid)
        fixed_value = _to_float(configured.get("fixed_value"), None)
        return status, fixed_value

    def effective_measurement_status_defaults(self) -> Dict[str, Dict[str, Any]]:
        """Return non-default measurement states for a materialized definition export."""
        with self.definition_update_lock:
            statuses: Dict[str, Dict[str, Any]] = {}
            for row in self.definition_snapshot.measurement_rows:
                name = str(row[1] if len(row) > 1 else "").strip()
                if not name:
                    continue
                status, fixed_value = self._measurement_status_override(row)
                default_status = _measurement_status_from_valid(row[6] if len(row) > 6 else 1)
                if status == default_status and fixed_value is None:
                    continue
                statuses[name] = {
                    "status": status,
                    "fixed_value": fixed_value if status == "fixed" else None,
                }
            return statuses

    def effective_measurement_median_deviation_defaults(self) -> Dict[str, float]:
        """Return nonzero Gaussian error means for a materialized definition export."""
        with self.definition_update_lock:
            return _measurement_median_deviation_map(self.definition_snapshot)

    def _apply_measurement_statuses(self, minute: int | float, absolute_minute: int | float) -> None:
        del minute, absolute_minute
        statuses = self.local_settings.get("measurement_statuses", {})
        has_local_statuses = (type(statuses) is dict or isinstance(statuses, Mapping)) and bool(statuses)
        if not (has_local_statuses or self._source_measurement_statuses) or not self.latest_scada_rows:
            return
        rows = [list(row) for row in self.latest_scada_rows]
        changed = False
        for row in rows:
            status, fixed_value = self._measurement_status_override(row)
            if status == "zero":
                row[7] = "0"
                changed = True
            elif status == "fixed" and fixed_value is not None:
                row[7] = _number_text(fixed_value)
                changed = True
            elif status == "dead":
                key = self._measurement_key(row)
                current_value = _to_float(row[7], 0.0) or 0.0
                row[7] = _number_text(self._last_scada_values.get(key, current_value))
                changed = True
        if changed:
            self.latest_scada_rows = rows
            self._invalidate_measurement_delta_cache()

    def _measurement_matches(self, row: Sequence[str], fault: Mapping[str, Any]) -> bool:
        name, dev_type, dev_name, meas_type = row[1], row[2], row[3], row[4]
        target = str(fault.get("target", fault.get("name", "")))
        if target and target not in {
            name,
            dev_name,
            f"{dev_type}.{dev_name}.{meas_type}",
            f"{dev_type}:{dev_name}:{meas_type}",
            f"{dev_name}.{meas_type}",
        }:
            return False
        if fault.get("dev_type") not in (None, "", dev_type):
            return False
        if fault.get("dev_name") not in (None, "", dev_name):
            return False
        if str(fault.get("meas_type", "")).upper() not in ("", meas_type.upper()):
            return False
        return True

    def _measurement_key(self, row: Sequence[str]) -> str:
        return f"{row[1]}|{row[2]}|{row[3]}|{row[4]}"

    def _is_weather_measurement_row(self, row: Mapping[str, Any]) -> bool:
        return (
            str(row.get("dev_type", "")) == "Environment"
            and str(row.get("dev_name", "")) == "weather"
            and str(row.get("meas_type", "")).upper() in WEATHER_MEASUREMENT_TYPE_SET
        )

    def _weather_measurement_rows(self, start_idx: int) -> List[Dict[str, Any]]:
        weather = self._current_weather_values()
        rows: List[Dict[str, Any]] = []
        for offset, (weather_key, _name_suffix, meas_type) in enumerate(WEATHER_MEASUREMENTS):
            value = _to_float(weather.get(weather_key), None)
            rows.append(
                {
                    "idx": start_idx + offset,
                    "name": automatic_point_name("Environment", "weather", meas_type),
                    "dev_type": "Environment",
                    "dev_name": "weather",
                    "meas_type": meas_type,
                    "weight": 1.0,
                    "valid": 1 if value is not None else 0,
                    "value": value if value is not None else 0.0,
                }
            )
        return rows

    def _is_signal_measurement_row(self, row: Mapping[str, Any]) -> bool:
        meas_type = row.get("meas_type", "")
        if meas_type not in ("RUN_STAT", "STATUS"):
            if not meas_type or str(meas_type).upper() not in SIGNAL_MEASUREMENT_TYPES:
                return False
        dev_type = row.get("dev_type", "")
        if not dev_type or not str(dev_type).strip():
            return False
        dev_name = row.get("dev_name", "")
        return bool(dev_name and str(dev_name).strip())

    def _signal_measurement_key(self, row: Mapping[str, Any]) -> Tuple[str, str, str]:
        return (
            str(row.get("dev_type", "")),
            str(row.get("dev_name", "")),
            str(row.get("meas_type", "")).upper(),
        )

    def _signal_measurement_rows(self, start_idx: int) -> List[Dict[str, Any]]:
        values = self._current_signal_values()
        rows: List[Dict[str, Any]] = []
        seen: set[Tuple[str, str, str]] = set()
        for book in (self.control_book, self.source_stat_book):
            for block_name, value_column, meas_type, name_suffix in SIGNAL_MEASUREMENTS:
                block = book.data.get(block_name)
                if block is None:
                    continue
                for item in getattr(block, "data", []):
                    dev_type = str(item.get("dev_type", ""))
                    dev_name = _dev_name(item)
                    if not dev_type or not dev_name:
                        continue
                    key = (dev_type, dev_name, meas_type)
                    if key in seen:
                        continue
                    seen.add(key)
                    value = values.get(key)
                    if value is None:
                        value = _to_float(item.get(value_column), 0.0) or 0.0
                    rows.append(
                        {
                            "idx": start_idx + len(rows),
                            "name": automatic_point_name(dev_type, dev_name, name_suffix),
                            "dev_type": dev_type,
                            "dev_name": dev_name,
                            "meas_type": meas_type,
                            "weight": 1.0,
                            "valid": 1,
                            "value": value,
                        }
                    )
        return rows

    def _apply_signal_measurement_value(
        self,
        row: Dict[str, Any],
        values: Mapping[Tuple[str, str, str], float],
    ) -> None:
        row["meas_type"] = str(row.get("meas_type", "")).upper()
        value = values.get(self._signal_measurement_key(row))
        if value is None:
            value = _to_float(row.get("value"), 0.0) or 0.0
        row["value"] = value
        row["valid"] = 1
        row.setdefault("weight", 1.0)

    def _with_weather_measurements(
        self,
        measurements: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        in_place: bool = False,
    ) -> Dict[str, List[Dict[str, Any]]]:
        weather = self._current_weather_values()
        weather_values = {
            meas_type: _to_float(weather.get(weather_key), None)
            for weather_key, _name_suffix, meas_type in WEATHER_MEASUREMENTS
        }
        if in_place:
            normalized = {
                channel: (
                    measurements[channel]
                    if isinstance(measurements.get(channel), list)
                    else list(measurements.get(channel, []))
                )
                for channel in ("definitions", "real", "scada")
            }
        else:
            normalized = {
                channel: [dict(row) for row in measurements.get(channel, [])]
                for channel in ("definitions", "real", "scada")
            }

        max_idx = -1
        for channel, rows in normalized.items():
            for row in rows:
                idx = int(_to_float(row.get("idx"), -1) or -1)
                max_idx = max(max_idx, idx)
                if channel != "definitions" or not self._is_weather_measurement_row(row):
                    # real/scada 通道中已由本拍仿真内核生成的气象行保留其真实/加噪/故障/状态值，
                    # 严禁被无噪声当前气象值覆盖抹除。
                    continue
                meas_type = str(row.get("meas_type", "")).upper()
                value = weather_values.get(meas_type)
                if value is not None:
                    row["value"] = value
                    row["valid"] = 1
                else:
                    row["value"] = _to_float(row.get("value"), 0.0) or 0.0
                    row["valid"] = 0
                row.setdefault("weight", 1.0)

        definition_weather_rows = [
            row for row in normalized["definitions"] if self._is_weather_measurement_row(row)
        ]
        if not definition_weather_rows:
            missing_start_idx = max_idx + 1
            definition_weather_rows = self._weather_measurement_rows(missing_start_idx)
            normalized["definitions"].extend(dict(row) for row in definition_weather_rows)

        for channel in ("real", "scada"):
            rows = normalized[channel]
            present_types = {
                str(row.get("meas_type", "")).upper()
                for row in rows
                if self._is_weather_measurement_row(row)
            }
            for definition_row in definition_weather_rows:
                meas_type = str(definition_row.get("meas_type", "")).upper()
                if meas_type not in present_types:
                    rows.append(dict(definition_row))
        return normalized

    def _with_signal_measurements(
        self,
        measurements: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        in_place: bool = False,
    ) -> Dict[str, List[Dict[str, Any]]]:
        values = self._current_signal_values()
        if in_place:
            normalized = {
                channel: (
                    measurements[channel]
                    if isinstance(measurements.get(channel), list)
                    else list(measurements.get(channel, []))
                )
                for channel in ("definitions", "real", "scada")
            }
        else:
            normalized = {
                channel: [dict(row) for row in measurements.get(channel, [])]
                for channel in ("definitions", "real", "scada")
            }

        max_idx = -1
        for channel, rows in normalized.items():
            for row in rows:
                idx = int(_to_float(row.get("idx"), -1) or -1)
                max_idx = max(max_idx, idx)
                if channel == "definitions" and self._is_signal_measurement_row(row):
                    self._apply_signal_measurement_value(row, values)

        definition_by_key = {
            self._signal_measurement_key(row): row
            for row in normalized["definitions"]
            if self._is_signal_measurement_row(row)
        }
        for expected in self._signal_measurement_rows(max_idx + 1):
            key = self._signal_measurement_key(expected)
            if key in definition_by_key:
                self._apply_signal_measurement_value(definition_by_key[key], values)
                continue
            row = dict(expected)
            self._apply_signal_measurement_value(row, values)
            normalized["definitions"].append(row)
            definition_by_key[key] = row

        valid_signal_keys = set(definition_by_key)
        definition_signal_rows = [
            row
            for row in normalized["definitions"]
            if self._is_signal_measurement_row(row)
            and self._signal_measurement_key(row) in valid_signal_keys
        ]
        for channel in ("real", "scada"):
            rows = [
                row
                for row in normalized[channel]
                if not self._is_signal_measurement_row(row)
                or self._signal_measurement_key(row) in valid_signal_keys
            ]
            by_key = {
                self._signal_measurement_key(row): row
                for row in rows
                if self._is_signal_measurement_row(row)
            }
            for definition_row in definition_signal_rows:
                key = self._signal_measurement_key(definition_row)
                target = by_key.get(key)
                if target is None:
                    # 仅补充该通道缺失的遥信行；已由本拍潮流产出的遥信行保持与同帧功率同步，
                    # 同时保留 SCADA 通道上的遥信故障/固定状态覆盖，避免未步进前产生撕裂帧。
                    target = dict(definition_row)
                    rows.append(target)
                    by_key[key] = target
                    self._apply_signal_measurement_value(target, values)
            normalized[channel] = rows
        return normalized

    def _with_realtime_measurements(
        self,
        measurements: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        in_place: bool = False,
    ) -> Dict[str, List[Dict[str, Any]]]:
        return self._with_signal_measurements(
            self._with_weather_measurements(measurements, in_place=in_place),
            in_place=True,
        )

    def _compiled_measurement_definitions(
        self,
    ) -> _MeasurementDefinitionLayout:
        """Compile immutable definition metadata once for each published revision."""

        definition_snapshot = self.definition_snapshot
        cached = self._measurement_definition_layout
        if cached is not None and cached.snapshot is definition_snapshot:
            return cached

        median_deviations = _measurement_median_deviation_map(definition_snapshot)
        definitions = tuple(
            _measurement_definition_row_to_dict(row, median_deviations)
            for row in definition_snapshot.measurement_rows
        )
        signature = measurement_definition_signature(definitions)
        first_index = measurement_row_index(definitions[0]) if definitions else 0
        contiguous = first_index >= 0 and all(
            measurement_row_index(definition) == first_index + position
            for position, definition in enumerate(definitions)
        )
        positions = (
            {}
            if contiguous
            else {
                measurement_row_index(definition): position
                for position, definition in enumerate(definitions)
                if measurement_row_index(definition) >= 0
            }
        )
        compiled = _MeasurementDefinitionLayout(
            snapshot=definition_snapshot,
            rows=definitions,
            signature=signature,
            first_index=first_index,
            contiguous=contiguous,
            positions=positions,
        )
        # Publish the complete layout with one reference assignment. Concurrent
        # readers can use either complete revision and will retry on snapshot mismatch.
        self._measurement_definition_layout = compiled
        return compiled

    def _measurement_definition_signature_for_current_revision(self) -> str:
        return self._compiled_measurement_definitions().signature

    def _align_rows_with_compiled_measurement_definitions(
        self,
        rows: Sequence[Mapping[str, Any]],
    ) -> List[Optional[Mapping[str, Any]]]:
        layout = self._compiled_measurement_definitions()
        definitions = layout.rows
        aligned: List[Optional[Mapping[str, Any]]] = [None] * len(definitions)
        row_list = list(rows)
        positional_fallback = len(row_list) == len(definitions)
        first_index = layout.first_index
        for row_position, row in enumerate(row_list):
            if not (type(row) is dict or isinstance(row, Mapping)):
                continue
            index = measurement_row_index(row)
            if layout.contiguous:
                position = (
                    index - first_index
                    if first_index <= index < first_index + len(aligned)
                    else None
                )
            else:
                position = layout.positions.get(index)
            if position is None and positional_fallback:
                position = row_position
            if position is not None and 0 <= position < len(aligned):
                aligned[position] = row
        return aligned

    def measurement_definitions(self) -> List[Dict[str, Any]]:
        """Return the wire-visible measurement definition order without live values."""

        layout = self._compiled_measurement_definitions()
        return [dict(row) for row in layout.rows]

    def _record_last_scada_values_locked(
        self,
        measurements: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> None:
        """在持锁步进提交阶段更新最近一次 SCADA 量测缓存，避免只读查询并发写字典。"""
        for item in measurements.get("scada", ()):
            self._last_scada_values[
                f"{item['name']}|{item['dev_type']}|{item['dev_name']}|{item['meas_type']}"
            ] = item.get("value", 0.0) or 0.0

    def measurements(self) -> Dict[str, List[Dict[str, Any]]]:
        with self.lock:
            return self._measurements_locked()

    def _measurements_locked(self) -> Dict[str, List[Dict[str, Any]]]:
        definitions = self.measurement_definitions()
        real = [_measurement_row_to_dict(row) for row in self.latest_real_rows]
        scada = [_measurement_row_to_dict(row) for row in self.latest_scada_rows]
        for rows in (real, scada):
            aligned_rows = self._align_rows_with_compiled_measurement_definitions(rows)
            for definition, row in zip(definitions, aligned_rows):
                if row is None:
                    continue
                row["weight"] = definition.get("weight", row.get("weight"))
                row_valid = int(_to_float(row.get("valid"), 1) or 0)
                if self._is_weather_measurement_row(definition):
                    # 气象测点在 meas.e 静态定义中初始 valid 可能为 0，实时有效性由本拍气象求解与人工状态覆盖决定。
                    row["valid"] = row_valid
                else:
                    def_valid = int(_to_float(definition.get("valid"), 1) or 0)
                    # 保留本拍潮流计算缺失或故障置零的 valid=0，仅在定义禁用时同步降为 0。
                    row["valid"] = 0 if (def_valid == 0 or row_valid == 0) else 1
        measurements = self._with_realtime_measurements(
            {"definitions": definitions, "real": real, "scada": scada},
            in_place=True,
        )
        if self._automatic_runtime_state_invalidated:
            # Before the first successful calculation of a lifecycle, weather
            # and signal projections are definitions only, not valid automatic
            # real/scada samples from a previous run.
            measurements["real"] = []
            measurements["scada"] = []
        statuses = self.local_settings.get("measurement_statuses")
        has_overrides = bool(
            (statuses and (type(statuses) is dict or isinstance(statuses, Mapping)))
            or self._source_measurement_statuses
        )
        if has_overrides:
            for channel_name, channel_rows in measurements.items():
                for row in channel_rows:
                    row_valid = int(_to_float(row.get("valid"), 1) or 0)
                    status, fixed_value = self._measurement_status_override(row)
                    if channel_name != "definitions" and status in {"valid", "normal"} and row_valid == 0:
                        # 保护本拍潮流计算缺失或无效气象产生的 valid=0，不被默认/显式 "valid" 状态覆盖洗白。
                        row["status"] = "invalid"
                        row["fixed_value"] = None
                        row["valid"] = 0
                    else:
                        row["status"] = status
                        row["fixed_value"] = fixed_value
                        row["valid"] = MEASUREMENT_STATUS_VALIDITY.get(status, row_valid)
        else:
            # 快路径：无自定义状态覆盖时直接按 valid 字段映射，状态词法与慢路径保持严格一致（"valid"/"invalid"）。
            for channel_rows in measurements.values():
                for row in channel_rows:
                    raw_valid = row.get("valid", 1)
                    if raw_valid == 1 or raw_valid == "1":
                        row["status"] = "valid"
                        row["fixed_value"] = None
                        row["valid"] = 1
                    elif raw_valid == 0 or raw_valid == "0":
                        row["status"] = "invalid"
                        row["fixed_value"] = None
                        row["valid"] = 0
                    else:
                        status = _measurement_status_from_valid(raw_valid)
                        row["status"] = status
                        row["fixed_value"] = None
                        row["valid"] = MEASUREMENT_STATUS_VALIDITY.get(status, int(_to_float(raw_valid, 0) or 0))
        return measurements

    def _measurement_delta_current_items(
        self,
        measurements: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
        measurement_clock: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        measurements = dict(measurements or self.measurements())
        definitions = measurements.get("definitions") or measurements.get("scada") or measurements.get("real") or []
        real_rows = measurement_rows_by_definition_index(definitions, measurements.get("real", []) or [])
        scada_rows = measurement_rows_by_definition_index(definitions, measurements.get("scada", []) or [])
        time_payload = self._api_time_payload(measurement_clock)
        items: Dict[str, Dict[str, Any]] = {}
        for index, definition in enumerate(definitions):
            key = str(index)
            name = str(definition.get("name", "")).strip()
            real = real_rows[index]
            scada = scada_rows[index]
            real_value = real.get("value") if real else None
            scada_value = scada.get("value") if scada else None
            value = scada_value if scada is not None else real_value
            sample_row = scada if scada is not None else real
            valid = (
                sample_row.get("valid", definition.get("valid", 0))
                if sample_row is not None
                else definition.get("valid", 0)
            )
            status = (
                sample_row.get("status", definition.get("status", _measurement_status_from_valid(valid)))
                if sample_row is not None
                else definition.get("status", _measurement_status_from_valid(valid))
            )
            items[key] = {
                "name": name,
                "value": _json_scalar(value),
                "real_value": _json_scalar(real_value),
                "scada_value": _json_scalar(scada_value),
                "valid": int(_to_float(valid, 0) or 0),
                "weight": _json_scalar(definition.get("weight", "")),
                "status": str(status),
                "fixed_value": _json_scalar(definition.get("fixed_value")),
                **self._external_update_time_fields(time_payload),
            }
        return items

    def _measurement_delta_signature(self, item: Mapping[str, Any]) -> Tuple[Any, ...]:
        return (
            item.get("value"),
            item.get("real_value"),
            item.get("scada_value"),
            item.get("valid"),
            item.get("weight"),
            item.get("status"),
            item.get("fixed_value"),
        )

    def _measurement_delta_runtime_state_marker(self) -> Tuple[Any, ...]:
        def values(rows: Sequence[Sequence[Any]]) -> Tuple[Any, ...]:
            return tuple(row[7] if len(row) > 7 else None for row in rows)

        return (
            id(self.latest_measurements),
            id(self.latest_result),
            id(self.latest_device_states),
            id(self.latest_real_rows),
            id(self.latest_scada_rows),
            values(self.latest_real_rows),
            values(self.latest_scada_rows),
        )

    def _invalidate_measurement_delta_cache(self) -> None:
        self._measurement_delta_step_count = None
        self._measurement_delta_runtime_marker = None

    def _refresh_measurement_delta_state(
        self,
        measurements: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
        measurement_clock: Optional[Mapping[str, Any]] = None,
        definition_signature: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        measurement_payload = dict(measurements or self.measurements())
        sample_clock = dict(measurement_clock or self.latest_measurement_clock or self.clock.as_dict())
        definitions = [
            row
            for row in measurement_payload.get("definitions", []) or []
            if (type(row) is dict or isinstance(row, Mapping))
        ]
        current_definition_signature = (
            str(definition_signature)
            if definition_signature
            else measurement_definition_signature(definitions)
        )
        definition_changed = (
            current_definition_signature
            != self._measurement_delta_definition_signature
        )
        current = self._measurement_delta_current_items(
            measurement_payload,
            measurement_clock=sample_clock,
        )
        previous = self._measurement_delta_state
        changed_keys: List[str] = []
        removed_keys = [key for key in previous if key not in current]
        for key, item in current.items():
            previous_item = previous.get(key)
            if (
                definition_changed
                or previous_item is None
                or self._measurement_delta_signature(previous_item)
                != self._measurement_delta_signature(item)
            ):
                changed_keys.append(key)
        if definition_changed or changed_keys or removed_keys:
            self._measurement_delta_seq += 1
            changed_items = [current[key] for key in changed_keys]
            changed_items.extend(
                {
                    "name": str(previous.get(key, {}).get("name", key)),
                    "deleted": True,
                    **self._external_update_time_fields(self._api_time_payload(sample_clock)),
                }
                for key in removed_keys
            )
            self._measurement_delta_history.append(
                {
                    "seq": self._measurement_delta_seq,
                    "items": changed_items,
                    "keys": [*changed_keys, *removed_keys],
                }
            )
            self._measurement_delta_history = self._measurement_delta_history[-200:]
            self._measurement_delta_state = current
        self._measurement_delta_definition_signature = current_definition_signature
        self._measurement_delta_definition_count = len(definitions)
        self._measurement_delta_definition_revision = self.definition_snapshot.revision
        self._measurement_delta_step_count = self.clock.step_count
        self._measurement_delta_runtime_marker = self._measurement_delta_runtime_state_marker()
        return current

    def measurement_runtime_definitions(
        self,
        definitions: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Attach local runtime-device identities without changing wire point identity."""

        with self.lock:
            definition_snapshot = self.definition_snapshot
            rows = [
                dict(row)
                for row in (
                    definitions
                    if definitions is not None
                    else self.measurements().get("definitions", [])
                )
                if (type(row) is dict or isinstance(row, Mapping))
            ]
            if self._measurement_bindings_cache_revision != definition_snapshot.revision:
                self._measurement_bindings_cache = simu_loop.compile_measurement_bindings(
                    definition_snapshot.measurement_rows,
                    definition_snapshot.model_book,
                )
                self._measurement_bindings_cache_revision = definition_snapshot.revision
            bindings = self._measurement_bindings_cache
            if len(bindings) != len(rows):
                return rows
            storage_resource_by_protocol_key = {
                protocol_key: resource_key
                for resource_key, protocol_keys in self._storage_runtime_protocol_keys().items()
                for protocol_key in protocol_keys
            }
            for row, binding in zip(rows, bindings):
                runtime_key = (binding.target_type, binding.target_name)
                if str(row.get("meas_type", "")).strip().upper() == "SOC":
                    runtime_key = storage_resource_by_protocol_key.get(
                        (
                            str(row.get("dev_type", "")).strip(),
                            str(row.get("dev_name", "")).strip(),
                        ),
                        runtime_key,
                    )
                row["runtime_dev_type"], row["runtime_dev_name"] = runtime_key
            return rows

    def measurement_delta(self, after_seq: int | float = 0, *, compact: bool = False) -> Dict[str, Any]:
        """Return changed measurement values keyed by measurement name."""
        try:
            after = int(after_seq)
        except (TypeError, ValueError):
            after = 0
        with self.lock:
            cache_valid = (
                self._measurement_delta_step_count == self.clock.step_count
                and self._measurement_delta_definition_revision == self.definition_snapshot.revision
                and self._measurement_delta_runtime_marker is not None
            )
            if cache_valid and (
                self._measurement_delta_runtime_marker
                == self._measurement_delta_runtime_state_marker()
            ):
                current = self._measurement_delta_state
            else:
                current = self._refresh_measurement_delta_state(
                    definition_signature=(
                        self._measurement_definition_signature_for_current_revision()
                    )
                )
            reset = False
            frame = after != self._measurement_delta_seq
            if compact and frame:
                items = list(current.values())
                reset = after <= 0 or after > self._measurement_delta_seq
            elif after <= 0:
                items = list(current.values())
                reset = True
            elif after > self._measurement_delta_seq:
                items = list(current.values())
                reset = True
            elif after == self._measurement_delta_seq:
                items = []
            else:
                oldest_seq = (
                    int(self._measurement_delta_history[0].get("seq", 0))
                    if self._measurement_delta_history
                    else 0
                )
                history = (
                    []
                    if (not self._measurement_delta_history or after < oldest_seq - 1)
                    else [
                        entry
                        for entry in self._measurement_delta_history
                        if int(entry.get("seq", 0)) > after
                    ]
                )
                if not history:
                    items = list(current.values())
                    reset = True
                else:
                    by_key: Dict[str, Dict[str, Any]] = {}
                    for entry in history:
                        entry_items = entry.get("items", [])
                        entry_keys = entry.get("keys", [])
                        if not isinstance(entry_keys, Sequence) or isinstance(entry_keys, (str, bytes)):
                            entry_keys = []
                        for position, item in enumerate(entry_items):
                            if (type(item) is dict or isinstance(item, Mapping)):
                                key = (
                                    str(entry_keys[position])
                                    if position < len(entry_keys)
                                    else str(item.get("name", ""))
                                )
                                by_key[key] = dict(item)
                    items = list(by_key.values())
            payload = {
                "model_id": self.model_id,
                "model_name": self.model_name,
                **self._api_time_payload(self.latest_measurement_clock or self.clock.as_dict()),
                "measurement_clock": dict(self.latest_measurement_clock or self.clock.as_dict()),
                "seq": self._measurement_delta_seq,
                "items": items,
                "reset": reset,
            }
            if compact:
                payload.update(
                    {
                        "frame": frame,
                        "count": self._measurement_delta_definition_count,
                        "definition_revision": self._measurement_delta_definition_revision,
                        "definition_signature": self._measurement_delta_definition_signature,
                    }
                )
        return compact_measurement_delta(payload) if compact else payload

    def measurement_history(
        self,
        *,
        indices: Optional[Sequence[int]] = None,
        after_seq: int | float = 0,
    ) -> Dict[str, Any]:
        """Return compact current-run history aligned to measurement order."""

        with self.lock:
            measurements = self.latest_measurements
            if not (type(measurements) is dict or isinstance(measurements, Mapping)) or not measurements.get("definitions"):
                measurements = self.measurements()
            definitions = [
                row
                for row in measurements.get("definitions", []) or []
                if (type(row) is dict or isinstance(row, Mapping))
            ]
            self._measurement_history.ensure_definition(
                definitions,
                definition_revision=self.definition_snapshot.revision,
            )
            return self._measurement_history.payload(
                indices=indices,
                after_seq=after_seq,
                model_id=self.model_id,
                model_name=self.model_name,
            )

    def _read_measurement_file(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        try:
            _before, rows, _after = parse_measurement_rows(path)
        except Exception:
            return []
        return [_measurement_row_to_dict(row) for row in rows]

    def external_measurement_history(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Return sampled YC/YX history matrices for external clients."""

        interval_seconds = self._external_history_interval_seconds(payload)
        start_minute = self._external_history_absolute_minute(payload, "start")
        end_minute = self._external_history_absolute_minute(payload, "end")
        if end_minute < start_minute - 1e-9:
            raise ValueError("end_time must not be earlier than start_time")

        telemetry_names = self._name_list_from_payload(
            payload,
            ("telemetry", "telemetries", "telemetry_names", "yc", "yc_names", "remote_measurements"),
        )
        signal_names = self._name_list_from_payload(
            payload,
            ("signals", "signal_names", "yx", "yx_names", "statuses", "status_names", "remote_signals"),
        )
        if not telemetry_names and not signal_names:
            raise ValueError("telemetry_names or signal_names is required")
        if len(telemetry_names) + len(signal_names) > 256:
            raise ValueError("at most 256 telemetry and signal names may be queried at once")

        with self.lock:
            measurements = self.latest_measurements
            if not (type(measurements) is dict or isinstance(measurements, Mapping)) or not measurements.get("definitions"):
                measurements = self.measurements()
            definitions = [
                row
                for row in measurements.get("definitions", []) or []
                if (type(row) is dict or isinstance(row, Mapping))
            ]
            definition_by_name: Dict[str, Tuple[int, Mapping[str, Any]]] = {}
            for index, row in enumerate(definitions):
                name = str(row.get("name", "")).strip()
                if name and name not in definition_by_name:
                    definition_by_name[name] = (index, row)

            def resolve_names(names: Sequence[str], expect_signal: bool) -> Tuple[List[bool], List[Optional[int]]]:
                found: List[bool] = []
                indices: List[Optional[int]] = []
                for name in names:
                    match = definition_by_name.get(name)
                    accepted = bool(
                        match is not None
                        and self._is_signal_measurement_row(match[1]) is expect_signal
                    )
                    found.append(accepted)
                    indices.append(match[0] if accepted and match is not None else None)
                return found, indices

            telemetry_found, telemetry_definition_indices = resolve_names(telemetry_names, False)
            signal_found, signal_definition_indices = resolve_names(signal_names, True)
            selected_indices: List[int] = []
            for index in [*telemetry_definition_indices, *signal_definition_indices]:
                if index is not None and index not in selected_indices:
                    selected_indices.append(index)
            history = self.measurement_history(indices=selected_indices)
            metadata = self._external_response_metadata()
            external_definition_signature = self.external_telemetry_names()["definition_signature"]

        selected_positions = {
            definition_index: position
            for position, definition_index in enumerate(history.get("indices", []))
        }
        telemetry_positions = [
            selected_positions.get(index) if index is not None else None
            for index in telemetry_definition_indices
        ]
        signal_positions = [
            selected_positions.get(index) if index is not None else None
            for index in signal_definition_indices
        ]
        frames = [
            frame
            for frame in history.get("frames", []) or []
            if (type(frame) is dict or isinstance(frame, Mapping))
            and _to_float(frame.get("absolute_minute"), None) is not None
        ]
        frames.sort(
            key=lambda frame: (
                float(_to_float(frame.get("absolute_minute"), 0.0) or 0.0),
                int(_to_float(frame.get("step_count"), 0) or 0),
                int(_to_float(frame.get("seq"), 0) or 0),
            )
        )

        interval_minutes = interval_seconds / 60.0
        available_start = (
            float(_to_float(frames[0].get("absolute_minute"), 0.0) or 0.0)
            if frames
            else None
        )
        available_end = (
            float(_to_float(frames[-1].get("absolute_minute"), 0.0) or 0.0)
            if frames
            else None
        )
        effective_start = max(start_minute, available_start) if available_start is not None else None
        effective_end = min(end_minute, available_end) if available_end is not None else None
        sample_count = 0
        if effective_start is not None and effective_end is not None and effective_start <= effective_end + 1e-9:
            raw_sample_count = (effective_end - effective_start + 1e-9) / interval_minutes + 1.0
            if not math.isfinite(raw_sample_count) or raw_sample_count > 10000:
                raise ValueError("history query would return more than 10000 samples; increase interval_seconds")
            sample_count = max(0, int(math.floor(raw_sample_count + 1e-9)))

        absolute_minutes: List[Any] = []
        simu_times: List[str] = []
        source_absolute_minutes: List[Any] = []
        source_simu_times: List[str] = []
        source_wall_times: List[str] = []
        telemetry_values: List[List[Any]] = []
        signal_values: List[List[Any]] = []
        telemetry_valid: List[List[int]] = []
        signal_valid: List[List[int]] = []

        def frame_values(
            frame: Mapping[str, Any],
            field: str,
            positions: Sequence[Optional[int]],
            *,
            signal: bool = False,
        ) -> List[Any]:
            values = frame.get(field, [])
            source = values if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) else []
            result: List[Any] = []
            for position in positions:
                if position is None or position >= len(source) or source[position] is None:
                    result.append(None)
                    continue
                if signal:
                    result.append(1 if float(_to_float(source[position], 0.0) or 0.0) > 0.5 else 0)
                else:
                    result.append(_json_scalar(source[position]))
            return result

        def frame_valid(frame: Mapping[str, Any], positions: Sequence[Optional[int]]) -> List[int]:
            values = frame.get("valid_values", [])
            source = values if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) else []
            return [
                int(_to_float(source[position], 0) or 0)
                if position is not None and position < len(source) and source[position] is not None
                else 0
                for position in positions
            ]

        frame_index = 0
        for sample_index in range(sample_count):
            target_minute = round(float(effective_start) + sample_index * interval_minutes, 9)
            while (
                frame_index + 1 < len(frames)
                and float(_to_float(frames[frame_index + 1].get("absolute_minute"), 0.0) or 0.0)
                <= target_minute + 1e-9
            ):
                frame_index += 1
            frame = frames[frame_index]
            source_minute = float(_to_float(frame.get("absolute_minute"), 0.0) or 0.0)
            absolute_minutes.append(_json_scalar(target_minute))
            simu_times.append(minute_to_time(target_minute))
            source_absolute_minutes.append(_json_scalar(source_minute))
            source_simu_times.append(str(frame.get("simu_time") or minute_to_time(source_minute)))
            source_wall_times.append(str(frame.get("wall_time") or "--"))
            telemetry_values.append(frame_values(frame, "scada_values", telemetry_positions))
            signal_values.append(frame_values(frame, "scada_values", signal_positions, signal=True))
            telemetry_valid.append(frame_valid(frame, telemetry_positions))
            signal_valid.append(frame_valid(frame, signal_positions))

        return {
            **metadata,
            "definition_signature": external_definition_signature,
            "measurement_definition_signature": history.get("definition_signature", ""),
            "run_id": int(history.get("run_id", 0) or 0),
            "start_time": minute_to_time(start_minute),
            "end_time": minute_to_time(end_minute),
            "start_absolute_minute": _json_scalar(start_minute),
            "end_absolute_minute": _json_scalar(end_minute),
            "available_start_absolute_minute": _json_scalar(available_start),
            "available_end_absolute_minute": _json_scalar(available_end),
            "effective_start_absolute_minute": _json_scalar(effective_start),
            "effective_end_absolute_minute": _json_scalar(effective_end),
            "interval_seconds": _json_scalar(interval_seconds),
            "value_layout": "time-major",
            "sample_count": len(absolute_minutes),
            "absolute_minutes": absolute_minutes,
            "simu_times": simu_times,
            "source_absolute_minutes": source_absolute_minutes,
            "source_simu_times": source_simu_times,
            "source_wall_times": source_wall_times,
            "telemetry_count": len(telemetry_names),
            "signal_count": len(signal_names),
            "telemetry_names": telemetry_names,
            "signal_names": signal_names,
            "telemetry_found": telemetry_found,
            "signal_found": signal_found,
            "telemetry_values": telemetry_values,
            "signal_values": signal_values,
            "telemetry_valid": telemetry_valid,
            "signal_valid": signal_valid,
            "yc_names": telemetry_names,
            "yx_names": signal_names,
            "yc_values": telemetry_values,
            "yx_values": signal_values,
            "missing": {
                "telemetry": [name for name, found in zip(telemetry_names, telemetry_found) if not found],
                "signals": [name for name, found in zip(signal_names, signal_found) if not found],
            },
        }

    def _measurement_definition_row(
        self,
        rows: Sequence[Sequence[str]],
        payload: Mapping[str, Any],
    ) -> Tuple[int, Dict[str, Any]]:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("Measurement name is required")
        matches: List[Tuple[int, Dict[str, Any]]] = []
        for index, row in enumerate(rows):
            item = _measurement_row_to_dict(row)
            if str(item.get("name", "")) == name:
                matches.append((index, item))
        if not matches:
            raise ValueError(f"Unknown measurement: {name}")
        if len(matches) != 1:
            raise ValueError(f"Measurement identity must be unique: {name}")
        index, item = matches[0]
        for identity_field in ("dev_type", "dev_name", "meas_type"):
            expected = str(payload.get(identity_field, "")).strip()
            if expected and str(item.get(identity_field, "")) != expected:
                raise ValueError(f"Measurement {identity_field} does not match: {name}")
        return index, item

    def _apply_manual_measurement_status_overrides_unlocked(
        self,
        snapshot: DefinitionSnapshot,
        items: Sequence[Mapping[str, Any]],
    ) -> None:
        grouped: Dict[str, Dict[str, Any]] = {}
        for item in items:
            if item.get("kind") != "measurement":
                continue
            field_name = str(item.get("field", ""))
            if field_name not in {"status", "fixed_value"}:
                continue
            measurement_name = str(item.get("measurement_name", "")).strip()
            if measurement_name:
                grouped.setdefault(measurement_name, {})[field_name] = item.get(
                    "current_value",
                    "",
                )

        statuses: Dict[str, Dict[str, Any]] = {}
        for measurement_name, values in grouped.items():
            try:
                index, _record = self._measurement_definition_row(
                    snapshot.measurement_rows,
                    {"name": measurement_name},
                )
            except (KeyError, ValueError):
                continue
            default_status = _measurement_status_from_valid(
                snapshot.measurement_rows[index][6]
            )
            status = str(values.get("status", default_status)).strip().casefold()
            if status not in MEASUREMENT_STATUS_TOKENS:
                status = default_status
            fixed_value = _to_float(values.get("fixed_value"), None)
            statuses[measurement_name] = {
                "status": status,
                "fixed_value": fixed_value,
            }
        self.local_settings["measurement_statuses"] = statuses

    def _migrate_legacy_measurement_status_overrides_unlocked(self) -> bool:
        configured_statuses = self.local_settings.get("measurement_statuses", {})
        if not (type(configured_statuses) is dict or isinstance(configured_statuses, Mapping)) or not configured_statuses:
            return False
        migrated = False
        existing_fields = {
            (
                str(item.get("measurement_name", "")),
                str(item.get("field", "")),
            )
            for item in self._manual_definition_changes.values()
            if item.get("kind") == "measurement"
        }
        rows = self.definition_snapshot.measurement_rows
        for measurement_name, configured in configured_statuses.items():
            if not (type(configured) is dict or isinstance(configured, Mapping)):
                continue
            name = str(measurement_name).strip()
            if not name:
                continue
            try:
                index, _record = self._measurement_definition_row(
                    rows,
                    {"name": name},
                )
            except (KeyError, ValueError):
                continue
            before_row = list(rows[index])
            after_row = list(before_row)
            default_status = _measurement_status_from_valid(before_row[6])
            status = str(configured.get("status", default_status)).strip().casefold()
            if status not in MEASUREMENT_STATUS_TOKENS:
                status = default_status
            fixed_value = _to_float(configured.get("fixed_value"), None)
            after_row[6] = str(MEASUREMENT_STATUS_VALIDITY[status])
            changed_fields: List[str] = []
            if (name, "valid") not in existing_fields and not self._manual_change_values_equal(
                before_row[6],
                after_row[6],
            ):
                changed_fields.append("valid")
            if (name, "status") not in existing_fields and status != default_status:
                changed_fields.append("status")
            if (
                (name, "fixed_value") not in existing_fields
                and status == "fixed"
                and fixed_value is not None
            ):
                changed_fields.append("fixed_value")
            if not changed_fields:
                continue
            self._record_measurement_manual_changes_unlocked(
                before_row,
                after_row,
                changed_fields,
                persisted=False,
                persistence_error="正在迁移旧量测状态覆盖",
                before_status=default_status,
                before_fixed_value=None,
                after_status=status,
                after_fixed_value=fixed_value,
            )
            migrated = True

        # Measurement status edits now live exclusively in manual_overrides.json.
        # Keep unrelated runtime settings, but remove the legacy duplicate layer.
        self.local_settings["measurement_statuses"] = {}
        try:
            _write_json(self.settings_file, self.local_settings)
        except OSError:
            pass
        return migrated

    def _record_measurement_manual_changes_unlocked(
        self,
        before_row: Sequence[Any],
        after_row: Sequence[Any],
        changed_fields: Sequence[str],
        *,
        persisted: bool,
        persistence_error: str = "",
        before_status: Optional[str] = None,
        before_fixed_value: Any = None,
        before_median_deviation: Any = 0.0,
        after_status: Optional[str] = None,
        after_fixed_value: Any = None,
        after_median_deviation: Any = 0.0,
    ) -> None:
        after = _measurement_row_to_dict(after_row)
        measurement_name = str(after.get("name", ""))
        identity = {"measurement_name": measurement_name}
        object_type = str(after.get("dev_type", ""))
        object_name = str(after.get("dev_name", ""))
        raw_values = {
            "weight": (before_row[5], after_row[5]),
            "median_deviation": (
                before_median_deviation,
                after_median_deviation,
            ),
            "valid": (before_row[6], after_row[6]),
            "status": (
                before_status
                if before_status is not None
                else _measurement_status_from_valid(before_row[6]),
                after_status
                if after_status is not None
                else _measurement_status_from_valid(after_row[6]),
            ),
            "fixed_value": (before_fixed_value, after_fixed_value),
        }
        now = _now_text()
        for field_name in changed_fields:
            if field_name not in raw_values:
                continue
            default_raw, current_raw = raw_values[field_name]
            change_id = self._manual_change_id("measurement", identity, field_name)
            existing = self._manual_definition_changes.get(change_id, {})
            default_value = self._manual_change_value_text(existing.get("default_value", default_raw))
            current_value = self._manual_change_value_text(current_raw)
            if persisted and self._manual_change_values_equal(current_value, default_value):
                self._manual_definition_changes.pop(change_id, None)
                continue
            item = {
                **existing,
                "id": change_id,
                "kind": "measurement",
                "change_type": (
                    "量测参数"
                    if field_name in {"weight", "median_deviation"}
                    else "量测状态"
                ),
                "object_type": object_type,
                "object_name": object_name,
                "object_id": str(after.get("idx", "")),
                "object_label": f"{object_type}.{object_name} · {measurement_name}",
                "measurement_name": measurement_name,
                "measurement_type": str(after.get("meas_type", "")),
                "field": field_name,
                "field_label": {
                    "weight": "量测误差 / 权重",
                    "median_deviation": "中值偏差",
                    "valid": "量测有效性",
                    "status": "量测状态",
                    "fixed_value": "量测固定值",
                }[field_name],
                "default_value": default_value,
                "current_value": current_value,
                "modified_at": now,
                "source_file": (
                    DEFINITION_DEFAULTS_FILE
                    if field_name == "median_deviation"
                    else "meas.e"
                ),
            }
            self._set_manual_change_sync_state_unlocked(
                item,
                persisted=persisted,
                error=persistence_error,
            )
            if field_name == "weight":
                item["default_error_sigma"] = self._manual_change_sigma(default_value)
                item["current_error_sigma"] = self._manual_change_sigma(current_value)
            self._manual_definition_changes[change_id] = item

    def update_measurement_definition(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self._active_definition_update_guard():
            current = self.definition_snapshot
            require_definition_revision(payload, current.revision)
            rows = [list(row) for row in current.measurement_rows]
            index, current_item = self._measurement_definition_row(rows, payload)
            before_row = list(rows[index])
            measurement_name = str(current_item.get("name", ""))
            median_deviations = _measurement_median_deviation_map(current)
            current_median_deviation = median_deviations.get(measurement_name, 0.0)
            changes = payload.get("changes", {})
            if not (type(changes) is dict or isinstance(changes, Mapping)):
                raise ValueError("changes must be an object")
            current_with_status = dict(current_item)
            current_status, current_fixed_value = self._measurement_status_override(current_item)
            current_with_status["status"] = current_status
            current_with_status["fixed_value"] = current_fixed_value
            current_with_status["median_deviation"] = current_median_deviation
            normalized = normalize_measurement_changes(current_with_status, changes)
            rows[index][5] = normalized["weight"]
            rows[index][6] = normalized["valid"]
            if normalized["median_deviation"] == 0.0:
                median_deviations.pop(measurement_name, None)
            else:
                median_deviations[measurement_name] = normalized["median_deviation"]
            next_snapshot = DefinitionSnapshot(
                revision=current.revision + 1,
                model_book=current.model_book,
                dev_define_book=current.dev_define_book,
                measurement_before=current.measurement_before,
                measurement_rows=tuple(tuple(row) for row in rows),
                measurement_after=current.measurement_after,
                measurement_median_deviations=_normalized_measurement_median_deviation_pairs(
                    median_deviations
                ),
            )
            self._publish_definition_snapshot(next_snapshot)

            changed_fields: List[str] = []
            if "weight" in changes or "error_sigma" in changes:
                changed_fields.append("weight")
            if "median_deviation" in changes:
                changed_fields.append("median_deviation")
            if "valid" in changes or "status" in changes:
                changed_fields.append("valid")
            if "status" in changes:
                changed_fields.append("status")
            if "fixed_value" in changes or (
                "status" in changes
                and (
                    current_fixed_value is not None
                    or normalized["fixed_value"] is not None
                )
            ):
                changed_fields.append("fixed_value")
            self._record_measurement_manual_changes_unlocked(
                before_row,
                rows[index],
                changed_fields,
                persisted=False,
                persistence_error="等待人工覆盖层保存",
                before_status=current_status,
                before_fixed_value=current_fixed_value,
                before_median_deviation=current_median_deviation,
                after_status=normalized["status"],
                after_fixed_value=normalized["fixed_value"],
                after_median_deviation=normalized["median_deviation"],
            )
            self._apply_manual_measurement_status_overrides_unlocked(
                next_snapshot,
                list(self._manual_definition_changes.values()),
            )
            persisted = False
            change_record_persisted = False
            warning = ""
            try:
                self._write_ahead_manual_definition_changes_unlocked()
            except OSError as exc:
                persistence_error = f"人工覆盖层保存失败: {exc}"
                warning = f"后台定义已更新，但人工覆盖层保存失败，请重试: {exc}"
                self._record_measurement_manual_changes_unlocked(
                    before_row,
                    rows[index],
                    changed_fields,
                    persisted=False,
                    persistence_error=persistence_error,
                    before_status=current_status,
                    before_fixed_value=current_fixed_value,
                    before_median_deviation=current_median_deviation,
                    after_status=normalized["status"],
                    after_fixed_value=normalized["fixed_value"],
                    after_median_deviation=normalized["median_deviation"],
                )
            else:
                change_record_persisted = True
                pending_changes = {
                    change_id: dict(item)
                    for change_id, item in self._manual_definition_changes.items()
                }
                self._mark_manual_changes_persisted_unlocked("measurement")
                try:
                    self._write_manual_definition_changes_unlocked()
                except OSError as exc:
                    self._manual_definition_changes = pending_changes
                    warning = (
                        "人工覆盖层已保存当前值，但同步状态保存失败，请重试: "
                        f"{exc}"
                    )
                else:
                    persisted = True
            record = _measurement_row_to_dict(rows[index])
            record["error_sigma"] = normalized["error_sigma"]
            record["median_deviation"] = normalized["median_deviation"]
            record["status"] = normalized["status"]
            record["fixed_value"] = normalized["fixed_value"]
            result = self._definition_update_result(
                next_snapshot,
                record,
                persisted=persisted,
                warning=warning,
            )
            result["change_record_persisted"] = change_record_persisted
            return result
