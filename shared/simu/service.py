"""Service layer for the polar microgrid time-series simulation system.

本模块作为仿真服务门面，按领域将 ``PolarMicrogridSimulator`` 拆分为
``simu.service_parts`` 下的 6 个高内聚 Mixin 模块（曲线、量测、控制、定义、持久化、时钟步进），
并保持所有公开与历史内部符号 100% 向后兼容。
"""

from __future__ import annotations

try:
    from .service_parts.common import *  # noqa: F401,F403
    from .service_parts.common import (
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
    from .service_parts.clock_step import _ClockStepMixin
    from .service_parts.controls import _ControlsMixin
    from .service_parts.curves import _CurvesMixin
    from .service_parts.definitions import _DefinitionsMixin
    from .service_parts.measurements import _MeasurementsMixin
    from .service_parts.persistence import _PersistenceMixin
except ImportError:  # pragma: no cover - legacy direct-module compatibility.
    from simu.service_parts.common import *  # noqa: F401,F403
    from simu.service_parts.common import (
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
    from simu.service_parts.clock_step import _ClockStepMixin
    from simu.service_parts.controls import _ControlsMixin
    from simu.service_parts.curves import _CurvesMixin
    from simu.service_parts.definitions import _DefinitionsMixin
    from simu.service_parts.measurements import _MeasurementsMixin
    from simu.service_parts.persistence import _PersistenceMixin


class PolarMicrogridSimulator(
    _CurvesMixin,
    _MeasurementsMixin,
    _ControlsMixin,
    _DefinitionsMixin,
    _PersistenceMixin,
    _ClockStepMixin,
):
    """Runtime service for simulator and trainee web consoles."""

    def __init__(
        self,
        sim_dir: str | Path,
        runtime_dir: str | Path,
        kernel: Optional[Callable[[simu_loop.SimulationConfig], Optional[simu_loop.SimulationResult]]] = None,
        *,
        kernel_runner: Optional[Any] = None,
        period_seconds: float = 60.0,
        noise_std: Optional[float] = None,
        random_seed: Optional[int] = None,
        compute_interval_seconds: float = DEFAULT_COMPUTE_INTERVAL_SECONDS,
        model_id: str = "default",
        model_name: str = "",
        clear_commands_on_start_and_reset: bool = False,
        enforce_runtime_setpoint_bounds: bool = True,
    ) -> None:
        self.sim_dir = Path(sim_dir).resolve()
        self.runtime_dir = Path(runtime_dir).resolve()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.model_id = _safe_model_id(model_id)
        self.model_name = model_name or self.model_id
        self.clear_commands_on_start_and_reset = bool(clear_commands_on_start_and_reset)
        self.enforce_runtime_setpoint_bounds = bool(enforce_runtime_setpoint_bounds)
        self.service_instance_id = uuid.uuid4().hex
        self.kernel = kernel or simu_loop.run_once
        self.kernel_runner = kernel_runner
        self.period_seconds = float(period_seconds)
        self._initial_compute_interval_seconds = _compute_interval_seconds(compute_interval_seconds)
        self.compute_interval_seconds = self._initial_compute_interval_seconds
        self.storage_initial_soc = DEFAULT_STORAGE_INITIAL_SOC
        self.remote_adjustment_response_ratio = DEFAULT_REMOTE_ADJUSTMENT_RESPONSE_RATIO
        self._remote_adjustment_execution: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self._remote_adjustment_cycle_seq = 0
        self.noise_std = noise_std
        self.random_seed = random_seed
        self.clock = ClockState()
        self.lock = threading.RLock()
        self._step_lock = threading.Lock()
        self._service_instance_lifecycle_lock = threading.RLock()
        self._service_instance_retired = False
        # Definition/control transactions always acquire this lock before
        # ``self.lock``. Reentrancy lets model-import helpers compose safely.
        self.definition_update_lock = threading.RLock()
        # Curve definitions change only through explicit editing APIs. Keep their
        # short read lock separate from the long-running power-flow calculation lock.
        self.curves_lock = threading.RLock()
        self._curve_revision = 0
        self._curve_boundary_cache_key: Optional[Tuple[Any, ...]] = None
        self._curve_boundary_cache_value: Optional[Dict[str, Any]] = None
        self._compiled_curve_revision = -1
        self._compiled_curve_series_cache: Dict[
            Tuple[int, str, float],
            Tuple[Tuple[float, ...], Tuple[float, ...]],
        ] = {}
        self._load_curve_target_cache_key: Optional[Tuple[int, int]] = None
        self._load_curve_target_cache_value: Dict[
            str,
            Tuple[int, Tuple[Tuple[str, str], ...]],
        ] = {}
        self._source_curve_catalog_cache_key = -1
        self._source_curve_catalog_cache_value: Tuple[Dict[str, Any], ...] = ()
        self._measurement_bindings_cache_revision = -1
        self._measurement_bindings_cache: Tuple[simu_loop.MeasurementBinding, ...] = ()
        self._measurement_definition_layout: Optional[
            _MeasurementDefinitionLayout
        ] = None
        self._latest_power_summary_cache_key: Optional[Tuple[Any, ...]] = None
        self._latest_power_summary_cache_value: Optional[Dict[str, Any]] = None
        self._device_runtime_frame_cache_key: Optional[Tuple[Any, ...]] = None
        self._device_runtime_frame_cache_value: Optional[Dict[str, Any]] = None
        self.command_history: List[Dict[str, Any]] = []
        self._command_history_persisted_signature: Optional[str] = None
        self._strategy_generation_entries: Dict[str, List[Dict[str, Any]]] = {}
        self._strategy_generation_index_token: Optional[Tuple[int, int, int]] = None
        self.runtime_logs: List[Dict[str, Any]] = []
        self._runtime_log_seq = 0
        self._runtime_log_persistence_lock = threading.RLock()
        self._runtime_log_journal_entry_count = 0
        self.runtime_log_journal_entry_limit = RUNTIME_LOG_JOURNAL_ENTRY_LIMIT
        self.runtime_log_journal_byte_limit = RUNTIME_LOG_JOURNAL_BYTE_LIMIT
        self._measurement_delta_seq = 0
        self._measurement_delta_state: Dict[str, Dict[str, Any]] = {}
        self._measurement_delta_history: List[Dict[str, Any]] = []
        self._measurement_delta_step_count: Optional[int] = None
        self._measurement_delta_runtime_marker: Optional[Tuple[Any, ...]] = None
        self._measurement_delta_definition_signature = ""
        self._measurement_delta_definition_count = 0
        self._measurement_delta_definition_revision = 0
        self._measurement_history = MeasurementHistoryStore()
        self._last_command_response_index = 0
        self.latest_result: Dict[str, Any] = {}
        self.latest_measurements: Dict[str, Any] = {}
        self.latest_measurement_clock: Dict[str, Any] = {}
        self._automatic_runtime_state_invalidated = False
        self.latest_model_book: Optional[EBook] = None
        self.latest_device_states: List[Dict[str, Any]] = []
        self.latest_compute: Dict[str, Any] = {
            "mode": "process" if kernel_runner is not None else "embedded",
            "http_pid": os.getpid(),
            "worker_pid": 0 if kernel_runner is not None else os.getpid(),
            "compute_ms": 0.0,
            "round_trip_ms": 0.0,
            "status": "idle",
            "resident_model": kernel_runner is None,
        }
        self.source_model_book = EBook({})
        self.source_stat_book = EBook({})
        self.control_book = EBook({})
        self.weather_book = EBook({})
        self.dev_define_book = EBook({})
        self._definition_snapshot = DefinitionSnapshot(
            revision=0,
            model_book=self.source_model_book,
            dev_define_book=self.dev_define_book,
            measurement_before=(),
            measurement_rows=(),
            measurement_after=(),
        )
        self.runtime_stat_book = EBook({})
        self.yt_ctrl_book = EBook({})
        self.mode_book: Optional[EBook] = None
        self.measurement_before: List[str] = []
        self.measurement_rows: List[List[str]] = []
        self.measurement_after: List[str] = []
        self._definition_publish_epoch = 0
        self._definition_snapshot_sync_lock = threading.Lock()
        self._definition_mirror_refs = (
            self.source_model_book,
            self.dev_define_book,
            self.measurement_before,
            self.measurement_rows,
            self.measurement_after,
        )
        self.latest_real_rows: List[List[str]] = []
        self.latest_scada_rows: List[List[str]] = []
        self._fault_restore: Dict[Tuple[str, str, str], str] = {}
        self._last_scada_values: Dict[str, float] = {}
        self._internal_power_converter_keys_cache: Optional[
            Tuple[int, set[Tuple[str, str]]]
        ] = None
        self._power_flow_connection_sides_cache: Optional[
            Tuple[int, Tuple[Tuple[str, str, str], ...], Dict[Tuple[str, str], str]]
        ] = None

        self.work_dir = self.runtime_dir / ".simu_loop_work"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.source_files = {
            "model": self.sim_dir / "model.e",
            "meas": self.sim_dir / "meas.e",
            "stat": self.sim_dir / "stat.e",
            "control": self.sim_dir / "control.e",
            "weather": self.sim_dir / "weather.e",
            "curves": self.sim_dir / "curves.json",
            "curves_e": self.sim_dir / "curves.e",
            "diagram": self.sim_dir / DIAGRAM_FILE_NAME,
            "definition_defaults": self.sim_dir / DEFINITION_DEFAULTS_FILE,
        }
        self.work_files = {
            "stat": self.work_dir / "stat.e",
            "weather": self.work_dir / "weather.e",
            "mode": self.work_dir / "mode.e",
        }
        self.files = {
            "model": self.source_files["model"],
            "meas": self.source_files["meas"],
            "stat": self.work_files["stat"],
            "control": self.source_files["control"],
            "weather": self.work_files["weather"],
            "yt_ctrl": self.runtime_dir / "yt_ctrl.e",
            "real": self.runtime_dir / "real.e",
            "scada": self.runtime_dir / "scada.e",
            "diagram": self.source_files["diagram"],
        }
        self.curves_file = self.runtime_dir / "curves.json"
        self.source_curves_file = self.source_files["curves"]
        self.settings_file = self.runtime_dir / "local_settings.json"
        self.commands_file = self.runtime_dir / "commands.json"
        self.runtime_logs_file = self.runtime_dir / "runtime_logs.json"
        self.runtime_logs_journal_file = self.runtime_dir / "runtime_logs.jsonl"
        self.trainee_receive_file = self.runtime_dir / "trainee_receive.json"
        self._trainee_receive_cache_lock = threading.RLock()
        self._trainee_receive_cache_signature: Optional[Tuple[int, int, int]] = None
        self._trainee_receive_cache_value: Optional[Dict[str, Any]] = None
        self._trainee_receive_cache_next_stat_monotonic = 0.0
        self._trainee_receive_revision = 0
        self._device_runtime_supplement_cache: Optional[Tuple[Any, Dict[str, Any]]] = None
        self._command_signature_cache: Optional[Tuple[Any, str]] = None
        # SVG definition edits are runtime overrides.  The source E files stay
        # immutable so an operator can always restore the model defaults.
        self.manual_definition_changes_file = self.runtime_dir / MANUAL_DEFINITION_CHANGES_FILE
        self._manual_definition_changes: Dict[str, Dict[str, Any]] = {}
        self._source_measurement_statuses: Dict[str, Dict[str, Any]] = {}

        self._load_runtime_state_from_disk()

    def _service_instance_active_locked(self) -> bool:
        return not self._service_instance_retired

    def service_instance_active(self) -> bool:
        with self._service_instance_lifecycle_lock:
            return self._service_instance_active_locked()

    def _retire_service_instance_locked(self) -> None:
        with self._service_instance_lifecycle_lock:
            self._service_instance_retired = True

    def _copy_runtime_inputs(self) -> None:
        self._cleanup_legacy_runtime_definition_files()
        self._cleanup_legacy_working_model_files()
        self._materialize_working_stat()
        self._materialize_working_weather()

    def _materialize_working_stat(self) -> None:
        source = self.source_files["stat"]
        target = self.work_files["stat"]
        if not target.exists() and source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _read_local_settings(self) -> Dict[str, Any]:
        default = {
            "device_faults": [],
            "measurement_faults": [],
            "measurement_statuses": {},
            "modes": [],
            "system_parameters": {},
        }
        if self.settings_file.exists():
            settings = _read_json(self.settings_file, default)
        else:
            source_settings_file = self.sim_dir / "local_settings.json"
            settings = _read_json(source_settings_file, default) if source_settings_file.exists() else default
        normalized = dict(settings) if (type(settings) is dict or isinstance(settings, Mapping)) else dict(default)
        for key, fallback in default.items():
            normalized.setdefault(key, fallback.copy() if isinstance(fallback, dict) else list(fallback))
        if not isinstance(normalized.get("measurement_statuses"), Mapping):
            normalized["measurement_statuses"] = {}
        return normalized

    def _normalize_trainee_receive_state(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        current = self._default_trainee_receive_state()
        current.update(
            {
                key: payload.get(key, current[key])
                for key in current
                if key in payload and key not in {"model_id", "model_name"}
            }
        )
        aliases = {
            "initialized": ("initialized", "model_initialized", "modelInitialized"),
            "initialized_at": ("initialized_at", "initializedAt", "model_initialized_at"),
            "active": ("active", "receive_mode", "receiveMode"),
            "frozen": ("frozen",),
            "interaction_link": ("interaction_link", "interactionLink", "link"),
            "teacher_api_base": ("teacher_api_base", "teacherApiBase"),
            "teacher_model_id": ("teacher_model_id", "teacherModelId", "model_id"),
            "teacher_model_name": ("teacher_model_name", "teacherModelName", "model_name"),
            "snapshot_path": ("snapshot_path", "snapshotPath"),
            "command_path": ("command_path", "commandPath"),
            "measurement_delta_path": ("measurement_delta_path", "measurementDeltaPath"),
            "definition_archive_path": ("definition_archive_path", "definitionArchivePath"),
            "last_receive_at": ("last_receive_at", "lastReceiveAt"),
            "updated_at": ("updated_at", "updatedAt"),
        }
        normalized: Dict[str, Any] = {
            "model_id": self.model_id,
            "model_name": self.model_name,
        }
        for key, names in aliases.items():
            value = current.get(key, "")
            for name in names:
                if name in payload:
                    value = payload.get(name)
                    break
            if key in {"initialized", "active", "frozen"}:
                normalized[key] = bool(value)
                continue
            normalized[key] = str(value or "").strip()
        normalized["teacher_api_base"] = normalized["teacher_api_base"].rstrip("/")
        has_explicit_initialized = any(name in payload for name in aliases["initialized"])
        has_saved_connection = bool(
            normalized["interaction_link"]
            or (
                normalized["teacher_api_base"]
                and (normalized["snapshot_path"] or normalized["command_path"])
            )
        )
        if not has_explicit_initialized and has_saved_connection:
            normalized["initialized"] = True
        if not normalized["teacher_model_id"] and normalized["active"]:
            normalized["teacher_model_id"] = self.model_id
        if not normalized["teacher_model_name"] and normalized["teacher_model_id"]:
            normalized["teacher_model_name"] = normalized["teacher_model_id"]
        return normalized

    def trainee_receive_state(self) -> Dict[str, Any]:
        now = time.monotonic()
        with self._trainee_receive_cache_lock:
            if (
                self._trainee_receive_cache_value is not None
                and now < self._trainee_receive_cache_next_stat_monotonic
            ):
                return dict(self._trainee_receive_cache_value)
            try:
                stat = self.trainee_receive_file.stat()
                signature: Optional[Tuple[int, int, int]] = (
                    int(stat.st_mtime_ns),
                    int(stat.st_ctime_ns),
                    int(stat.st_size),
                )
            except OSError:
                signature = None
            self._trainee_receive_cache_next_stat_monotonic = now + 0.25
            if (
                self._trainee_receive_cache_value is not None
                and self._trainee_receive_cache_signature == signature
            ):
                return dict(self._trainee_receive_cache_value)
            raw = _read_json(self.trainee_receive_file, {})
            if not (type(raw) is dict or isinstance(raw, Mapping)):
                raw = {}
            normalized = self._normalize_trainee_receive_state(raw)
            if self._trainee_receive_cache_value != normalized:
                self._trainee_receive_revision += 1
            self._trainee_receive_cache_signature = signature
            self._trainee_receive_cache_value = normalized
            return dict(normalized)

    def trainee_receive_revision(self) -> int:
        """返回学员端接收状态单调整型版本号，供 HTTP 帧缓存键零序列化复用。"""
        self.trainee_receive_state()
        with self._trainee_receive_cache_lock:
            return int(self._trainee_receive_revision)

    def set_trainee_receive_state(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock:
            if not self._service_instance_active_locked():
                raise RuntimeError("学员台接收请求所属模型生命周期已失效或已退休。")
            existing = self.trainee_receive_state()
            merged = {**existing, **dict(payload)}
            if "updated_at" not in payload and "updatedAt" not in payload:
                merged["updated_at"] = _now_text()
            normalized = self._normalize_trainee_receive_state(merged)
            _write_json(self.trainee_receive_file, normalized)
            try:
                stat = self.trainee_receive_file.stat()
                signature: Optional[Tuple[int, int, int]] = (
                    int(stat.st_mtime_ns),
                    int(stat.st_ctime_ns),
                    int(stat.st_size),
                )
            except OSError:
                signature = None
            with self._trainee_receive_cache_lock:
                self._trainee_receive_cache_signature = signature
                self._trainee_receive_cache_value = normalized
                self._trainee_receive_cache_next_stat_monotonic = time.monotonic() + 0.25
                self._trainee_receive_revision += 1
            return dict(normalized)

    def _apply_stored_system_parameters(self) -> None:
        params = self.local_settings.get("system_parameters", {})
        if not (type(params) is dict or isinstance(params, Mapping)):
            return
        self.clock.step_minutes = 1.0 / 60.0
        if "clock_speed" in params or "speed" in params:
            self.clock.speed = _nearest_clock_speed(params.get("clock_speed", params.get("speed")))
        if "compute_interval_seconds" in params or "calculation_period_seconds" in params:
            self.compute_interval_seconds = _compute_interval_seconds(
                params.get("compute_interval_seconds", params.get("calculation_period_seconds")),
                self.compute_interval_seconds,
            )
        if "storage_initial_soc" in params or "initial_storage_soc" in params:
            self.storage_initial_soc = _storage_initial_soc(
                params.get("storage_initial_soc", params.get("initial_storage_soc")),
                self.storage_initial_soc,
            )
        if "remote_adjustment_response_ratio" in params or "adjustment_response_ratio" in params:
            self.remote_adjustment_response_ratio = _remote_adjustment_response_ratio(
                params.get(
                    "remote_adjustment_response_ratio",
                    params.get("adjustment_response_ratio"),
                ),
                self.remote_adjustment_response_ratio,
            )

    def system_parameters(self) -> Dict[str, Any]:
        effective_step_minutes = _effective_clock_step(self.clock.step_minutes, self.clock.speed)
        return {
            "clock_speed": _nearest_clock_speed(self.clock.speed),
            "compute_interval_seconds": self.compute_interval_seconds,
            "storage_initial_soc": self.storage_initial_soc,
            "remote_adjustment_response_ratio": self.remote_adjustment_response_ratio,
            "clock_step_seconds": self.clock.step_minutes * 60.0,
            "clock_step_minutes": self.clock.step_minutes,
            "effective_step_seconds": effective_step_minutes * 60.0,
            "effective_step_minutes": effective_step_minutes,
        }

    def simulation_timing(self) -> Dict[str, float]:
        parameters = self.system_parameters()
        return {
            "simulation_step_seconds": float(parameters["effective_step_seconds"]),
            "simulation_period_seconds": float(self.compute_interval_seconds),
        }

    def set_system_parameters(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock:
            timing_keys = {
                "clock_speed",
                "speed",
                "simulation_speed",
                "compute_interval_seconds",
                "calculation_period_seconds",
            }
            if timing_keys.intersection(payload):
                self.clock.step_minutes = 1.0 / 60.0
            if "clock_speed" in payload or "speed" in payload or "simulation_speed" in payload:
                self.clock.speed = _nearest_clock_speed(
                    payload.get("clock_speed", payload.get("speed", payload.get("simulation_speed")))
                )
            if "compute_interval_seconds" in payload or "calculation_period_seconds" in payload:
                self.compute_interval_seconds = _compute_interval_seconds(
                    payload.get("compute_interval_seconds", payload.get("calculation_period_seconds")),
                    self.compute_interval_seconds,
                )
            if "storage_initial_soc" in payload or "initial_storage_soc" in payload:
                self.storage_initial_soc = _storage_initial_soc(
                    payload.get("storage_initial_soc", payload.get("initial_storage_soc")),
                    self.storage_initial_soc,
                )
            if "remote_adjustment_response_ratio" in payload or "adjustment_response_ratio" in payload:
                self.remote_adjustment_response_ratio = _remote_adjustment_response_ratio(
                    payload.get(
                        "remote_adjustment_response_ratio",
                        payload.get("adjustment_response_ratio"),
                    ),
                    self.remote_adjustment_response_ratio,
                )

            effective_step = _effective_clock_step(self.clock.step_minutes, self.clock.speed)
            # 仅调整系统参数（如切换时钟倍率）时不强行跳改当前仿真时刻，保证时钟单调连续不跳空。
            self.clock.minute = self.clock.absolute_minute % 1440.0
            self.clock.updated_at = time.time()

            stored_params = self.local_settings.get("system_parameters", {})
            params = dict(stored_params) if (type(stored_params) is dict or isinstance(stored_params, Mapping)) else {}
            params.update(
                {
                    "clock_speed": self.clock.speed,
                    "compute_interval_seconds": self.compute_interval_seconds,
                    "storage_initial_soc": self.storage_initial_soc,
                    "remote_adjustment_response_ratio": self.remote_adjustment_response_ratio,
                }
            )
            self.local_settings["system_parameters"] = params
            _write_json(self.settings_file, self.local_settings)
            self._append_runtime_log(
                "参数配置",
                "系统参数",
                "已更新",
                [
                    f"仿真步长/加速比 x{format_number(self.clock.speed)}",
                    f"仿真周期 {format_number(self.compute_interval_seconds)} s",
                    f"储能SOC初始值 {format_number(self.storage_initial_soc * 100.0)}%",
                    f"遥调指令响应系数 {format_number(self.remote_adjustment_response_ratio)}",
                    f"每次计算推进 {format_number(effective_step * 60.0)} s",
                ],
                level="ok",
                simu_time=minute_to_time(self.clock.minute),
            )
            return {"system_parameters": self.system_parameters(), "clock": self.clock.as_dict()}

    def _simulation_cycle_minutes(self) -> int:
        return int(_simulation_mode_duration_minutes(self.curves.get("mode", "day")))

    def _crossed_simulation_cycle_start(self, start_minute: int | float, end_minute: int | float) -> bool:
        cycle_minutes = float(self._simulation_cycle_minutes())
        start = max(0.0, float(start_minute))
        end = max(0.0, float(end_minute))
        if end <= start:
            return False
        return math.floor((end + 1e-9) / cycle_minutes) > math.floor((start + 1e-9) / cycle_minutes)

    @staticmethod
    def _write_boundary_set_value(book: EBook, key: Tuple[str, str, str], value: float) -> None:
        block = _ensure_block(book, "SetValue", STAT_HEADERS["SetValue"])
        row = _find_set_row(block, *key)
        if row is None:
            row = {
                "dev_type": key[0],
                "dev_name": key[1],
                "set_type": key[2],
                "set_value": "",
            }
            block.data.append(row)
        row["set_value"] = _number_text(value)

    def _make_config(
        self,
        period_seconds: Optional[float] = None,
        *,
        dev_stat_book: Optional[EBook] = None,
        yt_ctrl_book: Optional[EBook] = None,
    ) -> simu_loop.SimulationConfig:
        definition_snapshot = self.definition_snapshot
        if self._measurement_bindings_cache_revision != definition_snapshot.revision:
            self._measurement_bindings_cache = simu_loop.compile_measurement_bindings(
                definition_snapshot.measurement_rows,
                definition_snapshot.model_book,
            )
            self._measurement_bindings_cache_revision = definition_snapshot.revision
        return simu_loop.SimulationConfig(
            model_file=self.files["model"],
            meas_file=self.files["meas"],
            weather_file=self.files["weather"],
            dev_stat_file=self.files["stat"],
            dev_define_file=None,
            mode_file=None,
            yt_ctrl_file=self.files["yt_ctrl"],
            real_file=self.files["real"],
            scada_file=self.files["scada"],
            period_seconds=self.period_seconds if period_seconds is None else period_seconds,
            noise_std=self.noise_std,
            random_seed=self.random_seed,
            loop_count=1,
            log_file=None,
            step_mode=True,
            write_output_files=False,
            model_book=definition_snapshot.model_book,
            meas_before=list(definition_snapshot.measurement_before),
            meas_rows=[list(row) for row in definition_snapshot.measurement_rows],
            meas_after=list(definition_snapshot.measurement_after),
            weather_book=simu_loop._clone_ebook(self.weather_book),
            dev_stat_book=simu_loop._clone_ebook(dev_stat_book or self.runtime_stat_book),
            yt_ctrl_book=simu_loop._clone_ebook(yt_ctrl_book or self.yt_ctrl_book),
            dev_define_book=definition_snapshot.dev_define_book,
            mode_book=simu_loop._clone_ebook(self.mode_book) if self.mode_book is not None else None,
            measurement_bindings=self._measurement_bindings_cache,
            measurement_median_deviations=_measurement_median_deviation_map(
                definition_snapshot
            ),
        )

    def _record_compute_execution(self, execution: PowerFlowExecution, status: str = "ok") -> None:
        self.latest_compute = {
            "mode": execution.mode,
            "http_pid": os.getpid(),
            "worker_pid": int(execution.worker_pid),
            "compute_ms": round(max(0.0, execution.compute_seconds) * 1000.0, 3),
            "round_trip_ms": round(max(0.0, execution.round_trip_seconds) * 1000.0, 3),
            "status": status,
            "resident_model": execution.mode == "embedded",
        }

    def _short_list(self, items: Sequence[str], limit: int = 24) -> str:
        if not items:
            return "无"
        visible = list(items[:limit])
        if len(items) > limit:
            visible.append(f"... 共 {len(items)} 项")
        return "，".join(visible)

    def _renewable_limit_boundary_lines(
        self,
        definition_snapshot: Optional[DefinitionSnapshot] = None,
    ) -> List[str]:
        active_snapshot = definition_snapshot or self.definition_snapshot
        weather = simu_loop._weather_values_from_book(self.weather_book)
        model_book = self._load_flow_input_model_book(active_snapshot)
        if model_book is None:
            return ["新能源限值 未读取到潮流输入模型"]
        device_book = active_snapshot.dev_define_book
        if not device_book.data:
            return ["新能源限值 未读取到 model.e 内的设备能力参数"]

        wind_count = 0
        wind_available_total = 0.0
        wind_execute_total = 0.0
        wind_speed = weather.get("wind_speed_mps")
        if wind_speed is not None:
            for _table_name, row, define, _pos in simu_loop._renewable_target_rows(
                model_book,
                device_book,
                "wind_generator",
                ("ACGenerator", "DCGenerator"),
            ):
                rated = simu_loop._wind_rated_power_kw(row, define)
                rated_speed = simu_loop._safe_float((define or {}).get("rated_wind_speed", 15.0), 15.0) or 15.0
                cut_in = simu_loop._safe_float((define or {}).get("cut_in_speed", 5.0), 5.0) or 5.0
                cut_out = simu_loop._safe_float((define or {}).get("cut_out_speed", 30.0), 30.0) or 30.0
                available = simu_loop._available_with_bounds(
                    simu_loop.wind_available_power(float(wind_speed), rated, rated_speed, cut_in, cut_out),
                    define,
                )
                column = "p_ac_set" if "p_ac_set" in row else "p_set"
                wind_count += 1
                wind_available_total += float(available)
                wind_execute_total += abs(_to_float(row.get(column), 0.0) or 0.0)

        pv_count = 0
        pv_available_total = 0.0
        pv_execute_total = 0.0
        irradiance = weather.get("solar_irradiance_w_m2")
        if irradiance is not None:
            air_temp = float(weather.get("air_temp_c", 25.0))
            for _table_name, row, define, _pos in simu_loop._renewable_target_rows(
                model_book,
                device_book,
                "pv_generator",
                ("ACGenerator", "DCGenerator"),
            ):
                rated = simu_loop._pv_rated_power_kw(row, define)
                temp_coef = simu_loop._safe_float((define or {}).get("temp_coefficient", 0.0), 0.0) or 0.0
                ref_irrad = simu_loop._safe_float((define or {}).get("reference_irradiance", 1000.0), 1000.0) or 1000.0
                ref_temp = simu_loop._safe_float((define or {}).get("reference_temperature", 25.0), 25.0) or 25.0
                available = simu_loop._available_with_bounds(
                    simu_loop.pv_available_power(float(irradiance), air_temp, rated, temp_coef, ref_irrad, ref_temp),
                    define,
                )
                pv_count += 1
                pv_available_total += float(available)
                pv_execute_total += abs(_to_float(row.get("p_set"), 0.0) or 0.0)

        wind_summary = (
            "风电 风速未知，未执行最大可发限值计算"
            if wind_speed is None
            else f"风电 {wind_count} 台，可用 {format_number(wind_available_total)} kW，执行 {format_number(wind_execute_total)} kW"
        )
        pv_summary = (
            "光伏 辐照未知，未执行最大可发限值计算"
            if irradiance is None
            else f"光伏 {pv_count} 台，可用 {format_number(pv_available_total)} kW，执行 {format_number(pv_execute_total)} kW"
        )
        return [
            f"新能源限值 {wind_summary}；{pv_summary}"
        ]

    def _input_boundary_lines(
        self,
        minute: int | float,
        absolute_minute: int | float,
        clock_advance: int | float,
        period_seconds: float,
    ) -> List[str]:
        weather = self._weather_boundary_values()
        stat_book = self.runtime_stat_book
        run_rows = list(getattr(stat_book.data.get("RunStat"), "data", []))
        cb_rows = list(getattr(stat_book.data.get("CbOpenStat"), "data", []))
        set_rows = list(getattr(stat_book.data.get("SetValue"), "data", []))
        soc_block = stat_book.data.get("StorageSoc") or stat_book.data.get("StorageStatus")
        soc_rows = list(getattr(soc_block, "data", []))

        run_off = [row for row in run_rows if int(_to_float(row.get("run_stat"), 1) or 0) == 0]
        cb_zero = [
            row
            for row in cb_rows
            if int(_to_float(simu_loop.closed_status_set_value(row, 1), 1) or 0) == 0
        ]
        run_on = len(run_rows) - len(run_off)
        cb_one = len(cb_rows) - len(cb_zero)
        weather_text = (
            f"风速 {_value_with_unit(weather.get('wind_speed_mps', ''), 'm/s')}，"
            f"辐照 {_value_with_unit(weather.get('solar_irradiance_w_m2', ''), 'W/m2')}，"
            f"气温 {_value_with_unit(weather.get('air_temp_c', ''), '℃')}，"
            f"负荷 {_value_with_unit(weather.get('load_kw', ''), 'kW')}"
            if weather
            else "未读取到 Weather 块"
        )
        return [
            (
                f"仿真边界 时刻 {minute_to_time(minute)}，日内分钟 {format_number(minute)}，"
                f"累计分钟 {format_number(absolute_minute)}，本步推进 {format_number(clock_advance * 60.0)} s，"
                f"等效计算周期 {format_number(period_seconds)} s"
            ),
            f"输入边界 {weather_text}；投入设备 {run_on}/{len(run_rows)}，退出 {len(run_off)}，开关合位 {cb_one}/{len(cb_rows)}，分位 {len(cb_zero)}，设值 {len(set_rows)} 条，储能SOC {len(soc_rows)} 条",
            *self._renewable_limit_boundary_lines(),
        ]

    def _internal_power_converter_keys(
        self,
        definition_snapshot: Optional[DefinitionSnapshot] = None,
    ) -> set[Tuple[str, str]]:
        active_snapshot = definition_snapshot or self.definition_snapshot
        cached = self._internal_power_converter_keys_cache
        if cached is not None and cached[0] == active_snapshot.revision:
            return cached[1]

        model_book = active_snapshot.model_book
        boundary_keys = grid_converter_keys(model_book)
        keys: set[Tuple[str, str]] = set()
        for converter_type in ("ACDCConverter", "DCACConverter"):
            for row in getattr(model_book.data.get(converter_type), "data", []):
                name = str(row.get("name", "")).strip()
                if name and (converter_type, name) not in boundary_keys:
                    keys.add((converter_type, name))

        self._internal_power_converter_keys_cache = (active_snapshot.revision, keys)
        return keys

    def _preferred_power_value(self, category: str, values: Mapping[str, float]) -> Optional[float]:
        preferences = {
            "wind": ("P_AC", "P_DC", "P_GEN", "P", "P_FROM", "P_TO"),
            "pv": ("P_TO", "P_FROM", "P_GEN", "P", "P_DC", "P_AC"),
            "diesel": ("P_GEN", "P", "P_AC", "P_TO", "P_FROM"),
            "load": ("P_LOAD", "P", "P_AC", "P_TO", "P_FROM"),
            "storage": ("P", "P_GEN", "P_FROM", "P_TO"),
            "fuelCell": ("P", "P_GEN", "P_DC", "P_AC"),
            "electrolyzer": ("P", "P_LOAD", "P_AC", "P_DC"),
        }
        for meas_type in preferences.get(category, ("P",)):
            if meas_type in values:
                return values[meas_type]
        return None

    def _flow_group_status(self, group: Mapping[str, Any]) -> Tuple[str, str]:
        total_count = int(group.get("totalCount", 0) or 0)
        online_count = int(group.get("onlineCount", 0) or 0)
        retired_count = int(group.get("retiredCount", 0) or 0)
        dead_count = int(group.get("deadIslandCount", 0) or 0)
        if total_count and online_count == 0:
            if dead_count:
                return "deadIsland", "idle"
            if retired_count:
                return "retired", "idle"
        category = str(group.get("category", ""))
        if category == "hydrogenStorage":
            gas_flow = group.get("gasFlow")
            if gas_flow is None:
                return "unmeasured", "idle"
            gas_flow_value = float(gas_flow)
            if abs(gas_flow_value) <= 1e-9:
                return "idle", "idle"
            return (
                ("releasingHydrogen", "fromTank")
                if gas_flow_value > 0.0
                else ("storingHydrogen", "toTank")
            )
        power = group.get("power")
        if power is None:
            return "unmeasured", "idle"
        power_value = float(power)
        if abs(power_value) <= 1e-9:
            return "idle", "idle"
        if category == "storage":
            return ("discharge", "toBus") if power_value > 0 else ("charge", "fromBus")
        if category in {"load", "electrolyzer"}:
            return ("consumption", "fromBus") if power_value > 0 else ("generation", "toBus")
        if category == "converter":
            return ("dcToAc", "toAc") if power_value > 0 else ("acToDc", "toDc")
        return ("generation", "toBus") if power_value > 0 else ("absorption", "fromBus")

    def _expand_set_values(self, items: Iterable[Any]) -> List[Dict[str, Any]]:
        expanded: List[Dict[str, Any]] = []
        for item in items:
            if not (type(item) is dict or isinstance(item, Mapping)):
                continue
            if "set_type" in item:
                expanded.append(dict(item))
                continue
            for key in (
                "p_set",
                "q_set",
                "v_set",
                "p_ac_set",
                "q_ac_set",
                "v_ac_set",
                "p_dc_set",
                "q_dc_set",
                "v_dc_set",
            ):
                if key in item:
                    expanded.append(
                        {
                            "dev_type": item.get("dev_type", item.get("type", "")),
                            "dev_name": item.get("dev_name", item.get("name", "")),
                            "set_type": key,
                            "set_value": item[key],
                        }
                    )
        return expanded

    def set_local_settings(self, payload: Mapping[str, Any]) -> Dict[str, int]:
        with self.lock:
            measurement_cache_changed = False
            aliases = {
                "device_faults": ("device_faults", "deviceFaults", "faults"),
                "measurement_faults": ("measurement_faults", "measurementFaults", "meas_faults"),
                "measurement_statuses": ("measurement_statuses", "measurementStatuses"),
                "modes": ("modes", "device_modes", "deviceModes"),
            }
            for target_key, names in aliases.items():
                for name in names:
                    if name in payload:
                        value = payload.get(name) or []
                        if target_key == "measurement_statuses":
                            normalized_value = dict(value) if (type(value) is dict or isinstance(value, Mapping)) else {}
                        else:
                            normalized_value = list(value) if isinstance(value, Sequence) else []
                        if self.local_settings.get(target_key) != normalized_value:
                            self.local_settings[target_key] = normalized_value
                            if target_key in {"measurement_faults", "measurement_statuses"}:
                                measurement_cache_changed = True
                        break
            if measurement_cache_changed:
                self._invalidate_measurement_delta_cache()
            _write_json(self.settings_file, self.local_settings)
            return {
                "device_faults": len(self.local_settings.get("device_faults", [])),
                "measurement_faults": len(self.local_settings.get("measurement_faults", [])),
                "measurement_statuses": len(self.local_settings.get("measurement_statuses", {})),
                "modes": len(self.local_settings.get("modes", [])),
            }

    def _prepare_runtime_inputs(
        self,
        minute: int | float,
        absolute_minute: int | float,
        *,
        remote_adjustment_cycle_token: Optional[int] = None,
        period_seconds: Optional[float] = None,
        defer_remote_adjustment_commit: bool = False,
    ) -> Any:
        if remote_adjustment_cycle_token is None:
            self._remote_adjustment_cycle_seq += 1
            remote_adjustment_cycle_token = self._remote_adjustment_cycle_seq
        self._write_current_weather(minute, absolute_minute)
        self._materialize_active_control_commands(absolute_minute)
        self._apply_device_faults(minute, absolute_minute)
        self._write_modes_file()
        return self._remote_adjustment_boundary_books(
            absolute_minute,
            remote_adjustment_cycle_token,
            period_seconds=period_seconds,
            return_next_state=defer_remote_adjustment_commit,
        )

    def _current_signal_values(self) -> Dict[Tuple[str, str, str], float]:
        run_stats, cb_status, _set_values, _soc_values = self._stat_maps()
        values: Dict[Tuple[str, str, str], float] = {}
        for (dev_type, dev_name), value in run_stats.items():
            number = _to_float(value, None)
            if number is not None:
                values[(dev_type, dev_name, "RUN_STAT")] = number
        for (dev_type, dev_name), value in cb_status.items():
            number = _to_float(value, None)
            if number is not None:
                values[(dev_type, dev_name, "STATUS")] = number
        return simu_loop._effective_signal_measurement_values(
            values,
            self.latest_device_states,
        )

    def _latest_telemetry_items(self) -> List[Dict[str, Any]]:
        measurements = dict(self.latest_measurements or self.measurements())
        measurements = self._with_realtime_measurements(measurements)
        items: List[Dict[str, Any]] = []
        signal_keys: set[Tuple[str, str, str]] = set()
        for row in measurements.get("scada", []):
            name = str(row.get("name", "")).strip() or ".".join(
                str(row.get(key, "")).strip()
                for key in ("dev_type", "dev_name", "meas_type")
                if str(row.get(key, "")).strip()
            )
            if not name:
                continue
            is_signal = self._is_signal_measurement_row(row)
            if is_signal:
                signal_keys.add(self._signal_measurement_key(row))
            signal_value = int(_to_float(row.get("value"), 0) or 0)
            items.append(
                {
                    "name": name,
                    "point_type": "YX" if is_signal else "YC",
                    "category": "遥信" if is_signal else "遥测",
                    "dev_type": str(row.get("dev_type", "")),
                    "dev_name": str(row.get("dev_name", "")),
                    "meas_type": str(row.get("meas_type", "")),
                    "value": _json_scalar(row.get("value", 0.0)),
                    "valid": int(_to_float(row.get("valid"), 0) or 0),
                    "weight": _json_scalar(row.get("weight", "")),
                    **(
                        {
                            "text": (
                                ("闭合" if signal_value else "断开")
                                if str(row.get("meas_type", "")).upper() == "STATUS"
                                else ("投入" if signal_value else "退出")
                            )
                        }
                        if is_signal
                        else {}
                    ),
                }
            )

        for dev in self.devices():
            dev_type = str(dev.get("dev_type", ""))
            dev_name = str(dev.get("dev_name", ""))
            if not dev_type or not dev_name:
                continue
            run_key = (dev_type, dev_name, "RUN_STAT")
            if run_key not in signal_keys:
                run_stat = int(_to_float(dev.get("run_stat"), 0) or 0)
                items.append(
                    {
                        "name": automatic_point_name(dev_type, dev_name, "run_stat"),
                        "point_type": "YX",
                        "category": "遥信",
                        "dev_type": dev_type,
                        "dev_name": dev_name,
                        "meas_type": "run_stat",
                        "value": run_stat,
                        "valid": 1,
                        "text": "投入" if run_stat else "退出",
                    }
                )
            status_key = (dev_type, dev_name, "STATUS")
            if (
                status_key not in signal_keys
                and ("Switch" in dev_type or "Break" in dev_type or dev.get("raw", {}).get("status", "") not in ("", None))
            ):
                status = int(_to_float(dev.get("status"), 0) or 0)
                items.append(
                    {
                        "name": automatic_point_name(dev_type, dev_name, "status"),
                        "point_type": "YX",
                        "category": "遥信",
                        "dev_type": dev_type,
                        "dev_name": dev_name,
                        "meas_type": "status",
                        "value": status,
                        "valid": 1,
                        "text": "闭合" if status else "断开",
                    }
                )

        return items

    def latest_telemetry_values(self) -> Dict[str, Any]:
        """Return compact latest remote measurements and status points for external clients."""
        time_payload = self._api_time_payload()
        items = [
            self._compact_external_value_item(item, time_payload, include_valid=True)
            for item in self._latest_telemetry_items()
        ]
        return {
            **self._external_response_metadata(),
            "items": items,
            "values": {item["name"]: item.get("value") for item in items},
        }

    def selected_telemetry_values(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Return selected telemetry and signal values by requested point names."""
        yc_names = self._name_list_from_payload(
            payload,
            ("telemetry", "telemetries", "telemetry_names", "yc", "yc_names", "remote_measurements"),
        )
        yx_names = self._name_list_from_payload(
            payload,
            ("signals", "signal_names", "yx", "yx_names", "statuses", "status_names", "remote_signals"),
        )
        time_payload = self._api_time_payload()
        all_items = self._latest_telemetry_items()
        yc_index = {
            str(item.get("name", "")): item
            for item in all_items
            if (type(item) is dict or isinstance(item, Mapping)) and item.get("point_type") == "YC"
        }
        yx_index = {
            str(item.get("name", "")): item
            for item in all_items
            if (type(item) is dict or isinstance(item, Mapping)) and item.get("point_type") == "YX"
        }

        def pick(index: Mapping[str, Mapping[str, Any]], names: Sequence[str]) -> List[Dict[str, Any]]:
            rows: List[Dict[str, Any]] = []
            for name in names:
                item = index.get(name)
                if item is None:
                    rows.append(
                        {
                            "name": name,
                            "value": None,
                            **self._external_update_time_fields(time_payload),
                            "found": False,
                            "valid": 0,
                        }
                    )
                else:
                    rows.append(
                        self._compact_external_value_item(
                            item | {"found": True},
                            time_payload,
                            include_found=True,
                            include_valid=True,
                        )
                    )
            return rows

        telemetry = pick(yc_index, yc_names)
        signals = pick(yx_index, yx_names)
        return {
            **self._external_response_metadata(),
            "telemetry": telemetry,
            "signals": signals,
            "yc": telemetry,
            "yx": signals,
            "items": [*telemetry, *signals],
            "values": {item["name"]: item.get("value") for item in [*telemetry, *signals]},
            "missing": {
                "telemetry": [item["name"] for item in telemetry if not item.get("found")],
                "signals": [item["name"] for item in signals if not item.get("found")],
            },
        }

    @staticmethod
    def _manual_change_value_text(value: Any) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _manual_change_values_equal(left: Any, right: Any) -> bool:
        left_text = str(left if left is not None else "").strip()
        right_text = str(right if right is not None else "").strip()
        if left_text == right_text:
            return True
        try:
            left_number = float(left_text[:-1].strip() if left_text.endswith("%") else left_text)
            right_number = float(right_text[:-1].strip() if right_text.endswith("%") else right_text)
        except (TypeError, ValueError):
            return False
        return math.isfinite(left_number) and math.isfinite(right_number) and math.isclose(
            left_number,
            right_number,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )

    def _set_manual_change_sync_state_unlocked(
        self,
        item: Dict[str, Any],
        *,
        persisted: bool,
        error: str = "",
        increment_retry: bool = False,
    ) -> None:
        item["persisted"] = bool(persisted)
        item["persistence_status"] = self._manual_change_persistence_status(persisted)
        item["sync_status"] = "synced" if persisted else "failed"
        item["last_sync_time"] = _now_text()
        item["last_sync_error"] = "" if persisted else str(error or "人工覆盖层保存失败")
        retry_count = int(_to_float(item.get("retry_count"), 0) or 0)
        item["retry_count"] = retry_count + (1 if increment_retry else 0)

    @staticmethod
    def _manual_change_sigma(weight: Any) -> Optional[float]:
        number = _to_float(weight, None)
        if number is None or number <= 0:
            return None
        return 1.0 / math.sqrt(number)

    @staticmethod
    def _manual_change_id(kind: str, identity: Mapping[str, Any], field_name: str) -> str:
        canonical = json.dumps(
            {
                "kind": str(kind),
                "identity": {str(key): str(value) for key, value in sorted(identity.items())},
                "field": str(field_name),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        return f"{kind}-{digest}"

    def _current_manual_change_value(
        self,
        item: Mapping[str, Any],
        snapshot: Optional[DefinitionSnapshot] = None,
    ) -> Optional[str]:
        active = snapshot or self.definition_snapshot
        kind = str(item.get("kind", ""))
        field_name = str(item.get("field", ""))
        if kind == "device":
            block = active.model_book.data.get(str(item.get("block_name", "")))
            if block is None or field_name not in block.header_list:
                return None
            row = self._definition_row(block, item.get("row_key", {}))
            return self._manual_change_value_text(row.get(field_name, ""))
        if kind == "measurement":
            index, _record = self._measurement_definition_row(
                active.measurement_rows,
                {"name": item.get("measurement_name", "")},
            )
            column = {"weight": 5, "valid": 6}.get(field_name)
            if column is not None:
                return self._manual_change_value_text(active.measurement_rows[index][column])
            if field_name == "median_deviation":
                values = _measurement_median_deviation_map(active)
                return self._manual_change_value_text(
                    values.get(str(item.get("measurement_name", "")), 0.0)
                )
            if field_name in {"status", "fixed_value"}:
                status, fixed_value = self._measurement_status_override(
                    active.measurement_rows[index]
                )
                return self._manual_change_value_text(
                    status if field_name == "status" else fixed_value
                )
            return None
        return None

    @staticmethod
    def _upsert_runtime_status_value(
        book: EBook,
        dev_type: str,
        dev_name: str,
        field_name: str,
        value: Any,
    ) -> None:
        normalized_field = str(field_name or "").strip().casefold()
        if normalized_field not in RUNTIME_CONTROL_STATUS_FIELDS:
            return
        block_name = "RunStat" if normalized_field == "run_stat" else "CbOpenStat"
        block = _ensure_block(book, block_name, STAT_HEADERS[block_name])
        if block_name == "CbOpenStat":
            simu_loop.ensure_closed_status_rows_book(book)
        row = _find_dev_row(block, dev_type, dev_name)
        if row is None:
            row = {
                "dev_type": dev_type,
                "dev_name": dev_name,
                **(
                    {"run_stat": ""}
                    if normalized_field == "run_stat"
                    else {
                        "closed_status_set": "",
                        "closed_status": "",
                        "status": "",
                    }
                ),
            }
            block.data.append(row)
        target_field = (
            normalized_field
            if normalized_field == "run_stat"
            else "closed_status_set"
        )
        row[target_field] = _number_text(value)

    def _stat_maps(
        self,
    ) -> Tuple[
        Dict[Tuple[str, str], Any],
        Dict[Tuple[str, str], Any],
        Dict[Tuple[str, str], dict],
        Dict[Tuple[str, str], float],
    ]:
        stat_book = self.runtime_stat_book
        run_stats: Dict[Tuple[str, str], Any] = {}
        cb_status: Dict[Tuple[str, str], Any] = {}
        set_values: Dict[Tuple[str, str], dict] = {}
        soc_values = self._runtime_storage_soc_values()
        for row in getattr(stat_book.data.get("RunStat"), "data", []):
            run_stats[(str(row.get("dev_type", "")), _dev_name(row))] = row.get("run_stat", "")
        for row in getattr(stat_book.data.get("CbOpenStat"), "data", []):
            cb_status[(str(row.get("dev_type", "")), _dev_name(row))] = (
                simu_loop.closed_status_value(row, "")
            )
        for row in getattr(stat_book.data.get("SetValue"), "data", []):
            key = (str(row.get("dev_type", "")), _dev_name(row))
            set_values.setdefault(key, {})[str(row.get("set_type", ""))] = row.get("set_value", "")
        return run_stats, cb_status, set_values, soc_values

    def _closed_status_set_map(self) -> Dict[Tuple[str, str], Any]:
        return {
            (str(row.get("dev_type", "")), _dev_name(row)): (
                simu_loop.closed_status_set_value(row, "")
            )
            for row in getattr(
                self.runtime_stat_book.data.get("CbOpenStat"),
                "data",
                [],
            )
        }

    def _path_static_signature(self, paths: Sequence[Path | str | None]) -> Dict[str, Any]:
        signatures: List[str] = []
        for index, raw_path in enumerate(paths):
            if raw_path is None:
                signatures.append(f"{index}:<none>:0:0:0")
                continue
            path = Path(raw_path)
            try:
                stat = path.stat()
            except OSError:
                signatures.append(f"{index}:{path.name}:0:0:0")
                continue
            signatures.append(f"{index}:{path.name}:1:{stat.st_size}:{stat.st_mtime_ns}")
        return {"signature": "|".join(signatures)}

    def _path_mapping_signature(self, paths: Sequence[Path | str | None]) -> Dict[str, Any]:
        """Version a path mapping without coupling it to mutable file contents."""

        signatures: List[str] = []
        for index, raw_path in enumerate(paths):
            if raw_path is None:
                signatures.append(f"{index}:<none>")
                continue
            path = Path(raw_path).resolve(strict=False)
            signatures.append(f"{index}:{path}")
        return {"signature": "|".join(signatures)}

    def static_meta(self) -> Dict[str, Any]:
        definition_revision = self.definition_snapshot.revision
        definition_paths = [
            self.source_files.get("model"),
            self.source_files.get("meas"),
            self.source_files.get("stat"),
            self.source_files.get("control"),
            self.source_files.get("weather"),
        ]
        definitions_meta = self._path_static_signature(definition_paths)
        definitions_meta["revision"] = definition_revision
        device_parameters_meta = self._path_static_signature([self.source_files.get("model")])
        device_parameters_meta["revision"] = definition_revision
        return {
            "files": self._path_mapping_signature(list(self.files.values())),
            "source_files": self._path_mapping_signature(list(self.source_files.values())),
            "work_files": self._path_mapping_signature(list(self.work_files.values())),
            "definitions": definitions_meta,
            "curves": self._path_static_signature([self.source_curves_file, self.curves_file]),
            "settings": self._path_static_signature([self.sim_dir / "local_settings.json", self.settings_file]),
            "device_parameters": device_parameters_meta,
            "diagram": self._path_static_signature([self.source_files.get("diagram")]),
        }


class MultiModelSimulator:
    """Owns independent simulator instances for multiple model cases."""

    def __init__(
        self,
        specs: Sequence[SimulationModelSpec | Mapping[str, Any]],
        runtime_dir: str | Path,
        kernel: Optional[Callable[[simu_loop.SimulationConfig], Optional[simu_loop.SimulationResult]]] = None,
        *,
        kernel_runner: Optional[Any] = None,
        period_seconds: float = 60.0,
        compute_interval_seconds: float = DEFAULT_COMPUTE_INTERVAL_SECONDS,
        noise_std: Optional[float] = None,
        random_seed: Optional[int] = None,
        models_root: str | Path | None = None,
        directory_backed: bool = False,
        runtime_role: str = "",
    ) -> None:
        self.runtime_dir = Path(runtime_dir).resolve()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        normalized_specs = self._unique_specs([self._normalize_spec(raw_spec) for raw_spec in specs])
        self.models_root = Path(models_root).resolve() if models_root else self._infer_models_root(normalized_specs)
        self.models_root.mkdir(parents=True, exist_ok=True)
        self.directory_backed = directory_backed
        self.runtime_role = str(runtime_role or "").strip().lower()
        self.clear_commands_on_start_and_reset = self.runtime_role == "simulator"
        self.enforce_runtime_setpoint_bounds = True
        self.kernel = kernel
        self.kernel_runner = kernel_runner
        self.period_seconds = period_seconds
        self.compute_interval_seconds = _compute_interval_seconds(compute_interval_seconds)
        self.noise_std = noise_std
        self.random_seed = random_seed
        self._services: Dict[str, PolarMicrogridSimulator] = {}
        self.lock = threading.RLock()
        self.default_model_id = ""
        self._directory_sync_interval_seconds = 1.0
        self._next_directory_sync_at = (
            time.monotonic() + self._directory_sync_interval_seconds
        )
        for spec in normalized_specs:
            if spec.model_id in self._services:
                raise ValueError(f"Duplicate simulation model id: {spec.model_id}")
            service = PolarMicrogridSimulator(
                sim_dir=spec.sim_dir,
                runtime_dir=self.runtime_dir / spec.model_id,
                kernel=kernel,
                kernel_runner=kernel_runner,
                period_seconds=period_seconds,
                compute_interval_seconds=self.compute_interval_seconds,
                noise_std=noise_std,
                random_seed=random_seed,
                model_id=spec.model_id,
                model_name=spec.name,
                clear_commands_on_start_and_reset=self.clear_commands_on_start_and_reset,
                enforce_runtime_setpoint_bounds=self.enforce_runtime_setpoint_bounds,
            )
            self._services[spec.model_id] = service
            if not self.default_model_id:
                self.default_model_id = spec.model_id
        if not self._services:
            raise ValueError("At least one simulation model is required")
        self.default_model_id = self._preferred_default_model_id(list(self._services), self.default_model_id)

    @staticmethod
    def _unique_specs(specs: Sequence[SimulationModelSpec]) -> List[SimulationModelSpec]:
        unique: List[SimulationModelSpec] = []
        seen_keys: set[str] = set()
        for spec in specs:
            keys = {_model_key(spec.model_id), _model_key(spec.name or spec.model_id)}
            if seen_keys.intersection(keys):
                continue
            unique.append(spec)
            seen_keys.update(keys)
        return unique

    @staticmethod
    def _infer_models_root(specs: Sequence[SimulationModelSpec]) -> Path:
        if not specs:
            return Path("models").resolve()
        parents = [Path(spec.sim_dir).resolve().parent for spec in specs]
        first = parents[0]
        if all(parent == first for parent in parents):
            return first
        return Path(specs[0].sim_dir).resolve().parent

    @staticmethod
    def _normalize_spec(raw_spec: SimulationModelSpec | Mapping[str, Any]) -> SimulationModelSpec:
        if isinstance(raw_spec, SimulationModelSpec):
            return raw_spec.normalized()
        model_id = raw_spec.get("id", raw_spec.get("model_id", raw_spec.get("name", "default")))
        sim_dir = raw_spec.get("sim_dir", raw_spec.get("path", raw_spec.get("dir", "")))
        name = str(raw_spec.get("label", raw_spec.get("display_name", raw_spec.get("name", model_id))))
        return SimulationModelSpec(str(model_id), Path(sim_dir), name).normalized()

    @classmethod
    def discover(
        cls,
        sim_dir: str | Path,
        runtime_dir: str | Path,
        kernel: Optional[Callable[[simu_loop.SimulationConfig], Optional[simu_loop.SimulationResult]]] = None,
        *,
        kernel_runner: Optional[Any] = None,
        period_seconds: float = 60.0,
        compute_interval_seconds: float = DEFAULT_COMPUTE_INTERVAL_SECONDS,
        noise_std: Optional[float] = None,
        random_seed: Optional[int] = None,
        models_dir: str | Path | None = None,
        runtime_role: str = "",
    ) -> "MultiModelSimulator":
        root = Path(sim_dir).resolve()
        models_root = Path(models_dir).resolve() if models_dir else root / "models"
        specs = cls._discover_specs(root, models_root)
        return cls(
            specs,
            runtime_dir=runtime_dir,
            kernel=kernel,
            kernel_runner=kernel_runner,
            period_seconds=period_seconds,
            compute_interval_seconds=compute_interval_seconds,
            noise_std=noise_std,
            random_seed=random_seed,
            models_root=models_root,
            directory_backed=True,
            runtime_role=runtime_role,
        )

    @staticmethod
    def _directory_specs(models_root: Path) -> List[SimulationModelSpec]:
        if not models_root.exists():
            return []
        return [
            SimulationModelSpec(child.name, child, child.name).normalized()
            for child in sorted(models_root.iterdir(), key=lambda path: path.name.casefold())
            if child.is_dir() and (child / "model.e").exists()
        ]

    @staticmethod
    def _preferred_default_model_id(model_ids: Sequence[str], fallback: str = "") -> str:
        for preferred in ("默认模型", "default"):
            for model_id in model_ids:
                if _model_key(model_id) == _model_key(preferred):
                    return model_id
        return fallback or (model_ids[0] if model_ids else "")

    @staticmethod
    def _discover_specs(root: Path, models_root: Path) -> List[SimulationModelSpec]:
        specs = MultiModelSimulator._directory_specs(models_root)
        if specs:
            return specs

        manifest = root / "models.json"
        if manifest.exists():
            payload = _read_json(manifest, [])
            items = payload.get("models", []) if (type(payload) is dict or isinstance(payload, Mapping)) else payload
            specs = [
                SimulationModelSpec(
                    str(item.get("id", item.get("model_id", item.get("name", "default")))),
                    root / str(item.get("sim_dir", item.get("path", item.get("dir", ".")))),
                    str(item.get("label", item.get("name", item.get("id", "default")))),
                ).normalized()
                for item in items
                if (type(item) is dict or isinstance(item, Mapping))
            ]
            if specs:
                return specs

        specs: List[SimulationModelSpec] = []
        if (root / "model.e").exists():
            specs.append(SimulationModelSpec("default", root, "默认模型").normalized())

        return specs or [SimulationModelSpec("default", root, "默认模型").normalized()]

    def _make_service(
        self,
        spec: SimulationModelSpec,
        *,
        clear_runtime: bool = False,
    ) -> PolarMicrogridSimulator:
        runtime_dir = self.runtime_dir / spec.model_id
        if clear_runtime:
            _clear_directory_contents(runtime_dir)
        return PolarMicrogridSimulator(
            sim_dir=spec.sim_dir,
            runtime_dir=runtime_dir,
            kernel=self.kernel,
            kernel_runner=self.kernel_runner,
            period_seconds=self.period_seconds,
            compute_interval_seconds=self.compute_interval_seconds,
            noise_std=self.noise_std,
            random_seed=self.random_seed,
            model_id=spec.model_id,
            model_name=spec.name,
            clear_commands_on_start_and_reset=self.clear_commands_on_start_and_reset,
            enforce_runtime_setpoint_bounds=self.enforce_runtime_setpoint_bounds,
        )

    @staticmethod
    def _retire_service_instance(service: PolarMicrogridSimulator) -> None:
        with service.lock:
            service._retire_service_instance_locked()

    def _sync_models_from_directory_locked(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now < self._next_directory_sync_at:
            return
        specs = self._unique_specs(self._directory_specs(self.models_root))
        self._next_directory_sync_at = now + self._directory_sync_interval_seconds
        if not specs:
            return
        ordered_ids: List[str] = []
        for spec in specs:
            ordered_ids.append(spec.model_id)
            if spec.model_id not in self._services:
                self._services[spec.model_id] = self._make_service(spec, clear_runtime=True)
            else:
                self._services[spec.model_id].model_name = spec.name
        for model_id, service in list(self._services.items()):
            if model_id not in ordered_ids:
                self._retire_service_instance(service)
        self._services = {model_id: self._services[model_id] for model_id in ordered_ids}
        if self.default_model_id not in self._services:
            self.default_model_id = self._preferred_default_model_id(ordered_ids)

    def clone_model(self, source_model_id: Optional[str], new_model_id: Any) -> Dict[str, Any]:
        with self.lock:
            source = self.service_for(source_model_id)
            target_id = self.validate_new_model_name(new_model_id)
            target_dir = (self.models_root / target_id).resolve()
            try:
                target_dir.relative_to(self.models_root)
            except ValueError as exc:
                raise ValueError(f"模型名称无效: {new_model_id}") from exc
            if target_dir.exists():
                raise ValueError(f"模型文件夹已存在: {target_id}")

            source.clone_files_to(target_dir)
            service = self._make_service(
                SimulationModelSpec(target_id, target_dir, target_id).normalized(),
                clear_runtime=True,
            )
            self._services[target_id] = service
            self._append_manifest_model(target_id, target_dir)
            return service.model_info()

    def create_model_slot(self, new_model_id: Any) -> Dict[str, Any]:
        """Create an uninitialized trainee model slot without importing user files."""
        with self.lock:
            target_id = self.validate_new_model_name(new_model_id)
            target_dir = (self.models_root / target_id).resolve()
            runtime_dir = (self.runtime_dir / target_id).resolve()
            try:
                target_dir.relative_to(self.models_root.resolve())
                runtime_dir.relative_to(self.runtime_dir.resolve())
            except ValueError as exc:
                raise ValueError(f"模型名称无效: {new_model_id}") from exc

            target_dir.mkdir(parents=True, exist_ok=False)
            try:
                for file_name in ("model.e", "meas.e", "stat.e", "control.e", "weather.e", "curves.e"):
                    (target_dir / file_name).write_text("", encoding="utf-8")
                _write_json(
                    target_dir / "curves.json",
                    {
                        "mode": "day",
                        "time_step_minutes": 1,
                        "point_count": 0,
                        "weather": [],
                        "loads": {},
                    },
                )
                (target_dir / DIAGRAM_FILE_NAME).write_text(
                    (
                        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 480">'
                        '<rect width="800" height="480" fill="#f7fafb"/>'
                        '<text x="400" y="240" text-anchor="middle" fill="#60727a" font-size="24">'
                        "Model not initialized"
                        "</text></svg>"
                    ),
                    encoding="utf-8",
                )
                service = self._make_service(
                    SimulationModelSpec(target_id, target_dir, target_id).normalized(),
                    clear_runtime=True,
                )
            except Exception:
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                if runtime_dir.exists():
                    shutil.rmtree(runtime_dir)
                raise

            self._services[target_id] = service
            self._append_manifest_model(target_id, target_dir)
            return service.model_info()

    def delete_model(self, model_id: Any) -> Dict[str, Any]:
        target_id = _safe_model_id(model_id)
        with self.lock:
            if self.directory_backed:
                self._sync_models_from_directory_locked(force=True)
            service = self._services.get(target_id)
            if service is None:
                raise KeyError(f"Unknown simulation model: {model_id}")
            if len(self._services) <= 1:
                raise ValueError("至少需要保留一个模型")
            with service.lock:
                if service.trainee_receive_state().get("active"):
                    raise ValueError(f"模型正在接收中，无法删除: {target_id}")
                if service.clock.state != "stopped":
                    raise ValueError(f"模型正在运行中，无法删除: {target_id}")
                source_dir = Path(service.sim_dir).resolve()
                runtime_dir = Path(service.runtime_dir).resolve()
                removed = service.model_info()
                service._retire_service_instance_locked()
                self._services.pop(target_id, None)

            models_root = self.models_root.resolve()
            runtime_root = self.runtime_dir.resolve()
            try:
                source_dir.relative_to(models_root)
                runtime_dir.relative_to(runtime_root)
            except ValueError as exc:
                raise ValueError(f"模型目录无效，无法删除: {target_id}") from exc

            if source_dir.exists():
                shutil.rmtree(source_dir)
            if runtime_dir.exists():
                shutil.rmtree(runtime_dir)
            self._remove_manifest_model(target_id)

            if self.default_model_id == target_id:
                remaining_ids = list(self._services)
                self.default_model_id = self._preferred_default_model_id(remaining_ids, remaining_ids[0])
            return {
                **removed,
                "deleted": True,
                "active_model_id": self.default_model_id,
            }

    def validate_new_model_name(self, new_model_id: Any) -> str:
        target_id = _safe_model_id(new_model_id)
        target_keys = {_model_key(new_model_id), _model_key(target_id)}
        with self.lock:
            if self.directory_backed:
                self._sync_models_from_directory_locked(force=True)
            existing_keys = {
                key
                for existing_service in self._services.values()
                for key in (_model_key(existing_service.model_id), _model_key(existing_service.model_name))
            }
            if existing_keys.intersection(target_keys):
                raise ValueError(f"模型已存在: {target_id}")
            target_dir = (self.models_root / target_id).resolve()
            try:
                target_dir.relative_to(self.models_root)
            except ValueError as exc:
                raise ValueError(f"模型名称无效: {new_model_id}") from exc
            if target_dir.exists():
                raise ValueError(f"模型文件夹已存在: {target_id}")
        return target_id

    def _append_manifest_model(self, model_id: str, sim_dir: Path) -> None:
        manifest = self.models_root.parent / "models.json"
        if not manifest.exists():
            return
        payload = _read_json(manifest, {"models": []})
        is_mapping = (type(payload) is dict or isinstance(payload, Mapping))
        items = payload.get("models", []) if is_mapping else payload
        if not isinstance(items, list):
            items = []
        if any((type(item) is dict or isinstance(item, Mapping)) and _safe_model_id(item.get("id", item.get("model_id", ""))) == model_id for item in items):
            return
        try:
            rel_dir = sim_dir.relative_to(self.models_root.parent).as_posix()
        except ValueError:
            rel_dir = str(sim_dir)
        items.append({"id": model_id, "name": model_id, "sim_dir": rel_dir})
        if is_mapping:
            payload = dict(payload)
            payload["models"] = items
        else:
            payload = items
        _write_json(manifest, payload)

    def _remove_manifest_model(self, model_id: str) -> None:
        manifest = self.models_root.parent / "models.json"
        if not manifest.exists():
            return
        payload = _read_json(manifest, {"models": []})
        is_mapping = (type(payload) is dict or isinstance(payload, Mapping))
        items = payload.get("models", []) if is_mapping else payload
        if not isinstance(items, list):
            return
        target_key = _model_key(model_id)
        next_items = [
            item
            for item in items
            if not (
                (type(item) is dict or isinstance(item, Mapping))
                and _model_key(item.get("id", item.get("model_id", item.get("name", "")))) == target_key
            )
        ]
        if len(next_items) == len(items):
            return
        if is_mapping:
            payload = dict(payload)
            payload["models"] = next_items
        else:
            payload = next_items
        _write_json(manifest, payload)

    def service_for(self, model_id: Optional[str] = None) -> PolarMicrogridSimulator:
        with self.lock:
            if self.directory_backed:
                self._sync_models_from_directory_locked()
            target = _safe_model_id(model_id or self.default_model_id)
            service = self._services.get(target)
            if service is None and self.directory_backed:
                # Cache misses may be a newly added external model. Refresh
                # immediately without making hot lookups rescan the directory.
                self._sync_models_from_directory_locked(force=True)
                service = self._services.get(target)
        if service is None:
            raise KeyError(f"Unknown simulation model: {model_id}")
        return service

    def iter_services(self) -> List[PolarMicrogridSimulator]:
        with self.lock:
            return list(self._services.values())

    def close(self) -> None:
        runner = self.kernel_runner
        if runner is not None and callable(getattr(runner, "close", None)):
            runner.close()

    def models(self) -> List[Dict[str, Any]]:
        with self.lock:
            if self.directory_backed:
                self._sync_models_from_directory_locked(force=True)
            return [service.model_info() for service in self._services.values()]

    def trainee_receive_states(self) -> Dict[str, Dict[str, Any]]:
        with self.lock:
            if self.directory_backed:
                self._sync_models_from_directory_locked()
            return {model_id: service.trainee_receive_state() for model_id, service in self._services.items()}

    def snapshot(
        self,
        model_id: Optional[str] = None,
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
        return self.service_for(model_id).snapshot(
            include_static=include_static,
            runtime_log_limit=runtime_log_limit,
            include_runtime_logs=include_runtime_logs,
            include_measurements=include_measurements,
            include_static_meta=include_static_meta,
            static_fields=static_fields,
            include_devices=include_devices,
            include_device_states=include_device_states,
            include_commands=include_commands,
            include_command_history=include_command_history,
        )

    def measurements(self, model_id: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        return self.service_for(model_id).measurements()

    def measurement_delta(
        self,
        after_seq: int | float = 0,
        model_id: Optional[str] = None,
        *,
        compact: bool = False,
    ) -> Dict[str, Any]:
        return self.service_for(model_id).measurement_delta(after_seq=after_seq, compact=compact)

    def measurement_history(
        self,
        *,
        indices: Optional[Sequence[int]] = None,
        after_seq: int | float = 0,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.service_for(model_id).measurement_history(
            indices=indices,
            after_seq=after_seq,
        )

    def runtime_logs_delta(
        self,
        after_seq: int | float = 0,
        *,
        limit: int = 100,
        before_seq: Optional[int | float] = None,
        log_type: str = "",
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.service_for(model_id).runtime_logs_delta(
            after_seq=after_seq,
            limit=limit,
            before_seq=before_seq,
            log_type=log_type,
        )

    def devices(self, model_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.service_for(model_id).devices()

    def device_states(self, model_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.service_for(model_id).device_states()

    def device_runtime_frame(self, model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).device_runtime_frame()

    def apply_student_commands(self, payload: Mapping[str, Any], source: str = "", model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).apply_student_commands(payload, source=source)

    def control_clock(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).control_clock(payload)

    def step(self, model_id: Optional[str] = None, advance_minutes: Optional[int] = None) -> Dict[str, Any]:
        return self.service_for(model_id).step(advance_minutes=advance_minutes)

    def set_curves(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).set_curves(payload)

    def curves_summary(self, model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).curves_summary()

    def curves_series(self, keys: Sequence[str], model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).curves_series(keys)

    def update_curve_series(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).update_curve_series(payload)

    def external_curves_query(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).external_curves_query(payload)

    def external_curves_update(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).external_curves_update(payload)

    def external_realtime_input_schema(self, model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.service_for(model_id).external_realtime_input_schema()

    def apply_external_realtime_inputs(
        self,
        payload: Mapping[str, Any],
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.service_for(model_id).apply_external_realtime_inputs(payload)

    def set_local_settings(self, payload: Mapping[str, Any], model_id: Optional[str] = None) -> Dict[str, int]:
        return self.service_for(model_id).set_local_settings(payload)
