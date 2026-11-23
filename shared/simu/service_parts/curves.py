"""PolarMicrogridSimulator 拆分模块：曲线目录、编辑、边界投影与插值缓存能力。"""

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


class _CurvesMixin:
    """曲线目录、编辑、边界投影与插值缓存能力。"""

    def _read_curves(self) -> Dict[str, Any]:
        default = {"mode": "day", "time_step_minutes": 1, "weather": [], "loads": {}, "sources": []}
        source_curves = _read_json(self.source_curves_file, default) if self.source_curves_file.exists() else default
        payload = _read_json(self.curves_file, source_curves)
        return self._normalized_curves_with_source_defaults(payload)

    def _source_curve_catalog(self) -> Tuple[Dict[str, Any], ...]:
        revision = self.definition_snapshot.revision
        if revision != self._source_curve_catalog_cache_key:
            self._source_curve_catalog_cache_key = revision
            self._source_curve_catalog_cache_value = tuple(
                dict(item) for item in source_curve_catalog(self.definition_snapshot.model_book)
            )
        return self._source_curve_catalog_cache_value

    def _normalized_source_curves(
        self,
        raw_sources: Any,
        point_count: int,
        step_minutes: float,
    ) -> List[Dict[str, Any]]:
        catalog = self._source_curve_catalog()
        catalog_by_identity = {source_curve_identity(item): item for item in catalog}
        incoming: Dict[Tuple[str, str, str], Mapping[str, Any]] = {}
        if (type(raw_sources) is dict or isinstance(raw_sources, Mapping)):
            candidates = raw_sources.values()
        elif isinstance(raw_sources, Sequence) and not isinstance(raw_sources, (str, bytes)):
            candidates = raw_sources
        else:
            candidates = ()
        for item in candidates:
            if not (type(item) is dict or isinstance(item, Mapping)):
                continue
            identity = source_curve_identity(item)
            if identity in catalog_by_identity:
                incoming[identity] = item

        normalized: List[Dict[str, Any]] = []
        for catalog_item in catalog:
            identity = source_curve_identity(catalog_item)
            raw_item = incoming.get(identity, {})
            points = _normalize_points(raw_item.get("points"), ("value", "set_value", "p_kw", "flow_set"))
            default_value = float(catalog_item.get("default_value", 0.0) or 0.0)
            normalized_points: List[Dict[str, Any]] = []
            for index, raw_point in enumerate(points):
                value = next(
                    (
                        raw_point.get(alias)
                        for alias in ("value", "set_value", "p_kw", "flow_set")
                        if raw_point.get(alias) not in (None, "")
                    ),
                    default_value,
                )
                normalized_points.append(
                    {
                        "minute": _to_float(raw_point.get("minute"), index * step_minutes)
                        if raw_point
                        else index * step_minutes,
                        "value": _to_float(value, default_value) or 0.0,
                    }
                )
            if not normalized_points:
                normalized_points.append({"minute": 0.0, "value": default_value})
            normalized.append({**dict(catalog_item), "points": normalized_points})
        return normalized

    def _normalized_curves_with_source_defaults(self, payload: Any) -> Dict[str, Any]:
        raw = dict(payload) if (type(payload) is dict or isinstance(payload, Mapping)) else {}
        mode = _normalize_simulation_mode(raw.get("mode", "day"))
        default_step = _simulation_mode_curve_step_minutes(mode)
        step_minutes = float(_to_float(raw.get("time_step_minutes"), default_step) or default_step)
        if step_minutes <= 0:
            step_minutes = default_step
        weather = raw.get("weather", [])
        loads = raw.get("loads", {})
        point_count = int(_to_float(raw.get("point_count"), 0) or 0)
        if point_count <= 0:
            point_count = len(weather) if isinstance(weather, Sequence) and not isinstance(weather, (str, bytes)) else 0
        if point_count <= 0 and (type(loads) is dict or isinstance(loads, Mapping)):
            point_count = max(
                (
                    len(points)
                    for points in loads.values()
                    if isinstance(points, Sequence) and not isinstance(points, (str, bytes))
                ),
                default=0,
            )
        point_count = point_count or _simulation_mode_point_count(mode)
        raw.update(
            {
                "mode": mode,
                "time_step_minutes": step_minutes,
                "point_count": point_count,
                "weather": weather if isinstance(weather, list) else [],
                "loads": loads,
                "sources": self._normalized_source_curves(raw.get("sources"), point_count, step_minutes),
            }
        )
        return raw

    def _manual_source_curve_override_keys(self) -> set[Tuple[str, str, str]]:
        keys: set[Tuple[str, str, str]] = set()
        for item in self._manual_definition_changes.values():
            if item.get("kind") != "device" or item.get("effective") is False:
                continue
            dev_type = str(item.get("block_name", "")).strip()
            set_type = str(item.get("field", "")).strip().casefold()
            row_key = item.get("row_key", {})
            dev_name = (
                str(row_key.get("name", "")).strip()
                if (type(row_key) is dict or isinstance(row_key, Mapping))
                else ""
            )
            if dev_type and dev_name and set_type:
                keys.add((dev_type, dev_name, set_type))
                canonical_set_type = RUNTIME_CONTROL_SETPOINT_ALIASES.get((dev_type, set_type))
                if canonical_set_type:
                    keys.add((dev_type, dev_name, canonical_set_type))
        return keys

    def _inactive_coupling_default_curve_keys(self) -> set[Tuple[str, str, str]]:
        active_by_endpoint: Dict[Tuple[str, str, str], bool] = {}
        for bindings in energy_coupling_control_bindings(
            self.definition_snapshot.model_book
        ).values():
            for binding in bindings:
                key = (
                    str(binding.get("target_dev_type", "")).strip(),
                    str(binding.get("target_dev_name", "")).strip(),
                    str(binding.get("target_set_type", binding.get("set_type", ""))).strip(),
                )
                if not all(key):
                    continue
                active_by_endpoint[key] = active_by_endpoint.get(key, False) or bool(
                    binding.get("active")
                )
        return {key for key, active in active_by_endpoint.items() if not active}

    def _apply_default_source_curves(
        self,
        book: EBook,
        absolute_minute: int | float,
        *,
        allowed_set_keys: Optional[set[Tuple[str, str, str]]] = None,
        active_command_keys: Optional[set[Tuple[str, str, str]]] = None,
    ) -> int:
        sources = self.curves.get("sources", [])
        if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
            return 0
        catalog = source_curve_catalog_by_identity(self.definition_snapshot.model_book)
        allowed = allowed_set_keys if allowed_set_keys is not None else self._defined_set_control_keys()
        manual_overrides = self._manual_source_curve_override_keys()
        active_commands = (
            active_command_keys
            if active_command_keys is not None
            else self._active_remote_adjustment_keys(absolute_minute)
        )
        inactive_coupling_keys = self._inactive_coupling_default_curve_keys()
        curve_mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
        period_minutes = _simulation_mode_duration_minutes(curve_mode)
        applied = 0
        for item in sources:
            if not (type(item) is dict or isinstance(item, Mapping)):
                continue
            key = source_curve_identity(item)
            if (
                key not in catalog
                or key in manual_overrides
                or key in active_commands
                or key in inactive_coupling_keys
            ):
                continue
            points = item.get("points", [])
            if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
                continue
            value = self._interpolate_curve_series(
                points,
                absolute_minute,
                "value",
                None,
                period_minutes=period_minutes,
            )
            if value is None or not math.isfinite(value):
                continue
            try:
                safe = self._validated_set_command_item(
                    {
                        "dev_type": key[0],
                        "dev_name": key[1],
                        "set_type": key[2],
                        "set_value": value,
                    },
                    strict=True,
                )
            except ValueError:
                continue
            self._write_boundary_set_value(book, key, float(safe["set_value"]))
            applied += 1
        return applied

    def _apply_default_non_electric_load_curves(
        self,
        book: EBook,
        absolute_minute: int | float,
        *,
        active_command_keys: Optional[set[Tuple[str, str, str]]] = None,
    ) -> int:
        catalog = {
            str(item["key"]): item
            for item in self._external_curve_catalog()
            if item.get("curve_type") == "load"
            and item.get("dev_type") in {"HydroLoad", "HeatLoad"}
        }
        manual_overrides = self._manual_source_curve_override_keys()
        active_commands = (
            active_command_keys
            if active_command_keys is not None
            else self._active_remote_adjustment_keys(absolute_minute)
        )
        inactive_coupling_keys = self._inactive_coupling_default_curve_keys()
        curve_mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
        period_minutes = _simulation_mode_duration_minutes(curve_mode)
        applied = 0
        for item in catalog.values():
            key = load_curve_identity(item)
            if key in manual_overrides or key in active_commands or key in inactive_coupling_keys:
                continue
            points = item.get("points", [])
            aliases = tuple(item.get("value_aliases", ("value",)))
            value = None
            for alias in aliases:
                value = self._interpolate_curve_series(
                    points,
                    absolute_minute,
                    str(alias),
                    None,
                    period_minutes=period_minutes,
                )
                if value is not None:
                    break
            if value is None or not math.isfinite(value):
                continue
            try:
                safe = self._validated_set_command_item(
                    {
                        "dev_type": key[0],
                        "dev_name": key[1],
                        "set_type": key[2],
                        "set_value": value,
                    },
                    strict=True,
                )
            except ValueError:
                continue
            self._write_boundary_set_value(book, key, float(safe["set_value"]))
            applied += 1
        return applied

    def _curve_point_index(self, target_minute: float, period_minutes: float) -> int:
        points = self.curves.get("weather", [])
        if isinstance(points, Sequence) and not isinstance(points, (str, bytes)) and points:
            target = target_minute % period_minutes
            # 针对周/年仿真等上万点单调时间轴使用 O(log N) 二分查找，替代每步 O(N) 线性扫描
            n_points = len(points)
            cache = getattr(self, "_weather_curve_minutes_cache", None)
            cache_key = (self._curve_revision, id(points), n_points, period_minutes)
            if cache is None or cache[0] != cache_key:
                minutes_arr: list[float] = []
                monotonic = True
                prev_m = -1.0
                for idx, point in enumerate(points):
                    if not (type(point) is dict or isinstance(point, Mapping)):
                        monotonic = False
                        break
                    pm = float(_to_float(point.get("minute", idx), float(idx)) or 0.0) % period_minutes
                    if idx > 0 and pm < prev_m:
                        monotonic = False
                        break
                    minutes_arr.append(pm)
                    prev_m = pm
                cache = (cache_key, minutes_arr if monotonic and len(minutes_arr) == n_points else None)
                self._weather_curve_minutes_cache = cache
            minutes_arr = cache[1]
            if minutes_arr is not None:
                import bisect

                pos = bisect.bisect_left(minutes_arr, target)
                candidates = {pos % n_points, (pos - 1) % n_points, 0, n_points - 1}
                best_index = 0
                best_distance = period_minutes + 1.0
                for idx in candidates:
                    dist = abs(minutes_arr[idx] - target)
                    dist = min(dist, period_minutes - dist)
                    if dist < best_distance or (dist == best_distance and idx < best_index):
                        best_index = idx
                        best_distance = dist
                return best_index + 1
            best_index = 0
            best_distance = period_minutes
            for idx, point in enumerate(points):
                if not (type(point) is dict or isinstance(point, Mapping)):
                    continue
                point_minute = float(_to_float(point.get("minute", idx), float(idx)) or 0.0) % period_minutes
                distance = abs(point_minute - target)
                distance = min(distance, period_minutes - distance)
                if distance < best_distance:
                    best_index = idx
                    best_distance = distance
            return best_index + 1
        step = max(1e-9, _to_float(self.curves.get("time_step_minutes"), 1.0) or 1.0)
        return int(((target_minute % period_minutes) + 1e-9) // step) + 1

    def set_curves(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock, self.curves_lock:
            current_mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
            mode = _normalize_simulation_mode(payload.get("mode", current_mode), current_mode)
            if mode != current_mode and self.clock.state != "stopped":
                raise ValueError("仿真运行过程中不能切换仿真模式，请先停止仿真")
            default_step = _simulation_mode_curve_step_minutes(mode)
            time_step_minutes = float(_to_float(payload.get("time_step_minutes"), default_step) or default_step)
            if time_step_minutes <= 0:
                time_step_minutes = default_step
            default_point_count = _simulation_mode_point_count(mode)
            point_count = int(_to_float(payload.get("point_count"), default_point_count) or 0)
            weather_points = _normalize_points(
                payload.get("weather"),
                WEATHER_HEADER[1:],
                step_minutes=time_step_minutes,
            )
            loads_payload = payload.get("loads", {})
            loads: Dict[str, List[Dict[str, Any]]] = {}
            if (type(loads_payload) is dict or isinstance(loads_payload, Mapping)):
                for name, points in loads_payload.items():
                    load_key = str(name)
                    if load_key.startswith("HydroLoad:"):
                        aliases: Tuple[str, ...] = ("flow_set", "value")
                    elif load_key.startswith("HeatLoad:"):
                        aliases = ("heat_power", "value")
                    else:
                        aliases = ("p_kw", "value", "load_kw")
                    loads[load_key] = _normalize_points(
                        points,
                        aliases,
                        step_minutes=time_step_minutes,
                    )
            elif isinstance(loads_payload, Sequence) and not isinstance(loads_payload, (str, bytes)):
                for item in loads_payload:
                    if not (type(item) is dict or isinstance(item, Mapping)):
                        continue
                    name = str(item.get("dev_name", item.get("name", "load")))
                    default_min = float(len(loads.get(name, []))) * time_step_minutes
                    parsed_min = _to_float(item.get("minute"), None)
                    loads.setdefault(name, []).append(
                        {
                            "minute": default_min if parsed_min is None else float(parsed_min),
                            "p_kw": item.get("p_kw", item.get("value", item.get("load_kw", 0))),
                        }
                    )
            resolved_point_count = point_count or len(weather_points) or default_point_count
            self.curves = {
                "mode": mode,
                "time_step_minutes": time_step_minutes,
                "point_count": resolved_point_count,
                "weather": weather_points,
                "loads": loads,
                "sources": self._normalized_source_curves(
                    payload.get("sources"),
                    resolved_point_count,
                    time_step_minutes,
                ),
            }
            if mode != current_mode:
                self._apply_mode_default_clock_speed(mode, persist=True)
                self.clock.absolute_minute = _align_minute_to_step(
                    self.clock.absolute_minute,
                    _effective_clock_step(self.clock.step_minutes, self.clock.speed),
                )
            self.clock.minute = self.clock.absolute_minute % 1440.0
            self.clock.updated_at = time.time()
            _write_json(self.curves_file, self.curves)
            self._curve_revision += 1
            return {
                "weather_points": len(weather_points),
                "load_devices": len(loads),
                "source_devices": len(self.curves["sources"]),
                "mode": mode,
            }

    def curves_summary(self) -> Dict[str, Any]:
        with self.curves_lock:
            mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
            default_step = _simulation_mode_curve_step_minutes(mode)
            default_point_count = _simulation_mode_point_count(mode)
            weather = self.curves.get("weather", [])
            loads = self.curves.get("loads", {})
            sources = self.curves.get("sources", [])
            point_count = int(_to_float(self.curves.get("point_count"), 0) or 0)
            if not point_count:
                point_count = len(weather) if isinstance(weather, Sequence) else 0
            load_catalog = {
                str(item.get("storage_key", "")): item
                for item in self._external_curve_catalog()
                if item.get("curve_type") == "load"
            }
            return {
                "mode": mode,
                "time_step_minutes": float(_to_float(self.curves.get("time_step_minutes"), default_step) or default_step),
                "point_count": point_count or default_point_count,
                "environment": [
                    {
                        "key": key,
                        "point_count": len(weather) if isinstance(weather, Sequence) else 0,
                    }
                    for key in ("wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c")
                ],
                "loads": [
                    {
                        "key": f"load:{name}",
                        "name": str(name),
                        "point_count": len(points) if isinstance(points, Sequence) else 0,
                        **{
                            key: load_catalog[str(name)].get(key)
                            for key in ("dev_type", "dev_name", "set_type", "family", "unit")
                            if str(name) in load_catalog and load_catalog[str(name)].get(key) is not None
                        },
                    }
                    for name, points in (loads.items() if (type(loads) is dict or isinstance(loads, Mapping)) else [])
                ],
                "sources": [
                    {
                        key: item.get(key)
                        for key in (
                            "key",
                            "dev_type",
                            "dev_name",
                            "name",
                            "set_type",
                            "family",
                            "unit",
                            "default_value",
                            "min",
                            "max",
                        )
                        if item.get(key) is not None
                    }
                    | {
                        "point_count": len(item.get("points", []))
                        if isinstance(item.get("points"), Sequence)
                        and not isinstance(item.get("points"), (str, bytes))
                        else 0
                    }
                    for item in (
                        sources
                        if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes))
                        else []
                    )
                    if (type(item) is dict or isinstance(item, Mapping))
                ],
            }

    def _curve_series_values(self, key: str) -> List[float]:
        if key in ("wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c"):
            weather = self.curves.get("weather", [])
            if not isinstance(weather, Sequence) or isinstance(weather, (str, bytes)):
                return []
            return [float(_to_float(point.get(key), 0.0) or 0.0) for point in weather if (type(point) is dict or isinstance(point, Mapping))]
        if key.startswith("load:"):
            load_name = key.replace("load:", "", 1)
            loads = self.curves.get("loads", {})
            points = loads.get(load_name, []) if (type(loads) is dict or isinstance(loads, Mapping)) else []
            if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
                return []
            catalog_item = next(
                (
                    item for item in self._external_curve_catalog()
                    if item.get("curve_type") == "load"
                    and str(item.get("storage_key", "")) == load_name
                ),
                None,
            )
            aliases = tuple(catalog_item.get("value_aliases", ())) if catalog_item else ("p_kw", "value", "load_kw")
            return [
                float(
                    next(
                        (
                            _to_float(point.get(alias), 0.0)
                            for alias in aliases
                            if point.get(alias) not in (None, "")
                        ),
                        0.0,
                    )
                    or 0.0
                )
                for point in points
                if (type(point) is dict or isinstance(point, Mapping))
            ]
        if key.startswith("source:"):
            sources = self.curves.get("sources", [])
            if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
                return []
            item = next(
                (
                    item
                    for item in sources
                    if (type(item) is dict or isinstance(item, Mapping)) and str(item.get("key", "")) == key
                ),
                None,
            )
            if item is None:
                return []
            points = item.get("points", [])
            if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
                return []
            return [
                float(_to_float(point.get("value", point.get("set_value")), 0.0) or 0.0)
                for point in points
                if (type(point) is dict or isinstance(point, Mapping))
            ]
        return []

    def curves_series(self, keys: Sequence[str]) -> Dict[str, Any]:
        with self.curves_lock:
            mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
            default_step = _simulation_mode_curve_step_minutes(mode)
            default_point_count = _simulation_mode_point_count(mode)
            point_count = int(_to_float(self.curves.get("point_count"), default_point_count) or 0)
            requested = [str(key).strip() for key in keys if str(key).strip()]
            if not requested:
                requested = ["wind_speed_mps"]
            series: Dict[str, List[float]] = {}
            for key in requested:
                values = self._curve_series_values(key)
                if values:
                    series[key] = values
            return {
                "mode": mode,
                "time_step_minutes": float(_to_float(self.curves.get("time_step_minutes"), default_step) or default_step),
                "point_count": point_count or default_point_count,
                "series": series,
            }

    @staticmethod
    def _external_curve_range(
        item: Mapping[str, Any],
        fallback: Mapping[str, Any],
    ) -> Tuple[Optional[float], Optional[float]]:
        raw_start = item.get("start_minute", fallback.get("start_minute"))
        raw_end = item.get("end_minute", fallback.get("end_minute"))
        if raw_start in (None, "") and raw_end in (None, ""):
            return None, None
        if raw_start in (None, "") or raw_end in (None, ""):
            raise ValueError("曲线时间范围必须同时提供 start_minute 和 end_minute")
        start = _to_float(raw_start, None)
        end = _to_float(raw_end, None)
        if start is None or end is None or not math.isfinite(start) or not math.isfinite(end):
            raise ValueError("曲线时间范围必须是有限数值")
        if start < 0 or end < 0:
            raise ValueError("曲线时间范围不能为负数")
        if start > end:
            raise ValueError("曲线时间范围 start_minute 不能大于 end_minute")
        return float(start), float(end)

    @staticmethod
    def _load_curve_storage_key(
        item: Mapping[str, Any],
        loads: Mapping[str, Any],
        name_counts: Mapping[str, int],
    ) -> str:
        structured_key = str(item["key"])
        dev_type = str(item["dev_type"])
        dev_name = str(item["dev_name"])
        for candidate in (structured_key, f"{dev_type}:{dev_name}", dev_name):
            if candidate in loads and (candidate != dev_name or name_counts.get(dev_name, 0) == 1):
                return candidate
        return dev_name if name_counts.get(dev_name, 0) == 1 else f"{dev_type}:{dev_name}"

    def _external_curve_catalog(self, curves: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
        current = curves if (type(curves) is dict or isinstance(curves, Mapping)) else self.curves
        weather = current.get("weather", [])
        catalog: List[Dict[str, Any]] = [
            {
                "key": key,
                "curve_type": "environment",
                "energy_type": "environment",
                "dev_type": "Environment",
                "dev_name": "weather",
                "set_type": key,
                "unit": unit,
                "storage_kind": "weather",
                "storage_key": key,
                "value_aliases": (key,),
                "points": weather,
            }
            for key, unit in EXTERNAL_CURVE_ENVIRONMENT_SPECS.items()
        ]

        loads = current.get("loads", {})
        loads = loads if (type(loads) is dict or isinstance(loads, Mapping)) else {}
        load_items = load_curve_catalog(self.definition_snapshot.model_book)
        name_counts: Dict[str, int] = {}
        for item in load_items:
            name = str(item["dev_name"])
            name_counts[name] = name_counts.get(name, 0) + 1
        for item in load_items:
            storage_key = self._load_curve_storage_key(item, loads, name_counts)
            catalog.append(
                {
                    **dict(item),
                    "curve_type": "load",
                    "energy_type": item.get("family", ""),
                    "storage_kind": "load",
                    "storage_key": storage_key,
                    "points": loads.get(storage_key, []),
                }
            )

        sources = current.get("sources", [])
        source_points = {
            str(item.get("key", "")): item.get("points", [])
            for item in sources
            if (type(item) is dict or isinstance(item, Mapping))
        } if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)) else {}
        for item in source_curve_catalog(self.definition_snapshot.model_book):
            key = str(item["key"])
            catalog.append(
                {
                    **dict(item),
                    "curve_type": "source",
                    "energy_type": item.get("family", ""),
                    "storage_kind": "source",
                    "storage_key": key,
                    "value_aliases": ("value", "set_value", "p_kw", "flow_set"),
                    "points": source_points.get(key, []),
                }
            )
        return catalog

    @staticmethod
    def _external_curve_public_item(
        item: Mapping[str, Any],
        start_minute: Optional[float] = None,
        end_minute: Optional[float] = None,
    ) -> Dict[str, Any]:
        aliases = tuple(str(alias) for alias in item.get("value_aliases", ("value",)))
        points: List[Dict[str, float]] = []
        raw_points = item.get("points", [])
        if isinstance(raw_points, Sequence) and not isinstance(raw_points, (str, bytes)):
            for index, point in enumerate(raw_points):
                if not (type(point) is dict or isinstance(point, Mapping)):
                    continue
                minute = _to_float(point.get("minute"), float(index))
                value = next(
                    (
                        _to_float(point.get(alias), None)
                        for alias in aliases
                        if point.get(alias) not in (None, "")
                    ),
                    None,
                )
                if minute is None or value is None or not math.isfinite(minute) or not math.isfinite(value):
                    continue
                if start_minute is not None and minute < start_minute:
                    continue
                if end_minute is not None and minute > end_minute:
                    continue
                points.append({"minute": float(minute), "value": float(value)})
        points.sort(key=lambda point: point["minute"])
        return {
            key: item.get(key, "")
            for key in (
                "key", "curve_type", "energy_type", "dev_type",
                "dev_name", "set_type", "unit",
            )
        } | {"points": points}

    @staticmethod
    def _external_curve_selectors(payload: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        raw_curves = payload.get("curves")
        if raw_curves is not None:
            if not isinstance(raw_curves, Sequence) or isinstance(raw_curves, (str, bytes)):
                raise ValueError("curves 必须是曲线选择数组")
            if any(not (type(item) is dict or isinstance(item, Mapping)) for item in raw_curves):
                raise ValueError("curves 中的每一项必须是曲线对象")
            return list(raw_curves)
        raw_keys = payload.get("keys")
        if raw_keys is None:
            return []
        if isinstance(raw_keys, str):
            raw_keys = [key.strip() for key in raw_keys.split(",")]
        if not isinstance(raw_keys, Sequence) or isinstance(raw_keys, (str, bytes)):
            raise ValueError("keys 必须是曲线键数组")
        return [{"key": str(key).strip()} for key in raw_keys if str(key).strip()]

    @staticmethod
    def _resolve_external_curve(
        selector: Mapping[str, Any],
        catalog: Mapping[str, Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        key = str(selector.get("key", "")).strip()
        item = catalog.get(key) if key else None
        if item is None and not key:
            identity = tuple(
                str(selector.get(field, "")).strip()
                for field in ("dev_type", "dev_name", "set_type")
            )
            if all(identity):
                matches = [
                    candidate
                    for candidate in catalog.values()
                    if tuple(str(candidate.get(field, "")) for field in ("dev_type", "dev_name", "set_type"))
                    == identity
                ]
                item = matches[0] if len(matches) == 1 else None
        if item is None:
            identity_text = "/".join(
                str(selector.get(field, "")).strip()
                for field in ("dev_type", "dev_name", "set_type")
            ).strip("/")
            raise ValueError(f"曲线不存在：{key or identity_text or '<empty>'}")
        key = str(item["key"])
        for field in ("curve_type", "energy_type", "dev_type", "dev_name", "set_type"):
            requested = str(selector.get(field, "")).strip()
            if requested and requested != str(item.get(field, "")):
                raise ValueError(f"曲线 {key} 的 {field} 身份不匹配")
        return item

    def external_curves_query(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.curves_lock:
            catalog = self._external_curve_catalog()
            by_key = {str(item["key"]): item for item in catalog}
            selectors = self._external_curve_selectors(payload)
            if not selectors:
                selectors = [{"key": item["key"]} for item in catalog]
            curves = []
            for selector in selectors:
                item = self._resolve_external_curve(selector, by_key)
                start, end = self._external_curve_range(selector, payload)
                curves.append(self._external_curve_public_item(item, start, end))
            mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
            default_step = _simulation_mode_curve_step_minutes(mode)
            return {
                **self._external_response_metadata(),
                "mode": mode,
                "time_step_minutes": float(
                    _to_float(self.curves.get("time_step_minutes"), default_step) or default_step
                ),
                "returned_count": len(curves),
                "available_count": len(catalog),
                "curves": curves,
            }

    @staticmethod
    def _validated_external_curve_points(raw_points: Any) -> List[Dict[str, float]]:
        if not isinstance(raw_points, Sequence) or isinstance(raw_points, (str, bytes)):
            raise ValueError("曲线 points 必须是时间点数组")
        points: List[Dict[str, float]] = []
        seen: set[float] = set()
        for raw_point in raw_points:
            if not (type(raw_point) is dict or isinstance(raw_point, Mapping)):
                raise ValueError("曲线时间点必须包含 minute 和 value")
            minute = _to_float(raw_point.get("minute"), None)
            value = _to_float(raw_point.get("value"), None)
            if minute is None or value is None or not math.isfinite(minute) or not math.isfinite(value):
                raise ValueError("曲线 minute 和 value 必须是有限数值")
            minute = float(minute)
            if minute < 0:
                raise ValueError("曲线 minute 不能为负数")
            if minute in seen:
                raise ValueError(f"曲线存在重复时刻：{minute:g}")
            seen.add(minute)
            points.append({"minute": minute, "value": float(value)})
        points.sort(key=lambda point: point["minute"])
        return points

    @staticmethod
    def _store_external_curve_points(
        curves: Dict[str, Any],
        item: Mapping[str, Any],
        points: Sequence[Mapping[str, float]],
    ) -> None:
        kind = str(item.get("storage_kind", ""))
        storage_key = str(item.get("storage_key", item.get("key", "")))
        if kind == "weather":
            weather = curves.setdefault("weather", [])
            if not isinstance(weather, list):
                weather = []
                curves["weather"] = weather
            field = str(item["set_type"])
            for row in weather:
                if isinstance(row, dict):
                    row.pop(field, None)
            rows_by_minute = {
                float(_to_float(row.get("minute"), index) or 0.0): row
                for index, row in enumerate(weather)
                if isinstance(row, dict)
            }
            for point in points:
                minute = float(point["minute"])
                row = rows_by_minute.get(minute)
                if row is None:
                    row = {"minute": minute}
                    weather.append(row)
                    rows_by_minute[minute] = row
                row[field] = float(point["value"])
            weather.sort(key=lambda row: float(_to_float(row.get("minute"), 0.0) or 0.0))
            return
        if kind == "load":
            loads = curves.setdefault("loads", {})
            if not isinstance(loads, dict):
                loads = {}
                curves["loads"] = loads
            field = "p_kw" if item.get("set_type") == "p_set" else str(item["set_type"])
            loads[storage_key] = [
                {"minute": float(point["minute"]), field: float(point["value"])}
                for point in points
            ]
            return
        sources = curves.setdefault("sources", [])
        if not isinstance(sources, list):
            sources = []
            curves["sources"] = sources
        target = next(
            (
                source for source in sources
                if isinstance(source, dict) and str(source.get("key", "")) == storage_key
            ),
            None,
        )
        if target is None:
            target = {
                key: item.get(key)
                for key in ("key", "dev_type", "dev_name", "name", "set_type", "family", "unit")
            }
            sources.append(target)
        target["points"] = [
            {"minute": float(point["minute"]), "value": float(point["value"])}
            for point in points
        ]

    def external_curves_update(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock, self.curves_lock:
            raw_updates = payload.get("curves")
            if not isinstance(raw_updates, Sequence) or isinstance(raw_updates, (str, bytes)) or not raw_updates:
                raise ValueError("curves 必须是非空曲线更新数组")
            staged = copy.deepcopy(self.curves)
            by_key = {str(item["key"]): item for item in self._external_curve_catalog(staged)}
            prepared = []
            seen_keys: set[str] = set()
            for raw_item in raw_updates:
                if not (type(raw_item) is dict or isinstance(raw_item, Mapping)):
                    raise ValueError("curves 中的每一项必须是曲线对象")
                item = self._resolve_external_curve(raw_item, by_key)
                key = str(item["key"])
                if key in seen_keys:
                    raise ValueError(f"同一批更新中曲线重复：{key}")
                seen_keys.add(key)
                start, end = self._external_curve_range(raw_item, payload)
                points = self._validated_external_curve_points(raw_item.get("points"))
                if start is not None and any(point["minute"] < start or point["minute"] > end for point in points):
                    raise ValueError(f"曲线 {key} 的更新点超出指定时间范围")
                prepared.append((item, points, start, end))

            results = []
            for item, incoming, start, end in prepared:
                points = list(incoming)
                if start is not None:
                    points = [
                        point for point in self._external_curve_public_item(item)["points"]
                        if point["minute"] < start or point["minute"] > end
                    ] + points
                    points.sort(key=lambda point: point["minute"])
                self._store_external_curve_points(staged, item, points)
                result = {
                    "key": item["key"],
                    "update_scope": "time_range" if start is not None else "whole_curve",
                    "point_count": len(points),
                }
                if start is not None:
                    result.update({"start_minute": start, "end_minute": end})
                results.append(result)

            atomic_write_text(
                self.curves_file,
                json.dumps(staged, ensure_ascii=False, indent=2) + "\n",
            )
            self.curves = staged
            self._curve_revision += 1
            final_catalog = {str(item["key"]): item for item in self._external_curve_catalog()}
            return {
                **self._external_response_metadata(),
                "updated_count": len(results),
                "results": results,
                "curves": [
                    self._external_curve_public_item(final_catalog[str(item["key"])])
                    for item, _points, _start, _end in prepared
                ],
            }

    def _ensure_weather_curve_points(self, point_count: int, step_minutes: float) -> List[Dict[str, Any]]:
        weather = self.curves.get("weather", [])
        if not isinstance(weather, list):
            weather = []
        defaults = dict(DEFAULT_WEATHER)
        while len(weather) < point_count:
            index = len(weather)
            weather.append({"minute": index * step_minutes, **defaults})
        if len(weather) > point_count:
            del weather[point_count:]
        for index, point in enumerate(weather):
            if not isinstance(point, dict):
                point = {}
                weather[index] = point
            point["minute"] = _to_float(point.get("minute"), index * step_minutes) or index * step_minutes
            for key, value in defaults.items():
                point.setdefault(key, value)
        self.curves["weather"] = weather
        return weather

    @staticmethod
    def _load_curve_value_field(load_name: str) -> str:
        prefix, separator, _suffix = str(load_name).partition(":")
        if separator:
            if prefix == "HydroLoad":
                return "flow_set"
            if prefix == "HeatLoad":
                return "heat_power"
        return "p_kw"

    def _ensure_load_curve_points(
        self,
        load_name: str,
        point_count: int,
        step_minutes: float,
        *,
        value_field: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        field = value_field or self._load_curve_value_field(load_name)
        default_value = DEFAULT_WEATHER["load_kw"] if field == "p_kw" else 0.0
        loads = self.curves.get("loads")
        if not isinstance(loads, dict):
            loads = {}
            self.curves["loads"] = loads
        points = loads.get(load_name)
        if not isinstance(points, list):
            points = []
            loads[load_name] = points
        while len(points) < point_count:
            index = len(points)
            points.append({"minute": index * step_minutes, field: default_value})
        if len(points) > point_count:
            del points[point_count:]
        for index, point in enumerate(points):
            if not isinstance(point, dict):
                point = {field: point}
                points[index] = point
            parsed_minute = _to_float(point.get("minute"), None)
            point["minute"] = index * step_minutes if parsed_minute is None else float(parsed_minute)
            point.setdefault(field, default_value)
        return points

    def _ensure_source_curve_points(
        self,
        curve_key: str,
        point_count: int,
        step_minutes: float,
    ) -> Optional[List[Dict[str, Any]]]:
        catalog_item = source_curve_catalog_by_key(self.definition_snapshot.model_book).get(curve_key)
        if catalog_item is None:
            return None
        sources = self.curves.get("sources")
        if not isinstance(sources, list):
            sources = []
            self.curves["sources"] = sources
        item = next(
            (
                item
                for item in sources
                if isinstance(item, dict) and str(item.get("key", "")) == curve_key
            ),
            None,
        )
        if item is None:
            item = {**catalog_item, "points": []}
            sources.append(item)
        else:
            item.update(catalog_item)
        points = item.get("points")
        if not isinstance(points, list):
            points = []
            item["points"] = points
        fallback = float(catalog_item.get("default_value", 0.0) or 0.0)
        while len(points) < point_count:
            index = len(points)
            points.append({"minute": index * step_minutes, "value": fallback})
        if len(points) > point_count:
            del points[point_count:]
        for index, point in enumerate(points):
            if not isinstance(point, dict):
                point = {"value": point}
                points[index] = point
            point["minute"] = _to_float(point.get("minute"), index * step_minutes) or 0.0
            point.setdefault("value", fallback)
        return points

    def update_curve_series(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock, self.curves_lock:
            current_mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
            mode = _normalize_simulation_mode(payload.get("mode", current_mode), current_mode)
            if mode != current_mode and self.clock.state != "stopped":
                raise ValueError("仿真运行过程中不能切换仿真模式，请先停止仿真")
            default_step = _simulation_mode_curve_step_minutes(mode)
            step_minutes = float(
                _to_float(payload.get("time_step_minutes"), self.curves.get("time_step_minutes", default_step))
                or default_step
            )
            if step_minutes <= 0:
                step_minutes = default_step
            default_point_count = _simulation_mode_point_count(mode)
            point_count = int(
                _to_float(payload.get("point_count"), self.curves.get("point_count", default_point_count)) or 0
            )
            raw_series = payload.get("series", {})
            if not (type(raw_series) is dict or isinstance(raw_series, Mapping)):
                raw_series = {}
            for values in raw_series.values():
                if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                    point_count = max(point_count, len(values))
            point_count = point_count or default_point_count
            self.curves["mode"] = mode
            self.curves["time_step_minutes"] = step_minutes
            self.curves["point_count"] = point_count
            updated: List[str] = []
            for key, values in raw_series.items():
                curve_key = str(key).strip()
                if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                    continue
                if curve_key in ("wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c"):
                    weather = self._ensure_weather_curve_points(point_count, step_minutes)
                    for index, value in enumerate(values[:point_count]):
                        weather[index][curve_key] = _to_float(value, 0.0) or 0.0
                    updated.append(curve_key)
                elif curve_key.startswith("load:"):
                    load_name = curve_key.replace("load:", "", 1)
                    if not load_name:
                        continue
                    value_field = self._load_curve_value_field(load_name)
                    points = self._ensure_load_curve_points(
                        load_name,
                        point_count,
                        step_minutes,
                        value_field=value_field,
                    )
                    for index, value in enumerate(values[:point_count]):
                        points[index][value_field] = _to_float(value, 0.0) or 0.0
                    updated.append(curve_key)
                elif curve_key.startswith("source:"):
                    points = self._ensure_source_curve_points(curve_key, point_count, step_minutes)
                    if points is None:
                        continue
                    for index, value in enumerate(values[:point_count]):
                        points[index]["value"] = _to_float(value, 0.0) or 0.0
                    updated.append(curve_key)
            if mode != current_mode:
                self._apply_mode_default_clock_speed(mode, persist=True)
                self.clock.absolute_minute = _align_minute_to_step(
                    self.clock.absolute_minute,
                    _effective_clock_step(self.clock.step_minutes, self.clock.speed),
                )
            self.clock.minute = self.clock.absolute_minute % 1440.0
            self.clock.updated_at = time.time()
            _write_json(self.curves_file, self.curves)
            self._curve_revision += 1
            return {
                "updated": updated,
                "mode": mode,
                "time_step_minutes": step_minutes,
                "point_count": point_count,
            }

    def _interpolate_curve_series(
        self,
        points: Sequence[Mapping[str, Any]],
        minute: int | float,
        key: str,
        default: Optional[float],
        *,
        period_minutes: float,
    ) -> Optional[float]:
        if self._compiled_curve_revision != self._curve_revision:
            self._compiled_curve_revision = self._curve_revision
            self._compiled_curve_series_cache.clear()
            self._load_curve_target_cache_key = None
            self._load_curve_target_cache_value = {}
        cache_key = (id(points), str(key), float(period_minutes))
        series = self._compiled_curve_series_cache.get(cache_key)
        if series is None:
            series = _compile_interpolation_series(points, key, period_minutes)
            self._compiled_curve_series_cache[cache_key] = series
        return _interpolate_compiled_series(
            series,
            minute,
            default,
            period_minutes=period_minutes,
        )

    def _load_curve_targets(self) -> Dict[str, Tuple[int, Tuple[Tuple[str, str], ...]]]:
        definition_revision = self.definition_snapshot.revision
        cache_key = (definition_revision, self._curve_revision)
        if self._load_curve_target_cache_key == cache_key:
            return self._load_curve_target_cache_value

        model_book = self.definition_snapshot.model_book
        model_targets: Dict[str, List[Tuple[str, str]]] = {}
        for block_name in ("ACLoad", "DCLoad"):
            block = model_book.data.get(block_name)
            if block is None:
                continue
            for model_row in block.data:
                name = str(model_row.get("name", "")).strip()
                if name:
                    model_targets.setdefault(name, []).append((block_name, name))

        resolved: Dict[str, Tuple[int, Tuple[Tuple[str, str], ...]]] = {}
        loads = self.curves.get("loads", {})
        if (type(loads) is dict or isinstance(loads, Mapping)):
            for raw_name in loads:
                curve_name = str(raw_name).strip()
                if not curve_name:
                    continue
                explicit_type = ""
                model_name = curve_name
                prefix, separator, suffix = curve_name.partition(":")
                if separator and prefix in {"ACLoad", "DCLoad"}:
                    explicit_type = prefix
                    model_name = suffix.strip()
                matches = model_targets.get(model_name, [])
                if explicit_type:
                    matches = [match for match in matches if match[0] == explicit_type]
                resolved[curve_name] = (
                    1 if explicit_type else 0,
                    tuple(matches),
                )
        self._load_curve_target_cache_key = cache_key
        self._load_curve_target_cache_value = resolved
        return resolved

    def curve_boundary(self, absolute_minute: Optional[int | float] = None) -> Dict[str, Any]:
        target_minute = float(
            _to_float(
                self.clock.absolute_minute if absolute_minute is None else absolute_minute,
                0.0,
            )
            or 0.0
        )
        cache_key = (self._curve_revision, target_minute, id(self.curves))
        if (
            cache_key == self._curve_boundary_cache_key
            and self._curve_boundary_cache_value is not None
        ):
            return self._curve_boundary_cache_value

        curve_mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
        default_step = _simulation_mode_curve_step_minutes(curve_mode)
        default_point_count = _simulation_mode_point_count(curve_mode)
        step_minutes = float(_to_float(self.curves.get("time_step_minutes"), default_step) or default_step)
        period_minutes = _simulation_mode_duration_minutes(curve_mode)
        weather = self.curves.get("weather", [])
        if not isinstance(weather, Sequence) or isinstance(weather, (str, bytes)):
            weather = []
        point_count = int(_to_float(self.curves.get("point_count"), 0) or 0)
        if not point_count:
            point_count = len(weather)
        index = max(0, self._curve_point_index(target_minute, period_minutes) - 1)
        point = {
            key: self._interpolate_curve_series(
                weather,
                target_minute,
                key,
                default,
                period_minutes=period_minutes,
            )
            for key, default in self.weather_defaults.items()
            if key != "load_kw"
        }
        loads = self.curves.get("loads", {})
        load_total = 0.0
        load_count = 0
        if (type(loads) is dict or isinstance(loads, Mapping)):
            for load_name, points in loads.items():
                if self._load_curve_value_field(str(load_name)) != "p_kw":
                    # HydroLoad（Nm3/h）与 HeatLoad（kW热）不混入电负荷总功率统计。
                    continue
                if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
                    continue
                value = self._interpolate_curve_series(
                    points,
                    target_minute,
                    "p_kw",
                    float("nan"),
                    period_minutes=period_minutes,
                )
                if value == value:
                    load_total += value
                    load_count += 1
        result = {
            "mode": curve_mode,
            "time_step_minutes": step_minutes,
            "point_count": point_count or default_point_count,
            "target_minute": target_minute,
            "index": index,
            "point": point,
            "load_total": load_total,
            "load_count": load_count,
        }
        self._curve_boundary_cache_key = cache_key
        self._curve_boundary_cache_value = result
        return result
