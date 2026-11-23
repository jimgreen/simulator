"""PolarMicrogridSimulator 拆分模块：模型/设备/量测定义编辑、SVG 图形与潮流画像摘要能力。"""

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


class _DefinitionsMixin:
    """模型/设备/量测定义编辑、SVG 图形与潮流画像摘要能力。"""

    @contextmanager
    def _active_definition_update_guard(self):
        # Definition edits must not wait for a running kernel that owns service.lock.
        # The lifecycle lock still makes retirement versus memory/WAL/E publication atomic.
        with self.definition_update_lock:
            with self._service_instance_lifecycle_lock:
                if not self._service_instance_active_locked():
                    raise ServiceInstanceRetiredError("定义修改请求所属模型生命周期已失效或已退休。")
                yield

    def _ensure_runtime_stat_book(self) -> None:
        book = self.runtime_stat_book
        for name, headers in STAT_HEADERS.items():
            _ensure_block(book, name, headers)
        simu_loop.ensure_closed_status_rows_book(book)
        simu_loop.ensure_hydrogen_storage_state_rows_book(
            book,
            self.definition_snapshot.model_book,
        )
        self.runtime_stat_book = book

    @staticmethod
    def _set_value_from_book(book: EBook, key: Tuple[str, str, str]) -> Optional[float]:
        block = book.data.get("SetValue")
        if block is None:
            return None
        row = _find_set_row(block, *key)
        if row is None:
            return None
        value = _to_float(row.get("set_value"), None)
        return float(value) if value is not None and math.isfinite(value) else None

    def _merge_execution_runtime_stat_book(self, execution_book: EBook) -> None:
        incoming_cb = execution_book.data.get("CbOpenStat")
        if incoming_cb is not None:
            current_cb = _ensure_block(
                self.runtime_stat_book,
                "CbOpenStat",
                STAT_HEADERS["CbOpenStat"],
            )
            simu_loop.ensure_closed_status_rows_book(self.runtime_stat_book)
            for incoming_row in incoming_cb.data:
                current_row = _find_dev_row(
                    current_cb,
                    str(incoming_row.get("dev_type", "")),
                    _dev_name(incoming_row),
                )
                if current_row is None:
                    continue
                actual = simu_loop.closed_status_value(incoming_row, "")
                if actual == "":
                    continue
                current_row["closed_status"] = _number_text(actual)
                current_row["status"] = _number_text(actual)
        incoming_storage = execution_book.data.get("StorageSoc") or execution_book.data.get("StorageStatus")
        if incoming_storage is not None:
            current_storage = _ensure_block(self.runtime_stat_book, "StorageSoc", STAT_HEADERS["StorageSoc"])
            current_storage.data = self._merge_runtime_storage_soc(
                current_storage.data,
                incoming_storage.data,
            )
        incoming_hydrogen = execution_book.data.get(simu_loop.HYDROGEN_STORAGE_STATE_BLOCK)
        if incoming_hydrogen is not None:
            current_hydrogen = _ensure_block(
                self.runtime_stat_book,
                simu_loop.HYDROGEN_STORAGE_STATE_BLOCK,
                simu_loop.HYDROGEN_STORAGE_STATE_HEADERS,
            )
            current_hydrogen.data = self._merge_runtime_hydrogen_storage_state(
                current_hydrogen.data,
                incoming_hydrogen.data,
            )

    def _device_flow_lines(self, real_measurements: Sequence[Mapping[str, Any]]) -> List[str]:
        grouped: Dict[Tuple[str, str], List[str]] = {}
        for item in real_measurements:
            dev_type = str(item.get("dev_type", ""))
            dev_name = str(item.get("dev_name", ""))
            meas_type = str(item.get("meas_type", ""))
            if not dev_type or not dev_name or not meas_type:
                continue
            value = _number_text(item.get("value", ""))
            valid_flag = "" if int(_to_float(item.get("valid"), 1) or 0) == 1 else "(无效)"
            grouped.setdefault((dev_type, dev_name), []).append(f"{meas_type}={value}{valid_flag}")
        return [
            f"{dev_type}.{dev_name}: {', '.join(values)}"
            for (dev_type, dev_name), values in grouped.items()
        ]

    def _canonical_power_device_name(self, category: str, dev_name: str) -> str:
        return dev_name

    def _latest_power_summary(
        self,
        measurements: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> Dict[str, Any]:
        cache_key: Optional[Tuple[Any, ...]] = None
        if measurements is self.latest_measurements:
            cache_key = (
                id(measurements),
                self.definition_snapshot.revision,
                self.clock.step_count,
                float(self.clock.absolute_minute),
                id(self.runtime_stat_book),
                id(self.latest_model_book),
                id(self.latest_device_states),
                id(self.weather_book),
            )
            if (
                cache_key == self._latest_power_summary_cache_key
                and self._latest_power_summary_cache_value is not None
            ):
                return self._latest_power_summary_cache_value

        for source in ("scada", "real"):
            rows = measurements.get(source, [])
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                continue
            summary = self._power_flow_summary(rows)
            if any(summary["counts"].values()):
                result = {"source": source, **summary}
                break
        else:
            result = {"source": "", **self._power_flow_summary([])}
        if cache_key is not None:
            self._latest_power_summary_cache_key = cache_key
            self._latest_power_summary_cache_value = result
        return result

    def _signal_definition_paths(self) -> List[Path]:
        return []

    def devices(self) -> List[Dict[str, Any]]:
        with self.lock:
            return self._devices_locked()

    def _devices_locked(self) -> List[Dict[str, Any]]:
        definition_snapshot = self.definition_snapshot
        model_book = definition_snapshot.model_book
        run_stats, cb_status, set_values, soc_values = self._stat_maps()
        cb_status_set = self._closed_status_set_map()
        resources_by_key = resources_by_device_key(model_book)
        coupling_bindings = energy_coupling_control_bindings(model_book)
        devices: List[Dict[str, Any]] = []
        device_blocks = (
            "ACGenerator",
            "DCGenerator",
            "ACLoad",
            "DCLoad",
            "DCDCConverter",
            "ACDCConverter",
            "DCACConverter",
            "ACACConverter",
            "ACBreak",
            "DCBreak",
            "ACSwitch",
            "DCSwitch",
            "HydroSource",
            "HydroLoad",
            "HydroStorage",
            "AcE2Hydro",
            "DcE2Hydro",
            "Hydro2AcE",
            "Hydro2DcE",
        )
        for dev_type in device_blocks:
            block = model_book.data.get(dev_type)
            if block is None:
                continue
            for row in block.data:
                name = str(row.get("name", ""))
                key = (dev_type, name)
                terminal_domains = terminal_domains_from_block(dev_type)
                resource = resources_by_key.get(key)
                set_types = []
                for column in (
                    "p_set",
                    "q_set",
                    "v_set",
                    "p_ac_set",
                    "q_ac_set",
                    "v_ac_set",
                    "p_dc_set",
                    "v_dc_set",
                    "pv0",
                    "qv0",
                    "flow_set",
                ):
                    if column in block.header_list:
                        set_types.append(column)
                closed_status_set = int(
                    _to_float(
                        cb_status_set.get(
                            key,
                            row.get("closed_status_set", row.get("status", 1)),
                        ),
                        1,
                    )
                    or 0
                )
                closed_status = int(
                    _to_float(
                        cb_status.get(
                            key,
                            row.get("closed_status", row.get("status", 1)),
                        ),
                        1,
                    )
                    or 0
                )
                devices.append(
                    {
                        "dev_type": dev_type,
                        "dev_name": name,
                        "model_block": dev_type,
                        "device_family": device_family_from_block(dev_type),
                        "terminal_domains": list(terminal_domains),
                        "resource_technology": resource.technology if resource else "",
                        "run_stat": int(_to_float(run_stats.get(key, row.get("run_stat", 1)), 1) or 0),
                        "closed_status_set": closed_status_set,
                        "closed_status": closed_status,
                        # Periodic compact transport retains ``status`` as a
                        # compatibility alias for the calculated actual value.
                        "status": closed_status,
                        "mode": (
                            converter_control_mode(row)
                            if set(terminal_domains) == {"AC", "DC"}
                            else (
                                row.get("control_type")
                                or row.get("ac_control_type")
                                or row.get("dc_control_type")
                                or row.get("mode", "")
                            )
                        ),
                        "set_types": set_types,
                        "set_values": set_values.get(key, {}),
                        "control_bindings": list(coupling_bindings.get(key, ())),
                        "raw": {header: row.get(header, "") for header in block.header_list},
                    }
                )
        devices_by_key = {
            (str(device.get("dev_type", "")), str(device.get("dev_name", ""))): device
            for device in devices
        }
        def storage_soc_value(row: Mapping[str, Any], default: float = 0.0) -> float:
            value: Any = ""
            for column in ("state_of_charge", "soc_curr", "soc_cur", "soc"):
                if row.get(column, "") != "":
                    value = row.get(column)
                    break
            text = str(value or "").strip()
            if not text:
                return default
            try:
                return ratio_parameter_number(
                    "state_of_charge",
                    value,
                    legacy_percent_points=True,
                )
            except ValueError:
                return default
        for resource in structured_resources(model_book):
            if resource.technology != "storage":
                continue
            key = resource.device_key
            device = devices_by_key.get(key)
            if device is None:
                continue
            raw = dict(resource.parameter)
            soc_value = soc_values.get(
                key,
                storage_soc_value(resource.parameter),
            )
            device["soc_curr"] = soc_value
            device["raw"] = raw | dict(device.get("raw", {})) | {"soc_curr": soc_value}
            for set_type in ("p_set", "v_set"):
                if set_type not in device["set_types"]:
                    device["set_types"].append(set_type)
        return devices

    def device_states(self) -> List[Dict[str, Any]]:
        """Return the compact state needed by the live SVG diagram."""
        with self.lock:
            return self._device_states_locked()

    def _device_states_locked(self) -> List[Dict[str, Any]]:
        definition_snapshot = self.definition_snapshot
        model_blocks_by_key = {
            (str(block_name), str(row.get("name", "")).strip()): str(block_name)
            for block_name, block in definition_snapshot.model_book.data.items()
            for row in getattr(block, "data", [])
            if str(row.get("name", "")).strip()
        }
        states: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for item in self.latest_device_states:
            dev_type = str(item.get("dev_type", "")).strip()
            dev_name = str(item.get("dev_name", item.get("name", ""))).strip()
            if not dev_type or not dev_name:
                continue
            states[(dev_type, dev_name)] = {
                "dev_type": dev_type,
                "dev_name": dev_name,
                "model_block": str(item.get("model_block", "")).strip()
                or model_blocks_by_key.get((dev_type, dev_name), ""),
                "run_stat": int(_to_float(item.get("run_stat"), 1) or 0),
                "dead_island": bool(item.get("dead_island", False)),
            }

        run_stats, _cb_status, _set_values, _soc_values = self._stat_maps()
        for dev_type, block in definition_snapshot.model_book.data.items():
            if "name" not in block.header_list or "run_stat" not in block.header_list:
                continue
            for row in block.data:
                dev_name = str(row.get("name", "")).strip()
                if not dev_name:
                    continue
                key = (str(dev_type), dev_name)
                run_stat = int(_to_float(run_stats.get(key, row.get("run_stat", 1)), 1) or 0)
                state = states.setdefault(
                    key,
                    {
                        "dev_type": key[0],
                        "dev_name": key[1],
                        "model_block": str(dev_type),
                        "run_stat": run_stat,
                        "dead_island": False,
                    },
                )
                state["run_stat"] = run_stat
                if run_stat == 0:
                    state["dead_island"] = False

        for key, value in run_stats.items():
            dev_type, dev_name = str(key[0]).strip(), str(key[1]).strip()
            if not dev_type or not dev_name:
                continue
            run_stat = int(_to_float(value, 1) or 0)
            state = states.setdefault(
                (dev_type, dev_name),
                {
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "model_block": model_blocks_by_key.get((dev_type, dev_name), ""),
                    "run_stat": run_stat,
                    "dead_island": False,
                },
            )
            state["run_stat"] = run_stat
            if run_stat == 0:
                state["dead_island"] = False

        return [states[key] for key in sorted(states)]

    def device_runtime_frame(self) -> Dict[str, Any]:
        with self.lock:
            cache_key = (
                self.definition_snapshot.revision,
                self.clock.step_count,
                id(self.runtime_stat_book),
                id(self.latest_model_book),
                id(self.latest_device_states),
                id(self.mode_book),
                id(self.yt_ctrl_book),
                tuple(
                    (
                        str(item.get("dev_type", "")),
                        str(item.get("dev_name", item.get("name", ""))),
                        item.get("run_stat"),
                        bool(item.get("dead_island", False)),
                    )
                    for item in self.latest_device_states
                    if (type(item) is dict or isinstance(item, Mapping))
                ),
            )
            if (
                cache_key == self._device_runtime_frame_cache_key
                and self._device_runtime_frame_cache_value is not None
            ):
                return self._device_runtime_frame_cache_value
            frame = compact_device_runtime_frame(
                self.devices(),
                self.device_states(),
                definition_revision=self.definition_snapshot.revision,
            )
            self._device_runtime_frame_cache_key = cache_key
            self._device_runtime_frame_cache_value = frame
            return frame

    def _definition_row(self, block: EBlock, row_key: Any) -> Dict[str, Any]:
        if not (type(row_key) is dict or isinstance(row_key, Mapping)):
            raise ValueError("row_key must be an object")
        name = str(row_key.get("name", "")).strip()
        idx = str(row_key.get("idx", "")).strip()
        if not name and not idx:
            raise ValueError("row_key requires name or idx")

        matches: List[Dict[str, Any]] = []
        for item in block.data:
            if name:
                if "name" not in block.header_list or str(item.get("name", "")) != name:
                    continue
            if idx:
                if "idx" not in block.header_list or str(item.get("idx", "")) != idx:
                    continue
            matches.append(item)
        if not matches:
            identity = name or idx
            raise ValueError(f"Unknown definition row in {block.name}: {identity}")
        if len(matches) != 1:
            identity = name or idx
            raise ValueError(f"Definition row identity must be unique in {block.name}: {identity}")
        return matches[0]

    def _write_manual_definition_changes_unlocked(
        self,
        *,
        accepted_source_fingerprints: Optional[Sequence[str]] = None,
    ) -> None:
        if not self._manual_definition_changes:
            self.manual_definition_changes_file.unlink(missing_ok=True)
            return
        self.manual_definition_changes_file.parent.mkdir(parents=True, exist_ok=True)
        payload = self._manual_definition_changes_payload_unlocked(
            accepted_source_fingerprints=accepted_source_fingerprints,
        )
        atomic_write_text(
            self.manual_definition_changes_file,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )

    def _manual_definition_source_fingerprint(
        self,
        text_overrides: Optional[Mapping[str, str]] = None,
    ) -> str:
        overrides = text_overrides or {}
        digest = hashlib.sha256()
        for file_key in ("model", "meas", "stat", "control"):
            path = self.source_files[file_key]
            digest.update(file_key.encode("ascii"))
            digest.update(b"\0")
            if file_key in overrides:
                digest.update(str(overrides[file_key]).encode("utf-8"))
            else:
                try:
                    digest.update(path.read_bytes())
                except OSError:
                    digest.update(b"<missing>")
            digest.update(b"\0")
        return digest.hexdigest()

    def _write_ahead_manual_definition_changes_unlocked(
        self,
    ) -> None:
        self._write_manual_definition_changes_unlocked()

    def _clear_manual_definition_changes_unlocked(self) -> int:
        cleared = len(self._manual_definition_changes)
        self._manual_definition_changes = {}
        self.manual_definition_changes_file.unlink(missing_ok=True)
        return cleared

    def clear_manual_definition_changes(self) -> Dict[str, Any]:
        with self._active_definition_update_guard():
            cleared = self._clear_manual_definition_changes_unlocked()
            self._rebuild_effective_definitions_from_source_unlocked()
            return {
                **self._manual_definition_changes_payload_unlocked(),
                "cleared_count": cleared,
            }

    def _archive_manual_definition_changes_unlocked(self) -> Optional[Path]:
        if not self.manual_definition_changes_file.exists():
            return None
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        archived = self.runtime_dir / f"manual_overrides.stale.{timestamp}.json"
        try:
            self.manual_definition_changes_file.replace(archived)
        except OSError:
            self.manual_definition_changes_file.unlink(missing_ok=True)
            return None
        return archived

    def _source_definition_state_unlocked(
        self,
    ) -> Tuple[DefinitionSnapshot, EBook, EBook]:
        model_book = _load_book(self.source_files["model"])
        source_stat_book = _load_book(self.source_files["stat"])
        control_book = _load_book(
            self.source_files["control"]
            if self.source_files["control"].exists()
            else self.source_files["stat"]
        )
        source_stat_book, control_book = self._reconcile_source_dcp_controls_unlocked(
            model_book,
            source_stat_book,
            control_book,
        )
        simu_loop.ensure_closed_status_rows_book(source_stat_book)
        simu_loop.ensure_closed_status_rows_book(control_book)
        dev_define_book = simu_loop._capability_define_book(
            model_book,
            self._legacy_dev_define_file(),
        )
        try:
            measurement_before, measurement_rows, measurement_after = parse_measurement_rows(
                self.source_files["meas"]
            )
        except Exception:
            measurement_before, measurement_rows, measurement_after = [], [], []
        measurement_rows, _added_measurements = _reconcile_hydrogen_inline_flow_measurements(
            model_book,
            measurement_rows,
        )
        snapshot = DefinitionSnapshot(
            revision=self.definition_snapshot.revision + 1,
            model_book=model_book,
            dev_define_book=dev_define_book,
            measurement_before=tuple(measurement_before),
            measurement_rows=tuple(tuple(row) for row in measurement_rows),
            measurement_after=tuple(measurement_after),
            measurement_median_deviations=self._read_source_measurement_median_deviations(
                measurement_rows
            ),
        )
        return snapshot, source_stat_book, control_book

    def _rebuild_effective_definitions_from_source_unlocked(
        self,
        *,
        materialize_controls: bool = True,
    ) -> DefinitionSnapshot:
        source_snapshot, source_stat_book, control_book = (
            self._source_definition_state_unlocked()
        )
        old_runtime_stat_book = self.runtime_stat_book
        self.source_stat_book = source_stat_book
        self.control_book = control_book
        items = list(self._manual_definition_changes.values())
        next_snapshot, _kinds = self._snapshot_with_manual_change_values_unlocked(
            source_snapshot,
            items,
        )
        self._apply_manual_runtime_control_overrides_unlocked(items)
        self._apply_manual_measurement_status_overrides_unlocked(next_snapshot, items)
        self._publish_definition_snapshot(next_snapshot)

        # Rebuild the effective control baseline while preserving the live SOC
        # rows.  Active automatic/manual commands are then layered on top.
        self.runtime_stat_book = old_runtime_stat_book
        self.runtime_stat_book = self._base_stat_book_for_controls()
        self._ensure_runtime_stat_book()
        if materialize_controls:
            self._materialize_active_control_commands(self.clock.absolute_minute)
            self._apply_device_faults(self.clock.minute, self.clock.absolute_minute)
        return next_snapshot

    def manual_definition_changes(self) -> Dict[str, Any]:
        with self.definition_update_lock:
            return self._manual_definition_changes_payload_unlocked()

    def retry_manual_definition_changes(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self._active_definition_update_guard():
            current = self.definition_snapshot
            require_definition_revision(payload, current.revision)
            raw_change_ids = payload.get("change_ids")
            if raw_change_ids is None:
                change_ids = [
                    change_id
                    for change_id, item in self._manual_definition_changes.items()
                    if not bool(item.get("persisted", False))
                ]
            else:
                if not isinstance(raw_change_ids, Sequence) or isinstance(raw_change_ids, (str, bytes)):
                    raise ValueError("change_ids must be an array")
                change_ids = list(
                    dict.fromkeys(
                        str(change_id).strip()
                        for change_id in raw_change_ids
                        if str(change_id).strip()
                    )
                )
            missing = [change_id for change_id in change_ids if change_id not in self._manual_definition_changes]
            if missing:
                raise ValueError(f"Unknown manual definition change: {missing[0]}")
            selected = [
                self._manual_definition_changes[change_id]
                for change_id in change_ids
                if not bool(self._manual_definition_changes[change_id].get("persisted", False))
            ]
            if not selected:
                result = self._manual_definition_changes_payload_unlocked()
                result.update(
                    {
                        "retried_count": 0,
                        "persisted_count": 0,
                        "memory_updated": False,
                        "persisted": True,
                        "change_record_persisted": True,
                    }
                )
                return result

            self._rebuild_effective_definitions_from_source_unlocked()
            original_changes = {
                change_id: dict(item)
                for change_id, item in self._manual_definition_changes.items()
            }
            persisted_count = 0
            for item in selected:
                change_id = str(item.get("id", ""))
                active_item = self._manual_definition_changes.get(change_id)
                if active_item is None:
                    continue
                self._set_manual_change_sync_state_unlocked(
                    active_item,
                    persisted=True,
                    increment_retry=True,
                )
                persisted_count += 1
                if self._manual_change_values_equal(
                    active_item.get("current_value", ""),
                    active_item.get("default_value", ""),
                ):
                    self._manual_definition_changes.pop(change_id, None)

            try:
                self._write_manual_definition_changes_unlocked()
            except OSError as exc:
                self._manual_definition_changes = original_changes
                error = f"人工覆盖层保存失败，请重试: {exc}"
                for item in selected:
                    active_item = self._manual_definition_changes.get(str(item.get("id", "")))
                    if active_item is not None:
                        self._set_manual_change_sync_state_unlocked(
                            active_item,
                            persisted=False,
                            error=error,
                            increment_retry=True,
                        )
                result = self._manual_definition_changes_payload_unlocked()
                result.update(
                    {
                        "retried_count": len(selected),
                        "persisted_count": 0,
                        "memory_updated": True,
                        "persisted": False,
                        "change_record_persisted": False,
                        "static_meta": self.static_meta(),
                        "warning": error,
                    }
                )
                return result

            result = self._manual_definition_changes_payload_unlocked()
            result.update(
                {
                    "retried_count": len(selected),
                    "persisted_count": persisted_count,
                    "memory_updated": True,
                    "persisted": True,
                    "change_record_persisted": True,
                    "static_meta": self.static_meta(),
                }
            )
            return result

    def _record_device_manual_changes_unlocked(
        self,
        block_name: str,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        changed_fields: Sequence[str],
        *,
        persisted: bool,
        persistence_error: str = "",
    ) -> None:
        row_key = {
            key: self._manual_change_value_text(after.get(key, ""))
            for key in ("idx", "name")
            if self._manual_change_value_text(after.get(key, "")).strip()
        }
        identity = {"block_name": block_name, **row_key}
        object_name = str(after.get("name", "")).strip() or f"{block_name}_{after.get('idx', '')}"
        now = _now_text()
        for field_name in changed_fields:
            change_id = self._manual_change_id("device", identity, field_name)
            existing = self._manual_definition_changes.get(change_id, {})
            default_value = self._manual_change_value_text(
                existing.get("default_value", before.get(field_name, ""))
            )
            current_value = self._manual_change_value_text(after.get(field_name, ""))
            if persisted and self._manual_change_values_equal(current_value, default_value):
                self._manual_definition_changes.pop(change_id, None)
                continue
            item = {
                **existing,
                "id": change_id,
                "kind": "device",
                "change_type": "设备参数",
                "object_type": block_name,
                "object_name": object_name,
                "object_id": str(after.get("idx", "")),
                "object_label": f"{block_name} · {object_name}",
                "block_name": block_name,
                "row_key": row_key,
                "field": field_name,
                "field_label": field_name,
                "default_value": default_value,
                "current_value": current_value,
                "modified_at": now,
                "source_file": "model.e",
            }
            self._set_manual_change_sync_state_unlocked(
                item,
                persisted=persisted,
                error=persistence_error,
            )
            self._manual_definition_changes[change_id] = item

    @staticmethod
    def _merge_definition_warning(current: str, extra: str) -> str:
        return "；".join(text for text in (current, extra) if text)

    def _definition_update_result(
        self,
        snapshot: DefinitionSnapshot,
        record: Mapping[str, Any],
        *,
        persisted: bool,
        warning: str = "",
    ) -> Dict[str, Any]:
        result = {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "revision": snapshot.revision,
            "memory_updated": True,
            "persisted": persisted,
            "record": dict(record),
            "static_meta": self.static_meta(),
        }
        if warning:
            result["warning"] = warning
        return result

    def update_device_parameters(
        self,
        payload: Mapping[str, Any],
        *,
        allow_runtime_controls: bool = True,
    ) -> Dict[str, Any]:
        with self._active_definition_update_guard():
            current = self.definition_snapshot
            require_definition_revision(payload, current.revision)
            model_book = simu_loop._clone_ebook(current.model_book)
            block_name = str(payload.get("block_name", "")).strip()
            if not block_name:
                raise ValueError("block_name is required")
            block = model_book.data.get(block_name)
            if block is None:
                raise ValueError(f"Unknown model block: {block_name}")
            row = self._definition_row(block, payload.get("row_key", {}))
            before_row = dict(row)
            changes = payload.get("changes", {})
            if not (type(changes) is dict or isinstance(changes, Mapping)):
                raise ValueError("changes must be an object")
            if block_name in HYDROGEN_CONVERSION_BLOCKS and "control_type" in changes:
                changes = {
                    **changes,
                    "control_type": normalize_hydrogen_conversion_control_mode(
                        changes["control_type"]
                    ),
                }
            if not allow_runtime_controls:
                runtime_fields = [
                    str(field)
                    for field in changes
                    if str(field).strip().casefold() in RUNTIME_CONTROL_STATUS_FIELDS
                    or self._runtime_control_set_type(block_name, str(field)) is not None
                ]
                if runtime_fields:
                    raise ValueError(
                        "学员台设备参数入口禁止修改运行状态、开关状态和遥调设定值，"
                        "请使用遥控/遥调。"
                    )
            try:
                normalized_changes = normalize_device_changes(
                    row,
                    changes,
                    allow_out_of_bounds_setpoints=not self.enforce_runtime_setpoint_bounds,
                )
            except SafetyBoundaryError as exc:
                dev_name = str(row.get("name", row.get("dev_name", ""))).strip()
                raise ValueError(
                    f"人工修改安全校验失败：{block_name}/{dev_name} 的修改超出允许范围"
                    f"（{exc}）；修改未生效，人工覆盖层、运行控制文件和仿真边界均未更新。"
                ) from exc
            if "p_set" in normalized_changes and self.enforce_runtime_setpoint_bounds:
                try:
                    hydrogen_safety = validate_hydrogen_power_setpoint_safety(
                        model_book,
                        block_name,
                        str(row.get("name", row.get("dev_name", ""))).strip(),
                        "p_set",
                        normalized_changes["p_set"],
                        clamp_to_bounds=True,
                    )
                    if hydrogen_safety and hydrogen_safety.get("clamped"):
                        normalized_changes["p_set"] = _number_text(
                            hydrogen_safety["p_set"]
                        )
                    prospective_row = {**row, **normalized_changes}
                    final_power, _bounds, _clamped = (
                        clamp_setpoint_safety_bounds(
                            prospective_row,
                            "p_set",
                            normalized_changes["p_set"],
                        )
                    )
                    normalized_changes["p_set"] = _number_text(final_power)
                except ValueError as exc:
                    dev_name = str(row.get("name", row.get("dev_name", ""))).strip()
                    raise ValueError(
                        f"人工修改模型校验失败：{block_name}/{dev_name} 的跨域换算无法形成"
                        f"有效有限目标（{exc}）；修改未生效，人工覆盖层、运行控制文件和"
                        "仿真边界均未更新。"
                    ) from exc
            clamped_setpoint_details = []
            for field_name, normalized_value in normalized_changes.items():
                normalized_field = str(field_name).strip().casefold()
                if not (
                    normalized_field.endswith("_set")
                    or normalized_field in {"pv0", "qv0"}
                ):
                    continue
                requested_number = _to_float(changes.get(field_name), None)
                normalized_number = _to_float(normalized_value, None)
                if (
                    requested_number is not None
                    and normalized_number is not None
                    and not math.isclose(
                        requested_number,
                        normalized_number,
                        rel_tol=1e-9,
                        abs_tol=1e-9,
                    )
                ):
                    clamped_setpoint_details.append(
                        f"{field_name} 请求值 {_number_text(requested_number)} 已限幅为 "
                        f"{_number_text(normalized_number)}"
                    )
            if clamped_setpoint_details:
                dev_name = str(row.get("name", row.get("dev_name", ""))).strip()
                self._append_runtime_log(
                    "控制安全边界",
                    "人工遥调限幅",
                    "越界值已限幅并继续生效",
                    [
                        f"{block_name}/{dev_name}",
                        *clamped_setpoint_details,
                        "设备运行状态保持不变，限幅后的设定值继续写入运行控制边界。",
                    ],
                    level="warn",
                )
            row.update(normalized_changes)
            runtime_override_keys: set[Tuple[str, str, str, str]] = set()
            dev_name = str(row.get("name", row.get("dev_name", ""))).strip()
            if dev_name:
                for field_name in normalized_changes:
                    normalized_field = str(field_name).strip().casefold()
                    if normalized_field in RUNTIME_CONTROL_STATUS_FIELDS:
                        control_field = (
                            "run_stat" if normalized_field == "run_stat" else "status"
                        )
                        runtime_override_keys.add(
                            ("remote_control", block_name, dev_name, control_field)
                        )
                        continue
                    set_type = self._runtime_control_set_type(block_name, normalized_field)
                    if set_type:
                        runtime_override_keys.add(
                            ("remote_adjustment", block_name, dev_name, set_type)
                        )
            dev_define_book = simu_loop._capability_define_book(
                model_book,
                self._legacy_dev_define_file(),
            )
            next_snapshot = DefinitionSnapshot(
                revision=current.revision + 1,
                model_book=model_book,
                dev_define_book=dev_define_book,
                measurement_before=current.measurement_before,
                measurement_rows=current.measurement_rows,
                measurement_after=current.measurement_after,
                measurement_median_deviations=current.measurement_median_deviations,
            )
            self._publish_definition_snapshot(next_snapshot)

            self._record_device_manual_changes_unlocked(
                block_name,
                before_row,
                row,
                tuple(normalized_changes),
                persisted=False,
                persistence_error="等待人工覆盖层保存",
            )
            runtime_control = self._sync_runtime_controls_from_device_changes_unlocked(
                block_name,
                row,
                normalized_changes,
                priority_override_keys=runtime_override_keys,
            )
            persisted = False
            change_record_persisted = False
            runtime_control_persisted = runtime_control is None
            warning = ""
            try:
                self._write_ahead_manual_definition_changes_unlocked()
            except OSError as exc:
                persistence_error = f"人工覆盖层保存失败: {exc}"
                warning = f"后台定义已更新，但人工覆盖层保存失败，请重试: {exc}"
                self._record_device_manual_changes_unlocked(
                    block_name,
                    before_row,
                    row,
                    tuple(normalized_changes),
                    persisted=False,
                    persistence_error=persistence_error,
                )
            else:
                change_record_persisted = True
                pending_changes = {
                    change_id: dict(item)
                    for change_id, item in self._manual_definition_changes.items()
                }
                self._mark_manual_changes_persisted_unlocked("device")
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
                    runtime_control_persisted = True
            record = {
                header: _json_scalar(row.get(header, ""))
                for header in block.header_list
            }
            result = self._definition_update_result(
                next_snapshot,
                {
                    "block_name": block_name,
                    "row_key": {
                        "idx": record.get("idx", ""),
                        "name": record.get("name", ""),
                    },
                    **record,
                },
                persisted=persisted,
                warning=warning,
            )
            result["change_record_persisted"] = change_record_persisted
            if runtime_control is not None:
                result["runtime_control"] = runtime_control
                result["runtime_control_persisted"] = runtime_control_persisted
            return result

    def device_parameters(self) -> Dict[str, List[Dict[str, Any]]]:
        book = self.definition_snapshot.model_book
        parameter_blocks = (
            "ACWindGen",
            "DCWindGen",
            "ACPVGen",
            "DCPVGen",
            "ACStorageGen",
            "DCStorageGen",
            "ACDieselGen",
            "DCDieselGen",
        )
        return {
            name: [
                {key: _json_scalar(value) for key, value in row.items()}
                for row in getattr(block, "data", [])
            ]
            for name, block in book.data.items()
            if name in parameter_blocks
        }

    def _definition_book_blocks(
        self,
        path: Path,
        block_names: Optional[Sequence[str]] = None,
        definition_snapshot: Optional[DefinitionSnapshot] = None,
    ) -> Dict[str, Dict[str, Any]]:
        book = self._definition_book_for_path(path, definition_snapshot)
        selected = set(block_names or [])
        blocks: Dict[str, Dict[str, Any]] = {}
        for name, block in book.data.items():
            if selected and name not in selected:
                continue
            headers = list(getattr(block, "header_list", []) or [])
            rows = [
                {header: _json_scalar(row.get(header, "")) for header in headers}
                for row in getattr(block, "data", [])
            ]
            blocks[name] = {"headers": headers, "rows": rows}
        return blocks

    def _definition_book_for_path(
        self,
        path: Path,
        definition_snapshot: Optional[DefinitionSnapshot] = None,
    ) -> EBook:
        active_snapshot = definition_snapshot or self.definition_snapshot
        try:
            resolved = Path(path).resolve()
        except Exception:
            resolved = Path(path)
        path_by_book = (
            (self.source_files.get("model"), active_snapshot.model_book),
            (self.source_files.get("stat"), self.source_stat_book),
            (self.source_files.get("control"), self.control_book),
            (self.work_files.get("stat"), self.runtime_stat_book),
        )
        for candidate, book in path_by_book:
            if candidate is None:
                continue
            try:
                if Path(candidate).resolve() == resolved:
                    return book
            except Exception:
                continue
        return EBook({})

    def definitions(self, measurements: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None) -> Dict[str, Any]:
        definition_snapshot = self.definition_snapshot
        median_deviations = _measurement_median_deviation_map(definition_snapshot)
        measurement_rows = self._with_realtime_measurements(
            {
                "definitions": [
                    _measurement_definition_row_to_dict(row, median_deviations)
                    for row in definition_snapshot.measurement_rows
                ],
                "real": [],
                "scada": [],
            }
        )["definitions"]
        for row in measurement_rows:
            status, fixed_value = self._measurement_status_override(row)
            row["status"] = status
            row["fixed_value"] = fixed_value
            row["valid"] = MEASUREMENT_STATUS_VALIDITY.get(
                status,
                int(_to_float(row.get("valid"), 0) or 0),
            )
        return {
            "model": self._definition_book_blocks(
                self.files["model"],
                definition_snapshot=definition_snapshot,
            ),
            "measurement": measurement_rows,
            "control": self._definition_book_blocks(
                self._control_definition_path(),
                CONTROL_DEFINITION_BLOCKS,
                definition_snapshot=definition_snapshot,
            ),
        }

    def model_diagram(self) -> Dict[str, Any]:
        path = self.source_files.get("diagram", self.sim_dir / DIAGRAM_FILE_NAME)
        payload: Dict[str, Any] = {
            "present": False,
            "filename": DIAGRAM_FILE_NAME,
            "path": str(path),
            "svg": "",
            "updated_at": 0,
            "size": 0,
        }
        if not path.exists() or not path.is_file():
            return payload
        try:
            stat = path.stat()
            cache_key = (str(path), stat.st_mtime_ns, stat.st_size)
            cached = getattr(self, "_model_diagram_cache", None)
            if cached is not None and cached[0] == cache_key:
                svg_text = cached[1]
            else:
                svg_text = path.read_text(encoding="utf-8-sig")
                self._model_diagram_cache = (cache_key, svg_text)
            payload.update(
                {
                    "present": True,
                    "svg": svg_text,
                    "updated_at": stat.st_mtime,
                    "size": stat.st_size,
                }
            )
        except OSError as exc:
            payload["error"] = str(exc)
        except UnicodeDecodeError:
            payload["error"] = "diagram.svg is not valid UTF-8 text"
        return payload

    def model_info(self) -> Dict[str, Any]:
        return {
            "id": self.model_id,
            "name": self.model_name,
            "sim_dir": str(self.sim_dir),
            "runtime_dir": str(self.runtime_dir),
            "clock_state": self.clock.state,
        }

    def _summary(self, measurements: Mapping[str, Sequence[Mapping[str, Any]]]) -> Dict[str, Any]:
        scada = measurements.get("scada", [])
        valid = [item for item in scada if item.get("valid", 0) == 1]
        measurement_alarms = []
        for item in scada:
            raw_val = item.get("value")
            if raw_val is None:
                continue
            num_val = _to_float(raw_val, None)
            if num_val is None or abs(num_val) > 1e4:
                measurement_alarms.append(item)
        compute_status = str(self.latest_compute.get("status", "") or "").strip().lower()
        power_flow_alarm_count = int(compute_status in {"failed", "timeout"})
        return {
            "scada_count": len(scada),
            "valid_scada_count": len(valid),
            "alarm_count": len(measurement_alarms) + power_flow_alarm_count,
            "measurement_alarm_count": len(measurement_alarms),
            "power_flow_alarm_count": power_flow_alarm_count,
            "command_count": len(self.command_history),
            "runtime_dir": str(self.runtime_dir),
            "model_id": self.model_id,
            "model_name": self.model_name,
        }
