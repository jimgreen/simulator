"""PolarMicrogridSimulator 拆分模块：外部控制、遥调/遥控指令、策略代次与回溯执行能力。"""

from __future__ import annotations

from ..device_roles import device_role_from_type
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


class _ControlsMixin:
    """外部控制、遥调/遥控指令、策略代次与回溯执行能力。"""

    def _reconcile_source_dcp_controls_unlocked(
        self,
        model_book: EBook,
        source_stat_book: EBook,
        control_book: EBook,
    ) -> Tuple[EBook, EBook]:
        stat_path = Path(self.source_files["stat"])
        control_path = Path(
            self.source_files["control"]
            if self.source_files["control"].exists()
            else self.source_files["stat"]
        )
        same_file = stat_path.resolve() == control_path.resolve()
        stat_added = ensure_dcac_dcp_control_rows(model_book, source_stat_book)
        if same_file:
            if stat_added:
                simu_loop.write_ebook_aligned(source_stat_book, stat_path)
            return source_stat_book, simu_loop._clone_ebook(source_stat_book)

        control_added = ensure_dcac_dcp_control_rows(model_book, control_book)
        if stat_added:
            simu_loop.write_ebook_aligned(source_stat_book, stat_path)
        if control_added:
            simu_loop.write_ebook_aligned(control_book, control_path)
        return source_stat_book, control_book

    @staticmethod
    def _command_item_sequence(container: Mapping[str, Any], keys: Sequence[str]) -> List[Any]:
        for key in keys:
            value = container.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return list(value)
        return []

    def _filter_loaded_command_history_to_definitions(
        self,
        history: Sequence[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], bool]:
        filtered_history: List[Dict[str, Any]] = []
        changed = False
        run_keys = ("run_status", "runStatus")
        set_keys = ("set_values", "setValues", "setpoints")

        for item in history:
            normalized = item.get("normalized", {})
            normalized_map = normalized if (type(normalized) is dict or isinstance(normalized, Mapping)) else {}
            payload = item.get("payload", {})
            payload_map = payload if (type(payload) is dict or isinstance(payload, Mapping)) else {}
            accepted = item.get("accepted", {})
            accepted_map = accepted if (type(accepted) is dict or isinstance(accepted, Mapping)) else {}
            accepted_count = (
                int(_to_float(accepted_map.get("run_status"), 0) or 0)
                + int(_to_float(accepted_map.get("set_values"), 0) or 0)
            )

            normalized_has_control_keys = any(key in normalized_map for key in (*run_keys, *set_keys))
            normalized_run = self._command_item_sequence(normalized_map, run_keys)
            normalized_set = self._command_item_sequence(normalized_map, set_keys)
            payload_run = self._command_item_sequence(payload_map, run_keys)
            payload_set = self._command_item_sequence(payload_map, set_keys)
            has_requested_controls = bool(normalized_run or normalized_set or payload_run or payload_set)

            if not has_requested_controls:
                filtered_history.append(item)
                continue
            if accepted_count <= 0:
                changed = True
                continue

            source_run = normalized_run if normalized_has_control_keys else payload_run
            source_set = normalized_set if normalized_has_control_keys else payload_set
            requested_run = self._normalize_run_command_items(source_run)
            requested_set = self._normalize_set_command_items(source_set)
            retained_run = self._filter_defined_run_command_items(requested_run)
            retained_set = self._filter_defined_set_command_items(requested_set)
            try:
                retained_run = self._validate_run_command_items(retained_run)
                retained_set = self._validate_set_command_items(
                    retained_set,
                    strict=True,
                )
            except ValueError:
                # Persisted entries retain their original batch semantics.  A
                # corrupt or now-unsafe member invalidates the whole entry.
                changed = True
                continue
            if not retained_run and not retained_set:
                changed = True
                continue

            cleaned = dict(item)
            cleaned_normalized = dict(normalized_map)
            cleaned_normalized["run_status"] = retained_run
            cleaned_normalized["set_values"] = retained_set
            cleaned["normalized"] = cleaned_normalized

            if payload_map:
                cleaned_payload = dict(payload_map)
                for key in run_keys:
                    if key in cleaned_payload:
                        cleaned_payload[key] = [dict(row) for row in retained_run]
                for key in set_keys:
                    if key in cleaned_payload:
                        cleaned_payload[key] = [dict(row) for row in retained_set]
                cleaned["payload"] = cleaned_payload

            cleaned_accepted = dict(accepted_map)
            removed_count = max(0, len(requested_run) - len(retained_run)) + max(
                0,
                len(requested_set) - len(retained_set),
            )
            cleaned_accepted["run_status"] = len(retained_run)
            cleaned_accepted["set_values"] = len(retained_set)
            cleaned_accepted["ignored"] = int(_to_float(accepted_map.get("ignored"), 0) or 0) + removed_count
            cleaned["accepted"] = cleaned_accepted

            if cleaned != item:
                changed = True
            filtered_history.append(cleaned)

        return filtered_history, changed

    def _read_command_history(self) -> List[Dict[str, Any]]:
        items = _read_json(self.commands_file, [])
        if not isinstance(items, list):
            return []
        history = [item for item in items if isinstance(item, dict)]
        changed = self._repair_legacy_cancel_command_entries(history)
        history, definition_changed = self._filter_loaded_command_history_to_definitions(history)
        changed = changed or definition_changed
        changed = self._compact_command_history_payloads(history) or changed
        compacted = self._compact_command_history(history)
        if len(compacted) != len(history):
            changed = True
            history = compacted
        if changed:
            _write_json(self.commands_file, history, compact=True)
        self._command_history_persisted_signature = self._command_history_signature(history)
        return history

    @staticmethod
    def _command_history_signature(history: Sequence[Mapping[str, Any]]) -> str:
        encoded = json.dumps(history, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _compact_command_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Keep transport metadata without duplicating normalized controls or a full plan."""
        compacted: Dict[str, Any] = {}
        sequence_fields = {
            "run_status": "run_status_count",
            "runStatus": "run_status_count",
            "set_values": "set_values_count",
            "setValues": "set_values_count",
            "setpoints": "set_values_count",
            "command_rows": "command_rows_count",
            "commandRows": "command_rows_count",
        }
        strategy_fields = (
            "name",
            "strategy_id",
            "generation",
            "replace_strategy_generation",
            "loop_mode",
            "trigger",
            "time",
            "load_kw",
            "renewable_available_kw",
            "renewable_used_kw",
            "storage_kw",
            "storage_current_kw",
            "storage_soc",
            "acdc_current_kw",
            "acdc_target_kw",
            "diesel_residual_kw",
            "diesel_min_kw",
            "diesel_target_kw",
            "curtail_kw",
            "data_quality",
        )
        for key, value in payload.items():
            count_key = sequence_fields.get(str(key))
            if count_key is not None:
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    compacted[count_key] = max(int(compacted.get(count_key, 0)), len(value))
                continue
            if key == "strategy" and (type(value) is dict or isinstance(value, Mapping)):
                summary = {
                    field: copy.deepcopy(value[field])
                    for field in strategy_fields
                    if field in value
                }
                if summary:
                    compacted[key] = summary
                continue
            compacted[key] = copy.deepcopy(value)
        return compacted

    def _compact_command_history_payloads(
        self,
        history: Sequence[Dict[str, Any]],
    ) -> bool:
        changed = False
        for entry in history:
            payload = entry.get("payload")
            if not (type(payload) is dict or isinstance(payload, Mapping)):
                continue
            compacted = self._compact_command_payload(payload)
            if compacted != payload:
                entry["payload"] = compacted
                changed = True
        return changed

    def _preserve_command_history_entry(self, item: Mapping[str, Any]) -> bool:
        return (
            _manual_command_holds_across_clock_lifecycle(item)
            and self._command_entry_has_accepted_controls(item)
            and not item.get("cancelled")
        )

    def _compact_command_history(self, history: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        recent_start = max(0, len(history) - COMMAND_HISTORY_RECENT_LIMIT)
        recent_ids = {id(item) for item in history[recent_start:]}
        current_run_id = int(_to_float(self.clock.run_id, 0) or 0)
        latest_automatic_owner: Dict[Tuple[str, str, str, str], int] = {}
        for item in history:
            if (
                _command_origin(item) != "automatic"
                or not self._command_entry_has_recorded_controls(item)
                or int(_to_float(item.get("run_id"), -1)) != current_run_id
                or self._automatic_command_was_reset(item)
            ):
                continue
            for key in self._command_entry_control_keys(item):
                latest_automatic_owner[key] = id(item)
        latched_automatic_ids = set(latest_automatic_owner.values())
        return [
            item
            for item in history
            if id(item) in recent_ids
            or id(item) in latched_automatic_ids
            or self._preserve_command_history_entry(item)
        ]

    def _trim_command_history(self) -> None:
        self._ensure_strategy_generation_index()
        acknowledged_ids = {id(item) for item in self.command_history[: self._last_command_response_index]}
        compacted = self._compact_command_history(self.command_history)
        if len(compacted) == len(self.command_history):
            self._strategy_generation_index_token = self._command_history_identity_token()
            return
        self.command_history = compacted
        self._last_command_response_index = sum(1 for item in self.command_history if id(item) in acknowledged_ids)
        retained_ids = {id(item) for item in compacted}
        self._strategy_generation_entries = {
            strategy_id: [
                entry for entry in entries if id(entry) in retained_ids
            ]
            for strategy_id, entries in self._strategy_generation_entries.items()
            if any(id(entry) in retained_ids for entry in entries)
        }
        self._strategy_generation_index_token = self._command_history_identity_token()

    def _write_command_history(self, *, prepared: bool = False) -> None:
        if not prepared:
            self._prepare_command_history_for_persistence()
        signature = self._command_history_signature(self.command_history)
        if signature == self._command_history_persisted_signature and self.commands_file.exists():
            return
        _write_json(self.commands_file, self.command_history, compact=True)
        self._command_history_persisted_signature = signature

    def _prepare_command_history_for_persistence(self) -> None:
        self._trim_command_history()
        self._compact_command_history_payloads(self.command_history)

    def _bump_command_mutation_seq(self) -> int:
        next_seq = int(getattr(self, "_command_mutation_seq", 0) or 0) + 1
        self._command_mutation_seq = next_seq
        self._command_signature_cache = None
        self._device_runtime_supplement_cache = None
        return next_seq

    def _clear_command_history(self) -> Dict[str, int]:
        control_keys: set[Tuple[str, str, str, str]] = set()
        for entry in self.command_history:
            if (type(entry) is dict or isinstance(entry, Mapping)):
                control_keys.update(self._command_entry_control_keys(entry))
        cleared = {
            "entries": len(self.command_history),
            "remote_controls": sum(1 for key in control_keys if key[0] == "remote_control"),
            "remote_adjustments": sum(1 for key in control_keys if key[0] == "remote_adjustment"),
        }
        self.command_history = []
        self._last_command_response_index = 0
        self._strategy_generation_entries = {}
        self._strategy_generation_index_token = self._command_history_identity_token()
        self._bump_command_mutation_seq()
        _write_json(self.commands_file, [], compact=True)
        self._command_history_persisted_signature = self._command_history_signature([])
        return cleared

    def _remove_automatic_command_history_for_restart(self) -> Dict[str, int]:
        self._ensure_strategy_generation_index()
        acknowledged_ids = {id(item) for item in self.command_history[: self._last_command_response_index]}
        retained: List[Dict[str, Any]] = []
        removed_keys: set[Tuple[str, str, str, str]] = set()
        removed_entries = 0
        for entry in self.command_history:
            if _command_origin(entry) == "manual":
                retained.append(entry)
                continue
            removed_entries += 1
            removed_keys.update(self._command_entry_control_keys(entry))

        if removed_entries:
            self.command_history = retained
            self._last_command_response_index = sum(
                1 for item in self.command_history if id(item) in acknowledged_ids
            )
            self._strategy_generation_entries = {}
            self._strategy_generation_index_token = self._command_history_identity_token()
            self._bump_command_mutation_seq()
        self._force_control_targets_after_automatic_removal(removed_keys)
        self._write_command_history()

        return {
            "entries": removed_entries,
            "remote_controls": sum(1 for key in removed_keys if key[0] == "remote_control"),
            "remote_adjustments": sum(1 for key in removed_keys if key[0] == "remote_adjustment"),
        }

    def _force_control_targets_after_automatic_removal(
        self,
        control_keys: Iterable[Tuple[str, str, str, str]],
    ) -> None:
        for kind, dev_type, dev_name, field_name in control_keys:
            if kind != "remote_adjustment":
                continue
            key = (dev_type, dev_name, field_name)
            self._remote_adjustment_execution[key] = {
                "force_target_once": True,
                "last_cycle_token": None,
            }

    def _base_stat_book_for_controls(self) -> EBook:
        book = simu_loop._clone_ebook(self.source_stat_book)
        for name, headers in STAT_HEADERS.items():
            _ensure_block(book, name, headers)
        simu_loop.ensure_closed_status_rows_book(book)

        runtime_book = self.runtime_stat_book
        runtime_cb = runtime_book.data.get("CbOpenStat")
        base_cb = book.data.get("CbOpenStat")
        if runtime_cb is not None and base_cb is not None:
            for runtime_row in runtime_cb.data:
                current = _find_dev_row(
                    base_cb,
                    str(runtime_row.get("dev_type", "")),
                    _dev_name(runtime_row),
                )
                if current is None:
                    continue
                actual = simu_loop.closed_status_value(runtime_row, "")
                if actual != "":
                    current["closed_status"] = _number_text(actual)
                    current["status"] = _number_text(actual)
        runtime_storage = runtime_book.data.get("StorageSoc") or runtime_book.data.get("StorageStatus")
        if runtime_storage is not None:
            storage_block = _ensure_block(book, "StorageSoc", STAT_HEADERS["StorageSoc"])
            storage_block.data = self._merge_runtime_storage_soc(storage_block.data, runtime_storage.data)
        runtime_hydrogen = runtime_book.data.get(simu_loop.HYDROGEN_STORAGE_STATE_BLOCK)
        if runtime_hydrogen is not None:
            hydrogen_block = _ensure_block(
                book,
                simu_loop.HYDROGEN_STORAGE_STATE_BLOCK,
                simu_loop.HYDROGEN_STORAGE_STATE_HEADERS,
            )
            hydrogen_block.data = self._merge_runtime_hydrogen_storage_state(
                hydrogen_block.data,
                runtime_hydrogen.data,
            )
        simu_loop.ensure_hydrogen_storage_state_rows_book(
            book,
            self.definition_snapshot.model_book,
        )
        return book

    def _normalize_run_command_items(self, items: Sequence[Any]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for item in items:
            if not (type(item) is dict or isinstance(item, Mapping)):
                continue
            dev_type = str(item.get("dev_type", item.get("type", "")))
            dev_name = str(item.get("dev_name", item.get("name", "")))
            if not dev_type or not dev_name:
                continue
            run_stat = item.get("run_stat", item.get("running", item.get("value", "")))
            if isinstance(run_stat, bool):
                run_stat = 1 if run_stat else 0
            row = {"dev_type": dev_type, "dev_name": dev_name, "run_stat": _number_text(run_stat)}
            if "closed_status_set" in item or "status" in item:
                row["status"] = _number_text(
                    item.get("closed_status_set", item.get("status"))
                )
            normalized.append(row)
        return normalized

    def _normalize_set_command_items(self, items: Sequence[Any]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for item in self._expand_set_values(items):
            dev_type = str(item.get("dev_type", item.get("type", "")))
            dev_name = str(item.get("dev_name", item.get("name", "")))
            set_type = str(item.get("set_type", ""))
            if not dev_type or not dev_name or not set_type:
                continue
            normalized.append(
                {
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "set_type": set_type,
                    "set_value": _number_text(item.get("set_value", "")),
                }
            )
        return normalized

    def _write_active_yt_ctrl_file(self, set_rows: Sequence[Mapping[str, Any]], *, persist: bool = False) -> None:
        unique_rows: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for row in set_rows:
            dev_type = str(row.get("dev_type", ""))
            dev_name = str(row.get("dev_name", row.get("name", "")))
            set_type = str(row.get("set_type", ""))
            if not dev_type or not dev_name or not set_type:
                continue
            unique_rows[(dev_type, dev_name, set_type)] = {
                "dev_type": dev_type,
                "dev_name": dev_name,
                "set_type": set_type,
                "set_value": row.get("set_value", ""),
            }
        self.yt_ctrl_book = _make_book({"SetValue": (STAT_HEADERS["SetValue"], list(unique_rows.values()))})
        if persist:
            simu_loop.write_ebook_aligned(self.yt_ctrl_book, self.files["yt_ctrl"])

    def _command_entry_is_active(
        self,
        item: Mapping[str, Any],
        absolute_minute: int | float,
        run_id: Optional[int] = None,
    ) -> bool:
        current = float(absolute_minute)
        manual_hold = _manual_command_holds_across_clock_lifecycle(item)
        if not manual_hold and _command_origin(item) == "automatic":
            if (
                not self._command_entry_has_recorded_controls(item)
                or self._automatic_command_was_reset(item)
            ):
                return False
            entry_run_id = _to_float(item.get("run_id"), None)
            expected_run_id = int(
                run_id
                if run_id is not None
                else (_to_float(self.clock.run_id, 0) or 0)
            )
            if entry_run_id is None or int(entry_run_id) != expected_run_id:
                return False
            issued = _to_float(item.get("issued_absolute_minute"), None)
            if issued is None or issued > current + 1e-9:
                return False
            cycle_minutes = float(self._simulation_cycle_minutes())
            issued_cycle = math.floor((issued + 1e-9) / cycle_minutes)
            current_cycle = math.floor((current + 1e-9) / cycle_minutes)
            return issued_cycle == current_cycle
        if not self._command_entry_has_accepted_controls(item):
            return False
        if manual_hold:
            return True
        if not manual_hold:
            entry_run_id = _to_float(item.get("run_id"), None)
            expected_run_id = int(run_id if run_id is not None else (_to_float(self.clock.run_id, 0) or 0))
            if entry_run_id is None or int(entry_run_id) != expected_run_id:
                return False
        issued = _to_float(item.get("issued_absolute_minute"), None)
        expires = _to_float(item.get("expires_at_absolute_minute"), None)
        if issued is None or expires is None:
            return False
        return current < expires and (manual_hold or issued <= current)

    @staticmethod
    def _automatic_command_was_reset(item: Mapping[str, Any]) -> bool:
        reason = str(item.get("cancelled_reason", "")).strip().casefold()
        return reason.startswith("simulation_") or reason == "runtime_reset"

    def _command_entry_has_recorded_controls(self, item: Mapping[str, Any]) -> bool:
        if not (type(item) is dict or isinstance(item, Mapping)) or not item.get("eligible_source"):
            return False
        accepted = item.get("accepted", {})
        if not (type(accepted) is dict or isinstance(accepted, Mapping)):
            return False
        accepted_count = int(_to_float(accepted.get("run_status"), 0) or 0) + int(
            _to_float(accepted.get("set_values"), 0) or 0
        )
        return accepted_count > 0

    def _command_entry_has_accepted_controls(self, item: Mapping[str, Any]) -> bool:
        return self._command_entry_has_recorded_controls(item) and not item.get(
            "cancelled"
        )

    def _command_entry_can_be_cancelled(
        self,
        item: Mapping[str, Any],
        absolute_minute: int | float,
        run_id: Optional[int] = None,
    ) -> bool:
        if not self._command_entry_has_accepted_controls(item):
            return False
        if _manual_command_holds_across_clock_lifecycle(item):
            return True
        return self._command_entry_is_active(item, absolute_minute, run_id)

    def _active_control_command_entries(self, absolute_minute: int | float) -> List[Mapping[str, Any]]:
        current_run_id = int(_to_float(self.clock.run_id, 0) or 0)
        active: List[Tuple[int, Mapping[str, Any]]] = []
        for index, item in enumerate(self.command_history):
            if self._command_entry_is_active(item, absolute_minute, current_run_id):
                active.append((index, item))
        # Materialization is last-write-wins. Automatic targets are the lower
        # priority fallback; a manual command always owns the same control point
        # until the operator explicitly exits it.
        active.sort(key=lambda pair: (0 if _command_origin(pair[1]) == "automatic" else 1, pair[0]))
        return [item for _index, item in active]

    def _effective_active_control_command_entries(self, absolute_minute: int | float) -> List[Mapping[str, Any]]:
        active_entries = self._active_control_command_entries(absolute_minute)
        effective_by_control: Dict[Tuple[str, str, str, str], Mapping[str, Any]] = {}
        simulator_ui_overrides = self._simulator_ui_control_override_keys()
        for entry in active_entries:
            normalized = entry.get("normalized", {})
            if not (type(normalized) is dict or isinstance(normalized, Mapping)):
                continue
            run_items = normalized.get("run_status", [])
            if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)):
                for item in run_items:
                    if not (type(item) is dict or isinstance(item, Mapping)):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    if not dev_type or not dev_name:
                        continue
                    if (
                        item.get("run_stat", "") != ""
                        and ("remote_control", dev_type, dev_name, "run_stat")
                        not in simulator_ui_overrides
                    ):
                        effective_by_control[("remote_control", dev_type, dev_name, "run_stat")] = entry
                    if (
                        item.get("status", "") != ""
                        and ("remote_control", dev_type, dev_name, "status")
                        not in simulator_ui_overrides
                    ):
                        effective_by_control[("remote_control", dev_type, dev_name, "status")] = entry
            set_items = normalized.get("set_values", [])
            if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)):
                for item in set_items:
                    if not (type(item) is dict or isinstance(item, Mapping)):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    set_type = str(item.get("set_type", "")).strip()
                    if (
                        dev_type
                        and dev_name
                        and set_type
                        and ("remote_adjustment", dev_type, dev_name, set_type)
                        not in simulator_ui_overrides
                    ):
                        effective_by_control[("remote_adjustment", dev_type, dev_name, set_type)] = entry
        effective_ids = {id(entry) for entry in effective_by_control.values()}
        return [entry for entry in active_entries if id(entry) in effective_ids]

    def _effective_active_control_command_views(
        self,
        absolute_minute: int | float,
    ) -> List[Mapping[str, Any]]:
        """Project active history to the last owner of each control point."""
        active_entries = self._active_control_command_entries(absolute_minute)
        owner_by_control: Dict[Tuple[str, str, str, str], int] = {}
        simulator_ui_overrides = self._simulator_ui_control_override_keys()
        for entry_index, entry in enumerate(active_entries):
            normalized = entry.get("normalized", {})
            if not (type(normalized) is dict or isinstance(normalized, Mapping)):
                continue
            run_items = normalized.get("run_status", [])
            if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)):
                for item in run_items:
                    if not (type(item) is dict or isinstance(item, Mapping)):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    if not dev_type or not dev_name:
                        continue
                    if item.get("run_stat", "") != "":
                        key = ("remote_control", dev_type, dev_name, "run_stat")
                        if key not in simulator_ui_overrides:
                            owner_by_control[key] = entry_index
                    if item.get("status", "") != "":
                        key = ("remote_control", dev_type, dev_name, "status")
                        if key not in simulator_ui_overrides:
                            owner_by_control[key] = entry_index
            set_items = normalized.get("set_values", [])
            if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)):
                for item in set_items:
                    if not (type(item) is dict or isinstance(item, Mapping)):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    set_type = str(item.get("set_type", "")).strip()
                    key = ("remote_adjustment", dev_type, dev_name, set_type)
                    if dev_type and dev_name and set_type and key not in simulator_ui_overrides:
                        owner_by_control[key] = entry_index

        projected: List[Mapping[str, Any]] = []
        for entry_index, entry in enumerate(active_entries):
            normalized = entry.get("normalized", {})
            if not (type(normalized) is dict or isinstance(normalized, Mapping)):
                continue
            selected_run_by_device: Dict[Tuple[str, str], Dict[str, Any]] = {}
            run_items = normalized.get("run_status", [])
            if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)):
                for item in run_items:
                    if not (type(item) is dict or isinstance(item, Mapping)):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    if not dev_type or not dev_name:
                        continue
                    selected = {"dev_type": dev_type, "dev_name": dev_name}
                    for field_name in ("run_stat", "status"):
                        key = ("remote_control", dev_type, dev_name, field_name)
                        if item.get(field_name, "") != "" and owner_by_control.get(key) == entry_index:
                            selected[field_name] = item.get(field_name)
                    if len(selected) > 2:
                        selected_run_by_device[(dev_type, dev_name)] = selected
            selected_set: List[Dict[str, Any]] = []
            set_items = normalized.get("set_values", [])
            if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)):
                for item in set_items:
                    if not (type(item) is dict or isinstance(item, Mapping)):
                        continue
                    key = (
                        "remote_adjustment",
                        str(item.get("dev_type", "")).strip(),
                        str(item.get("dev_name", "")).strip(),
                        str(item.get("set_type", "")).strip(),
                    )
                    if owner_by_control.get(key) == entry_index:
                        selected_set.append(dict(item))
            selected_run = list(selected_run_by_device.values())
            if not selected_run and not selected_set:
                continue

            original_run = normalized.get("run_status", [])
            original_set = normalized.get("set_values", [])
            if selected_run == original_run and selected_set == original_set:
                projected.append(entry)
                continue
            view = dict(entry)
            view_normalized = dict(normalized)
            view_normalized["run_status"] = selected_run
            view_normalized["set_values"] = selected_set
            view["normalized"] = view_normalized
            accepted = entry.get("accepted", {})
            view_accepted = dict(accepted) if (type(accepted) is dict or isinstance(accepted, Mapping)) else {}
            view_accepted["run_status"] = len(selected_run)
            view_accepted["set_values"] = len(selected_set)
            view["accepted"] = view_accepted
            projected.append(view)
        return projected

    def _queued_active_control_command_views(
        self,
        absolute_minute: int | float,
    ) -> List[Mapping[str, Any]]:
        """Project the current highest-priority waiting owner per control point.

        A simulator UI override queues the otherwise-effective command.  A
        manual trainee command remains effective, while the latest automatic
        fallback for the same control point waits behind it.  Historical
        acceptance flags are deliberately not used here because a command can
        enter or leave the queue after it was received.
        """
        active_entries = self._active_control_command_entries(absolute_minute)
        simulator_ui_overrides = self._simulator_ui_control_override_keys()
        winner_by_control: Dict[Tuple[str, str, str, str], int] = {}
        automatic_by_control: Dict[Tuple[str, str, str, str], int] = {}

        def record_owner(
            key: Tuple[str, str, str, str],
            entry_index: int,
            entry: Mapping[str, Any],
        ) -> None:
            winner_by_control[key] = entry_index
            if _command_origin(entry) == "automatic":
                automatic_by_control[key] = entry_index

        for entry_index, entry in enumerate(active_entries):
            normalized = entry.get("normalized", {})
            if not (type(normalized) is dict or isinstance(normalized, Mapping)):
                continue
            run_items = normalized.get("run_status", [])
            if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)):
                for item in run_items:
                    if not (type(item) is dict or isinstance(item, Mapping)):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    if not dev_type or not dev_name:
                        continue
                    for field_name in ("run_stat", "status"):
                        if item.get(field_name, "") != "":
                            record_owner(
                                ("remote_control", dev_type, dev_name, field_name),
                                entry_index,
                                entry,
                            )
            set_items = normalized.get("set_values", [])
            if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)):
                for item in set_items:
                    if not (type(item) is dict or isinstance(item, Mapping)):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    set_type = str(item.get("set_type", "")).strip()
                    if dev_type and dev_name and set_type:
                        record_owner(
                            ("remote_adjustment", dev_type, dev_name, set_type),
                            entry_index,
                            entry,
                        )

        queued_owner_by_control: Dict[Tuple[str, str, str, str], int] = {}
        for key, winner_index in winner_by_control.items():
            if key in simulator_ui_overrides:
                queued_owner_by_control[key] = winner_index
                continue
            winner = active_entries[winner_index]
            if _command_origin(winner) != "manual":
                continue
            automatic_index = automatic_by_control.get(key)
            if automatic_index is not None and automatic_index != winner_index:
                queued_owner_by_control[key] = automatic_index

        projected: List[Mapping[str, Any]] = []
        for entry_index, entry in enumerate(active_entries):
            normalized = entry.get("normalized", {})
            if not (type(normalized) is dict or isinstance(normalized, Mapping)):
                continue
            selected_run_by_device: Dict[Tuple[str, str], Dict[str, Any]] = {}
            run_items = normalized.get("run_status", [])
            if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)):
                for item in run_items:
                    if not (type(item) is dict or isinstance(item, Mapping)):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    if not dev_type or not dev_name:
                        continue
                    selected = {"dev_type": dev_type, "dev_name": dev_name}
                    for field_name in ("run_stat", "status"):
                        key = ("remote_control", dev_type, dev_name, field_name)
                        if (
                            item.get(field_name, "") != ""
                            and queued_owner_by_control.get(key) == entry_index
                        ):
                            selected[field_name] = item.get(field_name)
                    if len(selected) > 2:
                        selected_run_by_device[(dev_type, dev_name)] = selected

            selected_set: List[Dict[str, Any]] = []
            set_items = normalized.get("set_values", [])
            if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)):
                for item in set_items:
                    if not (type(item) is dict or isinstance(item, Mapping)):
                        continue
                    key = (
                        "remote_adjustment",
                        str(item.get("dev_type", "")).strip(),
                        str(item.get("dev_name", "")).strip(),
                        str(item.get("set_type", "")).strip(),
                    )
                    if queued_owner_by_control.get(key) == entry_index:
                        selected_set.append(dict(item))

            selected_run = list(selected_run_by_device.values())
            if not selected_run and not selected_set:
                continue
            view = dict(entry)
            view_normalized = dict(normalized)
            view_normalized["run_status"] = selected_run
            view_normalized["set_values"] = selected_set
            view["normalized"] = view_normalized
            accepted = entry.get("accepted", {})
            view_accepted = dict(accepted) if (type(accepted) is dict or isinstance(accepted, Mapping)) else {}
            view_accepted["run_status"] = len(selected_run)
            view_accepted["set_values"] = len(selected_set)
            view["accepted"] = view_accepted
            view["queued"] = len(selected_run) + len(selected_set)
            view["queue_owner"] = "simulator"
            view["queue_state"] = "waiting"
            view["blocked"] = self._student_controls_queued_by_higher_priority(
                selected_run,
                selected_set,
                command_origin=_command_origin(entry),
                absolute_minute=absolute_minute,
            )
            projected.append(view)
        return projected

    def _defined_run_control_fields(self) -> Dict[Tuple[str, str], set[str]]:
        fields: Dict[Tuple[str, str], set[str]] = {}
        for row in self._control_definition_rows("RunStat"):
            dev_type = str(row.get("dev_type", "")).strip()
            dev_name = _dev_name(row).strip()
            if dev_type and dev_name:
                fields.setdefault((dev_type, dev_name), set()).add("run_stat")
        for row in self._control_definition_rows("CbOpenStat"):
            dev_type = str(row.get("dev_type", "")).strip()
            dev_name = _dev_name(row).strip()
            if dev_type and dev_name:
                fields.setdefault((dev_type, dev_name), set()).add("status")
        return fields

    def _defined_set_control_keys(self) -> set[Tuple[str, str, str]]:
        keys: set[Tuple[str, str, str]] = set()
        for row in self._control_definition_rows("SetValue"):
            dev_type = str(row.get("dev_type", "")).strip()
            dev_name = _dev_name(row).strip()
            set_type = str(row.get("set_type", "")).strip()
            if dev_type and dev_name and set_type:
                keys.add((dev_type, dev_name, set_type))
        return keys

    def _filter_defined_run_command_items(self, items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        allowed_fields = self._defined_run_control_fields()
        filtered: List[Dict[str, Any]] = []
        for item in items:
            dev_type = str(item.get("dev_type", "")).strip()
            dev_name = str(item.get("dev_name", "")).strip()
            fields = allowed_fields.get((dev_type, dev_name), set())
            if not dev_type or not dev_name or not fields:
                continue
            row: Dict[str, Any] = {"dev_type": dev_type, "dev_name": dev_name}
            if item.get("run_stat", "") != "" and "run_stat" in fields:
                row["run_stat"] = _number_text(item.get("run_stat"))
            if "status" in item and "status" in fields:
                row["status"] = _number_text(item.get("status"))
            if len(row) > 2:
                filtered.append(row)
        return filtered

    @staticmethod
    def _validate_run_command_items(
        items: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        validated: List[Dict[str, Any]] = []
        for item in items:
            dev_type = str(item.get("dev_type", "")).strip()
            dev_name = str(item.get("dev_name", "")).strip()
            row: Dict[str, Any] = {"dev_type": dev_type, "dev_name": dev_name}
            for field in ("run_stat", "status"):
                if field not in item or item.get(field, "") == "":
                    continue
                number = _to_float(item.get(field), None)
                if number not in (0.0, 1.0):
                    raise ValueError(
                        f"遥控安全校验失败：{dev_type}/{dev_name} 的 {field}="
                        f"{item.get(field)} 只能取 0 或 1；"
                        "本批指令未下发，仿真边界未修改。"
                    )
                row[field] = _number_text(number)
            validated.append(row)
        return validated

    def _filter_defined_set_command_items(self, items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        allowed_keys = self._defined_set_control_keys()
        filtered: List[Dict[str, Any]] = []
        for item in items:
            dev_type = str(item.get("dev_type", "")).strip()
            dev_name = str(item.get("dev_name", "")).strip()
            set_type = str(item.get("set_type", "")).strip()
            if (dev_type, dev_name, set_type) not in allowed_keys:
                continue
            filtered.append(
                {
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "set_type": set_type,
                    "set_value": _number_text(item.get("set_value", "")),
                }
            )
        return filtered

    def _validated_command_entry_items(
        self,
        command: Mapping[str, Any],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        normalized = command.get("normalized", {})
        normalized_map = normalized if (type(normalized) is dict or isinstance(normalized, Mapping)) else {}
        raw_run = normalized_map.get("run_status", [])
        raw_set = normalized_map.get("set_values", [])
        run_sequence = (
            list(raw_run)
            if isinstance(raw_run, Sequence) and not isinstance(raw_run, (str, bytes))
            else []
        )
        set_sequence = (
            list(raw_set)
            if isinstance(raw_set, Sequence) and not isinstance(raw_set, (str, bytes))
            else []
        )
        run_items = self._filter_defined_run_command_items(
            self._normalize_run_command_items(run_sequence)
        )
        set_items = self._filter_defined_set_command_items(
            self._normalize_set_command_items(set_sequence)
        )
        return (
            self._validate_run_command_items(run_items),
            self._validate_set_command_items(set_items, strict=True),
        )

    def _materialize_active_control_commands(
        self,
        absolute_minute: int | float,
        *,
        persist: bool = False,
        additional_ui_overrides: Optional[set[Tuple[str, str, str, str]]] = None,
    ) -> Dict[str, int]:
        active_entries = self._effective_active_control_command_views(absolute_minute)
        allowed_set_keys = self._defined_set_control_keys()
        active_adjustment_keys = self._remote_adjustment_keys_from_command_views(
            active_entries,
            allowed_set_keys=allowed_set_keys,
        )
        book = self._base_stat_book_for_controls()
        run_block = _ensure_block(book, "RunStat", STAT_HEADERS["RunStat"])
        cb_block = _ensure_block(book, "CbOpenStat", STAT_HEADERS["CbOpenStat"])
        set_block = _ensure_block(book, "SetValue", STAT_HEADERS["SetValue"])
        allowed_run_fields = self._defined_run_control_fields()
        source_curve_defaults = self._apply_default_source_curves(
            book,
            absolute_minute,
            allowed_set_keys=allowed_set_keys,
            active_command_keys=active_adjustment_keys,
        )
        load_curve_defaults = self._apply_default_non_electric_load_curves(
            book,
            absolute_minute,
            active_command_keys=active_adjustment_keys,
        )
        applied_run = 0
        applied_set = 0
        safe_active_entries = 0
        active_set_rows: List[Dict[str, Any]] = []
        unsafe_command_items: List[str] = []
        simulator_ui_overrides = self._simulator_ui_control_override_keys()
        if additional_ui_overrides:
            simulator_ui_overrides.update(additional_ui_overrides)

        for command in active_entries:
            try:
                run_items, set_items = self._validated_command_entry_items(command)
            except ValueError as exc:
                unsafe_command_items.append(str(exc))
                continue
            if not run_items and not set_items:
                continue
            safe_active_entries += 1
            for item in run_items:
                    dev_type = str(item.get("dev_type", ""))
                    dev_name = str(item.get("dev_name", ""))
                    if not dev_type or not dev_name:
                        continue
                    fields = allowed_run_fields.get((dev_type, dev_name), set())
                    if not fields:
                        continue
                    row = _find_dev_row(run_block, dev_type, dev_name)
                    run_stat_overridden = (
                        "remote_control", dev_type, dev_name, "run_stat"
                    ) in simulator_ui_overrides
                    status_overridden = (
                        "remote_control", dev_type, dev_name, "status"
                    ) in simulator_ui_overrides
                    if (
                        row is None
                        and not run_stat_overridden
                        and "run_stat" in fields
                        and item.get("run_stat", "") != ""
                    ):
                        row = {"dev_type": dev_type, "dev_name": dev_name, "run_stat": ""}
                        run_block.data.append(row)
                    if (
                        not run_stat_overridden
                        and row is not None
                        and item.get("run_stat", "") != ""
                        and "run_stat" in fields
                    ):
                        row["run_stat"] = _number_text(item.get("run_stat"))
                        applied_run += 1
                    if not status_overridden and "status" in item and "status" in fields:
                        cb_row = _find_dev_row(cb_block, dev_type, dev_name)
                        if cb_row is None:
                            cb_row = {
                                "dev_type": dev_type,
                                "dev_name": dev_name,
                                "closed_status_set": "",
                                "closed_status": "",
                                "status": "",
                            }
                            cb_block.data.append(cb_row)
                        cb_row["closed_status_set"] = _number_text(item.get("status"))
                        applied_run += 1
            for item in set_items:
                    dev_type = str(item.get("dev_type", ""))
                    dev_name = str(item.get("dev_name", ""))
                    set_type = str(item.get("set_type", ""))
                    if not dev_type or not dev_name or not set_type:
                        continue
                    if (dev_type, dev_name, set_type) not in allowed_set_keys:
                        continue
                    if (
                        "remote_adjustment", dev_type, dev_name, set_type
                    ) in simulator_ui_overrides:
                        continue
                    row = _find_set_row(set_block, dev_type, dev_name, set_type)
                    if row is None:
                        row = {"dev_type": dev_type, "dev_name": dev_name, "set_type": set_type, "set_value": ""}
                        set_block.data.append(row)
                    row["set_value"] = item["set_value"]
                    applied_set += 1
                    active_set_rows.append(
                        {
                            "dev_type": dev_type,
                            "dev_name": dev_name,
                            "set_type": set_type,
                            "set_value": row["set_value"],
                        }
                    )

        self.runtime_stat_book = book
        if persist:
            simu_loop.write_ebook_aligned(book, self.files["stat"])
        self._write_active_yt_ctrl_file(active_set_rows, persist=persist)
        if unsafe_command_items:
            self._append_runtime_log(
                "控制安全边界",
                "持久化指令物化",
                "越界指令已阻断",
                [
                    *unsafe_command_items,
                    "包含不安全值的整批指令未写入运行控制文件和潮流边界。",
                ],
                level="warn",
            )
        return {
            "active_commands": safe_active_entries,
            "run_status": applied_run,
            "set_values": applied_set,
            "source_curve_defaults": source_curve_defaults,
            "load_curve_defaults": load_curve_defaults,
        }

    def _simulator_ui_control_override_details(
        self,
    ) -> Dict[Tuple[str, str, str, str], Dict[str, Any]]:
        details: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
        for item in self._manual_definition_changes.values():
            if item.get("kind") != "device" or item.get("effective") is False:
                continue
            dev_type = str(item.get("block_name", "")).strip()
            field_name = str(item.get("field", "")).strip().casefold()
            row_key = item.get("row_key", {})
            dev_name = (
                str(row_key.get("name", "")).strip()
                if (type(row_key) is dict or isinstance(row_key, Mapping))
                else ""
            )
            if not dev_type or not dev_name:
                continue
            if field_name in RUNTIME_CONTROL_STATUS_FIELDS:
                control_field = "run_stat" if field_name == "run_stat" else "status"
                key = ("remote_control", dev_type, dev_name, control_field)
                details[key] = {
                    "reason": "simulator_manual_override",
                    "override_field": field_name,
                    "override_value": _number_text(item.get("current_value", "")),
                    "modified_at": str(item.get("modified_at", "")),
                }
                continue
            set_type = self._runtime_control_set_type(dev_type, field_name)
            if set_type:
                key = ("remote_adjustment", dev_type, dev_name, set_type)
                details[key] = {
                    "reason": "simulator_manual_override",
                    "override_field": field_name,
                    "override_value": _number_text(item.get("current_value", "")),
                    "modified_at": str(item.get("modified_at", "")),
                }
        return details

    def _simulator_ui_control_override_keys(self) -> set[Tuple[str, str, str, str]]:
        return set(self._simulator_ui_control_override_details())

    def _student_controls_queued_by_higher_priority(
        self,
        run_items: Sequence[Mapping[str, Any]],
        set_items: Sequence[Mapping[str, Any]],
        *,
        command_origin: str,
        absolute_minute: int | float,
    ) -> List[Dict[str, Any]]:
        override_details = self._simulator_ui_control_override_details()
        simulator_override_keys = set(override_details)
        if str(command_origin).strip().casefold() == "automatic":
            recent_start = max(0, len(self.command_history) - COMMAND_HISTORY_RECENT_LIMIT)
            for index, entry in enumerate(self.command_history):
                if index < recent_start and not self._preserve_command_history_entry(entry):
                    continue
                if (
                    _command_origin(entry) != "manual"
                    or not self._command_entry_has_accepted_controls(entry)
                    or not self._command_entry_is_active(
                        entry,
                        absolute_minute,
                        int(_to_float(self.clock.run_id, 0) or 0),
                    )
                ):
                    continue
                normalized = entry.get("normalized", {})
                if not (type(normalized) is dict or isinstance(normalized, Mapping)):
                    continue
                for item in normalized.get("run_status", []):
                    if not (type(item) is dict or isinstance(item, Mapping)):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    if not dev_type or not dev_name:
                        continue
                    for field_name in ("run_stat", "status"):
                        if item.get(field_name, "") == "":
                            continue
                        key = ("remote_control", dev_type, dev_name, field_name)
                        if key not in simulator_override_keys:
                            override_details[key] = {
                                "reason": "higher_priority_manual_command",
                                "override_field": field_name,
                                "override_value": _number_text(item.get(field_name, "")),
                                "modified_at": str(
                                    entry.get("received_wall_time", entry.get("time", ""))
                                ),
                            }
                for item in normalized.get("set_values", []):
                    if not (type(item) is dict or isinstance(item, Mapping)):
                        continue
                    dev_type = str(item.get("dev_type", "")).strip()
                    dev_name = str(item.get("dev_name", "")).strip()
                    set_type = str(item.get("set_type", "")).strip()
                    if not dev_type or not dev_name or not set_type:
                        continue
                    key = ("remote_adjustment", dev_type, dev_name, set_type)
                    if key not in simulator_override_keys:
                        override_details[key] = {
                            "reason": "higher_priority_manual_command",
                            "override_field": set_type,
                            "override_value": _number_text(item.get("set_value", "")),
                            "modified_at": str(
                                entry.get("received_wall_time", entry.get("time", ""))
                            ),
                        }
        blocked: List[Dict[str, Any]] = []
        seen: set[Tuple[str, str, str, str]] = set()

        def append_blocked(key: Tuple[str, str, str, str]) -> None:
            if key in seen or key not in override_details:
                return
            seen.add(key)
            kind, dev_type, dev_name, field_name = key
            detail = override_details[key]
            reason = str(detail.get("reason", "simulator_manual_override"))
            override_field = str(detail.get("override_field", field_name))
            override_value = str(detail.get("override_value", ""))
            if reason == "higher_priority_manual_command":
                message = (
                    f"更高优先级的学员人工指令已将 {dev_type}/{dev_name} 的 {override_field} "
                    f"设为 {override_value}；本自动指令已由模拟台记录并在模拟台后台排队；"
                    "在该人工指令取消或失效后"
                    "若仍在自身有效期内，将按优先级执行。"
                )
            else:
                message = (
                    f"模拟台人工修改已将 {dev_type}/{dev_name} 的 {override_field} "
                    f"固定为 {override_value}；本指令已由模拟台记录并在模拟台后台排队；"
                    "恢复该人工修改后，"
                    "仍有效的排队指令将按优先级执行。"
                )
            blocked.append(
                {
                    "kind": kind,
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "field": field_name,
                    "reason": reason,
                    "override_field": override_field,
                    "override_value": override_value,
                    "modified_at": str(detail.get("modified_at", "")),
                    "message": message,
                }
            )

        for item in run_items:
            dev_type = str(item.get("dev_type", "")).strip()
            dev_name = str(item.get("dev_name", "")).strip()
            if not dev_type or not dev_name:
                continue
            if item.get("run_stat", "") != "":
                append_blocked(("remote_control", dev_type, dev_name, "run_stat"))
            if item.get("status", "") != "":
                append_blocked(("remote_control", dev_type, dev_name, "status"))
        for item in set_items:
            dev_type = str(item.get("dev_type", "")).strip()
            dev_name = str(item.get("dev_name", "")).strip()
            set_type = str(item.get("set_type", "")).strip()
            if dev_type and dev_name and set_type:
                append_blocked(("remote_adjustment", dev_type, dev_name, set_type))
        return blocked

    def _remote_adjustment_keys_from_command_views(
        self,
        command_views: Sequence[Mapping[str, Any]],
        *,
        allowed_set_keys: Optional[set[Tuple[str, str, str]]] = None,
    ) -> set[Tuple[str, str, str]]:
        allowed = (
            allowed_set_keys
            if allowed_set_keys is not None
            else self._defined_set_control_keys()
        )
        active_keys: set[Tuple[str, str, str]] = set()
        simulator_ui_overrides = {
            (dev_type, dev_name, field_name)
            for kind, dev_type, dev_name, field_name in self._simulator_ui_control_override_keys()
            if kind == "remote_adjustment"
        }
        for command in command_views:
            try:
                _run_items, set_items = self._validated_command_entry_items(command)
            except ValueError:
                continue
            for item in set_items:
                key = (
                    str(item.get("dev_type", "")),
                    str(item.get("dev_name", "")),
                    str(item.get("set_type", "")),
                )
                if key in allowed and key not in simulator_ui_overrides:
                    active_keys.add(key)
        return active_keys

    def _active_remote_adjustment_keys(self, absolute_minute: int | float) -> set[Tuple[str, str, str]]:
        return self._remote_adjustment_keys_from_command_views(
            self._effective_active_control_command_views(absolute_minute)
        )

    def _model_control_row(self, dev_type: str, dev_name: str) -> Optional[Mapping[str, Any]]:
        block = self.definition_snapshot.model_book.data.get(dev_type)
        if block is None:
            return None
        return next(
            (
                row
                for row in getattr(block, "data", [])
                if str(row.get("name", "")).strip() == dev_name
            ),
            None,
        )

    def _control_target_row(
        self,
        dev_type: str,
        dev_name: str,
    ) -> Optional[Mapping[str, Any]]:
        direct = self._model_control_row(dev_type, dev_name)
        resources = structured_resources(self.definition_snapshot.model_book)
        resource_by_key = {resource.device_key: resource for resource in resources}
        matched_resources = []
        if direct is not None:
            direct_resource = resource_by_key.get((dev_type, dev_name))
            return self._control_safety_row(direct, direct_resource)

        protocol_key = (dev_type, dev_name)
        for resource_key, protocol_keys in self._storage_runtime_protocol_keys().items():
            if protocol_key in protocol_keys and resource_key in resource_by_key:
                matched_resources.append(resource_by_key[resource_key])
        matched_resources.extend(
            resource
            for resource in resources
            if dev_name in resource_aliases(resource)
            and (not dev_type or dev_type in {"ESS", resource.source_block})
        )
        unique = {resource.device_key: resource for resource in matched_resources}
        if len(unique) != 1:
            return None
        resource = next(iter(unique.values()))
        return self._control_safety_row(resource.source, resource)

    @staticmethod
    def _control_safety_row(
        source: Mapping[str, Any],
        resource: Any = None,
    ) -> Mapping[str, Any]:
        """Combine source and capability limits without changing model data."""

        row = dict(source)
        if resource is None:
            return row
        parameter = dict(resource.parameter)
        for field, value in parameter.items():
            row.setdefault(field, value)

        source_p_min = _to_float(row.get("p_min"), None)
        source_p_max = _to_float(row.get("p_max"), None)
        parameter_p_min = _to_float(parameter.get("p_min"), None)
        parameter_p_max = _to_float(parameter.get("p_max"), None)
        source_pair_is_placeholder = (
            source_p_min == 0.0
            and source_p_max == 0.0
            and any(value not in (None, 0.0) for value in (parameter_p_min, parameter_p_max))
        )
        if source_p_min is None or source_pair_is_placeholder:
            if parameter_p_min is not None:
                row["p_min"] = parameter_p_min
        if source_p_max is None or source_pair_is_placeholder:
            if parameter_p_max is not None:
                row["p_max"] = parameter_p_max

        if resource.technology == "storage" and (
            source_p_min is None
            or source_p_max is None
            or (source_p_min == 0.0 and source_p_max == 0.0)
        ):
            max_charge = _to_float(
                parameter.get("max_charge_power", parameter.get("charge_p_max")),
                None,
            )
            max_discharge = _to_float(
                parameter.get("max_discharge_power", parameter.get("dis_charge_p_max")),
                None,
            )
            if max_charge is not None and max_charge >= 0.0:
                row["p_min"] = -float(max_charge)
            if max_discharge is not None and max_discharge >= 0.0:
                row["p_max"] = float(max_discharge)
        return row

    def _validated_set_command_item(
        self,
        item: Mapping[str, Any],
        *,
        strict: bool,
    ) -> Dict[str, Any]:
        dev_type = str(item.get("dev_type", "")).strip()
        dev_name = str(item.get("dev_name", "")).strip()
        set_type = str(item.get("set_type", "")).strip()
        value = item.get("set_value", "")
        target = self._control_target_row(dev_type, dev_name)
        if target is None:
            if strict:
                raise ValueError(
                    f"遥调安全校验失败：未找到 {dev_type}/{dev_name} 的模型设备；"
                    "本批指令未下发，仿真边界未修改。"
                )
            return {
                "dev_type": dev_type,
                "dev_name": dev_name,
                "set_type": set_type,
                "set_value": _number_text(value),
            }

        target_type = str(dev_type)
        target_set_type = simu_loop._set_value_target_column(
            target_type,
            set_type,
            dict(target),
        )
        if not self.enforce_runtime_setpoint_bounds:
            number = _to_float(value, None)
            if number is None or not math.isfinite(number):
                raise ValueError(
                    f"遥调数值校验失败：{dev_type}/{dev_name} 的 "
                    f"{set_type}={value} 不是有限数值；"
                    "本批指令未下发，仿真边界未修改。"
                )
            return {
                "dev_type": dev_type,
                "dev_name": dev_name,
                "set_type": set_type,
                "set_value": _number_text(number),
            }
        try:
            requested_number = _to_float(value, None)
            if requested_number is None or not math.isfinite(requested_number):
                raise ValueError(f"{set_type}={value} 不是有限数值")
            number, bounds, device_clamped = clamp_setpoint_safety_bounds(
                target,
                target_set_type,
                requested_number,
            )
            hydrogen_safety = validate_hydrogen_power_setpoint_safety(
                self.definition_snapshot.model_book,
                dev_type,
                dev_name,
                target_set_type,
                number,
                clamp_to_bounds=True,
            )
            hydrogen_clamped = bool(
                hydrogen_safety and hydrogen_safety.get("clamped")
            )
            if hydrogen_clamped:
                number = float(hydrogen_safety["p_set"])
            number, _final_bounds, electrical_reclamped = (
                clamp_setpoint_safety_bounds(
                    target,
                    target_set_type,
                    number,
                )
            )
        except ValueError as exc:
            raise ValueError(
                f"遥调数值或模型校验失败：{dev_type}/{dev_name} 的 "
                f"{set_type}={_number_text(value)} 无法形成有效有限目标（{exc}）；"
                "本批指令未下发，仿真边界未修改。"
            ) from exc
        if device_clamped or hydrogen_clamped or electrical_reclamped:
            bound_text = ""
            if bounds is not None:
                lower_name, lower, upper_name, upper = bounds
                parts = []
                if lower is not None:
                    parts.append(f"{lower_name}={_number_text(lower)}")
                if upper is not None:
                    parts.append(f"{upper_name}={_number_text(upper)}")
                bound_text = "，设备边界 " + "，".join(parts)
            detail = [
                (
                    f"{dev_type}/{dev_name}.{set_type} 请求值 "
                    f"{_number_text(requested_number)} 已限幅为 {_number_text(number)}"
                    f"{bound_text}"
                ),
                "设备运行状态保持不变；限幅后的遥调指令继续登记、物化并送入潮流边界。",
            ]
            if hydrogen_clamped:
                detail.append("电氢转换目标同时按显式耦合关系和氢端流量边界完成限幅。")
            if electrical_reclamped:
                detail.append("电端与氢端边界没有完全重合，最终以电端设备边界为准并保留告警。")
            self._append_runtime_log(
                "控制安全边界",
                "遥调指令限幅",
                "越界值已限幅并继续下发",
                detail,
                level="warn",
            )
        return {
            "dev_type": dev_type,
            "dev_name": dev_name,
            "set_type": set_type,
            "set_value": _number_text(number),
        }

    def _validate_set_command_items(
        self,
        items: Sequence[Mapping[str, Any]],
        *,
        strict: bool,
    ) -> List[Dict[str, Any]]:
        return [
            self._validated_set_command_item(item, strict=strict)
            for item in items
        ]

    def _latest_true_remote_adjustment_value(self, key: Tuple[str, str, str]) -> Optional[float]:
        dev_type, dev_name, _set_type = key
        candidates: Dict[str, float] = {}
        for raw_row in self.latest_real_rows:
            row = _measurement_row_to_dict(raw_row)
            if str(row.get("dev_type", "")) != dev_type or str(row.get("dev_name", "")) != dev_name:
                continue
            if int(_to_float(row.get("valid"), 1) or 0) != 1:
                continue
            meas_type = str(row.get("meas_type", "")).upper()
            value = _to_float(row.get("value"), None)
            if meas_type and value is not None and math.isfinite(value):
                candidates[meas_type] = float(value)
        for meas_type in self._remote_adjustment_measurement_types(key):
            if meas_type in candidates:
                return candidates[meas_type]
        return None

    @staticmethod
    def _effective_remote_adjustment_response_ratio(
        base_ratio: float,
        period_seconds: Optional[float],
    ) -> float:
        """将 1 秒基准一阶响应比例按仿真步长 Δt 等效换算，避免高倍率仿真拉长响应时间常数。"""
        ratio = max(0.0, min(1.0, float(base_ratio)))
        if ratio <= 0.0 or ratio >= 1.0:
            return ratio
        if period_seconds is None:
            return ratio
        try:
            dt = float(period_seconds)
        except (TypeError, ValueError):
            return ratio
        if not math.isfinite(dt) or dt <= 0.0 or abs(dt - 1.0) <= 1e-9:
            return ratio
        effective = 1.0 - ((1.0 - ratio) ** dt)
        return max(0.0, min(1.0, effective))

    def _is_renewable_active_power_adjustment(self, key: Tuple[str, str, str]) -> bool:
        """判断遥调键是否属于风电/光伏有功上限调节。"""
        dev_type, dev_name, set_type = key
        if set_type not in ("p_set", "p_ac_set", "p_dc_set"):
            return False
        if device_role_from_type(dev_type) in {"wind", "pv"}:
            return True
        block = self.source_model_book.data.get(dev_type)
        if block is None:
            return False
        for row in block.data:
            if str(row.get("name", "")).strip() == dev_name:
                return device_role_from_type(row.get("dev_type")) in {"wind", "pv"}
        return False

    def _commit_remote_adjustment_execution(
        self,
        before_execution: Mapping[Tuple[str, str, str], Dict[str, Any]],
        pending_execution: Mapping[Tuple[str, str, str], Dict[str, Any]],
    ) -> None:
        """在潮流收敛且结果未陈旧时原子提交遥调执行状态，并保留锁外新下发的并发指令。"""
        all_keys = set(before_execution) | set(pending_execution)
        for key in all_keys:
            current_state = self._remote_adjustment_execution.get(key)
            before_state = before_execution.get(key)
            # 若潮流求解期间外部已写入新状态（如新的 force_target_once），保留外部最新状态。
            if current_state != before_state:
                continue
            if key in pending_execution:
                self._remote_adjustment_execution[key] = dict(pending_execution[key])
            else:
                self._remote_adjustment_execution.pop(key, None)

    def _remote_adjustment_boundary_books(
        self,
        absolute_minute: int | float,
        cycle_token: int,
        *,
        period_seconds: Optional[float] = None,
        return_next_state: bool = False,
    ) -> Any:
        stat_book = simu_loop._clone_ebook(self.runtime_stat_book)
        yt_ctrl_book = simu_loop._clone_ebook(self.yt_ctrl_book)
        active_keys = self._active_remote_adjustment_keys(absolute_minute)
        working_execution: Dict[Tuple[str, str, str], Dict[str, Any]] = {
            key: dict(value)
            for key, value in self._remote_adjustment_execution.items()
        }
        tracked_keys = active_keys | set(working_execution)
        response_ratio = self._effective_remote_adjustment_response_ratio(
            self.remote_adjustment_response_ratio,
            period_seconds,
        )

        for key in sorted(tracked_keys):
            target = self._set_value_from_book(self.runtime_stat_book, key)
            if target is None:
                working_execution.pop(key, None)
                continue
            try:
                safe_target = self._validated_set_command_item(
                    {
                        "dev_type": key[0],
                        "dev_name": key[1],
                        "set_type": key[2],
                        "set_value": target,
                    },
                    strict=True,
                )
                target = float(safe_target["set_value"])
            except ValueError as exc:
                self._append_runtime_log(
                    "控制安全边界",
                    "潮流边界准备",
                    "不安全目标已阻断",
                    [str(exc), "本轮潮流计算未接收该不安全遥调边界。"],
                    level="warn",
                )
                raise ValueError(
                    f"潮流边界安全校验失败：{key[0]}/{key[1]} 的 {key[2]}="
                    f"{_number_text(target)} 超出允许范围；本轮潮流计算已阻断。"
                ) from exc

            state = working_execution.get(key)
            if state is None:
                fallback = self._set_value_from_book(self.source_stat_book, key)
                current = self._latest_true_remote_adjustment_value(key)
                if current is None:
                    current = target if fallback is None else fallback
                state = {"executed_value": float(current), "last_cycle_token": None}
                working_execution[key] = state

            if state.pop("force_target_once", False):
                state["executed_value"] = float(target)
                state["target_value"] = float(target)
                state["last_cycle_token"] = cycle_token
            elif state.get("last_cycle_token") != cycle_token:
                current = self._latest_true_remote_adjustment_value(key)
                prev_executed = _to_float(state.get("executed_value"), None)
                if self._is_renewable_active_power_adjustment(key):
                    # 新能源遥调本质为有功上限设点：以 max(实测出力, 上拍已执行设点) 作为基线，
                    # 防止夜间/无风实发为 0 时放开限幅被永久卡在 response_ratio * target。
                    if current is not None and prev_executed is not None:
                        baseline = max(float(current), float(prev_executed))
                    elif prev_executed is not None:
                        baseline = float(prev_executed)
                    elif current is not None:
                        baseline = float(current)
                    else:
                        baseline = float(target)
                else:
                    baseline = float(current) if current is not None else float(
                        prev_executed if prev_executed is not None else target
                    )
                tolerance = max(1e-9, abs(target) * 1e-9)
                if abs(target - baseline) <= tolerance or response_ratio >= 1.0:
                    executed = target
                else:
                    executed = target * response_ratio + baseline * (1.0 - response_ratio)
                    if abs(target - executed) <= tolerance:
                        executed = target
                state["executed_value"] = float(executed)
                state["target_value"] = float(target)
                state["last_cycle_token"] = cycle_token

            executed_value = float(state.get("executed_value", target))
            try:
                requested_executed_value = executed_value
                safe_executed = self._validated_set_command_item(
                    {
                        "dev_type": key[0],
                        "dev_name": key[1],
                        "set_type": key[2],
                        "set_value": executed_value,
                    },
                    strict=True,
                )
                executed_value = float(safe_executed["set_value"])
                if not math.isclose(
                    executed_value,
                    requested_executed_value,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                ):
                    state["executed_value"] = executed_value
                    state["target_value"] = float(target)
                    self._append_runtime_log(
                        "控制安全边界",
                        "遥调逐步响应",
                        "越界中间值已限幅并继续执行",
                        [
                            (
                                f"逐步响应中间值 {_number_text(requested_executed_value)} "
                                f"已限幅为 {_number_text(executed_value)}。"
                            ),
                            (
                                f"安全目标 {_number_text(target)} 保持不变；后续周期继续按响应步长"
                                "向该目标调节。"
                            ),
                        ],
                        level="warn",
                    )
            except ValueError as exc:
                unsafe_executed = executed_value
                executed_value = float(target)
                state["executed_value"] = executed_value
                state["target_value"] = float(target)
                self._append_runtime_log(
                    "控制安全边界",
                    "遥调逐步响应",
                    "越界中间值已阻断",
                    [
                        str(exc),
                        f"逐步响应中间值 {_number_text(unsafe_executed)} 未送入潮流内核。",
                        f"已显式告警并直接采用已校验的安全目标 {_number_text(target)}。",
                    ],
                    level="warn",
                )
            self._write_boundary_set_value(stat_book, key, executed_value)
            if key in active_keys or self._set_value_from_book(yt_ctrl_book, key) is not None:
                self._write_boundary_set_value(yt_ctrl_book, key, executed_value)

            if key not in active_keys and math.isclose(executed_value, target, rel_tol=1e-9, abs_tol=1e-9):
                working_execution.pop(key, None)

        if return_next_state:
            return stat_book, yt_ctrl_book, working_execution
        self._remote_adjustment_execution = working_execution
        return stat_book, yt_ctrl_book

    def _cancel_command_input_items(self, payload: Mapping[str, Any]) -> List[Any]:
        collected: List[Any] = []
        for key in ("cancel_commands", "cancelCommands", "cancel_items", "cancelItems"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                collected.extend(value)
        for key in ("cancel_names", "cancelNames", "names"):
            value = payload.get(key)
            if isinstance(value, str):
                collected.extend(part.strip() for part in re.split(r"[,;\s]+", value) if part.strip())
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                collected.extend(str(item).strip() for item in value if str(item).strip())
        if not collected:
            for key in ("commands", "items", "controls"):
                value = payload.get(key)
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    collected.extend(value)
        if payload.get("cancel") is True or str(payload.get("action", payload.get("operation", ""))).strip().casefold() in {
            "cancel",
            "cancel_command",
            "cancel_commands",
            "取消",
            "取消指令",
        }:
            for key in ("commands", "items", "controls"):
                value = payload.get(key)
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    collected.extend(value)
            if payload.get("name"):
                collected.append(str(payload.get("name")))
        return collected

    def _cancel_command_key_from_item(self, item: Any) -> Optional[Tuple[Tuple[str, str, str, str], str]]:
        if isinstance(item, str):
            raw_item: Mapping[str, Any] = {"name": item}
        elif (type(item) is dict or isinstance(item, Mapping)):
            raw_item = item
        else:
            return None
        raw_name = str(raw_item.get("name", raw_item.get("command_name", raw_item.get("control_name", "")))).strip()
        definition = self._control_name_index().get(raw_name, {})
        dev_type = str(raw_item.get("dev_type", raw_item.get("type", definition.get("dev_type", "")))).strip()
        dev_name = str(raw_item.get("dev_name", raw_item.get("device", definition.get("dev_name", "")))).strip()
        command_kind = str(raw_item.get("command_kind", definition.get("command_kind", ""))).strip().lower()
        control_type = str(raw_item.get("control_type", raw_item.get("meas_type", definition.get("control_type", "")))).strip()
        set_type = str(raw_item.get("set_type", definition.get("set_type", ""))).strip()
        if (not dev_type or not dev_name or not (set_type or control_type)) and raw_name:
            parts = raw_name.split(".")
            if len(parts) >= 3:
                dev_type = dev_type or parts[0]
                dev_name = dev_name or ".".join(parts[1:-1])
                tail = parts[-1]
                if tail in ("run_stat", "status"):
                    control_type = control_type or tail
                else:
                    set_type = set_type or tail
        if not dev_type or not dev_name:
            return None
        if set_type or command_kind in ("remote_adjustment", "yt", "遥调"):
            if not set_type:
                return None
            name = raw_name or automatic_point_name(dev_type, dev_name, set_type)
            return ("remote_adjustment", dev_type, dev_name, set_type), name
        field_name = "status" if control_type == "status" else "run_stat"
        name = raw_name or automatic_point_name(dev_type, dev_name, field_name)
        return ("remote_control", dev_type, dev_name, field_name), name

    def _cancel_command_targets(self, payload: Mapping[str, Any]) -> Dict[Tuple[str, str, str, str], str]:
        targets: Dict[Tuple[str, str, str, str], str] = {}
        for item in self._cancel_command_input_items(payload):
            resolved = self._cancel_command_key_from_item(item)
            if resolved is None:
                continue
            key, name = resolved
            targets[key] = name
        return targets

    def _command_entry_control_keys(self, entry: Mapping[str, Any]) -> set[Tuple[str, str, str, str]]:
        keys: set[Tuple[str, str, str, str]] = set()
        normalized = entry.get("normalized", {})
        if not (type(normalized) is dict or isinstance(normalized, Mapping)):
            return keys
        run_items = normalized.get("run_status", [])
        if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)):
            for item in run_items:
                if not (type(item) is dict or isinstance(item, Mapping)):
                    continue
                dev_type = str(item.get("dev_type", ""))
                dev_name = str(item.get("dev_name", ""))
                if not dev_type or not dev_name:
                    continue
                if item.get("run_stat", "") != "":
                    keys.add(("remote_control", dev_type, dev_name, "run_stat"))
                if "status" in item:
                    keys.add(("remote_control", dev_type, dev_name, "status"))
        set_items = normalized.get("set_values", [])
        if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)):
            for item in set_items:
                if not (type(item) is dict or isinstance(item, Mapping)):
                    continue
                dev_type = str(item.get("dev_type", ""))
                dev_name = str(item.get("dev_name", ""))
                set_type = str(item.get("set_type", ""))
                if dev_type and dev_name and set_type:
                    keys.add(("remote_adjustment", dev_type, dev_name, set_type))
        return keys

    def _clear_automatic_commands_for_simulation_restart(
        self,
        *,
        reason: str = "simulation_restart",
    ) -> Dict[str, int]:
        cancelled_wall_time = _now_text()
        cancelled_simu_time = minute_to_time(self.clock.minute)
        cancelled_absolute_minute = float(self.clock.absolute_minute)
        cancelled_entries = 0
        cancelled_keys: set[Tuple[str, str, str, str]] = set()

        for entry in self.command_history:
            if not isinstance(entry, dict):
                continue
            if _command_origin(entry) != "automatic":
                continue
            if not self._command_entry_has_recorded_controls(entry):
                continue
            entry_keys = self._command_entry_control_keys(entry)
            if not entry_keys:
                continue
            entry["cancelled"] = True
            entry["cancelled_reason"] = reason
            entry["expires_at_absolute_minute"] = cancelled_absolute_minute
            entry["cancelled_names"] = sorted(
                f"{dev_type}.{dev_name}.{field_name}"
                for _kind, dev_type, dev_name, field_name in entry_keys
            )
            entry["cancelled_wall_time"] = cancelled_wall_time
            entry["cancelled_simu_time"] = cancelled_simu_time
            entry["cancelled_absolute_minute"] = cancelled_absolute_minute
            entry["cancelled_run_id"] = int(self.clock.run_id)
            cancelled_entries += 1
            cancelled_keys.update(entry_keys)

        if cancelled_entries:
            self._bump_command_mutation_seq()

        self._force_control_targets_after_automatic_removal(cancelled_keys)

        return {
            "entries": cancelled_entries,
            "remote_controls": sum(1 for key in cancelled_keys if key[0] == "remote_control"),
            "remote_adjustments": sum(1 for key in cancelled_keys if key[0] == "remote_adjustment"),
        }

    def _delete_command_entry_controls(
        self,
        entry: Dict[str, Any],
        targets: set[Tuple[str, str, str, str]],
        *,
        deleted_names: Mapping[Tuple[str, str, str, str], str],
        deleted_wall_time: str,
        deleted_simu_time: str,
        deleted_absolute_minute: float,
    ) -> set[Tuple[str, str, str, str]]:
        normalized = entry.get("normalized")
        if not isinstance(normalized, dict):
            return set()

        removed: set[Tuple[str, str, str, str]] = set()
        retained_run: List[Dict[str, Any]] = []
        run_items = normalized.get("run_status", [])
        if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)):
            for raw_item in run_items:
                if not (type(raw_item) is dict or isinstance(raw_item, Mapping)):
                    continue
                item = dict(raw_item)
                dev_type = str(item.get("dev_type", ""))
                dev_name = str(item.get("dev_name", ""))
                run_key = ("remote_control", dev_type, dev_name, "run_stat")
                status_key = ("remote_control", dev_type, dev_name, "status")
                if item.get("run_stat", "") != "" and run_key in targets:
                    item.pop("run_stat", None)
                    removed.add(run_key)
                if "status" in item and status_key in targets:
                    item.pop("status", None)
                    removed.add(status_key)
                if item.get("run_stat", "") != "" or "status" in item:
                    retained_run.append(item)

        retained_set: List[Dict[str, Any]] = []
        set_items = normalized.get("set_values", [])
        if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)):
            for raw_item in set_items:
                if not (type(raw_item) is dict or isinstance(raw_item, Mapping)):
                    continue
                item = dict(raw_item)
                key = (
                    "remote_adjustment",
                    str(item.get("dev_type", "")),
                    str(item.get("dev_name", "")),
                    str(item.get("set_type", "")),
                )
                if key in targets:
                    removed.add(key)
                    continue
                retained_set.append(item)

        if not removed:
            return set()

        normalized["run_status"] = retained_run
        normalized["set_values"] = retained_set
        accepted = entry.get("accepted")
        if not isinstance(accepted, dict):
            accepted = {}
            entry["accepted"] = accepted
        accepted["run_status"] = len(retained_run)
        accepted["set_values"] = len(retained_set)

        remaining_controls = bool(retained_run or retained_set)
        if remaining_controls:
            entry["partially_cancelled"] = True
        else:
            entry["cancelled"] = True
            entry["expires_at_absolute_minute"] = deleted_absolute_minute

        existing_names = entry.get("cancelled_names", [])
        merged_names = {
            str(name)
            for name in existing_names
            if str(name).strip()
        } if isinstance(existing_names, Sequence) and not isinstance(existing_names, (str, bytes)) else set()
        merged_names.update(deleted_names[key] for key in removed if key in deleted_names)
        entry["cancelled_names"] = sorted(merged_names)
        entry["cancelled_wall_time"] = deleted_wall_time
        entry["cancelled_simu_time"] = deleted_simu_time
        entry["cancelled_absolute_minute"] = deleted_absolute_minute
        return removed

    def _repair_legacy_cancel_command_entries(self, history: List[Dict[str, Any]]) -> bool:
        changed = False
        for index, entry in enumerate(history):
            if not isinstance(entry, dict):
                continue
            cancel_payload = self._cancel_payload_from_history_entry(entry)
            if not _has_cancel_command_payload(cancel_payload):
                continue
            source = str(entry.get("source") or cancel_payload.get("source") or "")
            if not _is_trainee_command_source(source):
                continue
            targets = self._cancel_command_targets(cancel_payload)
            if not targets:
                continue
            origin_filter = _cancel_command_origin_filter(cancel_payload)
            cancel_minute = _to_float(
                entry.get("received_absolute_minute", entry.get("issued_absolute_minute", entry.get("expires_at_absolute_minute"))),
                None,
            )
            if cancel_minute is None:
                continue
            run_id = _to_float(entry.get("run_id"), None)
            cancelled_keys: set[Tuple[str, str, str, str]] = set()
            for previous in reversed(history[:index]):
                if not isinstance(previous, dict):
                    continue
                if not self._command_entry_can_be_cancelled(previous, cancel_minute, int(run_id) if run_id is not None else None):
                    continue
                if origin_filter != "all" and _command_origin(previous) != origin_filter:
                    continue
                matched = self._command_entry_control_keys(previous) & set(targets)
                if not matched:
                    continue
                previous["expires_at_absolute_minute"] = cancel_minute
                previous["cancelled"] = True
                previous["cancelled_names"] = [targets[key] for key in sorted(matched)]
                previous["cancelled_wall_time"] = entry.get("received_wall_time", entry.get("time", ""))
                previous["cancelled_simu_time"] = entry.get("received_simu_time", minute_to_time(cancel_minute))
                previous["cancelled_absolute_minute"] = cancel_minute
                cancelled_keys.update(matched)
                changed = True

            accepted = entry.get("accepted")
            if not isinstance(accepted, dict):
                accepted = {}
                entry["accepted"] = accepted
                changed = True
            cancelled_remote = sum(1 for key in cancelled_keys if key[0] == "remote_control")
            cancelled_adjustment = sum(1 for key in cancelled_keys if key[0] == "remote_adjustment")
            missing = max(0, len(targets) - len(cancelled_keys))
            for key, value in {
                "cancelled_run_status": cancelled_remote,
                "cancelled_set_values": cancelled_adjustment,
                "missing": missing,
            }.items():
                if accepted.get(key) != value:
                    accepted[key] = value
                    changed = True

            normalized = entry.get("normalized")
            if not isinstance(normalized, dict):
                normalized = {"run_status": [], "set_values": []}
                entry["normalized"] = normalized
                changed = True
            cancel_rows = [
                {"name": targets[key], "cancelled": key in cancelled_keys}
                for key in sorted(targets)
            ]
            if normalized.get("cancel_commands") != cancel_rows:
                normalized["cancel_commands"] = cancel_rows
                changed = True
        return changed

    def _command_history_identity_token(self) -> Tuple[int, int, int]:
        return (
            id(self.command_history),
            len(self.command_history),
            id(self.command_history[-1]) if self.command_history else 0,
        )

    @staticmethod
    def _strategy_generation_entry_metadata(entry: Mapping[str, Any]) -> Tuple[str, Any, bool]:
        strategy_id, generation, replace_generation = _strategy_generation_metadata(entry)
        payload = entry.get("payload")
        if (type(payload) is dict or isinstance(payload, Mapping)):
            payload_strategy_id, payload_generation, payload_replace_generation = _strategy_generation_metadata(payload)
            strategy_id = strategy_id or payload_strategy_id
            if generation in (None, ""):
                generation = payload_generation
            replace_generation = replace_generation or payload_replace_generation
        return strategy_id, generation, replace_generation

    def _entry_belongs_in_strategy_generation_index(
        self,
        entry: Mapping[str, Any],
    ) -> Tuple[str, bool]:
        if entry.get("cancelled") or _command_origin(entry) != "automatic":
            return "", False
        strategy_id, _generation, replace_generation = (
            self._strategy_generation_entry_metadata(entry)
        )
        indexed = bool(
            strategy_id
            and (
                replace_generation
                or self._command_entry_has_accepted_controls(entry)
            )
        )
        return strategy_id, indexed

    def _rebuild_strategy_generation_index(self) -> None:
        indexed: Dict[str, List[Dict[str, Any]]] = {}
        for entry in self.command_history:
            if not isinstance(entry, dict):
                continue
            strategy_id, include = self._entry_belongs_in_strategy_generation_index(
                entry
            )
            if include:
                indexed.setdefault(strategy_id, []).append(entry)
        self._strategy_generation_entries = indexed
        self._strategy_generation_index_token = self._command_history_identity_token()

    def _ensure_strategy_generation_index(self) -> None:
        if self._strategy_generation_index_token != self._command_history_identity_token():
            self._rebuild_strategy_generation_index()

    def _prune_command_history_locked(self) -> None:
        """限制内存指令历史总量，始终保留全部当前生效指令与最新已完成记录，防止长期运行内存膨胀。"""
        limit = max(COMMAND_HISTORY_RECENT_LIMIT, int(COMMAND_HISTORY_MEMORY_LIMIT))
        if len(self.command_history) <= limit:
            return
        current_minute = float(getattr(self.clock, "absolute_minute", 0.0) or 0.0)
        active_indices: set[int] = set()
        for idx, entry in enumerate(self.command_history):
            if self._command_entry_is_active(entry, current_minute):
                active_indices.add(idx)
        remaining_slots = max(0, limit - len(active_indices))
        keep_indices = set(active_indices)
        if remaining_slots > 0:
            for idx in range(len(self.command_history) - 1, -1, -1):
                if idx in keep_indices:
                    continue
                keep_indices.add(idx)
                remaining_slots -= 1
                if remaining_slots == 0:
                    break
        self.command_history = [
            entry for idx, entry in enumerate(self.command_history) if idx in keep_indices
        ]
        self._rebuild_strategy_generation_index()

    def _append_command_history_entry(self, entry: Dict[str, Any]) -> None:
        self._ensure_strategy_generation_index()
        self.command_history.append(entry)
        self._command_mutation_seq = int(getattr(self, "_command_mutation_seq", 0) or 0) + 1
        self._command_signature_cache = None
        self._device_runtime_supplement_cache = None
        strategy_id, include = self._entry_belongs_in_strategy_generation_index(entry)
        if include:
            self._strategy_generation_entries.setdefault(strategy_id, []).append(entry)
        self._strategy_generation_index_token = self._command_history_identity_token()
        if len(self.command_history) > COMMAND_HISTORY_MEMORY_LIMIT:
            self._prune_command_history_locked()

    def _matching_complete_strategy_snapshot(
        self,
        *,
        strategy_id: str,
        generation: Any,
        run_items: Sequence[Mapping[str, Any]],
        set_items: Sequence[Mapping[str, Any]],
        absolute_minute: float,
    ) -> Optional[Mapping[str, Any]]:
        self._ensure_strategy_generation_index()
        for entry in reversed(self._strategy_generation_entries.get(strategy_id, ())):
            _entry_strategy_id, entry_generation, replace_generation = (
                self._strategy_generation_entry_metadata(entry)
            )
            if (
                not replace_generation
                or not entry.get("snapshot_complete")
                or not _strategy_generation_matches(entry_generation, generation)
                or not self._command_entry_is_active(entry, absolute_minute)
            ):
                continue
            normalized = entry.get("normalized", {})
            if not (type(normalized) is dict or isinstance(normalized, Mapping)):
                continue
            if (
                list(normalized.get("run_status", [])) == list(run_items)
                and list(normalized.get("set_values", [])) == list(set_items)
            ):
                return entry
        return None

    def _mark_strategy_generations_cancelled(
        self,
        *,
        strategy_id: str,
        generation: Any = None,
        reason: str,
        cancelled_wall_time: str,
        cancelled_simu_time: str,
        cancelled_absolute_minute: float,
        require_generation_match: bool,
    ) -> Tuple[int, set[Tuple[str, str, str, str]]]:
        self._ensure_strategy_generation_index()
        cancelled_entries = 0
        cancelled_keys: set[Tuple[str, str, str, str]] = set()
        indexed_entries = list(self._strategy_generation_entries.get(strategy_id, ()))
        retained_entries: List[Dict[str, Any]] = []
        for entry in indexed_entries:
            entry_strategy_id, entry_generation, replace_generation = self._strategy_generation_entry_metadata(entry)
            if entry_strategy_id != strategy_id:
                retained_entries.append(entry)
                continue
            if require_generation_match and not _strategy_generation_matches(entry_generation, generation):
                retained_entries.append(entry)
                continue
            # A strategy snapshot can legitimately contain no control points.  Keep
            # those records cancellable, but do not reinterpret unrelated metadata
            # as a replaceable strategy generation.
            if not replace_generation and not self._command_entry_has_accepted_controls(entry):
                continue
            entry_keys = self._command_entry_control_keys(entry)
            entry["cancelled"] = True
            entry["cancelled_reason"] = reason
            entry["expires_at_absolute_minute"] = cancelled_absolute_minute
            entry["cancelled_names"] = sorted(
                f"{dev_type}.{dev_name}.{field_name}"
                for _kind, dev_type, dev_name, field_name in entry_keys
            )
            entry["cancelled_wall_time"] = cancelled_wall_time
            entry["cancelled_simu_time"] = cancelled_simu_time
            entry["cancelled_absolute_minute"] = cancelled_absolute_minute
            entry["cancelled_run_id"] = int(self.clock.run_id)
            cancelled_entries += 1
            cancelled_keys.update(entry_keys)

        if cancelled_entries:
            self._bump_command_mutation_seq()
        if retained_entries:
            self._strategy_generation_entries[strategy_id] = retained_entries
        else:
            self._strategy_generation_entries.pop(strategy_id, None)
        self._strategy_generation_index_token = self._command_history_identity_token()
        return cancelled_entries, cancelled_keys

    def _cancel_strategy_generation(
        self,
        payload: Mapping[str, Any],
        source: str,
    ) -> Dict[str, Any]:
        strategy_id, generation, _replace_generation = _strategy_generation_metadata(payload)
        cancel_all_raw = payload.get(
            "cancel_all_generations",
            payload.get("cancelAllGenerations", False),
        )
        cancel_all_generations = bool(
            cancel_all_raw is True
            or str(cancel_all_raw or "").strip().casefold()
            in {"1", "true", "yes", "on"}
        )
        eligible_source = _is_trainee_command_source(source)
        current = float(self.clock.absolute_minute)
        received_wall_time = _now_text()
        received_simu_time = minute_to_time(self.clock.minute)
        reason = str(payload.get("reason", payload.get("cancelled_reason", "strategy_generation_revoked")) or "").strip()
        reason = reason or "strategy_generation_revoked"
        cancelled_entries = 0
        cancelled_keys: set[Tuple[str, str, str, str]] = set()

        if eligible_source and strategy_id and (
            cancel_all_generations or generation not in (None, "")
        ):
            cancelled_entries, cancelled_keys = self._mark_strategy_generations_cancelled(
                strategy_id=strategy_id,
                generation=generation,
                reason=reason,
                cancelled_wall_time=received_wall_time,
                cancelled_simu_time=received_simu_time,
                cancelled_absolute_minute=current,
                require_generation_match=not cancel_all_generations,
            )

        cancel_entry = {
            "time": received_wall_time,
            "received_wall_time": received_wall_time,
            "received_simu_time": received_simu_time,
            "received_absolute_minute": current,
            "run_id": int(self.clock.run_id),
            "source": source,
            "eligible_source": eligible_source,
            "manual_hold": False,
            "command_origin": "automatic",
            "issued_absolute_minute": current,
            "expires_at_absolute_minute": current,
            "valid_for_minutes": 0.0,
            "strategy_id": strategy_id,
            "generation": generation,
            "cancel_all_generations": cancel_all_generations,
            "cancelled_reason": reason,
            "accepted": {
                "run_status": 0,
                "set_values": 0,
                "cancelled_generations": cancelled_entries,
                "ignored": 0 if eligible_source else 1,
            },
            "normalized": {
                "run_status": [],
                "set_values": [],
                "cancel_strategy_generation": {
                    "strategy_id": strategy_id,
                    "generation": generation,
                    "cancel_all_generations": cancel_all_generations,
                    "cancelled": cancelled_entries > 0,
                },
            },
            "payload": json.loads(json.dumps(payload, ensure_ascii=False, default=str)),
        }
        self._append_command_history_entry(cancel_entry)
        self._prepare_command_history_for_persistence()
        self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)
        self._write_command_history(prepared=True)
        self._append_runtime_log(
            "控制指令",
            "学员台 /api/student/commands",
            "策略代次已结束" if cancelled_entries else "无可结束策略代次",
            [
                f"来源 {source}",
                (
                    f"策略 {strategy_id or '--'}，全部代次"
                    if cancel_all_generations
                    else f"策略 {strategy_id or '--'}，代次 {generation if generation not in (None, '') else '--'}"
                ),
                (
                    f"结束代次 {cancelled_entries} 个，涉及控制点 {len(cancelled_keys)} 个，"
                    f"原因 {reason}"
                ),
                "已下发的自动遥控和遥调不随策略代次结束而撤销，继续锁存至仿真重置、归零重启或本仿真周期结束。",
            ],
            level="ok" if cancelled_entries else "warn",
        )
        return {
            "cancelled_generations": cancelled_entries,
            "cancelled_controls": len(cancelled_keys),
            "ignored": 0 if eligible_source else 1,
            "strategy_id": strategy_id,
            "generation": generation,
            "cancel_all_generations": cancel_all_generations,
        }

    def cancel_student_commands(self, payload: Mapping[str, Any], source: str = "") -> Dict[str, Any]:
        with self.lock:
            source = source or str(payload.get("source", ""))
            action = str(payload.get("action", payload.get("operation", "")) or "").strip().casefold()
            if action in {
                "cancel_strategy_generation",
                "cancel-strategy-generation",
                "revoke_strategy_generation",
                "revoke-strategy-generation",
            }:
                return self._cancel_strategy_generation(payload, source)
            eligible_source = _is_trainee_command_source(source)
            targets = self._cancel_command_targets(payload)
            origin_filter = _cancel_command_origin_filter(payload)
            current = float(self.clock.absolute_minute)
            received_wall_time = _now_text()
            received_simu_time = minute_to_time(self.clock.minute)
            cancelled_keys: set[Tuple[str, str, str, str]] = set()
            if eligible_source and targets:
                for entry in self.command_history:
                    if not isinstance(entry, dict):
                        continue
                    if not self._command_entry_can_be_cancelled(entry, current, int(self.clock.run_id)):
                        continue
                    if _command_origin(entry) == "automatic":
                        continue
                    if origin_filter != "all" and _command_origin(entry) != origin_filter:
                        continue
                    matched = self._command_entry_control_keys(entry) & set(targets)
                    if not matched:
                        continue
                    entry["expires_at_absolute_minute"] = current
                    entry["cancelled"] = True
                    entry["cancelled_names"] = [targets[key] for key in sorted(matched)]
                    entry["cancelled_wall_time"] = received_wall_time
                    entry["cancelled_simu_time"] = received_simu_time
                    entry["cancelled_absolute_minute"] = current
                    cancelled_keys.update(matched)

            cancelled_remote = sum(1 for key in cancelled_keys if key[0] == "remote_control")
            cancelled_adjustment = sum(1 for key in cancelled_keys if key[0] == "remote_adjustment")
            ignored = 0 if eligible_source else len(targets)
            missing = max(0, len(targets) - len(cancelled_keys)) if eligible_source else 0
            result_counts = {
                "remote_controls": cancelled_remote,
                "remote_adjustments": cancelled_adjustment,
                "missing": missing,
                "ignored": ignored,
                "command_origin": origin_filter,
            }
            cancel_entry = {
                "time": received_wall_time,
                "received_wall_time": received_wall_time,
                "received_simu_time": received_simu_time,
                "received_absolute_minute": current,
                "run_id": int(self.clock.run_id),
                "source": source,
                "command_origin": origin_filter,
                "eligible_source": eligible_source,
                "issued_absolute_minute": current,
                "expires_at_absolute_minute": current,
                "valid_for_minutes": 0.0,
                "accepted": {
                    "run_status": 0,
                    "set_values": 0,
                    "cancelled_run_status": cancelled_remote,
                    "cancelled_set_values": cancelled_adjustment,
                    "ignored": ignored,
                    "missing": missing,
                },
                "normalized": {
                    "run_status": [],
                    "set_values": [],
                    "cancel_commands": [
                        {"name": targets[key], "cancelled": key in cancelled_keys}
                        for key in sorted(targets)
                    ],
                },
                "payload": json.loads(json.dumps(payload, ensure_ascii=False, default=str)),
            }
            self._append_command_history_entry(cancel_entry)
            self._prepare_command_history_for_persistence()
            self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)
            self._write_command_history(prepared=True)
            time_payload = self._api_time_payload()
            cancelled_items = [
                {
                    "name": targets[key],
                    "cancelled": key in cancelled_keys,
                    **self._external_update_time_fields(time_payload),
                }
                for key in sorted(targets)
            ]
            detail = [
                f"来源 {source}",
                f"取消范围 {'人工指令' if origin_filter == 'manual' else '自动指令' if origin_filter == 'automatic' else '全部有效指令'}",
                f"取消遥控 {cancelled_remote} 条，取消遥调 {cancelled_adjustment} 条，缺失 {missing} 条，忽略 {ignored} 条",
            ]
            if targets:
                detail.append(
                    "取消对象 "
                    + "，".join(
                        f"{targets[key]}={'已取消' if key in cancelled_keys else '未匹配'}"
                        for key in list(sorted(targets))[:8]
                    )
                    + (" ..." if len(targets) > 8 else "")
                )
            self._append_runtime_log(
                "控制指令",
                "学员台 /api/student/commands",
                "取消成功" if cancelled_keys else "无可取消指令",
                detail,
                level="ok" if cancelled_keys else "warn",
            )
            return {
                **result_counts,
                "cancelled": result_counts,
                "cancelled_items": cancelled_items,
            }

    def delete_active_commands(self, payload: Mapping[str, Any], source: str = "simulator-ui") -> Dict[str, Any]:
        """Remove active command overlays while preserving control definitions and defaults."""
        with self.lock:
            source = source or "simulator-ui"
            eligible_source = _is_simulator_command_source(source)
            targets = self._cancel_command_targets(payload)
            current = float(self.clock.absolute_minute)
            received_wall_time = _now_text()
            received_simu_time = minute_to_time(self.clock.minute)
            deleted_keys: set[Tuple[str, str, str, str]] = set()

            if eligible_source and targets:
                target_keys = set(targets)
                for entry in self.command_history:
                    if not isinstance(entry, dict):
                        continue
                    if not self._command_entry_can_be_cancelled(entry, current, int(self.clock.run_id)):
                        continue
                    if _command_origin(entry) == "automatic":
                        continue
                    matched = self._command_entry_control_keys(entry) & target_keys
                    if not matched:
                        continue
                    deleted_keys.update(
                        self._delete_command_entry_controls(
                            entry,
                            matched,
                            deleted_names=targets,
                            deleted_wall_time=received_wall_time,
                            deleted_simu_time=received_simu_time,
                            deleted_absolute_minute=current,
                        )
                    )

            if deleted_keys:
                self._command_mutation_seq = int(getattr(self, "_command_mutation_seq", 0) or 0) + 1
                self._command_signature_cache = None
                self._device_runtime_supplement_cache = None
            deleted_remote = sum(1 for key in deleted_keys if key[0] == "remote_control")
            deleted_adjustment = sum(1 for key in deleted_keys if key[0] == "remote_adjustment")
            ignored = 0 if eligible_source else len(targets)
            missing = max(0, len(targets) - len(deleted_keys)) if eligible_source else 0
            result_counts = {
                "remote_controls": deleted_remote,
                "remote_adjustments": deleted_adjustment,
                "missing": missing,
                "ignored": ignored,
            }
            delete_entry = {
                "time": received_wall_time,
                "received_wall_time": received_wall_time,
                "received_simu_time": received_simu_time,
                "received_absolute_minute": current,
                "run_id": int(self.clock.run_id),
                "source": source,
                "command_origin": "all",
                "eligible_source": eligible_source,
                "issued_absolute_minute": current,
                "expires_at_absolute_minute": current,
                "valid_for_minutes": 0.0,
                "accepted": {
                    "run_status": 0,
                    "set_values": 0,
                    "deleted_run_status": deleted_remote,
                    "deleted_set_values": deleted_adjustment,
                    "ignored": ignored,
                    "missing": missing,
                },
                "normalized": {
                    "run_status": [],
                    "set_values": [],
                    "delete_commands": [
                        {"name": targets[key], "deleted": key in deleted_keys}
                        for key in sorted(targets)
                    ],
                },
                "payload": self._compact_command_payload(
                    json.loads(json.dumps(payload, ensure_ascii=False, default=str))
                ),
            }
            self._append_command_history_entry(delete_entry)
            self._prepare_command_history_for_persistence()
            self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)
            self._write_command_history(prepared=True)
            time_payload = self._api_time_payload()
            deleted_items = [
                {
                    "name": targets[key],
                    "deleted": key in deleted_keys,
                    **self._external_update_time_fields(time_payload),
                }
                for key in sorted(targets)
            ]
            detail = [
                f"来源 {source}",
                "删除范围 当前控制点的全部有效指令覆盖，控制值恢复模拟台默认值",
                f"删除遥控 {deleted_remote} 条，删除遥调 {deleted_adjustment} 条，缺失 {missing} 条，忽略 {ignored} 条",
            ]
            if targets:
                detail.append(
                    "删除对象 "
                    + "，".join(
                        f"{targets[key]}={'已删除' if key in deleted_keys else '未匹配'}"
                        for key in list(sorted(targets))[:8]
                    )
                    + (" ..." if len(targets) > 8 else "")
                )
            self._append_runtime_log(
                "控制指令",
                "模拟台 /api/simulator/commands/delete",
                "删除成功" if deleted_keys else "无可删除指令",
                detail,
                level="ok" if deleted_keys else "warn",
            )
            return {
                **result_counts,
                "deleted": result_counts,
                "deleted_items": deleted_items,
            }

    def _command_accept_detail(
        self,
        payload: Mapping[str, Any],
        source: str,
        accepted: Mapping[str, int],
        run_items: Sequence[Any],
        set_items: Sequence[Mapping[str, Any]],
        *,
        eligible_source: bool,
        issued_absolute_minute: float,
        expires_at_absolute_minute: Optional[float],
        queued_controls: Sequence[Mapping[str, Any]] = (),
    ) -> List[str]:
        valid_text = (
            "无时间限制，人工指令保持有效直到取消"
            if expires_at_absolute_minute is None
            else (
                f"有效期 {format_number(max(0.0, expires_at_absolute_minute - issued_absolute_minute))} min，"
                f"截止累计分钟 {format_number(expires_at_absolute_minute)}"
            )
        )
        lines = [
            f"来源 {source}",
            (
                f"来源校验 {'学员台有效来源' if eligible_source else '非学员台来源，忽略为无效控制'}，"
                f"{valid_text}"
            ),
            f"接受投退 {accepted.get('run_status', 0)} 条，设值 {accepted.get('set_values', 0)} 条，忽略 {accepted.get('ignored', 0)} 条",
        ]
        run_preview = []
        for item in run_items:
            if not (type(item) is dict or isinstance(item, Mapping)):
                continue
            dev_type = str(item.get("dev_type", item.get("type", "")))
            dev_name = str(item.get("dev_name", item.get("name", "")))
            if not dev_type or not dev_name:
                continue
            if item.get("run_stat", "") != "" or "running" in item:
                run_stat = item.get("run_stat", item.get("running", item.get("value", "")))
                if isinstance(run_stat, bool):
                    run_stat = 1 if run_stat else 0
                run_preview.append(f"{dev_type}.{dev_name}.run_stat={_number_text(run_stat)}")
            if "status" in item:
                status = item.get("status")
                if isinstance(status, bool):
                    status = 1 if status else 0
                run_preview.append(f"{dev_type}.{dev_name}.status={_number_text(status)}")
        if run_preview:
            lines.append("投退明细 " + "，".join(run_preview[:6]) + (" ..." if len(run_preview) > 6 else ""))
        set_preview = [
            f"{item.get('dev_type', item.get('type', ''))}.{item.get('dev_name', item.get('name', ''))}.{item.get('set_type', '')}={_number_text(item.get('set_value', ''))}"
            for item in set_items[:8]
        ]
        set_preview = [text for text in set_preview if not text.startswith(".")]
        if set_preview:
            lines.append("设值明细 " + "，".join(set_preview) + (" ..." if len(set_items) > 8 else ""))
        strategy = payload.get("strategy")
        if (type(strategy) is dict or isinstance(strategy, Mapping)):
            strategy_lines = []
            for key, label in (
                ("name", "策略"),
                ("trigger", "触发"),
                ("load_kw", "负荷"),
                ("renewable_available_kw", "新能源可用"),
                ("renewable_used_kw", "计划消纳"),
                ("storage_kw", "储能"),
                ("diesel_residual_kw", "柴油缺额"),
                ("curtail_kw", "弃电"),
            ):
                if key in strategy:
                    strategy_lines.append(f"{label} {_number_text(strategy.get(key))}")
            if strategy_lines:
                lines.append("策略信息 " + "，".join(strategy_lines))
        if eligible_source and (accepted.get("run_status", 0) or accepted.get("set_values", 0)):
            if queued_controls:
                lines.append(
                    f"已登记为有效控制指令；其中 {len(queued_controls)} 个控制点被更高优先级控制阻断，"
                    "由模拟台持久化保管并在模拟台后台排队；学员台不保存等待任务；"
                    "高优先级覆盖取消后执行届时仍有效的最高优先级指令"
                )
                lines.extend(
                    str(item.get("message", ""))
                    for item in queued_controls[:6]
                    if str(item.get("message", ""))
                )
            else:
                lines.append("已登记为有效控制指令，并已同步到内存控制边界，等待下一轮潮流计算响应")
        else:
            lines.append("未写入有效控制边界，模拟台不会响应执行该控制指令")
        return lines

    def _command_response_detail(self, item: Mapping[str, Any], result: Mapping[str, Any]) -> List[str]:
        accepted = item.get("accepted", {})
        eligible_source = bool(item.get("eligible_source"))
        expires = _to_float(item.get("expires_at_absolute_minute"), None)
        valid_text = "无有效期" if expires is None else f"有效截止累计分钟 {format_number(expires)}"
        detail = [
            f"来源 {item.get('source', 'student')}，模拟台记录 {item.get('time', '--')}",
            (
                f"{'已响应' if eligible_source else '未响应'}投退 "
                f"{accepted.get('run_status', 0) if (type(accepted) is dict or isinstance(accepted, Mapping)) else 0} 条，设值 "
                f"{accepted.get('set_values', 0) if (type(accepted) is dict or isinstance(accepted, Mapping)) else 0} 条，{valid_text}"
            ),
            f"求解器 {result.get('solver_info', 'not-run')}，量测更新 {result.get('updated', 0)} 条，缺失 {result.get('missing', 0)} 条，叠加修正 {result.get('overlay_updates', 0)} 条",
        ]
        payload = item.get("payload", {})
        strategy = payload.get("strategy") if (type(payload) is dict or isinstance(payload, Mapping)) else None
        if (type(strategy) is dict or isinstance(strategy, Mapping)):
            detail.append(
                "策略响应 "
                + "，".join(
                    [
                        f"负荷 {_number_text(strategy.get('load_kw', ''))} kW",
                        f"新能源可用 {_number_text(strategy.get('renewable_available_kw', ''))} kW",
                        f"计划消纳 {_number_text(strategy.get('renewable_used_kw', ''))} kW",
                        f"储能 {_number_text(strategy.get('storage_kw', ''))} kW",
                        f"柴油缺额 {_number_text(strategy.get('diesel_residual_kw', ''))} kW",
                    ]
                )
            )
        detail.append("本轮真值与 SCADA 内存快照已刷新")
        return detail

    def _collect_command_response_lines(self, result: Mapping[str, Any]) -> List[str]:
        if self._last_command_response_index >= len(self.command_history):
            active = self._active_control_command_entries(self.clock.absolute_minute)
            return [
                f"控制响应 本轮无新增学员台控制指令；当前有效控制指令 {len(active)} 条"
            ]
        pending_items = self.command_history[self._last_command_response_index :]
        effective_count = sum(1 for item in pending_items if item.get("eligible_source"))
        lines = [f"控制响应 本轮新增控制记录 {len(pending_items)} 条，其中学员台有效来源 {effective_count} 条"]
        for item in pending_items:
            lines.extend(f"控制响应 {line}" for line in self._command_response_detail(item, result))
        self._last_command_response_index = len(self.command_history)
        return lines

    def _compact_command_response_lines(self, lines: Sequence[str]) -> List[str]:
        if not lines:
            return []
        first_line = str(lines[0])
        if len(lines) > 1:
            first_line = f"{first_line}；其余控制响应明细 {len(lines) - 1} 条已省略"
        return [first_line]

    def apply_student_commands(self, payload: Mapping[str, Any], source: str = "") -> Dict[str, Any]:
        if _has_cancel_command_payload(payload):
            return self.cancel_student_commands(payload, source=source)  # type: ignore[return-value]
        with self.lock:
            run_items = payload.get("run_status", payload.get("runStatus", [])) or []
            set_items = payload.get("set_values", payload.get("setValues", payload.get("setpoints", []))) or []
            run_sequence = list(run_items) if isinstance(run_items, Sequence) and not isinstance(run_items, (str, bytes)) else []
            set_sequence = list(set_items) if isinstance(set_items, Sequence) and not isinstance(set_items, (str, bytes)) else []
            requested_run_items = self._normalize_run_command_items(run_sequence)
            requested_set_items = self._normalize_set_command_items(set_sequence)
            normalized_run_items = self._filter_defined_run_command_items(requested_run_items)
            normalized_set_items = self._filter_defined_set_command_items(requested_set_items)
            eligible_source = _is_trainee_command_source(source)
            if eligible_source and (normalized_run_items or normalized_set_items):
                try:
                    normalized_run_items = self._validate_run_command_items(
                        normalized_run_items
                    )
                    normalized_set_items = self._validate_set_command_items(
                        normalized_set_items,
                        strict=True,
                    )
                except ValueError as exc:
                    self._append_runtime_log(
                        "控制安全边界",
                        "遥调指令接收",
                        "整批拒绝",
                        [
                            str(exc),
                            "本批遥控/遥调未写入指令历史、运行控制文件或潮流边界。",
                        ],
                        level="warn",
                    )
                    raise
            issued_absolute_minute = float(self.clock.absolute_minute)
            received_wall_time = _now_text()
            received_simu_time = minute_to_time(self.clock.minute)
            manual_hold = _manual_command_holds_across_clock_lifecycle(payload, source)
            command_origin = "manual" if manual_hold else "automatic"
            strategy_id, generation, replace_strategy_generation = _strategy_generation_metadata(payload)
            complete_strategy_snapshot = bool(
                eligible_source
                and command_origin == "automatic"
                and strategy_id
                and generation not in (None, "")
                and replace_strategy_generation
            )
            expires_at_absolute_minute = (
                None
                if manual_hold
                else _command_expires_at(payload, None, issued_absolute_minute)
            )
            if command_origin == "automatic":
                cycle_minutes = float(self._simulation_cycle_minutes())
                cycle_end = (
                    math.floor((issued_absolute_minute + 1e-9) / cycle_minutes) + 1
                ) * cycle_minutes
                expires_at_absolute_minute = cycle_end
            accepted_run = len(normalized_run_items) if eligible_source else 0
            accepted_set = len(normalized_set_items) if eligible_source else 0
            requested_count = len(requested_run_items) + len(requested_set_items)
            ignored = requested_count - accepted_run - accepted_set if eligible_source else requested_count
            accepted = {"run_status": accepted_run, "set_values": accepted_set, "ignored": ignored}
            queued_controls = (
                self._student_controls_queued_by_higher_priority(
                    normalized_run_items,
                    normalized_set_items,
                    command_origin=command_origin,
                    absolute_minute=issued_absolute_minute,
                )
                if eligible_source
                else []
            )
            response: Dict[str, Any] = {
                **accepted,
                "received_by": "simulator",
                "receive_state": "completed",
            }
            if queued_controls:
                response["queued"] = len(queued_controls)
                response["queue_owner"] = "simulator"
                response["queue_state"] = "waiting"
                response["blocked"] = copy.deepcopy(queued_controls)
            if complete_strategy_snapshot and self._matching_complete_strategy_snapshot(
                strategy_id=strategy_id,
                generation=generation,
                run_items=normalized_run_items,
                set_items=normalized_set_items,
                absolute_minute=issued_absolute_minute,
            ) is not None:
                return response
            valid_for_minutes = (
                None
                if expires_at_absolute_minute is None
                else max(0.0, expires_at_absolute_minute - issued_absolute_minute)
            )
            superseded_generations = 0
            superseded_controls: set[Tuple[str, str, str, str]] = set()
            if complete_strategy_snapshot:
                superseded_generations, superseded_controls = self._mark_strategy_generations_cancelled(
                    strategy_id=strategy_id,
                    reason="superseded_strategy_generation",
                    cancelled_wall_time=received_wall_time,
                    cancelled_simu_time=received_simu_time,
                    cancelled_absolute_minute=issued_absolute_minute,
                    require_generation_match=False,
                )
            command_entry = {
                "time": received_wall_time,
                "received_wall_time": received_wall_time,
                "received_simu_time": received_simu_time,
                "received_absolute_minute": issued_absolute_minute,
                "run_id": int(self.clock.run_id),
                "source": source,
                "received_by": "simulator",
                "receive_state": "completed",
                "eligible_source": eligible_source,
                "manual_hold": manual_hold,
                "command_origin": command_origin,
                "issued_absolute_minute": issued_absolute_minute,
                "expires_at_absolute_minute": expires_at_absolute_minute,
                "valid_for_minutes": valid_for_minutes,
                "strategy_id": strategy_id,
                "generation": generation,
                "replace_strategy_generation": replace_strategy_generation,
                "snapshot_complete": complete_strategy_snapshot,
                "superseded_generations": superseded_generations,
                "superseded_controls": len(superseded_controls),
                "accepted": accepted,
                "normalized": {
                    "run_status": normalized_run_items if eligible_source else [],
                    "set_values": normalized_set_items if eligible_source else [],
                },
                "payload": self._compact_command_payload(
                    json.loads(json.dumps(payload, ensure_ascii=False, default=str))
                ),
            }
            if queued_controls:
                command_entry["queued_at_acceptance"] = len(queued_controls)
                command_entry["queue_owner_at_acceptance"] = "simulator"
                command_entry["queue_state_at_acceptance"] = "waiting"
                command_entry["blocked_at_acceptance"] = copy.deepcopy(queued_controls)
            self._append_command_history_entry(command_entry)
            self._prepare_command_history_for_persistence()
            self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)
            self._write_command_history(prepared=True)
            self._append_runtime_log(
                "控制指令",
                "学员台 /api/student/commands",
                (
                    "接收完成，策略快照已替换"
                    if complete_strategy_snapshot
                    else (
                        "接收完成，模拟台排队"
                        if queued_controls
                        else (
                            "接收完成，立即生效"
                            if accepted_run or accepted_set
                            else "接收完成，未采纳"
                        )
                    )
                ),
                self._command_accept_detail(
                    payload,
                    source,
                    accepted,
                    run_sequence,
                    normalized_set_items,
                    eligible_source=eligible_source,
                    issued_absolute_minute=issued_absolute_minute,
                    expires_at_absolute_minute=expires_at_absolute_minute,
                    queued_controls=queued_controls,
                ),
                level="warn" if queued_controls else ("ok" if accepted_run or accepted_set else "warn"),
            )
            return response

    def _external_load_catalog(self) -> List[Dict[str, str]]:
        catalog: List[Dict[str, str]] = []
        model_book = self.definition_snapshot.model_book
        for dev_type in ("ACLoad", "DCLoad"):
            block = model_book.data.get(dev_type)
            if block is None:
                continue
            for row in block.data:
                dev_name = str(row.get("name", "")).strip()
                if not dev_name:
                    continue
                catalog.append(
                    {
                        "key": f"{dev_type}:{dev_name}",
                        "dev_type": dev_type,
                        "dev_name": dev_name,
                        "unit": "kW",
                    }
                )
        catalog.sort(key=lambda item: (item["dev_type"], item["dev_name"]))
        return catalog

    @staticmethod
    def _external_finite_number(field: str, value: Any) -> float:
        number = _to_float(value, None)
        if number is None or not math.isfinite(number):
            raise ValueError(f"{field} 必须是有限数值")
        return float(number)

    @staticmethod
    def _external_load_lookup(
        catalog: Sequence[Mapping[str, str]],
    ) -> Tuple[Dict[str, Mapping[str, str]], Dict[str, List[str]]]:
        by_key = {str(item["key"]): item for item in catalog}
        by_name: Dict[str, List[str]] = {}
        for item in catalog:
            by_name.setdefault(str(item["dev_name"]), []).append(str(item["key"]))
        return by_key, by_name

    @staticmethod
    def _resolve_external_load_key(
        raw_key: Any,
        by_key: Mapping[str, Mapping[str, str]],
        by_name: Mapping[str, Sequence[str]],
    ) -> str:
        key = str(raw_key or "").strip()
        if not key:
            raise ValueError("负荷输入缺少设备名称")
        if key in by_key:
            return key
        if ":" in key:
            raise ValueError(f"负荷 {key} 在当前模型中不存在")
        matches = list(by_name.get(key, []))
        if not matches:
            raise ValueError(f"负荷 {key} 在当前模型中不存在")
        if len(matches) > 1:
            raise ValueError(
                f"负荷名称 {key} 不唯一，请使用 ACLoad:{key} 或 DCLoad:{key}"
            )
        return matches[0]

    def _normalize_external_realtime_weather(self, payload: Mapping[str, Any]) -> Dict[str, float]:
        raw_weather = payload.get("weather", {})
        if raw_weather in (None, ""):
            raw_weather = {}
        if not (type(raw_weather) is dict or isinstance(raw_weather, Mapping)):
            raise ValueError("weather 必须是对象")
        unknown = sorted(str(key) for key in raw_weather if str(key) not in EXTERNAL_REALTIME_WEATHER_FIELD_SET)
        if unknown:
            raise ValueError(f"weather 包含不支持的字段: {', '.join(unknown)}")

        values: Dict[str, float] = {}
        for key, _unit in EXTERNAL_REALTIME_WEATHER_FIELDS:
            if key in payload:
                values[key] = self._external_finite_number(key, payload.get(key))
            if key in raw_weather:
                values[key] = self._external_finite_number(key, raw_weather.get(key))

        for key in ("wind_speed_mps", "solar_irradiance_w_m2"):
            if key in values and values[key] < 0:
                raise ValueError(f"{key} 不能小于 0")
        if "air_pressure_hpa" in values and values["air_pressure_hpa"] <= 0:
            raise ValueError("air_pressure_hpa 必须大于 0")
        if "humidity_pct" in values and not 0 <= values["humidity_pct"] <= 100:
            raise ValueError("humidity_pct 必须在 0 到 100 之间")
        return values

    def _normalize_external_realtime_loads(
        self,
        payload: Mapping[str, Any],
        catalog: Sequence[Mapping[str, str]],
    ) -> Dict[str, float]:
        by_key, by_name = self._external_load_lookup(catalog)

        values: Dict[str, float] = {}

        def resolve_key(raw_key: Any) -> str:
            return self._resolve_external_load_key(raw_key, by_key, by_name)

        def add(raw_key: Any, raw_value: Any) -> None:
            key = resolve_key(raw_key)
            if (type(raw_value) is dict or isinstance(raw_value, Mapping)):
                sentinel = object()
                value: Any = sentinel
                for field in ("p_kw", "value", "load_kw"):
                    if field in raw_value:
                        value = raw_value.get(field)
                        break
                if value is sentinel:
                    raise ValueError(f"{key} 缺少 p_kw/value/load_kw")
                raw_value = value
            number = self._external_finite_number(key, raw_value)
            if number < 0:
                raise ValueError(f"{key} 不能小于 0")
            values[key] = number

        def add_items(raw_items: Any, field_name: str) -> None:
            if raw_items in (None, ""):
                return
            if (type(raw_items) is dict or isinstance(raw_items, Mapping)):
                for raw_key, raw_value in raw_items.items():
                    add(raw_key, raw_value)
                return
            if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
                raise ValueError(f"{field_name} 必须是对象或数组")
            for item in raw_items:
                if not (type(item) is dict or isinstance(item, Mapping)):
                    raise ValueError(f"{field_name} 数组项必须是对象")
                raw_key = item.get("key")
                if raw_key in (None, ""):
                    dev_type = str(item.get("dev_type", item.get("type", ""))).strip()
                    dev_name = str(item.get("dev_name", item.get("name", ""))).strip()
                    if dev_type:
                        if dev_type not in {"ACLoad", "DCLoad"}:
                            raise ValueError(f"负荷类型 {dev_type} 不支持，只允许 ACLoad 或 DCLoad")
                        raw_key = f"{dev_type}:{dev_name}"
                    else:
                        raw_key = dev_name
                sentinel = object()
                raw_value: Any = sentinel
                for value_key in ("p_kw", "value", "load_kw"):
                    if value_key in item:
                        raw_value = item.get(value_key)
                        break
                if raw_value is sentinel:
                    raise ValueError(f"负荷 {raw_key} 缺少 p_kw/value/load_kw")
                add(raw_key, raw_value)

        add_items(payload.get("loads"), "loads")
        add_items(payload.get("load_values"), "load_values")
        return values

    def _external_realtime_target_locked(
        self,
        target_absolute_minute: Optional[float] = None,
    ) -> Dict[str, Any]:
        mode = _normalize_simulation_mode(self.curves.get("mode", "day"))
        default_step = _simulation_mode_curve_step_minutes(mode)
        step_minutes = float(_to_float(self.curves.get("time_step_minutes"), default_step) or default_step)
        if step_minutes <= 0:
            step_minutes = default_step
        period_minutes = _simulation_mode_duration_minutes(mode)
        default_point_count = _simulation_mode_point_count(mode)
        point_count = int(_to_float(self.curves.get("point_count"), 0) or 0)
        weather = self.curves.get("weather", [])
        weather_count = (
            len(weather)
            if isinstance(weather, Sequence) and not isinstance(weather, (str, bytes))
            else 0
        )
        loads = self.curves.get("loads", {})
        load_point_count = 0
        if (type(loads) is dict or isinstance(loads, Mapping)):
            load_point_count = max(
                (
                    len(points)
                    for points in loads.values()
                    if isinstance(points, Sequence) and not isinstance(points, (str, bytes))
                ),
                default=0,
            )
        point_count = point_count or weather_count or load_point_count or default_point_count
        if target_absolute_minute is None:
            target_absolute_minute = float(_to_float(self.clock.absolute_minute, 0.0) or 0.0)
        else:
            target_absolute_minute = float(target_absolute_minute)
        if weather_count >= point_count:
            target_index = self._curve_point_index(target_absolute_minute, period_minutes) - 1
        else:
            target_index = int((target_absolute_minute % period_minutes) // step_minutes)
        target_index = max(0, min(point_count - 1, target_index))
        point_minute = target_index * step_minutes
        if weather_count > target_index and isinstance(weather[target_index], Mapping):
            point_minute = float(_to_float(weather[target_index].get("minute"), point_minute) or point_minute)
        return {
            "mode": mode,
            "time_step_minutes": step_minutes,
            "period_minutes": period_minutes,
            "point_count": point_count,
            "absolute_minute": target_absolute_minute,
            "simu_time": minute_to_time(target_absolute_minute),
            "index": target_index,
            "point_number": target_index + 1,
            "point_minute": point_minute,
        }

    def _external_realtime_target_for_time_locked(
        self,
        absolute_minute: float,
        field_label: str,
    ) -> Dict[str, Any]:
        target = self._external_realtime_target_locked(absolute_minute)
        period_minutes = float(target["period_minutes"])
        point_delta = abs(
            (absolute_minute % period_minutes)
            - float(target["point_minute"])
        )
        point_delta = min(point_delta, max(0.0, period_minutes - point_delta))
        tolerance = max(1e-9, float(target["time_step_minutes"]) * 1e-9)
        if point_delta > tolerance:
            raise ValueError(f"{field_label} 必须落在当前曲线采样网格上")
        return target

    @staticmethod
    def _external_integer_field(
        payload: Mapping[str, Any],
        keys: Sequence[str],
        *,
        required: bool,
        default: Optional[int] = None,
        minimum: int = 0,
    ) -> Optional[int]:
        selected_key = next((key for key in keys if key in payload), "")
        if not selected_key:
            if required:
                raise ValueError(f"{keys[0]} 为必填整数参数")
            return default
        raw_value = payload.get(selected_key)
        if isinstance(raw_value, bool):
            raise ValueError(f"{selected_key} 必须是整数")
        number = _to_float(raw_value, None)
        if number is None or not math.isfinite(number) or int(number) != number:
            raise ValueError(f"{selected_key} 必须是整数")
        value = int(number)
        if value < minimum:
            raise ValueError(f"{selected_key} 不能小于 {minimum}")
        return value

    def _external_input_contract_locked(
        self,
        payload: Mapping[str, Any],
        *,
        expected_count: int,
        batch: bool,
    ) -> Dict[str, Any]:
        has_count = "point_count" in payload
        interval_keys = [
            key
            for key in (
                "point_interval_seconds",
                "point_interval_minutes",
                "data_interval_seconds",
                "data_interval_minutes",
            )
            if key in payload
        ]
        if batch and not has_count:
            raise ValueError("point_count 为批量输入必填参数")
        if batch and not interval_keys:
            raise ValueError("point_interval_seconds 或 point_interval_minutes 为批量输入必填参数")
        if not batch and (has_count or interval_keys) and not (has_count and interval_keys):
            raise ValueError("单点输入显式定义数据契约时，point_count 和数据点间隔必须同时提供")
        if len(interval_keys) > 1:
            raise ValueError("数据点间隔只能使用 seconds 或 minutes 中的一种")

        point_count = self._external_integer_field(
            payload,
            ("point_count",),
            required=batch or has_count,
            default=1,
            minimum=1,
        )
        if point_count != expected_count:
            raise ValueError(
                f"point_count={point_count} 与实际数据点数量 {expected_count} 不一致"
            )

        curve_target = self._external_realtime_target_locked()
        curve_interval_minutes = float(curve_target["time_step_minutes"])
        if interval_keys:
            interval_key = interval_keys[0]
            interval_value = self._external_finite_number(interval_key, payload.get(interval_key))
            if interval_value <= 0:
                raise ValueError(f"{interval_key} 必须大于 0")
            interval_minutes = interval_value / 60.0 if interval_key.endswith("seconds") else interval_value
        else:
            interval_minutes = curve_interval_minutes
        interval_ratio = interval_minutes / curve_interval_minutes
        curve_step_count = int(round(interval_ratio))
        tolerance = max(1e-9, abs(interval_ratio) * 1e-9)
        if curve_step_count < 1 or abs(interval_ratio - curve_step_count) > tolerance:
            raise ValueError(
                "数据点间隔必须是当前曲线采样间隔 "
                f"{format_number(curve_interval_minutes * 60.0)} 秒的正整数倍"
            )
        return {
            "point_count": int(point_count or 0),
            "point_interval_minutes": interval_minutes,
            "point_interval_seconds": interval_minutes * 60.0,
            "curve_step_count": curve_step_count,
        }

    def _external_target_from_index_locked(
        self,
        target_index: int,
        *,
        reference_absolute_minute: Optional[float] = None,
    ) -> Dict[str, Any]:
        current = self._external_realtime_target_locked()
        point_count = int(current["point_count"])
        if target_index < 0 or target_index >= point_count:
            raise ValueError(
                f"目标曲线索引 {target_index} 越界，允许范围为 0..{point_count - 1}"
            )
        point_minute = target_index * float(current["time_step_minutes"])
        weather = self.curves.get("weather", [])
        if (
            isinstance(weather, Sequence)
            and not isinstance(weather, (str, bytes))
            and len(weather) > target_index
            and isinstance(weather[target_index], Mapping)
        ):
            point_minute = float(
                _to_float(weather[target_index].get("minute"), point_minute) or point_minute
            )
        reference = (
            float(reference_absolute_minute)
            if reference_absolute_minute is not None
            else float(current["absolute_minute"])
        )
        period_minutes = float(current["period_minutes"])
        cycle_start = math.floor(reference / period_minutes) * period_minutes
        absolute_minute = cycle_start + point_minute
        return {
            **current,
            "absolute_minute": absolute_minute,
            "simu_time": minute_to_time(absolute_minute),
            "index": target_index,
            "point_number": target_index + 1,
            "point_minute": point_minute,
        }

    def _external_batch_start_target_locked(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        index_keys = ("start_index", "start_point_index")
        point_number_keys = ("start_point_number",)
        has_index = any(key in payload for key in index_keys)
        has_point_number = any(key in payload for key in point_number_keys)
        has_time = any(
            key in payload
            for key in (
                "start_absolute_minute",
                "start_minute",
                "start_absolute_second",
                "start_second",
                "start_time",
            )
        )
        if not has_time:
            raise ValueError(
                "批量输入必须提供起始点时刻 start_time、start_absolute_minute 或 start_absolute_second"
            )

        index_target: Optional[Dict[str, Any]] = None
        if has_index:
            target_index = self._external_integer_field(
                payload,
                index_keys,
                required=True,
                minimum=0,
            )
            index_target = self._external_target_from_index_locked(int(target_index or 0))
        elif has_point_number:
            point_number = self._external_integer_field(
                payload,
                point_number_keys,
                required=True,
                minimum=1,
            )
            index_target = self._external_target_from_index_locked(int(point_number or 1) - 1)

        time_target: Optional[Dict[str, Any]] = None
        if has_time:
            absolute_minute = self._external_history_absolute_minute(payload, "start")
            time_target = self._external_realtime_target_for_time_locked(
                absolute_minute,
                "起始点时刻",
            )

        if index_target is not None and time_target is not None:
            if int(index_target["index"]) != int(time_target["index"]):
                raise ValueError("起始点索引与起始点时刻不一致")
        return time_target or self._external_realtime_target_locked()

    def _external_point_target_locked(
        self,
        payload: Mapping[str, Any],
        expected_index: int,
        expected_absolute_minute: Optional[float] = None,
    ) -> Dict[str, Any]:
        has_index = any(key in payload for key in ("target_index", "index"))
        has_point_number = any(key in payload for key in ("target_point_number", "point_number"))
        has_time = any(
            key in payload
            for key in (
                "target_absolute_minute",
                "target_minute",
                "target_absolute_second",
                "target_second",
                "target_time",
            )
        )
        target = (
            self._external_realtime_target_locked(expected_absolute_minute)
            if expected_absolute_minute is not None
            else self._external_target_from_index_locked(expected_index)
        )
        explicit_targets: List[Dict[str, Any]] = []
        if has_index:
            index = self._external_integer_field(
                payload,
                ("target_index", "index"),
                required=True,
                minimum=0,
            )
            explicit_targets.append(self._external_target_from_index_locked(int(index or 0)))
        if has_point_number:
            point_number = self._external_integer_field(
                payload,
                ("target_point_number", "point_number"),
                required=True,
                minimum=1,
            )
            explicit_targets.append(
                self._external_target_from_index_locked(int(point_number or 1) - 1)
            )
        if has_time:
            absolute_minute = self._external_history_absolute_minute(payload, "target")
            if (
                expected_absolute_minute is not None
                and abs(absolute_minute - expected_absolute_minute) > 1e-9
            ):
                raise ValueError(
                    "多点输入目标时刻不连续："
                    f"期望 {format_number(expected_absolute_minute)} 分钟，"
                    f"收到 {format_number(absolute_minute)} 分钟"
                )
            explicit_targets.append(
                self._external_realtime_target_for_time_locked(
                    absolute_minute,
                    "目标时刻",
                )
            )
        for explicit in explicit_targets:
            if int(explicit["index"]) != expected_index:
                raise ValueError(
                    f"多点输入目标不连续：期望索引 {expected_index}，收到 {explicit['index']}"
                )
            target = explicit
        return target

    def _normalize_external_realtime_request_locked(
        self,
        payload: Mapping[str, Any],
        catalog: Sequence[Mapping[str, str]],
    ) -> Dict[str, Any]:
        has_points = "points" in payload
        has_series = "series" in payload
        if has_points and has_series:
            raise ValueError("points 和 series 不能在同一请求中同时出现")

        current_target = self._external_realtime_target_locked()
        curve_point_count = int(current_target["point_count"])
        operations: List[Dict[str, Any]] = []
        updated_weather_fields: set[str] = set()
        updated_loads: set[str] = set()

        if has_points:
            raw_points = payload.get("points")
            if not isinstance(raw_points, Sequence) or isinstance(raw_points, (str, bytes)):
                raise ValueError("points 必须是非空数组")
            points = list(raw_points)
            if not points:
                raise ValueError("points 必须是非空数组")
            if any(not (type(item) is dict or isinstance(item, Mapping)) for item in points):
                raise ValueError("points 数组项必须是对象")
            contract = self._external_input_contract_locked(
                payload,
                expected_count=len(points),
                batch=True,
            )
            start_target = self._external_batch_start_target_locked(payload)
            start_index = int(start_target["index"])
            curve_step_count = int(contract["curve_step_count"])
            final_index = start_index + (len(points) - 1) * curve_step_count
            if final_index >= curve_point_count:
                raise ValueError(
                    "起始点、point_count 和数据点间隔共同确定的结束时刻超出曲线范围"
                )
            field_signature: Optional[Tuple[Tuple[str, ...], Tuple[str, ...]]] = None
            for offset, raw_item in enumerate(points):
                item = raw_item if (type(raw_item) is dict or isinstance(raw_item, Mapping)) else {}
                expected_index = start_index + offset * curve_step_count
                expected_absolute_minute = (
                    float(start_target["absolute_minute"])
                    + offset * float(contract["point_interval_minutes"])
                )
                target = self._external_point_target_locked(
                    item,
                    expected_index,
                    expected_absolute_minute,
                )
                weather_values = self._normalize_external_realtime_weather(item)
                load_values = self._normalize_external_realtime_loads(item, catalog)
                if not weather_values and not load_values:
                    raise ValueError(f"points[{offset}] 至少提供一个天气量或负荷值")
                signature = (
                    tuple(sorted(weather_values)),
                    tuple(sorted(load_values)),
                )
                if field_signature is None:
                    field_signature = signature
                elif signature != field_signature:
                    raise ValueError("points 中每个数据点的天气字段和负荷字段必须完整且一致")
                updated_weather_fields.update(weather_values)
                updated_loads.update(load_values)
                operations.append(
                    {
                        "target": target,
                        "weather": weather_values,
                        "loads": load_values,
                    }
                )
            return {
                "update_mode": "points",
                "contract": contract,
                "start_target": start_target,
                "operations": operations,
                "updated_weather_fields": sorted(updated_weather_fields),
                "updated_loads": sorted(updated_loads),
            }

        if has_series:
            raw_series = payload.get("series")
            if not (type(raw_series) is dict or isinstance(raw_series, Mapping)):
                raise ValueError("series 必须是对象")
            nested_weather = raw_series.get("weather", {})
            nested_loads = raw_series.get("loads", {})
            if nested_weather in (None, ""):
                nested_weather = {}
            if nested_loads in (None, ""):
                nested_loads = {}
            if not (type(nested_weather) is dict or isinstance(nested_weather, Mapping)):
                raise ValueError("series.weather 必须是对象")
            if not (type(nested_loads) is dict or isinstance(nested_loads, Mapping)):
                raise ValueError("series.loads 必须是对象")

            raw_weather_series: Dict[str, Any] = dict(nested_weather)
            raw_load_series: Dict[str, Any] = dict(nested_loads)
            for raw_key, raw_values in raw_series.items():
                key = str(raw_key)
                if key in {"weather", "loads"}:
                    continue
                if key in EXTERNAL_REALTIME_WEATHER_FIELD_SET:
                    if key in raw_weather_series:
                        raise ValueError(f"series 中重复定义 {key}")
                    raw_weather_series[key] = raw_values
                elif key.startswith("load:"):
                    load_key = key.replace("load:", "", 1)
                    if load_key in raw_load_series:
                        raise ValueError(f"series 中重复定义负荷 {load_key}")
                    raw_load_series[load_key] = raw_values
                else:
                    raise ValueError(f"series 包含不支持的曲线字段: {key}")
            if not raw_weather_series and not raw_load_series:
                raise ValueError("series 至少提供一条天气或负荷曲线")

            declared_count = self._external_integer_field(
                payload,
                ("point_count",),
                required=True,
                minimum=1,
            )
            contract = self._external_input_contract_locked(
                payload,
                expected_count=int(declared_count or 0),
                batch=True,
            )
            point_count = int(contract["point_count"])
            start_target = self._external_batch_start_target_locked(payload)
            start_index = int(start_target["index"])
            curve_step_count = int(contract["curve_step_count"])
            final_index = start_index + (point_count - 1) * curve_step_count
            if final_index >= curve_point_count:
                raise ValueError(
                    "起始点、point_count 和数据点间隔共同确定的结束时刻超出曲线范围"
                )

            weather_series: Dict[str, List[float]] = {}
            for raw_key, raw_values in raw_weather_series.items():
                key = str(raw_key)
                if key not in EXTERNAL_REALTIME_WEATHER_FIELD_SET:
                    raise ValueError(f"series.weather 包含不支持的字段: {key}")
                if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)):
                    raise ValueError(f"series.{key} 必须是数组")
                values = list(raw_values)
                if len(values) != point_count:
                    raise ValueError(
                        f"series.{key} 长度 {len(values)} 与 point_count={point_count} 不一致"
                    )
                weather_series[key] = [
                    self._normalize_external_realtime_weather({key: value})[key]
                    for value in values
                ]
                updated_weather_fields.add(key)

            by_key, by_name = self._external_load_lookup(catalog)
            load_series: Dict[str, List[float]] = {}
            for raw_key, raw_values in raw_load_series.items():
                canonical_key = self._resolve_external_load_key(raw_key, by_key, by_name)
                if canonical_key in load_series:
                    raise ValueError(f"series 中重复定义负荷 {canonical_key}")
                if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)):
                    raise ValueError(f"series 负荷 {canonical_key} 必须是数组")
                values = list(raw_values)
                if len(values) != point_count:
                    raise ValueError(
                        f"series 负荷 {canonical_key} 长度 {len(values)} 与 point_count={point_count} 不一致"
                    )
                normalized_values: List[float] = []
                for value in values:
                    number = self._external_finite_number(canonical_key, value)
                    if number < 0:
                        raise ValueError(f"{canonical_key} 不能小于 0")
                    normalized_values.append(number)
                load_series[canonical_key] = normalized_values
                updated_loads.add(canonical_key)

            for offset in range(point_count):
                absolute_minute = (
                    float(start_target["absolute_minute"])
                    + offset * float(contract["point_interval_minutes"])
                )
                target = self._external_realtime_target_for_time_locked(
                    absolute_minute,
                    f"第 {offset + 1} 个数据点时刻",
                )
                expected_index = start_index + offset * curve_step_count
                if int(target["index"]) != expected_index:
                    raise ValueError(
                        f"第 {offset + 1} 个数据点时刻未映射到预期曲线索引 {expected_index}"
                    )
                operations.append(
                    {
                        "target": target,
                        "weather": {
                            key: values[offset]
                            for key, values in weather_series.items()
                        },
                        "loads": {
                            key: values[offset]
                            for key, values in load_series.items()
                        },
                    }
                )
            return {
                "update_mode": "series",
                "contract": contract,
                "start_target": start_target,
                "operations": operations,
                "updated_weather_fields": sorted(updated_weather_fields),
                "updated_loads": sorted(updated_loads),
            }

        contract = self._external_input_contract_locked(
            payload,
            expected_count=1,
            batch=False,
        )
        weather_values = self._normalize_external_realtime_weather(payload)
        load_values = self._normalize_external_realtime_loads(payload, catalog)
        if not weather_values and not load_values:
            raise ValueError("至少提供一个天气量或负荷值")

        target = current_target
        has_start_time = any(
            key in payload
            for key in (
                "start_absolute_minute",
                "start_minute",
                "start_absolute_second",
                "start_second",
                "start_time",
            )
        )
        if has_start_time:
            start_minute = self._external_history_absolute_minute(payload, "start")
            target = self._external_realtime_target_for_time_locked(
                start_minute,
                "起始点时刻",
            )
        if any(
            key in payload
            for key in (
                "target_absolute_minute",
                "target_minute",
                "target_absolute_second",
                "target_second",
                "target_time",
            )
        ):
            target_minute = self._external_history_absolute_minute(payload, "target")
            explicit_target = self._external_realtime_target_for_time_locked(
                target_minute,
                "目标时刻",
            )
            if has_start_time and int(explicit_target["index"]) != int(target["index"]):
                raise ValueError("单点输入的起始时刻与目标时刻不一致")
            target = explicit_target
        elif any(key in payload for key in ("target_index", "index")):
            target_index = self._external_integer_field(
                payload,
                ("target_index", "index"),
                required=True,
                minimum=0,
            )
            explicit_target = self._external_target_from_index_locked(int(target_index or 0))
            if has_start_time and int(explicit_target["index"]) != int(target["index"]):
                raise ValueError("单点输入的起始时刻与目标索引不一致")
            target = explicit_target
        elif any(key in payload for key in ("target_point_number", "point_number")):
            point_number = self._external_integer_field(
                payload,
                ("target_point_number", "point_number"),
                required=True,
                minimum=1,
            )
            explicit_target = self._external_target_from_index_locked(int(point_number or 1) - 1)
            if has_start_time and int(explicit_target["index"]) != int(target["index"]):
                raise ValueError("单点输入的起始时刻与目标点号不一致")
            target = explicit_target
        target = self._external_point_target_locked(
            payload,
            int(target["index"]),
            float(target["absolute_minute"]),
        )
        return {
            "update_mode": "single_point",
            "contract": contract,
            "start_target": target,
            "operations": [
                {
                    "target": target,
                    "weather": weather_values,
                    "loads": load_values,
                }
            ],
            "updated_weather_fields": sorted(weather_values),
            "updated_loads": sorted(load_values),
        }

    def external_realtime_input_schema(self) -> Dict[str, Any]:
        with self.lock, self.curves_lock:
            target = self._external_realtime_target_locked()
            load_catalog = self._external_load_catalog()
            return {
                **self._external_response_metadata(),
                "endpoint": "/api/external/realtime-inputs",
                "methods": ["GET", "POST"],
                "weather_fields": [
                    {"key": key, "unit": unit}
                    for key, unit in EXTERNAL_REALTIME_WEATHER_FIELDS
                ],
                "loads": load_catalog,
                "target_point": target,
                "curve_contract": {
                    "point_count": target["point_count"],
                    "point_interval_minutes": target["time_step_minutes"],
                    "point_interval_seconds": float(target["time_step_minutes"]) * 60.0,
                    "start_fields": [
                        "start_time",
                        "start_absolute_minute",
                        "start_absolute_second",
                    ],
                    "start_time_is_authoritative": True,
                    "batch_requires_start_time_count_and_interval": True,
                    "interval_must_be_curve_step_multiple": True,
                    "series_lengths_must_equal_point_count": True,
                    "point_fields_must_be_complete_and_consistent": True,
                },
                "request_formats": {
                    "single_point": {
                        "description": "未提供时标时写入下一未求解点；也可显式提供起始时刻",
                        "legacy_without_contract_supported": True,
                    },
                    "multiple_points": {
                        "container": "points",
                        "required": ["start_time", "point_count", "point_interval_seconds|minutes"],
                    },
                    "series": {
                        "container": "series",
                        "required": ["start_time", "point_count", "point_interval_seconds|minutes"],
                    },
                },
                "example_request": {
                    "start_time": target["simu_time"],
                    "point_count": 1,
                    "point_interval_seconds": float(target["time_step_minutes"]) * 60.0,
                    "weather": {
                        "wind_speed_mps": 9.6,
                        "solar_irradiance_w_m2": 650,
                        "air_temp_c": -12,
                        "air_pressure_hpa": 965,
                        "humidity_pct": 70,
                    },
                    "loads": {
                        item["key"]: 100
                        for item in load_catalog[:2]
                    },
                },
                "applies_on_next_power_flow": True,
            }

    def apply_external_realtime_inputs(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        if not (type(payload) is dict or isinstance(payload, Mapping)):
            raise ValueError("请求体必须是 JSON 对象")
        with self._step_lock:
            with self.lock, self.curves_lock:
                catalog = self._external_load_catalog()
                normalized = self._normalize_external_realtime_request_locked(payload, catalog)
                operations = list(normalized["operations"])
                current_target = self._external_realtime_target_locked()
                point_count = int(current_target["point_count"])
                step_minutes = float(current_target["time_step_minutes"])
                weather_points = self.curves.get("weather")
                if not isinstance(weather_points, list):
                    weather_points = []
                    self.curves["weather"] = weather_points
                while len(weather_points) < point_count:
                    index = len(weather_points)
                    weather_points.append({"minute": index * step_minutes, **DEFAULT_WEATHER})

                catalog_by_name: Dict[str, List[str]] = {}
                for item in catalog:
                    catalog_by_name.setdefault(item["dev_name"], []).append(item["key"])
                configured_loads = self.curves.get("loads", {})
                curve_key_by_load: Dict[str, str] = {}
                for canonical_key in normalized["updated_loads"]:
                    _dev_type, dev_name = canonical_key.split(":", 1)
                    curve_key = canonical_key
                    if (type(configured_loads) is dict or isinstance(configured_loads, Mapping)):
                        if canonical_key in configured_loads:
                            curve_key = canonical_key
                        elif dev_name in configured_loads and len(catalog_by_name.get(dev_name, [])) == 1:
                            curve_key = dev_name
                    curve_key_by_load[canonical_key] = curve_key

                load_points_by_key: Dict[str, List[Dict[str, Any]]] = {}
                loads = self.curves.get("loads")
                if not isinstance(loads, dict):
                    loads = {}
                    self.curves["loads"] = loads
                for canonical_key, curve_key in curve_key_by_load.items():
                    points = loads.get(curve_key)
                    if not isinstance(points, list):
                        points = []
                        loads[curve_key] = points
                    while len(points) < point_count:
                        index = len(points)
                        points.append(
                            {
                                "minute": index * step_minutes,
                                "p_kw": DEFAULT_WEATHER["load_kw"],
                            }
                        )
                    load_points_by_key[canonical_key] = points

                point_results: List[Dict[str, Any]] = []
                updated_indices: set[int] = set()
                for operation in operations:
                    target = operation["target"]
                    target_index = int(target["index"])
                    updated_indices.add(target_index)
                    if not isinstance(weather_points[target_index], dict):
                        weather_points[target_index] = {
                            "minute": target_index * step_minutes,
                            **DEFAULT_WEATHER,
                        }
                    weather_points[target_index].setdefault(
                        "minute",
                        target_index * step_minutes,
                    )
                    for key, value in operation["weather"].items():
                        weather_points[target_index][key] = value
                    for canonical_key, value in operation["loads"].items():
                        points = load_points_by_key[canonical_key]
                        if not isinstance(points[target_index], dict):
                            points[target_index] = {
                                "minute": target_index * step_minutes,
                                "p_kw": points[target_index],
                            }
                        points[target_index].setdefault(
                            "minute",
                            target_index * step_minutes,
                        )
                        points[target_index]["p_kw"] = value
                    if normalized["update_mode"] != "series":
                        point_results.append(
                            {
                                "target_absolute_minute": target["absolute_minute"],
                                "target_simu_time": target["simu_time"],
                                "target_index": target_index,
                                "target_point_number": target["point_number"],
                                "weather": operation["weather"],
                                "loads": operation["loads"],
                            }
                        )

                _write_json(self.curves_file, self.curves)
                self._curve_revision += 1
                sorted_indices = sorted(updated_indices)
                start_target = normalized["start_target"]
                end_target = operations[-1]["target"]
                applies_on_next_power_flow = int(current_target["index"]) in updated_indices
                self._append_runtime_log(
                    "外部实时输入",
                    "weather / load curves",
                    "已按时标写入曲线",
                    [
                        f"输入模式 {normalized['update_mode']}，起始时刻 {start_target['simu_time']}，结束时刻 {end_target['simu_time']}",
                        f"数据点 {normalized['contract']['point_count']} 个，间隔 {format_number(normalized['contract']['point_interval_seconds'])} 秒，更新曲线点 {len(sorted_indices)} 个",
                        "天气字段 " + ("，".join(normalized["updated_weather_fields"]) or "未更新"),
                        "负荷字段 " + ("，".join(normalized["updated_loads"]) or "未更新"),
                        "已更新运行曲线；潮流后台将在对应仿真时刻读取，接口未主动推进仿真时钟",
                    ],
                    level="ok",
                    simu_time=str(start_target["simu_time"]),
                )
                legacy_operation = operations[0]
                legacy_target = legacy_operation["target"]
                return {
                    **self._external_response_metadata(),
                    "update_mode": normalized["update_mode"],
                    "input_point_count": normalized["contract"]["point_count"],
                    "point_interval_minutes": normalized["contract"]["point_interval_minutes"],
                    "point_interval_seconds": normalized["contract"]["point_interval_seconds"],
                    "curve_step_count": normalized["contract"]["curve_step_count"],
                    "start_absolute_minute": start_target["absolute_minute"],
                    "start_simu_time": start_target["simu_time"],
                    "start_index": start_target["index"],
                    "end_absolute_minute": end_target["absolute_minute"],
                    "end_simu_time": end_target["simu_time"],
                    "end_index": end_target["index"],
                    "target_absolute_minute": legacy_target["absolute_minute"],
                    "target_simu_time": legacy_target["simu_time"],
                    "target_index": legacy_target["index"],
                    "target_point_number": legacy_target["point_number"],
                    "target_curve_minute": legacy_target["point_minute"],
                    "weather": legacy_operation["weather"] if normalized["update_mode"] == "single_point" else {},
                    "loads": legacy_operation["loads"] if normalized["update_mode"] == "single_point" else {},
                    "point_results": point_results,
                    "updated_indices": sorted_indices,
                    "updated_point_numbers": [index + 1 for index in sorted_indices],
                    "updated_point_count": len(sorted_indices),
                    "updated_weather_fields": normalized["updated_weather_fields"],
                    "updated_loads": normalized["updated_loads"],
                    "covers_full_curve": bool(
                        int(start_target["index"]) == 0
                        and int(normalized["contract"]["curve_step_count"]) == 1
                        and int(normalized["contract"]["point_count"]) == point_count
                    ),
                    "curve_revision": self._curve_revision,
                    "applies_on_next_power_flow": applies_on_next_power_flow,
                    "applies_to_power_flow_backend": True,
                    "next_power_flow_target": current_target,
                    "curve_boundary": self.curve_boundary(),
                }

    def control_clock(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self.lock:
            action = str(payload.get("action", "")).lower()
            previous_state = self.clock.state
            previous_absolute_minute = float(self.clock.absolute_minute)
            if "step_seconds" in payload:
                step_seconds = float(_to_float(payload.get("step_seconds"), self.clock.step_minutes * 60.0) or 0.0)
                self.clock.step_minutes = max(1e-9, step_seconds / 60.0)
            if "step_minutes" in payload:
                self.clock.step_minutes = max(
                    1e-9,
                    float(_to_float(payload.get("step_minutes"), self.clock.step_minutes) or self.clock.step_minutes),
                )
            requested_absolute_minute: Optional[float] = None
            if "absolute_second" in payload or "second" in payload:
                second = float(
                    _to_float(payload.get("absolute_second", payload.get("second")), self.clock.absolute_minute * 60.0)
                    or 0.0
                )
                requested_absolute_minute = max(0.0, second / 60.0)
            elif "minute" in payload:
                requested_absolute_minute = max(
                    0.0,
                    float(_to_float(payload.get("minute"), self.clock.minute) or 0.0),
                )
            if "speed" in payload:
                self.clock.speed = _nearest_clock_speed(payload.get("speed"))
            starts_new_lifecycle = action == "start" and (
                previous_state == "stopped"
                or (
                    requested_absolute_minute is not None
                    and (
                        requested_absolute_minute <= 1e-9
                        or requested_absolute_minute < previous_absolute_minute - 1e-9
                    )
                )
            )
            time_reset_requested = bool(
                requested_absolute_minute is not None
                and (
                    requested_absolute_minute <= 1e-9
                    or requested_absolute_minute < previous_absolute_minute - 1e-9
                )
            )
            remove_automatic_command_history = bool(
                self.clear_commands_on_start_and_reset
                and (starts_new_lifecycle or action == "stop" or time_reset_requested)
            )
            commands_cleared = False
            if remove_automatic_command_history:
                cleared = self._remove_automatic_command_history_for_restart()
                commands_cleared = True
                if cleared["entries"]:
                    self._append_runtime_log(
                        "控制指令",
                        "仿真时钟",
                        "自动指令已清空",
                        [
                            f"模拟台重启或归零前清空自动指令记录 {cleared['entries']} 条",
                            (
                                f"涉及遥控 {cleared['remote_controls']} 个控制点，"
                                f"遥调 {cleared['remote_adjustments']} 个控制点"
                            ),
                            "人工指令继续保持，人工界面修改不受影响",
                        ],
                        level="ok",
                        simu_time=minute_to_time(self.clock.minute),
                    )
            elif starts_new_lifecycle or action == "stop" or time_reset_requested:
                cleared = self._clear_automatic_commands_for_simulation_restart()
                if cleared["entries"]:
                    self._write_command_history()
                    self._append_runtime_log(
                        "控制指令",
                        "仿真时钟",
                        "自动指令已清空",
                        [
                            f"新仿真生命周期启动前清空自动指令记录 {cleared['entries']} 条",
                            (
                                f"涉及遥控 {cleared['remote_controls']} 个控制点，"
                                f"遥调 {cleared['remote_adjustments']} 个控制点"
                            ),
                            "人工指令继续保持，直至人工退出",
                        ],
                        level="ok",
                        simu_time=minute_to_time(self.clock.minute),
                    )
            if requested_absolute_minute is not None:
                self.clock.absolute_minute = requested_absolute_minute
                self.clock.minute = requested_absolute_minute % 1440.0
            history_reset_requested = bool(
                starts_new_lifecycle
                or action == "stop"
                or time_reset_requested
            )
            should_reset_storage_soc = False
            if time_reset_requested and not starts_new_lifecycle:
                self.clock.step_count = 0
                should_reset_storage_soc = True
            if action == "start":
                if starts_new_lifecycle:
                    self.clock.run_id += 1
                    self.clock.step_count = 0
                    should_reset_storage_soc = True
                self.clock.state = "running"
            elif action == "pause":
                self.clock.state = "paused"
            elif action == "stop":
                self.clock.state = "stopped"
                self.clock.absolute_minute = 0.0
                self.clock.minute = 0.0
                self.clock.step_count = 0
                should_reset_storage_soc = True
            elif action in ("faster", "speed_up"):
                self.clock.speed = _next_clock_speed(self.clock.speed)
            elif action in ("slower", "speed_down"):
                self.clock.speed = _previous_clock_speed(self.clock.speed)
            effective_step = _effective_clock_step(self.clock.step_minutes, self.clock.speed)
            if requested_absolute_minute is not None or action == "stop":
                self.clock.absolute_minute = _align_minute_to_step(self.clock.absolute_minute, effective_step)
            self.clock.minute = self.clock.absolute_minute % 1440.0
            if should_reset_storage_soc:
                self._reset_storage_soc_to_initial()
                self._reset_hydrogen_storage_state_to_initial()
            if history_reset_requested:
                self._invalidate_automatic_runtime_state_for_simulation_reset()
            if action in ("start", "stop") or commands_cleared or time_reset_requested:
                self._materialize_active_control_commands(self.clock.absolute_minute, persist=True)
            if action == "step":
                return self.step(advance_minutes=effective_step)["clock"]
            self.clock.updated_at = time.time()
            return self.clock.as_dict()

    @staticmethod
    def _external_book_signature_payload(book: EBook) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = []
        for block_name, block in book.data.items():
            headers = list(getattr(block, "header_list", []) or [])
            blocks.append(
                {
                    "name": str(block_name),
                    "headers": headers,
                    "rows": [
                        [_json_scalar(row.get(header, "")) for header in headers]
                        for row in getattr(block, "data", [])
                    ],
                }
            )
        return blocks

    def external_model_version(self) -> Dict[str, Any]:
        """Return a cached content version for every external API response."""
        snapshot = self.definition_snapshot
        cached = getattr(self, "_external_model_version_cache", None)
        if isinstance(cached, tuple) and len(cached) == 2 and cached[0] is snapshot:
            return dict(cached[1])
        canonical = json.dumps(
            {
                "model": self._external_book_signature_payload(snapshot.model_book),
                "control": self._external_book_signature_payload(snapshot.dev_define_book),
                "measurement": [list(row) for row in snapshot.measurement_rows],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        version = {
            "schema_version": 1,
            "revision": int(snapshot.revision),
            "signature": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "algorithm": "sha256",
        }
        self._external_model_version_cache = (snapshot, version)
        return dict(version)

    def _external_response_metadata(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "model_version": self.external_model_version(),
            **self._api_time_payload(),
        }

    @staticmethod
    def _external_names_signature(groups: Mapping[str, Sequence[str]]) -> str:
        canonical = json.dumps(
            {str(key): [str(name) for name in names] for key, names in groups.items()},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _external_update_time_fields(self, time_payload: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "updated_wall_time": time_payload.get("wall_time", "--"),
            "updated_simu_time": time_payload.get("simu_time", time_payload.get("time", "--")),
            "updated_absolute_minute": time_payload.get("absolute_minute"),
        }

    def _compact_external_value_item(
        self,
        item: Mapping[str, Any],
        time_payload: Mapping[str, Any],
        *,
        include_found: bool = False,
        include_valid: bool = False,
        include_active: bool = False,
    ) -> Dict[str, Any]:
        row: Dict[str, Any] = {
            "name": str(item.get("name", "")),
            "value": _json_scalar(item.get("value")),
            "updated_wall_time": item.get("updated_wall_time", time_payload.get("wall_time", "--")),
            "updated_simu_time": item.get("updated_simu_time", time_payload.get("simu_time", time_payload.get("time", "--"))),
            "updated_absolute_minute": _json_scalar(item.get("updated_absolute_minute", time_payload.get("absolute_minute"))),
        }
        if include_found or "found" in item:
            row["found"] = bool(item.get("found", True))
        if include_valid or "valid" in item:
            row["valid"] = int(_to_float(item.get("valid"), 0) or 0)
        if include_active or "active" in item:
            row["active"] = bool(item.get("active", False))
            row["expires_at_absolute_minute"] = _json_scalar(item.get("expires_at_absolute_minute"))
            row["command_origin"] = str(item.get("command_origin", ""))
        return row

    @staticmethod
    def _external_unique_items(
        items: Sequence[Mapping[str, Any]],
        discriminator: str,
        expected: str,
    ) -> List[Mapping[str, Any]]:
        selected: List[Mapping[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            if str(item.get(discriminator, "")) != expected:
                continue
            name = str(item.get("name", "")).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            selected.append(item)
        return selected

    def _external_telemetry_groups(
        self,
    ) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]:
        items = self._external_telemetry_catalog_items()
        return (
            self._external_unique_items(items, "point_type", "YC"),
            self._external_unique_items(items, "point_type", "YX"),
        )

    def _external_telemetry_catalog_items(self) -> List[Dict[str, Any]]:
        current_items = self._latest_telemetry_items()
        current_by_name = {
            str(item.get("name", "")): item
            for item in current_items
            if str(item.get("name", ""))
        }
        catalog: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for raw_row in self.definition_snapshot.measurement_rows:
            row = dict(zip(MEAS_HEADER, raw_row))
            name = str(row.get("name", "")).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            current = current_by_name.get(name, {})
            is_signal = self._is_signal_measurement_row(row)
            catalog.append(
                {
                    "name": name,
                    "point_type": "YX" if is_signal else "YC",
                    "category": "遥信" if is_signal else "遥测",
                    "dev_type": str(row.get("dev_type", "")),
                    "dev_name": str(row.get("dev_name", "")),
                    "meas_type": str(row.get("meas_type", "")),
                    "value": _json_scalar(current.get("value", row.get("value"))),
                    "valid": int(_to_float(current.get("valid", row.get("valid")), 0) or 0),
                    "weight": _json_scalar(current.get("weight", row.get("weight", ""))),
                }
            )
        for item in current_items:
            name = str(item.get("name", "")).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            catalog.append(dict(item))
        return catalog

    @staticmethod
    def _external_topology_fields(parameters: Mapping[str, Any]) -> Dict[str, Any]:
        topology: Dict[str, Any] = {}
        for raw_name, value in parameters.items():
            name = str(raw_name)
            lower = name.casefold()
            if (
                lower == "node"
                or lower.endswith("_node")
                or re.fullmatch(r"idx_.+_t[12]", lower)
            ):
                topology[name] = _json_scalar(value)
        return topology

    def external_device_information(self) -> Dict[str, Any]:
        """Return physical definitions enriched with topology, state, measurements and controls."""
        snapshot = self.definition_snapshot
        model_book = snapshot.model_book
        runtime_devices = {
            (str(item.get("dev_type", "")), str(item.get("dev_name", ""))): item
            for item in self.devices()
        }
        runtime_states = {
            (str(item.get("dev_type", "")), str(item.get("dev_name", ""))): item
            for item in self.device_states()
        }
        telemetry_by_device: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for item in self._latest_telemetry_items():
            key = (str(item.get("dev_type", "")), str(item.get("dev_name", "")))
            name = str(item.get("name", "")).strip()
            if key[0] and key[1] and name:
                telemetry_by_device.setdefault(key, {})[name] = _json_scalar(item.get("value"))
        for raw_row in snapshot.measurement_rows:
            row = dict(zip(MEAS_HEADER, raw_row))
            key = (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
            name = str(row.get("name", "")).strip()
            if key[0] and key[1] and name:
                telemetry_by_device.setdefault(key, {}).setdefault(name, _json_scalar(row.get("value")))
        controls_by_device: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for item in self._latest_control_value_items():
            key = (str(item.get("dev_type", "")), str(item.get("dev_name", "")))
            name = str(item.get("name", "")).strip()
            if key[0] and key[1] and name:
                controls_by_device.setdefault(key, {})[name] = _json_scalar(item.get("value"))

        parameter_links = (
            ("ACWindGen", "ACGenerator", "idx_acgenerator"),
            ("DCWindGen", "DCGenerator", "idx_dcgenerator"),
            ("ACPVGen", "ACGenerator", "idx_acgenerator"),
            ("DCPVGen", "DCGenerator", "idx_dcgenerator"),
            ("ACStorageGen", "ACGenerator", "idx_acgenerator"),
            ("DCStorageGen", "DCGenerator", "idx_dcgenerator"),
        )
        linked_parameters: Dict[Tuple[str, str], Dict[str, List[Dict[str, Any]]]] = {}
        for block_name, parent_type, index_field in parameter_links:
            parent_block = model_book.data.get(parent_type)
            parent_by_idx = {
                str(row.get("idx", "")): str(row.get("name", "")).strip()
                for row in getattr(parent_block, "data", [])
                if str(row.get("idx", "")) and str(row.get("name", "")).strip()
            }
            parameter_block = model_book.data.get(block_name)
            headers = list(getattr(parameter_block, "header_list", []) or [])
            for row in getattr(parameter_block, "data", []):
                parent_name = parent_by_idx.get(str(row.get(index_field, "")))
                if not parent_name:
                    continue
                linked_parameters.setdefault((parent_type, parent_name), {}).setdefault(block_name, []).append(
                    {header: _json_scalar(row.get(header, "")) for header in headers}
                )

        parameter_block_names = {item[0] for item in parameter_links}
        devices: List[Dict[str, Any]] = []
        device_keys: set[Tuple[str, str]] = set()
        connections: List[Dict[str, Any]] = []
        nodes: List[Dict[str, Any]] = []

        def append_device(dev_type: str, dev_name: str, parameters: Mapping[str, Any]) -> None:
            key = (dev_type, dev_name)
            if not dev_type or not dev_name or key in device_keys:
                return
            device_keys.add(key)
            runtime = runtime_devices.get(key, {})
            runtime_state = runtime_states.get(key, {})
            topology = self._external_topology_fields(parameters)
            state: Dict[str, Any] = {
                "run_stat": int(
                    _to_float(
                        runtime_state.get("run_stat", runtime.get("run_stat", parameters.get("run_stat", 1))),
                        1,
                    )
                    or 0
                ),
                "dead_island": bool(runtime_state.get("dead_island", False)),
            }
            if "status" in parameters or "Switch" in dev_type or "Break" in dev_type or "Valve" in dev_type:
                state["status"] = int(_to_float(runtime.get("status", parameters.get("status", 1)), 1) or 0)
            mode = runtime.get("mode") or parameters.get("control_type") or parameters.get("mode")
            if mode not in (None, ""):
                state["mode"] = str(mode)
            if runtime.get("soc_curr", "") != "":
                state["soc"] = _json_scalar(runtime.get("soc_curr"))
            device_id = f"{dev_type}.{dev_name}"
            devices.append(
                {
                    "id": device_id,
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "topology": topology,
                    "parameters": {str(name): _json_scalar(value) for name, value in parameters.items()},
                    "parameter_blocks": linked_parameters.get(key, {}),
                    "state": state,
                    "values": telemetry_by_device.get(key, {}),
                    "control_values": controls_by_device.get(key, {}),
                }
            )
            if topology:
                connections.append({"device_id": device_id, "terminals": topology})
            if dev_type in {"ACNode", "DCNode"}:
                nodes.append(
                    {
                        "device_id": device_id,
                        "network": "AC" if dev_type == "ACNode" else "DC",
                        "idx": _json_scalar(parameters.get("idx")),
                        "name": dev_name,
                    }
                )

        for block_name, block in model_book.data.items():
            if block_name in parameter_block_names or block_name in {"Model", "PowerBase", "basevoltage"}:
                continue
            headers = list(getattr(block, "header_list", []) or [])
            if "name" not in headers:
                continue
            physical_block = (
                "run_stat" in headers
                or block_name in {"ACNode", "DCNode"}
                or any(self._external_topology_fields({header: "" for header in headers}))
            )
            if not physical_block:
                continue
            for row in getattr(block, "data", []):
                name = str(row.get("name", "")).strip()
                if name:
                    append_device(
                        str(block_name),
                        name,
                        {header: row.get(header, "") for header in headers},
                    )

        for key, runtime in runtime_devices.items():
            if key in device_keys:
                continue
            parameters = runtime.get("raw", {})
            append_device(key[0], key[1], parameters if (type(parameters) is dict or isinstance(parameters, Mapping)) else {})

        devices.sort(key=lambda item: (str(item.get("dev_type", "")), str(item.get("dev_name", ""))))
        return {
            **self._external_response_metadata(),
            "device_count": len(devices),
            "devices": devices,
            "topology": {
                "nodes": nodes,
                "connections": connections,
            },
        }

    def external_telemetry_names(self) -> Dict[str, Any]:
        telemetry, signals = self._external_telemetry_groups()
        telemetry_names = [str(item.get("name", "")) for item in telemetry]
        signal_names = [str(item.get("name", "")) for item in signals]
        signature = self._external_names_signature(
            {
                "telemetry_names": telemetry_names,
                "signal_names": signal_names,
            }
        )
        return {
            **self._external_response_metadata(),
            "definition_signature": signature,
            "telemetry_count": len(telemetry_names),
            "signal_count": len(signal_names),
            "telemetry_names": telemetry_names,
            "signal_names": signal_names,
            "yc_names": telemetry_names,
            "yx_names": signal_names,
        }

    def external_telemetry_frame(self) -> Dict[str, Any]:
        telemetry, signals = self._external_telemetry_groups()
        telemetry_names = [str(item.get("name", "")) for item in telemetry]
        signal_names = [str(item.get("name", "")) for item in signals]
        return {
            **self._external_response_metadata(),
            "definition_signature": self._external_names_signature(
                {
                    "telemetry_names": telemetry_names,
                    "signal_names": signal_names,
                }
            ),
            "telemetry_count": len(telemetry),
            "signal_count": len(signals),
            "telemetry_values": [_json_scalar(item.get("value")) for item in telemetry],
            "signal_values": [_json_scalar(item.get("value")) for item in signals],
            "telemetry_valid": [int(_to_float(item.get("valid"), 0) or 0) for item in telemetry],
            "signal_valid": [int(_to_float(item.get("valid"), 0) or 0) for item in signals],
            "yc_values": [_json_scalar(item.get("value")) for item in telemetry],
            "yx_values": [_json_scalar(item.get("value")) for item in signals],
        }

    def selected_external_telemetry_frame(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        telemetry_names = self._name_list_from_payload(
            payload,
            ("telemetry", "telemetries", "telemetry_names", "yc", "yc_names", "remote_measurements"),
        )
        signal_names = self._name_list_from_payload(
            payload,
            ("signals", "signal_names", "yx", "yx_names", "statuses", "status_names", "remote_signals"),
        )
        telemetry, signals = self._external_telemetry_groups()
        telemetry_index = {str(item.get("name", "")): item for item in telemetry}
        signal_index = {str(item.get("name", "")): item for item in signals}

        def selected_rows(
            names: Sequence[str],
            index: Mapping[str, Mapping[str, Any]],
        ) -> List[Dict[str, Any]]:
            rows: List[Dict[str, Any]] = []
            for name in names:
                item = index.get(name)
                rows.append(
                    {
                        "name": name,
                        "value": _json_scalar(item.get("value")) if item is not None else None,
                        "valid": int(_to_float(item.get("valid"), 0) or 0) if item is not None else 0,
                        "found": item is not None,
                    }
                )
            return rows

        telemetry_rows = selected_rows(telemetry_names, telemetry_index)
        signal_rows = selected_rows(signal_names, signal_index)
        return {
            **self._external_response_metadata(),
            "telemetry_names": telemetry_names,
            "signal_names": signal_names,
            "telemetry_values": [item["value"] for item in telemetry_rows],
            "signal_values": [item["value"] for item in signal_rows],
            "telemetry_valid": [item["valid"] for item in telemetry_rows],
            "signal_valid": [item["valid"] for item in signal_rows],
            "telemetry_found": [item["found"] for item in telemetry_rows],
            "signal_found": [item["found"] for item in signal_rows],
            "yc_names": telemetry_names,
            "yx_names": signal_names,
            "yc_values": [item["value"] for item in telemetry_rows],
            "yx_values": [item["value"] for item in signal_rows],
            "missing": {
                "telemetry": [item["name"] for item in telemetry_rows if not item["found"]],
                "signals": [item["name"] for item in signal_rows if not item["found"]],
            },
        }

    @staticmethod
    def _external_history_absolute_minute(payload: Mapping[str, Any], prefix: str) -> float:
        minute_keys = (
            f"{prefix}_absolute_minute",
            f"{prefix}_minute",
        )
        for key in minute_keys:
            if key not in payload:
                continue
            value = _to_float(payload.get(key), None)
            if value is None or not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be a non-negative number")
            return float(value)

        second_keys = (
            f"{prefix}_absolute_second",
            f"{prefix}_second",
        )
        for key in second_keys:
            if key not in payload:
                continue
            value = _to_float(payload.get(key), None)
            if value is None or not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be a non-negative number")
            return float(value) / 60.0

        key = f"{prefix}_time"
        raw_value = payload.get(key)
        if raw_value is None or str(raw_value).strip() == "":
            raise ValueError(f"{key} is required")
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            value = float(raw_value)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be a non-negative absolute minute or HH:MM[:SS]")
            return value

        text = str(raw_value).strip()
        numeric = _to_float(text, None)
        if numeric is not None and ":" not in text:
            if not math.isfinite(numeric) or numeric < 0:
                raise ValueError(f"{key} must be a non-negative absolute minute or HH:MM[:SS]")
            return float(numeric)
        match = re.fullmatch(r"(?:(\d+)\+)?(\d+):(\d{1,2})(?::(\d{1,2}(?:\.\d+)?))?", text)
        if not match:
            raise ValueError(f"{key} must use HH:MM[:SS] or day+HH:MM[:SS]")
        day_text, hour_text, minute_text, second_text = match.groups()
        day = int(day_text or 0)
        hour = int(hour_text)
        minute_part = int(minute_text)
        second = float(second_text or 0.0)
        if minute_part >= 60 or second >= 60 or (day_text is not None and hour >= 24):
            raise ValueError(f"{key} is outside the valid clock range")
        return day * 1440.0 + hour * 60.0 + minute_part + second / 60.0

    @staticmethod
    def _external_history_interval_seconds(payload: Mapping[str, Any]) -> float:
        raw_value: Any = None
        for key in (
            "interval_seconds",
            "data_interval_seconds",
            "sample_interval_seconds",
            "data_interval",
        ):
            if key in payload:
                raw_value = payload.get(key)
                break
        value = _to_float(raw_value, None)
        if value is None or not math.isfinite(value) or value <= 0:
            raise ValueError("interval_seconds must be a positive number")
        return float(value)

    def _command_entry_time_info(self, entry: Mapping[str, Any]) -> Dict[str, Any]:
        absolute_minute = _to_float(entry.get("received_absolute_minute", entry.get("issued_absolute_minute")), None)
        return {
            "wall_time": entry.get("received_wall_time", entry.get("time", "")) or "--",
            "simu_time": entry.get("received_simu_time") or (minute_to_time(absolute_minute) if absolute_minute is not None else "--"),
            "absolute_minute": absolute_minute,
            "expires_at_absolute_minute": _to_float(entry.get("expires_at_absolute_minute"), None),
            "source": entry.get("source", ""),
            "command_origin": _command_origin(entry),
        }

    def _latest_active_control_update(
        self,
        command_kind: str,
        dev_type: str,
        dev_name: str,
        field_name: str,
    ) -> Dict[str, Any]:
        override_key = (command_kind, dev_type, dev_name, field_name)
        if override_key in self._simulator_ui_control_override_keys():
            return {
                "wall_time": "--",
                "simu_time": "--",
                "absolute_minute": None,
                "expires_at_absolute_minute": None,
                "source": "simulator-ui",
                "command_origin": "simulator-ui",
                "active": True,
            }
        for entry in reversed(self._active_control_command_entries(self.clock.absolute_minute)):
            normalized = entry.get("normalized", {})
            if not (type(normalized) is dict or isinstance(normalized, Mapping)):
                continue
            if command_kind == "remote_adjustment":
                items = normalized.get("set_values", [])
                if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
                    continue
                for item in items:
                    if (
                        (type(item) is dict or isinstance(item, Mapping))
                        and str(item.get("dev_type", "")) == dev_type
                        and str(item.get("dev_name", "")) == dev_name
                        and str(item.get("set_type", "")) == field_name
                    ):
                        return self._command_entry_time_info(entry) | {"active": True}
                continue
            items = normalized.get("run_status", [])
            if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
                continue
            for item in items:
                if not (type(item) is dict or isinstance(item, Mapping)):
                    continue
                if str(item.get("dev_type", "")) != dev_type or str(item.get("dev_name", "")) != dev_name:
                    continue
                if field_name == "status" and "status" in item:
                    return self._command_entry_time_info(entry) | {"active": True}
                if field_name == "run_stat" and item.get("run_stat", "") != "":
                    return self._command_entry_time_info(entry) | {"active": True}
        return {
            "wall_time": "--",
            "simu_time": "--",
            "absolute_minute": None,
            "expires_at_absolute_minute": None,
            "source": "",
            "command_origin": "",
            "active": False,
        }

    def _control_definition_rows(self, block_name: str) -> List[Dict[str, Any]]:
        book = self.control_book if block_name in self.control_book.data else self.source_stat_book
        block = book.data.get(block_name)
        if block is None:
            return []
        return [
            {header: row.get(header, "") for header in block.header_list}
            for row in getattr(block, "data", [])
        ]

    def _latest_control_value_items(self) -> List[Dict[str, Any]]:
        run_stats, _cb_status, set_values, _soc_values = self._stat_maps()
        cb_status_set = self._closed_status_set_map()
        items: List[Dict[str, Any]] = []

        for row in self._control_definition_rows("RunStat"):
            dev_type = str(row.get("dev_type", ""))
            dev_name = _dev_name(row)
            if not dev_type or not dev_name:
                continue
            value = int(_to_float(run_stats.get((dev_type, dev_name), row.get("run_stat", 0)), 0) or 0)
            update = self._latest_active_control_update("remote_control", dev_type, dev_name, "run_stat")
            items.append(
                {
                    "name": automatic_point_name(dev_type, dev_name, "run_stat"),
                    "command_kind": "remote_control",
                    "category": "遥控",
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "control_type": "run_stat",
                    "value": value,
                    "text": "投入" if value else "退出",
                    "updated_wall_time": update["wall_time"],
                    "updated_simu_time": update["simu_time"],
                    "updated_absolute_minute": update["absolute_minute"],
                    "expires_at_absolute_minute": update["expires_at_absolute_minute"],
                    "active": update["active"],
                    "source": update["source"],
                    "command_origin": update["command_origin"],
                }
            )

        for row in self._control_definition_rows("CbOpenStat"):
            dev_type = str(row.get("dev_type", ""))
            dev_name = _dev_name(row)
            if not dev_type or not dev_name:
                continue
            value = int(
                _to_float(
                    cb_status_set.get(
                        (dev_type, dev_name),
                        simu_loop.closed_status_set_value(row, 0),
                    ),
                    0,
                )
                or 0
            )
            update = self._latest_active_control_update("remote_control", dev_type, dev_name, "status")
            items.append(
                {
                    "name": automatic_point_name(dev_type, dev_name, "status"),
                    "command_kind": "remote_control",
                    "category": "遥控",
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "control_type": "status",
                    "value": value,
                    "text": "闭合" if value else "断开",
                    "updated_wall_time": update["wall_time"],
                    "updated_simu_time": update["simu_time"],
                    "updated_absolute_minute": update["absolute_minute"],
                    "expires_at_absolute_minute": update["expires_at_absolute_minute"],
                    "active": update["active"],
                    "source": update["source"],
                    "command_origin": update["command_origin"],
                }
            )

        for row in self._control_definition_rows("SetValue"):
            dev_type = str(row.get("dev_type", ""))
            dev_name = _dev_name(row)
            set_type = str(row.get("set_type", ""))
            if not dev_type or not dev_name or not set_type:
                continue
            value = set_values.get((dev_type, dev_name), {}).get(set_type, row.get("set_value", ""))
            update = self._latest_active_control_update("remote_adjustment", dev_type, dev_name, set_type)
            items.append(
                {
                    "name": automatic_point_name(dev_type, dev_name, set_type),
                    "command_kind": "remote_adjustment",
                    "category": "遥调",
                    "dev_type": dev_type,
                    "dev_name": dev_name,
                    "set_type": set_type,
                    "value": _json_scalar(value),
                    "updated_wall_time": update["wall_time"],
                    "updated_simu_time": update["simu_time"],
                    "updated_absolute_minute": update["absolute_minute"],
                    "expires_at_absolute_minute": update["expires_at_absolute_minute"],
                    "active": update["active"],
                    "source": update["source"],
                    "command_origin": update["command_origin"],
                }
            )

        return items

    def _external_control_groups(
        self,
    ) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]:
        items = self._latest_control_value_items()
        return (
            self._external_unique_items(items, "command_kind", "remote_adjustment"),
            self._external_unique_items(items, "command_kind", "remote_control"),
        )

    def external_control_names(self) -> Dict[str, Any]:
        adjustments, controls = self._external_control_groups()
        adjustment_names = [str(item.get("name", "")) for item in adjustments]
        control_names = [str(item.get("name", "")) for item in controls]
        signature = self._external_names_signature(
            {
                "remote_adjustment_names": adjustment_names,
                "remote_control_names": control_names,
            }
        )
        return {
            **self._external_response_metadata(),
            "definition_signature": signature,
            "remote_adjustment_count": len(adjustment_names),
            "remote_control_count": len(control_names),
            "remote_adjustment_names": adjustment_names,
            "remote_control_names": control_names,
            "yt_names": adjustment_names,
            "yk_names": control_names,
        }

    def latest_control_values(self) -> Dict[str, Any]:
        """Return compact current remote-control and remote-adjustment values for external clients."""
        time_payload = self._api_time_payload()
        items = [
            self._compact_external_value_item(item, time_payload, include_active=True)
            for item in self._latest_control_value_items()
        ]
        return {
            **self._external_response_metadata(),
            "items": items,
            "values": {item["name"]: item.get("value") for item in items},
        }

    def _external_control_items(self, payload: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        collected: List[Mapping[str, Any]] = []
        for key in ("commands", "items", "controls"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                collected.extend(item for item in value if (type(item) is dict or isinstance(item, Mapping)))
        values = payload.get("values")
        if (type(values) is dict or isinstance(values, Mapping)):
            collected.extend({"name": name, "value": value} for name, value in values.items())
        if not collected and any(key in payload for key in ("name", "dev_type", "dev_name", "set_type", "control_type")):
            collected.append(payload)
        return collected

    def _control_name_index(self) -> Dict[str, Mapping[str, Any]]:
        return {
            str(item.get("name", "")): item
            for item in self._latest_control_value_items()
            if (type(item) is dict or isinstance(item, Mapping)) and item.get("name")
        }

    def _normalize_external_control_payload(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        run_items: List[Dict[str, Any]] = []
        set_items: List[Dict[str, Any]] = []
        if isinstance(payload.get("run_status"), Sequence) and not isinstance(payload.get("run_status"), (str, bytes)):
            run_items.extend(item for item in payload.get("run_status", []) if (type(item) is dict or isinstance(item, Mapping)))
        if isinstance(payload.get("remote_controls"), Sequence) and not isinstance(payload.get("remote_controls"), (str, bytes)):
            run_items.extend(item for item in payload.get("remote_controls", []) if (type(item) is dict or isinstance(item, Mapping)))
        for key in ("set_values", "setpoints", "remote_adjustments"):
            if isinstance(payload.get(key), Sequence) and not isinstance(payload.get(key), (str, bytes)):
                set_items.extend(item for item in payload.get(key, []) if (type(item) is dict or isinstance(item, Mapping)))

        name_index = self._control_name_index()
        resolved_items: List[Dict[str, Any]] = []
        for item in self._external_control_items(payload):
            raw_name = str(item.get("name", item.get("command_name", item.get("control_name", "")))).strip()
            definition = name_index.get(raw_name, {})
            dev_type = str(item.get("dev_type", item.get("type", definition.get("dev_type", ""))))
            dev_name = str(item.get("dev_name", item.get("device", definition.get("dev_name", ""))))
            value = item.get("value", item.get("set_value", item.get("run_stat", item.get("status", ""))))
            command_kind = str(item.get("command_kind", definition.get("command_kind", ""))).lower()
            control_type = str(item.get("control_type", item.get("meas_type", definition.get("control_type", ""))))
            set_type = str(item.get("set_type", definition.get("set_type", "")))
            if (not dev_type or not dev_name or not (set_type or control_type)) and raw_name:
                parts = raw_name.split(".")
                if len(parts) >= 3:
                    dev_type = dev_type or parts[0]
                    dev_name = dev_name or ".".join(parts[1:-1])
                    tail = parts[-1]
                    if tail in ("run_stat", "status"):
                        control_type = control_type or tail
                    else:
                        set_type = set_type or tail
            if not dev_type or not dev_name:
                continue
            if set_type or command_kind in ("remote_adjustment", "yt", "遥调"):
                if not set_type:
                    continue
                set_items.append({"dev_type": dev_type, "dev_name": dev_name, "set_type": set_type, "set_value": value})
                resolved_items.append(
                    {
                        "name": raw_name or automatic_point_name(dev_type, dev_name, set_type),
                        "value": _json_scalar(value),
                    }
                )
                continue
            field_name = "status" if control_type == "status" else "run_stat"
            run_row: Dict[str, Any] = {"dev_type": dev_type, "dev_name": dev_name}
            run_row[field_name] = value
            run_items.append(run_row)
            resolved_items.append(
                {
                    "name": raw_name or automatic_point_name(dev_type, dev_name, field_name),
                    "value": _json_scalar(value),
                }
            )

        return {"run_status": run_items, "set_values": set_items, "resolved_items": resolved_items}

    def apply_external_control_values(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        if _has_cancel_command_payload(payload):
            source = str(payload.get("source") or "trainee-external-api")
            if not _is_trainee_command_source(source):
                source = f"trainee-{source}"
            result = self.cancel_student_commands(payload | {"source": source}, source=source)
            return {
                **self._external_response_metadata(),
                "cancelled": result["cancelled"],
                "cancelled_items": result["cancelled_items"],
                "control_values": self.latest_control_values(),
            }
        normalized = self._normalize_external_control_payload(payload)
        command_payload: Dict[str, Any] = {
            "run_status": normalized["run_status"],
            "set_values": normalized["set_values"],
        }
        for key in (
            "valid_for_minutes",
            "valid_minutes",
            "valid_for_seconds",
            "expires_at_absolute_minute",
            "expires_at_minute",
            "sent_wall_time",
            "sent_simu_time",
            "sent_absolute_minute",
            "command_origin",
            "commandOrigin",
            "origin",
            "manual_hold",
            "hold_until_cancelled",
        ):
            if key in payload:
                command_payload[key] = payload[key]
        source = str(payload.get("source") or "trainee-external-api")
        if not _is_trainee_command_source(source):
            source = f"trainee-{source}"
        result = self.apply_student_commands(command_payload | {"source": source}, source=source)
        time_payload = self._api_time_payload()
        updated_items = [
            item | self._external_update_time_fields(time_payload)
            for item in normalized["resolved_items"]
        ]
        return {
            **self._external_response_metadata(),
            "accepted": {
                "remote_controls": result.get("run_status", 0),
                "remote_adjustments": result.get("set_values", 0),
                "ignored": result.get("ignored", 0),
            },
            "updated_items": updated_items,
            "control_values": self.latest_control_values(),
        }

    @staticmethod
    def _external_payload_sequence(payload: Mapping[str, Any], keys: Sequence[str]) -> List[Any]:
        for key in keys:
            if key not in payload:
                continue
            value = payload.get(key)
            if value is None:
                return []
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return list(value)
            raise ValueError(f"{key} must be a list")
        return []

    def apply_external_control_frame(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        adjustment_names = [
            str(name).strip()
            for name in self._external_payload_sequence(
                payload,
                ("remote_adjustment_names", "adjustment_names", "yt_names"),
            )
        ]
        adjustment_values = self._external_payload_sequence(
            payload,
            ("remote_adjustment_values", "adjustment_values", "yt_values"),
        )
        control_names = [
            str(name).strip()
            for name in self._external_payload_sequence(
                payload,
                ("remote_control_names", "control_names", "yk_names"),
            )
        ]
        control_values = self._external_payload_sequence(
            payload,
            ("remote_control_values", "control_values", "yk_values"),
        )
        if len(adjustment_names) != len(adjustment_values):
            raise ValueError("remote adjustment name/value list length mismatch")
        if len(control_names) != len(control_values):
            raise ValueError("remote control name/value list length mismatch")

        all_definitions = self._control_name_index()
        adjustment_definitions = {
            name: item
            for name, item in all_definitions.items()
            if str(item.get("command_kind", "")) == "remote_adjustment"
        }
        control_definitions = {
            name: item
            for name, item in all_definitions.items()
            if str(item.get("command_kind", "")) == "remote_control"
        }
        commands: List[Dict[str, Any]] = []
        for name, value in zip(adjustment_names, adjustment_values):
            if name in adjustment_definitions:
                commands.append({"name": name, "value": value})
        for name, value in zip(control_names, control_values):
            if name in control_definitions:
                commands.append({"name": name, "value": value})
        unresolved_count = sum(name not in adjustment_definitions for name in adjustment_names) + sum(
            name not in control_definitions for name in control_names
        )

        delegated_keys = (
            "valid_for_minutes",
            "valid_minutes",
            "valid_for_seconds",
            "expires_at_absolute_minute",
            "expires_at_minute",
            "sent_wall_time",
            "sent_simu_time",
            "sent_absolute_minute",
            "source",
            "command_origin",
            "commandOrigin",
            "origin",
            "manual_hold",
            "hold_until_cancelled",
        )
        if commands:
            applied = self.apply_external_control_values(
                {"commands": commands}
                | {key: payload[key] for key in delegated_keys if key in payload}
            )
            accepted = dict(applied.get("accepted", {}))
            accepted["ignored"] = int(_to_float(accepted.get("ignored"), 0) or 0) + unresolved_count
        else:
            applied = {
                **self._external_response_metadata(),
                "accepted": {
                    "remote_controls": 0,
                    "remote_adjustments": 0,
                    "ignored": len(adjustment_names) + len(control_names),
                },
            }
            accepted = dict(applied["accepted"])

        current = self._control_name_index()

        def results(
            names: Sequence[str],
            values: Sequence[Any],
            definitions: Mapping[str, Mapping[str, Any]],
        ) -> List[Dict[str, Any]]:
            rows: List[Dict[str, Any]] = []
            for name, requested_value in zip(names, values):
                definition = definitions.get(name)
                item = current.get(name, {})
                found = definition is not None
                active = bool(item.get("active", False)) if found else False
                row = {
                    "name": name,
                    "requested_value": _json_scalar(requested_value),
                    "value": _json_scalar(item.get("value")) if found else None,
                    "found": found,
                    "accepted": bool(found and active),
                    "active": active,
                    "reason": "" if found and active else ("unknown control name" if not found else "command not active"),
                }
                if found:
                    row.update(
                        {
                            "updated_wall_time": item.get("updated_wall_time", "--"),
                            "updated_simu_time": item.get("updated_simu_time", "--"),
                            "updated_absolute_minute": _json_scalar(item.get("updated_absolute_minute")),
                            "expires_at_absolute_minute": _json_scalar(item.get("expires_at_absolute_minute")),
                            "command_origin": str(item.get("command_origin", "")),
                        }
                    )
                rows.append(row)
            return rows

        adjustment_results = results(adjustment_names, adjustment_values, adjustment_definitions)
        control_results = results(control_names, control_values, control_definitions)
        return {
            **self._external_response_metadata(),
            "definition_signature": self.external_control_names()["definition_signature"],
            "accepted": accepted,
            "remote_adjustment_results": adjustment_results,
            "remote_control_results": control_results,
            "yt_results": adjustment_results,
            "yk_results": control_results,
        }

    def _apply_manual_runtime_control_overrides_unlocked(
        self,
        items: Sequence[Mapping[str, Any]],
    ) -> None:
        for item in items:
            if item.get("kind") != "device":
                continue
            if item.get("effective") is False:
                continue
            field_name = str(item.get("field", "")).strip().casefold()
            block_name = str(item.get("block_name", "")).strip()
            row_key = item.get("row_key", {})
            if not (type(row_key) is dict or isinstance(row_key, Mapping)):
                continue
            dev_name = str(
                row_key.get("name", item.get("object_name", ""))
            ).strip()
            if not block_name or not dev_name:
                continue
            current_value = item.get("current_value", "")
            if field_name in RUNTIME_CONTROL_STATUS_FIELDS:
                for book in (self.source_stat_book, self.control_book):
                    self._upsert_runtime_status_value(
                        book,
                        block_name,
                        dev_name,
                        field_name,
                        current_value,
                    )
                continue
            set_type = self._runtime_control_set_type(block_name, field_name)
            if set_type is None:
                continue
            for book in (self.source_stat_book, self.control_book):
                self._upsert_runtime_setpoint_value(
                    book,
                    block_name,
                    dev_name,
                    set_type,
                    current_value,
                )

    @staticmethod
    def _runtime_control_set_type(block_name: str, field_name: str) -> Optional[str]:
        normalized_block = str(block_name or "").strip()
        normalized_field = str(field_name or "").strip().casefold()
        if normalized_field in RUNTIME_CONTROL_STATUS_FIELDS:
            return None
        alias = RUNTIME_CONTROL_SETPOINT_ALIASES.get(
            (normalized_block, normalized_field)
        )
        if alias:
            return alias
        if normalized_field in RUNTIME_CONTROL_SETPOINT_FIELDS:
            return normalized_field
        if normalized_field.endswith("_set"):
            return normalized_field
        return None

    @staticmethod
    def _upsert_runtime_setpoint_value(
        book: EBook,
        dev_type: str,
        dev_name: str,
        set_type: str,
        value: Any,
    ) -> None:
        block = _ensure_block(book, "SetValue", STAT_HEADERS["SetValue"])
        row = _find_set_row(block, dev_type, dev_name, set_type)
        if row is None:
            row = {
                "dev_type": dev_type,
                "dev_name": dev_name,
                "set_type": set_type,
                "set_value": "",
            }
            block.data.append(row)
        row["set_value"] = _number_text(value)

    def _sync_runtime_controls_from_device_changes_unlocked(
        self,
        block_name: str,
        row: Mapping[str, Any],
        changes: Mapping[str, Any],
        *,
        priority_override_keys: Optional[set[Tuple[str, str, str, str]]] = None,
    ) -> Optional[Dict[str, Any]]:
        dev_type = str(block_name or "").strip()
        dev_name = str(row.get("name", row.get("dev_name", ""))).strip()
        if not dev_type or not dev_name:
            return None

        requested: Dict[str, Any] = {
            "dev_type": dev_type,
            "dev_name": dev_name,
            "set_values": {},
        }
        changed = False
        for field_name, value in changes.items():
            normalized_field = str(field_name or "").strip().casefold()
            if normalized_field in RUNTIME_CONTROL_STATUS_FIELDS:
                for book in (self.source_stat_book, self.control_book):
                    self._upsert_runtime_status_value(
                        book,
                        dev_type,
                        dev_name,
                        normalized_field,
                        value,
                    )
                requested[normalized_field] = _json_scalar(value)
                changed = True
                continue

            set_type = self._runtime_control_set_type(dev_type, normalized_field)
            if set_type is None:
                continue
            for book in (self.source_stat_book, self.control_book):
                self._upsert_runtime_setpoint_value(
                    book,
                    dev_type,
                    dev_name,
                    set_type,
                    value,
                )
            requested["set_values"][set_type] = _json_scalar(value)
            changed = True

        if not changed:
            return None

        # The source books are the editable baseline. Rebuild the effective
        # runtime book so valid commands and active device faults keep their
        # existing precedence over that baseline.
        self._materialize_active_control_commands(
            self.clock.absolute_minute,
            additional_ui_overrides=priority_override_keys,
        )
        self._apply_device_faults(self.clock.minute, self.clock.absolute_minute)
        run_stats, _cb_status, set_values, _soc_values = self._stat_maps()
        cb_status_set = self._closed_status_set_map()
        key = (dev_type, dev_name)
        effective: Dict[str, Any] = {
            "dev_type": dev_type,
            "dev_name": dev_name,
        }
        if "run_stat" in requested:
            effective["run_stat"] = _json_scalar(
                run_stats.get(key, requested["run_stat"])
            )
        for requested_field in ("status", "closed_status_set"):
            if requested_field in requested:
                effective[requested_field] = _json_scalar(
                    cb_status_set.get(key, requested[requested_field])
                )
        requested_set_values = requested["set_values"]
        if requested_set_values:
            current_set_values = set_values.get(key, {})
            effective["set_values"] = {
                set_type: _json_scalar(
                    current_set_values.get(set_type, requested_value)
                )
                for set_type, requested_value in requested_set_values.items()
            }
        return effective

    def _control_definition_path(self) -> Path:
        for path in (self.source_files.get("control"), self.source_files.get("stat"), self.files["stat"]):
            if path and Path(path).exists():
                return Path(path)
        return self.files["stat"]
