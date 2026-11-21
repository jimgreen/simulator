"""PolarMicrogridSimulator 拆分模块：运行时日志、状态持久化与快照组装能力。"""

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


class _PersistenceMixin:
    """运行时日志、状态持久化与快照组装能力。"""

    def _load_runtime_state_from_disk(self) -> None:
        self._copy_runtime_inputs()
        self.weather_defaults = self._read_weather_defaults()
        self.reload_definition_state()
        self.ensure_weather_measurements_in_definition_files()
        self.reload_definition_state()
        with self.curves_lock:
            self.curves = self._read_curves()
            self._curve_revision += 1
            curve_mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
        self.clock.speed = _simulation_mode_default_clock_speed(curve_mode)
        self.local_settings = self._read_local_settings()
        self._source_measurement_statuses = self._read_source_measurement_statuses()
        self._apply_stored_system_parameters()
        self.command_history = self._read_command_history()
        self._rebuild_strategy_generation_index()
        if self.clear_commands_on_start_and_reset:
            self._remove_automatic_command_history_for_restart()
        self._last_command_response_index = len(self.command_history)
        self.runtime_logs = self._read_runtime_logs()
        self._runtime_log_seq = max((int(_to_float(item.get("seq"), 0) or 0) for item in self.runtime_logs), default=0)
        self.reload_definition_state()
        self._load_manual_definition_changes()
        self._reset_hydrogen_storage_state_to_initial()
        self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)

    @property
    def definition_snapshot(self) -> DefinitionSnapshot:
        epoch_before = self._definition_publish_epoch
        snapshot = self._definition_snapshot
        if epoch_before & 1:
            return snapshot
        mirror_refs = (
            self.source_model_book,
            self.dev_define_book,
            self.measurement_before,
            self.measurement_rows,
            self.measurement_after,
        )
        epoch_after = self._definition_publish_epoch
        if epoch_before != epoch_after or epoch_after & 1:
            return self._definition_snapshot
        if all(
            current is published
            for current, published in zip(mirror_refs, self._definition_mirror_refs)
        ):
            return snapshot

        # A few legacy tests and integrations replace mirror objects directly.
        # Copy those objects before the short snapshot commit window.
        measurement_before = tuple(mirror_refs[2])
        measurement_rows = tuple(tuple(row) for row in mirror_refs[3])
        measurement_after = tuple(mirror_refs[4])
        with self._definition_snapshot_sync_lock:
            if (
                self._definition_publish_epoch != epoch_after
                or self._definition_publish_epoch & 1
                or self._definition_snapshot is not snapshot
            ):
                return self._definition_snapshot
            live_refs = (
                self.source_model_book,
                self.dev_define_book,
                self.measurement_before,
                self.measurement_rows,
                self.measurement_after,
            )
            if not all(current is captured for current, captured in zip(live_refs, mirror_refs)):
                return self._definition_snapshot
            candidate = DefinitionSnapshot(
                revision=snapshot.revision + 1,
                model_book=mirror_refs[0],
                dev_define_book=mirror_refs[1],
                measurement_before=measurement_before,
                measurement_rows=measurement_rows,
                measurement_after=measurement_after,
                measurement_median_deviations=snapshot.measurement_median_deviations,
            )
            self._definition_publish_epoch = epoch_after + 1
            self._definition_mirror_refs = mirror_refs
            self._definition_snapshot = candidate
            self._definition_publish_epoch = epoch_after + 2
            self._internal_power_converter_keys_cache = None
            self._power_flow_connection_sides_cache = None
            self._measurement_definition_layout = None
            self._measurement_delta_step_count = None
            return candidate

    def _publish_definition_snapshot(self, snapshot: DefinitionSnapshot) -> None:
        normalized = DefinitionSnapshot(
            revision=int(snapshot.revision),
            model_book=snapshot.model_book,
            dev_define_book=snapshot.dev_define_book,
            measurement_before=tuple(snapshot.measurement_before),
            measurement_rows=tuple(tuple(row) for row in snapshot.measurement_rows),
            measurement_after=tuple(snapshot.measurement_after),
            measurement_median_deviations=_normalized_measurement_median_deviation_pairs(
                snapshot.measurement_median_deviations
            ),
        )
        measurement_before = list(normalized.measurement_before)
        measurement_rows = [list(row) for row in normalized.measurement_rows]
        measurement_after = list(normalized.measurement_after)
        with self._definition_snapshot_sync_lock:
            epoch = self._definition_publish_epoch
            if epoch & 1:  # pragma: no cover - publishers are serialized by the lock.
                raise RuntimeError("定义快照发布序列处于无效状态")
            old_snapshot = self._definition_snapshot
            old_mirrors = (
                self.source_model_book,
                self.dev_define_book,
                self.measurement_before,
                self.measurement_rows,
                self.measurement_after,
            )
            old_refs = self._definition_mirror_refs
            self._definition_publish_epoch = epoch + 1
            try:
                self.source_model_book = normalized.model_book
                self.dev_define_book = normalized.dev_define_book
                self.measurement_before = measurement_before
                self.measurement_rows = measurement_rows
                self.measurement_after = measurement_after
                self._definition_mirror_refs = (
                    self.source_model_book,
                    self.dev_define_book,
                    self.measurement_before,
                    self.measurement_rows,
                    self.measurement_after,
                )
                # The immutable pointer is committed last; readers seeing an odd
                # epoch return the previously committed old or this complete new value.
                self._definition_snapshot = normalized
            except Exception:
                (
                    self.source_model_book,
                    self.dev_define_book,
                    self.measurement_before,
                    self.measurement_rows,
                    self.measurement_after,
                ) = old_mirrors
                self._definition_mirror_refs = old_refs
                self._definition_snapshot = old_snapshot
                raise
            finally:
                self._definition_publish_epoch = epoch + 2
            self._internal_power_converter_keys_cache = None
            self._power_flow_connection_sides_cache = None
            self._measurement_definition_layout = None
            self._measurement_delta_step_count = None

    def reload_definition_state(self) -> None:
        """Load source definition E files into the live calculation state."""
        model_book = _load_book(self.source_files["model"])
        self.source_stat_book = _load_book(self.source_files["stat"])
        self.control_book = _load_book(
            self.source_files["control"] if self.source_files["control"].exists() else self.source_files["stat"]
        )
        self.source_stat_book, self.control_book = self._reconcile_source_dcp_controls_unlocked(
            model_book,
            self.source_stat_book,
            self.control_book,
        )
        simu_loop.ensure_closed_status_rows_book(self.source_stat_book)
        simu_loop.ensure_closed_status_rows_book(self.control_book)
        self.weather_book = _load_book(
            self.source_files["weather"] if self.source_files["weather"].exists() else self.work_files["weather"]
        )
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
        self._publish_definition_snapshot(
            DefinitionSnapshot(
                revision=self._definition_snapshot.revision + 1,
                model_book=model_book,
                dev_define_book=dev_define_book,
                measurement_before=tuple(measurement_before),
                measurement_rows=tuple(tuple(row) for row in measurement_rows),
                measurement_after=tuple(measurement_after),
                measurement_median_deviations=self._read_source_measurement_median_deviations(
                    measurement_rows
                ),
            )
        )
        self.runtime_stat_book = self._base_stat_book_for_controls()
        self._ensure_runtime_stat_book()
        self.yt_ctrl_book = _make_book({"SetValue": (STAT_HEADERS["SetValue"], [])})
        self.mode_book = None
        self.latest_model_book = None
        self.latest_device_states = []
        self.latest_real_rows = []
        self.latest_scada_rows = []
        median_deviations = _measurement_median_deviation_map(self.definition_snapshot)
        self.latest_measurements = {
            "definitions": [
                _measurement_definition_row_to_dict(row, median_deviations)
                for row in measurement_rows
            ],
            "real": [],
            "scada": [],
        }
        self.latest_measurement_clock = {}
        self._measurement_delta_seq = 0
        self._measurement_delta_state = {}
        self._measurement_delta_history = []
        self._measurement_delta_step_count = None
        self._measurement_delta_definition_signature = ""
        self._measurement_delta_definition_count = 0
        self._measurement_delta_definition_revision = 0
        self._measurement_history.clear(preserve_definition=False)

    def _cleanup_legacy_runtime_definition_files(self) -> None:
        for file_name in LEGACY_RUNTIME_DEFINITION_FILES:
            legacy_path = self.runtime_dir / file_name
            if not legacy_path.exists() or legacy_path.is_dir():
                continue
            if file_name == "stat.e" and not self.work_files["stat"].exists():
                shutil.copy2(legacy_path, self.work_files["stat"])
            elif file_name == "weather.e" and not self.work_files["weather"].exists():
                shutil.copy2(legacy_path, self.work_files["weather"])
            legacy_path.unlink()

    def _cleanup_legacy_working_model_files(self) -> None:
        for path in (self.work_dir / "model.e", self.work_dir / "merged_model.e"):
            if path.exists() and path.is_file():
                path.unlink()

    def _read_runtime_logs(self) -> List[Dict[str, Any]]:
        snapshot = _read_json(self.runtime_logs_file, [])
        snapshot_rows = snapshot if isinstance(snapshot, list) else []
        journal_rows: List[Dict[str, Any]] = []
        if self.runtime_logs_journal_file.exists():
            try:
                journal_lines = self.runtime_logs_journal_file.read_text(encoding="utf-8").splitlines()
            except OSError:
                journal_lines = []
            for line in journal_lines:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    journal_rows.append(item)
        self._runtime_log_journal_entry_count = len(journal_rows)

        legacy_rows: List[Dict[str, Any]] = []
        sequenced_rows: Dict[int, Dict[str, Any]] = {}
        for item in [*snapshot_rows, *journal_rows]:
            if not isinstance(item, dict):
                continue
            seq = int(_to_float(item.get("seq"), 0) or 0)
            if seq > 0:
                sequenced_rows[seq] = item
            else:
                legacy_rows.append(item)
        merged = [*legacy_rows, *(sequenced_rows[seq] for seq in sorted(sequenced_rows))]
        return merged[-RUNTIME_LOG_HISTORY_LIMIT:]

    def _write_runtime_logs(self) -> None:
        with self._runtime_log_persistence_lock:
            _write_json(self.runtime_logs_file, self.runtime_logs[-RUNTIME_LOG_HISTORY_LIMIT:])
            if self.runtime_logs_journal_file.exists():
                self.runtime_logs_journal_file.unlink()
            self._runtime_log_journal_entry_count = 0

    def _append_runtime_log_journal_batch(
        self,
        entries: Sequence[Mapping[str, Any]],
    ) -> None:
        pending = [dict(entry) for entry in entries]
        if not pending:
            return
        with self._runtime_log_persistence_lock:
            if not self.runtime_logs_file.exists():
                _write_json(self.runtime_logs_file, [])
            self.runtime_logs_journal_file.parent.mkdir(parents=True, exist_ok=True)
            with self.runtime_logs_journal_file.open("a", encoding="utf-8", newline="\n") as stream:
                stream.writelines(
                    f"{json.dumps(entry, ensure_ascii=False, separators=(',', ':'))}\n"
                    for entry in pending
                )
            self._runtime_log_journal_entry_count += len(pending)
            journal_size = self.runtime_logs_journal_file.stat().st_size
            if (
                self._runtime_log_journal_entry_count >= self.runtime_log_journal_entry_limit
                or journal_size >= self.runtime_log_journal_byte_limit
            ):
                self._write_runtime_logs()

    def _append_runtime_log_journal(self, entry: Mapping[str, Any]) -> None:
        self._append_runtime_log_journal_batch((entry,))

    def web_runtime_settings(self, role: str) -> Dict[str, Any]:
        with self.lock:
            return runtime_settings_payload(
                self.local_settings,
                role,
                model_id=self.model_id,
            )

    def set_web_runtime_settings(self, role: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock:
            with self._service_instance_lifecycle_lock:
                if not self._service_instance_active_locked():
                    raise ServiceInstanceRetiredError(
                        "运行参数请求所属模型生命周期已失效或已退休。"
                    )
                entry = updated_runtime_settings_entry(
                    self.local_settings,
                    role,
                    payload,
                    updated_at=_now_text(),
                )
                existing = self.local_settings.get("web_runtime_parameters", {})
                parameters = dict(existing) if (type(existing) is dict or isinstance(existing, Mapping)) else {}
                parameters[str(role).strip().lower()] = entry
                self.local_settings["web_runtime_parameters"] = parameters
                _write_json(self.settings_file, self.local_settings)
                return runtime_settings_payload(
                    self.local_settings,
                    role,
                    model_id=self.model_id,
                )

    def clone_files_to(self, target_dir: Path) -> None:
        with self.lock:
            _write_json(self.curves_file, self.curves)
            _write_json(self.settings_file, self.local_settings)
            self._write_command_history()
            target_dir.mkdir(parents=True, exist_ok=False)
            for name in SOURCE_DEFINITION_FILES:
                source = self.sim_dir / name
                if source.exists():
                    shutil.copy2(source, target_dir / name)
            diagram = self.sim_dir / DIAGRAM_FILE_NAME
            if diagram.exists():
                shutil.copy2(diagram, target_dir / DIAGRAM_FILE_NAME)
            if self.curves:
                _write_json(target_dir / "curves.json", self.curves)

    def _cancel_payload_from_history_entry(self, entry: Mapping[str, Any]) -> Dict[str, Any]:
        payload = entry.get("payload") if isinstance(entry.get("payload"), Mapping) else {}
        cancel_payload = dict(payload)
        for key in (
            "cancel_commands",
            "cancelCommands",
            "cancel_items",
            "cancelItems",
            "cancel_names",
            "cancelNames",
            "names",
            "name",
            "action",
            "operation",
            "cancel",
            "command_origin",
            "commandOrigin",
            "origin",
        ):
            if key in entry and key not in cancel_payload:
                cancel_payload[key] = entry.get(key)
        if "source" not in cancel_payload and entry.get("source"):
            cancel_payload["source"] = entry.get("source")
        return cancel_payload

    @staticmethod
    def _is_load_flow_convergence_failure(error: BaseException) -> bool:
        if isinstance(error, PowerFlowTimeoutError):
            return False
        text = f"{type(error).__name__}: {error}".casefold()
        return any(
            marker in text
            for marker in (
                "load flow failed",
                "power flow failed",
                "潮流计算失败",
                "潮流未收敛",
            )
        )

    def _legacy_dev_define_file(self) -> Optional[Path]:
        path = self.sim_dir / "device.e"
        return path if path.exists() and path.is_file() else None

    def _append_runtime_log(
        self,
        log_type: str,
        target: str,
        result: str,
        detail: Any = "",
        *,
        level: str = "info",
        simu_time: Optional[str] = None,
    ) -> None:
        self._append_runtime_log_batch(
            (
                {
                    "log_type": log_type,
                    "target": target,
                    "result": result,
                    "detail": detail,
                    "level": level,
                    "simu_time": simu_time,
                },
            )
        )

    def _append_runtime_log_batch(
        self,
        entries: Sequence[Mapping[str, Any]],
    ) -> None:
        if not entries:
            return
        with self._runtime_log_persistence_lock:
            journal_entries: List[Dict[str, Any]] = []
            for raw_entry in entries:
                self._runtime_log_seq += 1
                entry = {
                    "seq": self._runtime_log_seq,
                    "wall_time": _now_text(),
                    "simu_time": raw_entry.get("simu_time")
                    or minute_to_time(self.clock.minute),
                    "type": str(raw_entry.get("log_type", raw_entry.get("type", ""))),
                    "target": str(raw_entry.get("target", "")),
                    "result": str(raw_entry.get("result", "")),
                    "detail": _format_log_detail(raw_entry.get("detail", "")),
                    "level": str(raw_entry.get("level", "info")),
                }
                self.runtime_logs.append(entry)
                journal_entries.append(entry)
            self.runtime_logs = self.runtime_logs[-RUNTIME_LOG_HISTORY_LIMIT:]
            self._append_runtime_log_journal_batch(journal_entries)

    def clear_runtime_logs(self) -> Dict[str, int]:
        with self._runtime_log_persistence_lock:
            count = len(self.runtime_logs)
            self.runtime_logs = []
            self._runtime_log_seq = 0
            self._write_runtime_logs()
        return {"cleared": count}

    def runtime_logs_delta(
        self,
        after_seq: int | float = 0,
        *,
        limit: int = 100,
        before_seq: Optional[int | float] = None,
        log_type: str = "",
    ) -> Dict[str, Any]:
        """Return runtime log rows incrementally.

        ``after_seq`` is used by live polling. ``before_seq`` is available for
        history paging without forcing snapshots to carry the log tail.
        """
        try:
            after = int(after_seq)
        except (TypeError, ValueError):
            after = 0
        try:
            capped_limit = max(1, min(500, int(limit)))
        except (TypeError, ValueError):
            capped_limit = 100
        try:
            before = int(before_seq) if before_seq is not None else None
        except (TypeError, ValueError):
            before = None

        rows = list(self.runtime_logs)
        if log_type and log_type != "all":
            rows = [row for row in rows if str(row.get("type", "")) == log_type]
        latest_seq = max((int(_to_float(row.get("seq"), 0) or 0) for row in self.runtime_logs), default=0)
        reset = bool(after > latest_seq and latest_seq >= 0)

        if before is not None:
            page_rows = [row for row in rows if int(_to_float(row.get("seq"), 0) or 0) < before]
            selected = page_rows[-capped_limit:]
        elif reset:
            selected = rows[-capped_limit:]
        else:
            selected = [row for row in rows if int(_to_float(row.get("seq"), 0) or 0) > after][:capped_limit]

        oldest_seq = min((int(_to_float(row.get("seq"), 0) or 0) for row in rows), default=0)
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "items": selected,
            "logs": selected,
            "latest_seq": latest_seq,
            "oldest_seq": oldest_seq,
            "total": len(rows),
            "has_more_before": bool(selected and oldest_seq < int(_to_float(selected[0].get("seq"), 0) or 0)),
            "reset": reset,
        }

    def _append_environment_load_log(
        self,
        minute: int | float,
        target_minute: float,
        period_minutes: float,
        row: Mapping[str, Any],
        load_details: Sequence[Tuple[str, float]],
        *,
        load_seen: bool,
    ) -> None:
        curve_mode = str(self.curves.get("mode", "day") or "day")
        load_total = row.get("load_kw", 0)
        load_parts = [f"{name}={_number_text(value)} kW" for name, value in load_details[:8]]
        if len(load_details) > 8:
            load_parts.append("...")
        detail = [
            f"曲线模式 {curve_mode}，目标分钟 {format_number(float(target_minute % period_minutes))}，点号 {self._curve_point_index(target_minute, period_minutes)}",
            (
                f"环境 风速 {_value_with_unit(row.get('wind_speed_mps', ''), 'm/s')}，"
                f"光照 {_value_with_unit(row.get('solar_irradiance_w_m2', ''), 'W/m2')}，"
                f"气温 {_value_with_unit(row.get('air_temp_c', ''), '℃')}，"
                f"气压 {_value_with_unit(row.get('air_pressure_hpa', ''), 'hPa')}，"
                f"湿度 {_value_with_unit(row.get('humidity_pct', ''), '%')}"
            ),
            f"负荷合计 {load_total} kW" + (f"；{ '，'.join(load_parts) }" if load_parts else "；未配置分项负荷，使用默认/总负荷"),
            "已更新内存天气边界，并作为本轮负荷、新能源限值计算输入",
        ]
        self._append_runtime_log(
            "环境/负荷",
            "weather / curves",
            "逐点读取",
            detail,
            level="ok" if load_seen else "warn",
            simu_time=minute_to_time(minute),
        )

    def _load_flow_input_model_book(
        self,
        definition_snapshot: Optional[DefinitionSnapshot] = None,
    ) -> Optional[EBook]:
        if self.latest_model_book is not None:
            return self.latest_model_book
        active_snapshot = definition_snapshot or self.definition_snapshot
        return active_snapshot.model_book

    def _current_load_power_targets(
        self,
        target_minute: float,
        period_minutes: float,
    ) -> List[Dict[str, Any]]:
        loads = self.curves.get("loads", {})
        if not (type(loads) is dict or isinstance(loads, Mapping)):
            return []

        curve_targets = self._load_curve_targets()
        manual_overrides = self._manual_source_curve_override_keys()
        active_commands = self._active_remote_adjustment_keys(target_minute)
        inactive_coupling_keys = self._inactive_coupling_default_curve_keys()
        targets_by_device: Dict[Tuple[str, str], Tuple[int, Dict[str, Any]]] = {}
        for raw_name, points in loads.items():
            curve_name = str(raw_name).strip()
            if not curve_name:
                continue
            priority, matches = curve_targets.get(curve_name, (0, ()))
            value = self._interpolate_curve_series(
                points,
                target_minute,
                "p_kw",
                float("nan"),
                period_minutes=period_minutes,
            )
            if value != value:
                continue
            for block_name, dev_name in matches:
                key = (block_name, dev_name)
                control_key = (block_name, dev_name, "p_set")
                if (
                    control_key in manual_overrides
                    or control_key in active_commands
                    or control_key in inactive_coupling_keys
                ):
                    continue
                current = targets_by_device.get(key)
                if current is not None and current[0] > priority:
                    continue
                targets_by_device[key] = (
                    priority,
                    {
                        "dev_type": block_name,
                        "dev_name": dev_name,
                        "p_kw": max(0.0, float(value)),
                    },
                )
        return [targets_by_device[key][1] for key in sorted(targets_by_device)]

    def _write_modes_file(self) -> None:
        modes = self.local_settings.get("modes", [])
        if not modes:
            self.mode_book = None
            return
        rows: List[Dict[str, Any]] = []
        for mode in modes:
            if not (type(mode) is dict or isinstance(mode, Mapping)):
                continue
            dev_type = str(mode.get("dev_type", mode.get("type", "")))
            dev_name = str(mode.get("dev_name", mode.get("name", "")))
            mode_value = str(mode.get("mode", mode.get("control_type", "")))
            if not dev_type or not dev_name or not mode_value:
                continue
            rows.append({"dev_type": dev_type, "dev_name": dev_name, "mode": mode_value})
        if not rows:
            self.mode_book = None
            return
        self.mode_book = _make_book({"ControlMode": (("dev_type", "dev_name", "mode"), rows)})

    def _api_time_payload(self, clock: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        source = clock if (type(clock) is dict or isinstance(clock, Mapping)) else self.clock.as_dict()
        absolute_minute = _to_float(source.get("absolute_minute", source.get("minute")), 0.0) or 0.0
        minute = _to_float(source.get("minute"), None)
        if minute is None:
            minute = absolute_minute % 1440.0
        time_text = str(source.get("time") or minute_to_time(minute))
        return {
            "time": time_text,
            "simu_time": time_text,
            "absolute_minute": absolute_minute,
            "wall_time": _now_text(),
        }

    def _name_list_from_payload(self, payload: Mapping[str, Any], keys: Sequence[str]) -> List[str]:
        names: List[str] = []
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str):
                names.extend(part.strip() for part in re.split(r"[,;\s]+", value) if part.strip())
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                names.extend(str(item).strip() for item in value if str(item).strip())
        return names

    @staticmethod
    def _manual_change_persistence_status(persisted: bool) -> str:
        return "覆盖层已保存" if persisted else "覆盖层保存失败"

    def _manual_definition_changes_payload_unlocked(
        self,
        *,
        accepted_source_fingerprints: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        changes = []
        for item in self._manual_definition_changes.values():
            copied = dict(item)
            if isinstance(copied.get("row_key"), Mapping):
                copied["row_key"] = dict(copied["row_key"])
            changes.append(copied)
        changes.sort(
            key=lambda item: (str(item.get("modified_at", "")), str(item.get("id", ""))),
            reverse=True,
        )
        source_fingerprint = self._manual_definition_source_fingerprint()
        accepted_fingerprints = list(
            dict.fromkeys(
                fingerprint
                for fingerprint in (
                    source_fingerprint,
                    *(accepted_source_fingerprints or ()),
                )
                if fingerprint
            )
        )
        return {
            "version": 5,
            "model_id": self.model_id,
            "model_name": self.model_name,
            "source_fingerprint": source_fingerprint,
            "accepted_source_fingerprints": accepted_fingerprints,
            "revision": self.definition_snapshot.revision,
            "count": len(changes),
            "changes": changes,
        }

    def _load_manual_definition_changes(self) -> None:
        overlay_exists = self.manual_definition_changes_file.exists()
        payload = _read_json(self.manual_definition_changes_file, {})
        accepted_fingerprints: List[str] = []
        if (type(payload) is dict or isinstance(payload, Mapping)):
            expected_fingerprint = str(payload.get("source_fingerprint", "")).strip()
            if expected_fingerprint:
                accepted_fingerprints.append(expected_fingerprint)
            raw_accepted = payload.get("accepted_source_fingerprints", [])
            if isinstance(raw_accepted, Sequence) and not isinstance(raw_accepted, (str, bytes)):
                accepted_fingerprints.extend(
                    str(fingerprint).strip()
                    for fingerprint in raw_accepted
                    if str(fingerprint).strip()
                )
        accepted_fingerprints = list(dict.fromkeys(accepted_fingerprints))
        current_fingerprint = self._manual_definition_source_fingerprint()
        source_definition_changed = bool(
            accepted_fingerprints and current_fingerprint not in accepted_fingerprints
        )
        model_matches = not (type(payload) is dict or isinstance(payload, Mapping)) or str(
            payload.get("model_id", self.model_id)
        ).strip() in {"", self.model_id}
        if overlay_exists and (
            not (type(payload) is dict or isinstance(payload, Mapping))
            or not payload
            or not accepted_fingerprints
        ):
            self._manual_definition_changes = {}
            self._archive_manual_definition_changes_unlocked()
            return
        if (type(payload) is dict or isinstance(payload, Mapping)) and payload and not model_matches:
            self._manual_definition_changes = {}
            self._archive_manual_definition_changes_unlocked()
            return
        items = payload.get("changes", []) if (type(payload) is dict or isinstance(payload, Mapping)) else []
        loaded: Dict[str, Dict[str, Any]] = {}
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
            for raw_item in items:
                if not (type(raw_item) is dict or isinstance(raw_item, Mapping)):
                    continue
                item = dict(raw_item)
                change_id = str(item.get("id", "")).strip()
                if not change_id or item.get("kind") not in {"device", "measurement"} or not item.get("field"):
                    continue
                persisted = bool(item.get("persisted", False))
                item.setdefault("sync_status", "synced" if persisted else "failed")
                item.setdefault("last_sync_time", str(item.get("modified_at", "")))
                item.setdefault("last_sync_error", "" if persisted else "人工覆盖层尚未同步")
                item.setdefault("retry_count", 0)
                loaded[change_id] = item
        self._manual_definition_changes = loaded
        if source_definition_changed and self._manual_definition_changes:
            try:
                source_snapshot, _source_stat, _source_control = (
                    self._source_definition_state_unlocked()
                )
            except (KeyError, ValueError, OSError):
                source_snapshot = None
            if source_snapshot is not None:
                for item in self._manual_definition_changes.values():
                    try:
                        source_value = self._current_manual_change_value(
                            item,
                            snapshot=source_snapshot,
                        )
                    except (KeyError, ValueError):
                        source_value = None
                    if source_value is not None:
                        item["default_value"] = source_value
        migrated_legacy_statuses = self._migrate_legacy_measurement_status_overrides_unlocked()
        if not self._manual_definition_changes:
            return

        try:
            self._rebuild_effective_definitions_from_source_unlocked(
                materialize_controls=False,
            )
        except (KeyError, ValueError):
            self._manual_definition_changes = {}
            self._archive_manual_definition_changes_unlocked()
            self.reload_definition_state()
            return

        reconciled = migrated_legacy_statuses or source_definition_changed
        for change_id, item in list(self._manual_definition_changes.items()):
            if item.get("effective") is False:
                reconciled = True
                continue
            try:
                current_value = self._current_manual_change_value(item)
            except (KeyError, ValueError):
                current_value = None
            if current_value is None or not self._manual_change_values_equal(
                current_value,
                item.get("current_value", ""),
            ):
                self._manual_definition_changes.pop(change_id, None)
                reconciled = True
                continue
            if self._manual_change_values_equal(
                item.get("current_value", ""),
                item.get("default_value", ""),
            ):
                self._manual_definition_changes.pop(change_id, None)
                reconciled = True
                continue
            if not bool(item.get("persisted", False)) or item.get("sync_status") != "synced":
                self._set_manual_change_sync_state_unlocked(item, persisted=True)
                reconciled = True
        if reconciled:
            try:
                self._write_manual_definition_changes_unlocked()
            except OSError:
                pass

    def _snapshot_with_manual_change_values_unlocked(
        self,
        current: DefinitionSnapshot,
        items: Sequence[Mapping[str, Any]],
    ) -> Tuple[DefinitionSnapshot, set[str]]:
        kinds = {str(item.get("kind", "")) for item in items}
        model_book = simu_loop._clone_ebook(current.model_book) if "device" in kinds else current.model_book
        measurement_rows = [list(row) for row in current.measurement_rows]
        measurement_median_deviations = _measurement_median_deviation_map(current)
        changed = False

        device_groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for raw_item in items:
            if raw_item.get("kind") != "device":
                continue
            item = raw_item if isinstance(raw_item, dict) else dict(raw_item)
            block_name = str(item.get("block_name", ""))
            row_key = item.get("row_key", {})
            identity = json.dumps(row_key, ensure_ascii=False, sort_keys=True)
            device_groups.setdefault((block_name, identity), []).append(item)

        for (block_name, _identity), group in device_groups.items():
            try:
                block = model_book.data.get(block_name)
                if block is None:
                    raise ValueError(f"Unknown model block: {block_name}")
                row_key = group[0].get("row_key", {})
                if not (type(row_key) is dict or isinstance(row_key, Mapping)):
                    raise ValueError(
                        f"Invalid device identity for manual change: {group[0].get('id', '')}"
                    )
                row = self._definition_row(block, row_key)
                desired = {
                    str(item.get("field", "")): item.get("current_value", "")
                    for item in group
                }
                normalized = normalize_device_changes(
                    row,
                    desired,
                    allow_out_of_bounds_setpoints=not self.enforce_runtime_setpoint_bounds,
                )
            except (KeyError, ValueError) as exc:
                for item in group:
                    item["effective"] = False
                    item["application_status"] = "invalid"
                    item["application_error"] = str(exc)
                continue
            for item in group:
                item["effective"] = True
                item["application_status"] = "applied"
                item["application_error"] = ""
            changed = changed or any(
                not self._manual_change_values_equal(row.get(field_name, ""), value)
                for field_name, value in normalized.items()
            )
            row.update(normalized)

        measurement_groups: Dict[str, Dict[str, Any]] = {}
        for item in items:
            if item.get("kind") != "measurement":
                continue
            if isinstance(item, dict):
                item["effective"] = True
                item["application_status"] = "applied"
                item["application_error"] = ""
            measurement_name = str(item.get("measurement_name", ""))
            measurement_groups.setdefault(measurement_name, {})[str(item.get("field", ""))] = item.get(
                "current_value",
                "",
            )
        for measurement_name, desired_values in measurement_groups.items():
            index, current_item = self._measurement_definition_row(
                measurement_rows,
                {"name": measurement_name},
            )
            current_item["median_deviation"] = measurement_median_deviations.get(
                measurement_name,
                0.0,
            )
            normalized = normalize_measurement_changes(current_item, desired_values)
            changed = changed or not self._manual_change_values_equal(
                measurement_rows[index][5],
                normalized["weight"],
            ) or not self._manual_change_values_equal(
                measurement_rows[index][6],
                normalized["valid"],
            ) or not self._manual_change_values_equal(
                measurement_median_deviations.get(measurement_name, 0.0),
                normalized["median_deviation"],
            )
            measurement_rows[index][5] = normalized["weight"]
            measurement_rows[index][6] = normalized["valid"]
            if normalized["median_deviation"] == 0.0:
                measurement_median_deviations.pop(measurement_name, None)
            else:
                measurement_median_deviations[measurement_name] = normalized["median_deviation"]

        if not changed:
            return current, kinds
        dev_define_book = (
            simu_loop._capability_define_book(model_book, self._legacy_dev_define_file())
            if "device" in kinds
            else current.dev_define_book
        )
        return DefinitionSnapshot(
            revision=current.revision + 1,
            model_book=model_book,
            dev_define_book=dev_define_book,
            measurement_before=current.measurement_before,
            measurement_rows=tuple(tuple(row) for row in measurement_rows),
            measurement_after=current.measurement_after,
            measurement_median_deviations=_normalized_measurement_median_deviation_pairs(
                measurement_median_deviations
            ),
        ), kinds

    def _mark_manual_changes_persisted_unlocked(self, kind: str) -> None:
        for change_id, item in list(self._manual_definition_changes.items()):
            if item.get("kind") != kind:
                continue
            self._set_manual_change_sync_state_unlocked(item, persisted=True)
            if self._manual_change_values_equal(
                item.get("current_value", ""),
                item.get("default_value", ""),
            ):
                self._manual_definition_changes.pop(change_id, None)

    def snapshot(
        self,
        include_static: bool = True,
        runtime_log_limit: int = 300,
        *,
        include_runtime_logs: bool = True,
        include_measurements: bool = True,
        include_static_meta: bool = True,
        static_fields: Optional[Sequence[str]] = None,
        include_devices: bool = True,
        include_device_states: bool = True,
        include_commands: bool = True,
        include_command_history: bool = True,
    ) -> Dict[str, Any]:
        measurements: Dict[str, Any] = {}
        if include_measurements:
            compute_status = str(self.latest_compute.get("status", "") or "").lower()
            if compute_status in {"failed", "timeout"} and self.latest_measurements:
                measurements = {
                    str(channel): [dict(row) for row in rows]
                    for channel, rows in self.latest_measurements.items()
                }
            else:
                measurements = self.measurements()
                if "definitions" not in measurements:
                    definition_snapshot = self.definition_snapshot
                    median_deviations = _measurement_median_deviation_map(definition_snapshot)
                    measurements["definitions"] = [
                        _measurement_definition_row_to_dict(row, median_deviations)
                        for row in definition_snapshot.measurement_rows
                    ]
        try:
            log_limit = max(0, int(runtime_log_limit))
        except (TypeError, ValueError):
            log_limit = 300
        logs = self.runtime_logs[-log_limit:] if log_limit else []
        summary_measurements = measurements if include_measurements else (self.latest_measurements or {})
        snapshot = {
            "model": self.model_info(),
            "clock": self.clock.as_dict(),
            "measurement_clock": dict(self.latest_measurement_clock),
            "system_parameters": self.system_parameters(),
            "simulation_timing": self.simulation_timing(),
            "curve_boundary": self.curve_boundary(),
            "result": self.latest_result,
            "compute": dict(self.latest_compute),
            "summary": self._summary(summary_measurements),
            "power_summary": self._latest_power_summary(summary_measurements),
        }
        if include_static_meta:
            snapshot["static_meta"] = self.static_meta()
        if include_commands:
            recent_commands = self.command_history[-50:]
            recent_ids = {id(entry) for entry in recent_commands}
            active_commands = self._active_control_command_entries(self.clock.absolute_minute)
            effective_commands = self._effective_active_control_command_views(self.clock.absolute_minute)
            queued_commands = self._queued_active_control_command_views(self.clock.absolute_minute)
            pinned_commands = [
                entry
                for entry in active_commands
                if _manual_command_holds_across_clock_lifecycle(entry) and id(entry) not in recent_ids
            ]
            pinned_ids = {id(entry) for entry in pinned_commands}
            pinned_commands.extend(
                entry
                for entry in effective_commands
                if id(entry) not in recent_ids and id(entry) not in pinned_ids
            )
            snapshot["commands"] = {
                "history": pinned_commands + recent_commands if include_command_history else [],
                "effective": effective_commands,
                "queued": queued_commands,
            }
        if include_devices:
            snapshot["devices"] = self.devices()
        if include_device_states:
            snapshot["device_states"] = self.device_states()
        if include_runtime_logs:
            snapshot["runtime_logs"] = logs
        if include_measurements:
            snapshot["measurements"] = measurements
        if include_static:
            requested_static_fields = set(SNAPSHOT_STATIC_FIELDS)
            if static_fields is not None:
                requested_static_fields = {
                    str(field)
                    for field in static_fields
                    if str(field) in SNAPSHOT_STATIC_FIELDS
                }
            if "definitions" in requested_static_fields and not include_measurements:
                measurements = self.measurements()
            if "files" in requested_static_fields:
                snapshot["files"] = {key: str(path) for key, path in self.files.items()}
            if "source_files" in requested_static_fields:
                snapshot["source_files"] = {key: str(path) for key, path in self.source_files.items()}
            if "work_files" in requested_static_fields:
                snapshot["work_files"] = {key: str(path) for key, path in self.work_files.items()}
            if "definitions" in requested_static_fields:
                snapshot["definitions"] = self.definitions(measurements)
            if "curves" in requested_static_fields:
                snapshot["curves"] = self.curves
            if "settings" in requested_static_fields:
                snapshot["settings"] = self.local_settings
            if "device_parameters" in requested_static_fields:
                snapshot["device_parameters"] = self.device_parameters()
            if "diagram" in requested_static_fields:
                snapshot["diagram"] = self.model_diagram()
        return snapshot
