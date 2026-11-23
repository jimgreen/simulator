"""PolarMicrogridSimulator 拆分模块：仿真时钟控制、步进推进、潮流内核调用与故障注入能力。"""

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


class _ClockStepMixin:
    """仿真时钟控制、步进推进、潮流内核调用与故障注入能力。"""

    def reset_runtime_for_model_change(self) -> Dict[str, int]:
        """Discard runtime artifacts and rebuild a clean in-memory state from source definitions."""
        with self.definition_update_lock:
            with self.lock:
                if self.clock.state != "stopped":
                    raise ValueError(f"模型运行中或暂停中，无法清理运行数据: {self.model_id}")
                removed = _clear_directory_contents(self.runtime_dir)
                self.runtime_dir.mkdir(parents=True, exist_ok=True)
                self.work_dir.mkdir(parents=True, exist_ok=True)

                self.compute_interval_seconds = self._initial_compute_interval_seconds
                self.storage_initial_soc = DEFAULT_STORAGE_INITIAL_SOC
                self.remote_adjustment_response_ratio = DEFAULT_REMOTE_ADJUSTMENT_RESPONSE_RATIO
                self._remote_adjustment_execution = {}
                self._remote_adjustment_cycle_seq = 0
                self.clock = ClockState()
                self.command_history = []
                self._command_history_persisted_signature = None
                self._strategy_generation_entries = {}
                self._strategy_generation_index_token = None
                self.runtime_logs = []
                self._runtime_log_seq = 0
                self._runtime_log_journal_entry_count = 0
                self._measurement_delta_seq = 0
                self._measurement_delta_state = {}
                self._measurement_delta_history = []
                self._measurement_delta_step_count = None
                self._measurement_delta_runtime_marker = None
                self._measurement_delta_definition_signature = ""
                self._measurement_delta_definition_count = 0
                self._measurement_delta_definition_revision = 0
                self._measurement_history.clear(preserve_definition=False)
                self._last_command_response_index = 0
                self.latest_result = {}
                self.latest_measurements = {}
                self.latest_measurement_clock = {}
                self.latest_model_book = None
                self.latest_device_states = []
                self.latest_real_rows = []
                self.latest_scada_rows = []
                self._fault_restore = {}
                self._last_scada_values = {}
                self._clear_manual_definition_changes_unlocked()
                with self._trainee_receive_cache_lock:
                    self._trainee_receive_cache_signature = None
                    self._trainee_receive_cache_value = None
                    self._trainee_receive_cache_next_stat_monotonic = 0.0

                self._load_runtime_state_from_disk()
                return {"removed": removed}

    def _materialize_working_weather(self) -> None:
        source = self.source_files["weather"]
        target = self.work_files["weather"]
        if not target.exists() and source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        if not target.exists():
            self._write_weather_row(DEFAULT_WEATHER | {"time": minute_to_time(0)})

    def _default_trainee_receive_state(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "initialized": False,
            "initialized_at": "",
            "active": False,
            "frozen": False,
            "interaction_link": "",
            "teacher_api_base": "",
            "teacher_model_id": "",
            "teacher_model_name": "",
            "snapshot_path": "",
            "command_path": "",
            "measurement_delta_path": "",
            "definition_archive_path": "",
            "last_receive_at": "",
            "updated_at": "",
        }

    def _apply_mode_default_clock_speed(self, mode: str, *, persist: bool) -> None:
        self.clock.step_minutes = 1.0 / 60.0
        self.clock.speed = _simulation_mode_default_clock_speed(mode)
        if not persist:
            return
        stored_params = self.local_settings.get("system_parameters", {})
        params = dict(stored_params) if (type(stored_params) is dict or isinstance(stored_params, Mapping)) else {}
        params["clock_speed"] = self.clock.speed
        self.local_settings["system_parameters"] = params
        _write_json(self.settings_file, self.local_settings)

    def _read_weather_defaults(self) -> Dict[str, Optional[float]]:
        values = dict(DEFAULT_WEATHER)
        path = self.source_files.get("weather", self.files["weather"])
        if not path.exists():
            return values
        try:
            book = EBook(path)
        except Exception:
            return values
        block = book.data.get("Weather")
        if block is None or not block.data:
            return values
        row = block.data[0]
        if "name" in block.header_list and "value" in block.header_list:
            row = {str(item.get("name", "")): item.get("value", "") for item in block.data}
        for key in DEFAULT_WEATHER:
            number = _to_float(row.get(key), None)
            if number is not None:
                values[key] = number
        return values

    def _reset_storage_soc_to_initial(self, *, sync_latest_measurements: bool = True) -> None:
        book = self.runtime_stat_book
        storage_block = book.data.get("StorageSoc") or book.data.get("StorageStatus")
        if storage_block is None:
            return
        if storage_block is not book.data.get("StorageSoc"):
            legacy_rows = [
                {
                    "dev_type": row.get("dev_type", ""),
                    "idx": row.get("idx", ""),
                    "name": row.get("name", row.get("dev_name", "")),
                    "soc_curr": row.get("soc_curr", row.get("soc", row.get("soc_cur", ""))),
                }
                for row in storage_block.data
            ]
            storage_block = _ensure_block(book, "StorageSoc", STAT_HEADERS["StorageSoc"])
            storage_block.data = legacy_rows
        else:
            storage_block = _ensure_block(book, "StorageSoc", STAT_HEADERS["StorageSoc"])
        initial_soc = _number_text(self.storage_initial_soc)
        for row in storage_block.data:
            row["soc_curr"] = initial_soc
        self.runtime_stat_book = book
        if sync_latest_measurements:
            self._sync_latest_storage_soc_measurement_rows()

    def _reset_hydrogen_storage_state_to_initial(self, *, sync_latest_measurements: bool = True) -> None:
        simu_loop.reset_hydrogen_storage_state_book(
            self.runtime_stat_book,
            self.definition_snapshot.model_book,
        )
        if sync_latest_measurements:
            self._sync_latest_hydrogen_storage_measurement_rows()

    def _storage_target_aliases(self) -> Dict[str, set[Tuple[str, str]]]:
        return resource_keys_by_alias(
            self.definition_snapshot.model_book,
            ("storage",),
        )

    def _runtime_storage_soc_values(self) -> Dict[Tuple[str, str], float]:
        storage_block = self.runtime_stat_book.data.get("StorageSoc") or self.runtime_stat_book.data.get("StorageStatus")
        resources = [
            resource
            for resource in structured_resources(self.definition_snapshot.model_book)
            if resource.technology == "storage"
        ]
        resolved: Dict[Tuple[str, str], float] = {}
        for row in getattr(storage_block, "data", []):
            value = _to_float(
                row.get("soc_curr", row.get("soc", row.get("soc_cur", 0.0))),
                0.0,
            ) or 0.0
            resource_key = resolve_resource_reference(resources, row)
            if resource_key is not None:
                resolved[resource_key] = value
        return resolved

    def _storage_runtime_protocol_keys(self) -> Dict[Tuple[str, str], set[Tuple[str, str]]]:
        resources = [
            resource
            for resource in structured_resources(self.definition_snapshot.model_book)
            if resource.technology == "storage"
        ]
        keys_by_resource = {resource.device_key: {resource.device_key} for resource in resources}
        storage_block = self.runtime_stat_book.data.get("StorageSoc") or self.runtime_stat_book.data.get("StorageStatus")
        for row in getattr(storage_block, "data", []):
            resource_key = resolve_resource_reference(resources, row)
            dev_type = str(row.get("dev_type", "")).strip()
            dev_name = str(row.get("name", row.get("dev_name", ""))).strip()
            if resource_key is not None and dev_type and dev_name:
                keys_by_resource.setdefault(resource_key, {resource_key}).add((dev_type, dev_name))
        return keys_by_resource

    def _storage_soc_identity(self, row: Mapping[str, Any]) -> Optional[Tuple[str, str, str]]:
        dev_type = str(row.get("dev_type", "")).strip()
        name = str(row.get("name", row.get("dev_name", ""))).strip()
        idx = str(row.get("idx", "")).strip()
        if dev_type and name:
            return ("name", dev_type, name)
        if dev_type and idx:
            return ("idx", dev_type, idx)
        return None

    def _merge_runtime_storage_soc(
        self,
        source_rows: Sequence[Mapping[str, Any]],
        runtime_rows: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Preserve SOC only for storage rows that still belong to the current source model."""
        runtime_by_key: Dict[Tuple[str, str, str], Mapping[str, Any]] = {}
        for row in runtime_rows:
            key = self._storage_soc_identity(row)
            if key is not None:
                runtime_by_key[key] = row

        source_list = list(source_rows)
        if not source_list:
            return [{header: row.get(header, "") for header in STAT_HEADERS["StorageSoc"]} for row in runtime_rows]

        merged: List[Dict[str, Any]] = []
        for source_row in source_list:
            row = {header: source_row.get(header, "") for header in STAT_HEADERS["StorageSoc"]}
            runtime_row = runtime_by_key.get(self._storage_soc_identity(source_row))
            if runtime_row is not None and runtime_row.get("soc_curr", "") != "":
                row["soc_curr"] = runtime_row.get("soc_curr", "")
            merged.append(row)
        return merged

    def _merge_runtime_hydrogen_storage_state(
        self,
        current_rows: Sequence[Mapping[str, Any]],
        incoming_rows: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        headers = simu_loop.HYDROGEN_STORAGE_STATE_HEADERS
        incoming_by_key = {
            simu_loop._hydrogen_storage_state_key(row): row
            for row in incoming_rows
        }
        merged: List[Dict[str, Any]] = []
        seen: set[Tuple[str, str]] = set()
        for current in current_rows:
            key = simu_loop._hydrogen_storage_state_key(current)
            incoming = incoming_by_key.get(key)
            source = incoming if incoming is not None else current
            merged.append({header: source.get(header, "") for header in headers})
            seen.add(key)
        for incoming in incoming_rows:
            key = simu_loop._hydrogen_storage_state_key(incoming)
            if key in seen:
                continue
            merged.append({header: incoming.get(header, "") for header in headers})
            seen.add(key)
        return merged

    def _execute_kernel(self, config: simu_loop.SimulationConfig) -> PowerFlowExecution:
        if self.kernel_runner is not None:
            return self.kernel_runner.run(config)
        started = time.perf_counter()
        result = self.kernel(config)
        elapsed = max(0.0, time.perf_counter() - started)
        return PowerFlowExecution(
            result=result,
            runtime_stat_book=config.dev_stat_book,
            worker_pid=os.getpid(),
            compute_seconds=elapsed,
            round_trip_seconds=elapsed,
            mode="embedded",
        )

    def _power_flow_backtrack_candidates(
        self,
        config: simu_loop.SimulationConfig,
        absolute_minute: int | float,
    ) -> Dict[Tuple[str, str, str], Tuple[float, float]]:
        tracked_keys = self._active_remote_adjustment_keys(absolute_minute) | set(
            self._remote_adjustment_execution
        )
        candidates: Dict[Tuple[str, str, str], Tuple[float, float]] = {}
        for key in sorted(tracked_keys):
            candidate = self._set_value_from_book(config.yt_ctrl_book, key)
            if candidate is None:
                candidate = self._set_value_from_book(config.dev_stat_book, key)
            actual = self._latest_true_remote_adjustment_value(key)
            state = self._remote_adjustment_execution.get(key)
            prev_executed = _to_float((state or {}).get("executed_value"), None)
            if self._is_renewable_active_power_adjustment(key):
                # 新能源有功遥调回退锚点与一阶响应一致取 max(实测, 上拍已执行设点)，
                # 防止夜间/无风实发为 0 时触发回溯误将放开的新能源上限压回 0。
                if actual is not None and prev_executed is not None:
                    actual = max(float(actual), float(prev_executed))
                elif prev_executed is not None:
                    actual = float(prev_executed)
            if candidate is None or actual is None:
                continue
            candidate = float(candidate)
            actual = float(actual)
            if not math.isfinite(candidate) or not math.isfinite(actual):
                continue
            tolerance = max(1e-9, abs(candidate) * 1e-9, abs(actual) * 1e-9)
            if abs(candidate - actual) <= tolerance:
                continue
            candidates[key] = (actual, candidate)
        return candidates

    def _config_with_power_flow_backtrack(
        self,
        config: simu_loop.SimulationConfig,
        candidates: Mapping[Tuple[str, str, str], Tuple[float, float]],
        factor: float,
    ) -> Tuple[simu_loop.SimulationConfig, List[Dict[str, Any]]]:
        stat_book = simu_loop._clone_ebook(config.dev_stat_book)
        yt_ctrl_book = simu_loop._clone_ebook(config.yt_ctrl_book)
        controls: List[Dict[str, Any]] = []
        for key, (actual, candidate) in candidates.items():
            accepted = actual + (candidate - actual) * float(factor)
            try:
                safe_accepted = self._validated_set_command_item(
                    {
                        "dev_type": key[0],
                        "dev_name": key[1],
                        "set_type": key[2],
                        "set_value": accepted,
                    },
                    strict=True,
                )
                accepted = float(safe_accepted["set_value"])
            except ValueError:
                accepted = float(actual)
            self._write_boundary_set_value(stat_book, key, accepted)
            self._write_boundary_set_value(yt_ctrl_book, key, accepted)
            controls.append(
                {
                    "key": key,
                    "actual": float(actual),
                    "candidate": float(candidate),
                    "accepted": float(accepted),
                }
            )
        return (
            replace(
                config,
                dev_stat_book=stat_book,
                yt_ctrl_book=yt_ctrl_book,
            ),
            controls,
        )

    def _execute_kernel_with_power_flow_backtrack(
        self,
        config: simu_loop.SimulationConfig,
        candidates: Mapping[Tuple[str, str, str], Tuple[float, float]],
    ) -> Tuple[PowerFlowExecution, Optional[Dict[str, Any]]]:
        started = time.perf_counter()
        try:
            return self._execute_kernel(config), None
        except Exception as initial_error:
            if not candidates or not self._is_load_flow_convergence_failure(initial_error):
                raise

            failed_factors = [1.0]
            for attempt, factor in enumerate(POWER_FLOW_BACKTRACK_FACTORS, start=1):
                retry_config, controls = self._config_with_power_flow_backtrack(
                    config,
                    candidates,
                    factor,
                )
                try:
                    execution = self._execute_kernel(retry_config)
                except Exception as retry_error:
                    if not self._is_load_flow_convergence_failure(retry_error):
                        raise
                    failed_factors.append(float(factor))
                    continue

                elapsed = max(0.0, time.perf_counter() - started)
                execution = replace(
                    execution,
                    compute_seconds=elapsed,
                    round_trip_seconds=elapsed,
                )
                return execution, {
                    "factor": float(factor),
                    "attempts": int(attempt),
                    "failed_factors": failed_factors,
                    "initial_error": f"{type(initial_error).__name__}: {initial_error}",
                    "controls": controls,
                }
            raise initial_error

    @staticmethod
    def _apply_backtrack_controls_to_pending_execution(
        pending_execution: Dict[Tuple[str, str, str], Dict[str, Any]],
        before_execution: Mapping[Tuple[str, str, str], Dict[str, Any]],
        info: Mapping[str, Any],
        cycle_token: int,
    ) -> None:
        """将回溯实际收敛的 accepted 值并入待提交遥调状态，确保受并发保护原子提交且不漏写已弹出键。"""
        controls = [
            item
            for item in info.get("controls", ())
            if (type(item) is dict or isinstance(item, Mapping))
        ]
        for item in controls:
            key = item.get("key")
            if not isinstance(key, tuple) or len(key) != 3:
                continue
            accepted = float(item.get("accepted", 0.0) or 0.0)
            state = pending_execution.get(key)
            if state is not None:
                state["executed_value"] = accepted
            else:
                # 若该键原已达到目标并从 pending 中弹出，但回溯退回至 accepted，需重新保留状态以便下拍继续过渡。
                prev = before_execution.get(key) or {}
                target_value = _to_float(
                    prev.get("target_value", item.get("candidate")),
                    float(item.get("candidate", accepted) or accepted),
                )
                pending_execution[key] = {
                    "executed_value": accepted,
                    "target_value": float(target_value if target_value is not None else accepted),
                    "last_cycle_token": cycle_token,
                }

    def _record_power_flow_backtrack(
        self,
        info: Mapping[str, Any],
        minute: int | float,
    ) -> None:
        controls = [item for item in info.get("controls", ()) if (type(item) is dict or isinstance(item, Mapping))]
        factor = float(info.get("factor", 0.0) or 0.0)

        preview = []
        for item in controls[:8]:
            key = item.get("key")
            if not isinstance(key, tuple) or len(key) != 3:
                continue
            preview.append(
                f"{key[0]}.{key[1]}.{key[2]}: "
                f"{format_number(item.get('candidate'))} -> {format_number(item.get('accepted'))}"
            )
        detail = [
            f"初始遥调边界潮流未收敛：{info.get('initial_error', '')}",
            (
                f"已将 {len(controls)} 个本轮遥调增量按 {format_number(factor * 100.0)}% "
                "接受并重算，潮流恢复收敛"
            ),
            "原遥调目标继续保留；后续周期从本次可行结果继续向目标响应",
        ]
        if preview:
            detail.append("边界回退 " + "，".join(preview) + (" ..." if len(controls) > 8 else ""))
        self._append_runtime_log(
            "潮流计算",
            "遥调边界 / 潮流可行域",
            "自动回退后收敛",
            detail,
            level="warn",
            simu_time=minute_to_time(minute),
        )

    def _weather_boundary_values(self) -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        book = self.weather_book
        block = book.data.get("Weather")
        if block is None or not block.data:
            return values
        row = block.data[0]
        return {header: row.get(header, "") for header in block.header_list}

    def _power_flow_connection_sides(
        self,
        resources: Sequence[Tuple[str, str, str]],
        definition_snapshot: Optional[DefinitionSnapshot] = None,
    ) -> Dict[Tuple[str, str], str]:
        resource_key = tuple(sorted(set(resources)))
        definition_snapshot = definition_snapshot or self.definition_snapshot
        cached = self._power_flow_connection_sides_cache
        if cached is not None and cached[0] == definition_snapshot.revision and cached[1] == resource_key:
            return dict(cached[2])

        model_book = definition_snapshot.model_book

        def rows(block_name: str) -> Sequence[Mapping[str, Any]]:
            return getattr(model_book.data.get(block_name), "data", [])

        def node_id(value: Any) -> str:
            return str(value).strip() if value is not None else ""

        adjacency: Dict[
            Tuple[str, str],
            List[Tuple[Tuple[str, str], Tuple[int, int]]],
        ] = {}

        def add_edge(
            left: Tuple[str, str],
            right: Tuple[str, str],
            cost: Tuple[int, int],
        ) -> None:
            adjacency.setdefault(left, []).append((right, cost))
            adjacency.setdefault(right, []).append((left, cost))

        same_domain_edges = (
            ("ACBranch", "ac", False),
            ("ACLine", "ac", False),
            ("ACTransformer", "ac", False),
            ("ACZeroBranch", "ac", True),
            ("ACSwitch", "ac", True),
            ("ACBreak", "ac", True),
            ("ACACConverter", "ac", False),
            ("DCBranch", "dc", False),
            ("DCLine", "dc", False),
            ("DCZeroBranch", "dc", True),
            ("DCSwitch", "dc", True),
            ("DCBreak", "dc", True),
            ("DCDCConverter", "dc", False),
        )
        for block_name, domain, switchlike in same_domain_edges:
            for row in rows(block_name):
                left_id = node_id(row.get("i_node"))
                right_id = node_id(row.get("j_node"))
                if not left_id or not right_id:
                    continue
                add_edge(
                    (domain, left_id),
                    (domain, right_id),
                    (0, 0) if switchlike else (0, 1),
                )

        for converter_type in ("ACDCConverter", "DCACConverter"):
            for row in rows(converter_type):
                ac_node = node_id(row.get("ac_node"))
                dc_node = node_id(row.get("dc_node"))
                if ac_node and dc_node:
                    add_edge(("ac", ac_node), ("dc", dc_node), (1, 1))

        anchors: Dict[Tuple[str, str], set[str]] = {}
        for block_name, domain in (("ACRealBs", "ac"), ("DCRealBs", "dc")):
            for row in rows(block_name):
                terminal = node_id(row.get("node"))
                if terminal:
                    anchors.setdefault((domain, terminal), set()).add(domain)

        generators_by_name = {
            dev_type: {
                str(row.get("name", "")).strip(): row
                for row in rows(dev_type)
                if str(row.get("name", "")).strip()
            }
            for dev_type in ("ACGenerator", "DCGenerator")
        }
        sides: Dict[Tuple[str, str], str] = {}
        for _category, dev_type, dev_name in resource_key:
            native_side = "ac" if dev_type == "ACGenerator" else "dc" if dev_type == "DCGenerator" else ""
            generator = generators_by_name.get(dev_type, {}).get(dev_name)
            terminal = node_id(generator.get("node")) if generator is not None else ""
            if not native_side or not terminal:
                continue
            start = (native_side, terminal)
            queue: List[Tuple[int, int, Tuple[str, str]]] = [(0, 0, start)]
            best_node_cost: Dict[Tuple[str, str], Tuple[int, int]] = {start: (0, 0)}
            best_anchor_cost: Dict[str, Tuple[int, int]] = {}
            while queue:
                domain_changes, hop_count, node = heapq.heappop(queue)
                cost = (domain_changes, hop_count)
                if best_node_cost.get(node) != cost:
                    continue
                node_anchors = anchors.get(node, set())
                if node_anchors:
                    for anchor_side in node_anchors:
                        current = best_anchor_cost.get(anchor_side)
                        if current is None or cost < current:
                            best_anchor_cost[anchor_side] = cost
                    continue
                for neighbor, edge_cost in adjacency.get(node, []):
                    next_cost = (cost[0] + edge_cost[0], cost[1] + edge_cost[1])
                    current = best_node_cost.get(neighbor)
                    if current is not None and current <= next_cost:
                        continue
                    best_node_cost[neighbor] = next_cost
                    heapq.heappush(queue, (next_cost[0], next_cost[1], neighbor))

            ac_cost = best_anchor_cost.get("ac")
            dc_cost = best_anchor_cost.get("dc")
            if ac_cost is None and dc_cost is None:
                continue
            if dc_cost is None or (ac_cost is not None and ac_cost < dc_cost):
                sides[(dev_type, dev_name)] = "ac"
            elif ac_cost is None or dc_cost < ac_cost:
                sides[(dev_type, dev_name)] = "dc"

        self._power_flow_connection_sides_cache = (
            definition_snapshot.revision,
            resource_key,
            dict(sides),
        )
        return sides

    def _power_flow_device_profiles(
        self,
        definition_snapshot: Optional[DefinitionSnapshot] = None,
    ) -> List[Dict[str, Any]]:
        active_snapshot = definition_snapshot or self.definition_snapshot
        model_book = active_snapshot.model_book
        resources = structured_resources(model_book)
        run_stats, _cb_status, set_values, _soc_values = self._stat_maps()
        storage_protocol_keys = self._storage_runtime_protocol_keys()
        active_adjustment_values: Dict[Tuple[str, str, str], float] = {}
        for key in self._active_remote_adjustment_keys(float(self.clock.absolute_minute)):
            value = self._set_value_from_book(self.runtime_stat_book, key)
            if value is not None:
                active_adjustment_values[key] = value
        latest_states = {
            (str(item.get("dev_type", "")), str(item.get("dev_name", item.get("name", "")))): item
            for item in self.latest_device_states
            if str(item.get("dev_type", "")) and str(item.get("dev_name", item.get("name", "")))
        }

        def block_rows(name: str) -> List[Mapping[str, Any]]:
            return list(getattr(model_book.data.get(name), "data", []))

        effective_model_book = self.latest_model_book
        effective_rows: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        if effective_model_book is not None:
            for block_name, block in effective_model_book.data.items():
                for row in getattr(block, "data", []):
                    name = str(row.get("name", "")).strip()
                    if name:
                        effective_rows[(str(block_name), name)] = row

        model_rows_by_key: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        for block_name, block in model_book.data.items():
            for row in getattr(block, "data", []):
                name = str(row.get("name", "")).strip()
                if name:
                    model_rows_by_key[(str(block_name), name)] = row
        coupling_bindings = energy_coupling_control_bindings(model_book)
        coupling_electric_endpoints = {
            (
                str(binding.get("target_dev_type", "")),
                str(binding.get("target_dev_name", "")),
            )
            for bindings in coupling_bindings.values()
            for binding in bindings
            if str(binding.get("target_dev_type", ""))
            in {"ACGenerator", "DCGenerator", "ACLoad", "DCLoad"}
        }

        weather = simu_loop._weather_values_from_book(self.weather_book)

        def is_grid_forming(side: str, mode: str) -> bool:
            normalized = str(mode or "").strip().upper().replace("-", "").replace("_", "")
            if side == "dc":
                return normalized in {"V", "VDC", "VF", "PH", "SLACK", "SWING", "VOLTAGE"}
            return normalized in {"V", "VF", "PH", "SLACK", "SWING", "VOLTAGE"}

        def flow_group_key(category: str, side: str, mode: str = "") -> str:
            if category == "wind":
                return "dcWind" if side == "dc" else "acWind"
            if category == "pv":
                return "dcSolar" if side == "dc" else "acSolar"
            if category == "storage":
                suffix = "GridFormingStorage" if is_grid_forming(side, mode) else "GridFollowingStorage"
                return f"{side}{suffix[0].upper()}{suffix[1:]}"
            if category == "diesel":
                return "diesel"
            if category == "load":
                return "dcLoad" if side == "dc" else "acLoad"
            return ""

        def profile_state_keys(dev_type: str, name: str, category: str) -> List[Tuple[str, str]]:
            source_key = (dev_type, name)
            if category != "storage":
                return [source_key]
            return sorted(storage_protocol_keys.get(source_key, {source_key}))

        def first_power_setpoint(
            state_keys: Sequence[Tuple[str, str]],
            fields: Sequence[str],
        ) -> Optional[float]:
            for state_key in state_keys:
                values = set_values.get(state_key, {})
                for field in fields:
                    value = _to_float(values.get(field), None)
                    if value is not None:
                        return float(value)
            return None

        def first_active_power_setpoint(
            state_keys: Sequence[Tuple[str, str]],
            fields: Sequence[str],
        ) -> Optional[Tuple[str, float]]:
            for state_key in state_keys:
                for field in fields:
                    value = active_adjustment_values.get((state_key[0], state_key[1], field))
                    if value is not None:
                        return field, float(value)
            return None

        def endpoint_target_value(
            bindings: Sequence[Mapping[str, Any]],
            set_type: str,
        ) -> Optional[float]:
            binding = next(
                (
                    item
                    for item in bindings
                    if str(item.get("target_set_type", item.get("set_type", "")))
                    == set_type
                ),
                None,
            )
            if binding is None:
                return None
            target_key = (
                str(binding.get("target_dev_type", "")),
                str(binding.get("target_dev_name", "")),
            )
            active_value = active_adjustment_values.get(
                (target_key[0], target_key[1], set_type)
            )
            if active_value is not None:
                return float(active_value)
            effective_row = effective_rows.get(target_key)
            value = _to_float((effective_row or {}).get(set_type), None)
            if value is not None:
                return float(value)
            value = _to_float(set_values.get(target_key, {}).get(set_type), None)
            if value is not None:
                return float(value)
            value = _to_float(model_rows_by_key.get(target_key, {}).get(set_type), None)
            return float(value) if value is not None else None

        def target_power(
            dev_type: str,
            name: str,
            category: str,
            row: Mapping[str, Any],
            state_keys: Sequence[Tuple[str, str]],
        ) -> Optional[float]:
            effective_row = effective_rows.get((dev_type, name))
            if category == "load":
                target_row = effective_row or row
                pbase = _to_float(target_row.get("pbase"), 1.0)
                if pbase is None or pbase <= 0.0:
                    pbase = 1.0
                active_power = first_active_power_setpoint(state_keys, ("p_set", "pv0"))
                if active_power is not None:
                    active_field, active_value = active_power
                    # p_set 已经是物理有功功率（kW），仅 pv0 为相对于 pbase 的倍数。
                    if active_field == "p_set":
                        return float(active_value)
                    multiplier = active_value
                elif effective_row is not None:
                    if effective_row.get("p_set") not in (None, "", "-"):
                        p_val = _to_float(effective_row.get("p_set"), None)
                        if p_val is not None:
                            return float(p_val)
                    multiplier = _to_float(target_row.get("pv0"), None)
                else:
                    p_val = first_power_setpoint(state_keys, ("p_set",))
                    if p_val is not None:
                        return float(p_val)
                    multiplier = first_power_setpoint(state_keys, ("pv0",))
                    if multiplier is None:
                        if target_row.get("p_set") not in (None, "", "-"):
                            p_val = _to_float(target_row.get("p_set"), None)
                            if p_val is not None:
                                return float(p_val)
                        multiplier = _to_float(target_row.get("pv0"), None)
                return float(pbase) * float(multiplier) if multiplier is not None else None

            if category == "converter":
                target_row = effective_row or row
                power_field = ""
                value = None
                power_fields = converter_power_setpoint_fields(target_row)
                active_power = first_active_power_setpoint(state_keys, power_fields)
                if active_power is not None:
                    power_field, value = active_power
                elif effective_row is not None:
                    for field in power_fields:
                        value = _to_float(target_row.get(field), None)
                        if value is not None:
                            power_field = field
                            break
                else:
                    for state_key in state_keys:
                        values = set_values.get(state_key, {})
                        for field in power_fields:
                            value = _to_float(values.get(field), None)
                            if value is not None:
                                power_field = field
                                break
                        if value is not None:
                            break
                    if value is None:
                        for field in power_fields:
                            value = _to_float(target_row.get(field), None)
                            if value is not None:
                                power_field = field
                                break
                if value is None:
                    return None
                return converter_power_in_dc_to_ac_convention(
                    value,
                    AC_TO_DC,
                    power_field or "p_ac_set",
                )

            active_power = first_active_power_setpoint(
                state_keys,
                ("p_set", "p_ac_set", "p_dc_set"),
            )
            if active_power is not None:
                value = active_power[1]
            elif effective_row is not None:
                value = _to_float(
                    effective_row.get(
                        "p_set",
                        effective_row.get("p_ac_set", effective_row.get("p_dc_set")),
                    ),
                    None,
                )
            else:
                value = first_power_setpoint(state_keys, ("p_set", "p_ac_set", "p_dc_set"))
                if value is None:
                    value = _to_float(
                        row.get("p_set", row.get("p_ac_set", row.get("p_dc_set"))),
                        None,
                    )
            return float(value) if value is not None else None

        def renewable_max_available(
            category: str,
            row: Mapping[str, Any],
            parameter: Mapping[str, Any],
        ) -> Optional[float]:
            rated = _to_float(
                parameter.get(
                    "rated_power",
                    parameter.get(
                        "p_max",
                        row.get("rated_capacity", row.get("p_max")),
                    ),
                ),
                None,
            )
            if rated is None:
                return None
            return renewable_weather_available_kw(
                category,
                parameter,
                rated,
                wind_speed=_to_float(weather.get("wind_speed_mps"), None),
                solar_irradiance=_to_float(
                    weather.get("solar_irradiance_w_m2"),
                    None,
                ),
                air_temperature=_to_float(weather.get("air_temp_c"), None),
            )

        def operating_state(
            dev_type: str,
            name: str,
            category: str,
            row: Mapping[str, Any],
        ) -> Tuple[int, bool]:
            state_keys = profile_state_keys(dev_type, name, category)
            run_stat: Optional[int] = None
            for key in state_keys:
                if key in run_stats:
                    run_stat = int(_to_float(run_stats[key], 1) or 0)
                    break
            if run_stat is None:
                for key in state_keys:
                    if key in latest_states:
                        run_stat = int(_to_float(latest_states[key].get("run_stat"), 1) or 0)
                        break
            if run_stat is None:
                run_stat = int(_to_float(row.get("run_stat"), 1) or 0)
            dead_island = run_stat != 0 and any(
                bool(latest_states.get(key, {}).get("dead_island", False))
                for key in state_keys
            )
            return run_stat, dead_island

        profiles: List[Dict[str, Any]] = []
        seen_profiles: set[Tuple[str, str]] = set()
        classified_generators = [
            (
                resource.source_block,
                "ac" if resource.source_block == "ACGenerator" else "dc",
                resource.source,
                resource.technology,
                resource.parameter,
            )
            for resource in resources
        ]

        connection_sides = self._power_flow_connection_sides(
            [
                (category, dev_type, str(row.get("name", "")).strip())
                for dev_type, _native_side, row, category, _parameter in classified_generators
                if category in {"wind", "pv", "storage"}
            ],
            active_snapshot,
        )
        for dev_type, native_side, row, category, parameter in classified_generators:
            name = str(row.get("name", "")).strip()
            if (dev_type, name) in coupling_electric_endpoints:
                continue
            side = connection_sides.get((dev_type, name), native_side)
            canonical = self._canonical_power_device_name(category, name)
            mode = str(
                row.get("control_type")
                or row.get("ac_control_type")
                or row.get("dc_control_type")
                or row.get("mode", "")
            )
            group_key = flow_group_key(category, side, mode)
            identity = (group_key, canonical)
            if not group_key or identity in seen_profiles:
                continue
            seen_profiles.add(identity)
            run_stat, dead_island = operating_state(dev_type, name, category, row)
            state_keys = profile_state_keys(dev_type, name, category)
            capacity = None
            if category == "storage":
                capacity = _to_float(
                    parameter.get(
                        "energy_capacity",
                        parameter.get("rated_capacity", parameter.get("emva")),
                    ),
                    None,
                )
            profiles.append(
                {
                    "dev_type": dev_type,
                    "dev_name": name,
                    "canonical_name": canonical,
                    "category": category,
                    "side": side,
                    "control_mode": mode,
                    "group_key": group_key,
                    "run_stat": run_stat,
                    "dead_island": dead_island,
                    "online": run_stat != 0 and not dead_island,
                    "capacity": float(capacity) if capacity is not None and capacity > 0 else None,
                    "state_keys": state_keys,
                    "target_power": target_power(dev_type, name, category, row, state_keys),
                    "max_available_power": renewable_max_available(category, row, parameter),
                }
            )

        internal_converter_keys = self._internal_power_converter_keys(active_snapshot)
        for converter_type in ("ACDCConverter", "DCACConverter"):
            for row in block_rows(converter_type):
                name = str(row.get("name", "")).strip()
                converter_key = (converter_type, name)
                if not name or converter_key in internal_converter_keys:
                    continue
                identity = ("acdcConverter", f"{converter_type}\0{name}")
                if identity in seen_profiles:
                    continue
                seen_profiles.add(identity)
                run_stat, dead_island = operating_state(
                    converter_type,
                    name,
                    "converter",
                    row,
                )
                state_keys = [converter_key]
                profiles.append(
                    {
                        "dev_type": converter_type,
                        "dev_name": name,
                        "canonical_name": name,
                        "category": "converter",
                        "side": "bridge",
                        "control_mode": converter_control_mode(row),
                        "converter_direction": AC_TO_DC,
                        "group_key": "acdcConverter",
                        "run_stat": run_stat,
                        "dead_island": dead_island,
                        "online": run_stat != 0 and not dead_island,
                        "capacity": None,
                        "state_keys": state_keys,
                        "target_power": target_power(
                            converter_type,
                            name,
                            "converter",
                            row,
                            state_keys,
                        ),
                        "max_available_power": None,
                    }
                )

        hydrogen_conversion_specs = (
            ("Hydro2AcE", "fuelCell", "ac", "fuelCell"),
            ("Hydro2DcE", "fuelCell", "dc", "fuelCell"),
            ("AcE2Hydro", "electrolyzer", "ac", "electrolyzer"),
            ("DcE2Hydro", "electrolyzer", "dc", "electrolyzer"),
        )
        for dev_type, category, side, group_key in hydrogen_conversion_specs:
            for row in block_rows(dev_type):
                name = str(row.get("name", "")).strip()
                bindings = coupling_bindings.get((dev_type, name), ())
                if not name or not bindings:
                    continue
                identity = (group_key, f"{dev_type}\0{name}")
                if identity in seen_profiles:
                    continue
                seen_profiles.add(identity)
                run_stat, dead_island = operating_state(dev_type, name, category, row)
                profiles.append(
                    {
                        "dev_type": dev_type,
                        "dev_name": name,
                        "canonical_name": name,
                        "category": category,
                        "side": side,
                        "control_mode": str(row.get("control_type", "")),
                        "group_key": group_key,
                        "run_stat": run_stat,
                        "dead_island": dead_island,
                        "online": run_stat != 0 and not dead_island,
                        "capacity": None,
                        "state_keys": [(dev_type, name)],
                        "measurement_keys": [
                            (dev_type, name),
                            *[
                                (
                                    str(binding.get("target_dev_type", "")),
                                    str(binding.get("target_dev_name", "")),
                                )
                                for binding in bindings
                            ],
                        ],
                        "target_power": endpoint_target_value(bindings, "p_set"),
                        "target_gas_flow": endpoint_target_value(bindings, "flow_set"),
                        "max_available_power": None,
                    }
                )

        for row in block_rows("HydroStorage"):
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            identity = ("hydrogenStorage", name)
            if identity in seen_profiles:
                continue
            seen_profiles.add(identity)
            run_stat, dead_island = operating_state(
                "HydroStorage",
                name,
                "hydrogenStorage",
                row,
            )
            capacity = _first_number(
                row,
                ("rated_capacity", "capacity", "rated_gas_capacity", "gas_capacity"),
            )
            profiles.append(
                {
                    "dev_type": "HydroStorage",
                    "dev_name": name,
                    "canonical_name": name,
                    "category": "hydrogenStorage",
                    "side": "hydrogen",
                    "control_mode": "",
                    "group_key": "hydrogenStorage",
                    "run_stat": run_stat,
                    "dead_island": dead_island,
                    "online": run_stat != 0 and not dead_island,
                    "capacity": (
                        float(capacity)
                        if capacity is not None and capacity > 0.0
                        else None
                    ),
                    "state_keys": [("HydroStorage", name)],
                    "target_power": None,
                    "target_gas_flow": None,
                    "max_available_power": None,
                }
            )

        for dev_type, side in (("ACLoad", "ac"), ("DCLoad", "dc")):
            for row in block_rows(dev_type):
                name = str(row.get("name", "")).strip()
                if not name or (dev_type, name) in coupling_electric_endpoints:
                    continue
                group_key = flow_group_key("load", side)
                identity = (group_key, name)
                if identity in seen_profiles:
                    continue
                seen_profiles.add(identity)
                run_stat, dead_island = operating_state(dev_type, name, "load", row)
                state_keys = [(dev_type, name)]
                profiles.append(
                    {
                        "dev_type": dev_type,
                        "dev_name": name,
                        "canonical_name": name,
                        "category": "load",
                        "side": side,
                        "control_mode": "",
                        "group_key": group_key,
                        "run_stat": run_stat,
                        "dead_island": dead_island,
                        "online": run_stat != 0 and not dead_island,
                        "capacity": None,
                        "state_keys": state_keys,
                        "target_power": target_power(dev_type, name, "load", row, state_keys),
                        "max_available_power": None,
                    }
                )
        return profiles

    def _power_flow_profile_indexes(
        self,
        profiles: Sequence[Mapping[str, Any]],
    ) -> Tuple[
        Dict[Tuple[str, str], Mapping[str, Any]],
        Dict[Tuple[str, str], Mapping[str, Any]],
        Dict[Tuple[str, str, str], Mapping[str, Any]],
    ]:
        by_measurement: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        by_category_name: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        by_power_key: Dict[Tuple[str, str, str], Mapping[str, Any]] = {}
        for profile in profiles:
            dev_type = str(profile.get("dev_type", ""))
            dev_name = str(profile.get("dev_name", ""))
            category = str(profile.get("category", ""))
            canonical = str(profile.get("canonical_name", dev_name))
            group_key = str(profile.get("group_key", ""))
            by_measurement[(dev_type, dev_name)] = profile
            for measurement_type, measurement_name in profile.get(
                "measurement_keys",
                (),
            ):
                by_measurement.setdefault(
                    (str(measurement_type), str(measurement_name)),
                    profile,
                )
            by_category_name[(category, canonical)] = profile
            by_power_key[(category, canonical, group_key)] = profile
            if category == "storage":
                for alias_type, alias_name in profile.get("state_keys", []):
                    by_measurement.setdefault((str(alias_type), str(alias_name)), profile)
        return by_measurement, by_category_name, by_power_key

    def _power_flow_summary(self, realtime_measurements: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        definition_snapshot = self.definition_snapshot
        internal_converter_keys = self._internal_power_converter_keys(definition_snapshot)
        profiles = self._power_flow_device_profiles(definition_snapshot)
        (
            profiles_by_measurement,
            profiles_by_category_name,
            profiles_by_power_key,
        ) = self._power_flow_profile_indexes(profiles)
        power_by_device: Dict[Tuple[str, str, str], Dict[str, float]] = {}
        soc_by_storage: Dict[str, float] = {}
        measured_converter_power_by_key: Dict[Tuple[str, str], float] = {}
        converter_dc_terminal_power_by_key: Dict[Tuple[str, str], float] = {}
        converter_power_values_by_key: Dict[Tuple[str, str], Dict[str, float]] = {}
        hydrogen_measurements_by_device: Dict[
            Tuple[str, str, str],
            Dict[str, float],
        ] = {}

        for item in realtime_measurements:
            if int(_to_float(item.get("valid"), 1) or 0) != 1:
                continue
            dev_type = str(item.get("dev_type", ""))
            dev_name = str(item.get("dev_name", ""))
            meas_type = str(item.get("meas_type", "")).upper()
            value = _to_float(item.get("value"), None)
            if not dev_type or not dev_name or meas_type == "" or value is None:
                continue
            profile = profiles_by_measurement.get((dev_type, dev_name))
            if (
                profile is not None
                and profile.get("category") == "converter"
                and meas_type in {"P_AC", "P_DC", "P"}
            ):
                converter_key = (dev_type, dev_name)
                if profile is not None and converter_key not in internal_converter_keys:
                    converter_power_values_by_key.setdefault(converter_key, {})[
                        meas_type
                    ] = value
                continue
            category = str(profile.get("category", "")) if profile else ""
            if category == "storage" and meas_type == "SOC":
                canonical_name = str(profile.get("canonical_name", dev_name))
                soc_by_storage[canonical_name] = value
                continue
            if category in {"fuelCell", "electrolyzer", "hydrogenStorage"}:
                canonical_name = str(profile.get("canonical_name", dev_name))
                group_key = str(profile.get("group_key", ""))
                hydrogen_measurements_by_device.setdefault(
                    (category, canonical_name, group_key),
                    {},
                )[meas_type] = value
                if category == "hydrogenStorage" or not meas_type.startswith("P"):
                    continue
            if not meas_type.startswith("P"):
                continue
            if not category:
                continue
            canonical_name = str(profile.get("canonical_name", dev_name))
            group_key = str(profile.get("group_key", "")) if profile else ""
            device_key = (category, canonical_name, group_key)
            power_by_device.setdefault(device_key, {})[meas_type] = value

        for converter_key, values in converter_power_values_by_key.items():
            raw_power_item = next(
                ((key, values[key]) for key in ("P_AC", "P_DC", "P") if key in values),
                None,
            )
            if raw_power_item is None:
                continue
            raw_power_type, raw_power = raw_power_item
            measured_converter_power_by_key[converter_key] = raw_power
            profile = profiles_by_measurement.get(converter_key)
            direction = str(profile.get("converter_direction", "")) if profile else ""
            if direction:
                converter_dc_terminal_power_by_key[converter_key] = (
                    converter_power_in_dc_to_ac_convention(
                        raw_power,
                        direction,
                        raw_power_type,
                    )
                )

        totals = {"wind": 0.0, "pv": 0.0, "diesel": 0.0, "load": 0.0}
        counts = {
            "wind": 0,
            "pv": 0,
            "diesel": 0,
            "load": 0,
            "storage": 0,
            "fuelCell": 0,
            "electrolyzer": 0,
            "hydrogenStorage": 0,
            "greenPowerConverter": len(measured_converter_power_by_key),
        }
        storage_generation = 0.0
        storage_charge = 0.0
        storage_total = 0.0
        fuel_cell_generation = 0.0
        electrolyzer_consumption = 0.0
        measured_group_devices: Dict[str, set[Tuple[str, str]]] = {}
        group_power_totals: Dict[str, float] = {}
        for (category, dev_name, group_key), values in power_by_device.items():
            power = self._preferred_power_value(category, values)
            if power is None:
                continue
            profile = profiles_by_power_key.get((category, dev_name, group_key))
            if profile is not None and not bool(profile.get("online", False)):
                continue
            counts[category] += 1
            if category == "storage":
                storage_total += power
                if power >= 0.0:
                    storage_generation += power
                else:
                    storage_charge += -power
            elif category == "fuelCell":
                fuel_cell_generation += power
            elif category == "electrolyzer":
                electrolyzer_consumption += power
            else:
                totals[category] += power

            if profile is not None:
                if group_key:
                    group_power_totals[group_key] = group_power_totals.get(group_key, 0.0) + power
                    measured_group_devices.setdefault(group_key, set()).add(
                        (
                            str(profile.get("dev_type", "")),
                            str(profile.get("dev_name", dev_name)),
                        )
                    )

        for converter_key, power in converter_dc_terminal_power_by_key.items():
            profile = profiles_by_measurement.get(converter_key)
            if profile is None or not bool(profile.get("online", False)):
                continue
            group_key = str(profile.get("group_key", ""))
            if not group_key:
                continue
            group_power_totals[group_key] = group_power_totals.get(group_key, 0.0) + power
            measured_group_devices.setdefault(group_key, set()).add(converter_key)

        soc_values = [value * 100.0 if abs(value) <= 2.0 else value for value in soc_by_storage.values()]
        soc_average = sum(soc_values) / len(soc_values) if soc_values else None
        soc_total = sum(soc_by_storage.values()) if soc_values else None
        has_power = any(
            counts[key]
            for key in (
                "wind",
                "pv",
                "diesel",
                "load",
                "storage",
                "fuelCell",
                "electrolyzer",
            )
        )
        load_total = totals["load"] + electrolyzer_consumption
        generation_total = (
            totals["wind"]
            + totals["pv"]
            + totals["diesel"]
            + storage_generation
            + fuel_cell_generation
        )
        consumption_total = load_total + storage_charge
        power_difference = generation_total - consumption_total
        flow_groups: Dict[str, Dict[str, Any]] = {}
        group_target_totals: Dict[str, float] = {}
        group_target_counts: Dict[str, int] = {}
        group_target_gas_flow_totals: Dict[str, float] = {}
        group_target_gas_flow_counts: Dict[str, int] = {}
        group_available_totals: Dict[str, float] = {}
        group_available_counts: Dict[str, int] = {}
        for profile in profiles:
            group_key = str(profile.get("group_key", ""))
            if not group_key:
                continue
            group = flow_groups.setdefault(
                group_key,
                {
                    "category": profile.get("category", ""),
                    "side": profile.get("side", ""),
                    "powerConvention": (
                        "P_DC"
                        if profile.get("category") == "converter"
                        else ""
                    ),
                    "controlMode": (
                        str(profile.get("control_mode", "")).strip().upper()
                        if profile.get("category") in {"fuelCell", "electrolyzer"}
                        else "gridForming"
                        if "GridForming" in group_key
                        else "gridFollowing"
                        if "GridFollowing" in group_key
                        else ""
                    ),
                    "power": None,
                    "targetPower": None,
                    "maxAvailablePower": None,
                    "gasFlow": None,
                    "targetGasFlow": None,
                    "gasPressure": None,
                    "gasQuantity": None,
                    "soc": None,
                    "totalCount": 0,
                    "onlineCount": 0,
                    "retiredCount": 0,
                    "deadIslandCount": 0,
                    "measuredCount": 0,
                },
            )
            if profile.get("category") in {"fuelCell", "electrolyzer"}:
                profile_mode = str(profile.get("control_mode", "")).strip().upper()
                group_mode = str(group.get("controlMode", "")).strip().upper()
                if profile_mode and group_mode and profile_mode != group_mode:
                    group["controlMode"] = "MIXED"
                elif profile_mode:
                    group["controlMode"] = profile_mode
            group["totalCount"] += 1
            if int(profile.get("run_stat", 1) or 0) == 0:
                group["retiredCount"] += 1
            elif bool(profile.get("dead_island", False)):
                group["deadIslandCount"] += 1
            else:
                group["onlineCount"] += 1
                target = _to_float(profile.get("target_power"), None)
                if target is not None:
                    group_target_totals[group_key] = group_target_totals.get(group_key, 0.0) + target
                    group_target_counts[group_key] = group_target_counts.get(group_key, 0) + 1
                target_gas_flow = _to_float(profile.get("target_gas_flow"), None)
                if target_gas_flow is not None:
                    group_target_gas_flow_totals[group_key] = (
                        group_target_gas_flow_totals.get(group_key, 0.0)
                        + target_gas_flow
                    )
                    group_target_gas_flow_counts[group_key] = (
                        group_target_gas_flow_counts.get(group_key, 0) + 1
                    )
                available = _to_float(profile.get("max_available_power"), None)
                if available is not None:
                    group_available_totals[group_key] = group_available_totals.get(group_key, 0.0) + available
                    group_available_counts[group_key] = group_available_counts.get(group_key, 0) + 1

        hydrogen_metric_values: Dict[str, Dict[str, List[Tuple[float, float]]]] = {}
        hydrogen_measured_devices: Dict[str, set[Tuple[str, str]]] = {}
        for (category, dev_name, group_key), values in hydrogen_measurements_by_device.items():
            profile = profiles_by_power_key.get((category, dev_name, group_key))
            if profile is None or not bool(profile.get("online", False)):
                continue
            device_key = (
                str(profile.get("dev_type", "")),
                str(profile.get("dev_name", dev_name)),
            )
            measured_group_devices.setdefault(group_key, set()).add(device_key)
            hydrogen_measured_devices.setdefault(category, set()).add(device_key)
            metrics = hydrogen_metric_values.setdefault(group_key, {})
            capacity = _to_float(profile.get("capacity"), None)
            if "FLOW" in values:
                metrics.setdefault("gasFlow", []).append((float(values["FLOW"]), 1.0))
            if category == "hydrogenStorage":
                pressure = values.get("PRESSURE")
                if pressure is not None:
                    metrics.setdefault("gasPressure", []).append((float(pressure), 1.0))
                if "GAS_QUANTITY" in values:
                    gas_quantity = float(values["GAS_QUANTITY"])
                    metrics.setdefault("gasQuantity", []).append(
                        (gas_quantity, 1.0)
                    )
                    if capacity is not None and capacity > 0.0:
                        metrics.setdefault("soc", []).append(
                            (gas_quantity / capacity * 100.0, float(capacity))
                        )
                elif "SOC" in values:
                    raw_soc = float(values["SOC"])
                    soc_percent = raw_soc * 100.0 if abs(raw_soc) <= 2.0 else raw_soc
                    metrics.setdefault("soc", []).append(
                        (soc_percent, max(1e-9, float(capacity or 1.0)))
                    )

        counts["hydrogenStorage"] = len(
            hydrogen_measured_devices.get("hydrogenStorage", set())
        )
        for group_key, metric_values in hydrogen_metric_values.items():
            group = flow_groups.get(group_key)
            if group is None:
                continue
            for metric_name, values in metric_values.items():
                if not values:
                    continue
                if metric_name in {"gasPressure", "soc"}:
                    total_weight = sum(weight for _value, weight in values)
                    group[metric_name] = (
                        sum(value * weight for value, weight in values) / total_weight
                        if total_weight > 0.0
                        else None
                    )
                else:
                    group[metric_name] = sum(value for value, _weight in values)

        for group_key, group in flow_groups.items():
            online_count = int(group.get("onlineCount", 0) or 0)
            if online_count == 0:
                group["targetPower"] = 0.0
                if str(group.get("category", "")) in {"wind", "pv"}:
                    group["maxAvailablePower"] = 0.0
            elif group_target_counts.get(group_key, 0) == online_count:
                group["targetPower"] = group_target_totals.get(group_key, 0.0)
            if online_count == 0:
                group["targetGasFlow"] = 0.0
            elif group_target_gas_flow_counts.get(group_key, 0) == online_count:
                group["targetGasFlow"] = group_target_gas_flow_totals.get(
                    group_key,
                    0.0,
                )
            if (
                str(group.get("category", "")) in {"wind", "pv"}
                and group_available_counts.get(group_key, 0) == online_count
            ):
                group["maxAvailablePower"] = group_available_totals.get(group_key, 0.0)
            measured_devices = measured_group_devices.get(group_key, set())
            group["measuredCount"] = len(measured_devices)
            if measured_devices:
                group["power"] = group_power_totals.get(group_key, 0.0)
            elif int(group.get("onlineCount", 0) or 0) == 0:
                group["power"] = 0.0

        storage_soc_groups: Dict[str, List[Tuple[float, float]]] = {}
        for storage_name, raw_soc in soc_by_storage.items():
            profile = profiles_by_category_name.get(("storage", storage_name))
            if profile is None:
                continue
            group_key = str(profile.get("group_key", ""))
            if not group_key:
                continue
            soc_percent = raw_soc * 100.0 if abs(raw_soc) <= 2.0 else raw_soc
            weight = _to_float(profile.get("capacity"), 1.0) or 1.0
            storage_soc_groups.setdefault(group_key, []).append((soc_percent, max(1e-9, float(weight))))
        for group_key, values in storage_soc_groups.items():
            total_weight = sum(weight for _soc, weight in values)
            if total_weight > 0 and group_key in flow_groups:
                flow_groups[group_key]["soc"] = sum(soc * weight for soc, weight in values) / total_weight

        for group in flow_groups.values():
            status, direction = self._flow_group_status(group)
            group["status"] = status
            group["flowDirection"] = direction

        def green_metric_group_power(group_key: str) -> Optional[float]:
            group = flow_groups.get(group_key)
            if group is None:
                return 0.0
            return _to_float(group.get("power"), None)

        dc_load_power = green_metric_group_power("dcLoad")
        ac_load_power = green_metric_group_power("acLoad")
        electrolyzer_power = green_metric_group_power("electrolyzer")
        diesel_power = green_metric_group_power("diesel")
        if any(
            value is None
            for value in (
                dc_load_power,
                ac_load_power,
                electrolyzer_power,
                diesel_power,
            )
        ):
            green_power = None
            green_power_share = None
        else:
            green_load_power = (
                float(dc_load_power)
                + float(ac_load_power)
                + float(electrolyzer_power)
            )
            green_power = green_load_power - float(diesel_power)
            green_power_share = (
                green_power / green_load_power * 100.0
                if abs(green_load_power) > 1e-9
                else None
            )
        return {
            "wind": totals["wind"] if counts["wind"] else None,
            "solar": totals["pv"] if counts["pv"] else None,
            "diesel": totals["diesel"] if counts["diesel"] else None,
            "load": (
                load_total
                if counts["load"] or counts["electrolyzer"]
                else None
            ),
            "storage": storage_total if counts["storage"] else None,
            "storageDischarge": storage_generation if counts["storage"] else None,
            "storageCharge": storage_charge if counts["storage"] else None,
            "greenPower": green_power,
            "greenPowerShare": green_power_share,
            "soc": soc_average,
            "socTotal": soc_total if soc_values else None,
            "generation": generation_total if has_power else None,
            "consumption": consumption_total if has_power else None,
            "balance": power_difference if has_power else None,
            "flowGroups": flow_groups,
            "counts": {
                "wind": counts["wind"],
                "solar": counts["pv"],
                "diesel": counts["diesel"],
                "load": counts["load"],
                "storage": counts["storage"],
                "fuelCell": counts["fuelCell"],
                "electrolyzer": counts["electrolyzer"],
                "hydrogenStorage": counts["hydrogenStorage"],
                "greenPowerConverter": counts["greenPowerConverter"],
                "soc": len(soc_values),
            },
        }

    def _power_flow_summary_lines(self, real_measurements: Sequence[Mapping[str, Any]]) -> List[str]:
        summary = self._power_flow_summary(real_measurements)
        counts = summary["counts"]
        wind = summary["wind"] if summary["wind"] is not None else 0.0
        solar = summary["solar"] if summary["solar"] is not None else 0.0
        diesel = summary["diesel"] if summary["diesel"] is not None else 0.0
        load = summary["load"] if summary["load"] is not None else 0.0
        storage_generation = (
            summary["storageDischarge"] if summary["storageDischarge"] is not None else 0.0
        )
        storage_charge = summary["storageCharge"] if summary["storageCharge"] is not None else 0.0
        soc_average = summary["soc"]
        soc_total = summary["socTotal"]
        soc_text = (
            f"储能SOC 平均 {format_number(soc_average)}%，储能总SOC {format_number(soc_total)}，台数 {counts['soc']}"
            if soc_average is not None
            else "储能SOC 平均 --，储能总SOC --，台数 0"
        )
        generation_total = summary["generation"] if summary["generation"] is not None else 0.0
        consumption_total = summary["consumption"] if summary["consumption"] is not None else 0.0
        power_difference = summary["balance"] if summary["balance"] is not None else 0.0
        return [
            (
                f"分类统计 风力发电总功率 {format_number(wind)} kW（{counts['wind']} 台），"
                f"光伏发电总功率 {format_number(solar)} kW（{counts['solar']} 台）"
            ),
            (
                f"分类统计 柴油发电总功率 {format_number(diesel)} kW（{counts['diesel']} 台），"
                f"负荷用电总功率 {format_number(load)} kW（{counts['load']} 个）"
            ),
            (
                f"分类统计 储能发电总功率 {format_number(storage_generation)} kW，"
                f"储能充电总功率 {format_number(storage_charge)} kW（{counts['storage']} 台），{soc_text}"
            ),
            (
                f"功率平衡 电源发电总功率 {format_number(generation_total)} kW，"
                f"用电及充电总功率 {format_number(consumption_total)} kW，"
                f"功率差额 {format_number(power_difference)} kW（含网络与变流损耗）"
            ),
        ]

    def _append_power_flow_log(
        self,
        result: Mapping[str, Any],
        measurements: Mapping[str, Sequence[Mapping[str, Any]]],
        minute: int | float,
        absolute_minute: int | float,
        clock_advance: int | float,
        period_seconds: float,
        command_response_lines: Sequence[str],
    ) -> None:
        real_measurements = measurements.get("real", [])
        simu_time = minute_to_time(minute)
        control_detail = [
            *self._compact_command_response_lines(command_response_lines),
            *self._input_boundary_lines(minute, absolute_minute, clock_advance, period_seconds),
        ]
        power_flow_detail = [
            (
                f"计算摘要 时刻 {simu_time}，累计分钟 {absolute_minute}，推进 {clock_advance} min，"
                f"求解器 {result.get('solver_info', 'not-run')}，"
                f"真值量测 {len(real_measurements)} 条，更新 {result.get('updated', 0)} 条，"
                f"缺失 {result.get('missing', 0)} 条，叠加修正 {result.get('overlay_updates', 0)} 条"
            ),
            *self._power_flow_summary_lines(real_measurements),
        ]
        missing_measurements = [
            item
            for item in (result.get("missing_measurements") or [])
            if (type(item) is dict or isinstance(item, Mapping))
        ]
        if missing_measurements:
            missing_preview = "，".join(
                f"{item.get('dev_type', '')}.{item.get('dev_name', '')}.{item.get('meas_type', '')}"
                for item in missing_measurements[:12]
            )
            power_flow_detail.append(
                f"缺失测点 {missing_preview}"
                + (f"，其余 {len(missing_measurements) - 12} 条" if len(missing_measurements) > 12 else "")
            )
        has_missing = int(_to_float(result.get("missing"), 0) or 0) != 0
        operating_warnings = [
            dict(item)
            for item in (result.get("operating_warnings") or [])
            if (type(item) is dict or isinstance(item, Mapping))
        ]
        log_entries: List[Dict[str, Any]] = [
            {
                "log_type": "控制响应",
                "target": "运行边界 / 控制指令",
                "result": "完成",
                "detail": control_detail,
                "level": "ok",
                "simu_time": simu_time,
            },
            {
                "log_type": "潮流计算",
                "target": "内存模型 / 量测快照",
                "result": "有缺失" if has_missing else "完成",
                "detail": power_flow_detail,
                "level": "warn" if has_missing else "ok",
                "simu_time": simu_time,
            },
        ]
        if operating_warnings:
            has_error_warning = any(
                str(item.get("severity", "")).strip().lower() == "error"
                for item in operating_warnings
            )
            device_labels: List[str] = []
            for item in operating_warnings:
                label = str(item.get("dev_name", "") or item.get("dev_type", "")).strip()
                if label and label not in device_labels:
                    device_labels.append(label)
            target_text = "、".join(device_labels[:3])
            if len(device_labels) > 3:
                target_text += f" 等 {len(device_labels)} 台设备"
            warning_detail = [
                str(item.get("message", "")).strip()
                for item in operating_warnings
                if str(item.get("message", "")).strip()
            ]
            if not warning_detail:
                warning_detail = [
                    f"{item.get('dev_type', '')}/{item.get('dev_name', '')} {item.get('metric', '')} 越界"
                    for item in operating_warnings
                ]
            log_entries.append(
                {
                    "log_type": "运行告警",
                    "target": target_text or "设备运行越界",
                    "result": (
                        f"严重越界 ({len(operating_warnings)} 项)"
                        if has_error_warning
                        else f"越界告警 ({len(operating_warnings)} 项)"
                    ),
                    "detail": warning_detail,
                    "level": "error" if has_error_warning else "warn",
                    "simu_time": simu_time,
                }
            )
        self._append_runtime_log_batch(tuple(log_entries))

    def _power_flow_failure_result(self, error: BaseException) -> str:
        text = f"{type(error).__name__}: {error}".casefold()
        divergence_markers = (
            "normf=nan",
            "normf=inf",
            "nan",
            "overflow",
            "singular",
            "未收敛",
            "发散",
            "load flow failed",
            "潮流",
        )
        return "数值发散" if any(marker in text for marker in divergence_markers) else "失败"

    def _append_power_flow_failure_log(
        self,
        error: BaseException,
        minute: int | float,
        absolute_minute: int | float,
        clock_advance: int | float,
        period_seconds: float,
        *,
        auto_paused: bool,
    ) -> None:
        simu_time = minute_to_time(minute)
        result = self._power_flow_failure_result(error)
        detail = [
            (
                f"计算失败 时刻 {simu_time}，累计分钟 {format_number(absolute_minute)}，"
                f"推进 {format_number(clock_advance * 60.0)} s，"
                f"仿真周期 {format_number(period_seconds)} s"
            ),
            f"失败类型 {result}，异常 {type(error).__name__}: {error}",
            (
                "处理措施 本轮潮流结果未写入，仿真时钟不推进；运行中的仿真已自动暂停"
                if auto_paused
                else "处理措施 本轮潮流结果未写入，仿真时钟不推进；当前时钟状态保持不变"
            ),
            *self._input_boundary_lines(minute, absolute_minute, clock_advance, period_seconds),
        ]
        self._append_runtime_log(
            "潮流计算",
            "内存模型 / 量测快照",
            result,
            detail,
            level="error",
            simu_time=simu_time,
        )

    def _invalidate_automatic_runtime_state_for_simulation_reset(self) -> None:
        """Drop the completed automatic frame while preserving manual definitions and controls."""

        # Keep the current, possibly manually edited definition rows available to
        # clients, but detach every calculated value from the new lifecycle.
        current_measurements = self.measurements()
        definitions = [
            dict(row)
            for row in current_measurements.get("definitions", [])
            if (type(row) is dict or isinstance(row, Mapping))
        ]
        self.latest_real_rows = []
        self.latest_scada_rows = []
        self._automatic_runtime_state_invalidated = True
        self.latest_measurements = {
            "definitions": definitions,
            "real": [],
            "scada": [],
        }
        self.latest_measurement_clock = {}
        self.latest_result = {}
        self.latest_model_book = None
        self.latest_device_states = []
        self._last_scada_values = {}
        self._latest_power_summary_cache_key = None
        self._latest_power_summary_cache_value = None
        self._device_runtime_frame_cache_key = None
        self._device_runtime_frame_cache_value = None
        self._measurement_history.clear()

        # Keep the sequence monotonic across a same-service clock reset.  The
        # empty history then forces every cursor from the previous lifecycle to
        # receive a full reset frame instead of accidentally matching by seq.
        self._measurement_delta_seq += 1
        self._measurement_delta_state = self._measurement_delta_current_items(
            self.latest_measurements,
            measurement_clock=self.clock.as_dict(),
        )
        self._measurement_delta_history = []
        self._measurement_delta_definition_signature = measurement_definition_signature(
            definitions
        )
        self._measurement_delta_definition_count = len(definitions)
        self._measurement_delta_definition_revision = self.definition_snapshot.revision
        self._measurement_delta_step_count = self.clock.step_count
        self._measurement_delta_runtime_marker = self._measurement_delta_runtime_state_marker()

        compute = dict(self.latest_compute)
        self.latest_compute = {
            "mode": str(compute.get("mode", "embedded")),
            "http_pid": int(compute.get("http_pid", os.getpid()) or os.getpid()),
            "worker_pid": int(compute.get("worker_pid", 0) or 0),
            "compute_ms": 0.0,
            "round_trip_ms": 0.0,
            "status": "idle",
            "resident_model": bool(compute.get("resident_model", self.kernel_runner is None)),
        }

        for path in (self.files["real"], self.files["scada"]):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def clock_state(self) -> Dict[str, Any]:
        """Return only the scheduler clock state without assembling a service snapshot."""
        with self.lock:
            return self.clock.as_dict()

    def step(
        self,
        advance_minutes: Optional[int | float] = None,
        *,
        advance_seconds: Optional[int | float] = None,
        return_snapshot: bool = True,
    ) -> Optional[Dict[str, Any]]:
        with self._step_lock:
            with self.lock:
                if advance_seconds is not None:
                    clock_advance = max(1e-9, float(advance_seconds) / 60.0)
                elif advance_minutes is not None:
                    clock_advance = max(1e-9, float(advance_minutes))
                else:
                    clock_advance = _effective_clock_step(self.clock.step_minutes, self.clock.speed)
                # 保持仿真时钟在切换倍率或求解前单调连续，不因对齐粗网格而跳空或提前改写时钟。
                self.clock.minute = self.clock.absolute_minute % 1440.0
                period_seconds = clock_advance * 60.0
                minute = self.clock.minute
                absolute_minute = self.clock.absolute_minute
                start_clock_state = self.clock.state
                start_run_id = self.clock.run_id
                start_step_count = self.clock.step_count
                definition_revision = self.definition_snapshot.revision
                curve_revision = self._curve_revision
                self._remote_adjustment_cycle_seq += 1
                before_remote_adjustment_execution = {
                    key: dict(value)
                    for key, value in self._remote_adjustment_execution.items()
                }
                (
                    boundary_stat_book,
                    boundary_yt_ctrl_book,
                    pending_remote_adjustment_execution,
                ) = self._prepare_runtime_inputs(
                    minute,
                    absolute_minute,
                    remote_adjustment_cycle_token=self._remote_adjustment_cycle_seq,
                    period_seconds=period_seconds,
                    defer_remote_adjustment_commit=True,
                )
                config = self._make_config(
                    period_seconds=period_seconds,
                    dev_stat_book=boundary_stat_book,
                    yt_ctrl_book=boundary_yt_ctrl_book,
                )
                backtrack_candidates = self._power_flow_backtrack_candidates(
                    config,
                    absolute_minute,
                )

            execution_started = time.perf_counter()
            try:
                execution, backtrack_info = self._execute_kernel_with_power_flow_backtrack(
                    config,
                    backtrack_candidates,
                )
            except Exception as exc:
                elapsed = max(0.0, time.perf_counter() - execution_started)
                compute_status = "timeout" if isinstance(exc, PowerFlowTimeoutError) else "failed"
                with self.lock:
                    last_successful_simu_time = str(
                        self.latest_measurement_clock.get("time", "") or ""
                    )
                    if start_clock_state == "running":
                        self.clock.state = "paused"
                    self.latest_compute = {
                        "mode": "process" if self.kernel_runner is not None else "embedded",
                        "http_pid": os.getpid(),
                        "worker_pid": (
                            int(self.latest_compute.get("worker_pid", 0) or 0)
                            if self.kernel_runner is not None
                            else os.getpid()
                        ),
                        "compute_ms": round(elapsed * 1000.0, 3),
                        "round_trip_ms": round(elapsed * 1000.0, 3),
                        "status": compute_status,
                        "resident_model": self.kernel_runner is None,
                        "error": f"{type(exc).__name__}: {exc}",
                        "simu_time": minute_to_time(minute),
                        "absolute_minute": float(absolute_minute),
                        "failed_at": _now_text(),
                        "result_discarded": True,
                        "measurement_frame_stale": True,
                        "last_successful_simu_time": last_successful_simu_time,
                    }
                    self.latest_result = {
                        "solver_info": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    self._append_power_flow_failure_log(
                        exc,
                        minute,
                        absolute_minute,
                        clock_advance,
                        period_seconds,
                        auto_paused=start_clock_state == "running",
                    )
                    self.clock.updated_at = time.time()
                raise

            with self.lock:
                stale = (
                    not self.service_instance_active()
                    or self.definition_snapshot.revision != definition_revision
                    or self._curve_revision != curve_revision
                    or self.clock.run_id != start_run_id
                    or self.clock.step_count != start_step_count
                    or abs(float(self.clock.absolute_minute) - float(absolute_minute)) > 1e-9
                    or (start_clock_state != "stopped" and self.clock.state == "stopped")
                )
                if stale:
                    self._record_compute_execution(execution, status="discarded")
                    self.clock.updated_at = time.time()
                    if return_snapshot:
                        return self.snapshot()
                    return None

                if execution.runtime_stat_book is not None:
                    self._merge_execution_runtime_stat_book(execution.runtime_stat_book)
                if backtrack_info is not None:
                    self._apply_backtrack_controls_to_pending_execution(
                        pending_remote_adjustment_execution,
                        before_remote_adjustment_execution,
                        backtrack_info,
                        self._remote_adjustment_cycle_seq,
                    )
                self._commit_remote_adjustment_execution(
                    before_remote_adjustment_execution,
                    pending_remote_adjustment_execution,
                )
                kernel_result = execution.result
                self._record_compute_execution(execution)
                if backtrack_info is not None:
                    self.latest_compute.update(
                        {
                            "boundary_backtracked": True,
                            "boundary_backtrack_factor": float(backtrack_info["factor"]),
                            "boundary_backtrack_attempts": int(backtrack_info["attempts"]),
                            "boundary_backtrack_control_count": len(backtrack_info["controls"]),
                        }
                    )
                    self._record_power_flow_backtrack(backtrack_info, minute)
                self.latest_model_book = getattr(kernel_result, "model_book", None)
                self.latest_device_states = [
                    dict(item)
                    for item in (getattr(kernel_result, "device_states", None) or [])
                    if (type(item) is dict or isinstance(item, Mapping))
                ]
                self._store_kernel_measurement_rows(kernel_result)
                self._apply_measurement_faults(minute, absolute_minute)
                self._apply_measurement_statuses(minute, absolute_minute)
                self._automatic_runtime_state_invalidated = False
                self.latest_measurements = self.measurements()
                self._record_last_scada_values_locked(self.latest_measurements)
                measurement_updated_at = time.time()
                measurement_clock = self.clock.as_dict()
                measurement_clock["step_count"] = self.clock.step_count + 1
                measurement_clock["updated_at"] = measurement_updated_at
                self.latest_measurement_clock = measurement_clock
                result_dict = self._kernel_result_dict(kernel_result)
                if backtrack_info is not None:
                    result_dict["boundary_backtrack"] = {
                        "factor": float(backtrack_info["factor"]),
                        "attempts": int(backtrack_info["attempts"]),
                        "control_count": len(backtrack_info["controls"]),
                    }
                self.latest_result = result_dict
                command_response_lines = self._collect_command_response_lines(result_dict)
                self._append_power_flow_log(
                    result_dict,
                    self.latest_measurements,
                    minute,
                    absolute_minute,
                    clock_advance,
                    period_seconds,
                    command_response_lines,
                )
                next_absolute_minute = self.clock.absolute_minute + clock_advance
                crossed_cycle_start = self._crossed_simulation_cycle_start(
                    self.clock.absolute_minute,
                    next_absolute_minute,
                )
                self.clock.absolute_minute = round(next_absolute_minute, 9)
                self.clock.minute = self.clock.absolute_minute % 1440.0
                self.clock.step_count += 1
                self.clock.updated_at = measurement_updated_at
                if crossed_cycle_start:
                    # 跨周期归零时开启新 run_id 并重置储能/氢罐与自动指令，
                    # 但保留本拍刚计算完成的有效量测作为物理一致的过渡帧，不原地覆写过渡帧中的 SOC/氢储量。
                    self.clock.run_id += 1
                    self._reset_storage_soc_to_initial(sync_latest_measurements=False)
                    self._reset_hydrogen_storage_state_to_initial(sync_latest_measurements=False)
                    self._remote_adjustment_execution.clear()
                    self._fault_restore.clear()
                    if self.clear_commands_on_start_and_reset:
                        cleared = self._remove_automatic_command_history_for_restart()
                    else:
                        cleared = self._clear_automatic_commands_for_simulation_restart(
                            reason="simulation_cycle_reset",
                        )
                        if cleared["entries"]:
                            self._write_command_history()
                    self._materialize_active_control_commands(
                        self.clock.absolute_minute,
                        persist=True,
                    )
                    self._apply_device_faults(
                        self.clock.minute,
                        self.clock.absolute_minute,
                        restore_expired=False,
                    )
                    if cleared["entries"]:
                        self._append_runtime_log(
                            "控制指令",
                            "仿真时钟",
                            "周期归零自动指令已清空",
                            [
                                f"新仿真周期开始前清空自动指令记录 {cleared['entries']} 条",
                                (
                                    f"涉及遥控 {cleared['remote_controls']} 个控制点，"
                                    f"遥调 {cleared['remote_adjustments']} 个控制点"
                                ),
                                "人工指令继续保持，自动指令对潮流边界的影响已撤销",
                            ],
                            level="ok",
                            simu_time=minute_to_time(self.clock.minute),
                        )
                    definition_signature = (
                        self._measurement_definition_signature_for_current_revision()
                    )
                    self._measurement_history.clear()
                    self._measurement_delta_seq += 1
                    self._measurement_delta_state = self._measurement_delta_current_items(
                        self.latest_measurements,
                        measurement_clock=measurement_clock,
                    )
                    self._measurement_delta_history = []
                    self._measurement_delta_definition_signature = definition_signature
                    self._measurement_delta_definition_count = len(
                        self.latest_measurements.get("definitions", []) or []
                    )
                    self._measurement_delta_definition_revision = self.definition_snapshot.revision
                    self._measurement_delta_step_count = self.clock.step_count
                    self._measurement_delta_runtime_marker = self._measurement_delta_runtime_state_marker()
                else:
                    definition_signature = (
                        self._measurement_definition_signature_for_current_revision()
                    )
                    self._refresh_measurement_delta_state(
                        measurements=self.latest_measurements,
                        measurement_clock=measurement_clock,
                        definition_signature=definition_signature,
                    )
                    self._measurement_delta_step_count = self.clock.step_count
                    self._measurement_history.append(
                        measurement_clock,
                        self.latest_measurements,
                        definition_revision=self.definition_snapshot.revision,
                        definition_signature=definition_signature,
                        limit=3600,
                    )
                if return_snapshot:
                    return self.snapshot()
                return None

    def _write_current_weather(self, minute: int | float, absolute_minute: int | float | None = None) -> None:
        curve_mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
        period_minutes = _simulation_mode_duration_minutes(curve_mode)
        target_minute = absolute_minute if absolute_minute is not None else minute
        row = {"time": minute_to_time(minute)}
        for key, default in self.weather_defaults.items():
            row[key] = _number_text(
                self._interpolate_curve_series(
                    self.curves.get("weather", []),
                    target_minute,
                    key,
                    default,
                    period_minutes=period_minutes,
                )
            )
        load_targets = self._current_load_power_targets(float(target_minute), period_minutes)
        load_total = sum(float(target["p_kw"]) for target in load_targets)
        load_seen = bool(load_targets)
        load_details = [(str(target["dev_name"]), float(target["p_kw"])) for target in load_targets]
        row["load_kw"] = _number_text(load_total if load_seen else self.weather_defaults.get("load_kw", 0.0))
        self._write_weather_row(row, load_targets=load_targets)
        self._append_environment_load_log(
            minute,
            float(target_minute),
            period_minutes,
            row,
            load_details,
            load_seen=load_seen,
        )

    def _write_weather_row(
        self,
        row: Mapping[str, Any],
        *,
        load_targets: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        clean = {
            header: UNKNOWN_WEATHER_VALUE if row.get(header, "") is None else row.get(header, "")
            for header in WEATHER_HEADER
        }
        blocks: Dict[str, Tuple[Sequence[str], Sequence[Mapping[str, Any]]]] = {
            "Weather": (WEATHER_HEADER, [clean])
        }
        if load_targets:
            blocks["LoadPower"] = (RUNTIME_LOAD_POWER_HEADER, load_targets)
        self.weather_book = _make_book(blocks)

    def _apply_device_faults(
        self,
        minute: int | float,
        absolute_minute: int | float,
        *,
        restore_expired: bool = True,
    ) -> None:
        book = self.runtime_stat_book
        run_block = _ensure_block(book, "RunStat", STAT_HEADERS["RunStat"])
        cb_block = _ensure_block(book, "CbOpenStat", STAT_HEADERS["CbOpenStat"])
        active_keys: set[Tuple[str, str, str]] = set()

        curve_mode = str(self.curves.get("mode", "day") or "day").lower()
        for fault in self.local_settings.get("device_faults", []):
            if not (type(fault) is dict or isinstance(fault, Mapping)) or not _active_window(fault, minute, absolute_minute, curve_mode):
                continue
            dev_type = str(fault.get("dev_type", fault.get("type", "")))
            dev_name = str(fault.get("dev_name", fault.get("name", "")))
            if not dev_type or not dev_name:
                continue
            run_key = ("RunStat", dev_type, dev_name)
            active_keys.add(run_key)
            run_row = _find_dev_row(run_block, dev_type, dev_name)
            if run_row is None:
                run_row = {"dev_type": dev_type, "dev_name": dev_name, "run_stat": "1"}
                run_block.data.append(run_row)
            if run_key not in self._fault_restore:
                self._fault_restore[run_key] = str(run_row.get("run_stat", "1"))
            run_row["run_stat"] = _number_text(fault.get("run_stat", 0))

            if "status" in fault or dev_type.endswith("Break") or dev_type.endswith("Switch"):
                cb_key = ("CbOpenStat", dev_type, dev_name)
                active_keys.add(cb_key)
                cb_row = _find_dev_row(cb_block, dev_type, dev_name)
                if cb_row is None:
                    cb_row = {
                        "dev_type": dev_type,
                        "dev_name": dev_name,
                        "closed_status_set": "1",
                        "closed_status": "1",
                        "status": "1",
                    }
                    cb_block.data.append(cb_row)
                if cb_key not in self._fault_restore:
                    self._fault_restore[cb_key] = str(
                        simu_loop.closed_status_set_value(cb_row, 1)
                    )
                cb_row["closed_status_set"] = _number_text(fault.get("status", 0))

        for key, old_value in list(self._fault_restore.items()):
            if key in active_keys:
                continue
            if restore_expired:
                block_name, dev_type, dev_name = key
                block = run_block if block_name == "RunStat" else cb_block
                value_column = "run_stat" if block_name == "RunStat" else "closed_status_set"
                row = _find_dev_row(block, dev_type, dev_name)
                if row is not None:
                    row[value_column] = old_value
            del self._fault_restore[key]

        self.runtime_stat_book = book

    def _kernel_result_dict(self, result: Optional[simu_loop.SimulationResult]) -> Dict[str, Any]:
        if result is None:
            return {"updated": 0, "missing": 0, "overlay_updates": 0, "solver_info": "not-run"}
        return {
            "updated": getattr(result, "updated", 0),
            "missing": getattr(result, "missing", 0),
            "missing_measurements": [
                dict(item)
                for item in (getattr(result, "missing_measurements", None) or [])
                if (type(item) is dict or isinstance(item, Mapping))
            ],
            "operating_warnings": [
                dict(item)
                for item in (getattr(result, "operating_warnings", None) or [])
                if (type(item) is dict or isinstance(item, Mapping))
            ],
            "overlay_updates": getattr(result, "overlay_updates", 0),
            "solver_info": getattr(result, "solver_info", ""),
            "real_file": str(getattr(result, "real_file", self.files["real"])),
            "scada_file": str(getattr(result, "scada_file", self.files["scada"])),
        }

    def _current_weather_values(self) -> Dict[str, Any]:
        values: Dict[str, Any] = {**self.weather_defaults, "time": minute_to_time(self.clock.minute)}
        book = self.weather_book
        block = book.data.get("Weather")
        if block is None or not block.data:
            return values
        row: Mapping[str, Any] = block.data[0]
        if "name" in block.header_list and "value" in block.header_list:
            row = {str(item.get("name", "")): item.get("value", "") for item in block.data}
        if row.get("time") not in (None, ""):
            values["time"] = row.get("time")
        for key in DEFAULT_WEATHER:
            number = _to_float(row.get(key), None)
            if number is not None:
                values[key] = number
        return values

    def reset_manual_definition_changes(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self._active_definition_update_guard():
            current = self.definition_snapshot
            require_definition_revision(payload, current.revision)
            raw_change_ids = payload.get("change_ids", [])
            if not isinstance(raw_change_ids, Sequence) or isinstance(raw_change_ids, (str, bytes)):
                raise ValueError("change_ids must be an array")
            change_ids = list(
                dict.fromkeys(
                    str(change_id).strip()
                    for change_id in raw_change_ids
                    if str(change_id).strip()
                )
            )
            if not change_ids:
                raise ValueError("At least one manual change must be selected")
            missing = [change_id for change_id in change_ids if change_id not in self._manual_definition_changes]
            if missing:
                raise ValueError(f"Unknown manual definition change: {missing[0]}")
            # Measurement validity, status and fixed value form one effective
            # state.  Restoring one of them must not leave an impossible partial
            # override (for example fixed status without a fixed value).
            selected_ids = set(change_ids)
            selected_measurements = {
                str(item.get("measurement_name", ""))
                for change_id, item in self._manual_definition_changes.items()
                if change_id in selected_ids
                and item.get("kind") == "measurement"
                and item.get("field") in {"valid", "status", "fixed_value"}
            }
            for change_id, item in self._manual_definition_changes.items():
                if (
                    item.get("kind") == "measurement"
                    and str(item.get("measurement_name", "")) in selected_measurements
                    and item.get("field") in {"valid", "status", "fixed_value"}
                ):
                    selected_ids.add(change_id)
            change_ids = [
                change_id
                for change_id in self._manual_definition_changes
                if change_id in selected_ids
            ]
            selected = [
                dict(self._manual_definition_changes[change_id])
                for change_id in change_ids
            ]

            now = _now_text()
            for item in selected:
                active_item = self._manual_definition_changes[str(item.get("id", ""))]
                active_item["current_value"] = self._manual_change_value_text(
                    active_item.get("default_value", "")
                )
                active_item["modified_at"] = now
                self._set_manual_change_sync_state_unlocked(
                    active_item,
                    persisted=False,
                    error="等待人工覆盖层保存",
                )
                if active_item.get("field") == "weight":
                    active_item["current_error_sigma"] = self._manual_change_sigma(
                        active_item["current_value"]
                    )

            self._rebuild_effective_definitions_from_source_unlocked()
            try:
                self._write_ahead_manual_definition_changes_unlocked()
            except OSError as exc:
                error = f"后台定义已恢复，但人工覆盖层保存失败，请重试: {exc}"
                for item in selected:
                    active_item = self._manual_definition_changes.get(str(item.get("id", "")))
                    if active_item is not None:
                        self._set_manual_change_sync_state_unlocked(
                            active_item,
                            persisted=False,
                            error=error,
                        )
                result = self._manual_definition_changes_payload_unlocked()
                result.update(
                    {
                        "reset_count": len(selected),
                        "persisted_count": 0,
                        "memory_updated": True,
                        "persisted": False,
                        "change_record_persisted": False,
                        "reset_ids": change_ids,
                        "static_meta": self.static_meta(),
                        "warning": error,
                    }
                )
                return result

            pending_changes = {
                change_id: dict(item)
                for change_id, item in self._manual_definition_changes.items()
            }
            for change_id in change_ids:
                active_item = self._manual_definition_changes.get(change_id)
                if active_item is None:
                    continue
                self._set_manual_change_sync_state_unlocked(active_item, persisted=True)
                self._manual_definition_changes.pop(change_id, None)

            warning = ""
            persisted = True
            try:
                self._write_manual_definition_changes_unlocked()
            except OSError as exc:
                self._manual_definition_changes = pending_changes
                persisted = False
                warning = (
                    "默认值已写入人工覆盖层，但清理同步状态失败，请重试: "
                    f"{exc}"
                )

            result = self._manual_definition_changes_payload_unlocked()
            result.update(
                {
                    "reset_count": len(selected),
                    "persisted_count": len(selected) if persisted else 0,
                    "memory_updated": True,
                    "persisted": persisted,
                    "change_record_persisted": True,
                    "reset_ids": change_ids,
                    "static_meta": self.static_meta(),
                }
            )
            if warning:
                result["warning"] = warning
            return result
