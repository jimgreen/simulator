"""HTTP 服务工厂、顶层请求处理器与分领域 API 路由实现。"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request

try:
    from .command_frame import command_payload_signature
    from .definition_editing import DefinitionRevisionConflict
    from .device_runtime_frame import (
        compact_device_runtime_frame,
        compact_device_runtime_supplement_frame,
    )
    from .http_common import (
        CLIENT_DISCONNECT_ERRORS,
        DEFAULT_MAX_JSON_BYTES,
        UPLOAD_MAX_JSON_BYTES,
        EncodedResponseCache,
        JsonApiError,
        PayloadTooLargeError,
        StaticAssetCache,
        apply_cors_headers,
        encode_json_for_cache,
        local_urlopen,
        parse_content_length,
        read_json_body,
        require_active_service_instance_locked as _require_active_service_instance_locked,
        safe_write_bytes,
        send_json_response,
        send_preencoded_json_response,
        should_demote_access_log,
    )
    from .model_artifacts import (
        ModelPreflightError,
        _apply_parsed_definition_archive_locked,
        _decode_optional_svg_payload,
        _decode_uploaded_definition_text,
        _parse_definition_archive,
        _preflight_model_import,
        create_model_from_efile,
        import_definition_archive,
        import_definition_model,
        make_definition_archive,
        update_model_from_efile,
    )
    from .renewable_control import (
        TraineeRenewableControlLifecycleError,
        TraineeRenewableControlManager,
    )
    from .service import (
        DIAGRAM_FILE_NAME,
        MultiModelSimulator,
        PolarMicrogridSimulator,
        ServiceInstanceRetiredError,
    )
    from .trainee_data_policy import (
        project_trainee_interstation_snapshot,
        strip_trainee_remote_details_from_snapshot,
        strip_trainee_truth_from_measurement_delta,
        strip_trainee_truth_from_measurement_history,
        strip_trainee_truth_from_measurements,
        strip_trainee_truth_from_snapshot,
    )
    from .trainee_exchange import TraineeExchangeLifecycleError, TraineeRealtimeExchange
except ImportError:  # pragma: no cover - legacy direct-module compatibility.
    from simu.command_frame import command_payload_signature
    from simu.definition_editing import DefinitionRevisionConflict
    from simu.device_runtime_frame import (
        compact_device_runtime_frame,
        compact_device_runtime_supplement_frame,
    )
    from simu.http_common import (
        CLIENT_DISCONNECT_ERRORS,
        DEFAULT_MAX_JSON_BYTES,
        UPLOAD_MAX_JSON_BYTES,
        EncodedResponseCache,
        JsonApiError,
        PayloadTooLargeError,
        StaticAssetCache,
        apply_cors_headers,
        encode_json_for_cache,
        local_urlopen,
        parse_content_length,
        read_json_body,
        require_active_service_instance_locked as _require_active_service_instance_locked,
        safe_write_bytes,
        send_json_response,
        send_preencoded_json_response,
        should_demote_access_log,
    )
    from simu.model_artifacts import (
        ModelPreflightError,
        _apply_parsed_definition_archive_locked,
        _decode_optional_svg_payload,
        _decode_uploaded_definition_text,
        _parse_definition_archive,
        _preflight_model_import,
        create_model_from_efile,
        import_definition_archive,
        import_definition_model,
        make_definition_archive,
        update_model_from_efile,
    )
    from simu.renewable_control import (
        TraineeRenewableControlLifecycleError,
        TraineeRenewableControlManager,
    )
    from simu.service import (
        DIAGRAM_FILE_NAME,
        MultiModelSimulator,
        PolarMicrogridSimulator,
        ServiceInstanceRetiredError,
    )
    from simu.trainee_data_policy import (
        project_trainee_interstation_snapshot,
        strip_trainee_remote_details_from_snapshot,
        strip_trainee_truth_from_measurement_delta,
        strip_trainee_truth_from_measurement_history,
        strip_trainee_truth_from_measurements,
        strip_trainee_truth_from_snapshot,
    )
    from simu.trainee_exchange import TraineeExchangeLifecycleError, TraineeRealtimeExchange


PACKAGE_DIR = Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"

DEFINITION_EDIT_PATHS = {
    "/api/definitions/device-parameters",
    "/api/definitions/measurement",
    "/api/definitions/manual-changes/reset",
    "/api/definitions/manual-changes/retry",
}
MANUAL_DEFINITION_CHANGES_PATH = "/api/definitions/manual-changes"
LOCAL_DEFINITION_PATHS = DEFINITION_EDIT_PATHS | {MANUAL_DEFINITION_CHANGES_PATH}
LOCAL_RUNTIME_SETTINGS_PATH = "/api/runtime-settings"
SIMULATOR_COMMAND_DELETE_PATH = "/api/simulator/commands/delete"
TRAINEE_LOCAL_GET_PATHS = {
    "/api/health",
    "/api/config",
    "/api/models",
    "/api/snapshot",
    "/api/runtime-logs",
    "/api/measurements",
    "/api/measurements/delta",
    "/api/measurement-history",
    "/api/devices",
    "/api/device-states",
    "/api/curves",
    "/api/curves/summary",
    "/api/curves/series",
    "/api/settings",
    "/api/export-definitions",
}
TRAINEE_LOCAL_POST_PATHS = {
    "/api/clock",
    "/api/reset",
    "/api/step",
    "/api/curves",
    "/api/curves/series",
    "/api/settings",
    "/api/device-faults",
    "/api/measurement-faults",
    "/api/modes",
    "/api/commands",
    "/api/runtime-logs/clear",
    "/api/import-definitions",
    "/api/models/create",
    "/api/models/update-definitions",
    "/api/models/clone",
    "/api/models/delete",
    "/api/models/import-definitions",
}
RENEWABLE_CONTROL_PATH = "/api/trainee/renewable-control"
RENEWABLE_CONTROL_TREND_PATH = f"{RENEWABLE_CONTROL_PATH}/trend"
TRAINEE_UI_FRAME_PATH = "/api/trainee/ui-frame"
EXTERNAL_REALTIME_INPUTS_PATH = "/api/external/realtime-inputs"
UPLOAD_POST_PATHS = frozenset(
    {
        "/api/models/create",
        "/api/models/update-definitions",
        "/api/import-definitions",
        "/api/models/import-definitions",
        "/api/trainee/model-initialize",
    }
)

PROCESS_STARTED_MONOTONIC = time.monotonic()

_READONLY_POST_PATHS = frozenset(
    {
        "/api/external/telemetry/query",
        "/api/external/telemetry/values/query",
        "/api/external/telemetry/history/query",
        "/api/external/curves/query",
    }
)

if os.name == "nt":
    try:
        import ctypes as _win_ctypes
        from ctypes import wintypes as _win_wintypes

        class _ProcessMemoryCountersEx(_win_ctypes.Structure):
            _fields_ = [
                ("cb", _win_wintypes.DWORD),
                ("PageFaultCount", _win_wintypes.DWORD),
                ("PeakWorkingSetSize", _win_ctypes.c_size_t),
                ("WorkingSetSize", _win_ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", _win_ctypes.c_size_t),
                ("QuotaPagedPoolUsage", _win_ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", _win_ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", _win_ctypes.c_size_t),
                ("PagefileUsage", _win_ctypes.c_size_t),
                ("PeakPagefileUsage", _win_ctypes.c_size_t),
                ("PrivateUsage", _win_ctypes.c_size_t),
            ]
    except Exception:
        _win_ctypes = None
        _ProcessMemoryCountersEx = None
else:
    _win_ctypes = None
    _ProcessMemoryCountersEx = None


def _current_process_memory() -> dict[str, Optional[float]]:
    working_set_bytes: Optional[int] = None
    private_bytes: Optional[int] = None
    if os.name == "nt":
        if _win_ctypes is not None and _ProcessMemoryCountersEx is not None:
            try:
                counters = _ProcessMemoryCountersEx()
                counters.cb = _win_ctypes.sizeof(counters)
                handle = _win_ctypes.windll.kernel32.GetCurrentProcess()
                if _win_ctypes.windll.psapi.GetProcessMemoryInfo(
                    handle, _win_ctypes.byref(counters), counters.cb
                ):
                    working_set_bytes = int(counters.WorkingSetSize)
                    private_bytes = int(counters.PrivateUsage)
            except Exception:
                working_set_bytes = None
                private_bytes = None
    else:
        try:
            import resource

            rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            working_set_bytes = rss * 1024 if os.uname().sysname != "Darwin" else rss
        except Exception:
            working_set_bytes = None
    return {
        "rss_mb": round(working_set_bytes / (1024 * 1024), 2) if working_set_bytes is not None else None,
        "private_mb": round(private_bytes / (1024 * 1024), 2) if private_bytes is not None else None,
    }


def _process_health_payload(
    *,
    role: str,
    target: PolarMicrogridSimulator,
    exchange: Optional[TraineeRealtimeExchange] = None,
    renewable_manager: Optional[TraineeRenewableControlManager] = None,
) -> dict[str, Any]:
    memory = _current_process_memory()
    payload: dict[str, Any] = {
        "pid": os.getpid(),
        "role": role,
        "uptime_seconds": round(max(0.0, time.monotonic() - PROCESS_STARTED_MONOTONIC), 2),
        "thread_count": threading.active_count(),
        "rss_mb": memory["rss_mb"],
        "private_mb": memory["private_mb"],
        "model_id": target.model_id,
    }
    if exchange is not None:
        exchange_diag = getattr(exchange, "diagnostics", None)
        if callable(exchange_diag):
            payload["trainee_exchange"] = exchange_diag()
    if renewable_manager is not None:
        renewable_diag = getattr(renewable_manager, "diagnostics", None)
        if callable(renewable_diag):
            payload["renewable_control"] = renewable_diag()
    return payload


def _discover_local_simulator_services(sim_url: Optional[str] = None) -> dict[str, Any]:
    """自动探测本机教员端代理下已注册/运行中的模型服务列表，供学员端下拉选择。"""
    candidates: list[str] = []
    for raw in (
        sim_url,
        os.environ.get("SIMULATOR_PROXY_URL"),
        "http://127.0.0.1:18710",
        "http://127.0.0.1:8710",
    ):
        url = str(raw or "").strip().rstrip("/")
        if url and url not in candidates:
            candidates.append(url)
    for base in candidates:
        try:
            req = Request(f"{base}/api/models", headers={"Accept": "application/json"})
            with local_urlopen(req, timeout=1.2, allow_redirects=False) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue
        models = payload.get("models") if isinstance(payload, Mapping) else None
        if not isinstance(models, list):
            continue
        items = []
        for entry in models:
            if not isinstance(entry, Mapping):
                continue
            service = entry.get("service") if isinstance(entry.get("service"), Mapping) else {}
            service_url = str(service.get("base_url") or "").strip().rstrip("/")
            if not service_url:
                continue
            items.append(
                {
                    "model_id": str(entry.get("id") or ""),
                    "name": str(entry.get("name") or entry.get("id") or ""),
                    "base_url": service_url,
                    "state": str(service.get("state") or "stopped"),
                    "healthy": bool(service.get("healthy")),
                    "clock_state": str(service.get("clock_state") or "stopped"),
                }
            )
        items.sort(key=lambda item: (not item["healthy"], item["name"].casefold()))
        return {"ok": True, "proxy_url": base, "services": items}
    return {"ok": True, "proxy_url": "", "services": []}


@dataclass
class _ServerContext:
    """承载 HTTP 服务上下文，替代原先 1,680 行巨型嵌套闭包。"""

    service: PolarMicrogridSimulator | MultiModelSimulator
    role: str
    static_root: Path
    sim_url: Optional[str]
    exchange: Optional[TraineeRealtimeExchange]
    renewable_manager: Optional[TraineeRenewableControlManager]
    direct_simulator_ui: bool
    static_cache: StaticAssetCache
    response_cache: EncodedResponseCache

    def captured_service_is_current(self, target: PolarMicrogridSimulator) -> bool:
        if hasattr(self.service, "service_for"):
            try:
                current = self.service.service_for(target.model_id)  # type: ignore[union-attr]
            except KeyError:
                return False
            if current is not target:
                return False
        elif self.service is not target:
            return False
        checker = getattr(target, "service_instance_active", None)
        return bool(checker()) if callable(checker) else True


class PolarMicrogridHandler(BaseHTTPRequestHandler):
    server_version = "PolarMicrogridHTTP/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def _ctx(self) -> "_ServerContext":
        return self.server._ctx  # type: ignore[attr-defined]

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        logger = logging.getLogger("simu.web")
        method = getattr(self, "command", "")
        request_path = getattr(self, "path", "")
        if should_demote_access_log(method, request_path, code):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug('%s "%s" %s %s', self.client_address[0], self.requestline, code, size)
            return
        logger.info('%s "%s" %s %s', self.client_address[0], self.requestline, code, size)

    def log_message(self, fmt: str, *args: Any) -> None:
        logging.getLogger("simu.web").info("%s %s", self.client_address[0], fmt % args)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == EXTERNAL_REALTIME_INPUTS_PATH and self._ctx.role != "simulator":
                self._handle_api_get()
                return
            if (
                path in LOCAL_DEFINITION_PATHS
                or path == LOCAL_RUNTIME_SETTINGS_PATH
                or (self._ctx.role == "trainee" and path in TRAINEE_LOCAL_GET_PATHS)
            ):
                self._handle_api_get()
                return
            if path == RENEWABLE_CONTROL_PATH and self._ctx.role == "trainee":
                self._handle_api_get()
                return
            if (
                self.path.startswith("/api/")
                and self._ctx.role == "trainee"
                and self._ctx.sim_url
                and not path.startswith("/api/trainee/")
            ):
                self._proxy_to_simulator("GET", self._ctx.sim_url)
                return
            if self.path.startswith("/api/"):
                self._handle_api_get()
                return
            if self._ctx.direct_simulator_ui and self._ctx.role == "simulator" and path in {"", "/", "/index.html"}:
                ui_mode = (parse_qs(urlparse(self.path).query).get("ui") or [""])[0]
                if ui_mode != "direct":
                    self.send_response(302)
                    self._cors(cache_control="no-cache")
                    self.send_header("Location", "/?ui=direct")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            self._serve_static(self._ctx.static_root)
        except CLIENT_DISCONNECT_ERRORS:
            return
        except JsonApiError as exc:
            self._send_json(
                {"error": exc.message, **self._external_error_metadata(exc.details)},
                status=exc.status,
            )
        except PayloadTooLargeError as exc:
            self._send_json(
                {"error": str(exc), **self._external_error_metadata({})},
                status=413,
            )
        except (
            ServiceInstanceRetiredError,
            TraineeExchangeLifecycleError,
            TraineeRenewableControlLifecycleError,
        ) as exc:
            self._send_json(
                {"error": str(exc), **self._external_error_metadata({})},
                status=409,
            )
        except Exception as exc:
            logging.getLogger("simu.web").exception("Unhandled GET error for %s", self.path)
            self._send_json(
                {"error": str(exc), **self._external_error_metadata({})},
                status=500,
            )

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        mutated_successfully = False
        try:
            if path == EXTERNAL_REALTIME_INPUTS_PATH and self._ctx.role != "simulator":
                self._handle_api_post()
                mutated_successfully = True
                return
            if (
                path in LOCAL_DEFINITION_PATHS
                or path == LOCAL_RUNTIME_SETTINGS_PATH
                or path == SIMULATOR_COMMAND_DELETE_PATH
                or (self._ctx.role == "trainee" and path in TRAINEE_LOCAL_POST_PATHS)
            ):
                self._handle_api_post()
                mutated_successfully = True
                return
            if path == RENEWABLE_CONTROL_PATH and self._ctx.role == "trainee":
                self._handle_api_post()
                mutated_successfully = True
                return
            if (
                self.path.startswith("/api/")
                and self._ctx.role == "trainee"
                and self._ctx.sim_url
                and not path.startswith("/api/trainee/")
            ):
                self._proxy_to_simulator("POST", self._ctx.sim_url)
                mutated_successfully = True
                return
            self._handle_api_post()
            mutated_successfully = True
        except CLIENT_DISCONNECT_ERRORS:
            return
        except JsonApiError as exc:
            self._send_json(
                {"error": exc.message, **self._external_error_metadata(exc.details)},
                status=exc.status,
            )
        except PayloadTooLargeError as exc:
            self._send_json(
                {"error": str(exc), **self._external_error_metadata({})},
                status=413,
            )
        except (
            ServiceInstanceRetiredError,
            TraineeExchangeLifecycleError,
            TraineeRenewableControlLifecycleError,
        ) as exc:
            self._send_json(
                {"error": str(exc), **self._external_error_metadata({})},
                status=409,
            )
        except Exception as exc:
            logging.getLogger("simu.web").exception("Unhandled POST error for %s", self.path)
            self._send_json(
                {"error": str(exc), **self._external_error_metadata({})},
                status=500,
            )
        finally:
            # 仅在写操作成功返回后清空响应缓存与指令/设备补充帧缓存，避免只读 query POST 或失败请求击穿热点缓存。
            if mutated_successfully and path not in _READONLY_POST_PATHS:
                self._ctx.response_cache.clear()
                try:
                    for svc in (self._ctx.manager.list_services() if hasattr(self._ctx.manager, "list_services") else ()):
                        if hasattr(svc, "_command_signature_cache"):
                            svc._command_signature_cache = None
                        if hasattr(svc, "_device_runtime_supplement_cache"):
                            svc._device_runtime_supplement_cache = None
                except Exception:
                    pass

    def do_PUT(self) -> None:
        self.do_POST()

    def _request_model_id(self, payload: Optional[Mapping[str, Any]] = None) -> Optional[str]:
        parsed = urlparse(self.path)
        query_values = parse_qs(parsed.query).get("model_id") or parse_qs(parsed.query).get("model")
        if query_values and query_values[0]:
            return query_values[0]
        if payload:
            value = payload.get("model_id", payload.get("model"))
            return str(value) if value not in (None, "") else None
        return None

    def _target_service(self, payload: Optional[Mapping[str, Any]] = None) -> PolarMicrogridSimulator:
        if hasattr(self._ctx.service, "service_for"):
            try:
                return self._ctx.service.service_for(self._request_model_id(payload))  # type: ignore[union-attr]
            except KeyError as exc:
                raise JsonApiError(404, str(exc)) from exc
        return self._ctx.service  # type: ignore[return-value]

    def _external_error_metadata(self, details: Mapping[str, Any]) -> Mapping[str, Any]:
        merged = dict(details)
        if not urlparse(self.path).path.startswith("/api/external/"):
            return merged
        try:
            target = self._target_service()
        except Exception:
            return merged
        return target._external_response_metadata() | merged

    def _reject_active_trainee_receive_model(self, payload: Mapping[str, Any], operation: str) -> None:
        if self._ctx.role != "trainee":
            return
        target = self._target_service(payload)
        if target.trainee_receive_state().get("active"):
            raise JsonApiError(400, f"模型正在接收中，不能{operation}。")

    def _model_catalog(self) -> Mapping[str, Any]:
        if hasattr(self._ctx.service, "models"):
            return {
                "models": self._ctx.service.models(),  # type: ignore[union-attr]
                "active_model_id": self._ctx.service.default_model_id,  # type: ignore[union-attr]
                "models_root": str(self._ctx.service.models_root),  # type: ignore[union-attr]
            }
        return {
            "models": [self._ctx.service.model_info()],  # type: ignore[union-attr]
            "active_model_id": self._ctx.service.model_id,  # type: ignore[union-attr]
            "models_root": str(self._ctx.service.sim_dir),  # type: ignore[union-attr]
        }

    def _request_base_url(self) -> str:
        parsed_sim_url = urlparse(self._ctx.sim_url or "")
        scheme = parsed_sim_url.scheme or "http"
        host = self.headers.get("Host") or parsed_sim_url.netloc
        if not host:
            server_host, server_port = self.server.server_address[:2]
            host = f"{server_host}:{server_port}"
        return f"{scheme}://{host}".rstrip("/")

    def _truthy_query(self, name: str) -> bool:
        value = (parse_qs(urlparse(self.path).query).get(name) or [""])[0]
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _falsey_query(self, name: str) -> bool:
        value = (parse_qs(urlparse(self.path).query).get(name) or [""])[0]
        return str(value).strip().lower() in {"0", "false", "no", "off"}

    def _static_query(self, default_include_static: bool) -> tuple[bool, Optional[Sequence[str]]]:
        values = parse_qs(urlparse(self.path).query).get("static")
        if not values:
            return default_include_static, None
        raw = ",".join(str(value) for value in values).strip()
        normalized = raw.lower()
        if not raw or normalized in {"0", "false", "no", "off", "none"}:
            return False, []
        if normalized in {"1", "true", "yes", "on", "all"}:
            return True, None
        fields = [
            field.strip()
            for value in values
            for field in str(value).split(",")
            if field.strip()
        ]
        return bool(fields), fields

    def _int_query(self, name: str, default: int, minimum: int = 0, maximum: int = 500) -> int:
        raw = (parse_qs(urlparse(self.path).query).get(name) or [default])[0]
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, value))

    def _optional_int_query(self, name: str) -> Optional[int]:
        values = parse_qs(urlparse(self.path).query).get(name)
        if not values or values[0] in (None, ""):
            return None
        try:
            return int(values[0])
        except (TypeError, ValueError):
            return None

    def _measurement_indices_query(self) -> Optional[List[int]]:
        values = parse_qs(urlparse(self.path).query).get("indices")
        if not values:
            return None
        selected: List[int] = []
        seen: set[int] = set()
        for token in ",".join(str(value) for value in values).split(","):
            try:
                index = int(token.strip())
            except (TypeError, ValueError):
                continue
            if index < 0 or index in seen:
                continue
            selected.append(index)
            seen.add(index)
            if len(selected) >= 256:
                break
        return selected

    def _trainee_link_payload(self, target: PolarMicrogridSimulator) -> Mapping[str, Any]:
        model = target.model_info()
        model_id = str(model.get("id", target.model_id))
        base_url = self._request_base_url()
        encoded_model_id = quote(model_id, safe="")
        external_api = {
            "devices": f"/api/external/devices?model_id={encoded_model_id}",
            "realtime_inputs": f"{EXTERNAL_REALTIME_INPUTS_PATH}?model_id={encoded_model_id}",
            "telemetry_names": f"/api/external/telemetry/names?model_id={encoded_model_id}",
            "telemetry_values": f"/api/external/telemetry/values?model_id={encoded_model_id}",
            "selected_telemetry_values": f"/api/external/telemetry/values/query?model_id={encoded_model_id}",
            "measurement_history": f"/api/external/telemetry/history/query?model_id={encoded_model_id}",
            "control_names": f"/api/external/controls/names?model_id={encoded_model_id}",
            "control_execute": f"/api/external/controls/execute?model_id={encoded_model_id}",
            "curves_query": f"/api/external/curves/query?model_id={encoded_model_id}",
            "curves_update": f"/api/external/curves/update?model_id={encoded_model_id}",
        }
        return {
            "type": "polar-microgrid-trainee-link",
            "version": 1,
            "role": "simulator",
            "link": base_url,
            "teacher_api_base": base_url,
            "model_id": model_id,
            "model_name": model.get("name", model_id),
            "model_version": target.external_model_version(),
            "snapshot_path": f"/api/snapshot?model_id={encoded_model_id}&trainee_view=1",
            "command_path": f"/api/student/commands?model_id={encoded_model_id}",
            "runtime_logs_path": f"/api/runtime-logs?model_id={encoded_model_id}",
            "measurement_delta_path": f"/api/measurements/delta?model_id={encoded_model_id}&trainee_view=1",
            "definition_archive_path": f"/api/export-definitions?format=json&model_id={encoded_model_id}",
            "telemetry_path": f"/api/external/telemetry?model_id={encoded_model_id}",
            "selected_telemetry_path": f"/api/external/telemetry/query?model_id={encoded_model_id}",
            "control_values_path": f"/api/external/controls?model_id={encoded_model_id}",
            "control_command_path": f"/api/external/controls?model_id={encoded_model_id}",
            "device_information_path": external_api["devices"],
            "realtime_inputs_path": external_api["realtime_inputs"],
            "telemetry_names_path": external_api["telemetry_names"],
            "telemetry_values_path": external_api["telemetry_values"],
            "selected_telemetry_values_path": external_api["selected_telemetry_values"],
            "measurement_history_path": external_api["measurement_history"],
            "control_names_path": external_api["control_names"],
            "control_execute_path": external_api["control_execute"],
            "external_api": external_api,
            "shareable": True,
        }

    def _json_request_to_url(
        self,
        url: str,
        *,
        method: str = "GET",
        payload: Optional[Mapping[str, Any]] = None,
        timeout: float = 10.0,
    ) -> Any:
        body = None
        headers = {"Accept": "application/json"}
        if method in ("POST", "PUT"):
            body = json.dumps(payload or {}, ensure_ascii=False, default=str).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with local_urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise JsonApiError(exc.code, detail or exc.reason) from exc
        except URLError as exc:
            raise JsonApiError(502, f"模拟台服务不可达：{exc}") from exc
        try:
            return json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            raise JsonApiError(502, "模拟台返回内容不是有效 JSON") from exc

    def _resolve_trainee_connection(self, raw_link: str) -> Mapping[str, Any]:
        raw = str(raw_link or "").strip()
        if not raw:
            raise JsonApiError(400, "请输入模拟台服务地址")
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise JsonApiError(400, "模拟台服务地址必须是完整的 http 或 https 地址")
        if parsed.username or parsed.password:
            raise JsonApiError(400, "模拟台服务地址不能包含用户名或密码")
        base_url = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        payload = self._json_request_to_url(f"{base_url}/api/trainee-link")
        if not isinstance(payload, Mapping):
            raise JsonApiError(400, "模拟台服务返回的连接信息不是对象")
        if payload.get("type") != "polar-microgrid-trainee-link" or payload.get("role") != "simulator":
            raise JsonApiError(400, "模拟台服务地址无效，请使用模拟台生成的服务地址")
        model_id = str(payload.get("model_id") or "").strip()
        if not model_id:
            raise JsonApiError(400, "模拟台连接信息缺少模型标识")
        encoded_model_id = quote(model_id, safe="")
        snapshot_path = self._with_query_overrides(
            f"/api/snapshot?model_id={encoded_model_id}",
            {"trainee_view": 1},
        )
        measurement_delta_path = self._with_query_overrides(
            f"/api/measurements/delta?model_id={encoded_model_id}",
            {"trainee_view": 1},
        )
        return {
            "link": base_url,
            "teacher_api_base": base_url,
            "model_id": model_id,
            "model_name": str(payload.get("model_name") or model_id),
            "snapshot_path": snapshot_path,
            "command_path": f"/api/student/commands?model_id={encoded_model_id}",
            "measurement_delta_path": measurement_delta_path,
            "definition_archive_path": f"/api/export-definitions?format=json&model_id={encoded_model_id}",
        }

    def _with_query_overrides(self, path: str, overrides: Mapping[str, Any]) -> str:
        parsed = urlparse(path or "")
        query = parse_qs(parsed.query, keep_blank_values=True)
        for key, value in overrides.items():
            if value is None:
                continue
            query[key] = [str(value)]
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(query, doseq=True),
                parsed.fragment,
            )
        )

    def _trainee_remote_url(
        self,
        target: PolarMicrogridSimulator,
        path_key: str,
        *,
        default_path: str,
        query_overrides: Optional[Mapping[str, Any]] = None,
    ) -> str:
        receive_state = target.trainee_receive_state()
        if not receive_state.get("active"):
            raise JsonApiError(409, "当前模型未启动接收")
        base_url = str(receive_state.get("teacher_api_base") or "").rstrip("/")
        if not base_url:
            raise JsonApiError(409, "当前模型未配置模拟台服务地址")
        remote_path = str(receive_state.get(path_key) or default_path)
        if query_overrides:
            remote_path = self._with_query_overrides(remote_path, query_overrides)
        if remote_path.startswith("http://") or remote_path.startswith("https://"):
            return remote_path
        return urljoin(base_url + "/", remote_path.lstrip("/"))

    def _trainee_snapshot_query_overrides(self) -> Mapping[str, Any]:
        values = parse_qs(urlparse(self.path).query)
        allowed = (
            "lite",
            "logs",
            "runtime_logs",
            "measurements",
            "log_limit",
            "devices",
            "device_states",
            "commands",
            "command_history",
            "static",
            "static_meta",
            "device_runtime_compact",
            "device_runtime_supplement",
            "after_device_runtime_signature",
        )
        return {key: values[key][0] for key in allowed if values.get(key)}

    def _renewable_state_payload(self, target: PolarMicrogridSimulator) -> Mapping[str, Any]:
        if self._ctx.role != "trainee" or self._ctx.renewable_manager is None:
            raise JsonApiError(404, f"Unknown API route: {urlparse(self.path).path}")
        renewable_query = parse_qs(urlparse(self.path).query)
        options = {
            "refresh": self._truthy_query("refresh"),
            "compact": self._truthy_query("compact"),
            "include_performance": not self._falsey_query("performance"),
            "include_trend": not self._falsey_query("trend"),
            "after_log_seq": self._int_query(
                "after_log_seq",
                0,
                0,
                2_000_000_000,
            ),
            "after_trend_sample_key": str(
                (renewable_query.get("after_trend_sample_key") or [""])[0]
            ),
            "after_plan_revision": self._optional_int_query("after_plan_revision"),
            "after_settings_revision": self._optional_int_query(
                "after_settings_revision"
            ),
            "after_performance_revision": self._optional_int_query(
                "after_performance_revision"
            ),
            "after_controller_instance_id": str(
                (renewable_query.get("after_controller_instance_id") or [""])[0]
            ),
        }
        trend_encoding = str(
            (renewable_query.get("trend_encoding") or [""])[0]
        ).strip()
        if trend_encoding.casefold() == "arrays-v1":
            options["trend_encoding"] = "arrays-v1"
        state_for_service = getattr(self._ctx.renewable_manager, "state_for_service", None)
        if callable(state_for_service):
            return state_for_service(target, **options)
        if not self._ctx.captured_service_is_current(target):
            raise JsonApiError(
                409,
                "新能源控制请求所属模型生命周期已失效或已退休。",
            )
        return self._ctx.renewable_manager.state(target.model_id, **options)

    def _renewable_trend_payload(
        self,
        target: PolarMicrogridSimulator,
    ) -> Mapping[str, Any]:
        if self._ctx.role != "trainee" or self._ctx.renewable_manager is None:
            raise JsonApiError(404, f"Unknown API route: {urlparse(self.path).path}")
        query = parse_qs(urlparse(self.path).query)
        requested_fields = [
            field.strip()
            for value in query.get("fields", [])
            for field in str(value).split(",")
            if field.strip()
        ]
        if len(requested_fields) > 128:
            raise JsonApiError(400, "单次新能源趋势查询字段不能超过 128 个")
        trend_history = getattr(
            self._ctx.renewable_manager,
            "trend_history_for_service",
            None,
        )
        if not callable(trend_history):
            raise JsonApiError(404, "当前新能源控制器不支持趋势历史按需查询")
        try:
            return trend_history(
                target,
                fields=requested_fields,
                after_trend_sample_key=str(
                    (query.get("after_trend_sample_key") or [""])[0]
                ),
                after_controller_instance_id=str(
                    (query.get("after_controller_instance_id") or [""])[0]
                ),
                trend_encoding="arrays-v1",
            )
        except ValueError as exc:
            raise JsonApiError(400, str(exc)) from exc

    def _trainee_snapshot_payload(
        self,
        target: PolarMicrogridSimulator,
    ) -> Dict[str, Any]:
        if self._ctx.exchange is None:
            raise JsonApiError(404, f"Unknown API route: {urlparse(self.path).path}")
        snapshot_for_service = getattr(self._ctx.exchange, "snapshot_for_service", None)
        if callable(snapshot_for_service):
            snapshot_payload = snapshot_for_service(
                target,
                options=self._trainee_snapshot_query_overrides(),
                refresh=self._truthy_query("refresh"),
            )
        else:
            if not self._ctx.captured_service_is_current(target):
                raise JsonApiError(
                    409,
                    "学员台快照请求所属模型生命周期已失效或已退休。",
                )
            snapshot_payload = self._ctx.exchange.snapshot(
                target.model_id,
                options=self._trainee_snapshot_query_overrides(),
                refresh=self._truthy_query("refresh"),
            )
        measurement_after_seq = self._optional_int_query("measurement_after_seq")
        if measurement_after_seq is not None:
            delta_for_service = getattr(self._ctx.exchange, "measurement_delta_for_service", None)
            if callable(delta_for_service):
                snapshot_payload["measurement_delta"] = delta_for_service(
                    target,
                    after_seq=max(0, measurement_after_seq),
                    compact=self._truthy_query("measurement_compact"),
                )
            else:
                delta_options = {"after_seq": max(0, measurement_after_seq)}
                if self._truthy_query("measurement_compact"):
                    delta_options["compact"] = True
                snapshot_payload["measurement_delta"] = self._ctx.exchange.measurement_delta(
                    target.model_id,
                    **delta_options,
                )
        strip_trainee_remote_details_from_snapshot(snapshot_payload)
        trainee_snapshot_query = parse_qs(urlparse(self.path).query)
        after_command_signature = str(
            (trainee_snapshot_query.get("after_command_signature") or [""])[0]
        ).strip()
        commands_payload = snapshot_payload.get("commands")
        if isinstance(commands_payload, Mapping):
            command_signature = command_payload_signature(commands_payload)
            snapshot_payload["command_signature"] = command_signature
            if after_command_signature == command_signature:
                snapshot_payload.pop("commands", None)
        if self._truthy_query("device_runtime_compact"):
            if self._truthy_query("device_runtime_supplement"):
                device_runtime_frame = compact_device_runtime_supplement_frame(
                    snapshot_payload.get("devices", []),
                    snapshot_payload.get("device_states", []),
                    target.measurement_definitions(),
                    definition_revision=target.definition_snapshot.revision,
                )
            else:
                device_runtime_frame = compact_device_runtime_frame(
                    snapshot_payload.get("devices", []),
                    snapshot_payload.get("device_states", []),
                    definition_revision=target.definition_snapshot.revision,
                )
            device_runtime_signature = str(
                device_runtime_frame.get("runtime_signature", "")
            ).strip()
            after_device_runtime_signature = str(
                (
                    trainee_snapshot_query.get("after_device_runtime_signature")
                    or [""]
                )[0]
            ).strip()
            snapshot_payload.pop("devices", None)
            snapshot_payload.pop("device_states", None)
            snapshot_payload["device_runtime_signature"] = device_runtime_signature
            if after_device_runtime_signature != device_runtime_signature:
                snapshot_payload["device_runtime"] = device_runtime_frame
        return snapshot_payload

    def _handle_trainee_connect(self, payload: Mapping[str, Any]) -> None:
        connection = self._resolve_trainee_connection(str(payload.get("link", payload.get("interaction_link", ""))))
        snapshot_url = urljoin(
            connection["teacher_api_base"].rstrip("/") + "/",
            str(connection["snapshot_path"]).lstrip("/"),
        )
        snapshot = self._json_request_to_url(snapshot_url)
        self._send_json({"connection": connection, "snapshot": snapshot})

    @staticmethod
    def _connection_url(connection: Mapping[str, Any], path_key: str) -> str:
        base_url = str(connection.get("teacher_api_base") or "").rstrip("/")
        remote_path = str(connection.get(path_key) or "")
        if remote_path.startswith("http://") or remote_path.startswith("https://"):
            return remote_path
        return urljoin(base_url + "/", remote_path.lstrip("/"))

    def _handle_trainee_model_initialize(self, payload: Mapping[str, Any]) -> None:
        if self._ctx.role != "trainee":
            raise JsonApiError(404, "Unknown API route: /api/trainee/model-initialize")
        target = self._target_service(payload)
        if target.trainee_receive_state().get("active"):
            raise JsonApiError(409, "当前模型正在接收中，不能执行模型初始化。")

        connection = self._resolve_trainee_connection(
            str(payload.get("link", payload.get("interaction_link", "")))
        )
        archive_url = self._connection_url(connection, "definition_archive_path")
        archive_payload = self._json_request_to_url(archive_url, timeout=30.0)
        if not isinstance(archive_payload, Mapping):
            raise JsonApiError(502, "模拟台定义下载接口返回内容不是对象")
        data_base64 = str(archive_payload.get("data_base64") or "")
        if not data_base64:
            raise JsonApiError(502, "模拟台定义下载接口未返回定义压缩包")
        try:
            archive_data = base64.b64decode(data_base64, validate=True)
        except (ValueError, TypeError) as exc:
            raise JsonApiError(502, "模拟台返回的定义压缩包编码无效") from exc

        exchange_invalidated = False
        try:
            # Download and archive parsing stay outside the mutation locks.
            parsed_archive = _parse_definition_archive(archive_data)
            # Global mutation order: definition -> service -> exchange.
            with target.definition_update_lock:
                with target.lock:
                    _require_active_service_instance_locked(target)
                    if target.trainee_receive_state().get("active"):
                        raise JsonApiError(409, "当前模型正在接收中，不能执行模型初始化。")
                    imported = _apply_parsed_definition_archive_locked(target, parsed_archive)
                    target._clear_command_history()
                    receive_state = target.set_trainee_receive_state(
                        {
                            "initialized": True,
                            "initialized_at": datetime.now().isoformat(timespec="seconds"),
                            "active": False,
                            "frozen": False,
                            "interaction_link": connection["link"],
                            "teacher_api_base": connection["teacher_api_base"],
                            "teacher_model_id": connection["model_id"],
                            "teacher_model_name": connection["model_name"],
                            "snapshot_path": connection["snapshot_path"],
                            "command_path": connection["command_path"],
                            "measurement_delta_path": connection["measurement_delta_path"],
                            "definition_archive_path": connection["definition_archive_path"],
                            "last_receive_at": "",
                        }
                    )
                    if self._ctx.exchange is not None:
                        invalidate = getattr(self._ctx.exchange, "invalidate_model_for_service", None)
                        if callable(invalidate):
                            invalidate(target)
                            exchange_invalidated = True
        except JsonApiError:
            raise
        except (ValueError, OSError) as exc:
            raise JsonApiError(400, str(exc)) from exc

        if self._ctx.exchange is not None and not exchange_invalidated:
            self._ctx.exchange.invalidate_model(target.model_id)
        self._send_json(
            {
                "model": target.model_info(),
                "selected_model_id": target.model_id,
                "connection": connection,
                "receive_state": receive_state,
                "imported": imported,
                **self._model_catalog(),
            }
        )

    def _handle_trainee_receive(self, payload: Mapping[str, Any]) -> None:
        if self._ctx.role != "trainee":
            raise JsonApiError(404, "Unknown API route: /api/trainee/receive")
        target = self._target_service(payload)
        raw_active = payload.get("active", True)
        active = raw_active if isinstance(raw_active, bool) else str(raw_active).strip().lower() not in {
            "",
            "0",
            "false",
            "no",
            "off",
        }
        exchange_notified = False
        with target.lock:
            _require_active_service_instance_locked(target)
            receive_state = target.trainee_receive_state()
            if active:
                required = (
                    receive_state.get("initialized"),
                    receive_state.get("interaction_link"),
                    receive_state.get("teacher_api_base"),
                    receive_state.get("snapshot_path"),
                )
                if not all(required):
                    raise JsonApiError(409, "请先完成当前本地模型的模型初始化，再启动接收。")
                if self._ctx.exchange is not None:
                    invalidate = getattr(self._ctx.exchange, "invalidate_model_for_service", None)
                    if callable(invalidate):
                        # A receive start is a new local history lifecycle. Clear
                        # cached snapshots and measurement history before the
                        # active flag can wake the backend polling worker.
                        invalidate(target)
                    elif self._ctx.captured_service_is_current(target):
                        self._ctx.exchange.invalidate_model(target.model_id)
            next_state = target.set_trainee_receive_state(
                {
                    "active": active,
                    "frozen": not active,
                }
            )
            if self._ctx.exchange is not None:
                notify = getattr(self._ctx.exchange, "notify_receive_state_changed_for_service", None)
                if callable(notify):
                    notify(target)
                    exchange_notified = True
        if self._ctx.exchange is not None and not exchange_notified:
            if self._ctx.captured_service_is_current(target):
                self._ctx.exchange.receive_state_changed(target.model_id)
        if self._ctx.renewable_manager is not None:
            notify_renewable = getattr(
                self._ctx.renewable_manager,
                "receive_state_changed_for_service",
                None,
            )
            if callable(notify_renewable):
                try:
                    notify_renewable(target)
                except RuntimeError:
                    pass
            elif self._ctx.captured_service_is_current(target):
                self._ctx.renewable_manager.receive_state_changed(target.model_id)
        self._send_json(next_state)

    def _frame_cache_key(self, target: PolarMicrogridSimulator, scope: str) -> Optional[tuple[Any, ...]]:
        """构造高频只读接口的帧级缓存键；任意运行态或定义版本变化即自动失效。"""
        clock = getattr(target, "clock", None)
        def_snap = getattr(target, "definition_snapshot", None)
        if clock is None or def_snap is None:
            return None
        return (
            scope,
            id(target),
            getattr(target, "service_instance_id", ""),
            self._ctx.role,
            self.path,
            clock.step_count,
            clock.run_id,
            clock.state,
            clock.speed,
            clock.absolute_minute,
            clock.updated_at,
            def_snap.revision,
            getattr(target, "_measurement_delta_seq", 0),
            getattr(target, "_runtime_log_seq", 0),
            getattr(target, "_curve_revision", 0),
            getattr(target, "_command_mutation_seq", 0),
            len(getattr(target, "command_history", ())),
            bool(getattr(target, "_automatic_runtime_state_invalidated", False)),
            getattr(target, "_remote_adjustment_cycle_seq", 0),
        )

    def _trainee_frame_cache_key(
        self,
        target: PolarMicrogridSimulator,
        scope: str,
        *,
        extra: Any = "",
    ) -> Optional[tuple[Any, ...]]:
        """构造学员端 ui-frame / renewable-control 帧缓存键，纳入断连错误与墙钟超时/冻结状态。"""
        base_key = self._frame_cache_key(target, scope)
        if base_key is None:
            return None
        ex_rev: Any = None
        if self._ctx.exchange is not None:
            try:
                token_fn = getattr(self._ctx.exchange, "cache_version_token", None)
                if callable(token_fn):
                    ex_rev = token_fn(target.model_id)
                else:
                    ex_state = self._ctx.exchange._states.get(target.model_id)
                    if ex_state is not None:
                        ex_rev = (
                            ex_state.revision,
                            ex_state.receive_epoch,
                            ex_state.frame_identity,
                            getattr(ex_state, "last_error", ""),
                            getattr(ex_state, "consecutive_failures", 0),
                        )
            except Exception:
                return None
        rc_rev: Any = None
        if self._ctx.renewable_manager is not None:
            try:
                token_fn = getattr(self._ctx.renewable_manager, "cache_version_token", None)
                if callable(token_fn):
                    rc_rev = token_fn(target.model_id)
                else:
                    rc_state = self._ctx.renewable_manager._states.get(target.model_id)
                    if rc_state is not None:
                        rc_rev = (
                            rc_state.revision,
                            rc_state.plan_revision,
                            rc_state.settings_revision,
                        )
            except Exception:
                return None
        return (*base_key, ex_rev, rc_rev, extra)

    def _try_send_cached_json(self, cache_key: Optional[tuple[Any, ...]]) -> bool:
        """尝试命中帧级预编码缓存并支持 If-None-Match → 304 零字节短路。"""
        if cache_key is None:
            return False
        cached = self._ctx.response_cache.get_with_etag(cache_key)
        if cached is None:
            return False
        send_preencoded_json_response(
            self,
            cached[0],
            cached[1],
            status=200,
            cors_fn=self._cors,
            etag=cached[2],
        )
        return True

    def _send_cached_json(self, cache_key: Optional[tuple[Any, ...]], payload: Any) -> None:
        if cache_key is None:
            self._send_json(payload)
            return
        raw_bytes, gzip_bytes = encode_json_for_cache(payload)
        etag = self._ctx.response_cache.put(cache_key, raw_bytes, gzip_bytes)
        send_preencoded_json_response(
            self,
            raw_bytes,
            gzip_bytes,
            status=200,
            cors_fn=self._cors,
            etag=etag,
        )

    def _handle_api_get(self) -> None:
        path = urlparse(self.path).path
        target = self._target_service()
        if path == "/api/health":
            health = {
                "ok": True,
                "role": self._ctx.role,
                "model_id": target.model_id,
                "model_name": target.model_name,
                "snapshot": {
                    "model": {"id": target.model_id},
                    "clock": target.clock_state(),
                },
                "process": _process_health_payload(
                    role=self._ctx.role,
                    target=target,
                    exchange=self._ctx.exchange,
                    renewable_manager=self._ctx.renewable_manager,
                ),
                "compute": dict(getattr(target, "latest_compute", {}) or {}),
            }
            runner = getattr(target, "kernel_runner", None)
            diagnostics = getattr(runner, "diagnostics", None)
            if callable(diagnostics):
                health["power_flow_worker"] = diagnostics()
            self._send_json(health)
        elif path == RENEWABLE_CONTROL_TREND_PATH:
            self._send_json(self._renewable_trend_payload(target))
        elif path == RENEWABLE_CONTROL_PATH:
            force_refresh = self._truthy_query("refresh")
            rc_cache_key = (
                None
                if force_refresh
                else self._trainee_frame_cache_key(target, "renewable_control")
            )
            if self._try_send_cached_json(rc_cache_key):
                return
            self._send_cached_json(rc_cache_key, self._renewable_state_payload(target))
        elif path == TRAINEE_UI_FRAME_PATH:
            if self._ctx.role != "trainee":
                raise JsonApiError(404, f"Unknown API route: {path}")
            force_refresh = self._truthy_query("refresh")
            rev_getter = getattr(target, "trainee_receive_revision", None)
            receive_state: Optional[Dict[str, Any]] = None
            if callable(rev_getter):
                receive_state_revision = f"r{rev_getter()}"
            else:
                receive_state = target.trainee_receive_state()
                receive_state_revision = hashlib.sha256(
                    json.dumps(
                        receive_state,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()[:20]
            ui_cache_key = (
                None
                if force_refresh
                else self._trainee_frame_cache_key(
                    target, "trainee_ui_frame", extra=receive_state_revision
                )
            )
            if self._try_send_cached_json(ui_cache_key):
                return
            if receive_state is None:
                receive_state = target.trainee_receive_state()
            query = parse_qs(urlparse(self.path).query)
            after_receive_state_revision = str(
                (query.get("after_receive_state_revision") or [""])[0]
            ).strip()
            frame: Dict[str, Any] = {
                "encoding": "trainee-ui-frame-v1",
                "receive_state_revision": receive_state_revision,
            }
            if after_receive_state_revision != receive_state_revision:
                frame["receive_state"] = receive_state
            if receive_state.get("active"):
                frame["snapshot"] = self._trainee_snapshot_payload(target)
            if str((query.get("view") or [""])[0]).strip() == "renewable":
                frame["renewable_control"] = self._renewable_state_payload(target)
            self._send_cached_json(ui_cache_key, frame)
        elif path == "/api/models":
            self._send_json(self._model_catalog())
        elif path == MANUAL_DEFINITION_CHANGES_PATH:
            self._send_json(target.manual_definition_changes())
        elif path == "/api/snapshot":
            snap_cache_key = self._frame_cache_key(target, "snapshot")
            if self._try_send_cached_json(snap_cache_key):
                return
            lite = self._truthy_query("lite")
            trainee_view = self._truthy_query("trainee_view")
            compact_device_runtime = self._truthy_query("device_runtime_compact")
            supplement_device_runtime = self._truthy_query("device_runtime_supplement")
            include_static, static_fields = self._static_query(default_include_static=not lite)
            default_log_limit = 20 if lite else 300
            log_limit = self._int_query("log_limit", default_log_limit)
            include_runtime_logs = not (
                self._falsey_query("logs") or self._falsey_query("runtime_logs")
            )
            runtime_log_after_seq = self._optional_int_query("runtime_log_after_seq")
            snapshot_query = parse_qs(urlparse(self.path).query)
            after_command_signature = str(
                (snapshot_query.get("after_command_signature") or [""])[0]
            ).strip()
            after_device_runtime_signature = str(
                (snapshot_query.get("after_device_runtime_signature") or [""])[0]
            ).strip()
            snapshot_payload = target.snapshot(
                include_static=include_static,
                runtime_log_limit=log_limit,
                include_runtime_logs=(
                    include_runtime_logs and runtime_log_after_seq is None
                ),
                include_measurements=not self._falsey_query("measurements"),
                include_static_meta=not self._falsey_query("static_meta"),
                static_fields=static_fields,
                include_devices=(
                    not compact_device_runtime and not self._falsey_query("devices")
                ),
                include_device_states=(
                    not compact_device_runtime and not self._falsey_query("device_states")
                ),
                include_commands=not self._falsey_query("commands"),
                include_command_history=not self._falsey_query("command_history"),
            )
            measurement_after_seq = self._optional_int_query("measurement_after_seq")
            periodic_trainee_frame = bool(
                trainee_view
                and lite
                and measurement_after_seq is not None
                and compact_device_runtime
            )
            if measurement_after_seq is not None:
                snapshot_payload["measurement_delta"] = target.measurement_delta(
                    after_seq=max(0, measurement_after_seq),
                    compact=self._truthy_query("measurement_compact"),
                )
            if include_runtime_logs and runtime_log_after_seq is not None:
                snapshot_payload["runtime_logs_delta"] = target.runtime_logs_delta(
                    after_seq=max(0, runtime_log_after_seq),
                    limit=log_limit,
                )
            if trainee_view:
                strip_trainee_remote_details_from_snapshot(snapshot_payload)
            elif self._ctx.role == "trainee":
                strip_trainee_truth_from_snapshot(snapshot_payload)
            commands_payload = snapshot_payload.get("commands")
            if isinstance(commands_payload, Mapping):
                cmd_cache_key = (
                    getattr(target.clock, "run_id", 0),
                    getattr(target.clock, "step_count", 0),
                    getattr(target, "_command_mutation_seq", 0),
                    len(getattr(target, "command_history", ())),
                    getattr(target, "_remote_adjustment_cycle_seq", 0),
                    not self._falsey_query("command_history"),
                    bool(trainee_view),
                )
                cached_cmd_sig = getattr(target, "_command_signature_cache", None)
                if cached_cmd_sig is not None and cached_cmd_sig[0] == cmd_cache_key:
                    command_signature = cached_cmd_sig[1]
                else:
                    command_signature = command_payload_signature(commands_payload)
                    target._command_signature_cache = (cmd_cache_key, command_signature)
                snapshot_payload["command_signature"] = command_signature
                if after_command_signature == command_signature:
                    snapshot_payload.pop("commands", None)
            if compact_device_runtime:
                if periodic_trainee_frame or supplement_device_runtime:
                    sup_cache_key = (
                        getattr(target.clock, "run_id", 0),
                        getattr(target.clock, "step_count", 0),
                        target.definition_snapshot.revision,
                        getattr(target, "_measurement_delta_seq", 0),
                        getattr(target, "_command_mutation_seq", 0),
                        len(getattr(target, "command_history", ())),
                        getattr(target, "_remote_adjustment_cycle_seq", 0),
                        bool(periodic_trainee_frame),
                    )
                    cached_sup = getattr(target, "_device_runtime_supplement_cache", None)
                    if cached_sup is not None and cached_sup[0] == sup_cache_key:
                        device_runtime_frame = cached_sup[1]
                    else:
                        with target.lock:
                            measurement_definitions = target.measurement_definitions()
                            if periodic_trainee_frame:
                                measurement_definitions = target.measurement_runtime_definitions(
                                    measurement_definitions
                                )
                            device_runtime_frame = compact_device_runtime_supplement_frame(
                                target.devices(),
                                target.device_states(),
                                measurement_definitions,
                                definition_revision=target.definition_snapshot.revision,
                            )
                        target._device_runtime_supplement_cache = (sup_cache_key, device_runtime_frame)
                else:
                    device_runtime_frame = target.device_runtime_frame()
                device_runtime_signature = str(
                    device_runtime_frame.get("runtime_signature", "")
                ).strip()
                snapshot_payload["device_runtime_signature"] = device_runtime_signature
                if after_device_runtime_signature != device_runtime_signature:
                    snapshot_payload["device_runtime"] = device_runtime_frame
            if periodic_trainee_frame:
                project_trainee_interstation_snapshot(snapshot_payload)
            self._send_cached_json(snap_cache_key, snapshot_payload)
        elif path == "/api/runtime-logs":
            self._send_json(
                target.runtime_logs_delta(
                    after_seq=self._int_query("after_seq", 0, 0, 2_000_000_000),
                    before_seq=self._optional_int_query("before_seq"),
                    limit=self._int_query("limit", 100, 1, 500),
                    log_type=(parse_qs(urlparse(self.path).query).get("type") or [""])[0],
                )
            )
        elif path == "/api/measurements":
            meas_cache_key = self._frame_cache_key(target, "measurements")
            if self._try_send_cached_json(meas_cache_key):
                return
            measurements_payload = target.measurements()
            if self._ctx.role == "trainee" or self._truthy_query("trainee_view"):
                measurements_payload = strip_trainee_truth_from_measurements(
                    measurements_payload
                )
            self._send_cached_json(meas_cache_key, measurements_payload)
        elif path == "/api/measurements/delta":
            delta_cache_key = self._frame_cache_key(target, "measurements-delta")
            if self._try_send_cached_json(delta_cache_key):
                return
            delta_payload = target.measurement_delta(
                after_seq=self._int_query("after_seq", 0, 0, 2_000_000_000),
                compact=self._truthy_query("compact"),
            )
            if self._ctx.role == "trainee" or self._truthy_query("trainee_view"):
                delta_payload = strip_trainee_truth_from_measurement_delta(delta_payload)
            self._send_cached_json(delta_cache_key, delta_payload)
        elif path == "/api/measurement-history":
            history_payload = target.measurement_history(
                indices=self._measurement_indices_query(),
                after_seq=self._int_query("after_seq", 0, 0, 2_000_000_000),
            )
            if self._ctx.role == "trainee" or self._truthy_query("trainee_view"):
                history_payload = strip_trainee_truth_from_measurement_history(
                    history_payload
                )
            self._send_json(history_payload)
        elif path == "/api/external/telemetry":
            self._send_json(target.latest_telemetry_values())
        elif path == "/api/external/devices":
            self._send_json(target.external_device_information())
        elif path == EXTERNAL_REALTIME_INPUTS_PATH:
            if self._ctx.role != "simulator":
                raise JsonApiError(404, f"Unknown API route: {path}")
            self._send_json(target.external_realtime_input_schema())
        elif path == "/api/external/telemetry/names":
            self._send_json(target.external_telemetry_names())
        elif path == "/api/external/telemetry/values":
            self._send_json(target.external_telemetry_frame())
        elif path == "/api/external/controls":
            self._send_json(target.latest_control_values())
        elif path == "/api/external/controls/names":
            self._send_json(target.external_control_names())
        elif path == "/api/devices":
            self._send_json({"devices": target.devices()})
        elif path == "/api/device-states":
            self._send_json({"device_states": target.device_states()})
        elif path == "/api/curves":
            self._send_json(target.curves)
        elif path == "/api/curves/summary":
            self._send_json(target.curves_summary())
        elif path == "/api/curves/series":
            values = parse_qs(urlparse(self.path).query)
            keys = [
                key.strip()
                for value in values.get("keys", [])
                for key in str(value).split(",")
                if key.strip()
            ]
            self._send_json(target.curves_series(keys))
        elif path == "/api/settings":
            self._send_json(target.local_settings)
        elif path == "/api/trainee/discover-simulator-services":
            self._send_json(_discover_local_simulator_services(self._ctx.sim_url))
        elif path == "/api/trainee/receive-state":
            self._send_json(target.trainee_receive_state())
        elif path == "/api/trainee/receive-states":
            if hasattr(self._ctx.service, "trainee_receive_states"):
                self._send_json({"items": self._ctx.service.trainee_receive_states()})  # type: ignore[union-attr]
            else:
                self._send_json({"items": {target.model_id: target.trainee_receive_state()}})
        elif path == "/api/trainee/diagnostics":
            if self._ctx.exchange is None:
                raise JsonApiError(404, f"Unknown API route: {path}")
            receive_status_for_service = getattr(
                self._ctx.exchange,
                "receive_status_for_service",
                None,
            )
            if callable(receive_status_for_service):
                diagnostics = receive_status_for_service(target)
            else:
                if not self._ctx.captured_service_is_current(target):
                    raise JsonApiError(
                        409,
                        "学员台诊断请求所属模型生命周期已失效或已退休。",
                    )
                diagnostics = self._ctx.exchange.receive_status(target.model_id)
            self._send_json(diagnostics)
        elif path == "/api/trainee/snapshot":
            self._send_json(self._trainee_snapshot_payload(target))
        elif path == "/api/trainee/measurements/delta":
            if self._ctx.exchange is None:
                raise JsonApiError(404, f"Unknown API route: {path}")
            delta_for_service = getattr(self._ctx.exchange, "measurement_delta_for_service", None)
            if callable(delta_for_service):
                delta_payload = delta_for_service(
                    target,
                    after_seq=self._int_query("after_seq", 0, 0, 2_000_000_000),
                    compact=self._truthy_query("compact"),
                )
            else:
                if not self._ctx.captured_service_is_current(target):
                    raise JsonApiError(
                        409,
                        "学员台量测增量请求所属模型生命周期已失效或已退休。",
                    )
                delta_options = {
                    "after_seq": self._int_query("after_seq", 0, 0, 2_000_000_000)
                }
                if self._truthy_query("compact"):
                    delta_options["compact"] = True
                delta_payload = self._ctx.exchange.measurement_delta(
                    target.model_id,
                    **delta_options,
                )
            self._send_json(strip_trainee_truth_from_measurement_delta(delta_payload))
        elif path == "/api/trainee/measurement-history":
            if self._ctx.exchange is None:
                raise JsonApiError(404, f"Unknown API route: {path}")
            history_for_service = getattr(self._ctx.exchange, "measurement_history_for_service", None)
            if callable(history_for_service):
                history_payload = history_for_service(
                    target,
                    indices=self._measurement_indices_query(),
                    after_seq=self._int_query("after_seq", 0, 0, 2_000_000_000),
                )
            else:
                history_payload = self._ctx.exchange.measurement_history(
                    target.model_id,
                    indices=self._measurement_indices_query(),
                    after_seq=self._int_query("after_seq", 0, 0, 2_000_000_000),
                )
            self._send_json(strip_trainee_truth_from_measurement_history(history_payload))
        elif path in ("/api/trainee-link", "/api/client-link"):
            link_query = parse_qs(urlparse(self.path).query)
            if not hasattr(self._ctx.service, "service_for") and any(
                key in link_query for key in ("model_id", "model")
            ):
                raise JsonApiError(
                    400,
                    "单模型模拟服务交互链接不接受 model_id，请直接使用 /api/trainee-link。",
                )
            self._send_json(self._trainee_link_payload(target))
        elif path == "/api/config":
            runtime_settings = target.web_runtime_settings(self._ctx.role)["settings"]
            self._send_json(
                {
                    "role": self._ctx.role,
                    "sim_url": self._ctx.sim_url,
                    "poll_ms": int(float(runtime_settings["frontend_refresh_seconds"]) * 1000),
                    "system_parameters": target.system_parameters(),
                    **self._model_catalog(),
                }
            )
        elif path == LOCAL_RUNTIME_SETTINGS_PATH:
            self._send_json(target.web_runtime_settings(self._ctx.role))
        elif path == "/api/export-definitions":
            parsed = urlparse(self.path)
            response_format = (parse_qs(parsed.query).get("format") or ["zip"])[0]
            if response_format == "json":
                self._send_definition_archive_json(target)
            else:
                self._send_definition_archive(target)
        else:
            raise JsonApiError(404, f"Unknown API route: {path}")

    def _handle_api_post(self) -> None:
        path = urlparse(self.path).path
        payload = self._read_json_body()
        if path == RENEWABLE_CONTROL_PATH:
            if self._ctx.role != "trainee" or self._ctx.renewable_manager is None:
                raise JsonApiError(404, f"Unknown API route: {path}")
            try:
                result = self._ctx.renewable_manager.apply_action(
                    self._request_model_id(payload),
                    payload,
                )
            except ValueError as exc:
                raise JsonApiError(400, str(exc)) from exc
            if self._falsey_query("trend") and isinstance(result, Mapping):
                result = dict(result)
                for trend_key in (
                    "trend",
                    "trendEncoding",
                    "trendFields",
                    "trendRows",
                    "trendMissing",
                    "trendReset",
                ):
                    result.pop(trend_key, None)
            self._send_json(result)
            return
        if path == "/api/trainee/model-initialize":
            self._handle_trainee_model_initialize(payload)
            return
        if path == "/api/trainee/receive":
            self._handle_trainee_receive(payload)
            return
        if path == "/api/trainee/models/create":
            if self._ctx.role != "trainee" or not hasattr(self._ctx.service, "create_model_slot"):
                raise JsonApiError(404, f"Unknown API route: {path}")
            model_name = str(payload.get("name", payload.get("model_name", ""))).strip()
            if not model_name:
                raise JsonApiError(400, "请输入新模型名称")
            try:
                model = self._ctx.service.create_model_slot(model_name)  # type: ignore[union-attr]
            except (ValueError, OSError) as exc:
                raise JsonApiError(400, str(exc)) from exc
            self._send_json(
                {
                    "model": model,
                    "selected_model_id": model["id"],
                    **self._model_catalog(),
                }
            )
            return
        if path == "/api/models/create":
            if not hasattr(self._ctx.service, "validate_new_model_name") or not hasattr(self._ctx.service, "models_root"):
                raise JsonApiError(400, "Current simulator does not support multiple model folders")
            model_name = str(payload.get("name", payload.get("model_name", ""))).strip()
            if not model_name:
                raise JsonApiError(400, "New model name is required")
            data_base64 = str(payload.get("data_base64", ""))
            if not data_base64:
                raise JsonApiError(400, "model.e data is required")
            try:
                model_data = base64.b64decode(data_base64, validate=True)
                model_text = _decode_uploaded_definition_text(model_data)
                diagram_svg_text = _decode_optional_svg_payload(payload)
                preflight = _preflight_model_import(
                    model_text,
                    diagram_svg_text=diagram_svg_text,
                    source_label=str(payload.get("filename") or "model.e"),
                )
                model = create_model_from_efile(
                    self._ctx.service,  # type: ignore[arg-type]
                    model_name,
                    model_text,
                    diagram_svg_text=diagram_svg_text,
                    preflight_result=preflight,
                )
            except ModelPreflightError as exc:
                raise JsonApiError(400, str(exc), {"validation": exc.validation}) from exc
            except (UnicodeDecodeError, ValueError, OSError) as exc:
                raise JsonApiError(400, str(exc)) from exc
            catalog = dict(self._model_catalog())
            catalog["active_model_id"] = model["id"]
            self._send_json({"model": model, "validation": model.get("validation"), **catalog})
            return
        if path == "/api/models/update-definitions":
            if not hasattr(self._ctx.service, "service_for") or not hasattr(self._ctx.service, "models_root"):
                raise JsonApiError(400, "Current simulator does not support multiple model folders")
            model_id = self._request_model_id(payload)
            if not str(model_id or "").strip():
                raise JsonApiError(400, "Model id is required")
            self._reject_active_trainee_receive_model(payload, "修改")
            data_base64 = str(payload.get("data_base64", ""))
            if not data_base64:
                raise JsonApiError(400, "model.e data is required")
            try:
                model_data = base64.b64decode(data_base64, validate=True)
                model_text = _decode_uploaded_definition_text(model_data)
                diagram_svg_text = _decode_optional_svg_payload(payload)
                target_service = self._ctx.service.service_for(model_id)  # type: ignore[union-attr]
                candidate_diagram = diagram_svg_text
                if candidate_diagram is None:
                    current_diagram_path = Path(target_service.sim_dir) / DIAGRAM_FILE_NAME
                    if current_diagram_path.exists() and current_diagram_path.is_file():
                        candidate_diagram = current_diagram_path.read_text(encoding="utf-8-sig")
                preflight = _preflight_model_import(
                    model_text,
                    diagram_svg_text=candidate_diagram,
                    source_label=str(payload.get("filename") or "model.e"),
                )
                model = update_model_from_efile(
                    self._ctx.service,  # type: ignore[arg-type]
                    model_id,
                    model_text,
                    diagram_svg_text=diagram_svg_text,
                    replace_diagram=bool(payload.get("replace_diagram", False)),
                    preflight_result=preflight,
                )
            except ModelPreflightError as exc:
                raise JsonApiError(400, str(exc), {"validation": exc.validation}) from exc
            except (UnicodeDecodeError, ValueError, OSError, KeyError) as exc:
                raise JsonApiError(400, str(exc)) from exc
            catalog = dict(self._model_catalog())
            catalog["active_model_id"] = model["id"]
            self._send_json(
                {
                    "model": model,
                    "updated": model["updated"],
                    "validation": model.get("validation"),
                    **catalog,
                }
            )
            return
        if path == "/api/models/clone":
            if not hasattr(self._ctx.service, "clone_model"):
                raise JsonApiError(400, "Current simulator does not support multiple model folders")
            model_name = payload.get("name", payload.get("model_name", payload.get("new_model_id", "")))
            if not str(model_name or "").strip():
                raise JsonApiError(400, "New model name is required")
            try:
                model = self._ctx.service.clone_model(self._request_model_id(payload), model_name)  # type: ignore[union-attr]
            except ValueError as exc:
                raise JsonApiError(400, str(exc)) from exc
            catalog = dict(self._model_catalog())
            catalog["active_model_id"] = model["id"]
            self._send_json({"model": model, **catalog})
            return
        if path == "/api/models/delete":
            if not hasattr(self._ctx.service, "delete_model"):
                raise JsonApiError(400, "Current simulator does not support multiple model folders")
            model_id = self._request_model_id(payload)
            if not str(model_id or "").strip():
                raise JsonApiError(400, "Model id is required")
            try:
                old_service = self._ctx.service.service_for(model_id)  # type: ignore[union-attr]
                if old_service.trainee_receive_state().get("active"):
                    raise JsonApiError(400, "模型正在接收中，不能删除。")
                deleted = self._ctx.service.delete_model(model_id)  # type: ignore[union-attr]
            except JsonApiError:
                raise
            except KeyError as exc:
                raise JsonApiError(404, str(exc)) from exc
            except ValueError as exc:
                raise JsonApiError(400, str(exc)) from exc
            for lifecycle_owner in (self._ctx.exchange, self._ctx.renewable_manager):
                remove = getattr(lifecycle_owner, "remove_model_for_service", None)
                if callable(remove):
                    remove(old_service)
            catalog = dict(self._model_catalog())
            catalog["active_model_id"] = deleted.get("active_model_id", catalog.get("active_model_id"))
            self._send_json({"deleted": deleted, **catalog})
            return
        if path == "/api/models/import-definitions":
            data_base64 = str(payload.get("data_base64", ""))
            if not data_base64:
                raise JsonApiError(400, "Definition archive data is required")
            try:
                archive_data = base64.b64decode(data_base64, validate=True)
                if payload.get("create_model"):
                    if not hasattr(self._ctx.service, "clone_model"):
                        raise ValueError("Current simulator does not support multiple model folders")
                    model_name = str(payload.get("name", payload.get("model_name", ""))).strip()
                    if not model_name:
                        raise ValueError("New model name is required")
                    model = import_definition_model(
                        self._ctx.service,  # type: ignore[arg-type]
                        self._request_model_id(payload),
                        model_name,
                        archive_data,
                        source_label=str(payload.get("filename") or "definitions.zip/model.e"),
                    )
                    catalog = dict(self._model_catalog())
                    catalog["active_model_id"] = model["id"]
                    self._send_json(
                        {
                            "model": model,
                            "imported": model["imported"],
                            "validation": model.get("validation"),
                            **catalog,
                        }
                    )
                    return
                self._reject_active_trainee_receive_model(payload, "修改")
                imported = import_definition_archive(
                    self._target_service(payload),
                    archive_data,
                    source_label=str(payload.get("filename") or "definitions.zip/model.e"),
                )
            except ModelPreflightError as exc:
                raise JsonApiError(400, str(exc), {"validation": exc.validation}) from exc
            except (ValueError, OSError) as exc:
                raise JsonApiError(400, str(exc)) from exc
            self._send_json(
                {
                    "imported": imported,
                    "validation": imported.get("validation"),
                    **self._model_catalog(),
                }
            )
            return

        if path == "/api/trainee/connect":
            self._handle_trainee_connect(payload)
            return

        target = self._target_service(payload)
        if path in DEFINITION_EDIT_PATHS:
            try:
                if path == "/api/definitions/device-parameters":
                    result = target.update_device_parameters(
                        payload,
                        allow_runtime_controls=self._ctx.role != "trainee",
                    )
                elif path == "/api/definitions/measurement":
                    result = target.update_measurement_definition(payload)
                elif path == "/api/definitions/manual-changes/retry":
                    result = target.retry_manual_definition_changes(payload)
                else:
                    result = target.reset_manual_definition_changes(payload)
            except DefinitionRevisionConflict as exc:
                raise JsonApiError(
                    409,
                    str(exc),
                    {
                        "expected_revision": exc.expected_revision,
                        "current_revision": exc.current_revision,
                    },
                ) from exc
            except ServiceInstanceRetiredError as exc:
                raise JsonApiError(409, str(exc)) from exc
            except (KeyError, ValueError) as exc:
                raise JsonApiError(400, str(exc)) from exc
            self._send_json(result)
        elif path == "/api/student/commands":
            try:
                result = target.apply_student_commands(
                    payload,
                    source=str(payload.get("source", "")),
                )
            except ValueError as exc:
                raise JsonApiError(400, str(exc)) from exc
            self._send_json(result)
        elif path == SIMULATOR_COMMAND_DELETE_PATH:
            if self._ctx.role != "simulator":
                raise JsonApiError(404, f"Unknown API route: {path}")
            self._send_json(target.delete_active_commands(payload, source="simulator-ui"))
        elif path == "/api/trainee/receive-state":
            exchange_notified = False
            with target.lock:
                _require_active_service_instance_locked(target)
                receive_state = target.set_trainee_receive_state(payload)
                if self._ctx.exchange is not None:
                    notify = getattr(self._ctx.exchange, "notify_receive_state_changed_for_service", None)
                    if callable(notify):
                        notify(target)
                        exchange_notified = True
            if self._ctx.exchange is not None and not exchange_notified:
                if self._ctx.captured_service_is_current(target):
                    self._ctx.exchange.receive_state_changed(target.model_id)
            if self._ctx.renewable_manager is not None:
                notify_renewable = getattr(
                    self._ctx.renewable_manager,
                    "receive_state_changed_for_service",
                    None,
                )
                if callable(notify_renewable):
                    try:
                        notify_renewable(target)
                    except RuntimeError:
                        pass
                elif self._ctx.captured_service_is_current(target):
                    self._ctx.renewable_manager.receive_state_changed(target.model_id)
            self._send_json(receive_state)
        elif path == "/api/trainee/commands":
            if self._ctx.exchange is None:
                raise JsonApiError(404, f"Unknown API route: {path}")
            submit_for_service = getattr(self._ctx.exchange, "submit_commands_for_service", None)
            try:
                if callable(submit_for_service):
                    result = submit_for_service(target, payload)
                else:
                    if not self._ctx.captured_service_is_current(target):
                        raise JsonApiError(
                            409,
                            "学员台指令请求所属模型生命周期已失效或已退休。",
                        )
                    result = self._ctx.exchange.submit_commands(target.model_id, payload)
            except (ServiceInstanceRetiredError, TraineeExchangeLifecycleError) as exc:
                raise JsonApiError(409, str(exc)) from exc
            self._send_json(result)
        elif path == "/api/external/telemetry/query":
            self._send_json(target.selected_telemetry_values(payload))
        elif path == "/api/external/telemetry/values/query":
            self._send_json(target.selected_external_telemetry_frame(payload))
        elif path == "/api/external/telemetry/history/query":
            if self._ctx.role != "simulator":
                raise JsonApiError(404, f"Unknown API route: {path}")
            try:
                result = target.external_measurement_history(payload)
            except ValueError as exc:
                raise JsonApiError(400, str(exc), target._external_response_metadata()) from exc
            self._send_json(result)
        elif path == "/api/external/curves/query":
            if self._ctx.role != "simulator":
                raise JsonApiError(404, f"Unknown API route: {path}")
            try:
                result = target.external_curves_query(payload)
            except ValueError as exc:
                raise JsonApiError(400, str(exc), target._external_response_metadata()) from exc
            self._send_json(result)
        elif path in ("/api/external/curves/update", "/api/external/curves/updat"):
            if self._ctx.role != "simulator":
                raise JsonApiError(404, f"Unknown API route: {path}")
            try:
                result = target.external_curves_update(payload)
            except ValueError as exc:
                raise JsonApiError(400, str(exc), target._external_response_metadata()) from exc
            self._send_json(result)
        elif path == EXTERNAL_REALTIME_INPUTS_PATH:
            if self._ctx.role != "simulator":
                raise JsonApiError(404, f"Unknown API route: {path}")
            try:
                result = target.apply_external_realtime_inputs(payload)
            except ValueError as exc:
                raise JsonApiError(400, str(exc), target._external_response_metadata()) from exc
            self._send_json(result)
        elif path == "/api/external/controls":
            self._send_json(target.apply_external_control_values(payload))
        elif path == "/api/external/controls/execute":
            requested_model = self._request_model_id(payload)
            if requested_model is not None and requested_model != target.model_id:
                raise JsonApiError(409, "控制指令所属模型与当前服务不一致")
            try:
                result = target.apply_external_control_frame(payload)
            except ValueError as exc:
                raise JsonApiError(400, str(exc), target._external_response_metadata()) from exc
            self._send_json(result)
        elif path == "/api/clock":
            self._send_json(target.control_clock(payload))
        elif path == "/api/config":
            self._send_json(target.set_system_parameters(payload))
        elif path == LOCAL_RUNTIME_SETTINGS_PATH:
            try:
                if self._ctx.role == "trainee" and self._ctx.renewable_manager is not None:
                    self._ctx.renewable_manager.validate_runtime_settings_update_for_service(
                        target,
                        payload,
                    )
                result = target.set_web_runtime_settings(self._ctx.role, payload)
            except ServiceInstanceRetiredError as exc:
                raise JsonApiError(409, str(exc)) from exc
            except ValueError as exc:
                raise JsonApiError(400, str(exc)) from exc
            if self._ctx.exchange is not None:
                notify_for_service = getattr(
                    self._ctx.exchange,
                    "runtime_settings_changed_for_service",
                    None,
                )
                if callable(notify_for_service):
                    notify_for_service(target)
                elif self._ctx.captured_service_is_current(target):
                    notify = getattr(self._ctx.exchange, "runtime_settings_changed", None)
                    if callable(notify):
                        notify(target.model_id)
            if self._ctx.role == "trainee" and self._ctx.renewable_manager is not None:
                self._ctx.renewable_manager.runtime_settings_changed_for_service(target)
            self._send_json(result)
        elif path == "/api/runtime-logs/clear":
            self._send_json(target.clear_runtime_logs())
        elif path == "/api/step":
            self._send_json(target.step())
        elif path == "/api/curves":
            self._send_json(target.set_curves(payload))
        elif path == "/api/curves/series":
            self._send_json(target.update_curve_series(payload))
        elif path == "/api/settings":
            self._send_json(target.set_local_settings(payload))
        elif path == "/api/device-faults":
            self._send_json(target.set_local_settings({"device_faults": payload.get("items", payload)}))
        elif path == "/api/measurement-faults":
            self._send_json(target.set_local_settings({"measurement_faults": payload.get("items", payload)}))
        elif path == "/api/modes":
            self._send_json(target.set_local_settings({"modes": payload.get("items", payload)}))
        else:
            raise JsonApiError(404, f"Unknown API route: {path}")

    def _read_json_body(self) -> Mapping[str, Any]:
        path = urlparse(self.path).path
        max_bytes = UPLOAD_MAX_JSON_BYTES if path in UPLOAD_POST_PATHS else DEFAULT_MAX_JSON_BYTES
        try:
            return read_json_body(self.headers, self.rfile, max_bytes=max_bytes)
        except PayloadTooLargeError as exc:
            raise JsonApiError(413, str(exc)) from exc
        except ValueError as exc:
            raise JsonApiError(400, str(exc)) from exc

    def _serve_static(self, root: Path) -> None:
        served = self._ctx.static_cache.serve(
            self,
            root,
            self.path,
            cors_fn=lambda cc: self._cors(cache_control=cc),
            cache_control="no-cache",
        )
        if not served:
            path = urlparse(self.path).path
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            raise JsonApiError(404, f"Static file not found: {rel}")

    def _proxy_to_simulator(self, method: str, base_url: str) -> None:
        path = self.path
        body = None
        headers = {"Accept": "application/json"}
        if method in ("POST", "PUT"):
            route = urlparse(path).path
            max_bytes = UPLOAD_MAX_JSON_BYTES if route in UPLOAD_POST_PATHS else DEFAULT_MAX_JSON_BYTES
            try:
                length = parse_content_length(self.headers, max_bytes=max_bytes)
            except PayloadTooLargeError as exc:
                raise JsonApiError(413, str(exc)) from exc
            except ValueError as exc:
                raise JsonApiError(400, str(exc)) from exc
            body = self.rfile.read(length) if length else b"{}"
            headers["Content-Type"] = self.headers.get("Content-Type", "application/json")
        request = Request(urljoin(base_url + "/", path.lstrip("/")), data=body, headers=headers, method=method)
        try:
            with local_urlopen(request, timeout=10) as response:
                data = response.read()
                status = response.status
                content_type = response.headers.get("Content-Type", "application/json")
        except HTTPError as exc:
            data = exc.read()
            status = exc.code
            content_type = exc.headers.get("Content-Type", "application/json")
        except URLError as exc:
            raise JsonApiError(502, f"Simulator is unreachable: {exc}") from exc
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        safe_write_bytes(self, data)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        send_json_response(
            self,
            payload,
            status=status,
            compress=True,
            cors_fn=self._cors,
        )

    def _send_definition_archive(self, target: PolarMicrogridSimulator) -> None:
        filename, data = make_definition_archive(target)
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/zip")
        self.send_header(
            "Content-Disposition",
            f"attachment; filename=\"model_definitions.zip\"; filename*=UTF-8''{quote(filename)}",
        )
        self.send_header("Content-Length", str(len(data)))
        safe_write_bytes(self, data)

    def _send_definition_archive_json(self, target: PolarMicrogridSimulator) -> None:
        filename, data = make_definition_archive(target)
        self._send_json(
            {
                "filename": filename,
                "content_type": "application/zip",
                "data_base64": base64.b64encode(data).decode("ascii"),
            }
        )

    def _cors(self, *, cache_control: str = "no-store") -> None:
        apply_cors_headers(
            self,
            methods="GET, POST, PUT, OPTIONS",
            cache_control=cache_control,
        )


class ManagedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        context: _ServerContext,
    ) -> None:
        self._ctx = context
        self._trainee_exchange_closed = False
        self._renewable_manager_closed = False
        self._service_closed = False
        super().__init__(server_address, PolarMicrogridHandler)
        self.service = context.service
        self.trainee_exchange = context.exchange
        self.renewable_control_manager = context.renewable_manager

    def server_close(self) -> None:
        # 先中断学员台底层 HTTP 连接池在途 I/O，再关闭控制管理器，避免关停卡死等待完整超时。
        if self._ctx.exchange is not None and not self._trainee_exchange_closed:
            abort_fn = getattr(self._ctx.exchange, "abort_inflight_io", None)
            if callable(abort_fn):
                abort_fn()
        if self._ctx.renewable_manager is not None and not self._renewable_manager_closed:
            self._renewable_manager_closed = True
            self._ctx.renewable_manager.close()
        if self._ctx.exchange is not None and not self._trainee_exchange_closed:
            self._trainee_exchange_closed = True
            self._ctx.exchange.close()
        if not self._service_closed:
            self._service_closed = True
            close_service = getattr(self._ctx.service, "close", None)
            if callable(close_service):
                close_service()
        super().server_close()


def make_http_server(
    server_address: tuple[str, int],
    service: PolarMicrogridSimulator | MultiModelSimulator,
    *,
    role: str = "simulator",
    static_root: Optional[str | Path] = None,
    sim_url: Optional[str] = None,
    trainee_exchange: Optional[TraineeRealtimeExchange] = None,
    renewable_control_manager: Optional[TraineeRenewableControlManager] = None,
    direct_simulator_ui: bool = False,
) -> ThreadingHTTPServer:
    normalized_role = role.lower()
    resolved_static = (
        Path(static_root).resolve()
        if static_root is not None
        else (WEB_DIR / ("trainee" if normalized_role == "trainee" else "simulator")).resolve()
    )
    normalized_sim_url = sim_url.rstrip("/") if sim_url else None
    exchange = trainee_exchange
    if normalized_role == "trainee" and exchange is None:
        exchange = TraineeRealtimeExchange(service)
    renewable_manager = renewable_control_manager
    if normalized_role == "trainee" and renewable_manager is None:
        if exchange is None:  # pragma: no cover
            raise RuntimeError("学员台实时交换服务未初始化")
        renewable_manager = TraineeRenewableControlManager(
            service,
            snapshot_provider=exchange.control_snapshot,
            receive_status_provider=exchange.receive_status,
            command_sink=exchange.submit_commands,
        )
    context = _ServerContext(
        service=service,
        role=normalized_role,
        static_root=resolved_static,
        sim_url=normalized_sim_url,
        exchange=exchange,
        renewable_manager=renewable_manager,
        direct_simulator_ui=bool(direct_simulator_ui),
        static_cache=StaticAssetCache(),
        response_cache=EncodedResponseCache(),
    )
    return ManagedThreadingHTTPServer(server_address, context)
