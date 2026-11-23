"""共享的本机 HTTP 工具、静态资源缓存、请求体校验与 CORS 安全策略。"""

from __future__ import annotations

import gzip
import hashlib
import json
import mimetypes
import os
import threading
from collections import OrderedDict
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

CLIENT_DISCONNECT_ERRORS = (
    BrokenPipeError,
    ConnectionAbortedError,
    ConnectionResetError,
)

DEFAULT_MAX_JSON_BYTES = 8 * 1024 * 1024
UPLOAD_MAX_JSON_BYTES = 64 * 1024 * 1024
STATIC_CACHE_MAX_ENTRIES = 256
ENCODED_RESPONSE_CACHE_MAX_ENTRIES = 64

# 高频只读轮询接口白名单：200/204/304 成功响应降级为 DEBUG，避免淹没写操作与错误日志。
HIGH_FREQUENCY_POLL_GET_PATHS = frozenset(
    {
        "/api/health",
        "/api/models",
        "/api/simulator-services",
        "/api/snapshot",
        "/api/measurements",
        "/api/measurements/delta",
        "/api/runtime-logs",
        "/api/trainee/ui-frame",
        "/api/trainee/snapshot",
        "/api/trainee/measurements/delta",
        "/api/trainee/diagnostics",
        "/api/trainee/renewable-control",
        "/api/trainee/receive-state",
        "/api/trainee/receive-states",
        "/api/external/controls/names",
        "/api/simulator104/status",
        "/api/simulator104/points",
        "/api/simulator104/logs",
    }
)


def should_demote_access_log(method: str, request_path: str, status_code: Any) -> bool:
    """判断单次 HTTP 访问日志是否应降级为 DEBUG，消除高频轮询与 304 刷屏噪音。"""
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return False
    if str(method or "").upper() != "GET":
        return False
    if code == 304:
        return True
    if code not in (200, 204):
        return False
    path = urlparse(str(request_path or "")).path
    return path in HIGH_FREQUENCY_POLL_GET_PATHS


def compute_weak_etag(raw_bytes: bytes) -> str:
    """基于响应体字节快速计算轻量弱 ETag，用于 HTTP 304 协商缓存。"""
    digest = hashlib.blake2b(raw_bytes, digest_size=8).hexdigest()
    return f'W/"{digest}"'


def etag_matches(if_none_match: Optional[str], etag: str) -> bool:
    """按 RFC 7232 弱比较规则检查请求头 If-None-Match 是否命中当前 ETag。"""
    if not if_none_match or not etag:
        return False
    target = etag.strip()
    target_opaque = target[2:] if target.startswith("W/") else target
    for raw_token in str(if_none_match).split(","):
        token = raw_token.strip()
        if not token:
            continue
        if token == "*":
            return True
        token_opaque = token[2:] if token.startswith("W/") else token
        if token_opaque == target_opaque:
            return True
    return False


def is_mapping(value: Any) -> bool:
    """快路径判断对象是否为映射类型，避免在热循环中高频触发 typing.Mapping ABC 反射。"""
    return type(value) is dict or isinstance(value, dict) or isinstance(value, Mapping)


class EncodedResponseCache:
    """线程安全的 LRU 帧级 JSON / gzip / ETag 响应字节缓存，避免同一仿真步内重复序列化大快照。"""

    def __init__(self, max_entries: int = ENCODED_RESPONSE_CACHE_MAX_ENTRIES) -> None:
        self._lock = threading.RLock()
        self._entries: OrderedDict[Any, tuple[bytes, bytes, str]] = OrderedDict()
        self._max_entries = max(4, int(max_entries))

    def get(self, key: Any) -> Optional[tuple[bytes, bytes]]:
        with self._lock:
            item = self._entries.get(key)
            if item is None:
                return None
            self._entries.move_to_end(key)
            return item[0], item[1]

    def get_with_etag(self, key: Any) -> Optional[tuple[bytes, bytes, str]]:
        """获取缓存的 (raw_bytes, gzip_bytes, etag) 并刷新 LRU 顺序。"""
        with self._lock:
            item = self._entries.get(key)
            if item is None:
                return None
            self._entries.move_to_end(key)
            return item

    def put(
        self,
        key: Any,
        raw_bytes: bytes,
        gzip_bytes: bytes,
        etag: Optional[str] = None,
    ) -> str:
        resolved_etag = str(etag) if etag else compute_weak_etag(raw_bytes)
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
            elif len(self._entries) >= self._max_entries:
                self._entries.popitem(last=False)
            self._entries[key] = (raw_bytes, gzip_bytes, resolved_etag)
        return resolved_etag

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def send_preencoded_json_response(
    handler: Any,
    raw_bytes: bytes,
    gzip_bytes: bytes,
    *,
    status: int = 200,
    cors_fn: Optional[Callable[[], None]] = None,
    etag: str = "",
) -> bool:
    """直接发送已序列化/预压缩的 JSON 字节，支持 If-None-Match 命中 304 零字节短路。"""
    if status == 200 and etag and etag_matches(handler.headers.get("If-None-Match"), etag):
        try:
            handler.send_response(304)
            if cors_fn is not None:
                cors_fn()
            handler.send_header("ETag", etag)
            handler.send_header("Vary", "Accept-Encoding")
            handler.send_header("Content-Length", "0")
            return safe_write_bytes(handler, b"")
        except CLIENT_DISCONNECT_ERRORS:
            return False
    accepted = str(handler.headers.get("Accept-Encoding", "")).lower()
    use_gzip = bool(gzip_bytes and "gzip" in accepted)
    data = gzip_bytes if use_gzip else raw_bytes
    try:
        handler.send_response(status)
        if cors_fn is not None:
            cors_fn()
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        if etag:
            handler.send_header("ETag", etag)
        handler.send_header("Vary", "Accept-Encoding")
        if use_gzip:
            handler.send_header("Content-Encoding", "gzip")
        handler.send_header("Content-Length", str(len(data)))
        return safe_write_bytes(handler, data)
    except CLIENT_DISCONNECT_ERRORS:
        return False


def encode_json_for_cache(payload: Any) -> tuple[bytes, bytes]:
    """将载荷一次性序列化为 UTF-8 JSON 字节并按需预压缩为 gzip 字节。"""
    raw_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    gzip_bytes = b""
    if len(raw_bytes) >= 1024:
        compressed = gzip.compress(raw_bytes, compresslevel=1, mtime=0)
        if len(compressed) + 32 < len(raw_bytes):
            gzip_bytes = compressed
    return raw_bytes, gzip_bytes


class PayloadTooLargeError(ValueError):
    """当 HTTP 请求体超过允许上限时抛出，对应 HTTP 413。"""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = int(max_bytes)
        super().__init__(f"Request payload exceeds limit ({self.max_bytes} bytes)")


class _NoRedirectHandler(HTTPRedirectHandler):
    """禁止内部回环调用跟随任意 HTTP 重定向。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_LOCAL_OPENER = build_opener(ProxyHandler({}))
_LOCAL_NO_REDIRECT_OPENER = build_opener(ProxyHandler({}), _NoRedirectHandler())


def local_urlopen(
    request: str | Request,
    *,
    timeout: float = 10.0,
    allow_redirects: bool = True,
):
    """发起绕过系统代理的本机 HTTP 请求，避免全局代理劫持回环通信。"""
    opener = _LOCAL_OPENER if allow_redirects else _LOCAL_NO_REDIRECT_OPENER
    return opener.open(request, timeout=timeout)


def _extra_allowed_origins() -> set[str]:
    raw = os.environ.get("POWER_SIMU_CORS_ORIGINS", "")
    return {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}


def is_loopback_origin(origin: str) -> bool:
    """判断浏览器 Origin 是否属于本机回环来源（localhost / 127.0.0.1 / ::1）。"""
    text = str(origin or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def resolve_cors_origin(origin_header: Optional[str]) -> Optional[str]:
    """根据请求 Origin 计算允许回显的 CORS Origin，避免对任意第三方站点开放 `*`。"""
    origin = str(origin_header or "").strip().rstrip("/")
    if not origin:
        return None
    if is_loopback_origin(origin):
        return origin
    extra = _extra_allowed_origins()
    if "*" in extra:
        return "*"
    if origin in extra:
        return origin
    return None


def apply_cors_headers(
    handler: Any,
    *,
    methods: str = "GET, POST, OPTIONS",
    cache_control: str = "no-store",
) -> None:
    """为 HTTP 响应写入受控 CORS 与缓存头。"""
    allowed = resolve_cors_origin(handler.headers.get("Origin"))
    if allowed:
        handler.send_header("Access-Control-Allow-Origin", allowed)
        if allowed != "*":
            handler.send_header("Vary", "Origin")
    handler.send_header("Access-Control-Allow-Methods", methods)
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, If-None-Match")
    handler.send_header("Access-Control-Expose-Headers", "ETag")
    handler.send_header("Cache-Control", cache_control)


def parse_content_length(headers: Mapping[str, Any], *, max_bytes: int = DEFAULT_MAX_JSON_BYTES) -> int:
    """解析并校验 Content-Length，拦截负数、非数字及超大请求体。"""
    raw = headers.get("Content-Length")
    if raw is None or str(raw).strip() == "":
        return 0
    try:
        length = int(str(raw).strip())
    except ValueError as exc:
        raise ValueError("Invalid Content-Length header") from exc
    if length < 0:
        raise ValueError("Content-Length cannot be negative")
    if length > max_bytes:
        raise PayloadTooLargeError(max_bytes)
    return length


def read_json_body(
    headers: Mapping[str, Any],
    rfile: Any,
    *,
    max_bytes: int = DEFAULT_MAX_JSON_BYTES,
) -> Mapping[str, Any]:
    """带大小上限校验地读取并解析 JSON 对象请求体。"""
    length = parse_content_length(headers, max_bytes=max_bytes)
    if length <= 0:
        return {}
    raw = rfile.read(length)
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON payload: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("JSON payload must be an object")
    return payload


def safe_write_bytes(handler: Any, data: bytes) -> bool:
    """安全发送响应头与响应体；若客户端已主动断开则返回 False。"""
    try:
        handler.end_headers()
        if data:
            handler.wfile.write(data)
        return True
    except CLIENT_DISCONNECT_ERRORS:
        return False


def send_json_response(
    handler: Any,
    payload: Any,
    *,
    status: int = 200,
    compress: bool = True,
    cors_fn: Optional[Callable[[], None]] = None,
) -> bool:
    """序列化并发送 JSON 响应，支持 gzip 压缩并静默容忍客户端断连。"""
    data = json.dumps(
        payload,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    content_encoding = ""
    if compress and len(data) >= 1024:
        accepted = str(handler.headers.get("Accept-Encoding", "")).lower()
        if "gzip" in accepted:
            compressed = gzip.compress(data, compresslevel=1, mtime=0)
            if len(compressed) + 32 < len(data):
                data = compressed
                content_encoding = "gzip"
    try:
        handler.send_response(status)
        if cors_fn is not None:
            cors_fn()
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        if compress:
            handler.send_header("Vary", "Accept-Encoding")
        if content_encoding:
            handler.send_header("Content-Encoding", content_encoding)
        handler.send_header("Content-Length", str(len(data)))
        return safe_write_bytes(handler, data)
    except CLIENT_DISCONNECT_ERRORS:
        return False


def resolve_static_target(root: Path, request_path: str) -> Optional[Path]:
    """安全解析静态资源路径，使用 is_relative_to 防止兄弟目录前缀绕过。"""
    resolved_root = Path(root).resolve()
    path = urlparse(request_path).path
    relative = "index.html" if path in {"", "/"} else path.lstrip("/")
    target = (resolved_root / relative).resolve()
    if not target.is_relative_to(resolved_root) or not target.exists() or not target.is_file():
        fallback = resolved_root / "index.html"
        if fallback.exists() and fallback.is_file():
            return fallback
        return None
    return target


class StaticAssetCache:
    """线程安全的静态资源内存缓存，支持 mtime/size 校验、ETag 与 gzip 压缩。"""

    _COMPRESSIBLE_TYPES = frozenset(
        {
            "application/javascript",
            "text/javascript",
            "application/json",
            "application/xml",
            "image/svg+xml",
        }
    )

    def __init__(self, max_entries: int = STATIC_CACHE_MAX_ENTRIES) -> None:
        self._lock = threading.RLock()
        self._entries: dict[Path, dict[str, Any]] = {}
        self._max_entries = max(16, int(max_entries))

    def load(self, target: Path) -> dict[str, Any]:
        stat = target.stat()
        with self._lock:
            cached = self._entries.get(target)
            if (
                cached is not None
                and cached["mtime_ns"] == stat.st_mtime_ns
                and cached["size"] == stat.st_size
            ):
                return cached

        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        compressible = content_type.startswith("text/") or content_type in self._COMPRESSIBLE_TYPES
        gzip_data = b""
        if compressible and len(data) >= 512:
            candidate = gzip.compress(data, compresslevel=1, mtime=0)
            if len(candidate) + 32 < len(data):
                gzip_data = candidate
        loaded = {
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
            "content_type": content_type,
            "data": data,
            "gzip_data": gzip_data,
            "etag": f'"{hashlib.sha256(data).hexdigest()}"',
        }
        with self._lock:
            if len(self._entries) >= self._max_entries and target not in self._entries:
                self._entries.pop(next(iter(self._entries)))
            self._entries[target] = loaded
        return loaded

    def serve(
        self,
        handler: Any,
        root: Path,
        request_path: str,
        *,
        cors_fn: Optional[Callable[[str], None]] = None,
        cache_control: str = "no-cache",
    ) -> bool:
        """发送静态文件响应；文件缺失返回 False，已发送或断连返回 True。"""
        target = resolve_static_target(root, request_path)
        if target is None:
            return False
        asset = self.load(target)
        etag = str(asset["etag"])
        accepted = str(handler.headers.get("Accept-Encoding", "")).lower()
        use_gzip = bool(asset["gzip_data"] and "gzip" in accepted)
        data = asset["gzip_data"] if use_gzip else asset["data"]
        if etag_matches(handler.headers.get("If-None-Match"), etag):
            try:
                handler.send_response(304)
                if cors_fn is not None:
                    cors_fn(cache_control)
                handler.send_header("ETag", etag)
                handler.send_header("Vary", "Accept-Encoding")
                handler.send_header("Content-Length", "0")
                safe_write_bytes(handler, b"")
            except CLIENT_DISCONNECT_ERRORS:
                pass
            return True
        try:
            handler.send_response(200)
            if cors_fn is not None:
                cors_fn(cache_control)
            handler.send_header("Content-Type", str(asset["content_type"]))
            handler.send_header("ETag", etag)
            handler.send_header("Vary", "Accept-Encoding")
            if use_gzip:
                handler.send_header("Content-Encoding", "gzip")
            handler.send_header("Content-Length", str(len(data)))
            safe_write_bytes(handler, data)
        except CLIENT_DISCONNECT_ERRORS:
            pass
        return True


class JsonApiError(Exception):
    """结构化 HTTP JSON API 异常。"""

    def __init__(self, status: int, message: str, details: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = dict(details or {})


def require_active_service_instance_locked(service: Any) -> None:
    """在持锁变更模型/定义前校验服务实例未退休。"""
    checker = getattr(service, "_service_instance_active_locked", None)
    if callable(checker) and not checker():
        raise JsonApiError(409, "请求所属模型生命周期已失效或已退休，操作已取消。")

