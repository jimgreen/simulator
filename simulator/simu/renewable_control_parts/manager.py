"""renewable_control 拆分模块：学员台新能源实时控制生命周期管理器（TraineeRenewableControlManager）。"""

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
from .planner import *  # noqa: F401,F403
from .planner import (
    _COMPACT_TREND_FIELDS,
    _RENEWABLE_AUTO_RESUMED_STATUS,
    _RENEWABLE_READY_IDLE_STATUS,
    _TREND_ARRAY_ENCODING,
    _TREND_IDENTITY_FIELDS,
    _USER_CONTROL_BUSY_WAIT_SECONDS,
    _compact_decision_log_detail,
    _compact_log_number,
    _compact_plan_for_ui,
    _compact_trend_payload,
    _decision_log_level,
)


import logging

_TRAINEE_CTRL_LOG = logging.getLogger("simu.trainee.control")


class TraineeRenewableControlLifecycleError(RuntimeError):
    """Raised when a controller request outlives its captured model service."""

def _stale_receive_prerequisite_status(message: Any) -> bool:
    text = str(message or "").strip()
    return (
        "请先启动接收" in text
        or "等待第一份实时数据" in text
        or "接收已停止" in text
        or text.startswith("学员台实时交换状态不可用")
        or text.startswith("学员台尚未收到实时数据")
    )

@dataclass
class _ControllerState:
    model_id: str
    service_instance_id: str
    settings: RenewableControlSettings = field(default_factory=RenewableControlSettings)
    enabled: bool = False
    desired_enabled: bool = False
    loop_mode: str = "open"
    operation_epoch: int = 0
    sending: bool = False
    status: str = _RENEWABLE_READY_IDLE_STATUS
    last_plan: Optional[Dict[str, Any]] = None
    effective_target_snapshot: Optional[Dict[str, Any]] = None
    last_calculated_at: str = ""
    last_sent_at: str = ""
    last_clock_key: str = ""
    last_dispatched_clock_key: str = ""
    last_dispatched_generation_key: Tuple[Any, ...] = ()
    strategy_generation_active: bool = False
    strategy_cancel_pending: bool = False
    strategy_cancel_operation_epoch: int = 0
    pending_dispatch_clock_key: str = ""
    pending_dispatch_generation_key: Tuple[Any, ...] = ()
    last_auto_started: float = 0.0
    last_preview_started: float = 0.0
    control_clock_run_id: Optional[int] = None
    control_clock_anchor_second: Optional[float] = None
    control_clock_last_second: Optional[float] = None
    control_clock_last_step_count: Optional[int] = None
    background_cycle_pending: bool = False
    settings_revision: int = 1
    plan_revision: int = 0
    revision: int = 0
    log_seq: int = 0
    logs: List[Dict[str, Any]] = field(default_factory=list)
    trend: List[Dict[str, Any]] = field(default_factory=list)
    trend_normalized: bool = False
    topology_static_context: Optional[ResourceTopologyStaticContext] = field(
        default=None,
        repr=False,
    )
    topology_definition_revision: int = -1
    performance: _CyclePerformanceWindow = field(
        default_factory=_CyclePerformanceWindow,
        repr=False,
    )
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    run_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

@dataclass
class _TrendCandidate:
    trend: List[Dict[str, Any]]
    trend_normalized: bool
    persistence_reset: bool = False
    persistence_replace_last: bool = False
    persistence_point: Optional[Dict[str, Any]] = None

@dataclass(frozen=True)
class _SimulationControlClock:
    state: str
    run_id: int
    step_count: int
    absolute_second: float

class TraineeRenewableControlManager:
    """Model-scoped shared control state and background execution."""

    def __init__(
        self,
        services: Any,
        *,
        snapshot_provider: Callable[[Optional[str]], TraineeControlSnapshot],
        receive_status_provider: Callable[[Optional[str]], Mapping[str, Any]],
        command_sink: Callable[[Optional[str], Mapping[str, Any]], Mapping[str, Any]],
        start_worker: bool = True,
    ) -> None:
        self.services = services
        self.snapshot_provider = snapshot_provider
        self.receive_status_provider = receive_status_provider
        self.command_sink = command_sink
        self._states: Dict[str, _ControllerState] = {}
        self._states_by_service_instance: Dict[str, _ControllerState] = {}
        self._states_lock = threading.RLock()
        self._trend_persistence_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._close_lock = threading.Lock()
        self._background_submit_lock = threading.Lock()
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="renewable-control")
        self._worker: Optional[threading.Thread] = None
        if start_worker:
            self._worker = threading.Thread(target=self._worker_loop, name="trainee-renewable-control", daemon=True)
            self._worker.start()

    def close(self) -> None:
        current_thread = threading.current_thread()
        if current_thread is self._worker or current_thread.name.startswith("renewable-control_"):
            raise RuntimeError("新能源控制管理器不能从自身后台工作线程中关闭")
        with self._close_lock:
            if self._closed:
                return
            with self._background_submit_lock:
                self._closed = True
            self._stop_event.set()
            self._wake_worker()
            if self._worker and self._worker.is_alive():
                self._worker.join(timeout=3.0)
            # 配合 server_close 提前中断 exchange 在途 I/O，此处可快速回收工作线程。
            self._executor.shutdown(wait=False, cancel_futures=True)
            with self._states_lock:
                states_by_identity = {
                    id(state): state
                    for state in (
                        list(self._states.values())
                        + list(self._states_by_service_instance.values())
                    )
                }
                states = list(states_by_identity.values())
            for state in states:
                with state.lock:
                    state.background_cycle_pending = False

    def _wake_worker(self) -> None:
        self._wake_event.set()

    def _service_for(self, model_id: Optional[str]) -> Any:
        if hasattr(self.services, "service_for"):
            return self.services.service_for(model_id)
        return self.services

    def _service_is_current_registry_instance(self, service: Any) -> bool:
        if hasattr(self.services, "service_for"):
            try:
                current = self.services.service_for(
                    str(getattr(service, "model_id", "default"))
                )
            except KeyError:
                return False
            return current is service
        return self.services is service

    def _model_id(self, model_id: Optional[str]) -> str:
        service = self._service_for(model_id)
        return str(getattr(service, "model_id", model_id or "default"))

    @staticmethod
    def _service_instance_id(service: Any) -> str:
        value = str(getattr(service, "service_instance_id", "") or "").strip()
        return value or f"object:{id(service)}"

    @staticmethod
    def _service_instance_active_locked(service: Any) -> bool:
        checker = getattr(service, "_service_instance_active_locked", None)
        if callable(checker):
            return bool(checker())
        return not bool(getattr(service, "_service_instance_retired", False))

    @staticmethod
    def _persistence_path_for_service(service: Any) -> Optional[Path]:
        runtime_dir = getattr(service, "runtime_dir", None)
        return Path(runtime_dir) / RENEWABLE_CONTROL_STATE_FILE if runtime_dir else None

    @staticmethod
    def _trend_persistence_path_for_service(service: Any) -> Optional[Path]:
        runtime_dir = getattr(service, "runtime_dir", None)
        return Path(runtime_dir) / RENEWABLE_CONTROL_TREND_FILE if runtime_dir else None

    def _load_trend_for_service(self, service: Any) -> List[Dict[str, Any]]:
        path = self._trend_persistence_path_for_service(service)
        if path is None or not path.exists():
            return []
        points: List[Dict[str, Any]] = []
        try:
            with self._trend_persistence_lock:
                lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        parsed_count = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                point = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not (type(point) is dict or isinstance(point, Mapping)):
                continue
            parsed_count += 1
            normalized = dict(point)
            if points and self._trend_lifecycle_changed(points[-1], normalized):
                points = []
            sample_key = str(normalized.get("sampleKey", ""))
            if points and sample_key and str(points[-1].get("sampleKey", "")) == sample_key:
                points[-1] = normalized
            else:
                points.append(normalized)
        latest_segment = self._latest_trend_segment(points)
        if parsed_count != len(latest_segment):
            payload = "".join(
                f"{json.dumps(point, ensure_ascii=False, separators=(',', ':'), default=str)}\n"
                for point in latest_segment
            )
            try:
                with self._trend_persistence_lock:
                    path.write_text(payload, encoding="utf-8")
            except OSError:
                pass
        return latest_segment

    @staticmethod
    def _replace_last_trend_record(path: Path, payload: str) -> None:
        encoded = payload.encode("utf-8")
        with path.open("r+b") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            if size <= 0:
                stream.write(encoded)
                return
            position = size - 1
            while position >= 0:
                stream.seek(position)
                if stream.read(1) not in (b"\r", b"\n"):
                    break
                position -= 1
            while position >= 0:
                stream.seek(position)
                if stream.read(1) == b"\n":
                    position += 1
                    break
                position -= 1
            line_start = max(0, position)
            stream.seek(line_start)
            stream.write(encoded)
            stream.truncate()

    def _persist_trend_candidate_for_service(
        self,
        service: Any,
        candidate: _TrendCandidate,
    ) -> None:
        if candidate.persistence_point is None:
            return
        path = self._trend_persistence_path_for_service(service)
        if path is None:
            return
        points = candidate.trend if candidate.persistence_reset else [candidate.persistence_point]
        payload = "".join(
            f"{json.dumps(point, ensure_ascii=False, separators=(',', ':'), default=str)}\n"
            for point in points
        )
        try:
            with self._trend_persistence_lock:
                if not hasattr(self, "_trend_last_written_order"):
                    self._trend_last_written_order: Dict[Path, Tuple[Any, int, float]] = {}
                point_ref = candidate.persistence_point
                run_key = point_ref.get("runId")
                try:
                    step_key = int(point_ref.get("stepCount", 0) or 0)
                except (TypeError, ValueError):
                    step_key = 0
                try:
                    minute_key = float(point_ref.get("minute", 0.0) or 0.0)
                except (TypeError, ValueError):
                    minute_key = 0.0
                prev_order = self._trend_last_written_order.get(path)
                # 防止并发轮次交错落盘将旧步数写入新步数之后，导致重启加载误判周期重置而清空历史。
                if (
                    not candidate.persistence_reset
                    and prev_order is not None
                    and prev_order[0] == run_key
                    and (step_key < prev_order[1] or (step_key == prev_order[1] and minute_key < prev_order[2] - 1e-9))
                ):
                    return
                path.parent.mkdir(parents=True, exist_ok=True)
                if candidate.persistence_reset:
                    path.write_text(payload, encoding="utf-8")
                elif candidate.persistence_replace_last and path.exists():
                    self._replace_last_trend_record(path, payload)
                else:
                    with path.open("a", encoding="utf-8") as stream:
                        stream.write(payload)
                self._trend_last_written_order[path] = (run_key, step_key, minute_key)
        except OSError:
            # Trend persistence must not interrupt realtime control. The complete
            # in-memory history remains available for the current WEB process.
            return

    def cache_version_token(self, model_id: str) -> Optional[Tuple[Any, ...]]:
        """受锁返回用于 HTTP 帧缓存键的新能源控制版本令牌，避免无锁读取私有 _states。"""
        with self._states_lock:
            state = self._states.get(model_id)
        if state is None:
            return None
        with state.lock:
            return (
                state.revision,
                state.plan_revision,
                state.settings_revision,
                state.enabled,
                state.loop_mode,
                state.sending,
                state.status,
            )

    def _persistence_path(self, model_id: Optional[str]) -> Optional[Path]:
        return self._persistence_path_for_service(self._service_for(model_id))

    @staticmethod
    def _runtime_settings_for_service(service: Any) -> Mapping[str, Any]:
        getter = getattr(service, "web_runtime_settings", None)
        if not callable(getter):
            return {}
        try:
            payload = getter("trainee")
        except (TypeError, ValueError):
            return {}
        if not (type(payload) is dict or isinstance(payload, Mapping)):
            return {}
        settings = payload.get("effectiveSettings", payload.get("settings", {}))
        return settings if (type(settings) is dict or isinstance(settings, Mapping)) else {}

    def _collection_interval_seconds_for_service(self, service: Any) -> float:
        settings = self._runtime_settings_for_service(service)
        try:
            interval = float(
                settings.get(
                    "backend_refresh_seconds",
                    DEFAULT_TRAINEE_BACKEND_REFRESH_SECONDS,
                )
            )
        except (TypeError, ValueError):
            interval = DEFAULT_TRAINEE_BACKEND_REFRESH_SECONDS
        if not math.isfinite(interval) or interval <= 0.0:
            return DEFAULT_TRAINEE_BACKEND_REFRESH_SECONDS
        return interval

    @staticmethod
    def _validate_simulation_control_interval(
        control_interval_seconds: Any,
    ) -> float:
        return _simulation_control_interval_seconds(control_interval_seconds)

    @staticmethod
    def _validate_electrolyzer_soc_hysteresis(
        settings: RenewableControlSettings,
    ) -> None:
        if (
            settings.electrolyzer_storage_soc_start_minimum
            <= settings.electrolyzer_storage_soc_stop_maximum + EPSILON
        ):
            raise ValueError("电制氢启机SOC最小值必须大于停机SOC最大值。")

    @staticmethod
    def _validate_hydrogen_diesel_hysteresis(
        settings: RenewableControlSettings,
    ) -> None:
        if (
            settings.electrolyzer_diesel_power_limit_ratio
            >= settings.electrolyzer_diesel_power_stop_maximum_ratio - EPSILON
        ):
            raise ValueError("电制氢启机柴发门槛必须小于停机柴发门槛。")
        if (
            settings.fuel_cell_diesel_power_limit_ratio
            <= settings.fuel_cell_diesel_power_stop_minimum_ratio + EPSILON
        ):
            raise ValueError("燃料电池启机柴发门槛必须大于停机柴发门槛。")

    def validate_runtime_settings_update_for_service(
        self,
        service: Any,
        payload: Mapping[str, Any],
    ) -> None:
        self._state_for_live_service(service)
        values = payload.get("settings", {})
        if not (type(values) is dict or isinstance(values, Mapping)):
            return
        if "backend_refresh_seconds" in values:
            try:
                collection_interval = float(values["backend_refresh_seconds"])
            except (TypeError, ValueError) as exc:
                raise ValueError("后台数据刷新周期必须为有效数字。") from exc
            if not math.isfinite(collection_interval) or collection_interval <= 0.0:
                raise ValueError("后台数据刷新周期必须大于 0 系统秒。")

    def runtime_settings_changed_for_service(self, service: Any) -> bool:
        try:
            state = self._state_for_live_service(service)
        except RuntimeError:
            return False
        with state.lock:
            state.last_preview_started = 0.0
            state.revision += 1
        self._wake_worker()
        return True

    def _load_configuration_for_service(
        self,
        service: Any,
    ) -> Tuple[RenewableControlSettings, str, bool]:
        path = self._persistence_path_for_service(service)
        if path is None or not path.exists():
            return RenewableControlSettings(), "open", False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return RenewableControlSettings(), "open", False
        if not (type(payload) is dict or isinstance(payload, Mapping)):
            return RenewableControlSettings(), "open", False
        settings_payload = payload.get("settings")
        settings = RenewableControlSettings().updated(
            settings_payload if (type(settings_payload) is dict or isinstance(settings_payload, Mapping)) else payload
        )
        loop_mode = "closed" if str(payload.get("loopMode", payload.get("loop_mode", "open"))).lower() == "closed" else "open"
        desired_enabled = bool(
            payload.get(
                "desiredEnabled",
                payload.get("desired_enabled", False),
            )
        )
        return settings, loop_mode, desired_enabled

    def _persist_configuration(
        self,
        service: Any,
        settings: RenewableControlSettings,
        loop_mode: str,
        desired_enabled: bool,
    ) -> None:
        path = self._persistence_path_for_service(service)
        if path is None:
            raise RuntimeError("当前模型没有可用的运行目录，无法持久化新能源控制参数")
        payload = {
            "version": 2,
            "modelId": str(getattr(service, "model_id", "default")),
            "loopMode": "closed" if loop_mode == "closed" else "open",
            "desiredEnabled": bool(desired_enabled),
            "settings": settings.payload(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise RuntimeError(f"新能源控制参数持久化失败：{exc}") from exc

    def _require_active_service_for_state_locked(
        self,
        service: Any,
        state: _ControllerState,
    ) -> None:
        if (
            self._service_instance_id(service) != state.service_instance_id
            or not self._service_instance_active_locked(service)
        ):
            raise RuntimeError("新能源控制请求所属模型生命周期已失效或已退休，操作已取消。")

    def _state_for_service(self, service: Any) -> _ControllerState:
        normalized = str(getattr(service, "model_id", "default"))
        service_instance_id = self._service_instance_id(service)
        with self._states_lock:
            state = self._states.get(normalized)
            if state is not None and state.service_instance_id == service_instance_id:
                return state
            state = self._states_by_service_instance.get(service_instance_id)
        if state is None:
            settings, loop_mode, desired_enabled = self._load_configuration_for_service(
                service
            )
            persisted_trend = self._load_trend_for_service(service)
            prerequisite = self._receive_prerequisite_for_service(service)
            enabled = bool(desired_enabled and prerequisite["canRun"])
            if enabled:
                status = _RENEWABLE_AUTO_RESUMED_STATUS
            elif desired_enabled:
                prerequisite_status = str(
                    prerequisite.get("prerequisiteStatus") or "接收尚未就绪。"
                ).rstrip("。")
                status = (
                    f"{prerequisite_status}；新能源实时控制将在接收就绪后自动恢复。"
                )
            else:
                status = _RENEWABLE_READY_IDLE_STATUS
            candidate = _ControllerState(
                normalized,
                service_instance_id,
                settings=settings,
                enabled=enabled,
                desired_enabled=desired_enabled,
                loop_mode=loop_mode,
                status=status,
                trend=persisted_trend,
                trend_normalized=bool(persisted_trend),
            )
            with self._states_lock:
                state = self._states_by_service_instance.setdefault(
                    service_instance_id,
                    candidate,
                )
            if state is candidate and state.enabled:
                self._wake_worker()
        with self._states_lock:
            self._states[normalized] = state
            return state

    def _state_for_live_service(self, service: Any) -> _ControllerState:
        if not self._service_is_current_registry_instance(service):
            raise TraineeRenewableControlLifecycleError(
                "新能源控制请求所属模型生命周期已失效或已退休。"
            )
        service_lock = getattr(service, "lock", None)
        with (service_lock if service_lock is not None else nullcontext()):
            if not self._service_instance_active_locked(service):
                raise TraineeRenewableControlLifecycleError(
                    "新能源控制请求所属模型生命周期已失效或已退休。"
                )
            return self._state_for_service(service)

    def _state_for(self, model_id: Optional[str]) -> _ControllerState:
        return self._state_for_service(self._service_for(model_id))

    @staticmethod
    def _service_bound_provider(
        provider: Callable[..., Any],
        method_name: str,
    ) -> Optional[Callable[[Any], Any]]:
        explicit = getattr(provider, "for_service", None)
        if callable(explicit):
            return explicit
        owner = getattr(provider, "__self__", None)
        candidate = getattr(owner, method_name, None)
        return candidate if callable(candidate) else None

    def _service_lifecycle_valid(self, service: Any, state: _ControllerState) -> bool:
        with state.lock:
            service_lock = getattr(service, "lock", None)
            with (service_lock if service_lock is not None else nullcontext()):
                return bool(
                    self._service_instance_id(service) == state.service_instance_id
                    and self._service_instance_active_locked(service)
                )

    def _require_active_service_for_state(
        self,
        service: Any,
        state: _ControllerState,
    ) -> None:
        with state.lock:
            service_lock = getattr(service, "lock", None)
            with (service_lock if service_lock is not None else nullcontext()):
                self._require_active_service_for_state_locked(service, state)

    def _receive_status_for_service(self, service: Any) -> Dict[str, Any]:
        provider = self._service_bound_provider(
            self.receive_status_provider,
            "receive_status_for_service",
        )
        try:
            payload = (
                provider(service)
                if provider is not None
                else self.receive_status_provider(str(getattr(service, "model_id", "default")))
            )
        except Exception as exc:
            return {
                "receiveActive": False,
                "ready": False,
                "canRun": False,
                "prerequisiteStatus": f"学员台实时交换状态不可用：{exc}",
                "revision": 0,
                "connectionSignature": [],
            }
        return dict(payload) if (type(payload) is dict or isinstance(payload, Mapping)) else {}

    def _receive_status(self, model_id: Optional[str]) -> Dict[str, Any]:
        return self._receive_status_for_service(self._service_for(model_id))

    def _receive_state_signature_for_service(self, service: Any) -> Tuple[Any, ...]:
        status = self._receive_status_for_service(service)
        signature = status.get("connectionSignature", ())
        if not isinstance(signature, Sequence) or isinstance(signature, (str, bytes)):
            signature = ()
        return (
            bool(status.get("receiveActive")),
            bool(status.get("ready")),
            bool(status.get("controlFrozen") or status.get("simulationPaused")),
            int(_number(status.get("receiveEpoch", status.get("connectionEpoch")), 0.0) or 0),
            tuple(signature),
            int(_number(status.get("revision"), 0.0) or 0),
        )

    def _receive_state_signature(self, model_id: Optional[str]) -> Tuple[Any, ...]:
        return self._receive_state_signature_for_service(self._service_for(model_id))

    @classmethod
    def _receive_state_signature_for_view(
        cls,
        view: TraineeControlSnapshot,
    ) -> Tuple[Any, ...]:
        return (
            bool(view.receive_active),
            bool(view.ready),
            cls._snapshot_simulation_paused(view.snapshot),
            int(view.receive_epoch),
            tuple(view.connection_signature),
            int(view.revision),
        )

    def _candidate_generation_guard(
        self,
        service: Any,
        view: TraineeControlSnapshot,
        receive_signature: Tuple[Any, ...],
    ) -> ContextManager[bool]:
        lease = getattr(view, "control_lease", None)
        if lease is not None:
            return lease.guard()
        return nullcontext(
            self._receive_state_signature_for_service(service) == receive_signature
        )

    @staticmethod
    def _view_matches_controller_state(
        view: TraineeControlSnapshot,
        state: _ControllerState,
    ) -> bool:
        lease = getattr(view, "control_lease", None)
        generation = getattr(lease, "generation", None)
        if generation is None:
            return True
        return str(getattr(generation, "service_instance_id", "")) == state.service_instance_id

    def _receive_prerequisite_for_service(self, service: Any) -> Dict[str, Any]:
        status = self._receive_status_for_service(service)
        active = bool(status.get("receiveActive"))
        ready = bool(status.get("ready"))
        control_frozen = bool(
            status.get("controlFrozen") or status.get("simulationPaused")
        )
        can_run = active and ready and bool(status.get("canRun", True))
        can_calculate = can_run and not control_frozen and bool(
            status.get("canCalculate", True)
        )
        can_dispatch = can_calculate and bool(status.get("canDispatch", can_calculate))
        if not active:
            message = str(status.get("prerequisiteStatus") or "请先启动接收。")
        elif not ready:
            message = str(status.get("prerequisiteStatus") or "学员台正在等待第一份实时数据。")
        else:
            message = str(status.get("prerequisiteStatus") or "") if not can_calculate else ""
        normalized = dict(status)
        normalized.update({
            "receiveActive": active,
            "receiveConfigured": active,
            "ready": ready,
            "canRun": can_run,
            "canCalculate": can_calculate,
            "canDispatch": can_dispatch,
            "controlFrozen": control_frozen,
            "simulationPaused": control_frozen,
            "prerequisiteStatus": message,
            "dispatchStatus": (
                ""
                if control_frozen
                else str(status.get("dispatchStatus") or "")
                if not can_dispatch
                else ""
            ),
        })
        return normalized

    @staticmethod
    def _snapshot_simulation_paused(snapshot: Mapping[str, Any]) -> bool:
        clock = snapshot.get("clock") if isinstance(snapshot.get("clock"), Mapping) else {}
        return str(clock.get("state") or "").strip().casefold() == "paused"

    @staticmethod
    def _simulation_control_clock(
        snapshot: Mapping[str, Any],
    ) -> Optional[_SimulationControlClock]:
        clock = snapshot.get("clock")
        if not (type(clock) is dict or isinstance(clock, Mapping)):
            return None
        absolute_second = _number(clock.get("absolute_second"))
        if absolute_second is None:
            absolute_minute = _number(
                clock.get("absolute_minute", clock.get("minute"))
            )
            if absolute_minute is None:
                return None
            absolute_second = absolute_minute * 60.0
        if not math.isfinite(absolute_second):
            return None
        return _SimulationControlClock(
            state=str(clock.get("state") or "running").strip().casefold(),
            run_id=int(_number(clock.get("run_id"), 0.0) or 0),
            step_count=int(_number(clock.get("step_count"), 0.0) or 0),
            absolute_second=float(absolute_second),
        )

    @staticmethod
    def _simulation_control_due_locked(
        state: _ControllerState,
        clock: Optional[_SimulationControlClock],
        interval_seconds: float,
    ) -> bool:
        if clock is None or clock.state != "running":
            return False
        lifecycle_changed = bool(
            state.control_clock_run_id is not None
            and (
                clock.run_id != state.control_clock_run_id
                or (
                    state.control_clock_last_step_count is not None
                    and clock.step_count < state.control_clock_last_step_count
                )
                or (
                    state.control_clock_last_second is not None
                    and clock.absolute_second
                    < state.control_clock_last_second - EPSILON
                )
                or (
                    state.control_clock_last_step_count is not None
                    and state.control_clock_last_second is not None
                    and clock.step_count == state.control_clock_last_step_count
                    and clock.absolute_second
                    > state.control_clock_last_second + EPSILON
                )
            )
        )
        if state.control_clock_anchor_second is None or lifecycle_changed:
            state.control_clock_run_id = clock.run_id
            state.control_clock_anchor_second = clock.absolute_second
            state.control_clock_last_second = clock.absolute_second
            state.control_clock_last_step_count = clock.step_count
            return False
        state.control_clock_run_id = clock.run_id
        state.control_clock_last_second = clock.absolute_second
        state.control_clock_last_step_count = clock.step_count
        return (
            clock.absolute_second - state.control_clock_anchor_second
            >= max(MINIMUM_CONTROL_INTERVAL_SECONDS, interval_seconds) - EPSILON
        )

    @staticmethod
    def _mark_simulation_control_started_locked(
        state: _ControllerState,
        clock: _SimulationControlClock,
    ) -> None:
        state.control_clock_run_id = clock.run_id
        state.control_clock_anchor_second = clock.absolute_second
        state.control_clock_last_second = clock.absolute_second
        state.control_clock_last_step_count = clock.step_count

    def _receive_prerequisite(self, model_id: Optional[str]) -> Dict[str, Any]:
        return self._receive_prerequisite_for_service(self._service_for(model_id))

    @staticmethod
    def _dispatch_generation_key(
        view: TraineeControlSnapshot,
        receive_signature: Tuple[Any, ...],
    ) -> Tuple[Any, ...]:
        lease = getattr(view, "control_lease", None)
        generation = getattr(lease, "generation", None)
        if generation is None:
            return tuple(receive_signature)
        return (
            str(getattr(generation, "model_id", "")),
            str(getattr(generation, "service_instance_id", "")),
            int(getattr(generation, "receive_epoch", 0)),
            tuple(getattr(generation, "connection_signature", ())),
            int(getattr(generation, "definition_revision", 0)),
            int(getattr(generation, "runtime_revision", 0)),
        )

    @staticmethod
    def _topology_definition_revision(view: TraineeControlSnapshot) -> Optional[int]:
        lease = getattr(view, "control_lease", None)
        generation = getattr(lease, "generation", None)
        if generation is None:
            return None
        try:
            return int(getattr(generation, "definition_revision"))
        except (TypeError, ValueError):
            return None

    def _topology_static_context_for_plan(
        self,
        state: _ControllerState,
        view: TraineeControlSnapshot,
        snapshot: Mapping[str, Any],
    ) -> ResourceTopologyStaticContext:
        definition_revision = self._topology_definition_revision(view)
        if definition_revision is None:
            return prepare_resource_topology_static_context(snapshot)
        with state.lock:
            if (
                state.topology_static_context is not None
                and state.topology_definition_revision == definition_revision
            ):
                return state.topology_static_context
        prepared = prepare_resource_topology_static_context(snapshot)
        with state.lock:
            if (
                state.topology_static_context is not None
                and state.topology_definition_revision == definition_revision
            ):
                return state.topology_static_context
            state.topology_static_context = prepared
            state.topology_definition_revision = definition_revision
            return prepared

    def _control_snapshot(self, model_id: Optional[str]) -> TraineeControlSnapshot:
        return self._control_snapshot_for_service(self._service_for(model_id))

    def _control_snapshot_for_service(self, service: Any) -> TraineeControlSnapshot:
        provider = self._service_bound_provider(
            self.snapshot_provider,
            "control_calculation_snapshot_for_service",
        )
        if provider is None:
            provider = self._service_bound_provider(
                self.snapshot_provider,
                "control_snapshot_for_service",
            )
        view = (
            provider(service)
            if provider is not None
            else self.snapshot_provider(str(getattr(service, "model_id", "default")))
        )
        if not isinstance(view, TraineeControlSnapshot):
            raise RuntimeError("学员台实时交换服务返回了无效快照契约")
        if not view.ready:
            raise RuntimeError(view.error or "学员台尚未收到实时数据")
        if not (type(view.snapshot) is dict or isinstance(view.snapshot, Mapping)):
            raise RuntimeError("学员台实时交换服务返回的快照不是对象")
        return view

    def _control_schedule_snapshot_for_service(
        self,
        service: Any,
    ) -> TraineeControlSnapshot:
        provider = self._service_bound_provider(
            self.snapshot_provider,
            "control_schedule_snapshot_for_service",
        )
        if provider is None:
            return self._control_snapshot_for_service(service)
        view = provider(service)
        if not isinstance(view, TraineeControlSnapshot):
            raise RuntimeError("学员台实时交换服务返回了无效调度快照契约")
        if not view.ready:
            raise RuntimeError(view.error or "学员台尚未收到实时数据")
        if not (type(view.snapshot) is dict or isinstance(view.snapshot, Mapping)):
            raise RuntimeError("学员台实时交换服务返回的调度快照不是对象")
        return view

    def _reject_without_receive_for_service(
        self,
        service: Any,
        state: _ControllerState,
        *,
        action_label: str,
        record_log: bool,
        raise_on_retired: bool,
        serialize_result: bool = True,
    ) -> Optional[Dict[str, Any]]:
        if not self._service_lifecycle_valid(service, state):
            if raise_on_retired:
                self._require_active_service_for_state(service, state)
            return self._cycle_state_result(
                service,
                state,
                serialize_result=serialize_result,
            )
        prerequisite = self._receive_prerequisite_for_service(service)
        if prerequisite["canRun"]:
            return None
        runtime_log_entry = None
        with state.lock:
            service_lock = getattr(service, "lock", None)
            with (service_lock if service_lock is not None else nullcontext()):
                if not (
                    self._service_instance_id(service) == state.service_instance_id
                    and self._service_instance_active_locked(service)
                ):
                    if raise_on_retired:
                        self._require_active_service_for_state_locked(service, state)
                    return self._cycle_state_result(
                        service,
                        state,
                        serialize_result=serialize_result,
                    )
                state.enabled = False
                prerequisite_status = str(
                    prerequisite["prerequisiteStatus"] or "接收尚未就绪。"
                ).rstrip("。")
                state.status = (
                    (
                        "接收已停止；"
                        if not prerequisite.get("receiveActive")
                        else ""
                    )
                    + f"{prerequisite_status}；新能源实时控制将在接收就绪后自动恢复。"
                    if state.desired_enabled
                    else str(prerequisite["prerequisiteStatus"])
                )
                if record_log:
                    runtime_log_entry = self._append_log(
                        state,
                        "策略控制",
                        f"{action_label}阻断",
                        state.status,
                        level="warn",
                        simu_time=state.last_plan.get("time", "--") if state.last_plan else "--",
                        persist_runtime=False,
                    )
                state.revision += 1
        if runtime_log_entry is not None:
            self._persist_runtime_log_for_service(service, state, runtime_log_entry)
        self._wake_worker()
        return self._cycle_state_result(
            service,
            state,
            serialize_result=serialize_result,
        )

    def _reject_without_receive(
        self,
        model_id: Optional[str],
        *,
        action_label: str,
        record_log: bool,
    ) -> Optional[Dict[str, Any]]:
        service = self._service_for(model_id)
        state = self._state_for_service(service)
        return self._reject_without_receive_for_service(
            service,
            state,
            action_label=action_label,
            record_log=record_log,
            raise_on_retired=True,
        )

    def receive_state_changed_for_service(
        self,
        service: Any,
        *,
        serialize_result: bool = True,
    ) -> Dict[str, Any]:
        state = self._state_for_service(service)
        prerequisite = self._receive_prerequisite_for_service(service)
        runtime_log_entry = None
        state_changed = False
        with state.lock:
            revision_before = state.revision
            service_lock = getattr(service, "lock", None)
            with (service_lock if service_lock is not None else nullcontext()):
                self._require_active_service_for_state_locked(service, state)
                if prerequisite["canRun"]:
                    if state.desired_enabled and not state.enabled:
                        state.enabled = True
                        state.operation_epoch += 1
                        state.last_auto_started = 0.0
                        state.last_preview_started = 0.0
                        state.status = _RENEWABLE_AUTO_RESUMED_STATUS
                        runtime_log_entry = self._append_log(
                            state,
                            "策略控制",
                            "自动恢复",
                            state.status,
                            level="ok",
                            simu_time=(
                                state.last_plan.get("time", "--")
                                if state.last_plan
                                else "--"
                            ),
                            persist_runtime=False,
                        )
                        state.revision += 1
                    elif not state.enabled and _stale_receive_prerequisite_status(state.status):
                        state.status = _RENEWABLE_READY_IDLE_STATUS
                        state.revision += 1
                elif state.enabled:
                    state.enabled = False
                    state.operation_epoch += 1
                    prerequisite_status = str(
                        prerequisite.get("prerequisiteStatus") or "接收已停止。"
                    ).rstrip("。")
                    state.status = (
                        f"接收已停止；{prerequisite_status}；新能源实时控制已暂停，"
                        "将在接收就绪后自动恢复。"
                        if state.desired_enabled
                        else "接收已停止，新能源实时控制同步停止。"
                    )
                    runtime_log_entry = self._append_log(
                        state,
                        "策略控制",
                        "接收联动暂停" if state.desired_enabled else "接收联动停止",
                        state.status,
                        level="warn",
                        simu_time=state.last_plan.get("time", "--") if state.last_plan else "--",
                        persist_runtime=False,
                    )
                    state.revision += 1
                elif state.desired_enabled:
                    prerequisite_status = str(
                        prerequisite.get("prerequisiteStatus") or "接收尚未就绪。"
                    ).rstrip("。")
                    next_status = (
                        (
                            "接收已停止；"
                            if not prerequisite.get("receiveActive")
                            else ""
                        )
                        + f"{prerequisite_status}；新能源实时控制将在接收就绪后自动恢复。"
                    )
                    if state.status != next_status:
                        state.status = next_status
                        state.revision += 1
            state_changed = state.revision != revision_before
        if runtime_log_entry is not None:
            self._persist_runtime_log_for_service(service, state, runtime_log_entry)
        if state_changed:
            self._wake_worker()
        return self._cycle_state_result(
            service,
            state,
            serialize_result=serialize_result,
        )

    def receive_state_changed(self, model_id: Optional[str]) -> Dict[str, Any]:
        return self.receive_state_changed_for_service(self._service_for(model_id))

    def _retire_state(self, state: _ControllerState) -> None:
        with state.lock:
            state.operation_epoch += 1
            state.enabled = False
            state.desired_enabled = False
            state.strategy_generation_active = False
            state.strategy_cancel_pending = False
            state.strategy_cancel_operation_epoch = 0
            state.effective_target_snapshot = None
            state.pending_dispatch_clock_key = ""
            state.pending_dispatch_generation_key = ()
            state.topology_static_context = None
            state.topology_definition_revision = -1
        with self._states_lock:
            if self._states.get(state.model_id) is state:
                self._states.pop(state.model_id, None)
            if self._states_by_service_instance.get(state.service_instance_id) is state:
                self._states_by_service_instance.pop(state.service_instance_id, None)
        self._wake_worker()

    def remove_model_for_service(self, service: Any) -> bool:
        """Cancel and remove only the controller lifecycle for this service."""
        service_instance_id = self._service_instance_id(service)
        with self._states_lock:
            state = self._states_by_service_instance.get(service_instance_id)
        if state is None:
            return False
        self._retire_state(state)
        return True

    def _serialize_cancelled_cycle(
        self,
        service: Any,
        state: _ControllerState,
        *,
        clear_sending: bool,
        serialize_result: bool = True,
    ) -> Dict[str, Any]:
        if clear_sending:
            with state.lock:
                if state.sending:
                    state.sending = False
                    state.revision += 1
        return self._cycle_state_result(
            service,
            state,
            serialize_result=serialize_result,
        )

    def _cycle_state_result(
        self,
        service: Any,
        state: _ControllerState,
        *,
        serialize_result: bool,
        serialization_options: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not serialize_result:
            return {}
        return self._serialize_for_service(
            service,
            state,
            **dict(serialization_options or {}),
        )

    def _busy_cycle_response(
        self,
        service: Any,
        state: _ControllerState,
        *,
        action_label: str,
        record_log: bool,
        disable_control: bool = False,
        raise_on_retired: bool,
    ) -> Dict[str, Any]:
        runtime_log_entry = None
        with state.lock:
            service_lock = getattr(service, "lock", None)
            with (service_lock if service_lock is not None else nullcontext()):
                if not (
                    self._service_instance_id(service) == state.service_instance_id
                    and self._service_instance_active_locked(service)
                ):
                    if raise_on_retired:
                        self._require_active_service_for_state_locked(service, state)
                    return self._serialize_for_service(service, state)
                if disable_control:
                    state.enabled = False
                state.status = f"新能源控制正在执行上一轮计算，本次{action_label}未执行，请稍后重试。"
                if record_log:
                    runtime_log_entry = self._append_log(
                        state,
                        "策略控制",
                        f"{action_label}忙碌阻断",
                        state.status,
                        level="warn",
                        simu_time=state.last_plan.get("time", "--") if state.last_plan else "--",
                        persist_runtime=False,
                    )
                state.revision += 1
        if runtime_log_entry is not None:
            self._persist_runtime_log_for_service(service, state, runtime_log_entry)
        return self._serialize_for_service(service, state)

    def _append_log(
        self,
        state: _ControllerState,
        log_type: str,
        result: str,
        detail: Any,
        *,
        full_detail: Any = None,
        level: str = "info",
        simu_time: str = "--",
        persist_runtime: bool = True,
    ) -> Dict[str, Any]:
        state.log_seq += 1
        normalized_detail = detail if isinstance(detail, str) else "；".join(str(item) for item in detail if item)
        detail_source = detail if full_detail is None else full_detail
        if isinstance(detail_source, str):
            normalized_full_detail = [detail_source] if detail_source.strip() else []
        elif isinstance(detail_source, Sequence):
            normalized_full_detail = [
                str(item).strip()
                for item in detail_source
                if str(item).strip()
            ]
        else:
            detail_text = str(detail_source).strip() if detail_source is not None else ""
            normalized_full_detail = [detail_text] if detail_text else []
        entry = {
            "seq": state.log_seq,
            "wall_time": _now_text(),
            "simu_time": simu_time or "--",
            "type": log_type,
            "target": "新能源优先",
            "result": result,
            "detail": normalized_detail,
            "full_detail": normalized_full_detail,
            "level": level,
        }
        state.logs.insert(0, entry)
        state.logs = state.logs[:300]
        if persist_runtime:
            self._persist_runtime_log(state, entry)
        return entry

    def _persist_runtime_log(
        self,
        state: _ControllerState,
        entry: Mapping[str, Any],
    ) -> None:
        try:
            target = self._service_for(state.model_id)
            self._persist_runtime_log_for_service(target, state, entry)
        except Exception as exc:
            # 运行日志落盘失败不应中断控制循环，但需留痕便于排障。
            _TRAINEE_CTRL_LOG.warning(
                "Persisting renewable control runtime log failed for %s: %s",
                state.model_id,
                exc,
            )

    def _persist_runtime_log_for_service(
        self,
        service: Any,
        state: _ControllerState,
        entry: Mapping[str, Any],
    ) -> None:
        target_lock = getattr(service, "lock", None)
        with (target_lock if target_lock is not None else nullcontext()):
            if (
                self._service_instance_id(service) != state.service_instance_id
                or not self._service_instance_active_locked(service)
            ):
                return
            append_runtime_log = getattr(service, "_append_runtime_log", None)
            if callable(append_runtime_log):
                append_runtime_log(
                    str(entry.get("type", "")),
                    str(entry.get("target", "新能源优先")),
                    str(entry.get("result", "")),
                    str(entry.get("detail", "")),
                    level=str(entry.get("level", "info")),
                    simu_time=str(entry.get("simu_time", "--")),
                )

    @staticmethod
    def _trend_point(plan: Mapping[str, Any], snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
        weather = plan.get("weather") if isinstance(plan.get("weather"), Mapping) else {}
        clock = _measurement_sample_clock(snapshot)
        run_id = int(_number(clock.get("run_id"), 0.0) or 0)
        step_count = int(_number(clock.get("step_count"), 0.0) or 0)
        minute = _number(clock.get("absolute_minute", clock.get("minute")), 0.0) or 0.0

        def metric_total(*keys: str) -> Optional[float]:
            values = [_number(metrics.get(key)) for key in keys]
            finite_values = [value for value in values if value is not None and math.isfinite(value)]
            return sum(finite_values) if finite_values else None

        def metric_value(key: str, *fallback_keys: str) -> Optional[float]:
            value = _number(metrics.get(key))
            if value is not None and math.isfinite(value):
                return value
            return metric_total(*fallback_keys)

        def metric_soc_percent(key: str, *fallback_keys: str) -> Optional[float]:
            value = metric_value(key, *fallback_keys)
            return value * 100.0 if value is not None and math.isfinite(value) else None

        point = {
            "sampleKey": f"{run_id}|{minute}|{clock.get('time', '')}",
            "runId": run_id,
            "stepCount": step_count,
            "minute": minute,
            "time": str(clock.get("time", "--")),
            "loadKw": metrics.get("loadKw"),
            "dieselKw": metrics.get("dieselCurrentKw"),
            "storageKw": metrics.get("storageCurrentKw"),
            "storageSocPercent": metric_soc_percent("storageSoc"),
            "renewableKw": metrics.get("renewableCurrentKw"),
            "acLoadKw": metric_value("acLoadKw"),
            "dcLoadKw": metric_value("dcLoadKw"),
            "dieselCurrentKw": metric_value("dieselCurrentKw", "totalDieselCurrentKw"),
            "dieselTargetKw": metric_value("dieselTargetKw", "totalDieselTargetKw"),
            "acRenewableCurrentKw": metric_value("acRenewableCurrentKw", "acWindCurrentKw", "acPvCurrentKw"),
            "acRenewableTargetKw": metric_value("acRenewableTargetKw", "acWindTargetKw", "acPvTargetKw"),
            "acRenewableMaxAvailableKw": metric_value("acRenewableMaxAvailableKw"),
            "acWindCurrentKw": metric_value("acWindCurrentKw"),
            "acWindTargetKw": metric_value("acWindTargetKw"),
            "acWindMaxAvailableKw": metric_value("acWindMaxAvailableKw"),
            "acPvCurrentKw": metric_value("acPvCurrentKw"),
            "acPvTargetKw": metric_value("acPvTargetKw"),
            "acPvMaxAvailableKw": metric_value("acPvMaxAvailableKw"),
            "dcRenewableCurrentKw": metric_value("dcRenewableCurrentKw", "dcWindCurrentKw", "dcPvCurrentKw"),
            "dcRenewableTargetKw": metric_value("dcRenewableTargetKw", "dcWindTargetKw", "dcPvTargetKw"),
            "dcRenewableMaxAvailableKw": metric_value("dcRenewableMaxAvailableKw"),
            "dcWindCurrentKw": metric_value("dcWindCurrentKw"),
            "dcWindTargetKw": metric_value("dcWindTargetKw"),
            "dcWindMaxAvailableKw": metric_value("dcWindMaxAvailableKw"),
            "dcPvCurrentKw": metric_value("dcPvCurrentKw"),
            "dcPvTargetKw": metric_value("dcPvTargetKw"),
            "dcPvMaxAvailableKw": metric_value("dcPvMaxAvailableKw"),
            "acStorageCurrentKw": metric_value(
                "acStorageCurrentKw",
                "acGridFollowingStorageCurrentKw",
                "acGridFormingStorageCurrentKw",
            ),
            "acStorageTargetKw": metric_value(
                "acStorageTargetKw",
                "acGridFollowingStorageTargetKw",
                "acGridFormingStorageTargetKw",
            ),
            "acStorageSocPercent": metric_soc_percent("acStorageSoc"),
            "dcStorageCurrentKw": metric_value(
                "dcStorageCurrentKw",
                "dcGridFollowingStorageCurrentKw",
                "dcGridFormingStorageCurrentKw",
            ),
            "dcStorageTargetKw": metric_value(
                "dcStorageTargetKw",
                "dcGridFollowingStorageTargetKw",
                "dcGridFormingStorageTargetKw",
            ),
            "dcStorageSocPercent": metric_soc_percent("dcStorageSoc"),
            "acGridFollowingStorageCurrentKw": metric_value("acGridFollowingStorageCurrentKw", "acGridStorageCurrentKw"),
            "acGridFollowingStorageTargetKw": metric_value("acGridFollowingStorageTargetKw", "acGridStorageTargetKw"),
            "dcGridFollowingStorageCurrentKw": metric_value("dcGridFollowingStorageCurrentKw", "dcGridStorageCurrentKw"),
            "dcGridFollowingStorageTargetKw": metric_value("dcGridFollowingStorageTargetKw", "dcGridStorageTargetKw"),
            "acGridFormingStorageCurrentKw": metric_value("acGridFormingStorageCurrentKw", "acBalanceStorageCurrentKw"),
            "acGridFormingStorageTargetKw": metric_value("acGridFormingStorageTargetKw", "acBalanceStorageTargetKw"),
            "dcGridFormingStorageCurrentKw": metric_value("dcGridFormingStorageCurrentKw", "dcBalanceStorageCurrentKw"),
            "dcGridFormingStorageTargetKw": metric_value("dcGridFormingStorageTargetKw", "dcBalanceStorageTargetKw"),
            "acGridFollowingStorageSocPercent": metric_soc_percent("acGridFollowingStorageSoc", "acGridStorageSoc"),
            "dcGridFollowingStorageSocPercent": metric_soc_percent("dcGridFollowingStorageSoc", "dcGridStorageSoc"),
            "acGridFormingStorageSocPercent": metric_soc_percent("acGridFormingStorageSoc", "acBalanceStorageSoc"),
            "dcGridFormingStorageSocPercent": metric_soc_percent("dcGridFormingStorageSoc", "dcBalanceStorageSoc"),
            "acDieselCurrentKw": metric_value("acDieselCurrentKw"),
            "acDieselMinKw": metric_value("acDieselMinKw"),
            "acDieselTargetKw": metric_value("acDieselTargetKw"),
            "dcDieselCurrentKw": metric_value("dcDieselCurrentKw"),
            "dcDieselMinKw": metric_value("dcDieselMinKw"),
            "dcDieselTargetKw": metric_value("dcDieselTargetKw"),
            "totalRenewableCurrentKw": metric_value("totalRenewableCurrentKw", "acRenewableCurrentKw", "dcRenewableCurrentKw"),
            "totalRenewableTargetKw": metric_value("totalRenewableTargetKw", "acRenewableTargetKw", "dcRenewableTargetKw"),
            "totalRenewableMaxAvailableKw": metric_value("totalRenewableMaxAvailableKw"),
            "totalWindCurrentKw": metric_value("totalWindCurrentKw", "acWindCurrentKw", "dcWindCurrentKw"),
            "totalWindTargetKw": metric_value("totalWindTargetKw", "acWindTargetKw", "dcWindTargetKw"),
            "totalWindMaxAvailableKw": metric_value("totalWindMaxAvailableKw"),
            "totalPvCurrentKw": metric_value("totalPvCurrentKw", "acPvCurrentKw", "dcPvCurrentKw"),
            "totalPvTargetKw": metric_value("totalPvTargetKw", "acPvTargetKw", "dcPvTargetKw"),
            "totalPvMaxAvailableKw": metric_value("totalPvMaxAvailableKw"),
            "totalStorageCurrentKw": metric_value(
                "totalStorageCurrentKw",
                "acStorageCurrentKw",
                "dcStorageCurrentKw",
            ),
            "totalStorageTargetKw": metric_value(
                "totalStorageTargetKw",
                "acStorageTargetKw",
                "dcStorageTargetKw",
            ),
            "totalStorageSocPercent": metric_soc_percent("totalStorageSoc"),
            "totalGridFollowingStorageCurrentKw": metric_value("totalGridFollowingStorageCurrentKw", "acGridFollowingStorageCurrentKw", "dcGridFollowingStorageCurrentKw"),
            "totalGridFollowingStorageTargetKw": metric_value("totalGridFollowingStorageTargetKw", "acGridFollowingStorageTargetKw", "dcGridFollowingStorageTargetKw"),
            "totalGridFollowingStorageSocPercent": metric_soc_percent("totalGridFollowingStorageSoc"),
            "totalGridFormingStorageCurrentKw": metric_value("totalGridFormingStorageCurrentKw", "acGridFormingStorageCurrentKw", "dcGridFormingStorageCurrentKw"),
            "totalGridFormingStorageTargetKw": metric_value("totalGridFormingStorageTargetKw", "acGridFormingStorageTargetKw", "dcGridFormingStorageTargetKw"),
            "totalGridFormingStorageSocPercent": metric_soc_percent("totalGridFormingStorageSoc"),
            "totalDieselCurrentKw": metric_value("totalDieselCurrentKw", "acDieselCurrentKw", "dcDieselCurrentKw"),
            "totalDieselMinKw": metric_value("totalDieselMinKw", "acDieselMinKw", "dcDieselMinKw"),
            "totalDieselTargetKw": metric_value("totalDieselTargetKw", "acDieselTargetKw", "dcDieselTargetKw"),
            "totalLoadKw": metric_value("totalLoadKw", "acLoadKw", "dcLoadKw"),
            "acdcCurrentKw": metric_value("acdcCurrentKw"),
            "acdcTargetKw": metric_value("acdcTargetKw"),
            "electrolyzerCurrentKw": metric_value("electrolyzerCurrentKw"),
            "electrolyzerTargetKw": metric_value("electrolyzerTargetKw"),
            "electrolyzerFlowCurrentNm3h": metric_value("electrolyzerFlowCurrentNm3h"),
            "electrolyzerFlowTargetNm3h": metric_value("electrolyzerFlowTargetNm3h"),
            "fuelCellCurrentKw": metric_value("fuelCellCurrentKw"),
            "fuelCellTargetKw": metric_value("fuelCellTargetKw"),
            "fuelCellFlowCurrentNm3h": metric_value("fuelCellFlowCurrentNm3h"),
            "fuelCellFlowTargetNm3h": metric_value("fuelCellFlowTargetNm3h"),
            "hydrogenStoragePressureMpa": metric_value("hydrogenStoragePressureMpa"),
            "hydrogenStoragePressureLowGuardMpa": metric_value("hydrogenStoragePressureLowGuardMpa"),
            "hydrogenStoragePressureHighGuardMpa": metric_value("hydrogenStoragePressureHighGuardMpa"),
            "hydrogenStorageGasQuantityNm3": metric_value("hydrogenStorageGasQuantityNm3"),
            "hydrogenStorageSocPercent": metric_soc_percent("hydrogenStorageSoc"),
            "hydrogenStorageFlowNm3h": metric_value("hydrogenStorageFlowNm3h"),
            "observedWindSpeed": _number(weather.get("observedWindSpeed")),
            "observedSolarIrradiance": _number(weather.get("observedSolarIrradiance")),
        }
        for key in (
            "acGridStorageCurrentKw",
            "acGridStorageTargetKw",
            "acGridStorageSoc",
            "dcGridStorageCurrentKw",
            "dcGridStorageTargetKw",
            "dcGridStorageSoc",
            "acBalanceStorageCurrentKw",
            "acBalanceStorageTargetKw",
            "dcBalanceStorageCurrentKw",
            "dcBalanceStorageTargetKw",
            "acBalanceStorageSoc",
            "dcBalanceStorageSoc",
            "dcRenewableToAcKw",
            "dcTransferGroups",
        ):
            point[key] = _json_safe_copy(metrics.get(key))
        return point

    @staticmethod
    def _command_row_target_key(row: Mapping[str, Any], index: int) -> Tuple[str, ...]:
        identity = tuple(
            str(row.get(key, "")).strip()
            for key in ("dev_type", "dev_name", "set_type")
        )
        return identity if any(identity) else ("index", str(index))

    @classmethod
    def _capture_effective_targets(cls, plan: Mapping[str, Any]) -> Dict[str, Any]:
        metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
        rows = plan.get("commandRows")
        command_rows = (
            rows
            if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes))
            else []
        )
        commands = plan.get("commands")
        run_commands = plan.get("runCommands")
        return {
            "metrics": {
                str(key): _json_safe_copy(value)
                for key, value in metrics.items()
                if "target" in str(key).casefold()
            },
            "commands": _json_safe_copy(
                commands
                if isinstance(commands, Sequence) and not isinstance(commands, (str, bytes))
                else []
            ),
            "runCommands": _json_safe_copy(
                run_commands
                if isinstance(run_commands, Sequence)
                and not isinstance(run_commands, (str, bytes))
                else []
            ),
            "commandRows": {
                cls._command_row_target_key(row, index): {
                    key: _json_safe_copy(row.get(key))
                    for key in (
                        "commandKw",
                        "targetKw",
                        "projectedTargetKw",
                        "recoveryKw",
                        "strategyCommand",
                    )
                    if key in row
                }
                for index, row in enumerate(command_rows)
                if (type(row) is dict or isinstance(row, Mapping))
            },
        }

    @classmethod
    def _plan_with_effective_targets(
        cls,
        plan: Mapping[str, Any],
        effective_target_snapshot: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        if effective_target_snapshot is None:
            return dict(plan)
        metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
        effective_target_metrics = effective_target_snapshot.get("metrics")
        if not (type(effective_target_metrics) is dict or isinstance(effective_target_metrics, Mapping)):
            effective_target_metrics = {}
        published_metrics = {
            str(key): value
            for key, value in metrics.items()
            if "target" not in str(key).casefold()
        }
        published_metrics.update(
            {
                str(key): _json_safe_copy(value)
                for key, value in effective_target_metrics.items()
            }
        )
        published_plan = dict(plan)
        published_plan["metrics"] = published_metrics
        published_plan["commands"] = _json_safe_copy(
            effective_target_snapshot.get("commands", [])
        )
        published_plan["runCommands"] = _json_safe_copy(
            effective_target_snapshot.get("runCommands", [])
        )
        rows = plan.get("commandRows")
        command_rows = (
            rows
            if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes))
            else []
        )
        effective_command_rows = effective_target_snapshot.get("commandRows")
        if not (type(effective_command_rows) is dict or isinstance(effective_command_rows, Mapping)):
            effective_command_rows = {}
        published_rows: List[Dict[str, Any]] = []
        held_fields = {
            "commandKw",
            "targetKw",
            "projectedTargetKw",
            "recoveryKw",
            "strategyCommand",
        }
        for index, row in enumerate(command_rows):
            if not (type(row) is dict or isinstance(row, Mapping)):
                continue
            published_row = {
                str(key): value
                for key, value in row.items()
                if key not in held_fields
            }
            target_fields = effective_command_rows.get(
                cls._command_row_target_key(row, index),
                {},
            )
            if (type(target_fields) is dict or isinstance(target_fields, Mapping)):
                published_row.update(
                    {
                        str(key): _json_safe_copy(value)
                        for key, value in target_fields.items()
                    }
                )
            published_rows.append(published_row)
        published_plan["commandRows"] = published_rows
        return published_plan

    @staticmethod
    def _trend_lifecycle_changed(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
        previous_run_id = int(_number(previous.get("runId"), 0.0) or 0)
        current_run_id = int(_number(current.get("runId"), 0.0) or 0)
        if previous_run_id != current_run_id:
            return True
        previous_step = _number(previous.get("stepCount"))
        current_step = _number(current.get("stepCount"))
        if previous_step is not None and current_step is not None and current_step < previous_step:
            return True
        previous_minute = _number(previous.get("minute"))
        current_minute = _number(current.get("minute"))
        return (
            previous_minute is not None
            and current_minute is not None
            and current_minute < previous_minute
        )

    @classmethod
    def _latest_trend_segment(cls, points: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        if not points:
            return []
        segment_start = 0
        for index in range(1, len(points)):
            if cls._trend_lifecycle_changed(points[index - 1], points[index]):
                segment_start = index
        return [dict(point) for point in points[segment_start:]]

    def _update_trend(self, state: Any, plan: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
        point = self._trend_point(plan, snapshot)
        if not state.trend_normalized:
            state.trend = self._latest_trend_segment(state.trend)
            state.trend_normalized = True
        if state.trend and self._trend_lifecycle_changed(state.trend[-1], point):
            state.trend = []
        if state.trend and state.trend[-1].get("sampleKey") == point["sampleKey"]:
            state.trend[-1] = point
        else:
            state.trend.append(point)

    def _stage_trend(
        self,
        state: _ControllerState,
        plan: Mapping[str, Any],
        snapshot: Mapping[str, Any],
    ) -> _TrendCandidate:
        with state.lock:
            previous_trend = state.trend
            previous_length = len(previous_trend)
            previous_last = copy.deepcopy(previous_trend[-1]) if previous_trend else None
            was_normalized = state.trend_normalized
            candidate = _TrendCandidate(
                # Trend points are published as immutable records. A staged
                # candidate only replaces the last record or appends a new one,
                # so detaching the outer list is sufficient and avoids walking
                # the complete simulation history on every control cycle.
                trend=list(previous_trend),
                trend_normalized=state.trend_normalized,
            )
        self._update_trend(candidate, plan, snapshot)
        # 限制趋势内存与落盘上限（最多保留 4320 点），防止长时连续仿真内存与 JSONL 无限膨胀。
        max_trend_points = 4320
        trimmed_for_cap = False
        if len(candidate.trend) > max_trend_points:
            candidate.trend = candidate.trend[-max_trend_points:]
            trimmed_for_cap = True
        current_last = candidate.trend[-1] if candidate.trend else None
        lifecycle_reset = bool(
            previous_last is not None
            and current_last is not None
            and self._trend_lifecycle_changed(previous_last, current_last)
        )
        normalized_reset = bool(
            not was_normalized
            and len(self._latest_trend_segment(previous_trend)) < previous_length
        )
        changed = bool(
            len(candidate.trend) != previous_length
            or previous_last != current_last
            or trimmed_for_cap
        )
        candidate.persistence_reset = lifecycle_reset or normalized_reset or trimmed_for_cap
        candidate.persistence_replace_last = bool(
            changed
            and not candidate.persistence_reset
            and previous_last is not None
            and current_last is not None
            and str(previous_last.get("sampleKey", ""))
            == str(current_last.get("sampleKey", ""))
        )
        candidate.persistence_point = copy.deepcopy(current_last) if changed and current_last is not None else None
        return candidate

    def _command_payload(
        self,
        state: _ControllerState,
        plan: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        trigger: str,
        *,
        settings: Optional[RenewableControlSettings] = None,
        loop_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
        clock = _measurement_sample_clock(snapshot)
        metrics_payload = _json_safe_copy(metrics)
        cycle_settings = settings if settings is not None else state.settings
        cycle_loop_mode = loop_mode if loop_mode is not None else state.loop_mode
        strategy_generation = str(plan.get("clockKey", "") or "").strip()
        if not strategy_generation:
            strategy_generation = "|".join(
                str(clock.get(key, "") or "")
                for key in ("run_id", "step_count", "absolute_minute", "time")
            )
        return {
            "source": "trainee-renewable-priority-backend",
            "command_origin": "automatic",
            "strategy_id": RENEWABLE_CONTROL_STRATEGY_ID,
            "generation": strategy_generation,
            "replace_strategy_generation": True,
            "valid_for_minutes": cycle_settings.command_valid_minutes,
            "sent_wall_time": _now_text(),
            "sent_simu_time": str(clock.get("time", "")),
            "sent_absolute_minute": _number(clock.get("absolute_minute", clock.get("minute"))),
            # The simulator materializes run_status before set_values. Keeping
            # both lists in one generation preserves atomic replacement while
            # guaranteeing that a start remote control precedes its setpoint.
            "run_status": copy.deepcopy(plan.get("runCommands", [])),
            "set_values": copy.deepcopy(plan.get("commands", [])),
            "command_rows": copy.deepcopy(plan.get("commandRows", [])),
            "strategy": {
                "name": "renewable_priority",
                "strategy_id": RENEWABLE_CONTROL_STRATEGY_ID,
                "generation": strategy_generation,
                "replace_strategy_generation": True,
                "loop_mode": cycle_loop_mode,
                "trigger": trigger,
                "time": plan.get("time"),
                "metrics": metrics_payload,
                "load_kw": metrics.get("loadKw"),
                "renewable_available_kw": metrics.get("availableRenewable"),
                "renewable_used_kw": metrics.get("renewableTarget"),
                "storage_kw": metrics.get("storageTarget"),
                "storage_current_kw": metrics.get("storageCurrentKw"),
                "storage_soc": metrics.get("storageSoc"),
                "acdc_current_kw": metrics.get("acdcCurrentKw"),
                "acdc_target_kw": metrics.get("acdcTargetKw"),
                "diesel_residual_kw": metrics.get("dieselResidual"),
                "diesel_min_kw": metrics.get("dieselMinKw"),
                "diesel_target_kw": metrics.get("dieselTargetKw"),
                "curtail_kw": metrics.get("curtailKw"),
                "data_quality": plan.get("dataQuality"),
            },
        }

    def _submit_commands_for_service(
        self,
        service: Any,
        state: _ControllerState,
        payload: Mapping[str, Any],
        *,
        on_transport_start: Optional[Callable[[], None]] = None,
    ) -> Mapping[str, Any]:
        provider = self._service_bound_provider(
            self.command_sink,
            "submit_commands_for_service",
        )
        self._require_active_service_for_state(service, state)
        if on_transport_start is not None:
            on_transport_start()
        if provider is not None:
            return provider(service, payload)  # type: ignore[call-arg]
        return self.command_sink(
            str(getattr(service, "model_id", "default")),
            payload,
        )

    @staticmethod
    def _elapsed_milliseconds(started: float) -> float:
        return max(0.0, (time.perf_counter() - started) * 1000.0)

    @staticmethod
    def _snapshot_for_calculation(view: TraineeControlSnapshot) -> Dict[str, Any]:
        if bool(
            getattr(view, "snapshot_isolated", False)
            or getattr(view, "snapshot_read_only", False)
        ):
            return view.snapshot
        return copy.deepcopy(dict(view.snapshot))

    @staticmethod
    def _plan_performance_diagnostics(plan: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
        if not (type(plan) is dict or isinstance(plan, Mapping)):
            return {}
        diagnostics = plan.get("performanceDiagnostics")
        return diagnostics if (type(diagnostics) is dict or isinstance(diagnostics, Mapping)) else {}

    def _record_cycle_performance_locked(
        self,
        state: _ControllerState,
        *,
        trigger: str,
        phases_ms: Mapping[str, Any],
        plan: Mapping[str, Any],
        dispatch_attempted: bool,
        dispatch_success: Optional[bool],
    ) -> None:
        plan_diagnostics = self._plan_performance_diagnostics(plan)
        plan_phases = (
            plan_diagnostics.get("phasesMs")
            if isinstance(plan_diagnostics.get("phasesMs"), Mapping)
            else {}
        )
        normalized_phases = {
            str(name): max(0.0, float(value))
            for name, value in {**plan_phases, **dict(phases_ms)}.items()
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        }
        solver = (
            _json_safe_copy(plan_diagnostics.get("solver"))
            if isinstance(plan_diagnostics.get("solver"), Mapping)
            else {}
        )
        solver_success = solver.get("success")
        state.performance.record(
            {
                "wallTime": _now_text(),
                "simulationTime": str(plan.get("time", "--")),
                "clockKey": str(plan.get("clockKey", "")),
                "trigger": str(trigger or "manual"),
                "success": bool(solver_success is not False),
                "dispatchAttempted": bool(dispatch_attempted),
                "dispatchSuccess": dispatch_success,
                "phasesMs": normalized_phases,
                "solver": solver,
            }
        )

    def _exchange_performance_phases_for_service(
        self,
        service: Any,
    ) -> Dict[str, float]:
        try:
            status = self._receive_status_for_service(service)
        except Exception:
            return {}
        seconds_by_phase = {
            "exchangeRequestMs": status.get("requestDurationSeconds"),
            "exchangeProcessingMs": status.get(
                "refreshProcessingDurationSeconds"
            ),
            "exchangePublishMs": status.get("refreshPublishDurationSeconds"),
            "exchangeTotalMs": status.get("refreshTotalDurationSeconds"),
        }
        return {
            name: max(0.0, float(value) * 1000.0)
            for name, value in seconds_by_phase.items()
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        }

    def collect_once(self, model_id: Optional[str]) -> Dict[str, Any]:
        """Refresh the shared plan and trend without changing or dispatching control state."""
        service = self._service_for(model_id)
        state = self._state_for_service(service)
        return self._collect_once_for_service(
            service,
            state,
            raise_on_retired=True,
        )

    def _collect_once_for_service(
        self,
        service: Any,
        state: _ControllerState,
        *,
        raise_on_retired: bool,
        serialization_options: Optional[Mapping[str, Any]] = None,
        snapshot_view: Optional[TraineeControlSnapshot] = None,
        expected_receive_signature: Optional[Tuple[Any, ...]] = None,
        serialize_result: bool = True,
    ) -> Dict[str, Any]:
        response_options = dict(serialization_options or {})
        blocked = self._reject_without_receive_for_service(
            service,
            state,
            action_label="实时数据采集",
            record_log=False,
            raise_on_retired=raise_on_retired,
            serialize_result=serialize_result,
        )
        if blocked is not None:
            return blocked
        if self._receive_prerequisite_for_service(service).get("controlFrozen"):
            return self._cycle_state_result(
                service,
                state,
                serialize_result=serialize_result,
                serialization_options=response_options,
            )
        receive_signature = self._receive_state_signature_for_service(service)
        if (
            expected_receive_signature is not None
            and receive_signature != expected_receive_signature
        ):
            return self._cycle_state_result(
                service,
                state,
                serialize_result=serialize_result,
                serialization_options=response_options,
            )
        if not state.run_lock.acquire(blocking=False):
            return self._cycle_state_result(
                service,
                state,
                serialize_result=serialize_result,
                serialization_options=response_options,
            )
        cycle_started = time.perf_counter()
        cycle_phases: Dict[str, float] = {}
        cycle_plan: Optional[Dict[str, Any]] = None
        try:
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    if not (
                        self._service_instance_id(service) == state.service_instance_id
                        and self._service_instance_active_locked(service)
                    ):
                        if raise_on_retired:
                            self._require_active_service_for_state_locked(service, state)
                        return self._cycle_state_result(
                            service,
                            state,
                            serialize_result=serialize_result,
                            serialization_options=response_options,
                        )
                operation_epoch = state.operation_epoch
                cycle_settings = state.settings
            snapshot_receive_started = time.perf_counter()
            if snapshot_view is None:
                try:
                    view = self._control_snapshot_for_service(service)
                except RuntimeError:
                    cycle_phases["snapshotReceiveMs"] = self._elapsed_milliseconds(
                        snapshot_receive_started
                    )
                    if not self._service_lifecycle_valid(service, state):
                        return self._serialize_cancelled_cycle(
                            service,
                            state,
                            clear_sending=False,
                            serialize_result=serialize_result,
                        )
                    raise
            else:
                view = snapshot_view
            cycle_phases["snapshotReceiveMs"] = self._elapsed_milliseconds(
                snapshot_receive_started
            )
            snapshot_validation_started = time.perf_counter()
            if not self._view_matches_controller_state(view, state):
                return self._serialize_cancelled_cycle(
                    service,
                    state,
                    clear_sending=False,
                    serialize_result=serialize_result,
                )
            snapshot = self._snapshot_for_calculation(view)
            if self._snapshot_simulation_paused(snapshot):
                return self._cycle_state_result(
                    service,
                    state,
                    serialize_result=serialize_result,
                    serialization_options=response_options,
                )
            source = view.source
            age = view.age_seconds
            blocked = self._reject_without_receive_for_service(
                service,
                state,
                action_label="实时数据采集",
                record_log=False,
                raise_on_retired=False,
                serialize_result=serialize_result,
            )
            if blocked is not None:
                return blocked
            if self._receive_state_signature_for_service(service) != receive_signature:
                return self._serialize_cancelled_cycle(
                    service,
                    state,
                    clear_sending=False,
                    serialize_result=serialize_result,
                )
            cycle_phases["snapshotValidationMs"] = self._elapsed_milliseconds(
                snapshot_validation_started
            )
            strategy_compute_started = time.perf_counter()
            topology_static_context = self._topology_static_context_for_plan(
                state,
                view,
                snapshot,
            )
            plan = calculate_renewable_control_plan(
                snapshot,
                cycle_settings,
                data_source=source,
                snapshot_age_seconds=age,
                topology_static_context=topology_static_context,
            )
            cycle_plan = plan
            cycle_phases["strategyComputeMs"] = self._elapsed_milliseconds(
                strategy_compute_started
            )
            with state.lock:
                effective_target_snapshot = (
                    state.effective_target_snapshot
                    if state.effective_target_snapshot is not None
                    else self._capture_effective_targets(plan)
                )
            published_plan = self._plan_with_effective_targets(
                plan,
                effective_target_snapshot,
            )
            trend_started = time.perf_counter()
            trend_candidate = self._stage_trend(state, published_plan, snapshot)
            cycle_phases["trendPostprocessMs"] = self._elapsed_milliseconds(
                trend_started
            )
            committed = False
            with state.lock:
                with self._candidate_generation_guard(
                    service,
                    view,
                    receive_signature,
                ) as generation_valid:
                    if (
                        generation_valid
                        and state.operation_epoch == operation_epoch
                        and self._service_instance_id(service) == state.service_instance_id
                    ):
                        if state.effective_target_snapshot is None:
                            state.effective_target_snapshot = effective_target_snapshot
                        state.last_plan = published_plan
                        state.plan_revision += 1
                        state.last_calculated_at = _now_text()
                        state.last_clock_key = str(plan.get("clockKey", ""))
                        state.trend = trend_candidate.trend
                        state.trend_normalized = trend_candidate.trend_normalized
                        if not state.enabled and _stale_receive_prerequisite_status(state.status):
                            state.status = _RENEWABLE_READY_IDLE_STATUS
                        state.revision += 1
                        committed = True
            if not committed:
                return self._serialize_cancelled_cycle(
                    service,
                    state,
                    clear_sending=False,
                    serialize_result=serialize_result,
                )
            self._persist_trend_candidate_for_service(service, trend_candidate)
        finally:
            if cycle_plan is not None:
                cycle_phases["cycleTotalMs"] = self._elapsed_milliseconds(
                    cycle_started
                )
                cycle_phases.update(
                    self._exchange_performance_phases_for_service(service)
                )
                with state.lock:
                    self._record_cycle_performance_locked(
                        state,
                        trigger="preview",
                        phases_ms=cycle_phases,
                        plan=cycle_plan,
                        dispatch_attempted=False,
                        dispatch_success=None,
                    )
                    state.revision += 1
            state.run_lock.release()
        return self._cycle_state_result(
            service,
            state,
            serialize_result=serialize_result,
            serialization_options=response_options,
        )

    def run_once(
        self,
        model_id: Optional[str],
        *,
        trigger: str = "manual",
        allow_dispatch: bool = True,
        record_log: bool = True,
    ) -> Dict[str, Any]:
        service = self._service_for(model_id)
        state = self._state_for_service(service)
        return self._run_once_for_service(
            service,
            state,
            trigger=trigger,
            allow_dispatch=allow_dispatch,
            record_log=record_log,
            raise_on_retired=True,
        )

    def _run_once_for_service(
        self,
        service: Any,
        state: _ControllerState,
        *,
        trigger: str,
        allow_dispatch: bool,
        record_log: bool,
        raise_on_retired: bool,
        snapshot_view: Optional[TraineeControlSnapshot] = None,
        expected_receive_signature: Optional[Tuple[Any, ...]] = None,
        serialize_result: bool = True,
    ) -> Dict[str, Any]:
        blocked = self._reject_without_receive_for_service(
            service,
            state,
            action_label="实时控制" if trigger in {"start", "auto"} else "单次计算",
            record_log=record_log,
            raise_on_retired=raise_on_retired,
            serialize_result=serialize_result,
        )
        if blocked is not None:
            return blocked
        if self._receive_prerequisite_for_service(service).get("controlFrozen"):
            return self._cycle_state_result(
                service,
                state,
                serialize_result=serialize_result,
            )
        receive_signature = self._receive_state_signature_for_service(service)
        if (
            expected_receive_signature is not None
            and receive_signature != expected_receive_signature
        ):
            return self._cycle_state_result(
                service,
                state,
                serialize_result=serialize_result,
            )
        wait_for_running_cycle = trigger in {"manual", "start"}
        if wait_for_running_cycle:
            acquired = state.run_lock.acquire(timeout=_USER_CONTROL_BUSY_WAIT_SECONDS)
        else:
            acquired = state.run_lock.acquire(blocking=False)
        if not acquired:
            if wait_for_running_cycle:
                return self._busy_cycle_response(
                    service,
                    state,
                    action_label="启动实时控制" if trigger == "start" else "单次计算",
                    record_log=record_log,
                    disable_control=trigger == "start",
                    raise_on_retired=raise_on_retired,
                )
            return self._cycle_state_result(
                service,
                state,
                serialize_result=serialize_result,
            )
        cycle_started = time.perf_counter()
        cycle_phases: Dict[str, float] = {}
        cycle_plan: Optional[Dict[str, Any]] = None
        dispatch_attempted = False
        dispatch_success: Optional[bool] = None
        try:
            blocked = self._reject_without_receive_for_service(
                service,
                state,
                action_label="实时控制" if trigger in {"start", "auto"} else "单次计算",
                record_log=record_log,
                raise_on_retired=raise_on_retired,
                serialize_result=serialize_result,
            )
            if blocked is not None:
                return blocked
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    if not (
                        self._service_instance_id(service) == state.service_instance_id
                        and self._service_instance_active_locked(service)
                    ):
                        if raise_on_retired:
                            self._require_active_service_for_state_locked(service, state)
                        return self._cycle_state_result(
                            service,
                            state,
                            serialize_result=serialize_result,
                        )
                operation_epoch = state.operation_epoch
                cycle_settings = state.settings
                cycle_loop_mode = state.loop_mode
                cycle_requires_enabled = trigger in {"start", "auto"}
                if cycle_requires_enabled and not state.enabled:
                    return self._cycle_state_result(
                        service,
                        state,
                        serialize_result=serialize_result,
                    )
                state.sending = True
                state.revision += 1
            snapshot_receive_started = time.perf_counter()
            if snapshot_view is None:
                try:
                    view = self._control_snapshot_for_service(service)
                except RuntimeError:
                    cycle_phases["snapshotReceiveMs"] = self._elapsed_milliseconds(
                        snapshot_receive_started
                    )
                    if not self._service_lifecycle_valid(service, state):
                        return self._serialize_cancelled_cycle(
                            service,
                            state,
                            clear_sending=True,
                            serialize_result=serialize_result,
                        )
                    raise
            else:
                view = snapshot_view
            cycle_phases["snapshotReceiveMs"] = self._elapsed_milliseconds(
                snapshot_receive_started
            )
            snapshot_validation_started = time.perf_counter()
            if not self._view_matches_controller_state(view, state):
                return self._serialize_cancelled_cycle(
                    service,
                    state,
                    clear_sending=True,
                    serialize_result=serialize_result,
                )
            snapshot = self._snapshot_for_calculation(view)
            if self._snapshot_simulation_paused(snapshot):
                return self._serialize_cancelled_cycle(
                    service,
                    state,
                    clear_sending=True,
                    serialize_result=serialize_result,
                )
            source = view.source
            age = view.age_seconds
            fetch_error = view.error
            blocked = self._reject_without_receive_for_service(
                service,
                state,
                action_label="实时控制" if trigger in {"start", "auto"} else "单次计算",
                record_log=record_log,
                raise_on_retired=False,
                serialize_result=serialize_result,
            )
            if blocked is not None:
                with state.lock:
                    state.sending = False
                return self._cycle_state_result(
                    service,
                    state,
                    serialize_result=serialize_result,
                )
            if self._receive_state_signature_for_service(service) != receive_signature:
                return self._serialize_cancelled_cycle(
                    service,
                    state,
                    clear_sending=True,
                    serialize_result=serialize_result,
                )
            cycle_phases["snapshotValidationMs"] = self._elapsed_milliseconds(
                snapshot_validation_started
            )
            strategy_compute_started = time.perf_counter()
            topology_static_context = self._topology_static_context_for_plan(
                state,
                view,
                snapshot,
            )
            plan = calculate_renewable_control_plan(
                snapshot,
                cycle_settings,
                data_source=source,
                snapshot_age_seconds=age,
                topology_static_context=topology_static_context,
            )
            cycle_plan = plan
            cycle_phases["strategyComputeMs"] = self._elapsed_milliseconds(
                strategy_compute_started
            )
            publishes_control_targets = trigger != "preview"
            with state.lock:
                effective_target_snapshot = (
                    self._capture_effective_targets(plan)
                    if publishes_control_targets or state.effective_target_snapshot is None
                    else state.effective_target_snapshot
                )
            published_plan = self._plan_with_effective_targets(
                plan,
                effective_target_snapshot,
            )
            trend_started = time.perf_counter()
            trend_candidate = self._stage_trend(state, published_plan, snapshot)
            cycle_phases["trendPostprocessMs"] = self._elapsed_milliseconds(
                trend_started
            )
            commands = plan.get("commands") if isinstance(plan.get("commands"), Sequence) else []
            run_commands = (
                plan.get("runCommands")
                if isinstance(plan.get("runCommands"), Sequence)
                else []
            )
            has_dispatch_commands = bool(commands or run_commands)
            quality = plan.get("dataQuality") if isinstance(plan.get("dataQuality"), Mapping) else {}
            dispatch_prerequisite = self._receive_prerequisite_for_service(service)
            dispatch_generation_key = self._dispatch_generation_key(view, receive_signature)
            committed_runtime_logs: List[Dict[str, Any]] = []
            dispatch_payload: Optional[Dict[str, Any]] = None
            dispatch_clock_key = ""
            dispatch_ticket: Any = None
            dispatch_claimed = False
            committed = False
            with state.lock:
                with self._candidate_generation_guard(
                    service,
                    view,
                    receive_signature,
                ) as generation_valid:
                    controller_valid = (
                        state.operation_epoch == operation_epoch
                        and (not cycle_requires_enabled or state.enabled)
                        and self._service_instance_id(service) == state.service_instance_id
                    )
                    if not generation_valid or not controller_valid:
                        committed = False
                    else:
                        if publishes_control_targets or state.effective_target_snapshot is None:
                            state.effective_target_snapshot = effective_target_snapshot
                        state.last_plan = published_plan
                        state.plan_revision += 1
                        state.last_calculated_at = _now_text()
                        state.last_clock_key = str(plan.get("clockKey", ""))
                        state.trend = trend_candidate.trend
                        state.trend_normalized = trend_candidate.trend_normalized
                        if record_log:
                            committed_runtime_logs.append(
                                self._append_log(
                                    state,
                                    "策略决策",
                                    "计算完成",
                                    _compact_decision_log_detail(plan),
                                    full_detail=plan.get(
                                        "decisionLogDetail",
                                        plan.get("decisionDetail", []),
                                    ),
                                    level=_decision_log_level(plan),
                                    simu_time=str(plan.get("time", "--")),
                                    persist_runtime=False,
                                )
                            )

                        should_dispatch = (
                            allow_dispatch
                            and cycle_loop_mode == "closed"
                            and bool(has_dispatch_commands or state.strategy_generation_active)
                        )
                        if should_dispatch and not dispatch_prerequisite["canDispatch"]:
                            state.status = str(
                                dispatch_prerequisite.get("dispatchStatus")
                                or "实时数据状态不允许闭环下发。"
                            )
                            if record_log:
                                committed_runtime_logs.append(
                                    self._append_log(
                                        state,
                                        "策略控制",
                                        "闭环未下发",
                                        state.status,
                                        level="warn",
                                        simu_time=str(plan.get("time", "--")),
                                        persist_runtime=False,
                                    )
                                )
                        elif should_dispatch and not quality.get("dispatchAllowed"):
                            state.status = "控制策略已生成，但输入数据质量不满足闭环下发条件。"
                            if record_log:
                                committed_runtime_logs.append(
                                    self._append_log(
                                        state,
                                        "策略控制",
                                        "闭环未下发",
                                        state.status,
                                        level="warn",
                                        simu_time=str(plan.get("time", "--")),
                                        persist_runtime=False,
                                    )
                                )
                        elif should_dispatch:
                            command_serialize_started = time.perf_counter()
                            payload = self._command_payload(
                                state,
                                plan,
                                snapshot,
                                trigger,
                                settings=cycle_settings,
                                loop_mode=cycle_loop_mode,
                            )
                            cycle_phases["commandSerializeMs"] = (
                                self._elapsed_milliseconds(command_serialize_started)
                            )
                            dispatch_clock_key = str(plan.get("clockKey", "")).strip()
                            duplicate_dispatch = bool(
                                dispatch_clock_key
                                and (
                                    state.last_dispatched_clock_key == dispatch_clock_key
                                    or (
                                        state.pending_dispatch_clock_key == dispatch_clock_key
                                        and state.pending_dispatch_generation_key
                                        == dispatch_generation_key
                                    )
                                )
                            )
                            if duplicate_dispatch:
                                state.status = "当前仿真时刻已下发过控制策略，已跳过重复下发。"
                                if record_log:
                                    committed_runtime_logs.append(
                                        self._append_log(
                                            state,
                                            "策略控制",
                                            "跳过重复",
                                            state.status,
                                            level="info",
                                            simu_time=str(plan.get("time", "--")),
                                            persist_runtime=False,
                                        )
                                    )
                            else:
                                # This guarded claim is the dispatch-eligibility
                                # linearization point; transport runs after lock release.
                                if dispatch_clock_key:
                                    state.pending_dispatch_clock_key = dispatch_clock_key
                                    state.pending_dispatch_generation_key = dispatch_generation_key
                                dispatch_payload = payload
                                dispatch_ticket = getattr(generation_valid, "dispatch_ticket", None)
                                dispatch_claimed = True
                        else:
                            if not has_dispatch_commands:
                                state.status = "本轮无可调节指令。"
                            elif cycle_loop_mode == "open" or not allow_dispatch:
                                state.status = (
                                    f"开环仅计算（生成 {len(run_commands)} 遥控、{len(commands)} 遥调），未下发。"
                                )
                            if record_log:
                                committed_runtime_logs.append(
                                    self._append_log(
                                        state,
                                        "策略控制",
                                        "开环未下发" if has_dispatch_commands else "无可用策略",
                                        state.status,
                                        level="ok" if has_dispatch_commands else "warn",
                                        simu_time=str(plan.get("time", "--")),
                                        persist_runtime=False,
                                    )
                                )
                        if fetch_error and record_log:
                            committed_runtime_logs.append(
                                self._append_log(
                                    state,
                                    "数据状态",
                                    "实时获取失败",
                                    fetch_error,
                                    level="warn",
                                    simu_time=str(plan.get("time", "--")),
                                    persist_runtime=False,
                                )
                            )
                        state.revision += 1
                        committed = True

            if not committed:
                return self._serialize_cancelled_cycle(
                    service,
                    state,
                    clear_sending=True,
                    serialize_result=serialize_result,
                )
            self._persist_trend_candidate_for_service(service, trend_candidate)
            for entry in committed_runtime_logs:
                self._persist_runtime_log(state, entry)

            if dispatch_claimed and dispatch_payload is not None:
                response_runtime_logs: List[Dict[str, Any]] = []
                transport_started = False
                dispatch_attempted = True
                command_dispatch_started = time.perf_counter()

                def mark_transport_started() -> None:
                    nonlocal transport_started
                    with state.lock:
                        controller_valid = (
                            state.operation_epoch == operation_epoch
                            and (not cycle_requires_enabled or state.enabled)
                            and self._service_instance_id(service)
                            == state.service_instance_id
                            and state.pending_dispatch_clock_key == dispatch_clock_key
                            and state.pending_dispatch_generation_key
                            == dispatch_generation_key
                        )
                        if not controller_valid:
                            raise RuntimeError(
                                "控制周期状态或待下发声明已失效，未提交学员台指令。"
                            )
                        transport_started = True
                        if dispatch_clock_key:
                            state.last_dispatched_clock_key = dispatch_clock_key
                            state.last_dispatched_generation_key = dispatch_generation_key
                        if has_dispatch_commands:
                            # Treat a transport-started non-empty generation as
                            # potentially active even when the response becomes
                            # ambiguous. An explicit stop will then revoke it.
                            state.strategy_generation_active = True
                        if (
                            state.pending_dispatch_clock_key == dispatch_clock_key
                            and state.pending_dispatch_generation_key == dispatch_generation_key
                        ):
                            state.pending_dispatch_clock_key = ""
                            state.pending_dispatch_generation_key = ()

                try:
                    if dispatch_ticket is not None:
                        with state.lock:
                            dispatch_permit = dispatch_ticket.prepare(
                                dispatch_payload,
                                on_transport_start=mark_transport_started,
                            )
                        result = dispatch_permit.submit()
                    else:
                        result = self._submit_commands_for_service(
                            service,
                            state,
                            dispatch_payload,
                            on_transport_start=mark_transport_started,
                        )
                except Exception as exc:
                    dispatch_success = False
                    with state.lock:
                        if (
                            not transport_started
                            and state.pending_dispatch_clock_key == dispatch_clock_key
                            and state.pending_dispatch_generation_key == dispatch_generation_key
                        ):
                            state.pending_dispatch_clock_key = ""
                            state.pending_dispatch_generation_key = ()
                        result_guard = (
                            dispatch_ticket.guard()
                            if dispatch_ticket is not None
                            else self._candidate_generation_guard(
                                service,
                                view,
                                receive_signature,
                            )
                        )
                        with result_guard as generation_valid:
                            controller_valid = (
                                state.operation_epoch == operation_epoch
                                and (not cycle_requires_enabled or state.enabled)
                                and self._service_instance_id(service) == state.service_instance_id
                            )
                            if generation_valid and controller_valid:
                                state.status = (
                                    f"控制指令下发失败：{exc}（当前时刻不再重复发送）"
                                )
                                if record_log:
                                    response_runtime_logs.append(
                                        self._append_log(
                                            state,
                                            "指令下发",
                                            "下发失败",
                                            state.status,
                                            level="error",
                                            simu_time=str(plan.get("time", "--")),
                                            persist_runtime=False,
                                        )
                                    )
                else:
                    dispatch_success = True
                    accepted_set = (
                        int(_number(result.get("set_values"), len(commands)) or 0)
                        if (type(result) is dict or isinstance(result, Mapping))
                        else len(commands)
                    )
                    accepted_run = (
                        int(_number(result.get("run_status"), len(run_commands)) or 0)
                        if (type(result) is dict or isinstance(result, Mapping))
                        else len(run_commands)
                    )
                    with state.lock:
                        result_guard = (
                            dispatch_ticket.guard()
                            if dispatch_ticket is not None
                            else self._candidate_generation_guard(
                                service,
                                view,
                                receive_signature,
                            )
                        )
                        with result_guard as generation_valid:
                            controller_valid = (
                                state.operation_epoch == operation_epoch
                                and (not cycle_requires_enabled or state.enabled)
                                and self._service_instance_id(service) == state.service_instance_id
                            )
                            if generation_valid and controller_valid:
                                state.last_sent_at = _now_text()
                                state.last_preview_started = time.monotonic()
                                state.strategy_generation_active = has_dispatch_commands
                                state.status = (
                                    f"已下发 {accepted_run} 条遥控、{accepted_set} 条遥调指令。"
                                )
                                if record_log:
                                    response_runtime_logs.append(
                                        self._append_log(
                                            state,
                                            "指令下发",
                                            "下发成功",
                                            f"已下发遥控 {accepted_run} 条、遥调 {accepted_set} 条（仿真时刻 {plan.get('time', '--')}）",
                                            level="ok",
                                            simu_time=str(plan.get("time", "--")),
                                            persist_runtime=False,
                                        )
                                    )
                finally:
                    cycle_phases["commandDispatchMs"] = (
                        self._elapsed_milliseconds(command_dispatch_started)
                    )
                for entry in response_runtime_logs:
                    self._persist_runtime_log(state, entry)
        finally:
            if cycle_plan is not None:
                cycle_phases["cycleTotalMs"] = self._elapsed_milliseconds(
                    cycle_started
                )
                cycle_phases.update(
                    self._exchange_performance_phases_for_service(service)
                )
            with state.lock:
                state.sending = False
                if cycle_plan is not None:
                    self._record_cycle_performance_locked(
                        state,
                        trigger=trigger,
                        phases_ms=cycle_phases,
                        plan=cycle_plan,
                        dispatch_attempted=dispatch_attempted,
                        dispatch_success=dispatch_success,
                    )
                state.revision += 1
            state.run_lock.release()
            self._drain_pending_strategy_cancel(service, state)
        return self._cycle_state_result(
            service,
            state,
            serialize_result=serialize_result,
        )

    def _serialize_current_lifecycle(self, state: _ControllerState) -> Dict[str, Any]:
        try:
            current = self._state_for(state.model_id)
        except KeyError:
            current = state
        return self._serialize(current)

    @staticmethod
    def _trend_delta_locked(
        state: _ControllerState,
        *,
        after_trend_sample_key: str = "",
        after_controller_instance_id: str = "",
    ) -> Tuple[Sequence[Mapping[str, Any]], bool]:
        requested_sample_key = str(after_trend_sample_key or "")
        requested_controller_instance_id = str(after_controller_instance_id or "")
        if (
            requested_controller_instance_id
            and requested_controller_instance_id != state.service_instance_id
        ):
            requested_sample_key = ""
        trend_reset = not requested_sample_key
        trend: Sequence[Mapping[str, Any]] = state.trend
        if requested_sample_key:
            matching_index = next(
                (
                    index
                    for index in range(len(state.trend) - 1, -1, -1)
                    if str(state.trend[index].get("sampleKey", ""))
                    == requested_sample_key
                ),
                None,
            )
            if matching_index is None:
                trend_reset = True
            else:
                trend_reset = False
                # Include the cursor point so a recomputed simulation instant
                # replaces the browser's previous value instead of duplicating it.
                trend = state.trend[matching_index:]
        return trend, trend_reset

    def _serialize_with_prerequisite(
        self,
        state: _ControllerState,
        prerequisite: Mapping[str, Any],
        *,
        compact: bool = False,
        after_log_seq: int = 0,
        after_trend_sample_key: str = "",
        trend_encoding: str = "",
        after_plan_revision: Optional[int] = None,
        after_settings_revision: Optional[int] = None,
        after_performance_revision: Optional[int] = None,
        after_controller_instance_id: str = "",
        include_performance: bool = True,
        include_trend: bool = True,
    ) -> Dict[str, Any]:
        with state.lock:
            requested_log_seq = max(0, int(after_log_seq or 0))
            logs_reset = requested_log_seq <= 0 or requested_log_seq > state.log_seq
            logs = (
                state.logs
                if logs_reset
                else [
                    entry
                    for entry in state.logs
                    if int(_number(entry.get("seq"), 0.0) or 0) > requested_log_seq
                ]
            )

            trend_payload: Dict[str, Any] = {}
            if include_trend:
                trend, trend_reset = self._trend_delta_locked(
                    state,
                    after_trend_sample_key=after_trend_sample_key,
                    after_controller_instance_id=after_controller_instance_id,
                )
                trend_payload = (
                    {
                        "trendReset": trend_reset,
                        **_compact_trend_payload(
                            trend,
                            trend_encoding=trend_encoding,
                            include_fields=trend_reset,
                        ),
                    }
                    if compact
                    else {
                        "trend": list(trend),
                        "trendReset": trend_reset,
                    }
                )
            plan_cursor_matches = (
                after_plan_revision is not None
                and int(after_plan_revision) == state.plan_revision
                and str(after_controller_instance_id or "") == state.service_instance_id
            )
            performance_cursor_matches = include_performance and (
                after_performance_revision is not None
                and int(after_performance_revision) == state.performance.revision
                and str(after_controller_instance_id or "") == state.service_instance_id
            )
            settings_cursor_matches = (
                after_settings_revision is not None
                and int(after_settings_revision) == state.settings_revision
                and str(after_controller_instance_id or "")
                == state.service_instance_id
            )
            control_frozen = bool(prerequisite.get("controlFrozen"))
            payload = {
                "modelId": state.model_id,
                "controllerInstanceId": state.service_instance_id,
                "enabled": state.enabled,
                "desiredEnabled": state.desired_enabled,
                "resumePending": bool(state.desired_enabled and not state.enabled),
                "runState": (
                    "frozen"
                    if control_frozen and state.enabled
                    else "running"
                    if state.enabled
                    else "resume_pending"
                    if state.desired_enabled
                    else "stopped"
                ),
                "loopMode": state.loop_mode,
                "sending": state.sending,
                "status": (
                    "模拟台已暂停，学员台保持冻结；恢复后将继续原运行状态。"
                    if control_frozen
                    else state.status
                ),
                "planRevision": state.plan_revision,
                "settingsRevision": state.settings_revision,
                "lastCalculatedAt": state.last_calculated_at,
                "lastSentAt": state.last_sent_at,
                "lastDispatchedClockKey": state.last_dispatched_clock_key,
                "lastDispatchedGenerationKey": list(state.last_dispatched_generation_key),
                "revision": state.revision,
                "logs": list(logs),
                "logsReset": logs_reset,
                "latestLogSeq": state.log_seq,
                "latestTrendSampleKey": str(state.trend[-1].get("sampleKey", "")) if state.trend else "",
                **trend_payload,
                **prerequisite,
            }
            if include_performance:
                payload["performanceRevision"] = state.performance.revision
            if not plan_cursor_matches:
                payload["lastPlan"] = (
                    _compact_plan_for_ui(state.last_plan)
                    if compact
                    else (dict(state.last_plan) if state.last_plan is not None else None)
                )
            if not settings_cursor_matches:
                payload["settings"] = state.settings.payload()
            if include_performance and not performance_cursor_matches:
                payload["performanceDiagnostics"] = state.performance.payload()
            return payload

    def _serialize_for_service(
        self,
        service: Any,
        state: _ControllerState,
        *,
        compact: bool = False,
        after_log_seq: int = 0,
        after_trend_sample_key: str = "",
        trend_encoding: str = "",
        after_plan_revision: Optional[int] = None,
        after_settings_revision: Optional[int] = None,
        after_performance_revision: Optional[int] = None,
        after_controller_instance_id: str = "",
        include_performance: bool = True,
        include_trend: bool = True,
    ) -> Dict[str, Any]:
        prerequisite = self._receive_prerequisite_for_service(service)
        return self._serialize_with_prerequisite(
            state,
            prerequisite,
            compact=compact,
            after_log_seq=after_log_seq,
            after_trend_sample_key=after_trend_sample_key,
            trend_encoding=trend_encoding,
            after_plan_revision=after_plan_revision,
            after_settings_revision=after_settings_revision,
            after_performance_revision=after_performance_revision,
            after_controller_instance_id=after_controller_instance_id,
            include_performance=include_performance,
            include_trend=include_trend,
        )

    def _serialize(
        self,
        state: _ControllerState,
        *,
        compact: bool = False,
        after_log_seq: int = 0,
        after_trend_sample_key: str = "",
        trend_encoding: str = "",
        after_plan_revision: Optional[int] = None,
        after_settings_revision: Optional[int] = None,
        after_performance_revision: Optional[int] = None,
        after_controller_instance_id: str = "",
        include_performance: bool = True,
        include_trend: bool = True,
    ) -> Dict[str, Any]:
        try:
            service = self._service_for(state.model_id)
        except KeyError:
            service = None
        if (
            service is None
            or self._service_instance_id(service) != state.service_instance_id
        ):
            prerequisite = {
                "receiveActive": False,
                "receiveConfigured": False,
                "ready": False,
                "canRun": False,
                "canCalculate": False,
                "canDispatch": False,
                "prerequisiteStatus": "模型生命周期已失效或已退休。",
                "dispatchStatus": "模型生命周期已失效或已退休。",
            }
            return self._serialize_with_prerequisite(
                state,
                prerequisite,
                compact=compact,
                after_log_seq=after_log_seq,
                after_trend_sample_key=after_trend_sample_key,
                trend_encoding=trend_encoding,
                after_plan_revision=after_plan_revision,
                after_settings_revision=after_settings_revision,
                after_performance_revision=after_performance_revision,
                after_controller_instance_id=after_controller_instance_id,
                include_performance=include_performance,
                include_trend=include_trend,
            )
        return self._serialize_for_service(
            service,
            state,
            compact=compact,
            after_log_seq=after_log_seq,
            after_trend_sample_key=after_trend_sample_key,
            trend_encoding=trend_encoding,
            after_plan_revision=after_plan_revision,
            after_settings_revision=after_settings_revision,
            after_performance_revision=after_performance_revision,
            after_controller_instance_id=after_controller_instance_id,
            include_performance=include_performance,
            include_trend=include_trend,
        )

    def trend_history_for_service(
        self,
        service: Any,
        *,
        fields: Sequence[str],
        after_trend_sample_key: str = "",
        after_controller_instance_id: str = "",
        trend_encoding: str = _TREND_ARRAY_ENCODING,
    ) -> Dict[str, Any]:
        requested_fields: List[str] = []
        invalid_fields: List[str] = []
        allowed_fields = set(_COMPACT_TREND_FIELDS)
        for raw_field in fields:
            field = str(raw_field or "").strip()
            if not field or field in _TREND_IDENTITY_FIELDS:
                continue
            if field not in allowed_fields:
                invalid_fields.append(field)
                continue
            if field not in requested_fields:
                requested_fields.append(field)
        if invalid_fields:
            raise ValueError(
                "不支持的新能源趋势字段：" + "、".join(invalid_fields[:8])
            )
        if not requested_fields:
            raise ValueError("至少需要指定一个新能源趋势字段")

        state = self._state_for_live_service(service)
        with state.lock:
            service_lock = getattr(service, "lock", None)
            with (service_lock if service_lock is not None else nullcontext()):
                self._require_active_service_for_state_locked(service, state)
            trend, trend_reset = self._trend_delta_locked(
                state,
                after_trend_sample_key=after_trend_sample_key,
                after_controller_instance_id=after_controller_instance_id,
            )
            selected_fields = (*_TREND_IDENTITY_FIELDS, *requested_fields)
            return {
                "modelId": state.model_id,
                "controllerInstanceId": state.service_instance_id,
                "trendReset": trend_reset,
                "latestTrendSampleKey": (
                    str(state.trend[-1].get("sampleKey", ""))
                    if state.trend
                    else ""
                ),
                **_compact_trend_payload(
                    trend,
                    trend_encoding=trend_encoding,
                    include_fields=True,
                    fields=selected_fields,
                ),
            }

    def state(
        self,
        model_id: Optional[str],
        *,
        refresh: bool = False,
        compact: bool = False,
        after_log_seq: int = 0,
        after_trend_sample_key: str = "",
        trend_encoding: str = "",
        after_plan_revision: Optional[int] = None,
        after_settings_revision: Optional[int] = None,
        after_performance_revision: Optional[int] = None,
        after_controller_instance_id: str = "",
        include_performance: bool = True,
        include_trend: bool = True,
    ) -> Dict[str, Any]:
        service = self._service_for(model_id)
        return self.state_for_service(
            service,
            refresh=refresh,
            compact=compact,
            after_log_seq=after_log_seq,
            after_trend_sample_key=after_trend_sample_key,
            trend_encoding=trend_encoding,
            after_plan_revision=after_plan_revision,
            after_settings_revision=after_settings_revision,
            after_performance_revision=after_performance_revision,
            after_controller_instance_id=after_controller_instance_id,
            include_performance=include_performance,
            include_trend=include_trend,
        )

    def state_for_service(
        self,
        service: Any,
        *,
        refresh: bool = False,
        compact: bool = False,
        after_log_seq: int = 0,
        after_trend_sample_key: str = "",
        trend_encoding: str = "",
        after_plan_revision: Optional[int] = None,
        after_settings_revision: Optional[int] = None,
        after_performance_revision: Optional[int] = None,
        after_controller_instance_id: str = "",
        include_performance: bool = True,
        include_trend: bool = True,
    ) -> Dict[str, Any]:
        state = self._state_for_live_service(service)
        serialization_options = {
            "compact": compact,
            "after_log_seq": after_log_seq,
            "after_trend_sample_key": after_trend_sample_key,
            "trend_encoding": trend_encoding,
            "after_plan_revision": after_plan_revision,
            "after_settings_revision": after_settings_revision,
            "after_performance_revision": after_performance_revision,
            "after_controller_instance_id": after_controller_instance_id,
            "include_performance": include_performance,
            "include_trend": include_trend,
        }
        now = time.monotonic()
        collection_interval_seconds = self._collection_interval_seconds_for_service(
            service
        )
        if (
            refresh
            and not state.enabled
            and now - state.last_preview_started >= collection_interval_seconds
        ):
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    self._require_active_service_for_state_locked(service, state)
                    state.last_preview_started = now
            return self._collect_once_for_service(
                service,
                state,
                raise_on_retired=True,
                serialization_options=serialization_options,
            )
        return self._serialize_for_service(service, state, **serialization_options)

    def _submit_background_cycle(
        self,
        state: _ControllerState,
        *,
        timestamp_attr: str,
        timestamp: float,
        callback: Callable[..., Dict[str, Any]],
        args: Tuple[Any, ...],
        kwargs: Mapping[str, Any],
        service: Any = None,
    ) -> bool:
        def run_pending_cycle() -> Dict[str, Any]:
            try:
                return callback(*args, **dict(kwargs))
            finally:
                with state.lock:
                    state.background_cycle_pending = False
                self._wake_worker()

        with self._background_submit_lock:
            if self._closed or self._stop_event.is_set():
                return False
            if service is not None and not self._service_is_current_registry_instance(service):
                return False
            with state.lock:
                service_lock = getattr(service, "lock", None) if service is not None else None
                with (service_lock if service_lock is not None else nullcontext()):
                    if service is not None and not (
                        self._service_instance_active_locked(service)
                        and self._service_instance_id(service) == state.service_instance_id
                    ):
                        return False
                    if state.sending or state.background_cycle_pending or state.run_lock.locked():
                        return False
                    state.background_cycle_pending = True
                    setattr(state, timestamp_attr, timestamp)
                    try:
                        self._executor.submit(run_pending_cycle)
                    except Exception:
                        state.background_cycle_pending = False
                        raise
        return True

    def _execute_pending_strategy_cancel(
        self,
        service: Any,
        state: _ControllerState,
        stop_operation_epoch: int,
    ) -> None:
        with state.lock:
            cancel_allowed = bool(
                state.strategy_cancel_pending
                and state.strategy_cancel_operation_epoch == stop_operation_epoch
                and state.operation_epoch == stop_operation_epoch
                and not state.enabled
                and self._service_instance_id(service) == state.service_instance_id
            )
            if not cancel_allowed:
                if state.strategy_cancel_operation_epoch == stop_operation_epoch:
                    state.strategy_cancel_pending = False
                return
            state.strategy_cancel_pending = False

        cancel_payload = {
            "source": "trainee-renewable-priority-backend",
            "command_origin": "automatic",
            "action": "cancel_strategy_generation",
            "strategy_id": RENEWABLE_CONTROL_STRATEGY_ID,
            "cancel_all_generations": True,
            "reason": "controller_stopped",
        }
        runtime_log_entry = None
        try:
            cancel_result = self._submit_commands_for_service(
                service,
                state,
                cancel_payload,
            )
        except Exception as exc:
            with state.lock:
                if (
                    state.operation_epoch == stop_operation_epoch
                    and not state.enabled
                ):
                    state.status = (
                        "实时控制已停止，但策略代次结束状态登记失败："
                        f"{exc}；已下发指令仍按本仿真周期保持有效。"
                    )
                    runtime_log_entry = self._append_log(
                        state,
                        "策略控制",
                        "策略代次结束登记失败",
                        state.status,
                        level="error",
                        simu_time=(
                            state.last_plan.get("time", "--")
                            if state.last_plan
                            else "--"
                        ),
                        persist_runtime=False,
                    )
                    state.revision += 1
        else:
            cancelled_generations = int(
                _number(cancel_result.get("cancelled_generations"), 0.0) or 0
            ) if (type(cancel_result) is dict or isinstance(cancel_result, Mapping)) else 0
            cancelled_controls = int(
                _number(cancel_result.get("cancelled_controls"), 0.0) or 0
            ) if (type(cancel_result) is dict or isinstance(cancel_result, Mapping)) else 0
            with state.lock:
                if (
                    state.operation_epoch == stop_operation_epoch
                    and not state.enabled
                ):
                    state.strategy_generation_active = False
                    state.effective_target_snapshot = None
                    state.status = "自动实时控制已停止（已下发指令保持当前设定值）。"
                    runtime_log_entry = self._append_log(
                        state,
                        "策略控制",
                        "已停止",
                        f"自动控制已停止（涉及 {cancelled_controls} 个控制点，已下发设定值保持不变）",
                        level="ok",
                        simu_time=(
                            state.last_plan.get("time", "--")
                            if state.last_plan
                            else "--"
                        ),
                        persist_runtime=False,
                    )
                    state.revision += 1
        if runtime_log_entry is not None:
            self._persist_runtime_log_for_service(
                service,
                state,
                runtime_log_entry,
            )

    def _drain_pending_strategy_cancel(
        self,
        service: Any,
        state: _ControllerState,
    ) -> bool:
        with state.lock:
            if not state.strategy_cancel_pending:
                return False
            stop_operation_epoch = state.strategy_cancel_operation_epoch
        if not state.run_lock.acquire(blocking=False):
            return False
        try:
            self._execute_pending_strategy_cancel(
                service,
                state,
                stop_operation_epoch,
            )
        finally:
            state.run_lock.release()
        return True

    def apply_action(self, model_id: Optional[str], payload: Mapping[str, Any]) -> Dict[str, Any]:
        service = self._service_for(model_id)
        state = self._state_for_service(service)
        self._require_active_service_for_state(service, state)
        action = str(payload.get("action", "state")).strip().lower()
        settings_payload = payload.get("settings") if isinstance(payload.get("settings"), Mapping) else payload
        if action in {"update_settings", "settings"}:
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    self._require_active_service_for_state_locked(service, state)
                    requested_interval = next(
                        (
                            settings_payload[key]
                            for key in (
                                "simulation_interval_seconds",
                                "simulationIntervalSeconds",
                                "interval_seconds",
                                "intervalSeconds",
                            )
                            if key in settings_payload
                        ),
                        state.settings.interval_seconds,
                    )
                    self._validate_simulation_control_interval(
                        requested_interval,
                    )
                    next_settings = state.settings.updated(settings_payload)
                    self._validate_simulation_control_interval(
                        next_settings.interval_seconds,
                    )
                    self._validate_electrolyzer_soc_hysteresis(next_settings)
                    self._validate_hydrogen_diesel_hysteresis(next_settings)
                    self._persist_configuration(
                        service,
                        next_settings,
                        state.loop_mode,
                        state.desired_enabled,
                    )
                    if next_settings != state.settings:
                        state.operation_epoch += 1
                        state.settings_revision += 1
                    state.settings = next_settings
                    state.status = (
                        "新能源实时控制参数已更新并持久化；"
                        "自动控制周期为 "
                        f"{next_settings.interval_seconds:g} 仿真秒。"
                    )
                    state.revision += 1
            self._wake_worker()
            return self._serialize_for_service(service, state)
        if action in {"set_loop_mode", "loop_mode"}:
            next_mode = "closed" if str(payload.get("loop_mode", payload.get("loopMode", "open"))).lower() == "closed" else "open"
            runtime_log_entry = None
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    self._require_active_service_for_state_locked(service, state)
                    previous = state.loop_mode
                    self._persist_configuration(
                        service,
                        state.settings,
                        next_mode,
                        state.desired_enabled,
                    )
                    if next_mode != previous:
                        state.operation_epoch += 1
                    state.loop_mode = next_mode
                    prev_label = "闭环" if previous == "closed" else "开环"
                    next_label = "闭环" if next_mode == "closed" else "开环"
                    state.status = "已切换为闭环控制，后续策略自动下发执行。" if next_mode == "closed" else "已切换为开环模式，仅计算展示、不下发指令。"
                    runtime_log_entry = self._append_log(
                        state,
                        "策略控制",
                        "模式切换",
                        f"{prev_label} → {next_label}｜{state.status}",
                        simu_time=state.last_plan.get("time", "--") if state.last_plan else "--",
                        persist_runtime=False,
                    )
                    state.revision += 1
            try:
                self._persist_runtime_log_for_service(service, state, runtime_log_entry)
            except Exception as exc:
                _TRAINEE_CTRL_LOG.warning(
                    "Persisting loop-mode log failed for %s: %s",
                    state.model_id,
                    exc,
                )
            self._wake_worker()
            return self._serialize_for_service(service, state)
        if action == "start":
            start_operation_epoch = 0
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    self._require_active_service_for_state_locked(service, state)
                    self._validate_simulation_control_interval(
                        state.settings.interval_seconds,
                    )
                    self._persist_configuration(
                        service,
                        state.settings,
                        state.loop_mode,
                        True,
                    )
                    state.operation_epoch += 1
                    start_operation_epoch = state.operation_epoch
                    state.desired_enabled = True
            blocked = self._reject_without_receive_for_service(
                service,
                state,
                action_label="启动实时控制",
                record_log=True,
                raise_on_retired=True,
            )
            if blocked is not None:
                return blocked
            runtime_log_entry = None
            start_cancelled = False
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    self._require_active_service_for_state_locked(service, state)
                    if (
                        state.operation_epoch != start_operation_epoch
                        or not state.desired_enabled
                    ):
                        start_cancelled = True
                    else:
                        state.enabled = True
                        cycle_started_at = time.monotonic()
                        state.last_auto_started = cycle_started_at
                        state.last_preview_started = cycle_started_at
                        state.status = f"{'闭环' if state.loop_mode == 'closed' else '开环'}实时控制已在学员台后台启动。"
                        runtime_log_entry = self._append_log(
                            state,
                            "策略控制",
                            "启动",
                            state.status,
                            level="ok",
                            simu_time=state.last_plan.get("time", "--") if state.last_plan else "--",
                            persist_runtime=False,
                        )
                        state.revision += 1
            if start_cancelled:
                return self._serialize_for_service(service, state)
            defer_initial_cycle = False
            try:
                start_view = self._control_snapshot_for_service(service)
            except (KeyError, RuntimeError):
                start_view = None
            if (
                start_view is not None
                and self._view_matches_controller_state(start_view, state)
            ):
                start_clock = self._simulation_control_clock(start_view.snapshot)
                if start_clock is not None:
                    with state.lock:
                        if (
                            state.operation_epoch == start_operation_epoch
                            and state.desired_enabled
                            and state.enabled
                        ):
                            self._mark_simulation_control_started_locked(
                                state,
                                start_clock,
                            )
                            defer_initial_cycle = bool(
                                start_clock.state != "running"
                                or (
                                    start_clock.step_count <= 0
                                    and start_clock.absolute_second <= EPSILON
                                )
                            )
                            if defer_initial_cycle:
                                state.status = (
                                    f"{'闭环' if state.loop_mode == 'closed' else '开环'}"
                                    "实时控制已启动；仿真数据归零后的控制周期已从 0 重新计数。"
                                )
                                if runtime_log_entry is not None:
                                    runtime_log_entry["detail"] = state.status
                                state.revision += 1
            if runtime_log_entry is not None:
                self._persist_runtime_log_for_service(service, state, runtime_log_entry)
            if defer_initial_cycle:
                self._wake_worker()
                return self._serialize_for_service(service, state)
            result = self._run_once_for_service(
                service,
                state,
                trigger="start",
                allow_dispatch=True,
                record_log=True,
                raise_on_retired=True,
                snapshot_view=start_view,
            )
            self._wake_worker()
            return result
        if action == "stop":
            runtime_log_entry = None
            stop_operation_epoch = 0
            with state.lock:
                service_lock = getattr(service, "lock", None)
                with (service_lock if service_lock is not None else nullcontext()):
                    self._require_active_service_for_state_locked(service, state)
                    was_enabled = state.enabled
                    state.operation_epoch += 1
                    stop_operation_epoch = state.operation_epoch
                    state.enabled = False
                    state.desired_enabled = False
                    persistence_error = ""
                    try:
                        self._persist_configuration(
                            service,
                            state.settings,
                            state.loop_mode,
                            False,
                        )
                    except RuntimeError as exc:
                        persistence_error = str(exc)
                    state.strategy_cancel_pending = state.strategy_generation_active
                    state.effective_target_snapshot = None
                    state.strategy_cancel_operation_epoch = (
                        stop_operation_epoch
                        if state.strategy_cancel_pending
                        else 0
                    )
                    state.status = (
                        "实时控制已在学员台后台停止，正在结束当前策略代次；"
                        "已下发指令保持有效。"
                        if state.strategy_cancel_pending
                        else "实时控制已在学员台后台停止。"
                    )
                    if persistence_error:
                        state.status += f" 停止状态持久化失败：{persistence_error}"
                    if was_enabled:
                        runtime_log_entry = self._append_log(
                            state,
                            "策略控制",
                            "停止",
                            state.status,
                            level="warn",
                            simu_time=state.last_plan.get("time", "--") if state.last_plan else "--",
                            persist_runtime=False,
                        )
                    state.revision += 1
            if runtime_log_entry is not None:
                self._persist_runtime_log_for_service(service, state, runtime_log_entry)
            self._drain_pending_strategy_cancel(service, state)
            self._wake_worker()
            return self._serialize_for_service(service, state)
        if action in {"run_once", "calculate"}:
            result = self._run_once_for_service(
                service,
                state,
                trigger="manual",
                allow_dispatch=True,
                record_log=True,
                raise_on_retired=True,
            )
            self._wake_worker()
            return result
        if action in {"refresh", "preview"}:
            result = self._run_once_for_service(
                service,
                state,
                trigger="preview",
                allow_dispatch=False,
                record_log=False,
                raise_on_retired=True,
            )
            self._wake_worker()
            return result
        return self._serialize_for_service(service, state)

    def _run_worker_iteration(self, *, now: Optional[float] = None) -> float:
        iteration_now = time.monotonic() if now is None else float(now)
        next_deadlines: List[float] = []
        enumeration_succeeded = True
        try:
            services = (
                list(self.services.iter_services())
                if hasattr(self.services, "iter_services")
                else [self.services]
            )
        except Exception:
            services = []
            enumeration_succeeded = False
        for target in services:
            if not self._service_is_current_registry_instance(target):
                continue
            try:
                state = self._state_for_live_service(target)
                receive_prerequisite = self._receive_prerequisite_for_service(target)
            except (KeyError, RuntimeError):
                continue
            if receive_prerequisite.get("controlFrozen"):
                next_deadlines.append(iteration_now + 1.0)
                continue
            if not receive_prerequisite["canRun"]:
                if state.enabled or state.desired_enabled:
                    try:
                        self.receive_state_changed_for_service(
                            target,
                            serialize_result=False,
                        )
                    except RuntimeError:
                        pass
                next_deadlines.append(iteration_now + 1.0)
                continue
            with state.lock:
                resume_requested = bool(state.desired_enabled and not state.enabled)
            if resume_requested:
                try:
                    self.receive_state_changed_for_service(
                        target,
                        serialize_result=False,
                    )
                except RuntimeError:
                    continue
            collection_interval_seconds = max(
                0.01,
                self._collection_interval_seconds_for_service(target),
            )
            with state.lock:
                cycle_idle = (
                    not state.sending
                    and not state.background_cycle_pending
                    and not state.run_lock.locked()
                )
                enabled = state.enabled
                control_interval_seconds = max(
                    MINIMUM_CONTROL_INTERVAL_SECONDS,
                    float(state.settings.interval_seconds),
                )
                collection_deadline = (
                    state.last_preview_started + collection_interval_seconds
                )
            if not cycle_idle:
                continue
            control_clock: Optional[_SimulationControlClock] = None
            control_view: Optional[TraineeControlSnapshot] = None
            control_receive_signature: Optional[Tuple[Any, ...]] = None
            control_due = False
            if enabled:
                try:
                    schedule_view = self._control_schedule_snapshot_for_service(target)
                except (KeyError, RuntimeError):
                    schedule_view = None
                if (
                    schedule_view is not None
                    and self._view_matches_controller_state(schedule_view, state)
                ):
                    schedule_clock = self._simulation_control_clock(
                        schedule_view.snapshot
                    )
                    if not bool(
                        getattr(schedule_view, "snapshot_schedule_only", False)
                    ):
                        control_view = schedule_view
                        control_receive_signature = (
                            self._receive_state_signature_for_view(schedule_view)
                        )
                    with state.lock:
                        if state.enabled:
                            control_due = self._simulation_control_due_locked(
                                state,
                                schedule_clock,
                                control_interval_seconds,
                            )
            collection_due = iteration_now >= collection_deadline
            if control_due:
                if control_view is None:
                    try:
                        control_view = self._control_snapshot_for_service(target)
                    except (KeyError, RuntimeError):
                        control_view = None
                if (
                    control_view is None
                    or not self._view_matches_controller_state(control_view, state)
                ):
                    control_due = False
                else:
                    control_clock = self._simulation_control_clock(control_view.snapshot)
                    control_receive_signature = self._receive_state_signature_for_view(
                        control_view
                    )
            if not control_due and not collection_due:
                next_deadline = collection_deadline
                if enabled:
                    next_deadline = min(next_deadline, iteration_now + 1.0)
                next_deadlines.append(next_deadline)
                continue
            if control_due:
                try:
                    self._validate_simulation_control_interval(
                        control_interval_seconds,
                    )
                except ValueError as exc:
                    with state.lock:
                        state.enabled = False
                        state.desired_enabled = False
                        state.operation_epoch += 1
                        state.status = f"实时控制已停止：{exc}"
                        state.revision += 1
                        try:
                            self._persist_configuration(
                                target,
                                state.settings,
                                state.loop_mode,
                                False,
                            )
                        except RuntimeError as persist_exc:
                            state.status += f" 停止状态持久化失败：{persist_exc}"
                    continue
                submitted = self._submit_background_cycle(
                    state,
                    timestamp_attr="last_auto_started",
                    timestamp=iteration_now,
                    callback=self._run_once_for_service,
                    args=(target, state),
                    kwargs={
                        "trigger": "auto",
                        "allow_dispatch": True,
                        "record_log": True,
                        "raise_on_retired": False,
                        "snapshot_view": control_view,
                        "expected_receive_signature": control_receive_signature,
                        "serialize_result": False,
                    },
                    service=target,
                )
                if submitted:
                    with state.lock:
                        if control_clock is not None:
                            self._mark_simulation_control_started_locked(
                                state,
                                control_clock,
                            )
                        state.last_preview_started = iteration_now
            elif collection_due:
                self._submit_background_cycle(
                    state,
                    timestamp_attr="last_preview_started",
                    timestamp=iteration_now,
                    callback=self._collect_once_for_service,
                    args=(target, state),
                    kwargs={
                        "raise_on_retired": False,
                        "snapshot_view": control_view,
                        "expected_receive_signature": control_receive_signature,
                        "serialize_result": False,
                    },
                    service=target,
                )
        if enumeration_succeeded:
            with self._states_lock:
                states = list(self._states_by_service_instance.values())
            for state in states:
                try:
                    current = self._service_for(state.model_id)
                except KeyError:
                    current = None
                if (
                    current is not None
                    and self._service_instance_id(current) == state.service_instance_id
                ):
                    continue
                self._retire_state(state)
        if not next_deadlines:
            return 1.0
        deadline_now = time.monotonic() if now is None else iteration_now
        return max(0.01, min(1.0, min(next_deadlines) - deadline_now))

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            self._wake_event.clear()
            wait_seconds = self._run_worker_iteration()
            if self._stop_event.wait(0):
                break
            self._wake_event.wait(wait_seconds)
