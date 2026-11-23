"""Process manager for the simulator proxy and per-model simulator services."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request

try:
    from .http_common import local_urlopen
except ImportError:  # pragma: no cover - legacy direct-module compatibility.
    from http_common import local_urlopen


HealthResult = tuple[bool, Mapping[str, Any], str]
HealthChecker = Callable[[str, int, str, float], HealthResult]
ClockStateChecker = Callable[[str, int, str, float], str]

CHILD_LOG_MAX_BYTES = 5 * 1024 * 1024
CHILD_LOG_BACKUP_COUNT = 3
DEFAULT_HEALTH_CACHE_TTL_SECONDS = 0.8


def _safe_model_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Model id is required")
    if text in {".", ".."} or any(char in text for char in '<>:"/\\|?*'):
        raise ValueError(f"模型名称无效: {text}")
    return text


def _model_key(value: Any) -> str:
    return str(value or "").strip().casefold()


_SERVICE_HOST_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


def _normalize_service_host(value: Any, default: str = "127.0.0.1") -> str:
    text = str(value if value is not None else default).strip()
    if (
        not text
        or "://" in text
        or "/" in text
        or "\\" in text
        or ":" in text
        or any(char.isspace() for char in text)
        or ".." in text
        or not _SERVICE_HOST_PATTERN.fullmatch(text)
    ):
        raise ValueError("服务地址无效：请输入 IPv4 地址或主机名，不要包含协议、端口或路径")
    return text


def _normalize_service_port(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("服务端口必须是 1-65535 之间的整数")
    text = str(value if value is not None else "").strip()
    if not text.isdigit():
        raise ValueError("服务端口必须是 1-65535 之间的整数")
    port = int(text)
    if not 1 <= port <= 65535:
        raise ValueError("服务端口必须是 1-65535 之间的整数")
    return port


def _read_log_tail(log_path: Path, *, max_lines: int = 8, max_chars: int = 800) -> str:
    """读取子服务日志尾部关键行，便于异常退出时直接向前端透出崩溃原因。"""
    try:
        if not log_path.is_file():
            return ""
        size = log_path.stat().st_size
        read_bytes = min(size, 8192)
        with log_path.open("rb") as fh:
            if size > read_bytes:
                fh.seek(size - read_bytes)
            text = fh.read().decode("utf-8", errors="replace")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""
        tail = " | ".join(lines[-max_lines:])
        return tail[-max_chars:]
    except OSError:
        return ""


def _rotate_log_if_needed(
    log_path: Path,
    *,
    max_bytes: int = CHILD_LOG_MAX_BYTES,
    backup_count: int = CHILD_LOG_BACKUP_COUNT,
) -> None:
    """在启动子服务前按大小轮转历史日志，防止单文件无限膨胀。"""
    try:
        if not log_path.exists() or log_path.stat().st_size < max_bytes:
            return
        for index in range(backup_count, 0, -1):
            src = log_path if index == 1 else log_path.with_name(f"{log_path.name}.{index - 1}")
            dst = log_path.with_name(f"{log_path.name}.{index}")
            if src.exists():
                try:
                    src.replace(dst)
                except OSError:
                    continue
    except OSError:
        return


class SimulatorClusterManager:
    """Own one independently addressable simulator process per source model."""

    REGISTRY_VERSION = 1

    def __init__(
        self,
        *,
        sim_dir: str | Path,
        models_root: str | Path,
        runtime_root: str | Path,
        service_host: str = "127.0.0.1",
        first_service_port: int = 8711,
        compute_interval_seconds: float = 1.0,
        child_no_worker: bool = False,
        noise_std: Optional[float] = None,
        random_seed: Optional[int] = None,
        process_factory: Callable[..., Any] = subprocess.Popen,
        health_checker: Optional[HealthChecker] = None,
        clock_state_checker: Optional[ClockStateChecker] = None,
        port_checker: Optional[Callable[[str, int], bool]] = None,
        startup_timeout_seconds: float = 30.0,
        shutdown_timeout_seconds: float = 8.0,
        poll_interval_seconds: float = 0.1,
        log_dir: Optional[Path] = None,
        health_cache_ttl_seconds: float = DEFAULT_HEALTH_CACHE_TTL_SECONDS,
    ) -> None:
        self.sim_dir = Path(sim_dir).resolve()
        self.models_root = Path(models_root).resolve()
        self.runtime_root = Path(runtime_root).resolve()
        self.service_host = _normalize_service_host(service_host or "127.0.0.1")
        self.first_service_port = max(1, int(first_service_port))
        self.compute_interval_seconds = max(0.1, float(compute_interval_seconds or 1.0))
        self.child_no_worker = bool(child_no_worker)
        self.noise_std = noise_std
        self.random_seed = random_seed
        self.process_factory = process_factory
        self.health_checker = health_checker or self._default_health_checker
        self.clock_state_checker = clock_state_checker or self._default_clock_state_checker
        self.port_checker = port_checker or self._port_is_open
        self.startup_timeout_seconds = max(0.01, float(startup_timeout_seconds))
        self.shutdown_timeout_seconds = max(0.01, float(shutdown_timeout_seconds))
        self.poll_interval_seconds = max(0.001, float(poll_interval_seconds))
        self.health_cache_ttl_seconds = max(0.0, float(health_cache_ttl_seconds))
        self.lock = threading.RLock()
        self._model_op_locks: dict[str, threading.RLock] = {}
        self._health_cache: dict[str, tuple[float, HealthResult]] = {}
        self._inflight_probes: dict[str, threading.Event] = {}
        self._probe_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=8,
            thread_name_prefix="cluster-probe",
        )
        self._models_sync_next_at = 0.0
        self._custom_clock_state_checker = clock_state_checker is not None
        self.models_root.mkdir(parents=True, exist_ok=True)
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.cluster_runtime_dir = self.runtime_root / ".cluster"
        self.cluster_runtime_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir = Path(log_dir).resolve() if log_dir is not None else self.cluster_runtime_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.cluster_runtime_dir / "services.json"
        self._processes: dict[str, Any] = {}
        self._log_handles: dict[str, Any] = {}
        self._states: dict[str, str] = {}
        self._errors: dict[str, str] = {}
        self._adoption_deadlines: dict[str, float] = {}
        self._adoption_next_probe_at: dict[str, float] = {}
        self._service_suggestion_cache: dict[str, Any] = {}
        self._service_suggestion_cached_at = 0.0
        self._registry = self._load_registry()
        self.default_model_id = ""
        self._sync_models_locked()
        startup_adoption_deadline = time.monotonic() + self.startup_timeout_seconds
        self._adoption_deadlines.update(
            {
                model_id: startup_adoption_deadline
                for model_id in self._registry.get("services", {})
            }
        )
        self._adoption_next_probe_at.update(
            {model_id: 0.0 for model_id in self._registry.get("services", {})}
        )

    @contextmanager
    def model_operation_lock(self, model_id: Any) -> Iterator[None]:
        """按模型维度的细粒度互斥锁，用于串行化同一模型的更新与导入流程。"""
        key = _model_key(model_id or self.default_model_id or "__default__")
        with self.lock:
            op_lock = self._model_op_locks.get(key)
            if op_lock is None:
                op_lock = threading.RLock()
                self._model_op_locks[key] = op_lock
        with op_lock:
            yield

    def invalidate_health_cache(self, model_id: Optional[str] = None) -> None:
        with self.lock:
            if model_id is None:
                self._health_cache.clear()
            else:
                self._health_cache.pop(model_id, None)

    def _load_registry(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {"version": self.REGISTRY_VERSION, "services": {}}
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": self.REGISTRY_VERSION, "services": {}}
        services = payload.get("services", {}) if isinstance(payload, Mapping) else {}
        return {
            "version": self.REGISTRY_VERSION,
            "services": dict(services) if isinstance(services, Mapping) else {},
        }

    def _save_registry_locked(self) -> None:
        self._service_suggestion_cache = {}
        self._service_suggestion_cached_at = 0.0
        payload = {
            "version": self.REGISTRY_VERSION,
            "service_host": self.service_host,
            "first_service_port": self.first_service_port,
            "services": self._registry.get("services", {}),
        }
        temporary = self.registry_path.with_name(
            f"{self.registry_path.stem}.{uuid.uuid4().hex[:8]}.tmp"
        )
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        temporary.write_text(content, encoding="utf-8")
        try:
            for attempt in range(4):
                try:
                    temporary.replace(self.registry_path)
                    return
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(0.02 * (attempt + 1))
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def _model_dirs_locked(self) -> list[Path]:
        return [
            child
            for child in sorted(self.models_root.iterdir(), key=lambda path: path.name.casefold())
            if child.is_dir() and (child / "model.e").exists()
        ]

    @staticmethod
    def _preferred_default_model_id(model_ids: list[str]) -> str:
        for preferred in ("默认模型", "default"):
            for model_id in model_ids:
                if _model_key(model_id) == _model_key(preferred):
                    return model_id
        return model_ids[0] if model_ids else ""

    def _next_port_locked(self, host: str, used_ports: set[int]) -> int:
        port = self.first_service_port
        while port <= 65535 and (port in used_ports or self.port_checker(host, port)):
            port += 1
        if port > 65535:
            raise ValueError("没有可分配的模拟服务端口")
        return port

    def _sync_models_locked(self, *, force: bool = True) -> None:
        now = time.monotonic()
        if not force and now < self._models_sync_next_at and self._registry.get("services"):
            return
        self._models_sync_next_at = now + 1.5
        services = self._registry.setdefault("services", {})
        model_dirs = self._model_dirs_locked()
        model_ids = [path.name for path in model_dirs]
        reserved_ports: dict[str, set[int]] = {}
        for model_id in model_ids:
            entry = services.get(model_id)
            if not isinstance(entry, Mapping):
                continue
            try:
                host = _normalize_service_host(entry.get("host"), self.service_host)
                port = int(entry.get("port", 0))
            except (TypeError, ValueError):
                continue
            if port > 0:
                reserved_ports.setdefault(host, set()).add(port)

        changed = False
        normalized: dict[str, dict[str, Any]] = {}
        for model_dir in model_dirs:
            model_id = model_dir.name
            raw_entry = services.get(model_id)
            entry = dict(raw_entry) if isinstance(raw_entry, Mapping) else {}
            try:
                host = _normalize_service_host(entry.get("host"), self.service_host)
            except ValueError:
                host = self.service_host
                changed = True
            try:
                port = int(entry.get("port", 0))
            except (TypeError, ValueError):
                port = 0
            if port <= 0 or any(
                str(other.get("host") or "") == host and int(other.get("port", 0) or 0) == port
                for other_id, other in normalized.items()
                if other_id != model_id
            ):
                host_ports = reserved_ports.setdefault(host, set())
                port = self._next_port_locked(host, host_ports)
                host_ports.add(port)
                changed = True
            normalized[model_id] = {
                "host": host,
                "port": port,
                "pid": entry.get("pid"),
            }
            self._states.setdefault(model_id, "stopped")
            self._errors.setdefault(model_id, "")
        if set(services) != set(normalized):
            changed = True
            for removed_id in set(services) - set(normalized):
                self._health_cache.pop(removed_id, None)
        self._registry["services"] = normalized
        self.default_model_id = self._preferred_default_model_id(model_ids)
        if changed or not self.registry_path.exists():
            self._save_registry_locked()

    def _entry_locked(self, model_id: Any, *, sync: bool = True) -> tuple[str, dict[str, Any]]:
        if sync:
            self._sync_models_locked()
        target_id = _safe_model_id(model_id or self.default_model_id)
        entry = self._registry["services"].get(target_id)
        if not isinstance(entry, dict):
            raise KeyError(f"Unknown simulation model: {model_id}")
        return target_id, entry

    @classmethod
    def _default_health_checker(cls, host: str, port: int, model_id: str, timeout: float) -> HealthResult:
        request = Request(
            f"http://{host}:{port}/api/health",
            headers={"Accept": "application/json"},
        )
        try:
            with local_urlopen(request, timeout=timeout, allow_redirects=False) as response:
                data = response.read().decode("utf-8")
        except (HTTPError, URLError, OSError) as exc:
            return False, {}, str(exc)
        try:
            payload = json.loads(data) if data else {}
        except json.JSONDecodeError:
            return False, {}, "health response is not valid JSON"
        if not isinstance(payload, Mapping):
            return False, {}, "health response is not an object"
        actual_model_id = str(payload.get("model_id") or "")
        healthy = bool(payload.get("ok")) and actual_model_id == model_id
        if healthy and not cls._clock_state_from_payload(payload, model_id):
            try:
                payload = dict(payload)
                payload["snapshot"] = cls._fetch_snapshot(host, port, model_id, timeout)
            except RuntimeError:
                pass
        error = "" if healthy else f"unexpected service on {host}:{port}"
        return healthy, payload, error

    @staticmethod
    def _fetch_snapshot(host: str, port: int, model_id: str, timeout: float) -> Mapping[str, Any]:
        request = Request(
            (
                f"http://{host}:{port}/api/snapshot"
                "?lite=1&measurements=0&devices=0&device_states=0&commands=0&logs=0&static=0&static_meta=0"
            ),
            headers={"Accept": "application/json"},
        )
        try:
            with local_urlopen(request, timeout=timeout, allow_redirects=False) as response:
                data = response.read().decode("utf-8")
        except (HTTPError, URLError, OSError) as exc:
            raise RuntimeError(f"无法核实模型 {model_id} 的仿真时钟状态: {exc}") from exc
        try:
            payload = json.loads(data) if data else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"模型 {model_id} 的仿真时钟状态响应无效") from exc
        if not isinstance(payload, Mapping) or not SimulatorClusterManager._clock_state_from_payload(payload, model_id):
            raise RuntimeError(f"无法核实模型 {model_id} 的仿真时钟状态")
        return payload

    @staticmethod
    def _port_is_open(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.15):
                return True
        except OSError:
            return False

    @staticmethod
    def _default_clock_state_checker(host: str, port: int, model_id: str, timeout: float) -> str:
        payload = SimulatorClusterManager._fetch_snapshot(host, port, model_id, timeout)
        return SimulatorClusterManager._clock_state_from_payload(payload, model_id)

    @staticmethod
    def _clock_state_from_payload(payload: Mapping[str, Any], model_id: str) -> str:
        snapshot = payload.get("snapshot", payload)
        if not isinstance(snapshot, Mapping):
            return ""
        actual_model_id = str(snapshot.get("model", {}).get("id") or "")
        clock = snapshot.get("clock", {})
        state = str(clock.get("state") or "") if isinstance(clock, Mapping) else ""
        if actual_model_id == model_id and state in {"running", "paused", "stopped"}:
            return state
        return ""

    def _probe_unlocked(self, model_id: str, host: str, port: int) -> HealthResult:
        return self.health_checker(
            host,
            port,
            model_id,
            min(2.5, self.startup_timeout_seconds),
        )

    def _close_log_handle_locked(self, model_id: str) -> None:
        handle = self._log_handles.pop(model_id, None)
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def _reconcile_model(self, model_id: str, *, force_probe: bool = False) -> HealthResult:
        """在不持全局锁的前提下完成健康探测，并结合 Singleflight + 短 TTL 缓存消除并发排队。"""
        while True:
            with self.lock:
                entry = self._registry["services"].get(model_id)
                if not isinstance(entry, dict):
                    return False, {}, f"Unknown simulation model: {model_id}"
                process = self._processes.get(model_id)
                if process is not None and process.poll() is not None:
                    self._processes.pop(model_id, None)
                    self._close_log_handle_locked(model_id)
                    self._states[model_id] = "failed" if process.returncode else "stopped"
                    if process.returncode:
                        tail = _read_log_tail(self.log_dir / f"{model_id}.log")
                        base_msg = f"模拟服务已退出，返回码 {process.returncode}"
                        self._errors[model_id] = f"{base_msg}：{tail}" if tail else base_msg
                    entry["pid"] = None
                    self._health_cache.pop(model_id, None)
                    self._save_registry_locked()
                    process = None

                state = self._states.get(model_id, "stopped")
                now = time.monotonic()
                if not force_probe and self.health_cache_ttl_seconds > 0.0:
                    cached = self._health_cache.get(model_id)
                    if cached is not None and now - cached[0] < self.health_cache_ttl_seconds:
                        return cached[1]

                need_adoption_port_check = False
                if process is None and not entry.get("pid") and state in {"stopped", "failed"}:
                    adoption_deadline = self._adoption_deadlines.get(model_id, 0.0)
                    if adoption_deadline <= now:
                        self._adoption_deadlines.pop(model_id, None)
                        self._adoption_next_probe_at.pop(model_id, None)
                        result: HealthResult = (False, {}, self._errors.get(model_id, ""))
                        self._health_cache[model_id] = (now, result)
                        return result
                    if not force_probe and self._adoption_next_probe_at.get(model_id, 0.0) > now:
                        return False, {}, self._errors.get(model_id, "")
                    self._adoption_next_probe_at[model_id] = now + self.poll_interval_seconds
                    need_adoption_port_check = True

                # 若已有同模型探测在途，且无需强制重探，等待其完成后直接复用缓存（Singleflight）。
                inflight = self._inflight_probes.get(model_id)
                if inflight is not None:
                    wait_event = inflight
                    should_probe = False
                else:
                    wait_event = threading.Event()
                    self._inflight_probes[model_id] = wait_event
                    should_probe = True
                    host = str(entry["host"])
                    port = int(entry["port"])
                    had_process = process is not None
                    had_pid = bool(entry.get("pid"))

            if not should_probe:
                wait_event.wait(timeout=min(3.0, self.startup_timeout_seconds))
                if not force_probe:
                    with self.lock:
                        cached = self._health_cache.get(model_id)
                        if cached is not None:
                            return cached[1]
                force_probe = False
                continue

            # 锁外执行网络/端口探测，彻底释放全局锁。
            try:
                if need_adoption_port_check and not self.port_checker(host, port):
                    result = (False, {}, self._errors.get(model_id, ""))
                    with self.lock:
                        self._health_cache[model_id] = (time.monotonic(), result)
                    return result
                healthy, payload, error = self._probe_unlocked(model_id, host, port)
                with self.lock:
                    current_entry = self._registry["services"].get(model_id)
                    if isinstance(current_entry, dict):
                        current_process = self._processes.get(model_id)
                        if healthy:
                            self._adoption_deadlines.pop(model_id, None)
                            self._adoption_next_probe_at.pop(model_id, None)
                            if self._states.get(model_id) != "stopping":
                                self._states[model_id] = "running"
                                self._errors[model_id] = ""
                            process_payload = payload.get("process", {}) if isinstance(payload, Mapping) else {}
                            pid = process_payload.get("pid") if isinstance(process_payload, Mapping) else None
                            next_pid = pid or current_entry.get("pid")
                            if next_pid != current_entry.get("pid"):
                                current_entry["pid"] = next_pid
                                self._save_registry_locked()
                        elif current_process is None and not had_process and had_pid and current_entry.get("pid"):
                            current_entry["pid"] = None
                            self._states[model_id] = "stopped"
                            self._errors[model_id] = ""
                            self._adoption_deadlines[model_id] = (
                                time.monotonic() + self.startup_timeout_seconds
                            )
                            self._adoption_next_probe_at[model_id] = 0.0
                            self._save_registry_locked()
                        elif self._states.get(model_id) == "running":
                            self._states[model_id] = "failed"
                            self._errors[model_id] = error or "模拟服务健康检查失败"
                    result = (healthy, payload, error)
                    self._health_cache[model_id] = (time.monotonic(), result)
                return result
            finally:
                with self.lock:
                    if self._inflight_probes.get(model_id) is wait_event:
                        self._inflight_probes.pop(model_id, None)
                wait_event.set()

    def _build_service_payload_locked(
        self,
        model_id: str,
        entry: Mapping[str, Any],
        health: HealthResult,
    ) -> dict[str, Any]:
        healthy, payload, error = health
        state = self._states.get(model_id, "stopped")
        if not healthy and state not in {"starting", "stopping", "failed"}:
            state = "stopped"
        host = str(entry["host"])
        port = int(entry["port"])
        return {
            "state": state,
            "host": host,
            "port": port,
            "access_link": f"{host}:{port}",
            "base_url": f"http://{host}:{port}",
            "pid": entry.get("pid"),
            "healthy": healthy,
            "clock_state": self._clock_state_from_payload(payload, model_id) if healthy else "stopped",
            "error": self._errors.get(model_id, "") or (error if state == "failed" else ""),
        }

    def _format_model_info_locked(
        self,
        target_id: str,
        entry: Mapping[str, Any],
        health: HealthResult,
    ) -> dict[str, Any]:
        service = self._build_service_payload_locked(target_id, entry, health)
        clock_state = str(service.get("clock_state") or "")
        return {
            "id": target_id,
            "name": target_id,
            "sim_dir": str(self.models_root / target_id),
            "runtime_dir": str(self.runtime_root / target_id),
            "clock_state": clock_state or ("unknown" if service["healthy"] else "stopped"),
            "service": service,
        }

    def model_info(self, model_id: Any, *, force_probe: bool = False) -> dict[str, Any]:
        with self.lock:
            target_id, _entry = self._entry_locked(model_id, sync=True)
        health = self._reconcile_model(target_id, force_probe=force_probe)
        with self.lock:
            target_id, entry = self._entry_locked(target_id, sync=False)
            return self._format_model_info_locked(target_id, entry, health)

    def models(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        with self.lock:
            self._sync_models_locked(force=False)
            model_ids = list(self._registry["services"])
            health_map: dict[str, HealthResult] = {}
            pending_ids: list[str] = []
            for mid in model_ids:
                cached = self._health_cache.get(mid)
                if (
                    cached is not None
                    and self.health_cache_ttl_seconds > 0.0
                    and (now - cached[0]) < self.health_cache_ttl_seconds
                ):
                    health_map[mid] = cached[1]
                    continue
                entry = self._registry["services"].get(mid)
                process = self._processes.get(mid)
                state = self._states.get(mid, "stopped")
                if (
                    isinstance(entry, Mapping)
                    and process is None
                    and not entry.get("pid")
                    and state in {"stopped", "failed"}
                    and self._adoption_deadlines.get(mid, 0.0) <= now
                ):
                    # 稳定停止且过领养期的模型直接快速返回，无需提交探测线程池。
                    self._adoption_deadlines.pop(mid, None)
                    self._adoption_next_probe_at.pop(mid, None)
                    res: HealthResult = (False, {}, self._errors.get(mid, ""))
                    self._health_cache[mid] = (now, res)
                    health_map[mid] = res
                    continue
                pending_ids.append(mid)
        if len(pending_ids) == 1:
            mid = pending_ids[0]
            health_map[mid] = self._reconcile_model(mid)
        elif len(pending_ids) > 1:
            # 复用类级常驻线程池，仅对未命中 TTL 缓存的模型并发探测，避免每秒反复建毁线程。
            futures = {
                self._probe_executor.submit(self._reconcile_model, mid): mid
                for mid in pending_ids
            }
            for fut, mid in futures.items():
                health_map[mid] = fut.result()
        with self.lock:
            result: list[dict[str, Any]] = []
            services = self._registry["services"]
            for mid in model_ids:
                entry = services.get(mid)
                if isinstance(entry, Mapping):
                    result.append(self._format_model_info_locked(mid, entry, health_map[mid]))
            return result

    def catalog(self) -> dict[str, Any]:
        models_list = self.models()
        return {
            "models": models_list,
            "active_model_id": self.default_model_id,
            "models_root": str(self.models_root),
            "data_plane": "direct",
            "service_suggestion": self.suggest_service_address(sync=False),
        }

    def _validate_service_address_locked(
        self,
        host: Any,
        port: Any,
        *,
        exclude_model_id: str = "",
    ) -> dict[str, Any]:
        normalized_host = _normalize_service_host(host, self.service_host)
        services = self._registry.setdefault("services", {})
        used_ports = {
            int(entry.get("port", 0) or 0)
            for model_id, entry in services.items()
            if (
                model_id != exclude_model_id
                and isinstance(entry, Mapping)
                and _normalize_service_host(entry.get("host"), self.service_host) == normalized_host
            )
        }
        if port is None or str(port).strip() == "":
            normalized_port = self._next_port_locked(normalized_host, used_ports)
        else:
            normalized_port = _normalize_service_port(port)
            for model_id, entry in services.items():
                if model_id == exclude_model_id or not isinstance(entry, Mapping):
                    continue
                entry_host = _normalize_service_host(entry.get("host"), self.service_host)
                if entry_host == normalized_host and int(entry.get("port", 0) or 0) == normalized_port:
                    raise ValueError(
                        f"服务地址 {normalized_host}:{normalized_port} 已分配给模型“{model_id}”，"
                        "不同模型不能共用同一 IP 和端口"
                    )

            current = services.get(exclude_model_id) if exclude_model_id else None
            unchanged = bool(
                isinstance(current, Mapping)
                and str(current.get("host") or "") == normalized_host
                and int(current.get("port", 0) or 0) == normalized_port
            )
            if not unchanged and self.port_checker(normalized_host, normalized_port):
                raise ValueError(f"服务地址 {normalized_host}:{normalized_port} 已被占用")
        return {
            "host": normalized_host,
            "port": normalized_port,
            "access_link": f"{normalized_host}:{normalized_port}",
            "base_url": f"http://{normalized_host}:{normalized_port}",
        }

    def validate_service_address(
        self,
        host: Any = None,
        port: Any = None,
        *,
        exclude_model_id: Any = "",
    ) -> dict[str, Any]:
        with self.lock:
            self._sync_models_locked()
            excluded = str(exclude_model_id or "").strip()
            return self._validate_service_address_locked(host, port, exclude_model_id=excluded)

    def suggest_service_address(self, host: Any = None, *, sync: bool = True) -> dict[str, Any]:
        with self.lock:
            if sync:
                self._sync_models_locked()
            normalized_host = _normalize_service_host(host, self.service_host)
            now = time.monotonic()
            cached = self._service_suggestion_cache
            if (
                cached
                and cached.get("host") == normalized_host
                and now - self._service_suggestion_cached_at < 2.0
            ):
                return dict(cached)
            suggestion = self._validate_service_address_locked(normalized_host, None)
            self._service_suggestion_cache = dict(suggestion)
            self._service_suggestion_cached_at = now
            return suggestion

    def configure_model_service(self, model_id: Any, host: Any, port: Any) -> dict[str, Any]:
        with self.model_operation_lock(model_id):
            with self.lock:
                target_id, _entry = self._entry_locked(model_id)
            healthy, _payload, _error = self._reconcile_model(target_id, force_probe=True)
            with self.lock:
                target_id, entry = self._entry_locked(target_id, sync=False)
                process = self._processes.get(target_id)
                if healthy or (process is not None and process.poll() is None):
                    raise ValueError(f"模型模拟服务运行中，无法修改访问链接: {target_id}")
                address = self._validate_service_address_locked(
                    host,
                    port,
                    exclude_model_id=target_id,
                )
                changed = entry.get("host") != address["host"] or entry.get("port") != address["port"]
                if changed:
                    entry["host"] = address["host"]
                    entry["port"] = address["port"]
                    entry["pid"] = None
                    self._states[target_id] = "stopped"
                    self._errors[target_id] = ""
                    self._adoption_deadlines.pop(target_id, None)
                    self._adoption_next_probe_at.pop(target_id, None)
                    self._health_cache.pop(target_id, None)
                    self._save_registry_locked()
            return self.model_info(target_id)

    def _command_locked(self, model_id: str, entry: Mapping[str, Any]) -> list[str]:
        command = [
            sys.executable,
            "-X",
            "utf8",
            "-u",
            "-m",
            "simu.server",
            "--role",
            "simulator-service",
            "--host",
            str(entry["host"]),
            "--port",
            str(entry["port"]),
            "--sim-dir",
            str(self.sim_dir),
            "--model-id",
            model_id,
            "--model-dir",
            str(self.models_root / model_id),
            "--runtime-dir",
            str(self.runtime_root / model_id),
            "--compute-interval-seconds",
            str(self.compute_interval_seconds),
        ]
        if self.noise_std is not None:
            command.extend(["--noise-std", str(self.noise_std)])
        if self.random_seed is not None:
            command.extend(["--seed", str(self.random_seed)])
        if self.child_no_worker:
            command.append("--no-worker")
        return command

    def start(self, model_id: Any) -> dict[str, Any]:
        with self.model_operation_lock(model_id):
            with self.lock:
                target_id, entry = self._entry_locked(model_id)
                host = str(entry["host"])
                port = int(entry["port"])
            healthy, payload, error = self._probe_unlocked(target_id, host, port)
            if healthy:
                with self.lock:
                    target_id, entry = self._entry_locked(target_id, sync=False)
                    self._adoption_deadlines.pop(target_id, None)
                    self._adoption_next_probe_at.pop(target_id, None)
                    self._states[target_id] = "running"
                    self._errors[target_id] = ""
                    process_payload = payload.get("process", {}) if isinstance(payload, Mapping) else {}
                    if isinstance(process_payload, Mapping) and process_payload.get("pid"):
                        entry["pid"] = process_payload["pid"]
                    self._health_cache[target_id] = (time.monotonic(), (healthy, payload, error))
                    self._save_registry_locked()
                    return self._build_service_payload_locked(target_id, entry, (healthy, payload, error))
            if self.port_checker(host, port):
                raise RuntimeError(f"端口 {host}:{port} 已被非目标模拟服务占用")

            with self.lock:
                target_id, entry = self._entry_locked(target_id, sync=False)
                previous = self._processes.get(target_id)
                if previous is not None and previous.poll() is None:
                    self._states[target_id] = "starting"
                else:
                    self._states[target_id] = "starting"
                    self._errors[target_id] = ""
                    self._health_cache.pop(target_id, None)
                    log_path = self.log_dir / f"{target_id}.log"
                    _rotate_log_if_needed(log_path)
                    log_handle = log_path.open("ab", buffering=0)
                    environment = os.environ.copy()
                    environment.setdefault("PYTHONUTF8", "1")
                    environment["POWER_SIMU_APP_ROOT"] = str(self.sim_dir)
                    shared_root = Path(
                        str(os.environ.get("POWER_SIMU_SHARED_ROOT", "") or "").strip()
                        or (self.sim_dir.parent / "shared")
                    ).resolve()
                    if (shared_root / "simu").is_dir():
                        environment["POWER_SIMU_SHARED_ROOT"] = str(shared_root)
                        existing_py_path = environment.get("PYTHONPATH", "")
                        path_parts = [str(shared_root), str(self.sim_dir)]
                        if existing_py_path:
                            path_parts.append(existing_py_path)
                        environment["PYTHONPATH"] = os.pathsep.join(path_parts)
                    kwargs: dict[str, Any] = {
                        "cwd": str(self.sim_dir),
                        "env": environment,
                        "stdout": log_handle,
                        "stderr": subprocess.STDOUT,
                    }
                    if os.name == "nt":
                        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    try:
                        process = self.process_factory(self._command_locked(target_id, entry), **kwargs)
                    except Exception:
                        log_handle.close()
                        self._states[target_id] = "failed"
                        raise
                    self._processes[target_id] = process
                    self._log_handles[target_id] = log_handle
                    entry["pid"] = getattr(process, "pid", None)
                    self._save_registry_locked()

            deadline = time.monotonic() + self.startup_timeout_seconds
            last_error = "模拟服务启动超时"
            while time.monotonic() < deadline:
                with self.lock:
                    process = self._processes.get(target_id)
                    if process is not None and process.poll() is not None:
                        self._states[target_id] = "failed"
                        tail = _read_log_tail(self.log_dir / f"{target_id}.log")
                        base_msg = f"模拟服务启动失败，返回码 {process.returncode}"
                        last_error = f"{base_msg}：{tail}" if tail else base_msg
                        self._errors[target_id] = last_error
                        break
                healthy, payload, last_error = self._probe_unlocked(target_id, host, port)
                if healthy:
                    with self.lock:
                        target_id, entry = self._entry_locked(target_id, sync=False)
                        self._states[target_id] = "running"
                        self._errors[target_id] = ""
                        self._health_cache[target_id] = (time.monotonic(), (healthy, payload, last_error))
                        self._save_registry_locked()
                        return self._build_service_payload_locked(
                            target_id, entry, (healthy, payload, last_error)
                        )
                time.sleep(self.poll_interval_seconds)

            with self.lock:
                process = self._processes.pop(target_id, None)
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=self.shutdown_timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.shutdown_timeout_seconds)
            with self.lock:
                self._states[target_id] = "failed"
                self._errors[target_id] = last_error or "模拟服务启动失败"
                self._close_log_handle_locked(target_id)
                entry_ref = self._registry["services"].get(target_id)
                if isinstance(entry_ref, dict):
                    entry_ref["pid"] = None
                self._health_cache.pop(target_id, None)
                self._save_registry_locked()
                failure_message = self._errors[target_id]
            raise RuntimeError(failure_message)

    @staticmethod
    def _terminate_pid(pid: int) -> None:
        if pid <= 0:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError):
            return

    def _wait_adopted_exit(self, model_id: str, host: str, port: int, pid: int) -> None:
        """等待已领养的子服务退出并释放监听端口，防止随后立即删目录或重启时发生竞态。"""
        deadline = time.monotonic() + self.shutdown_timeout_seconds
        while time.monotonic() < deadline:
            if not self.port_checker(host, port):
                return
            healthy, _payload, _err = self._probe_unlocked(model_id, host, port)
            if not healthy:
                return
            time.sleep(min(0.1, self.poll_interval_seconds))
        if hasattr(signal, "SIGKILL"):
            try:
                os.kill(pid, signal.SIGKILL)
            except (OSError, ValueError):
                pass

    def stop(self, model_id: Any) -> dict[str, Any]:
        with self.model_operation_lock(model_id):
            with self.lock:
                target_id, entry = self._entry_locked(model_id)
                process = self._processes.get(target_id)
                host = str(entry["host"])
                port = int(entry["port"])
                recorded_pid = entry.get("pid")
                self._states[target_id] = "stopping"
                self._adoption_deadlines.pop(target_id, None)
                self._adoption_next_probe_at.pop(target_id, None)
                self._health_cache.pop(target_id, None)

            # 锁外等待子进程退出，避免阻塞其他模型的并发查询。
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=self.shutdown_timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.shutdown_timeout_seconds)
            elif recorded_pid:
                healthy, payload, _error = self._probe_unlocked(target_id, host, port)
                if healthy:
                    process_payload = payload.get("process", {}) if isinstance(payload, Mapping) else {}
                    verified_pid = process_payload.get("pid") if isinstance(process_payload, Mapping) else None
                    if verified_pid:
                        self._terminate_pid(int(verified_pid))
                        self._wait_adopted_exit(target_id, host, port, int(verified_pid))

            with self.lock:
                target_id, entry = self._entry_locked(target_id, sync=False)
                self._processes.pop(target_id, None)
                self._close_log_handle_locked(target_id)
                entry["pid"] = None
                self._states[target_id] = "stopped"
                self._errors[target_id] = ""
                self._health_cache[target_id] = (time.monotonic(), (False, {}, ""))
                self._save_registry_locked()
                host = str(entry["host"])
                port = int(entry["port"])
            return {
                "state": "stopped",
                "host": host,
                "port": port,
                "access_link": f"{host}:{port}",
                "base_url": f"http://{host}:{port}",
                "pid": None,
                "healthy": False,
                "error": "",
            }

    def require_stopped(self, model_id: Any) -> tuple[str, Path, Path]:
        with self.lock:
            target_id, _entry = self._entry_locked(model_id)
        healthy, _payload, _error = self._reconcile_model(target_id, force_probe=True)
        with self.lock:
            process = self._processes.get(target_id)
            if healthy or (process is not None and process.poll() is None):
                raise ValueError(f"模型模拟服务运行中，无法修改: {target_id}")
            return target_id, self.models_root / target_id, self.runtime_root / target_id

    def simulation_clock_state(self, model_id: Any) -> str:
        with self.lock:
            target_id, entry = self._entry_locked(model_id)
            host = str(entry["host"])
            port = int(entry["port"])
            timeout = min(2.0, self.startup_timeout_seconds)
        healthy, payload, error = self._reconcile_model(target_id, force_probe=True)
        if not healthy:
            raise RuntimeError(error or f"模型 {target_id} 的模拟服务未运行，无法核实仿真时钟状态")
        if not self._custom_clock_state_checker:
            clock_state = self._clock_state_from_payload(payload, target_id)
            if clock_state:
                return clock_state
        return self.clock_state_checker(host, port, target_id, timeout)

    def validate_new_model_name(self, new_model_id: Any) -> str:
        target_id = _safe_model_id(new_model_id)
        with self.lock:
            self._sync_models_locked()
            keys = {_model_key(model_id) for model_id in self._registry["services"]}
            if _model_key(target_id) in keys or (self.models_root / target_id).exists():
                raise ValueError(f"模型已存在: {target_id}")
        return target_id

    def register_model(
        self,
        model_id: Any,
        *,
        service_host: Any = None,
        service_port: Any = None,
    ) -> dict[str, Any]:
        target_id = _safe_model_id(model_id)
        with self.lock:
            if not (self.models_root / target_id / "model.e").exists():
                raise ValueError(f"模型定义不存在: {target_id}")
            self._sync_models_locked()
            if service_host is not None or service_port is not None:
                entry = self._registry["services"][target_id]
                address = self._validate_service_address_locked(
                    service_host if service_host is not None else entry["host"],
                    service_port if service_port is not None else entry["port"],
                    exclude_model_id=target_id,
                )
                entry["host"] = address["host"]
                entry["port"] = address["port"]
                entry["pid"] = None
                self._health_cache.pop(target_id, None)
                self._save_registry_locked()
        return self.model_info(target_id)

    def model_source_dir(self, model_id: Any) -> tuple[str, Path]:
        with self.lock:
            target_id, _entry = self._entry_locked(model_id)
            return target_id, self.models_root / target_id

    def clone_model(self, source_model_id: Any, new_model_id: Any) -> dict[str, Any]:
        _source_id, source_dir = self.model_source_dir(source_model_id)
        target_id = self.validate_new_model_name(new_model_id)
        target_dir = self.models_root / target_id
        shutil.copytree(source_dir, target_dir)
        try:
            return self.register_model(target_id)
        except Exception:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise

    def delete_model(self, model_id: Any) -> dict[str, Any]:
        with self.model_operation_lock(model_id):
            target_id, source_dir, runtime_dir = self.require_stopped(model_id)
            removed = self.model_info(target_id)
            with self.lock:
                self._sync_models_locked()
                if len(self._registry["services"]) <= 1:
                    raise ValueError("至少需要保留一个模型")
                shutil.rmtree(source_dir)
                if runtime_dir.exists():
                    shutil.rmtree(runtime_dir)
                self._registry["services"].pop(target_id, None)
                self._states.pop(target_id, None)
                self._errors.pop(target_id, None)
                self._health_cache.pop(target_id, None)
                self._save_registry_locked()
                self._sync_models_locked()
                return {**removed, "deleted": True, "active_model_id": self.default_model_id}

    def clear_model_runtime(self, model_id: Any) -> None:
        _target_id, _source_dir, runtime_dir = self.require_stopped(model_id)
        if runtime_dir.exists():
            shutil.rmtree(runtime_dir)
        runtime_dir.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        with self.lock:
            model_ids = list(self._registry.get("services", {}))
        for model_id in model_ids:
            try:
                self.stop(model_id)
            except (KeyError, OSError, RuntimeError, ValueError):
                pass
        self._probe_executor.shutdown(wait=False, cancel_futures=True)
