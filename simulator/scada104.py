"""Run an independent scdfe_s Web/IEC104 process backed by simulator models."""

import argparse
from contextlib import closing
import gzip
import hashlib
import http.client
from ipaddress import ip_address
import json
import logging
import math
import os
from pathlib import Path
import socket
import sqlite3
import sys
import threading
import time
from typing import Any
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from urllib.parse import urlencode, urlsplit


LOG = logging.getLogger("simulator.scada104")
KINDS = ("yc", "yx", "yk", "yt")
APP_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = (APP_ROOT / "../../workspace").resolve()
DEFAULT_HTTP_TIMEOUT = 5.0
DEFAULT_OFFLINE_FAILURE_THRESHOLD = 3


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


LOCAL_HTTP = build_opener(ProxyHandler({}), NoRedirect())


def default_scada_root(settings=None):
    """按环境变量 FES_ROOT/SCADA_ROOT > startup.json(fes_root/scada_root) > 同级 fes/scada 目录探测默认 FES 路径。"""
    env_root = str(os.environ.get("FES_ROOT") or os.environ.get("SCADA_ROOT") or "").strip()
    if env_root:
        return Path(env_root)
    if isinstance(settings, dict):
        for key in ("fes_root", "scada_root"):
            if str(settings.get(key) or "").strip():
                return (APP_ROOT / str(settings[key]).strip()).resolve()
    fes_sibling = (APP_ROOT / "../../fes").resolve()
    if (fes_sibling / "scdfe_s").is_dir():
        return fes_sibling
    return (APP_ROOT / "../../scada").resolve()


def loopback_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.username or parsed.password or not parsed.port
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or not parsed.hostname or not ip_address(parsed.hostname).is_loopback):
        raise ValueError("模拟台地址必须是本机 HTTP 地址，例如 http://127.0.0.1:18710")
    return url.rstrip("/")


def port_available(port):
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


class _LoopbackKeepAlivePool:
    """线程安全的本机 HTTP/1.1 Keep-Alive + gzip 连接池，消除 0.5s 轮询短连接握手与未压缩传输开销。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._slots: dict[tuple[str, int], tuple[threading.RLock, http.client.HTTPConnection]] = {}
        self._etag_cache: dict[tuple[str, int, str], tuple[str, Any]] = {}

    def _get_slot(self, host: str, port: int, timeout: float):
        key = (host, port)
        with self._lock:
            slot = self._slots.get(key)
            if slot is None:
                slot = (threading.RLock(), http.client.HTTPConnection(host, port, timeout=timeout))
                self._slots[key] = slot
            return slot

    def _discard(self, host: str, port: int, conn: http.client.HTTPConnection) -> None:
        key = (host, port)
        with self._lock:
            slot = self._slots.get(key)
            if slot is not None and slot[1] is conn:
                self._slots.pop(key, None)
        try:
            conn.close()
        except OSError:
            pass

    def request_json(self, base: str, path: str, payload=None, *, timeout: float = DEFAULT_HTTP_TIMEOUT):
        parsed = urlsplit(base)
        host = parsed.hostname or "127.0.0.1"
        port = int(parsed.port or 80)
        method = "GET" if payload is None else "POST"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Connection": "keep-alive",
        }
        cache_key = (host, port, path)
        cached_entry = None
        if method == "GET":
            with self._lock:
                cached_entry = self._etag_cache.get(cache_key)
            if cached_entry is not None:
                headers["If-None-Match"] = cached_entry[0]
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))
        last_exc = None
        for attempt in range(2):
            slot_lock, conn = self._get_slot(host, port, timeout)
            reused = False
            try:
                with slot_lock:
                    conn.timeout = timeout
                    sock = getattr(conn, "sock", None)
                    reused = sock is not None
                    if sock is not None:
                        sock.settimeout(timeout)
                    conn.request(method, path, body=body, headers=headers)
                    resp = conn.getresponse()
                    raw = resp.read()
                    status = int(resp.status)
                    reason = str(resp.reason or "")
                    will_close = bool(getattr(resp, "will_close", False))
                    is_gzip = str(resp.getheader("Content-Encoding", "")).lower() == "gzip"
                    resp_etag = str(resp.getheader("ETag", "") or "").strip()
            except (OSError, http.client.HTTPException) as exc:
                last_exc = exc
                self._discard(host, port, conn)
                # 非幂等 POST 绝不在 TimeoutError 时重发；仅在复用连接发生零字节断连时安全重试一次
                safe_post_retry = (
                    reused
                    and isinstance(
                        exc,
                        (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError),
                    )
                )
                if attempt == 0 and (method == "GET" or safe_post_retry):
                    continue
                raise
            if will_close:
                self._discard(host, port, conn)
            if status == 304 and cached_entry is not None:
                return cached_entry[1]
            if is_gzip and raw:
                raw = gzip.decompress(raw)
            if status >= 400:
                text = raw.decode("utf-8", errors="replace")
                raise OSError(f"HTTP {status} {reason}: {text[:200]}")
            parsed_body = json.loads(raw.decode("utf-8")) if raw else {}
            if method == "GET" and resp_etag:
                with self._lock:
                    if len(self._etag_cache) >= 256:
                        self._etag_cache.clear()
                    self._etag_cache[cache_key] = (resp_etag, parsed_body)
            return parsed_body
        raise last_exc or OSError("HTTP request failed")

    def close(self) -> None:
        with self._lock:
            slots = list(self._slots.values())
            self._slots.clear()
        for _slot_lock, conn in slots:
            try:
                conn.close()
            except OSError:
                pass


_HTTP_POOL = _LoopbackKeepAlivePool()


def request(base, path, payload=None, *, timeout=DEFAULT_HTTP_TIMEOUT):
    return _HTTP_POOL.request_json(base, path, payload=payload, timeout=timeout)


_DEFAULT_REQUEST = request


def read_points(base, model):
    measurement = request(base, "/api/measurements")
    controls = request(base, "/api/external/controls/names")
    if controls.get("model_id") != model:
        raise ValueError("模型服务标识与教员台目录不一致")
    definitions = {kind: {} for kind in KINDS}
    values = {str(row["name"]): row for row in measurement["scada"]}
    for row in measurement["definitions"]:
        kind = "yx" if str(row["meas_type"]).upper() in {"RUN_STAT", "STATUS"} else "yc"
        definitions[kind][str(row["name"])] = values.get(str(row["name"]))
    for kind in ("yk", "yt"):
        definitions[kind].update((name, None) for name in controls[kind + "_names"])
    return definitions


def migrate_bridge_tables_out(scada_db_path: Path, bridge_db_path: Path) -> None:
    """将旧版写入 scdfe_s.sqlite3 的 simulator104_* 表迁移到独立边车库，保持 SCADA 库纯净。"""
    bridge_db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(bridge_db_path, timeout=15)) as bdb:
        bdb.execute("PRAGMA journal_mode=WAL")
        with bdb:
            bdb.execute("""CREATE TABLE IF NOT EXISTS simulator104_models (
                model TEXT PRIMARY KEY, rtu_id INTEGER UNIQUE NOT NULL)""")
            bdb.execute("""CREATE TABLE IF NOT EXISTS simulator104_points (
                rtu_id INTEGER NOT NULL, kind TEXT NOT NULL, source_name TEXT NOT NULL,
                pnt_no INTEGER NOT NULL, active INTEGER NOT NULL,
                PRIMARY KEY (rtu_id, kind, source_name), UNIQUE (rtu_id, kind, pnt_no))""")
        if not scada_db_path.is_file() or scada_db_path.stat().st_size == 0:
            return
        with closing(sqlite3.connect(scada_db_path, timeout=15)) as sdb:
            tables = {
                r[0]
                for r in sdb.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not ({"simulator104_models", "simulator104_points"} & tables):
                return
            models = (
                sdb.execute("SELECT model, rtu_id FROM simulator104_models").fetchall()
                if "simulator104_models" in tables
                else []
            )
            points = (
                sdb.execute(
                    "SELECT rtu_id, kind, source_name, pnt_no, active FROM simulator104_points"
                ).fetchall()
                if "simulator104_points" in tables
                else []
            )
            with bdb:
                if models:
                    bdb.executemany(
                        "INSERT OR IGNORE INTO simulator104_models VALUES (?,?)", models
                    )
                if points:
                    bdb.executemany(
                        "INSERT OR IGNORE INTO simulator104_points VALUES (?,?,?,?,?)",
                        points,
                    )
            with sdb:
                sdb.execute("BEGIN IMMEDIATE")
                sdb.execute("DROP TABLE IF EXISTS simulator104_points")
                sdb.execute("DROP TABLE IF EXISTS simulator104_models")


class Bridge:
    def __init__(
        self,
        server,
        simulator_url,
        first_port,
        interval=1.0,
        *,
        bridge_db_path=None,
        offline_failure_threshold=DEFAULT_OFFLINE_FAILURE_THRESHOLD,
        catalog_provider=None,
    ):
        self.server = server
        self.simulator_url = simulator_url
        self.first_port = first_port
        self.interval = interval
        self.offline_failure_threshold = max(1, int(offline_failure_threshold))
        self.catalog_provider = catalog_provider
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.online = {}
        self.models = {}
        self.initialized = set()
        self.pending_reload = set()
        self.manual_stopped = set()
        self.last_errors = {}
        self._failure_counts = {}
        self._point_def_cache = {}
        self._last_samples = {}
        self._model_rtu_cache = {}
        self._known_rtus = None
        self._invalidated_rtus = set()
        self._delta_sync_state = {}
        self._cached_catalog_models = None
        self._cached_catalog_ts = 0.0
        self._catalog_ttl_seconds = 2.5
        self.bridge_db_path = Path(
            bridge_db_path
            or server.store.db_path.with_name(server.store.db_path.stem + "_bridge.sqlite3")
        ).resolve()
        migrate_bridge_tables_out(server.store.db_path, self.bridge_db_path)

    def _bridge_con(self):
        con = sqlite3.connect(self.bridge_db_path, timeout=15)
        con.execute("PRAGMA busy_timeout=15000")
        return con

    def is_bound_rtu(self, rtu):
        with closing(self._bridge_con()) as bdb:
            return (
                bdb.execute(
                    "SELECT 1 FROM simulator104_models WHERE rtu_id=?", (int(rtu),)
                ).fetchone()
                is not None
            )

    def channel(self, model):
        cached_rtu = self._model_rtu_cache.get(model)
        if cached_rtu is not None:
            return cached_rtu
        # 优先普通只读查询，避免每轮 0.5s 触发无谓的 BEGIN IMMEDIATE 写锁。
        with closing(self._bridge_con()) as bdb:
            row = bdb.execute(
                "SELECT rtu_id FROM simulator104_models WHERE model=?",
                (model,),
            ).fetchone()
            if row:
                rtu_id = int(row[0])
                self._model_rtu_cache[model] = rtu_id
                return rtu_id
        store = self.server.store
        with closing(self._bridge_con()) as bdb, bdb:
            bdb.execute("BEGIN IMMEDIATE")
            row = bdb.execute("SELECT rtu_id FROM simulator104_models WHERE model=?", (model,)).fetchone()
            if row:
                rtu_id = int(row[0])
                self._model_rtu_cache[model] = rtu_id
                return rtu_id
            used_bridge = {
                int(value)
                for value, in bdb.execute("SELECT rtu_id FROM simulator104_models")
                if value is not None
            }
            with store.connection() as db, db:
                db.execute("BEGIN IMMEDIATE")
                used = used_bridge | {int(value) for value, in db.execute(
                    "SELECT rtu_id FROM fes_rtu_define UNION SELECT channel_id FROM fes_rtu_define "
                    "UNION SELECT channel_id FROM fes_channel_iec104_define "
                    "UNION SELECT id FROM fes_channel_iec104_define"
                ) if value is not None}
                ports = {int(port) for port, in db.execute(
                    "SELECT remote_port FROM fes_channel_iec104_define WHERE remote_port IS NOT NULL")}
                rtu = next((number for number in range(1, 65535) if number not in used), None)
                if rtu is None:
                    raise RuntimeError("没有可分配的 IEC104 RTU 编号")
                port = next(
                    (number for number in range(self.first_port, 65536)
                     if number not in ports and port_available(number)),
                    None,
                )
                if port is None:
                    raise RuntimeError("没有可分配的本机 IEC104 监听端口")
                db.execute("INSERT INTO fes_channel_iec104_define (id,name,channel_id,rtu_addr,remote_host,remote_port) "
                           "VALUES (?,?,?,?,'127.0.0.1',?)", (rtu, model, rtu, rtu, port))
                db.execute("INSERT INTO fes_rtu_define (rtu_id,channel_id,channel_type,name,process_enable) VALUES (?,?,'iec104',?,1)",
                           (rtu, rtu, model))
            bdb.execute("INSERT INTO simulator104_models VALUES (?,?)", (model, rtu))
        self._model_rtu_cache[model] = rtu
        return rtu

    def sync_points(self, rtu, points):
        """增量同步测点定义与数值，仅在定义或采样发生变化时才开启 SQLite 写事务。"""
        def_signature = tuple(
            (kind, tuple(sorted(current.keys())))
            for kind, current in points.items()
        )
        cached_def = self._point_def_cache.get(rtu)
        sample_updates = {}
        if cached_def is not None and cached_def["signature"] == def_signature:
            # 快速路径：点表定义未变，检查是否有遥测/遥信值变化，无变化则完全跳过写事务。
            known_by_kind = cached_def["known"]
            last_samples = self._last_samples.setdefault(rtu, {})
            for kind in ("yc", "yx"):
                current = points.get(kind, {})
                known = known_by_kind.get(kind, {})
                for name, row in current.items():
                    no = known.get(name)
                    if no is None:
                        continue
                    value = row.get("value") if row else None
                    valid = isinstance(value, (int, float)) and math.isfinite(value) and bool(row.get("valid", 1))
                    if kind == "yx":
                        valid = valid and value in (0, 1)
                    prev_value, prev_status = last_samples.get((kind, no), (None, None))
                    quality = 0 if valid else 128
                    effective_value = value if valid else (prev_value if prev_value is not None else 0)
                    if (effective_value, quality) != (prev_value, prev_status):
                        sample_updates[(kind, no)] = (effective_value, quality)
            if not sample_updates:
                return False
            now = time.time_ns() // 1_000_000
            with self.server.store.connection() as db, db:
                db.execute("BEGIN IMMEDIATE")
                for (kind, no), (val, quality) in sample_updates.items():
                    table = f"fes_{kind}_define"
                    if kind == "yc":
                        db.execute(
                            f"UPDATE {table} SET value=?,status=?,refresh_time=?,raw_value=?,raw_status=?,raw_time=? "
                            "WHERE rtu_id=? AND pnt_no=?",
                            (val, quality, now, val, quality, now, rtu, no),
                        )
                    else:
                        db.execute(
                            f"UPDATE {table} SET value=?,status=?,refresh_time=? WHERE rtu_id=? AND pnt_no=?",
                            (val, quality, now, rtu, no),
                        )
            # 仅在 SQLite 事务提交成功后更新内存缓存，防止回滚导致测点永久滞留旧值。
            last_samples.update(sample_updates)
            return False

        now = time.time_ns() // 1_000_000
        changed = False
        known_cache = {}
        pending_samples = {}
        removed_samples = []
        with closing(self._bridge_con()) as bdb, bdb, self.server.store.connection() as db, db:
            bdb.execute("BEGIN IMMEDIATE")
            db.execute("BEGIN IMMEDIATE")
            for kind, current in points.items():
                table = f"fes_{kind}_define"
                known = {name: (no, active) for name, no, active in bdb.execute(
                    "SELECT source_name,pnt_no,active FROM simulator104_points WHERE rtu_id=? AND kind=?",
                    (rtu, kind))}
                existing = {no: (value, status) for no, value, status in db.execute(
                    f"SELECT pnt_no,value,status FROM {table} WHERE rtu_id=?", (rtu,))}
                number = max([0, *existing, *(entry[0] for entry in known.values())])
                for name, row in current.items():
                    if name not in known:
                        number += 1
                        db.execute(f"INSERT INTO {table} (rtu_id,pnt_no,name,value,status) VALUES (?,?,?,0,128)",
                                   (rtu, number, name))
                        bdb.execute("INSERT INTO simulator104_points VALUES (?,?,?,?,1)", (rtu, kind, name, number))
                        known[name] = (number, True)
                        existing[number] = (0, 128)
                        changed = True
                    no, active = known[name]
                    if no not in existing:
                        # 若 SCADA 点表行被手工删除但边车仍有绑定，自动补插定义行避免永久跳过更新。
                        db.execute(
                            f"INSERT INTO {table} (rtu_id,pnt_no,name,value,status) VALUES (?,?,?,0,128)",
                            (rtu, no, name),
                        )
                        existing[no] = (0, 128)
                        changed = True
                    if not active:
                        bdb.execute("UPDATE simulator104_points SET active=1 WHERE rtu_id=? AND kind=? AND source_name=?",
                                    (rtu, kind, name))
                        changed = True
                    if kind in {"yc", "yx"} and no in existing:
                        value = row.get("value") if row else None
                        valid = isinstance(value, (int, float)) and math.isfinite(value) and bool(row.get("valid", 1))
                        if kind == "yx":
                            valid = valid and value in (0, 1)
                        previous, status = existing[no]
                        quality = 0 if valid else 128
                        value = value if valid else previous
                        if (value, quality) != (previous, status):
                            # Samples are independent of the version used for editing point definitions.
                            fields = "value=?,status=?,refresh_time=?"
                            values = [value, quality, now]
                            if kind == "yc":
                                fields += ",raw_value=?,raw_status=?,raw_time=?"
                                values += [value, quality, now]
                            db.execute(f"UPDATE {table} SET {fields} WHERE rtu_id=? AND pnt_no=?",
                                       (*values, rtu, no))
                        pending_samples[(kind, no)] = (value, quality)
                for name, (no, active) in known.items():
                    if active and name not in current:
                        bdb.execute("UPDATE simulator104_points SET active=0 WHERE rtu_id=? AND kind=? AND source_name=?",
                                    (rtu, kind, name))
                        raw_status_sql = ",raw_status=128" if kind == "yc" else ""
                        db.execute(
                            f"UPDATE {table} SET status=128{raw_status_sql},refresh_time=? WHERE rtu_id=? AND pnt_no=?",
                            (now, rtu, no),
                        )
                        removed_samples.append((kind, no))
                        changed = True
                known_cache[kind] = {name: no for name, (no, _active) in known.items() if name in current}
        # 双库事务全部提交成功后再更新内存状态缓存。
        last_samples = self._last_samples.setdefault(rtu, {})
        last_samples.update(pending_samples)
        for sample_key in removed_samples:
            last_samples.pop(sample_key, None)
        self._point_def_cache[rtu] = {"signature": def_signature, "known": known_cache}
        return changed

    def command_target(self, rtu, kind, number, value):
        if kind not in {"yk", "yt"}:
            raise ValueError("只允许遥控或遥调")
        with closing(self._bridge_con()) as bdb:
            brow = bdb.execute(
                "SELECT source_name FROM simulator104_points "
                "WHERE rtu_id=? AND kind=? AND pnt_no=? AND active=1",
                (rtu, kind, number),
            ).fetchone()
        if brow is None:
            raise ValueError("仿真控制点未绑定、已退役或模型离线")
        with self.server.store.connection() as db:
            prow = db.execute(
                f"SELECT man_disable,auto_disable FROM fes_{kind}_define "
                "WHERE rtu_id=? AND pnt_no=?",
                (rtu, number),
            ).fetchone()
        with self.lock:
            target = self.online.get(rtu)
        if prow is None or target is None:
            raise ValueError("仿真控制点未绑定、已退役或模型离线")
        if prow[0] or prow[1]:
            raise ValueError("控制点已禁止操作")
        if not isinstance(value, (int, float)) or not math.isfinite(value) or (kind == "yk" and value not in (0, 1)):
            raise ValueError("无效遥控或遥调值")
        return target[0], target[1], brow[0]

    def execute(self, rtu, kind, number, value):
        base, model, name = self.command_target(rtu, kind, number, value)
        # 不再硬编码 manual_hold=True，避免通过 IEC104 下发的设点在仿真周期归零/重启后永久锁死；
        # 同时收紧单次命令超时，避免模拟台短暂抖动长时间阻塞 IEC104 协议线程。
        payload = {
            kind + "_names": [name],
            kind + "_values": [value],
            "source": "scdfe_s",
            "manual_hold": False,
        }
        path = "/api/external/controls/execute?" + urlencode({"model_id": model})
        if request is _DEFAULT_REQUEST:
            response = request(base, path, payload, timeout=2.5)
        else:
            response = request(base, path, payload)
        key = "remote_controls" if kind == "yk" else "remote_adjustments"
        results = response.get(kind + "_results", [])
        if response.get("accepted", {}).get(key) != 1 or (results and not results[0].get("accepted")):
            raise ValueError("仿真模型未接受该指令")
        applied_value = value
        if results and isinstance(results[0], dict) and results[0].get("value") is not None:
            try:
                parsed = float(results[0]["value"])
                if math.isfinite(parsed):
                    applied_value = int(round(parsed)) if kind == "yk" else parsed
            except (TypeError, ValueError):
                pass
        LOG.info("模型 %s 已接受 RTU%s %s/%s=%s", model, rtu, kind.upper(), number, applied_value)
        return applied_value

    def remove_model(self, model_name):
        """模型被删除时停止并回收对应 RTU 的 IEC104 通道、边车点号映射与内存同步缓存。"""
        name = str(model_name or "").strip()
        if not name:
            return False
        with self.lock:
            rtu = self._model_rtu_cache.pop(name, None)
            self._delta_sync_state.pop(name, None)
            self.last_errors.pop(name, None)
        with closing(self._bridge_con()) as bdb, bdb:
            if rtu is None:
                row = bdb.execute(
                    "SELECT rtu_id FROM simulator104_models WHERE model=?",
                    (name,),
                ).fetchone()
                if row is not None:
                    rtu = int(row[0])
            if rtu is None:
                return False
            bdb.execute("DELETE FROM simulator104_points WHERE rtu_id=?", (rtu,))
            bdb.execute("DELETE FROM simulator104_models WHERE rtu_id=?", (rtu,))
        now = time.time_ns() // 1_000_000
        try:
            with self.server.store.connection() as db, db:
                db.execute(
                    "UPDATE fes_yc_define SET status=128,raw_status=128,refresh_time=? WHERE rtu_id=?",
                    (now, rtu),
                )
                db.execute(
                    "UPDATE fes_yx_define SET status=128,refresh_time=? WHERE rtu_id=?",
                    (now, rtu),
                )
        except Exception as exc:
            LOG.warning("清理模型 %s (RTU%s) SCADA 测点质量位失败: %s", name, rtu, exc)
        with self.lock:
            self.online.pop(rtu, None)
            self.models.pop(rtu, None)
            self._last_samples.pop(rtu, None)
            self._point_def_cache.pop(rtu, None)
            self._failure_counts.pop(rtu, None)
            self.initialized.discard(rtu)
            self.manual_stopped.discard(rtu)
            self.pending_reload.discard(rtu)
            self._invalidated_rtus.discard(rtu)
            if self._known_rtus is not None:
                self._known_rtus.discard(rtu)
            try:
                channels = self.server.channel_services(rtu_id=rtu)
                channel = channels.get(f"iec104-rtu-{rtu}")
                if channel is not None:
                    try:
                        if channel.status().get("running"):
                            channel.stop()
                    except Exception:
                        pass
                    try:
                        channel.close()
                    except Exception:
                        pass
            except Exception as exc:
                LOG.warning("停止已删除模型 %s 的 IEC104 通道 RTU%s 失败: %s", name, rtu, exc)
            cache = getattr(self.server, "_channel_cache", None)
            if isinstance(cache, dict):
                cache.pop(f"iec104-rtu-{rtu}", None)
            svc_cache = getattr(self.server, "_channel_service_cache", None)
            if isinstance(svc_cache, dict):
                svc_cache.pop(f"iec104-rtu-{rtu}", None)
        LOG.info("已回收已删除模型 %s 的 IEC104 通道与点表映射 (RTU%s)", name, rtu)
        return True

    def invalidate_offline(self, seen):
        if self._known_rtus is None:
            with closing(self._bridge_con()) as bdb:
                self._known_rtus = {
                    int(rtu) for rtu, in bdb.execute("SELECT rtu_id FROM simulator104_models")
                }
        self._known_rtus.update(int(r) for r in seen)
        offline = [
            rtu
            for rtu in self._known_rtus
            if rtu not in seen and rtu not in self._invalidated_rtus
        ]
        if not offline:
            return
        with closing(self._bridge_con()) as bdb:
            offline_points = {}
            for rtu in offline:
                for kind in ("yc", "yx"):
                    pts = [
                        int(no)
                        for no, in bdb.execute(
                            "SELECT pnt_no FROM simulator104_points WHERE rtu_id=? AND kind=?",
                            (rtu, kind),
                        )
                    ]
                    if pts:
                        offline_points[(rtu, kind)] = pts
        now = time.time_ns() // 1_000_000
        with self.server.store.connection() as db, db:
            for rtu in offline:
                for kind in ("yc", "yx"):
                    pts = offline_points.get((rtu, kind))
                    if not pts:
                        continue
                    raw_status = ",raw_status=128" if kind == "yc" else ""
                    placeholders = ",".join("?" for _ in pts)
                    db.execute(
                        f"UPDATE fes_{kind}_define SET status=128{raw_status},refresh_time=? "
                        f"WHERE rtu_id=? AND status IS NOT 128 AND pnt_no IN ({placeholders})",
                        (now, rtu, *pts),
                    )
        for rtu in offline:
            self._last_samples.pop(rtu, None)
            self._point_def_cache.pop(rtu, None)
            self._invalidated_rtus.add(rtu)

    def status(self):
        with self.lock:
            models = [dict(value) for value in self.models.values()]
            errors = dict(self.last_errors)
        return {"simulator_url": self.simulator_url, "database": self.server.database_info()["database"],
                "models": models, "errors": errors}

    def list_points(self, rtu, kind):
        """查询指定 RTU 的四遥点表（yc/yx/yk/yt），供前端点表预览与指令选择使用。"""
        if kind not in KINDS:
            raise ValueError("测点类型仅支持 yc、yx、yk 或 yt")
        with closing(self._bridge_con()) as bdb:
            bound = bdb.execute(
                "SELECT pnt_no, source_name FROM simulator104_points "
                "WHERE rtu_id=? AND kind=? AND active=1 ORDER BY pnt_no",
                (int(rtu), kind),
            ).fetchall()
        if not bound:
            return []
        with self.server.store.connection() as db:
            if kind in {"yk", "yt"}:
                defs = {
                    int(pnt_no): (name, man_disable, auto_disable, value, status, refresh_time)
                    for pnt_no, name, man_disable, auto_disable, value, status, refresh_time in db.execute(
                        f"SELECT pnt_no, name, man_disable, auto_disable, value, status, refresh_time "
                        f"FROM fes_{kind}_define WHERE rtu_id=?",
                        (int(rtu),),
                    )
                }
            else:
                defs = {
                    int(pnt_no): (name, 0, 0, value, status, refresh_time)
                    for pnt_no, name, value, status, refresh_time in db.execute(
                        f"SELECT pnt_no, name, value, status, refresh_time "
                        f"FROM fes_{kind}_define WHERE rtu_id=?",
                        (int(rtu),),
                    )
                }
        items = []
        for pnt_no, source_name in bound:
            info = defs.get(int(pnt_no))
            if info is None:
                continue
            name, man_disable, auto_disable, value, status, refresh_time = info
            items.append(
                {
                    "pnt_no": int(pnt_no),
                    "name": str(name or source_name or ""),
                    "source_name": str(source_name or ""),
                    "disabled": bool(man_disable or auto_disable),
                    "man_disable": bool(man_disable),
                    "value": value,
                    "status": int(status) if status is not None else 128,
                    "refresh_time": int(refresh_time) if refresh_time is not None else 0,
                }
            )
        return items

    def set_point_disabled(self, rtu, kind, pnt_no, disabled):
        """切换遥控/遥调测点的人工禁操标志（man_disable），直接持久化至 SCADA SQLite 点库。"""
        if kind not in {"yk", "yt"}:
            raise ValueError("仅支持切换遥控(yk)或遥调(yt)测点的禁操状态")
        flag = 1 if disabled else 0
        with self.server.store.connection() as db, db:
            cur = db.execute(
                f"UPDATE fes_{kind}_define SET man_disable=? WHERE rtu_id=? AND pnt_no=?",
                (flag, int(rtu), int(pnt_no)),
            )
            if cur.rowcount == 0:
                raise ValueError(f"未找到测点 RTU {rtu} {kind.upper()}/{pnt_no}")
        return {"rtu_id": int(rtu), "kind": kind, "pnt_no": int(pnt_no), "disabled": bool(flag)}

    def list_control_points(self, rtu, kind):
        """查询指定 RTU 已绑定且活跃的遥控/遥调测点列表，供前端下拉选择。"""
        if kind not in {"yk", "yt"}:
            raise ValueError("控制点类型仅支持 yk 或 yt")
        return self.list_points(rtu, kind)

    def _read_points_for_model(self, base, name):
        """优先使用增量 /api/measurements/delta（稳态单次轻量请求），首次或定义变更自动回退全量同步。
        返回 (points, changed_hint)，当增量帧声明 frame=False 时可直接跳过下游全表比对。
        """
        if request is not _DEFAULT_REQUEST:
            return read_points(base, name), True
        sync_state = self._delta_sync_state.get(name)
        if sync_state is not None and sync_state.get("base") == base:
            try:
                delta = request(
                    base,
                    f"/api/measurements/delta?after_seq={int(sync_state['seq'])}&compact=1&trainee_view=1",
                )
                delta_sig = str(delta.get("definition_signature") or "")
                if (
                    isinstance(delta, dict)
                    and not delta.get("reset")
                    and delta_sig
                    and delta_sig == sync_state.get("definition_signature")
                ):
                    by_index = sync_state["index_meta"]
                    by_name = sync_state.get("name_meta")
                    if by_name is None:
                        by_name = {pt_name: (kind, pt_name) for kind, pt_name in by_index.values()}
                        sync_state["name_meta"] = by_name
                    points = sync_state["points"]
                    dirty = False
                    # 稳态期间每隔 5 秒顺带同步一次 yk/yt 控制点定义，感知模拟台增删遥控/遥调点。
                    now_mono = time.monotonic()
                    last_ctrl_sync = float(sync_state.get("controls_synced_at", now_mono) or 0.0)
                    if now_mono - last_ctrl_sync >= 5.0:
                        try:
                            ctrl_resp = request(base, "/api/external/controls/names")
                            if not (ctrl_resp.get("model_id") and ctrl_resp.get("model_id") != name):
                                for ctrl_kind in ("yk", "yt"):
                                    fresh_names = {
                                        str(pt_name)
                                        for pt_name in (ctrl_resp.get(f"{ctrl_kind}_names") or ())
                                        if str(pt_name)
                                    }
                                    prev_names = set(points[ctrl_kind].keys())
                                    if fresh_names != prev_names:
                                        points[ctrl_kind] = {pt: {"name": pt} for pt in sorted(fresh_names)}
                                        dirty = True
                            sync_state["controls_synced_at"] = now_mono
                        except Exception:
                            pass
                    if delta.get("encoding") == "measurement-arrays-v1":
                        # 紧凑数组协议：frame=False 表示本轮零变更；frame=True 携带全量按索引对齐的 scada/valid 数组
                        if delta.get("frame") is False:
                            sync_state["seq"] = int(delta.get("seq", sync_state["seq"]) or 0)
                            return points, dirty
                        scada_vals = delta.get("scada_values")
                        valid_vals = delta.get("valid_values")
                        if isinstance(scada_vals, list) and len(scada_vals) == len(by_index):
                            has_valid = isinstance(valid_vals, list) and len(valid_vals) == len(by_index)
                            for idx, scada_val in enumerate(scada_vals):
                                meta = by_index.get(idx)
                                if meta is None:
                                    continue
                                kind, pt_name = meta
                                valid_val = valid_vals[idx] if has_valid else 1
                                prev = points[kind].get(pt_name)
                                if (
                                    prev is None
                                    or prev.get("value") != scada_val
                                    or prev.get("valid") != valid_val
                                ):
                                    points[kind][pt_name] = {
                                        "name": pt_name,
                                        "value": scada_val,
                                        "valid": valid_val,
                                    }
                                    dirty = True
                            sync_state["seq"] = int(delta.get("seq", sync_state["seq"]) or 0)
                            return points, dirty
                    elif "rows" in delta:
                        for row in delta.get("rows") or ():
                            if not isinstance(row, list) or len(row) < 3:
                                continue
                            meta = None
                            if isinstance(row[0], int):
                                meta = by_index.get(row[0])
                            else:
                                raw_key = str(row[0]).strip()
                                if raw_key.isdigit():
                                    meta = by_index.get(int(raw_key))
                                if meta is None:
                                    meta = by_name.get(raw_key)
                            if meta is None:
                                continue
                            kind, pt_name = meta
                            scada_val = row[2]
                            valid_val = row[3] if len(row) > 3 else 1
                            prev = points[kind].get(pt_name)
                            if (
                                prev is None
                                or prev.get("value") != scada_val
                                or prev.get("valid") != valid_val
                            ):
                                points[kind][pt_name] = {"name": pt_name, "value": scada_val, "valid": valid_val}
                                dirty = True
                        sync_state["seq"] = int(delta.get("seq", sync_state["seq"]) or 0)
                        return points, dirty
            except Exception:
                self._delta_sync_state.pop(name, None)

        # 全量建基线：一次拉取 measurements + /api/external/controls/names，复用同一份 definitions 构建 index_meta
        m = request(base, "/api/measurements?trainee_view=1")
        c = request(base, "/api/external/controls/names")
        if c.get("model_id") and c.get("model_id") != name:
            raise ValueError("模型服务标识与教员台目录不一致")
        points = {"yc": {}, "yx": {}, "yk": {}, "yt": {}}
        index_meta = {}
        meas_defs = m.get("definitions") or []
        scada = {row["name"]: row for row in m.get("scada", [])}
        for idx, row in enumerate(meas_defs):
            pt_name = str(row.get("name", ""))
            kind = "yx" if str(row.get("meas_type", "")).upper() in {"RUN_STAT", "STATUS"} else "yc"
            index_meta[idx] = (kind, pt_name)
            cur = scada.get(pt_name, {})
            points[kind][pt_name] = {
                "name": pt_name,
                "value": cur.get("value", 0),
                "valid": cur.get("valid", 0),
            }
        for kind in ("yk", "yt"):
            for pt_name in c.get(f"{kind}_names") or ():
                pt_text = str(pt_name)
                if pt_text:
                    points[kind][pt_text] = {"name": pt_text}
        # 兼容极早期返回 remote_controls/remote_adjustments 的桩响应
        for row in c.get("remote_controls") or ():
            pt_name = str(row.get("name", "") if isinstance(row, dict) else row)
            if pt_name:
                points["yk"].setdefault(pt_name, {"name": pt_name})
        for row in c.get("remote_adjustments") or ():
            pt_name = str(row.get("name", "") if isinstance(row, dict) else row)
            if pt_name:
                points["yt"].setdefault(pt_name, {"name": pt_name})
        # 尝试建立增量同步基线（静默容错，老版本服务自动回退全量）
        try:
            delta_init = request(base, "/api/measurements/delta?after_seq=0&compact=1&trainee_view=1")
            if isinstance(delta_init, dict) and delta_init.get("definition_signature"):
                if len(index_meta) == int(delta_init.get("count", len(index_meta)) or 0):
                    # 若建基线两次请求期间模拟台已步进至更高 seq，将 delta_init 的最新值合入 points，
                    # 确保返回数据与记录的 seq 严格同帧、绝不永久丢帧。
                    scada_vals = delta_init.get("scada_values")
                    valid_vals = delta_init.get("valid_values")
                    if (
                        delta_init.get("encoding") == "measurement-arrays-v1"
                        and isinstance(scada_vals, list)
                        and len(scada_vals) == len(index_meta)
                    ):
                        has_valid = isinstance(valid_vals, list) and len(valid_vals) == len(index_meta)
                        for idx, scada_val in enumerate(scada_vals):
                            meta = index_meta.get(idx)
                            if meta is None:
                                continue
                            kind, pt_name = meta
                            points[kind][pt_name] = {
                                "name": pt_name,
                                "value": scada_val,
                                "valid": valid_vals[idx] if has_valid else 1,
                            }
                    self._delta_sync_state[name] = {
                        "base": base,
                        "seq": int(delta_init.get("seq", 0) or 0),
                        "definition_signature": str(delta_init.get("definition_signature") or ""),
                        "index_meta": index_meta,
                        "name_meta": {pt_name: (kind, pt_name) for kind, pt_name in index_meta.values()},
                        "points": points,
                        "controls_synced_at": time.monotonic(),
                    }
        except Exception:
            self._delta_sync_state.pop(name, None)
        return points, True

    def _sync_single_model(self, name, base_url):
        base = loopback_url(base_url)
        points, dirty = self._read_points_for_model(base, name)
        rtu = self.channel(name)
        if self._known_rtus is not None:
            self._known_rtus.add(rtu)
        changed = False
        if dirty or rtu not in self.initialized or rtu in self._invalidated_rtus:
            changed = self.sync_points(rtu, points)
        self._invalidated_rtus.discard(rtu)
        with self.lock:
            self.online[rtu] = (base, name)
            self._failure_counts.pop(rtu, None)
            channel = self.server.channel_services(rtu_id=rtu)[f"iec104-rtu-{rtu}"]
            manual_stopped = rtu in self.manual_stopped
            if not manual_stopped and (rtu not in self.initialized or (changed and channel.status()["running"])):
                self.pending_reload.add(rtu)
            if not manual_stopped and rtu in self.pending_reload:
                if channel.status()["running"]:
                    channel.stop()
                channel.start()
                self.pending_reload.remove(rtu)
                self.initialized.add(rtu)
            channel_status = channel.status()
            self.models[rtu] = {"model": name, "rtu_id": rtu, "model_url": base,
                                "online": True, "running": channel_status["running"],
                                "endpoint": channel_status.get("endpoint"),
                                "points": {key: len(items) for key, items in points.items()},
                                "updated_ms": time.time_ns() // 1_000_000}
            self.last_errors.pop(name, None)
        return rtu

    def poll_once(self, *, force_catalog=True):
        """执行单轮目录发现与点表同步；目录瞬时超时不误将全站测点置为无效。"""
        seen = set()
        catalog_ok = False
        catalog_models = None
        now = time.monotonic()
        use_cached_catalog = (
            not force_catalog
            and self._cached_catalog_models is not None
            and (now - self._cached_catalog_ts) < self._catalog_ttl_seconds
        )
        if use_cached_catalog:
            catalog_models = self._cached_catalog_models
            catalog_ok = True
        else:
            try:
                if callable(self.catalog_provider):
                    catalog_models = self.catalog_provider()
                else:
                    catalog_models = request(self.simulator_url, "/api/models")["models"]
                catalog_ok = True
                self._cached_catalog_models = catalog_models
                self._cached_catalog_ts = now
                with self.lock:
                    self.last_errors.pop("catalog", None)
            except Exception as exc:
                self.report_error("catalog", exc)

        if catalog_ok and isinstance(catalog_models, list):
            healthy_targets = []
            for model in catalog_models:
                service = model.get("service") or {}
                if not service.get("healthy"):
                    continue
                healthy_targets.append((model["id"], service["base_url"]))
            for name, base_url in healthy_targets:
                try:
                    rtu = self._sync_single_model(name, base_url)
                    seen.add(rtu)
                except Exception as exc:
                    self.report_error(name, exc)
                    # 直连瞬时抖动未达阈值时保留当前在线态，避免单次丢包引起测点闪断。
                    with self.lock:
                        matched_rtu = next(
                            (r for r, (_b, m) in self.online.items() if m == name),
                            None,
                        )
                        if matched_rtu is not None:
                            count = self._failure_counts.get(matched_rtu, 0) + 1
                            self._failure_counts[matched_rtu] = count
                            if count < self.offline_failure_threshold:
                                seen.add(matched_rtu)
        else:
            # 目录接口超时/不可达时，继续直连已在线模型服务，绝不误判全站离线。
            with self.lock:
                known_online = list(self.online.items())
            for rtu, (base_url, name) in known_online:
                try:
                    synced_rtu = self._sync_single_model(name, base_url)
                    seen.add(synced_rtu)
                except Exception as exc:
                    self.report_error(name, exc)
                    with self.lock:
                        count = self._failure_counts.get(rtu, 0) + 1
                        self._failure_counts[rtu] = count
                        if count < self.offline_failure_threshold:
                            seen.add(rtu)

        if not catalog_ok:
            # 仅对达到连续失败阈值的已知模型标记离线，跳过基于空目录的全表置无效。
            with self.lock:
                stale_rtus = [
                    rtu for rtu in list(self.online.keys())
                    if rtu not in seen
                ]
                for rtu in stale_rtus:
                    self.online.pop(rtu, None)
                    self._failure_counts.pop(rtu, None)
                    if rtu in self.models:
                        self.models[rtu]["online"] = False
                keep_online = set(self.online.keys()) | seen
            if stale_rtus:
                try:
                    self.invalidate_offline(keep_online)
                except Exception as exc:
                    self.report_error("database", exc)
            return

        with self.lock:
            for rtu in self.online.keys() - seen:
                self.online.pop(rtu, None)
                self._failure_counts.pop(rtu, None)
                if rtu in self.models:
                    self.models[rtu]["online"] = False
        try:
            self.invalidate_offline(seen)
        except Exception as exc:
            self.report_error("database", exc)
        else:
            with self.lock:
                self.last_errors.pop("database", None)

    def poll(self):
        while not self.stop.is_set():
            self.poll_once(force_catalog=False)
            self.stop.wait(self.interval)

    def report_error(self, name, exc):
        with self.lock:
            if self.last_errors.get(name) != str(exc):
                LOG.error("%s: %s", name, exc)
                self.last_errors[name] = str(exc)


def main(argv=None):
    settings = json.loads((APP_ROOT / "startup.json").read_text(encoding="utf-8"))
    data_dir = (APP_ROOT / settings.get("data_dir", "data")).resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scada-root", type=Path, default=default_scada_root(settings))
    parser.add_argument("--db", type=Path, default=data_dir / "scdfe_s.sqlite3")
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--simulator-url", default=f"http://127.0.0.1:{settings['port']}")
    parser.add_argument("--web-port", type=int, default=8878)
    parser.add_argument("--first-iec104-port", type=int, default=2405)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args(argv)
    if not 0.1 <= args.interval <= 60 or not 1 <= args.first_iec104_port <= 65535:
        parser.error("轮询周期必须为 0.1–60 秒，IEC104 起始端口必须为 1–65535")
    try:
        simulator_url = loopback_url(args.simulator_url)
    except ValueError as exc:
        parser.error(str(exc))
    scada_root = args.scada_root.resolve()
    if not scada_root.is_dir():
        parser.error(f"SCADA 目录不存在: {scada_root}，请通过 --scada-root 或环境变量 SCADA_ROOT 指定")
    sys.path.insert(0, str(scada_root))
    from scdfe_s.web.iec104_service import IEC104Service, IEC104ServiceError
    from scdfe_s.web.server import ApiError, ScadaHandler, ScadaHTTPServer

    class ModelIEC104Service(IEC104Service):
        def _on_command(self, event, rtu_id=None):
            cause = str(getattr(event.cause, "name", event.cause)).upper()
            if cause.endswith("ACTIVATION") and not cause.endswith("DEACTIVATION"):
                try:
                    operation = bridge.command_target if event.selected else bridge.execute
                    operation(rtu_id, event.kind, event.point_no, event.value)
                except Exception as exc:
                    self._record("ERROR", f"仿真指令执行失败: {exc}", alert=True)
                    return False
            return super()._on_command(event, rtu_id)

        def simulate_command(self, kind, point_no, value):
            # 释放通道锁后再执行 5s 网络请求，避免模拟台短暂抖动冻结整个 IEC104 通道锁。
            with self._lock:
                if self._server is None or kind not in {"yk", "yt"}:
                    raise IEC104ServiceError("请启动模型 IEC104 通道并选择遥控或遥调点")
                try:
                    rtu_id = self._server.rtu_id
                    actual = self._server.prepare_value(kind, int(point_no), value)
                except Exception as exc:
                    raise IEC104ServiceError(str(exc)) from exc
            try:
                applied = bridge.execute(rtu_id, kind, int(point_no), actual)
            except Exception as exc:
                raise IEC104ServiceError(str(exc)) from exc
            effective_value = actual if applied is None else applied
            with self._lock:
                if self._server is None:
                    raise IEC104ServiceError("指令发送期间模型 IEC104 通道已停止")
                try:
                    table, key, fields = self._point_update(kind, int(point_no), effective_value, rtu_id)
                    fields["cmd_handle_time"] = fields["refresh_time"]
                    item = self.store.update_row(table, key, fields)
                    self._server.set_value(kind, int(point_no), effective_value)
                except Exception as exc:
                    raise IEC104ServiceError(str(exc)) from exc
                self._record("INFO", f"Web 指令已由仿真模型接受：{kind.upper()}/{point_no}={effective_value}")
                return {"kind": kind, "pnt_no": int(point_no), "value": effective_value,
                        "item": item, "applied_to_simulator": True}

    _asset_cache = {}
    _asset_cache_lock = threading.Lock()

    def _load_cached_asset(file_name):
        target = APP_ROOT / "simu/web/simulator" / file_name
        stat = target.stat()
        with _asset_cache_lock:
            cached = _asset_cache.get(file_name)
            if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
                return cached[2], cached[3]
        content = target.read_bytes()
        etag = f'W/"{hashlib.blake2b(content, digest_size=8).hexdigest()}"'
        with _asset_cache_lock:
            _asset_cache[file_name] = (stat.st_mtime_ns, stat.st_size, content, etag)
        return content, etag

    class BridgeHandler(ScadaHandler):
        def _dispatch(self):
            parts, query = self._path()
            if (
                self.command == "POST"
                and not query
                and len(parts) == 6
                and parts[:2] == ["api", "rtus"]
                and parts[3] == "commands"
            ):
                self._prepare_request()
                rtu_id = self._rtu_id(parts[2])
                result = self.server.simulator_command(rtu_id, parts[4], parts[5], self._body())
                if result is not None:
                    return self._json(200, {"item": result, "command_status": "applied"})
            if self.command == "GET" and parts == ["api", "simulator104", "points"]:
                self._prepare_request()
                raw_rtu = (query.get("rtu_id") or [""])[0]
                raw_kind = str((query.get("kind") or ["yk"])[0]).strip().lower()
                if not str(raw_rtu).strip().isdigit():
                    return self._json(400, {"error": "请指定有效的 rtu_id"})
                try:
                    items = bridge.list_control_points(int(raw_rtu), raw_kind)
                except ValueError as exc:
                    return self._json(400, {"error": str(exc)})
                return self._json(200, {"rtu_id": int(raw_rtu), "kind": raw_kind, "items": items})
            if self.command in ("GET", "HEAD"):
                assets = {"simulator104": ("scada104.html", "text/html"),
                          "scada104.js": ("scada104.js", "application/javascript"),
                          "scada104.css": ("scada104.css", "text/css")}
                if len(parts) == 1 and parts[0] in assets:
                    self._prepare_request()
                    file, media = assets[parts[0]]
                    content, etag = _load_cached_asset(file)
                    if str(self.headers.get("If-None-Match", "")).strip() == etag:
                        self.send_response(304)
                        self.send_header("ETag", etag)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", media + "; charset=utf-8")
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    if self.command == "GET":
                        self.wfile.write(content)
                    return
                if not query and parts == ["api", "simulator104", "status"]:
                    self._prepare_request()
                    return self._json(200, bridge.status())
            return super()._dispatch()

    class ModelScadaServer(ScadaHTTPServer):
        def __init__(self, address, **kwargs):
            super().__init__(address, **kwargs)
            self.RequestHandlerClass = BridgeHandler
            # The generic IEC104 page and per-RTU pages must both call the simulator.
            self.iec104_service = ModelIEC104Service(
                self.store, startup_catalog=self._channel_service_history,
            )
            self._resources.callback(self.iec104_service.close)

        def channel_services(self, *, rtu_id=None):
            """在自身子类中直接为 IEC104 通道注入 ModelIEC104Service，无需修改 scada 源码。"""
            with self._channel_service_lock:
                with self.store.connection() as con:
                    where = " WHERE r.channel_type='iec104'"
                    params = ()
                    if rtu_id is not None:
                        where += " AND r.rtu_id=?"
                        params = (int(rtu_id),)
                    rows = con.execute(
                        "SELECT r.rtu_id, p.remote_port "
                        "FROM fes_rtu_define r LEFT JOIN fes_channel_iec104_define p "
                        "ON p.channel_id=r.channel_id" + where + " ORDER BY r.rtu_id",
                        params,
                    ).fetchall()
                for row in rows:
                    rid = int(row[0])
                    slug = f"iec104-rtu-{rid}"
                    if slug in self._channel_service_cache:
                        continue
                    config_path = self.store.db_path.with_name(f".scdfe_s_iec104_rtu_{rid}.json")
                    service = ModelIEC104Service(
                        self.store,
                        config_path=config_path,
                        startup_catalog=self._channel_service_history,
                    )
                    service._config["rtu_id"] = rid
                    if hasattr(service, "_configured_fields"):
                        service._configured_fields.add("rtu_id")
                    if row[1]:
                        try:
                            service._config["port"] = int(row[1])
                        except (TypeError, ValueError):
                            pass
                    self._channel_service_cache[slug] = service
                    self._resources.callback(service.close)
            return super().channel_services(rtu_id=rtu_id)

        def switch_database(self, body):
            raise ApiError(409, "此进程绑定仿真专库，切换路径请使用 --db 重新启动")

        def simulator_command(self, rtu, kind, number, body):
            if not bridge.is_bound_rtu(rtu):
                return None
            if kind not in {"yk", "yt"} or "value" not in body:
                raise IEC104ServiceError("请选择遥控或遥调点并填写值")
            channel = self.channel_services(rtu_id=rtu)[f"iec104-rtu-{rtu}"]
            return channel.simulate_command(kind, int(number), body["value"])

    logging.basicConfig(level=logging.INFO)
    database = args.db.resolve()
    workspace_root = args.workspace_root or (WORKSPACE_ROOT if database.is_relative_to(WORKSPACE_ROOT) else database.parent)
    if not database.is_relative_to(workspace_root.resolve()):
        parser.error("仿真点库必须位于工作区根目录内")
    bridge_db_path = database.with_name(database.stem + "_bridge.sqlite3")
    migrate_bridge_tables_out(database, bridge_db_path)
    with ModelScadaServer(("127.0.0.1", args.web_port), db_path=database,
                          workspace_root=workspace_root) as server:
        bridge = Bridge(
            server,
            simulator_url,
            args.first_iec104_port,
            args.interval,
            bridge_db_path=bridge_db_path,
        )
        worker = threading.Thread(target=bridge.poll, name="simulator104", daemon=True)
        worker.start()
        LOG.info("scdfe_s Web http://127.0.0.1:%s, SQLite %s", args.web_port, database)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            bridge.stop.set()
            worker.join(timeout=3.0)
            _HTTP_POOL.close()


class _UnavailableScada104Host:
    """当环境未安装 SCADA 协议库或手动禁用 IEC104 时使用的降级占位托管器。"""

    available = False

    def __init__(self, reason: str, *, scada_web_url: str = "") -> None:
        self.reason = str(reason or "IEC104 联动服务未启用")
        self.scada_web_url = str(scada_web_url or "").strip().rstrip("/")

    def status(self) -> dict:
        return {
            "available": False,
            "hosted_by": "simulator",
            "database": "",
            "scada_web_url": self.scada_web_url,
            "models": [],
            "errors": {"iec104": self.reason},
        }

    def list_points(self, rtu: int, kind: str) -> list:
        raise RuntimeError(self.reason)

    def set_point_disabled(self, rtu: int, kind: str, pnt_no: int, disabled: bool) -> dict:
        raise RuntimeError(self.reason)

    def execute_command(self, rtu: int, kind: str, point_no: int, value) -> dict:
        raise RuntimeError(self.reason)

    def control_channel(self, rtu: int, action: str) -> dict:
        raise RuntimeError(self.reason)

    def channel_logs(self, rtu: int, limit: int = 120) -> list:
        return []

    def service_overview(self, rtu_id: int | None = None) -> dict:
        return {
            "available": False,
            "hosted_by": "simulator",
            "reason": self.reason,
            "host": {
                "pid": os.getpid(),
                "running": False,
                "bridge_alive": False,
                "database": "",
                "bridge_database": "",
                "started_at": 0,
                "first_iec104_port": 2405,
                "interval": 0.5,
                "running_channels": 0,
                "total_channels": 0,
            },
            "services": [],
            "rtus": [],
            "channels": [],
        }

    def list_point_definitions(self, rtu: int, kind: str) -> list:
        raise RuntimeError(self.reason)

    def control_service_process(self, action: str, *, rtu_id: int | None = None, scope: str = "single") -> dict:
        raise RuntimeError(self.reason)

    def update_service_config(self, rtu: int, values: dict, *, apply_restart: bool = True) -> dict:
        raise RuntimeError(self.reason)

    def update_rtu_definition(self, rtu: int, values: dict) -> dict:
        raise RuntimeError(self.reason)

    def update_channel_definition(self, channel_id: int, values: dict, *, apply_restart: bool = True) -> dict:
        raise RuntimeError(self.reason)

    def export_channel_efile(self, rtu: int) -> dict:
        raise RuntimeError(self.reason)

    def remove_model(self, model_name: str) -> bool:
        return False

    def close(self) -> None:
        return


class EmbeddedScada104Host:
    """内嵌于 simulator Web 进程内的 IEC104 联动托管器（不启动 scdfe_s Web 端口）。"""

    available = True

    def __init__(
        self,
        *,
        db_path: Path,
        scada_root: Path,
        simulator_url: str,
        first_iec104_port: int = 2405,
        interval: float = 0.5,
        catalog_provider=None,
        scada_web_url: str = "",
    ) -> None:
        scada_root_resolved = Path(scada_root).resolve()
        if not scada_root_resolved.is_dir():
            raise FileNotFoundError(f"SCADA 目录不存在: {scada_root_resolved}")
        if str(scada_root_resolved) not in sys.path:
            sys.path.insert(0, str(scada_root_resolved))
        from scdfe_s.database import SimulatorStore
        from scdfe_s.web.iec104_service import IEC104Service, IEC104ServiceError

        self._iec104_service_cls = IEC104Service
        self._iec104_error_cls = IEC104ServiceError
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.bridge_db_path = self.db_path.with_name(self.db_path.stem + "_bridge.sqlite3")
        self.scada_web_url = str(scada_web_url or "").strip().rstrip("/")
        migrate_bridge_tables_out(self.db_path, self.bridge_db_path)

        self.store = SimulatorStore(self.db_path)
        self._channel_lock = threading.RLock()
        self._channel_cache = {}
        self._startup_catalog = {}
        self._closed = False
        self._started_at_ms = time.time_ns() // 1_000_000
        self._first_iec104_port = int(first_iec104_port)
        self._interval = float(interval)
        self._scada_root = scada_root_resolved

        host_ref = self

        class EmbeddedModelIEC104Service(IEC104Service):
            def _on_command(self, event, rtu_id=None):
                cause = str(getattr(event.cause, "name", event.cause)).upper()
                if cause.endswith("ACTIVATION") and not cause.endswith("DEACTIVATION"):
                    try:
                        operation = (
                            host_ref.bridge.command_target
                            if event.selected
                            else host_ref.bridge.execute
                        )
                        operation(rtu_id, event.kind, event.point_no, event.value)
                    except Exception as exc:
                        self._record("ERROR", f"仿真指令执行失败: {exc}", alert=True)
                        return False
                return super()._on_command(event, rtu_id)

            def simulate_command(self, kind, point_no, value):
                with self._lock:
                    if self._server is None or kind not in {"yk", "yt"}:
                        raise IEC104ServiceError("请启动模型 IEC104 通道并选择遥控或遥调点")
                    try:
                        rtu_id = self._server.rtu_id
                        actual = self._server.prepare_value(kind, int(point_no), value)
                    except Exception as exc:
                        raise IEC104ServiceError(str(exc)) from exc
                try:
                    applied = host_ref.bridge.execute(rtu_id, kind, int(point_no), actual)
                except Exception as exc:
                    raise IEC104ServiceError(str(exc)) from exc
                effective_value = actual if applied is None else applied
                with self._lock:
                    if self._server is None:
                        raise IEC104ServiceError("指令发送期间模型 IEC104 通道已停止")
                    try:
                        table, key, fields = self._point_update(kind, int(point_no), effective_value, rtu_id)
                        fields["cmd_handle_time"] = fields["refresh_time"]
                        item = self.store.update_row(table, key, fields)
                        self._server.set_value(kind, int(point_no), effective_value)
                    except Exception as exc:
                        raise IEC104ServiceError(str(exc)) from exc
                    self._record("INFO", f"Web 指令已由仿真模型接受：{kind.upper()}/{point_no}={effective_value}")
                    return {
                        "kind": kind,
                        "pnt_no": int(point_no),
                        "value": effective_value,
                        "item": item,
                        "applied_to_simulator": True,
                    }

        self._model_iec104_cls = EmbeddedModelIEC104Service
        self.bridge = Bridge(
            self,
            simulator_url,
            first_iec104_port,
            interval,
            bridge_db_path=self.bridge_db_path,
            catalog_provider=catalog_provider,
        )
        self._worker = threading.Thread(
            target=self.bridge.poll,
            name="simulator-embedded-iec104",
            daemon=True,
        )
        self._worker.start()

    def database_info(self) -> dict:
        try:
            display = str(self.db_path.relative_to(WORKSPACE_ROOT)).replace("\\", "/")
        except ValueError:
            display = str(self.db_path)
        return {"database": display, "path": str(self.db_path)}

    def channel_services(self, *, rtu_id=None) -> dict:
        with self._channel_lock:
            if rtu_id is not None:
                slug = f"iec104-rtu-{int(rtu_id)}"
                cached = self._channel_cache.get(slug)
                if cached is not None:
                    return {slug: cached}
            with self.store.connection() as con:
                where = " WHERE r.channel_type='iec104'"
                params = ()
                if rtu_id is not None:
                    where += " AND r.rtu_id=?"
                    params = (int(rtu_id),)
                rows = con.execute(
                    "SELECT r.rtu_id, p.remote_port "
                    "FROM fes_rtu_define r LEFT JOIN fes_channel_iec104_define p "
                    "ON p.channel_id=r.channel_id" + where + " ORDER BY r.rtu_id",
                    params,
                ).fetchall()
            result = {}
            for row in rows:
                rid = int(row[0])
                slug = f"iec104-rtu-{rid}"
                service = self._channel_cache.get(slug)
                if service is None:
                    config_path = self.store.db_path.with_name(f".scdfe_s_iec104_rtu_{rid}.json")
                    service = self._model_iec104_cls(
                        self.store,
                        config_path=config_path,
                        startup_catalog=self._startup_catalog,
                    )
                    service._config["rtu_id"] = rid
                    if hasattr(service, "_configured_fields"):
                        service._configured_fields.add("rtu_id")
                    if row[1]:
                        try:
                            service._config["port"] = int(row[1])
                        except (TypeError, ValueError):
                            pass
                    self._channel_cache[slug] = service
                result[slug] = service
            return result

    def status(self) -> dict:
        payload = self.bridge.status()
        payload["available"] = True
        payload["hosted_by"] = "simulator"
        payload["scada_web_url"] = self.scada_web_url
        return payload

    def list_points(self, rtu: int, kind: str) -> list:
        return self.bridge.list_points(int(rtu), kind)

    def set_point_disabled(self, rtu: int, kind: str, pnt_no: int, disabled: bool) -> dict:
        return self.bridge.set_point_disabled(int(rtu), kind, int(pnt_no), bool(disabled))

    def remove_model(self, model_name: str) -> bool:
        return self.bridge.remove_model(model_name)

    def execute_command(self, rtu: int, kind: str, point_no: int, value) -> dict:
        if not self.bridge.is_bound_rtu(int(rtu)):
            raise ValueError(f"RTU {rtu} 未绑定到仿真模型")
        if kind not in {"yk", "yt"}:
            raise ValueError("控制点类型仅支持 yk 或 yt")
        channels = self.channel_services(rtu_id=int(rtu))
        channel = channels.get(f"iec104-rtu-{int(rtu)}")
        if channel is None:
            raise ValueError(f"未找到 RTU {rtu} 的 IEC104 通道")
        return channel.simulate_command(kind, int(point_no), value)

    def control_channel(self, rtu: int, action: str) -> dict:
        rid = int(rtu)
        act = str(action or "").strip().lower()
        if act not in {"start", "stop", "restart"}:
            raise ValueError("通道操作仅支持 start、stop 或 restart")
        with self.bridge.lock:
            channels = self.channel_services(rtu_id=rid)
            channel = channels.get(f"iec104-rtu-{rid}")
            if channel is None:
                raise ValueError(f"未找到 RTU {rid} 的 IEC104 通道")
            if act == "start":
                self.bridge.manual_stopped.discard(rid)
                ch_status = channel.start()
                self.bridge.initialized.add(rid)
            elif act == "stop":
                self.bridge.manual_stopped.add(rid)
                self.bridge.pending_reload.discard(rid)
                ch_status = channel.stop()
            else:
                self.bridge.manual_stopped.discard(rid)
                if channel.status().get("running"):
                    channel.stop()
                ch_status = channel.start()
                self.bridge.initialized.add(rid)
            if rid in self.bridge.models:
                self.bridge.models[rid]["running"] = bool(ch_status.get("running"))
                self.bridge.models[rid]["endpoint"] = ch_status.get("endpoint")
        return {
            "rtu_id": rid,
            "action": act,
            "running": bool(ch_status.get("running")),
            "endpoint": ch_status.get("endpoint"),
        }

    def channel_logs(self, rtu: int, limit: int = 120) -> list:
        rid = int(rtu)
        channels = self.channel_services(rtu_id=rid)
        channel = channels.get(f"iec104-rtu-{rid}")
        if channel is None:
            return []
        max_items = max(1, min(500, int(limit or 120)))
        with channel._log_lock:
            rows = list(channel._logs)[-max_items:]
        rows.reverse()
        return rows

    _DEFAULT_IOA_BASE = {"yc": 0x4001, "yx": 0x0001, "yk": 0x6001, "yt": 0x6201}
    _DEFAULT_TYPE_ID = {
        "yx": {1: (1, "M_SP_NA_1"), 2: (3, "M_DP_NA_1")},
        "yc": {1: (13, "M_ME_NC_1"), 2: (11, "M_ME_NB_1"), 3: (9, "M_ME_NA_1")},
        "yk": {1: (45, "C_SC_NA_1"), 2: (46, "C_DC_NA_1")},
        "yt": {1: (48, "C_SE_NA_1"), 2: (49, "C_SE_NB_1"), 3: (50, "C_SE_NC_1")},
    }
    _TYPE_ID_NAMES = {
        1: "M_SP_NA_1", 2: "M_SP_TA_1", 3: "M_DP_NA_1", 4: "M_DP_TA_1", 5: "M_ST_NA_1",
        9: "M_ME_NA_1", 10: "M_ME_TA_1", 11: "M_ME_NB_1", 12: "M_ME_TB_1",
        13: "M_ME_NC_1", 14: "M_ME_TC_1", 21: "M_ME_ND_1",
        30: "M_SP_TB_1", 31: "M_DP_TB_1", 32: "M_ST_TB_1",
        34: "M_ME_TD_1", 35: "M_ME_TE_1", 36: "M_ME_TF_1",
        45: "C_SC_NA_1", 46: "C_DC_NA_1", 48: "C_SE_NA_1", 49: "C_SE_NB_1", 50: "C_SE_NC_1",
        58: "C_SC_TA_1", 59: "C_DC_TA_1", 61: "C_SE_TA_1", 62: "C_SE_TB_1", 63: "C_SE_TC_1",
    }

    def _model_name_by_rtu(self) -> dict[int, str]:
        mapping: dict[int, str] = {}
        try:
            with closing(self.bridge._bridge_con()) as bdb:
                for model_name, rid in bdb.execute("SELECT model, rtu_id FROM simulator104_models"):
                    if rid is not None:
                        mapping[int(rid)] = str(model_name or "")
        except Exception:
            pass
        with self.bridge.lock:
            for rid, info in self.bridge.models.items():
                if info.get("model"):
                    mapping[int(rid)] = str(info["model"])
        return mapping

    def _point_counts_by_rtu(self) -> dict[int, dict[str, int]]:
        counts: dict[int, dict[str, int]] = {}
        with self.store.connection() as con:
            for kind in KINDS:
                for rid, cnt in con.execute(
                    f"SELECT rtu_id, COUNT(*) FROM fes_{kind}_define GROUP BY rtu_id"
                ):
                    if rid is None:
                        continue
                    bucket = counts.setdefault(int(rid), {"yc": 0, "yx": 0, "yk": 0, "yt": 0})
                    bucket[kind] = int(cnt or 0)
        return counts

    def service_overview(self, rtu_id: int | None = None) -> dict:
        """聚合内嵌 IEC104 宿主进程、各通道服务运行态、连接监控以及 RTU/通道定义表。"""
        model_by_rtu = self._model_name_by_rtu()
        counts_by_rtu = self._point_counts_by_rtu()
        total_points_by_rtu = {rid: sum(v.values()) for rid, v in counts_by_rtu.items()}

        with self.store.connection() as con:
            con.row_factory = sqlite3.Row
            rtu_rows = [
                dict(row)
                for row in con.execute(
                    "SELECT * FROM fes_rtu_define WHERE channel_type='iec104' ORDER BY rtu_id"
                ).fetchall()
            ]
            channel_rows = [
                dict(row)
                for row in con.execute(
                    "SELECT * FROM fes_channel_iec104_define ORDER BY channel_id, id"
                ).fetchall()
            ]
        channel_by_cid = {int(row["channel_id"]): row for row in channel_rows if row.get("channel_id") is not None}

        services_map = self.channel_services(rtu_id=int(rtu_id) if rtu_id is not None else None)
        service_items = []
        running_count = 0
        with self.bridge.lock:
            bridge_models = {int(k): dict(v) for k, v in self.bridge.models.items()}
            manual_stopped = set(self.bridge.manual_stopped)

        for rtu_row in rtu_rows:
            rid = int(rtu_row["rtu_id"])
            if rtu_id is not None and rid != int(rtu_id):
                continue
            rtu_row["model"] = model_by_rtu.get(rid, str(rtu_row.get("name") or ""))
            cid = int(rtu_row.get("channel_id") or rid)
            ch_def = channel_by_cid.get(cid, {})
            svc = services_map.get(f"iec104-rtu-{rid}")
            st = svc.status(point_counts=total_points_by_rtu) if svc is not None else {}
            is_running = bool(st.get("running"))
            if is_running:
                running_count += 1
            cfg = dict(st.get("config") or {})
            if not cfg.get("bind_ip"):
                cfg["bind_ip"] = str(ch_def.get("remote_host") or "127.0.0.1")
            if not cfg.get("port") and ch_def.get("remote_port"):
                cfg["port"] = int(ch_def["remote_port"])
            endpoint = st.get("endpoint") or {
                "host": str(cfg.get("bind_ip") or "127.0.0.1"),
                "port": int(cfg.get("port") or 0),
            }
            bridge_entry = bridge_models.get(rid, {})
            service_items.append(
                {
                    "rtu_id": rid,
                    "channel_id": cid,
                    "model": model_by_rtu.get(rid, str(rtu_row.get("name") or f"RTU-{rid}")),
                    "name": str(rtu_row.get("name") or ""),
                    "online": bool(bridge_entry.get("online", False)),
                    "running": is_running,
                    "manual_stopped": rid in manual_stopped,
                    "process_enable": bool(int(rtu_row.get("process_enable") or 0)),
                    "packet_recording": bool(int(rtu_row.get("packet_recording") or 0)),
                    "pid": os.getpid() if is_running else 0,
                    "bind_ip": str(endpoint.get("host") or cfg.get("bind_ip") or "127.0.0.1"),
                    "port": int(endpoint.get("port") or cfg.get("port") or 0),
                    "endpoint": endpoint,
                    "common_address": st.get("common_address") or ch_def.get("rtu_addr") or rid,
                    "open_connections": int(st.get("open_connections") or 0),
                    "active_connections": int(st.get("active_connections") or 0),
                    "point_count": int(st.get("point_count") or total_points_by_rtu.get(rid, 0)),
                    "points": counts_by_rtu.get(rid, {"yc": 0, "yx": 0, "yk": 0, "yt": 0}),
                    "started_at": int(st.get("started_at") or 0),
                    "stopped_at": int(st.get("stopped_at") or 0),
                    "heartbeat_at": int(rtu_row.get("process_heartbeat_time") or (time.time_ns() // 1_000_000 if is_running else 0)),
                    "rx_count": int(st.get("rx_count") or 0),
                    "tx_count": int(st.get("tx_count") or 0),
                    "error_count": int(st.get("error_count") or 0),
                    "reconnect_count": int(st.get("reconnect_count") or 0),
                    "last_rx_time": int(st.get("last_rx_time") or 0),
                    "last_tx_time": int(st.get("last_tx_time") or 0),
                    "last_error": str(st.get("last_error") or rtu_row.get("process_error") or ""),
                    "connections": list(st.get("connections") or [])[:30],
                    "config": cfg,
                    "protocol_config": dict(st.get("protocol_config") or {}),
                }
            )

        for row in channel_rows:
            cid = row.get("channel_id")
            matched_rtu = next((r for r in rtu_rows if r.get("channel_id") == cid), None)
            row["rtu_id"] = int(matched_rtu["rtu_id"]) if matched_rtu else None
            row["model"] = matched_rtu.get("model", "") if matched_rtu else ""

        return {
            "available": True,
            "hosted_by": "simulator",
            "host": {
                "pid": os.getpid(),
                "running": not self._closed,
                "bridge_alive": bool(self._worker.is_alive()),
                "database": self.database_info()["database"],
                "database_path": str(self.db_path),
                "bridge_database": str(self.bridge_db_path.name),
                "started_at": self._started_at_ms,
                "first_iec104_port": self._first_iec104_port,
                "interval": self._interval,
                "running_channels": running_count,
                "total_channels": len(rtu_rows),
            },
            "services": service_items,
            "rtus": rtu_rows,
            "channels": channel_rows,
        }

    def list_point_definitions(self, rtu: int, kind: str) -> list:
        """查询指定 RTU 的四遥完整定义（含 IEC104 实际生效 IOA、类型标识、时间标签、上送周期及实时值）。"""
        rid = int(rtu)
        norm_kind = str(kind or "yc").strip().lower()
        if norm_kind not in KINDS:
            raise ValueError("测点类型仅支持 yc、yx、yk 或 yt")
        source_by_pnt: dict[int, str] = {}
        try:
            with closing(self.bridge._bridge_con()) as bdb:
                for pnt_no, src_name in bdb.execute(
                    "SELECT pnt_no, source_name FROM simulator104_points WHERE rtu_id=? AND kind=? AND active=1",
                    (rid, norm_kind),
                ):
                    source_by_pnt[int(pnt_no)] = str(src_name or "")
        except Exception:
            pass

        with self.store.connection() as con:
            con.row_factory = sqlite3.Row
            rtu_row = con.execute(
                "SELECT channel_id FROM fes_rtu_define WHERE rtu_id=?", (rid,)
            ).fetchone()
            channel_id = int(rtu_row["channel_id"]) if rtu_row and rtu_row["channel_id"] is not None else rid
            ch_row = con.execute(
                "SELECT * FROM fes_channel_iec104_define WHERE channel_id=?", (channel_id,)
            ).fetchone()
            ch_def = dict(ch_row) if ch_row else {}
            map_rows = {
                int(r["pnt_no"]): dict(r)
                for r in con.execute(
                    "SELECT * FROM fes_channel_iec104_point_define WHERE channel_id=? AND kind=?",
                    (channel_id, norm_kind),
                ).fetchall()
            }
            point_rows = [
                dict(r)
                for r in con.execute(
                    f"SELECT * FROM fes_{norm_kind}_define WHERE rtu_id=? ORDER BY pnt_no",
                    (rid,),
                ).fetchall()
            ]

        begin_col = f"{norm_kind}begin_addr"
        base_ioa = int(ch_def.get(begin_col) or 0) or self._DEFAULT_IOA_BASE[norm_kind]
        dtype_col = {
            "yc": "yc_data_type",
            "yx": "yx_data_type",
            "yk": "yk_excute_type",
            "yt": "yt_excute_type",
        }[norm_kind]
        selector = int(ch_def.get(dtype_col) or 1)
        default_tid, default_tname = self._DEFAULT_TYPE_ID[norm_kind].get(
            selector, next(iter(self._DEFAULT_TYPE_ID[norm_kind].values()))
        )

        items = []
        for row in point_rows:
            pnt_no = int(row["pnt_no"])
            mapped = map_rows.get(pnt_no, {})
            explicit_ioa = mapped.get("io_address")
            io_address = int(explicit_ioa) if explicit_ioa is not None else (base_ioa + pnt_no - 1)
            explicit_tid = mapped.get("type_id")
            type_id = int(explicit_tid) if explicit_tid is not None else default_tid
            type_name = self._TYPE_ID_NAMES.get(type_id, default_tname)
            items.append(
                {
                    "rtu_id": rid,
                    "channel_id": channel_id,
                    "kind": norm_kind,
                    "pnt_no": pnt_no,
                    "name": str(row.get("name") or source_by_pnt.get(pnt_no) or ""),
                    "source_name": source_by_pnt.get(pnt_no, ""),
                    "io_address": io_address,
                    "io_address_hex": f"0x{io_address:04X}",
                    "io_explicit": explicit_ioa is not None,
                    "type_id": type_id,
                    "type_name": type_name,
                    "time_tag": str(mapped.get("time_tag") or "NONE"),
                    "report_ms": int(mapped.get("report_ms") or 0),
                    "command_mode": str(mapped.get("command_mode") or ""),
                    "qualifier": mapped.get("qualifier"),
                    "value": row.get("value"),
                    "status": int(row["status"]) if row.get("status") is not None else 128,
                    "disabled": bool(row.get("man_disable") or row.get("auto_disable")),
                    "refresh_time": int(row.get("refresh_time") or 0),
                }
            )
        return items

    def control_service_process(self, action: str, *, rtu_id: int | None = None, scope: str = "single") -> dict:
        """管控单个或全部 IEC104 通道服务的启动、停止与重启。"""
        act = str(action or "").strip().lower()
        if act not in {"start", "stop", "restart"}:
            raise ValueError("服务操作仅支持 start、stop 或 restart")
        if scope == "all" or rtu_id is None:
            with self.store.connection() as con:
                rtus = [
                    int(r[0])
                    for r in con.execute(
                        "SELECT rtu_id FROM fes_rtu_define WHERE channel_type='iec104' ORDER BY rtu_id"
                    ).fetchall()
                ]
            results = []
            for rid in rtus:
                results.append(self.control_channel(rid, act))
            return {"scope": "all", "action": act, "results": results}
        result = self.control_channel(int(rtu_id), act)
        return {"scope": "single", "action": act, "results": [result]}

    def update_service_config(self, rtu: int, values: dict, *, apply_restart: bool = True) -> dict:
        """更新指定 RTU 的 IEC104 监听地址、端口与协议参数并同步持久化到通道定义表。"""
        if not isinstance(values, dict):
            raise ValueError("配置参数必须是对象")
        rid = int(rtu)
        allowed = {
            "bind_ip", "port", "max_connections", "tick_rate_ms", "select_timeout_ms",
            "k", "w", "t1", "t2", "t3", "max_asdu_length",
        }
        patch = {k: v for k, v in values.items() if k in allowed and v is not None and v != ""}
        if not patch:
            raise ValueError("请提供至少一项有效的服务配置参数")

        with self.bridge.lock:
            channels = self.channel_services(rtu_id=rid)
            channel = channels.get(f"iec104-rtu-{rid}")
            if channel is None:
                raise ValueError(f"未找到 RTU {rid} 的 IEC104 服务通道")
            was_running = bool(channel.status().get("running"))
            updated_cfg = channel.configure(patch)

            # 同步将监听主机、端口与规约窗口参数写回 fes_channel_iec104_define，确保定义与运行配置单一事实来源
            db_updates = {}
            if "bind_ip" in updated_cfg:
                db_updates["remote_host"] = str(updated_cfg["bind_ip"])
            if "port" in updated_cfg:
                db_updates["remote_port"] = int(updated_cfg["port"])
            for col in ("k", "w", "t1", "t2", "t3", "max_asdu_length"):
                if col in updated_cfg:
                    db_updates[col] = updated_cfg[col]
            if db_updates:
                with self.store.connection() as con, con:
                    row = con.execute("SELECT channel_id FROM fes_rtu_define WHERE rtu_id=?", (rid,)).fetchone()
                    if row is not None and row[0] is not None:
                        set_sql = ", ".join(f"{col}=?" for col in db_updates)
                        con.execute(
                            f"UPDATE fes_channel_iec104_define SET {set_sql} WHERE channel_id=?",
                            (*db_updates.values(), int(row[0])),
                        )

            restarted = False
            if was_running and apply_restart:
                channel.stop()
                st = channel.start()
                restarted = True
            else:
                st = channel.status()
            if rid in self.bridge.models:
                self.bridge.models[rid]["running"] = bool(st.get("running"))
                self.bridge.models[rid]["endpoint"] = st.get("endpoint")

        return {
            "rtu_id": rid,
            "config": updated_cfg,
            "running": bool(st.get("running")),
            "endpoint": st.get("endpoint"),
            "restarted": restarted,
        }

    def update_rtu_definition(self, rtu: int, values: dict) -> dict:
        """更新 fes_rtu_define 中的可配置定义字段（名称、自动通信启用、保存报文）。"""
        if not isinstance(values, dict):
            raise ValueError("RTU 定义参数必须是对象")
        rid = int(rtu)
        updates = {}
        if "name" in values:
            name_val = str(values["name"] or "").strip()
            if not name_val:
                raise ValueError("RTU 名称不能为空")
            updates["name"] = name_val
        if "process_enable" in values:
            updates["process_enable"] = 1 if bool(int(values["process_enable"])) else 0
        if "packet_recording" in values:
            updates["packet_recording"] = 1 if bool(int(values["packet_recording"])) else 0
        if not updates:
            raise ValueError("未提供可更新的 RTU 定义字段")
        with self.store.connection() as con, con:
            set_sql = ", ".join(f"{col}=?" for col in updates)
            cur = con.execute(
                f"UPDATE fes_rtu_define SET {set_sql} WHERE rtu_id=?",
                (*updates.values(), rid),
            )
            if cur.rowcount == 0:
                raise ValueError(f"未找到 RTU {rid} 定义")
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM fes_rtu_define WHERE rtu_id=?", (rid,)).fetchone()
        return dict(row) if row else {"rtu_id": rid, **updates}

    def update_channel_definition(self, channel_id: int, values: dict, *, apply_restart: bool = True) -> dict:
        """更新 fes_channel_iec104_define 通道定义，并同步刷新对应 IEC104 服务配置。"""
        if not isinstance(values, dict):
            raise ValueError("通道定义参数必须是对象")
        cid = int(channel_id)
        int_fields = {
            "rtu_addr", "remote_port", "ycbegin_addr", "yxbegin_addr", "ykbegin_addr", "ytbegin_addr",
            "yx_data_type", "yk_excute_type", "yc_data_type", "yt_excute_type",
            "call_alldata_time", "if_autosend_alldata", "k", "w", "max_asdu_length",
        }
        float_fields = {"t1", "t2", "t3"}
        str_fields = {"name", "remote_host"}
        updates: dict[str, Any] = {}
        for key, raw in values.items():
            if raw is None or raw == "":
                continue
            if key in str_fields:
                text = str(raw).strip()
                if not text:
                    raise ValueError(f"{key} 不能为空")
                updates[key] = text
            elif key in int_fields:
                iv = int(raw)
                if key == "remote_port" and not (1 <= iv <= 65535):
                    raise ValueError("远端端口必须在 1..65535")
                if key.endswith("begin_addr") and not (0 <= iv <= 0xFFFFFF):
                    raise ValueError(f"{key} 超出 24 位信息体地址范围")
                updates[key] = iv
            elif key in float_fields:
                fv = float(raw)
                if not math.isfinite(fv) or fv <= 0:
                    raise ValueError(f"{key} 必须是正数")
                updates[key] = fv
        if not updates:
            raise ValueError("未提供可更新的 IEC104 通道定义字段")

        with self.store.connection() as con, con:
            set_sql = ", ".join(f"{col}=?" for col in updates)
            cur = con.execute(
                f"UPDATE fes_channel_iec104_define SET {set_sql} WHERE channel_id=?",
                (*updates.values(), cid),
            )
            if cur.rowcount == 0:
                raise ValueError(f"未找到通道 {cid} 的 IEC104 定义")
            con.row_factory = sqlite3.Row
            ch_row = con.execute("SELECT * FROM fes_channel_iec104_define WHERE channel_id=?", (cid,)).fetchone()
            rtu_row = con.execute("SELECT rtu_id FROM fes_rtu_define WHERE channel_id=?", (cid,)).fetchone()

        restarted = False
        if rtu_row is not None and rtu_row["rtu_id"] is not None:
            rid = int(rtu_row["rtu_id"])
            svc_patch = {}
            if "remote_host" in updates:
                svc_patch["bind_ip"] = updates["remote_host"]
            if "remote_port" in updates:
                svc_patch["port"] = updates["remote_port"]
            for col in ("k", "w", "t1", "t2", "t3", "max_asdu_length"):
                if col in updates:
                    svc_patch[col] = updates[col]
            for extra_int in ("max_connections", "tick_rate_ms", "select_timeout_ms"):
                raw_extra = values.get(extra_int)
                if raw_extra is not None and raw_extra != "":
                    svc_patch[extra_int] = int(raw_extra)
            with self.bridge.lock:
                channels = self.channel_services(rtu_id=rid)
                channel = channels.get(f"iec104-rtu-{rid}")
                if channel is not None:
                    was_running = bool(channel.status().get("running"))
                    if svc_patch:
                        channel.configure(svc_patch)
                    if was_running and apply_restart:
                        channel.stop()
                        st = channel.start()
                        restarted = True
                        if rid in self.bridge.models:
                            self.bridge.models[rid]["running"] = bool(st.get("running"))
                            self.bridge.models[rid]["endpoint"] = st.get("endpoint")

        return {"channel": dict(ch_row) if ch_row else {"channel_id": cid, **updates}, "restarted": restarted}

    def export_channel_efile(self, rtu: int) -> dict:
        """按 scdfe_s 同构格式导出指定 RTU/通道及其四遥点表为标准 E 文件（可直接导入 scdfe_c）。"""
        rid = int(rtu)
        from core.channel_efile import export_channel_efile as _export_channel_efile

        services_map: dict[str, Any] = {}
        with self.bridge.lock:
            channels = self.channel_services(rtu_id=rid)
            channel = channels.get(f"iec104-rtu-{rid}")
            if channel is not None:
                services_map["iec104"] = channel
                services_map["iec104-server"] = channel
        try:
            return _export_channel_efile(self.store, rid, services=services_map)
        except Exception as exc:
            status_code = getattr(exc, "status", None)
            if status_code == 404:
                raise KeyError(str(exc)) from exc
            raise ValueError(str(exc)) from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.bridge.stop.set()
        if self._worker.is_alive():
            self._worker.join(timeout=3.0)
        with self._channel_lock:
            services = list(self._channel_cache.values())
            self._channel_cache.clear()
        for svc in services:
            try:
                svc.close()
            except Exception:
                pass
        _HTTP_POOL.close()


def create_embedded_scada104_host(
    *,
    simulator_url: str,
    catalog_provider=None,
    data_dir: Path | None = None,
    db_path: Path | None = None,
    scada_root: Path | None = None,
    first_iec104_port: int = 2405,
    interval: float = 0.5,
    scada_web_url: str = "",
):
    """为 simulator Web 进程创建内嵌 IEC104 托管器；缺少外部 SCADA 库时优雅降级不阻塞主服务。"""
    settings = {}
    startup_file = APP_ROOT / "startup.json"
    if startup_file.is_file():
        try:
            settings = json.loads(startup_file.read_text(encoding="utf-8"))
        except Exception:
            settings = {}
    resolved_scada_root = Path(scada_root).resolve() if scada_root else default_scada_root(settings)
    resolved_data_dir = (
        Path(data_dir).resolve()
        if data_dir is not None
        else (APP_ROOT / settings.get("data_dir", "data")).resolve()
    )
    resolved_db = Path(db_path).resolve() if db_path else (resolved_data_dir / "scdfe_s.sqlite3")
    resolved_web_url = str(scada_web_url or settings.get("scada_web_url") or "").strip().rstrip("/")
    if not resolved_scada_root.is_dir():
        return _UnavailableScada104Host(
            f"未找到 SCADA 协议库目录（{resolved_scada_root}），请通过 SCADA_ROOT 或 startup.json(scada_root) 配置",
            scada_web_url=resolved_web_url,
        )
    try:
        return EmbeddedScada104Host(
            db_path=resolved_db,
            scada_root=resolved_scada_root,
            simulator_url=simulator_url,
            first_iec104_port=first_iec104_port,
            interval=interval,
            catalog_provider=catalog_provider,
            scada_web_url=resolved_web_url,
        )
    except Exception as exc:
        LOG.warning("内嵌 IEC104 联动服务初始化失败，已降级：%s", exc)
        return _UnavailableScada104Host(f"IEC104 联动初始化失败：{exc}", scada_web_url=resolved_web_url)


if __name__ == "__main__":
    main()
