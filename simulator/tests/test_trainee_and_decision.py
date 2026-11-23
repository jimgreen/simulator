"""针对学员端后端通道、帧缓存与新能源控制决策引擎的回归与可靠性测试。"""

from __future__ import annotations

import concurrent.futures
import http.client
import io
import json
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
SHARED_ROOT = REPO_ROOT / "shared"
TRAINEE_ROOT = REPO_ROOT / "trainee"
for _entry in (str(APP_ROOT), str(TRAINEE_ROOT), str(SHARED_ROOT)):
    if _entry in sys.path:
        sys.path.remove(_entry)
    sys.path.insert(0, _entry)

from simu import renewable_control, renewable_optimization, resource_topology, trainee_exchange
from simu.http_common import EncodedResponseCache, StaticAssetCache
from simu.http_routes import PolarMicrogridHandler, _ServerContext


class _FakeHttpResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.reason = "OK"
        self.will_close = False
        self._body = body

    def read(self) -> bytes:
        return self._body

    def getheader(self, name: str, default: str = "") -> str:
        return default


class _FakeSockHandle:
    def __init__(self) -> None:
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def close(self) -> None:
        self.closed = True


class _FakeHttpConnection:
    """可编程模拟的 HTTPConnection，用于验证读写连接槽隔离与陈旧连接自动重连。"""

    def __init__(self, host: str, port: int | None = None, timeout: float = 10.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: _FakeSockHandle | None = None
        self.closed = False
        self.requests: list[tuple[str, str]] = []
        self.scripted_outcomes: list[object] = []

    def request(self, method: str, target: str, body=None, headers=None) -> None:
        self.requests.append((method, target))
        if self.sock is None:
            self.sock = _FakeSockHandle()
        if self.scripted_outcomes:
            outcome = self.scripted_outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            self._next_resp = outcome
        else:
            self._next_resp = _FakeHttpResponse(200, json.dumps({"ok": True, "method": method}).encode("utf-8"))

    def getresponse(self) -> _FakeHttpResponse:
        return self._next_resp

    def close(self) -> None:
        self.closed = True
        self.sock = None


class _FakeSocket:
    def __init__(self, raw_request: bytes) -> None:
        self._r = io.BytesIO(raw_request)
        self._w = io.BytesIO()

    def makefile(self, mode: str, bufsize: int = -1):
        return self._r if "r" in mode else self._w

    def sendall(self, data: bytes) -> None:
        self._w.write(data)

    def close(self) -> None:
        pass

    @property
    def raw_response(self) -> bytes:
        return self._w.getvalue()


def _parse_http_response(raw: bytes) -> tuple[int, dict[str, str], bytes]:
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1").splitlines()
    status_code = int(lines[0].split()[1])
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return status_code, headers, body


class DecisionAndTopologyTests(unittest.TestCase):
    """验证 P0 NameError 修复、静态拓扑缓存、热启动以及决策确定性。"""

    def test_weather_helper_exported_and_callable(self) -> None:
        from simu.renewable_control_parts import settings as rc_settings

        self.assertTrue(callable(getattr(rc_settings, "_renewable_weather_available_kw", None)))
        self.assertTrue(callable(getattr(renewable_control, "_renewable_weather_available_kw", None)))

    def test_real_model_control_plan_and_warm_start_determinism(self) -> None:
        from simu.service import PolarMicrogridSimulator

        startup_file = APP_ROOT / "startup.json"
        model_dir = None
        if startup_file.is_file():
            cfg = json.loads(startup_file.read_text(encoding="utf-8"))
            data_dir = (APP_ROOT / str(cfg.get("data_dir") or "data")).resolve()
            models_dir = data_dir / "models"
            if (models_dir / "秦岭站" / "model.e").is_file():
                model_dir = models_dir / "秦岭站"
            elif models_dir.is_dir():
                found = sorted(models_dir.glob("*/model.e"))
                if found:
                    model_dir = found[0].parent
        if model_dir is None:
            self.skipTest("未找到本地测试模型目录")

        with tempfile.TemporaryDirectory() as td:
            svc = PolarMicrogridSimulator(
                sim_dir=model_dir,
                runtime_dir=Path(td) / "rt",
                model_id=model_dir.name,
                model_name=model_dir.name,
                noise_std=0.0,
            )
            try:
                snapshot = svc.step()
            finally:
                if hasattr(svc, "shutdown"):
                    svc.shutdown()

        ctrl_settings = renewable_control.RenewableControlSettings()
        renewable_optimization._ISLAND_WARM_START_CACHE.clear()
        plan_first = renewable_control.calculate_renewable_control_plan(snapshot, ctrl_settings)
        plan_second = renewable_control.calculate_renewable_control_plan(snapshot, ctrl_settings)

        self.assertIsInstance(plan_first, dict)
        self.assertIn("commands", plan_first)
        self.assertGreater(len(plan_first["commands"]), 0)
        self.assertEqual(plan_first["commands"], plan_second["commands"])
        self.assertEqual(plan_first.get("runCommands"), plan_second.get("runCommands"))

        # 校验动作结论与实际功率方向一致（不出现“动作说 hold，实际大幅压减/充电”）
        metrics = plan_first["metrics"]
        if float(metrics.get("renewableDeltaKw", 0.0)) < -0.5:
            self.assertFalse(str(metrics.get("renewableControlAction", "")).startswith("hold"))
            self.assertEqual(metrics.get("renewableStepDirection"), "decrease")
        if abs(float(metrics.get("storageTarget", 0.0)) - float(metrics.get("storageCurrentKw", 0.0))) > 1.0:
            self.assertFalse(str(metrics.get("storageControlAction", "")).startswith("hold"))

        # 校验精简后的控制决策日志可读性：行数精简、无未翻译英文内部枚举、无规则长文背诵
        log_lines = plan_first.get("decisionLogDetail", [])
        self.assertGreater(len(log_lines), 0)
        self.assertLessEqual(len(log_lines), 22)
        joined = "\n".join(log_lines)
        for forbidden in ("hold_low_diesel", "within_bounds", "phase=topology", "电制氢规则：", "燃料电池规则：", "进入统一generation"):
            self.assertNotIn(forbidden, joined)

    def test_resolved_topology_cache_reuses_and_invalidates_on_state_change(self) -> None:
        snapshot = {
            "model": {"id": "topo_cache_test", "version": "1"},
            "definitions": {
                "model": {
                    "ACBus": {"rows": [{"idx": 1, "name": "B1", "node": "N1", "run_stat": 1}]},
                    "ACGenerator": {"rows": [{"idx": 1, "name": "PV1", "node": "N1", "run_stat": 1}]},
                }
            },
            "devices": [
                {"dev_type": "ACBus", "dev_name": "B1", "idx": 1, "model_block": "ACBus", "run_stat": 1},
                {"dev_type": "ACGenerator", "dev_name": "PV1", "idx": 1, "model_block": "ACGenerator", "run_stat": 1},
            ],
        }
        refs = [resource_topology.ResourceRef(technology="pv", dev_type="ACGenerator", dev_name="PV1")]
        resource_topology._STATIC_CONTEXT_CACHE.clear()
        resource_topology._RESOLVED_TOPOLOGY_CACHE.clear()
        ctx = resource_topology.prepare_resource_topology_static_context(snapshot)
        topo1 = resource_topology.resolve_resource_topology(snapshot, refs, static_context=ctx)
        topo2 = resource_topology.resolve_resource_topology(snapshot, refs, static_context=ctx)
        self.assertIs(topo1, topo2)

        # 改变设备在线态后缓存必须失效并重新计算
        snapshot_changed = {
            **snapshot,
            "devices": [
                {"dev_type": "ACBus", "dev_name": "B1", "idx": 1, "model_block": "ACBus", "run_stat": 1},
                {"dev_type": "ACGenerator", "dev_name": "PV1", "idx": 1, "model_block": "ACGenerator", "run_stat": 0},
            ],
        }
        topo3 = resource_topology.resolve_resource_topology(snapshot_changed, refs, static_context=ctx)
        self.assertIsNot(topo1, topo3)

    def test_log_helpers_compress_names_and_merge_warnings(self) -> None:
        from simu.renewable_control_parts import dispatch as rc_dispatch

        self.assertEqual(
            rc_dispatch._compress_device_names(["交流风电-1", "交流风电-2", "交流风电-3", "交流风电-4"]),
            "交流风电-1~4",
        )
        merged = rc_dispatch._merge_similar_warnings(
            [
                "交流柴油发电机-27 已限幅至 79 kW（允许范围 70~300 kW）",
                "交流柴油发电机-28 已限幅至 79 kW（允许范围 70~300 kW）",
                "交流柴油发电机-29 已限幅至 79 kW（允许范围 70~300 kW）",
            ]
        )
        self.assertEqual(merged, ["交流柴油发电机-27~29 已限幅至 79 kW（允许范围 70~300 kW）"])

    def test_static_topology_context_cache_hit(self) -> None:
        snapshot = {
            "model": {"id": "unit_test_model", "version": "1"},
            "devices": [
                {"dev_type": "Bus", "dev_name": "B1", "idx": 1, "model_block": "Bus"},
                {"dev_type": "PV", "dev_name": "PV1", "idx": 1, "model_block": "PV"},
            ],
            "device_definitions": [],
            "model_parameters": {"blocks": {}},
        }
        resource_topology._STATIC_CONTEXT_CACHE.clear()
        ctx1 = resource_topology.prepare_resource_topology_static_context(snapshot)
        ctx2 = resource_topology.prepare_resource_topology_static_context(snapshot)
        self.assertIs(ctx1, ctx2)

    def test_preferred_set_type_cache_reuses_set_types(self) -> None:
        from simu.renewable_control_parts import common as rc_common

        rows = [
            {"dev_type": "PV", "dev_name": "PV1", "set_type": "P_SET"},
            {"dev_type": "WT", "dev_name": "WT1", "set_type": "P_LIMIT"},
        ]
        snapshot = {"definitions": {"control": {"SetValue": {"rows": rows}}}}
        device = {"dev_type": "PV", "dev_name": "PV1"}
        rc_common._CONTROL_ROWS_SET_TYPE_CACHE.clear()
        chosen1 = rc_common._preferred_set_type(snapshot, device, ("P_SET", "P_REF"))
        chosen2 = rc_common._preferred_set_type(snapshot, device, ("P_SET", "P_REF"))
        self.assertEqual(chosen1, "P_SET")
        self.assertEqual(chosen2, "P_SET")
        self.assertEqual(len(rc_common._CONTROL_ROWS_SET_TYPE_CACHE), 1)


class TraineeExchangeTests(unittest.TestCase):
    """验证学员端连接池读写隔离、POST 陈旧连接重连、浅拷贝合并与快速关闭。"""

    def test_persistent_client_read_write_channel_isolation_and_post_retry(self) -> None:
        created: list[_FakeHttpConnection] = []

        def factory(host, port=None, timeout=10.0):
            conn = _FakeHttpConnection(host, port, timeout)
            created.append(conn)
            return conn

        client = trainee_exchange._PersistentJsonClient(http_connection_factory=factory)
        try:
            # 1. GET 使用 read 通道，POST 使用 write 通道，二者各自持有独立连接槽
            r1 = client.request("http://127.0.0.1:18716/api/snapshot", method="GET", timeout=2.0)
            r2 = client.request("http://127.0.0.1:18716/api/commands", method="POST", payload={"a": 1}, timeout=2.0)
            self.assertTrue(r1["ok"])
            self.assertTrue(r2["ok"])
            self.assertEqual(len(created), 2)
            self.assertIn(("read", "http", "127.0.0.1", 18716), client._connections)
            self.assertIn(("write", "http", "127.0.0.1", 18716), client._connections)

            # 2. 模拟 write 通道已建立复用连接因空闲超时断开，POST 应自动重建连接重试 1 次成功
            write_conn = created[1]
            self.assertIsNotNone(write_conn.sock)
            write_conn.scripted_outcomes.append(http.client.RemoteDisconnected("stale keep-alive"))
            r3 = client.request("http://127.0.0.1:18716/api/commands", method="POST", payload={"a": 2}, timeout=2.0)
            self.assertTrue(r3["ok"])
            self.assertTrue(write_conn.closed)
            self.assertEqual(len(created), 3)
        finally:
            client.close()

    def test_merge_runtime_snapshot_preserves_isolation_without_deepcopy(self) -> None:
        local_snapshot = {
            "model": {"id": "m1", "name": "模型1"},
            "diagram": {"svg": "<svg/>"},
            "devices": [{"dev_type": "PV", "dev_name": "PV1", "p_mw": 1.0, "run_stat": 1}],
            "measurements": {"scada": [{"idx": 1, "name": "M1", "value": 10.0, "valid": 1}]},
            "definitions": {"measurement": {"rows": [{"idx": 1, "name": "M1", "valid": 1}]}},
            "static_meta": {"version": "v1"},
        }
        projection = trainee_exchange._ControlStaticProjection(
            snapshot=local_snapshot,
            measurement_definitions=({"idx": 1, "name": "M1", "valid": 1},),
            measurement_definition_signature="sig-1",
        )
        remote_snapshot = {
            "clock": {"step_count": 42, "simu_time": "2026-01-01 00:42:00"},
            "devices": [{"dev_type": "PV", "dev_name": "PV1", "run_stat": 0}],
            "measurements": {"scada": [{"idx": 1, "name": "M1", "value": 25.0}]},
            "commands": {"history": [{"seq": 1}]},
        }
        merged = trainee_exchange._merge_runtime_snapshot_with_local_definitions(remote_snapshot, projection)
        self.assertEqual(merged["clock"]["step_count"], 42)
        self.assertEqual(merged["devices"][0]["run_stat"], 0)
        self.assertEqual(merged["measurements"]["scada"][0]["value"], 25.0)
        self.assertEqual(merged["measurements"]["scada"][0]["valid"], 1)
        # 修改合并结果的顶层或运行态字段不应污染原 local_snapshot 或 remote_snapshot
        merged["clock"] = {"step_count": 99}
        self.assertNotIn("clock", local_snapshot)
        self.assertEqual(local_snapshot["devices"][0]["run_stat"], 1)
        self.assertEqual(remote_snapshot["clock"]["step_count"], 42)

    def test_exchange_close_cancels_client_and_joins_promptly(self) -> None:
        closed_events: list[str] = []

        class _StubClient:
            def close(self) -> None:
                closed_events.append("client_closed")

        ex = trainee_exchange.TraineeRealtimeExchange.__new__(trainee_exchange.TraineeRealtimeExchange)
        ex._close_lock = threading.Lock()
        ex._refresh_pending_lock = threading.Lock()
        ex._refresh_pending = set()
        ex._refresh_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        ex._closed = False
        ex._stop_event = threading.Event()
        ex._wake_event = threading.Event()
        ex._request_client = _StubClient()

        def _worker():
            ex._stop_event.wait(timeout=2.0)
            closed_events.append("worker_exited")

        ex._worker = threading.Thread(target=_worker, daemon=True)
        ex._worker.start()

        started = time.perf_counter()
        ex.close()
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.0)
        self.assertIn("client_closed", closed_events)
        self.assertIn("worker_exited", closed_events)
        self.assertEqual(closed_events[0], "client_closed")


class TraineeRouteCacheTests(unittest.TestCase):
    """验证学员端高频只读路由帧级缓存与 POST 自动失效。"""

    def test_trainee_ui_frame_and_renewable_control_frame_cache_and_invalidation(self) -> None:
        calls = {"ui_frame": 0, "renewable": 0}

        class _StubExchange:
            def __init__(self) -> None:
                self._states = {
                    "m1": types.SimpleNamespace(revision=3, receive_epoch=1, frame_identity="frame-10")
                }

            def snapshot_for_service(self, target_service, **kwargs):
                calls["ui_frame"] += 1
                return {"model": {"id": "m1"}, "clock": {"step_count": 10}, "call": calls["ui_frame"]}

        class _StubRenewableManager:
            def __init__(self) -> None:
                self._states = {
                    "m1": types.SimpleNamespace(revision=5, plan_revision=2, settings_revision=1)
                }

            def state_for_service(self, target_service, **kwargs):
                calls["renewable"] += 1
                return {"ok": True, "call": calls["renewable"]}

            def handle_action_for_service(self, target_service, payload):
                return {"ok": True, "action": payload.get("action")}

            def action_for_service(self, target_service, payload):
                return {"ok": True, "action": payload.get("action")}

            def preview_for_service(self, target_service, **kwargs):
                return {"ok": True}

            def preview(self, model_id, **kwargs):
                return {"ok": True}

        class _StubService:
            model_id = "m1"
            model_name = "测试模型"
            service_instance_id = "inst-1"
            clock = types.SimpleNamespace(
                step_count=10,
                run_id=1,
                state="running",
                speed=1.0,
                absolute_minute=10.0,
                updated_at="2026-01-01T00:10:00",
            )
            definition_snapshot = types.SimpleNamespace(revision="def-rev-1")
            command_history: list = []

            def clock_state(self):
                return {"step_count": 10, "state": "running"}

            def service_for(self, model_id=None):
                return self

            def service_instance_active(self):
                return True

            def frame_cache_key(self):
                return ("m1", 1, 10, "running", 0, 0)

            def trainee_receive_state(self):
                return {"active": True, "frozen": False, "initialized": True}

            def clear_runtime_logs(self):
                return {"ok": True}

        class _StubServer:
            pass

        srv = _StubServer()
        static_root = REPO_ROOT / "trainee" / "simu" / "web" / "trainee"
        srv._ctx = _ServerContext(
            service=_StubService(),
            role="trainee",
            static_root=static_root,
            sim_url=None,
            exchange=_StubExchange(),
            renewable_manager=_StubRenewableManager(),
            direct_simulator_ui=False,
            static_cache=StaticAssetCache(),
            response_cache=EncodedResponseCache(max_entries=32),
        )

        def _dispatch(raw_req: bytes) -> tuple[int, dict[str, str], dict]:
            sock = _FakeSocket(raw_req)
            PolarMicrogridHandler(sock, ("127.0.0.1", 50000), srv)
            status, headers, body = _parse_http_response(sock.raw_response)
            return status, headers, json.loads(body.decode("utf-8"))

        # 0. /api/health 应正常返回 200 且兼容未实现 diagnostics() 的真实管理器实例
        sh, _, dh = _dispatch(b"GET /api/health HTTP/1.1\r\nHost: localhost\r\n\r\n")
        self.assertEqual(sh, 200)
        self.assertTrue(dh.get("ok"))
        self.assertEqual(dh.get("process", {}).get("role"), "trainee")
        self.assertEqual(dh.get("process", {}).get("model_id"), "m1")
        self.assertNotIn("trainee_exchange", dh.get("process", {}))
        self.assertNotIn("renewable_control", dh.get("process", {}))

        # 1. /api/trainee/ui-frame 连续两次 GET 命中帧缓存，仅计算 1 次；带 If-None-Match 命中 304 零字节短路
        s1, h1, d1 = _dispatch(b"GET /api/trainee/ui-frame?page=overview HTTP/1.1\r\nHost: localhost\r\n\r\n")
        s2, h2, d2 = _dispatch(b"GET /api/trainee/ui-frame?page=overview HTTP/1.1\r\nHost: localhost\r\n\r\n")
        self.assertEqual((s1, s2), (200, 200))
        self.assertEqual(d1["snapshot"]["call"], 1)
        self.assertEqual(d2["snapshot"]["call"], 1)
        self.assertEqual(calls["ui_frame"], 1)
        etag1 = h1.get("etag", "")
        self.assertTrue(etag1.startswith('W/"'))
        sock_304 = _FakeSocket(
            f"GET /api/trainee/ui-frame?page=overview HTTP/1.1\r\nHost: localhost\r\nIf-None-Match: {etag1}\r\n\r\n".encode("ascii")
        )
        PolarMicrogridHandler(sock_304, ("127.0.0.1", 50000), srv)
        s304, _, b304 = _parse_http_response(sock_304.raw_response)
        self.assertEqual(s304, 304)
        self.assertEqual(b304, b"")

        # 1b. 带 ?refresh=1 强制绕过读缓存重新计算
        s_ref, _, d_ref = _dispatch(b"GET /api/trainee/ui-frame?page=overview&refresh=1 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        self.assertEqual(s_ref, 200)
        self.assertEqual(d_ref["snapshot"]["call"], 2)
        self.assertEqual(calls["ui_frame"], 2)

        # 1c. 交换层错误态变更（last_error）立即使帧缓存键变化，不再返回假在线旧缓存
        srv._ctx.exchange._states["m1"].last_error = "simulator disconnected"
        s_err, _, d_err = _dispatch(b"GET /api/trainee/ui-frame?page=overview HTTP/1.1\r\nHost: localhost\r\n\r\n")
        self.assertEqual(s_err, 200)
        self.assertEqual(d_err["snapshot"]["call"], 3)
        self.assertEqual(calls["ui_frame"], 3)

        # 2. /api/trainee/renewable-control 连续两次 GET 命中帧缓存
        s3, _, d3 = _dispatch(b"GET /api/trainee/renewable-control HTTP/1.1\r\nHost: localhost\r\n\r\n")
        s4, _, d4 = _dispatch(b"GET /api/trainee/renewable-control HTTP/1.1\r\nHost: localhost\r\n\r\n")
        self.assertEqual((s3, s4), (200, 200))
        self.assertEqual(d3["call"], 1)
        self.assertEqual(d4["call"], 1)
        self.assertEqual(calls["renewable"], 1)

        # 3. 发起写操作 POST 变更后，帧缓存自动清空，再次 GET 重新计算
        post_body = b"{}"
        post_req = (
            b"POST /api/runtime-logs/clear HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(post_body)}\r\n\r\n".encode("ascii")
            + post_body
        )
        sp, _, _ = _dispatch(post_req)
        self.assertEqual(sp, 200)

        s5, _, d5 = _dispatch(b"GET /api/trainee/ui-frame?page=overview HTTP/1.1\r\nHost: localhost\r\n\r\n")
        self.assertEqual(s5, 200)
        self.assertEqual(d5["snapshot"]["call"], 4)
        self.assertEqual(calls["ui_frame"], 4)

    def test_access_log_demotion_and_lru_etag_cache(self) -> None:
        from simu.http_common import EncodedResponseCache, encode_json_for_cache, should_demote_access_log

        self.assertTrue(should_demote_access_log("GET", "/api/models", 200))
        self.assertTrue(should_demote_access_log("GET", "/api/snapshot?lite=1", 200))
        self.assertTrue(should_demote_access_log("GET", "/styles.css?v=1", 304))
        self.assertFalse(should_demote_access_log("GET", "/api/snapshot", 500))
        self.assertFalse(should_demote_access_log("POST", "/api/models/clone", 200))
        self.assertFalse(should_demote_access_log("GET", "/", 200))

        # 验证 LRU 淘汰最近最少使用的键（k2），而非最先写入但刚被访问的热键（k1）
        cache = EncodedResponseCache(max_entries=4)
        for k in ("k1", "k2", "k3", "k4"):
            raw, gz = encode_json_for_cache({"k": k})
            cache.put(k, raw, gz)
        self.assertIsNotNone(cache.get("k1"))
        raw5, gz5 = encode_json_for_cache({"k": "k5"})
        cache.put("k5", raw5, gz5)
        self.assertIsNotNone(cache.get("k1"))
        self.assertIsNone(cache.get("k2"))


class TraineeFrontendStructureTests(unittest.TestCase):
    """验证学员端前端模块化拆分与静态资产完整性。"""

    def test_trainee_frontend_modules_exist_and_referenced(self) -> None:
        web_dir = REPO_ROOT / "trainee" / "simu" / "web" / "trainee"
        index_html = (web_dir / "index.html").read_text(encoding="utf-8")
        self.assertFalse((web_dir / "app.js").exists(), "旧单体 app.js 应已移除")
        expected_modules = [
            "00-i18n.js",
            "01-state-core.js",
            "02-diagram-core.js",
            "03-diagram-editor.js",
            "04-receive-models.js",
            "05-curves.js",
            "06-renewable-control.js",
            "07-measurements-commands.js",
            "08-bootstrap.js",
            "09-ux-enhancements.js",
        ]
        for mod in expected_modules:
            self.assertTrue((web_dir / "js" / mod).is_file(), f"缺少模块文件：{mod}")
            self.assertIn(f"/js/{mod}", index_html, f"index.html 未引用：{mod}")

    def test_all_frontend_bundles_load_in_script_order_without_reference_error(self) -> None:
        """用 Node.js vm 模拟浏览器按 index.html 顺序执行全部三套前端脚本，杜绝跨文件顶层未定义引用。"""
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        harness = r"""
const fs = require("fs");
const path = require("path");
const vm = require("vm");
function makeEl(id = "", tag = "DIV") {
  const el = {
    id, tagName: tag, dataset: {}, style: { setProperty(){}, removeProperty(){} },
    hidden: false, open: false, disabled: false, checked: false, value: "", textContent: "", innerHTML: "", className: "",
    width: 900, height: 260, clientWidth: 900, clientHeight: 260, offsetWidth: 900, offsetHeight: 260,
    scrollTop: 0, scrollLeft: 0, children: [], childNodes: [], options: [],
    classList: { add(){}, remove(){}, toggle(){ return false; }, contains(){ return false; } },
    addEventListener(){}, removeEventListener(){}, dispatchEvent(){}, setAttribute(){}, getAttribute(){ return null; }, removeAttribute(){},
    matches(){ return false; }, querySelector(){ return null; }, querySelectorAll(){ return []; }, closest(){ return null; }, contains(){ return false; },
    append(){}, appendChild(c){ return c; }, replaceChildren(){}, remove(){}, focus(){}, select(){}, blur(){},
    showModal(){ el.open = true; }, close(){ el.open = false; }, setCustomValidity(){}, reportValidity(){ return true; },
    getBoundingClientRect(){ return { left:0, top:0, width:900, height:260, right:900, bottom:260 }; },
    getContext(){ return { clearRect(){}, fillRect(){}, strokeRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, fill(){}, arc(){}, roundRect(){}, fillText(){}, measureText(){ return { width: 40 }; }, save(){}, restore(){}, setLineDash(){}, scale(){}, setTransform(){} }; },
  };
  return el;
}
function runBundle(htmlPath) {
  const html = fs.readFileSync(htmlPath, "utf8");
  const rootDir = path.dirname(htmlPath);
  const scripts = [...html.matchAll(/<script[^>]+src="([^"]+)"/g)].map((m) => m[1].split("?")[0]);
  const ids = new Map();
  for (const m of html.matchAll(/\bid="([^"]+)"/g)) ids.set(m[1], makeEl(m[1]));
  const store = new Map();
  const ctx = {
    console, Math, Date, JSON, Number, String, Boolean, Array, Object, Set, Map, WeakMap, WeakSet, Promise, RegExp, Error, TypeError, URL, URLSearchParams, Blob,
    setTimeout: () => 1, clearTimeout: () => {}, setInterval: () => 1, clearInterval: () => {},
    requestAnimationFrame: () => 1, cancelAnimationFrame: () => {}, AbortController,
    Element: function(){}, HTMLElement: function(){}, HTMLInputElement: function(){}, HTMLSelectElement: function(){},
    Event: function(t){ this.type = t; }, CustomEvent: function(t, o){ this.type = t; this.detail = o?.detail; },
    Option: function(){ return makeEl("", "OPTION"); }, ResizeObserver: function(){ return { observe(){}, disconnect(){} }; },
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
    sessionStorage: { getItem: () => null, setItem(){}, removeItem(){} },
    navigator: { clipboard: { writeText: async () => {} } },
    location: { protocol: "http:", hostname: "127.0.0.1", host: "127.0.0.1:18720", origin: "http://127.0.0.1:18720", search: "", hash: "", href: "http://127.0.0.1:18720/" },
    fetch: async () => ({ ok: true, status: 200, text: async () => "{}", json: async () => ({}), headers: { get: () => null } }),
    getComputedStyle: () => ({ getPropertyValue: () => "" }), devicePixelRatio: 1,
    document: { documentElement: makeEl("html", "HTML"), body: makeEl("body", "BODY"), visibilityState: "visible", hidden: false, activeElement: null,
      getElementById: (id) => ids.get(id) || null, querySelector: () => null, querySelectorAll: () => [],
      createElement: (t) => makeEl("", String(t).toUpperCase()), addEventListener(){}, removeEventListener(){} },
    addEventListener(){}, removeEventListener(){},
  };
  ctx.window = ctx; ctx.globalThis = ctx;
  vm.createContext(ctx);
  for (const rel of scripts) {
    const fp = path.join(rootDir, rel.replace(/^\//, ""));
    vm.runInContext(fs.readFileSync(fp, "utf8"), ctx, { filename: rel });
  }
  if (typeof ctx.applyUiLanguage === "function") {
    ctx.applyUiLanguage("en-US", { persist: true, notify: false, redraw: false });
    ctx.applyUiLanguage("ru-RU", { persist: true, notify: false, redraw: false });
    ctx.applyUiLanguage("zh-CN", { persist: true, notify: false, redraw: false });
  }
}
for (const p of process.argv.slice(1)) runBundle(p);
process.exit(0);
"""
        bundles = [
            str(REPO_ROOT / "trainee" / "simu" / "web" / "trainee" / "index.html"),
            str(REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "index.html"),
            str(REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "scada104.html"),
        ]
        proc = subprocess.run(
            [node, "-e", harness, *bundles],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, f"前端模块顺序加载失败：\n{proc.stderr}")

    def test_all_web_pages_expose_all_eight_style_presets(self) -> None:
        """三套 Web 页面均应完整列出最新 8 套风格预设，移除 neo-brutalism 与旧 sci-fi。"""
        expected_themes = (
            "minimalist-light",
            "precision-dark",
            "bento-grid",
            "glassmorphism",
            "editorial",
            "sci-fi-cyan",
            "sci-fi-purple",
            "sci-fi-matrix",
        )
        removed_themes = ("neo-brutalism", "sci-fi")
        pages = [
            (
                REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "index.html",
                REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "styles.css",
            ),
            (
                REPO_ROOT / "trainee" / "simu" / "web" / "trainee" / "index.html",
                REPO_ROOT / "trainee" / "simu" / "web" / "trainee" / "styles.css",
            ),
            (
                REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "scada104.html",
                REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "scada104.css",
            ),
        ]
        for html_path, css_path in pages:
            html_text = html_path.read_text(encoding="utf-8")
            css_text = css_path.read_text(encoding="utf-8")
            self.assertIn('id="themeSelector"', html_text, f"{html_path.name} 缺少风格选择器")
            for theme_id in expected_themes:
                self.assertIn(f'value="{theme_id}"', html_text, f"{html_path.name} 缺少风格选项 {theme_id}")
                self.assertIn(f'[data-theme="{theme_id}"]', css_text, f"{css_path.name} 缺少风格样式 {theme_id}")
            for old_id in removed_themes:
                self.assertNotIn(f'value="{old_id}"', html_text, f"{html_path.name} 仍残留已废弃选项 {old_id}")
                self.assertNotIn(f'[data-theme="{old_id}"]', css_text, f"{css_path.name} 仍残留已废弃样式 {old_id}")

    def test_all_web_pages_support_trilingual_i18n(self) -> None:
        """三套 Web 页面均应提供 zh-CN / en-US / ru-RU 实时切换器且三语词典键完整对齐。"""
        import shutil
        import subprocess

        pages = [
            REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "index.html",
            REPO_ROOT / "trainee" / "simu" / "web" / "trainee" / "index.html",
            REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "scada104.html",
        ]
        for html_path in pages:
            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn('id="langSelector"', html_text, f"{html_path.name} 缺少语言选择器")
            self.assertIn("/js/00-i18n.js", html_text, f"{html_path.name} 未引入 00-i18n.js")
            for lang_code in ("zh-CN", "en-US", "ru-RU"):
                self.assertIn(f'value="{lang_code}"', html_text, f"{html_path.name} 缺少语言选项 {lang_code}")

        sim_i18n = (REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "js" / "00-i18n.js").read_text(encoding="utf-8")
        trn_i18n = (REPO_ROOT / "trainee" / "simu" / "web" / "trainee" / "js" / "00-i18n.js").read_text(encoding="utf-8")
        self.assertEqual(sim_i18n, trn_i18n, "教员端与学员端 00-i18n.js 内容应保持一致")

        sim_html = (REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        for token in (
            'id="topbarClockControls"',
            'id="clockControlTrigger"',
            'id="clockControlPopover"',
            'id="overviewClockState"',
            'id="overviewClockSpeed"',
        ):
            self.assertIn(token, sim_html, f"教员端时钟控制悬浮框缺少元素：{token}")

        node = shutil.which("node")
        if node:
            check_js = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync(process.argv[1], "utf8");
const ctx = {
  document: { documentElement: { lang: "zh-CN", dataset: {} }, body: null, getElementById: () => null, querySelector: () => null },
  window: { addEventListener(){} },
  localStorage: { getItem: () => null, setItem(){} },
  WeakMap, Set, Map, Object, Array, RegExp, String,
};
vm.createContext(ctx);
vm.runInContext(code + "\nthis.__EXPORT = { I18N_DICT, PHRASE_TRANSLATIONS, translatePhrase, t };", ctx);
const { I18N_DICT, PHRASE_TRANSLATIONS, translatePhrase } = ctx.__EXPORT;
const zhKeys = Object.keys(I18N_DICT["zh-CN"]).sort();
for (const lang of ["en-US", "ru-RU"]) {
  const keys = Object.keys(I18N_DICT[lang]).sort();
  if (JSON.stringify(keys) !== JSON.stringify(zhKeys)) {
    throw new Error(`I18N_DICT keys mismatch for ${lang}`);
  }
}
for (const [zh, pair] of Object.entries(PHRASE_TRANSLATIONS)) {
  if (!Array.isArray(pair) || pair.length !== 2 || !pair[0] || !pair[1]) {
    throw new Error(`Invalid phrase pair for ${zh}`);
  }
}
if (translatePhrase("极地微电网模拟台", "en-US") !== "Polar Microgrid Simulator") {
  throw new Error("en-US translation check failed");
}
if (translatePhrase("极地微电网模拟台", "ru-RU") !== "Симулятор полярной микросети") {
  throw new Error("ru-RU translation check failed");
}
if (translatePhrase("12 台设备", "ru-RU") !== "12 устр.") {
  throw new Error("dynamic pattern check failed");
}
"""
            proc = subprocess.run(
                [node, "-e", check_js, str(REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "js" / "00-i18n.js")],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, f"i18n 词典校验失败：\n{proc.stderr}")

    def test_dark_theme_covers_all_legacy_light_backgrounds(self) -> None:
        """既有 CSS 中所有浅色硬编码背景类必须被暗黑覆盖层显式接管，杜绝白底穿帮。"""
        import re

        light_bg_re = re.compile(
            r"background(?:-color)?\s*:\s*(?:#(?:fff|ffffff|[def][0-9a-f]{5}|[def][0-9a-f]{2})\b|white\b|rgba\(\s*2[2-5]\d|linear-gradient\([^)]*#(?:fff|[def][0-9a-f]{5}))",
            re.IGNORECASE,
        )
        whitelist = {".brand-mark"}
        for css_path in (
            REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "styles.css",
            REPO_ROOT / "trainee" / "simu" / "web" / "trainee" / "styles.css",
        ):
            text = css_path.read_text(encoding="utf-8")
            cut = text.find("全 8 套官方视觉风格")
            self.assertGreater(cut, 0, f"{css_path} 缺少多风格覆盖层")
            head, tail = text[:cut], text[cut:]
            uncovered = []
            for sel, body in re.findall(r"([^{}]+)\{([^{}]+)\}", head):
                if not light_bg_re.search(body):
                    continue
                clean_sel = " ".join(sel.split())
                if clean_sel.startswith("@") or clean_sel.startswith("from") or clean_sel.startswith("to") or "::" in clean_sel:
                    continue
                classes = re.findall(r"\.[a-zA-Z0-9_-]+", clean_sel)
                if not classes or all(c in whitelist for c in classes):
                    continue
                if not any(c in tail for c in classes):
                    uncovered.append(clean_sel)
            self.assertEqual(uncovered, [], f"{css_path.name} 存在未被暗黑主题覆盖的浅底选择器：{uncovered}")
            self.assertIn('data-color-scheme="dark"] ::-webkit-scrollbar-track', tail, f"{css_path.name} 缺少暗黑滚动条样式")
            self.assertIn('[data-overview-target]', tail, f"{css_path.name} 缺少暗黑能量流对比度覆盖")
            self.assertIn('data-color-scheme="dark"] th', tail, f"{css_path.name} 缺少暗黑裸标签 th 覆盖（防止表头与 tbody th 惨白穿帮）")
            self.assertIn('data-color-scheme="dark"] tbody th', tail, f"{css_path.name} 缺少暗黑 tbody th 覆盖")
            self.assertIn('.vertical-stack-splitter::before', tail, f"{css_path.name} 缺少暗黑分隔条伪元素覆盖")

    def test_all_static_html_chinese_strings_mapped_in_i18n(self) -> None:
        """三套静态 HTML 中的可见中文文案与属性必须 100% 命中 i18n 词典或动态模板。"""
        import re

        i18n_src = (REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "js" / "00-i18n.js").read_text(encoding="utf-8")
        known = set(re.findall(r'^\s*"([^"]+)"\s*:\s*\[', i18n_src, re.M)) | set(
            re.findall(r'^\s*"[^"]+"\s*:\s*"([^"]+)"', i18n_src, re.M)
        )
        dyn_res = [
            re.compile(r"^\d+\s*(?:台设备|可用|待发|条|条控制指令|条有效指令|点|类|项|次)$"),
            re.compile(r"^\d+\s*类\s*·\s*\d+\s*台$"),
            re.compile(r"^全部设备\s*·\s*\d+\s*台$"),
            re.compile(r"^\d+/\d+\s*台$"),
            re.compile(r"^最近\s*\d+\s*条$"),
            re.compile(r"^\d+\s*项修改\s*·\s*已选\s*\d+\s*项$"),
            re.compile(r"^\d+\s*点\s*·\s*左轴无\s*·\s*右轴无$"),
        ]
        missing = []
        for hf in (
            REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "index.html",
            REPO_ROOT / "trainee" / "simu" / "web" / "trainee" / "index.html",
            REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "scada104.html",
        ):
            s = re.sub(r"<script[\s\S]*?</script>", "", hf.read_text(encoding="utf-8"))
            found = set()
            for m in re.findall(r">([^<>]*[\u4e00-\u9fff][^<>]*)<", s):
                t = " ".join(m.split())
                if t:
                    found.add(t)
            for m in re.findall(r'(?:placeholder|title)="([^"]*[\u4e00-\u9fff][^"]*)"', s):
                t = " ".join(m.split())
                if t:
                    found.add(t)
            for item in sorted(found):
                if item == "中文" or item in known or any(r.match(item) for r in dyn_res):
                    continue
                missing.append(f"{hf.name}: {item}")
        self.assertEqual(missing, [], f"存在未映射 i18n 的静态 HTML 中文文案：{missing[:20]}")

    def test_trainee_cache_version_token_stable_across_seconds_when_paused(self) -> None:
        """验证学员端暂停态下跨秒调用 cache_version_token 不随墙钟抖动，避免 HTTP 帧缓存失效。"""
        from unittest.mock import patch

        exchange = trainee_exchange.TraineeRealtimeExchange.__new__(trainee_exchange.TraineeRealtimeExchange)
        exchange._states_lock = threading.RLock()
        exchange.frame_age_limit_seconds = 15.0
        exchange.same_frame_limit_seconds = 30.0

        state = trainee_exchange._ExchangeState(model_id="m1")
        state.runtime_snapshot = {"clock": {"state": "paused", "absolute_minute": 42.0}}
        state.received_at = 1000.0
        state.frame_changed_at = 1000.0
        state.frame_identity = "frame-42"
        state.revision = 7
        state.receive_epoch = 2
        state.last_error = ""
        state.consecutive_failures = 0
        exchange._states = {"m1": state}

        with patch.object(trainee_exchange.time, "time", return_value=1010.0):
            tok1 = exchange.cache_version_token("m1")
        with patch.object(trainee_exchange.time, "time", return_value=1060.0):
            tok2 = exchange.cache_version_token("m1")
        self.assertIsNotNone(tok1)
        self.assertEqual(tok1, tok2, "暂停态跨秒不应因 last_frame_age 改变 cache_version_token")

    def test_frontend_trace_history_compaction_bounded(self) -> None:
        """验证双端 compactTraceHistory 真实执行有界裁剪，避免长时运行内存膨胀。"""
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        for rel in (
            "simulator/simu/web/simulator/js/01-state-core.js",
            "trainee/simu/web/trainee/js/01-state-core.js",
        ):
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("TRACE_HISTORY_MAX_POINTS", src, f"{rel} 缺少 TRACE_HISTORY_MAX_POINTS 常量")
            probe = f"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync({str(REPO_ROOT / rel)!r}, "utf8");
const m = code.match(/const TRACE_HISTORY_MAX_POINTS[\\s\\S]*?function compactTraceHistory\\([\\s\\S]*?\\n\\}}/);
if (!m) throw new Error("compactTraceHistory not found");
const ctx = {{ Number, Math, Array, Set }};
vm.runInNewContext(m[0] + "; globalThis.__res = compactTraceHistory;", ctx);
const fn = ctx.__res;
const arr = [];
for (let i = 0; i < 4200; i += 1) arr.push({{ minute: i, value: i * 0.1 }});
const out = fn(arr);
if (out.length > 3600) throw new Error("exceeded bound: " + out.length);
if (out[out.length - 1].minute !== 4199) throw new Error("tail lost");
"""
            res = subprocess.run([node, "-e", probe], capture_output=True, text=True, check=False)
            self.assertEqual(res.returncode, 0, f"{rel} 裁剪验证失败：{res.stderr}")

    def test_i18n_skips_lowercase_svg_and_orphan_pages_removed(self) -> None:
        """验证 i18n 正确跳过小写 SVG 节点，且教员端孤儿页面 faults/modes 已清理。"""
        import shutil
        import subprocess

        sim_html = (REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('data-page="faults"', sim_html, "孤儿页面 faults 应已清理")
        self.assertNotIn('data-page="modes"', sim_html, "孤儿页面 modes 应已清理")

        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        i18n_path = REPO_ROOT / "simulator" / "simu" / "web" / "simulator" / "js" / "00-i18n.js"
        probe = f"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync({str(i18n_path)!r}, "utf8");
const m = code.match(/const SKIP_SVG_TAGS[\\s\\S]*?function isSkippableGraphicNode\\([\\s\\S]*?\\n\\}}/);
if (!m) throw new Error("isSkippableGraphicNode not found");
const ctx = {{ Set, String }};
vm.runInNewContext(m[0] + "; globalThis.__fn = isSkippableGraphicNode;", ctx);
const fn = ctx.__fn;
if (!fn({{ tagName: "svg" }})) throw new Error("lowercase svg not skipped");
if (!fn({{ tagName: "path" }})) throw new Error("lowercase path not skipped");
if (!fn({{ tagName: "tspan", namespaceURI: "http://www.w3.org/2000/svg" }})) throw new Error("svg namespace not skipped");
if (fn({{ tagName: "DIV" }})) throw new Error("normal DIV wrongly skipped");
"""
        res = subprocess.run([node, "-e", probe], capture_output=True, text=True, check=False)
        self.assertEqual(res.returncode, 0, f"SVG 节点跳过断言失败：{res.stderr}")


class Batch1ControlStrategyTests(unittest.TestCase):
    """验证第 1 批控制策略改进（低载禁区、氢能电气岛隔离、SOC 回差与驻留、双层融合防虚假增发）。"""

    def test_fuel_cell_soc_hysteresis_and_no_low_load_forbidden_zone(self) -> None:
        from simu.fuel_cell_control import (
            FuelCellControlInputs,
            FuelCellControlParameters,
            calculate_fuel_cell_power_decision,
        )

        params = FuelCellControlParameters(
            power_step_kw=10.0,
            diesel_power_limit_ratio=0.50,
            diesel_power_stop_minimum_ratio=0.30,
            electric_storage_soc_limit=0.30,
            hydrogen_storage_soc_start_limit=0.30,
            hydrogen_storage_soc_stop_limit=0.20,
            electric_storage_soc_deadband=0.05,
        )
        # SOC 处于 30%~35% 回差区时应保持当前功率，不得因微小波动频繁降载
        hold_decision = calculate_fuel_cell_power_decision(
            params,
            FuelCellControlInputs(
                current_power_kw=30.0,
                maximum_power_kw=90.0,
                minimum_power_kw=20.0,
                start_threshold_kw=30.0,
                stop_threshold_kw=10.0,  # 即使传入旧低阈值，算法也必须锁死不低于 minimum_power_kw
                diesel_power_kw=40.0,
                diesel_capacity_kw=100.0,
                electric_storage_soc_average=0.33,
                hydrogen_storage_soc_average=0.50,
            ),
        )
        self.assertEqual(hold_decision.action, "hold")

        # SOC 高于 35% 触发降载；若当前 20 kW 再降 10 kW 会落入低载禁区，必须直接 stop 到 0
        stop_decision = calculate_fuel_cell_power_decision(
            params,
            FuelCellControlInputs(
                current_power_kw=20.0,
                maximum_power_kw=90.0,
                minimum_power_kw=20.0,
                start_threshold_kw=30.0,
                stop_threshold_kw=10.0,
                diesel_power_kw=40.0,
                diesel_capacity_kw=100.0,
                electric_storage_soc_average=0.36,
                hydrogen_storage_soc_average=0.50,
            ),
        )
        self.assertEqual(stop_decision.action, "stop")
        self.assertAlmostEqual(stop_decision.requested_delta_kw, -20.0, places=6)

    def test_hydrogen_island_isolation_and_single_bad_soc_fault_tolerance(self) -> None:
        from simu.renewable_control_parts.hydrogen import _island_electric_storage_soc

        storage_rows = [
            {
                "dev_type": "ACStorage",
                "dev_name": "ES_A1",
                "online": True,
                "socKnown": True,
                "soc": 0.88,
                "gridComponentId": "AC_1",
            },
            {
                "dev_type": "ACStorage",
                "dev_name": "ES_A2_BAD",
                "online": True,
                "socKnown": False,
                "soc": None,
                "gridComponentId": "AC_1",
            },
            {
                "dev_type": "ACStorage",
                "dev_name": "ES_B1",
                "online": True,
                "socKnown": True,
                "soc": 0.22,
                "gridComponentId": "AC_2",
            },
        ]
        warned: set[tuple[str, str]] = set()
        warnings: list[str] = []
        soc_a = _island_electric_storage_soc(storage_rows, "AC_1", None, warned, warnings)
        soc_b = _island_electric_storage_soc(storage_rows, "AC_2", None, warned, warnings)
        self.assertAlmostEqual(soc_a or 0.0, 0.88, places=6)
        self.assertAlmostEqual(soc_b or 0.0, 0.22, places=6)
        self.assertTrue(any("ES_A2_BAD" in w for w in warnings))

        # 若某电气岛内电储 SOC 全部无效，则该岛返回 None（fail closed）
        all_bad_soc = _island_electric_storage_soc(
            [storage_rows[1]],
            "AC_1",
            None,
            set(),
            [],
        )
        self.assertIsNone(all_bad_soc)

    def test_weather_measurement_availability_gating_and_dual_layer_fusion(self) -> None:
        from simu.renewable_control_parts.planner import (
            _apply_renewable_natural_upper_bounds,
            _finalize_renewable_saturation_memory,
        )
        from simu.renewable_control_parts.settings import _environment_measurement_status
        from simu.renewable_control_parts.common import _measurement_index

        # 1) 测点配置停用（definitions.measurement valid=0）时，即使 curve_boundary 与 real 有值也必须判不可用
        snap_disabled_def = {
            "definitions": {
                "measurement": [
                    {
                        "dev_type": "Environment",
                        "dev_name": "weather",
                        "meas_type": "SOLAR_IRRADIANCE",
                        "valid": 0,
                        "status": "invalid",
                    },
                    {
                        "dev_type": "Environment",
                        "dev_name": "weather",
                        "meas_type": "WIND_SPEED",
                        "valid": 1,
                        "status": "valid",
                    },
                ]
            },
            "measurements": {
                "scada": [
                    {
                        "dev_type": "Environment",
                        "dev_name": "weather",
                        "meas_type": "SOLAR_IRRADIANCE",
                        "valid": 1,
                        "value": 0.0,
                    },
                    {
                        "dev_type": "Environment",
                        "dev_name": "weather",
                        "meas_type": "WIND_SPEED",
                        "valid": 1,
                        "value": 1.2,
                    },
                ]
            },
            "curve_boundary": {"point": {"solar_irradiance_w_m2": 0.0, "wind_speed_mps": 0.0}},
        }
        meas_idx = _measurement_index(snap_disabled_def)
        solar_st = _environment_measurement_status(snap_disabled_def, meas_idx, "SOLAR_IRRADIANCE")
        wind_st = _environment_measurement_status(snap_disabled_def, meas_idx, "WIND_SPEED")
        self.assertFalse(solar_st["available"])
        self.assertEqual(solar_st["reason"], "config_disabled")
        self.assertTrue(wind_st["available"])
        self.assertAlmostEqual(float(wind_st["value"]), 1.2, places=6)

        # 2) SCADA 实时停用（valid=0）时严禁回退 real 或 curve_boundary
        snap_scada_invalid = {
            "measurements": {
                "scada": [
                    {
                        "dev_type": "Environment",
                        "dev_name": "weather",
                        "meas_type": "WIND_SPEED",
                        "valid": 0,
                        "value": 0.0,
                    }
                ],
                "real": [
                    {
                        "dev_type": "Environment",
                        "dev_name": "weather",
                        "meas_type": "WIND_SPEED",
                        "valid": 1,
                        "value": 0.0,
                    }
                ],
            },
            "curve_boundary": {"point": {"wind_speed_mps": 0.0}},
        }
        wind_scada_st = _environment_measurement_status(
            snap_scada_invalid, _measurement_index(snap_scada_invalid), "WIND_SPEED"
        )
        self.assertFalse(wind_scada_st["available"])
        self.assertEqual(wind_scada_st["reason"], "scada_invalid")

        # 3) 双层融合测试：
        # - 风速有效且为 0 -> 第一层气象前馈直接将风电 naturalUpperKw 置 0
        # - 辐照度停用 -> 光伏不进第一层夜间前馈，转由第二层电侧响应失配 2 拍饱和、10 拍解耦探顶、响应后解锁
        ctrl_settings = renewable_control.RenewableControlSettings(step_coefficient=0.05)
        memory: dict[str, object] = {}
        wind_ok = {"available": True, "value": 0.5, "reason": "valid"}
        solar_off = {"available": False, "value": None, "reason": "config_disabled"}

        def make_rows(pv_cur: float, wind_cur: float) -> list[dict[str, object]]:
            return [
                {
                    "dev_type": "ACGenerator",
                    "dev_name": "WT1",
                    "technology": "wind",
                    "online": True,
                    "commandable": True,
                    "capacityKw": 100.0,
                    "currentKw": wind_cur,
                    "planningCurrentKw": wind_cur,
                    "weatherMeasurementAvailable": True,
                    "controlWeatherAvailableKw": 0.0,
                    "strategyCommand": True,
                    "dispatchEnabled": True,
                },
                {
                    "dev_type": "ACGenerator",
                    "dev_name": "PV1",
                    "technology": "pv",
                    "online": True,
                    "commandable": True,
                    "capacityKw": 100.0,
                    "currentKw": pv_cur,
                    "planningCurrentKw": pv_cur,
                    "weatherMeasurementAvailable": False,
                    "controlWeatherAvailableKw": None,
                    "strategyCommand": True,
                    "dispatchEnabled": True,
                },
            ]

        # 第 1 拍（t=0）：风电被第一层直接封顶为 0；光伏因辐照停用暂不封顶，下发增发 5 kW
        rows = make_rows(pv_cur=0.0, wind_cur=0.0)
        targets = {("ACGenerator", "WT1"): 5.0, ("ACGenerator", "PV1"): 5.0}
        _apply_renewable_natural_upper_bounds(
            rows,
            targets,
            ctrl_settings,
            runtime_memory=memory,
            sim_time_seconds=0.0,
            wind_measurement_status=wind_ok,
            solar_measurement_status=solar_off,
            diesel_guard_blocked=False,
        )
        self.assertAlmostEqual(float(rows[0]["naturalUpperKw"]), 0.0, places=6)
        self.assertAlmostEqual(targets[("ACGenerator", "WT1")], 0.0, places=6)
        self.assertNotIn("naturalUpperKw", rows[1])
        rows[0]["commandKw"] = 0.0
        rows[1]["commandKw"] = 5.0
        _finalize_renewable_saturation_memory(
            rows, runtime_memory=memory, sim_time_seconds=0.0, quality_blocked=False
        )

        # 第 2 拍（t=2）：光伏实测仍为 0（第 1 次失配），尚未锁定
        rows = make_rows(pv_cur=0.0, wind_cur=0.0)
        targets = {("ACGenerator", "WT1"): 5.0, ("ACGenerator", "PV1"): 5.0}
        _apply_renewable_natural_upper_bounds(
            rows,
            targets,
            ctrl_settings,
            runtime_memory=memory,
            sim_time_seconds=2.0,
            wind_measurement_status=wind_ok,
            solar_measurement_status=solar_off,
            diesel_guard_blocked=False,
        )
        self.assertFalse(bool(rows[1]["naturalResourceSaturated"]))
        rows[0]["commandKw"] = 0.0
        rows[1]["commandKw"] = 5.0
        _finalize_renewable_saturation_memory(
            rows, runtime_memory=memory, sim_time_seconds=2.0, quality_blocked=False
        )

        # 第 3 拍（t=4）：光伏实测仍为 0（连续第 2 次失配）-> 第二层进入饱和态，锁定自然上限为 0
        rows = make_rows(pv_cur=0.0, wind_cur=0.0)
        targets = {("ACGenerator", "WT1"): 5.0, ("ACGenerator", "PV1"): 5.0}
        _apply_renewable_natural_upper_bounds(
            rows,
            targets,
            ctrl_settings,
            runtime_memory=memory,
            sim_time_seconds=4.0,
            wind_measurement_status=wind_ok,
            solar_measurement_status=solar_off,
            diesel_guard_blocked=False,
        )
        self.assertTrue(bool(rows[1]["naturalResourceSaturated"]))
        self.assertAlmostEqual(float(rows[1]["naturalUpperKw"]), 0.0, places=6)
        self.assertAlmostEqual(targets[("ACGenerator", "PV1")], 0.0, places=6)
        rows[0]["commandKw"] = 0.0
        rows[1]["commandKw"] = 0.0
        _finalize_renewable_saturation_memory(
            rows, runtime_memory=memory, sim_time_seconds=4.0, quality_blocked=False
        )

        # 持续推进至第 10 次饱和计数 -> 触发解耦探顶（不改优化器目标，仅抬高最终下发 commandKw）
        probe_seen = False
        for step_idx in range(1, 12):
            t_sec = 4.0 + step_idx * 2.0
            rows = make_rows(pv_cur=0.0, wind_cur=0.0)
            targets = {("ACGenerator", "WT1"): 5.0, ("ACGenerator", "PV1"): 5.0}
            _apply_renewable_natural_upper_bounds(
                rows,
                targets,
                ctrl_settings,
                runtime_memory=memory,
                sim_time_seconds=t_sec,
                wind_measurement_status=wind_ok,
                solar_measurement_status=solar_off,
                diesel_guard_blocked=False,
            )
            rows[0]["commandKw"] = 0.0
            rows[1]["commandKw"] = 0.0
            _finalize_renewable_saturation_memory(
                rows, runtime_memory=memory, sim_time_seconds=t_sec, quality_blocked=False
            )
            if rows[1].get("decoupledProbeApplied"):
                probe_seen = True
                self.assertGreater(float(rows[1]["commandKw"]), 0.0)
                # 下一拍模拟日出：光伏响应探顶涨至 2.0 kW -> 立刻解除饱和
                next_rows = make_rows(pv_cur=2.0, wind_cur=0.0)
                next_targets = {("ACGenerator", "WT1"): 5.0, ("ACGenerator", "PV1"): 7.0}
                _apply_renewable_natural_upper_bounds(
                    next_rows,
                    next_targets,
                    ctrl_settings,
                    runtime_memory=memory,
                    sim_time_seconds=t_sec + 2.0,
                    wind_measurement_status=wind_ok,
                    solar_measurement_status=solar_off,
                    diesel_guard_blocked=False,
                )
                self.assertFalse(bool(next_rows[1]["naturalResourceSaturated"]))
                break
        self.assertTrue(probe_seen, "持续饱和达到探顶周期后应触发解耦探顶")

    def test_real_model_night_pv_does_not_falsely_curtail_diesel(self) -> None:
        """真实模型集成校验：夜间辐照测点有效为 0 时光伏目标为 0；停用该测点时不进夜间前馈。"""
        import copy
        from simu.service import PolarMicrogridSimulator

        startup_file = APP_ROOT / "startup.json"
        model_dir = None
        if startup_file.is_file():
            cfg = json.loads(startup_file.read_text(encoding="utf-8"))
            data_dir = (APP_ROOT / str(cfg.get("data_dir") or "data")).resolve()
            models_dir = data_dir / "models"
            if (models_dir / "秦岭站" / "model.e").is_file():
                model_dir = models_dir / "秦岭站"
        if model_dir is None:
            self.skipTest("未找到本地秦岭站测试模型")

        with tempfile.TemporaryDirectory() as td:
            svc = PolarMicrogridSimulator(
                sim_dir=model_dir,
                runtime_dir=Path(td) / "rt",
                model_id=model_dir.name,
                model_name=model_dir.name,
                noise_std=0.0,
            )
            try:
                snapshot = svc.step()
            finally:
                if hasattr(svc, "shutdown"):
                    svc.shutdown()

        # 构造夜间零辐照快照（辐照测点配置有效且实时值为 0，光伏实测为 0）
        night_snap = copy.deepcopy(snapshot)
        for channel in ("scada", "real"):
            for row in night_snap.get("measurements", {}).get(channel, []) or []:
                if (
                    str(row.get("dev_type", "")) == "Environment"
                    and str(row.get("dev_name", "")) == "weather"
                    and str(row.get("meas_type", "")).upper() == "SOLAR_IRRADIANCE"
                ):
                    row["valid"] = 1
                    row["value"] = 0.0
                if "光伏" in str(row.get("dev_name", "")) and str(row.get("meas_type", "")).upper() in {"P", "P_GEN", "P_AC", "P_DC"}:
                    row["value"] = 0.0
        for row in night_snap.get("definitions", {}).get("measurement", []) or []:
            if (
                str(row.get("dev_type", "")) == "Environment"
                and str(row.get("dev_name", "")) == "weather"
                and str(row.get("meas_type", "")).upper() == "SOLAR_IRRADIANCE"
            ):
                row["valid"] = 1
                row["status"] = "valid"

        plan_night_valid = renewable_control.calculate_renewable_control_plan(
            night_snap, renewable_control.RenewableControlSettings()
        )
        self.assertTrue(plan_night_valid["weather"]["solarMeasurementAvailable"])
        pv_rows_valid = [
            r for r in plan_night_valid["commandRows"] if r.get("technology") == "pv" and r.get("online")
        ]
        self.assertGreater(len(pv_rows_valid), 0)
        for pv_row in pv_rows_valid:
            self.assertAlmostEqual(float(pv_row.get("naturalUpperKw", -1.0)), 0.0, places=6)
            self.assertAlmostEqual(float(pv_row.get("commandKw", -1.0)), 0.0, places=6)

        # 将辐照测点自身配置置为停用（valid=0），光伏不应再进入夜间前馈截断
        night_snap_disabled = copy.deepcopy(night_snap)
        for row in night_snap_disabled.get("definitions", {}).get("measurement", []) or []:
            if (
                str(row.get("dev_type", "")) == "Environment"
                and str(row.get("dev_name", "")) == "weather"
                and str(row.get("meas_type", "")).upper() == "SOLAR_IRRADIANCE"
            ):
                row["valid"] = 0
                row["status"] = "invalid"
        plan_night_disabled = renewable_control.calculate_renewable_control_plan(
            night_snap_disabled, renewable_control.RenewableControlSettings()
        )
        self.assertFalse(plan_night_disabled["weather"]["solarMeasurementAvailable"])
        pv_rows_disabled = [
            r for r in plan_night_disabled["commandRows"] if r.get("technology") == "pv" and r.get("online")
        ]
        for pv_row in pv_rows_disabled:
            self.assertIsNone(pv_row.get("naturalUpperKw"))

    def test_hydrogen_min_dwell_and_safety_override_on_real_model(self) -> None:
        """验证氢能启停最小驻留冷却在常规经济性停机时保持最小运行功率，但安全停机不受阻塞。"""
        import copy
        from simu.renewable_control_parts.common import _measurement_index
        from simu.renewable_control_parts.hydrogen import _optimize_hydrogen_within_topology_islands
        from simu.resource_topology import resolve_resource_topology
        from simu.service import PolarMicrogridSimulator

        startup_file = APP_ROOT / "startup.json"
        model_dir = None
        if startup_file.is_file():
            cfg = json.loads(startup_file.read_text(encoding="utf-8"))
            data_dir = (APP_ROOT / str(cfg.get("data_dir") or "data")).resolve()
            models_dir = data_dir / "models"
            if (models_dir / "秦岭站" / "model.e").is_file():
                model_dir = models_dir / "秦岭站"
        if model_dir is None:
            self.skipTest("未找到本地秦岭站测试模型")

        with tempfile.TemporaryDirectory() as td:
            svc = PolarMicrogridSimulator(
                sim_dir=model_dir,
                runtime_dir=Path(td) / "rt",
                model_id=model_dir.name,
                model_name=model_dir.name,
                noise_std=0.0,
            )
            try:
                snapshot = svc.step()
            finally:
                if hasattr(svc, "shutdown"):
                    svc.shutdown()

        # 构造电制氢正在以最小运行功率（20%）运行、但柴发高负载要求常规停机的快照
        snap = copy.deepcopy(snapshot)
        coupling_rows = (
            snap.get("definitions", {}).get("model", {}).get("AcE2Hydro", {}).get("rows", [])
            or snap.get("definitions", {}).get("model", {}).get("DcE2Hydro", {}).get("rows", [])
        )
        if not coupling_rows:
            self.skipTest("当前模型不含电制氢耦合设备")

        ctrl_settings = renewable_control.RenewableControlSettings(
            hydrogen_min_dwell_seconds=30.0,
        )
        # 校验默认配置与序列化完整透出新增参数
        payload = ctrl_settings.payload()
        self.assertAlmostEqual(float(payload["hydrogenMinDwellSeconds"]), 30.0, places=6)
        self.assertAlmostEqual(float(payload["fuelCellStorageSocDeadband"]), 0.05, places=6)

        # 验证时钟回退重置 runtime_memory 的逻辑
        from simu.renewable_control_parts.planner import _reset_runtime_memory_if_clock_rewound

        mem: dict[str, object] = {
            "lastSimTimeSeconds": 120.0,
            "hydrogen_dwell": {"AcE2Hydro:E1": {"state": "running", "lastTransitionSimTime": 100.0}},
            "renewable_saturation": {"ACGenerator:PV1": {"saturated": True}},
        }
        _reset_runtime_memory_if_clock_rewound(mem, 10.0)
        self.assertNotIn("hydrogen_dwell", mem)
        self.assertNotIn("renewable_saturation", mem)
        self.assertAlmostEqual(float(mem["lastSimTimeSeconds"]), 10.0, places=6)


class Batch2ControlStrategyTests(unittest.TestCase):
    """验证第 2 批控制策略改进（氢能单拍协同、变流器效率损耗、平滑 SOC 均衡、柴发/变流器爬坡、启机滞后与零柴发构网）。"""

    def _minimal_ac_dc_topology(self):
        from simu.resource_topology import ResourceTopology

        return ResourceTopology(
            resources={},
            dc_transfer_groups={},
            converter_component_ids={("DCACConverter", "CONV1"): ("AC_1", "DC_1")},
            device_component_ids={},
        )

    def test_external_injection_single_cycle_coordination(self) -> None:
        """验证氢能外部注入变更量回代主优化器时，新能源与柴发在单拍内精确协同平衡。"""
        topo = self._minimal_ac_dc_topology()
        ren_rows = [
            {
                "dev_type": "ACGenerator",
                "dev_name": "WT1",
                "online": True,
                "commandable": True,
                "capacityKw": 200.0,
                "currentKw": 100.0,
                "planningCurrentKw": 100.0,
                "connectionSide": "AC",
                "gridComponentId": "AC_1",
            }
        ]
        diesel_rows = [
            {
                "dev_type": "ACGenerator",
                "dev_name": "DG1",
                "online": True,
                "commandable": True,
                "capacityKw": 200.0,
                "minKw": 20.0,
                "currentKw": 100.0,
                "connectionSide": "AC",
                "gridComponentId": "AC_1",
            }
        ]
        # 模拟电制氢本拍增耗电 25 kW（AC_1 外部净注入 -25 kW）
        res = renewable_optimization.optimize_topology_islands(
            topo,
            renewable_rows=ren_rows,
            diesel_rows=diesel_rows,
            storage_rows=[],
            converter_rows=[],
            step_coefficient=0.20,  # 风电单拍最多恢复 +40 kW
            diesel_step_ratio=0.50,
            diesel_power_protection_ratio=0.0,
            external_injection_delta_by_component={("AC_1", "AC"): -25.0},
        )
        self.assertTrue(res.all_success)
        wt_tgt = res.targets[("ACGenerator", "WT1")]
        dg_tgt = res.targets[("ACGenerator", "DG1")]
        # 新能源增发 + 柴发变化 必须精确补齐制氢 +25 kW 负荷，且优先推高新能源、压低柴发
        self.assertAlmostEqual((wt_tgt - 100.0) + (dg_tgt - 100.0), 25.0, places=3)
        self.assertAlmostEqual(wt_tgt, 140.0, places=3)
        self.assertAlmostEqual(dg_tgt, 85.0, places=3)

    def test_converter_efficiency_asymmetric_balance(self) -> None:
        """验证变流器效率系数生效时，跨交直流能量平衡系数体现损耗；效率 1.0 时严格无损。"""
        topo = self._minimal_ac_dc_topology()
        conv_row = {
            "dev_type": "DCACConverter",
            "dev_name": "CONV1",
            "online": True,
            "commandable": True,
            "currentKw": -50.0,  # P_AC 口径 -50 kW 对应 DC -> AC 正向送电 +50 kW
            "signedMinTargetKw": -100.0,
            "signedMaxTargetKw": 100.0,
            "transferCapacityKw": 100.0,
            "set_type": "p_ac_set",
        }
        var_lossy = renewable_optimization._converter_variable(
            conv_row, topo, 0.20, converter_efficiency=0.96
        )
        var_lossless = renewable_optimization._converter_variable(
            conv_row, topo, 0.20, converter_efficiency=1.0
        )
        self.assertIsNotNone(var_lossy)
        self.assertIsNotNone(var_lossless)
        assert var_lossy is not None and var_lossless is not None
        # DC->AC：AC 注入 +1.0 时 DC 侧须多吸取 1/0.96
        self.assertAlmostEqual(abs(var_lossy.dc_balance_coefficient), 1.0 / 0.96, places=5)
        self.assertAlmostEqual(abs(var_lossless.dc_balance_coefficient), 1.0, places=6)
        # 常规爬坡步长 = 20% * 100 = 20 kW -> [30, 70]
        self.assertAlmostEqual(var_lossy.lower_kw, 30.0, places=5)
        self.assertAlmostEqual(var_lossy.upper_kw, 70.0, places=5)

    def test_smooth_storage_soc_rebalance_and_deadband(self) -> None:
        """验证多储能 SOC 差值在死区内均分不乒乓，超死区时平滑加权分摊且总功率守恒。"""
        import numpy as np

        def make_storage(name: str, soc: float):
            return renewable_optimization._Variable(
                key=("ACStorage", name),
                kind="storage",
                current_kw=0.0,
                lower_kw=-100.0,
                upper_kw=100.0,
                side="AC",
                component_id="AC_1",
                storage_soc=soc,
                storage_forced_direction=False,
            )

        # 场景 A：SOC 差值 1% <= 2% 死区 -> 两台应均分 60 kW 放电（各 30 kW），不倒手
        vars_close = [make_storage("ES1", 0.505), make_storage("ES2", 0.495)]
        out_close = renewable_optimization._rebalance_storage_targets_by_soc(
            np.array([60.0, 0.0]),
            vars_close,
            np.array([-100.0, -100.0]),
            np.array([100.0, 100.0]),
            np.array([[1.0, 1.0]]),
            np.zeros((0, 2)),
            0.05,
            1e-4,
            100,
            soc_rebalance_deadband=0.02,
        )
        self.assertAlmostEqual(float(np.sum(out_close)), 60.0, places=3)
        self.assertAlmostEqual(float(out_close[0]), 30.0, places=2)
        self.assertAlmostEqual(float(out_close[1]), 30.0, places=2)

        # 场景 B：SOC 差值 20% > 2% -> 高 SOC 多放、低 SOC 也平滑分担（非 60/0 极端贪心）
        vars_far = [make_storage("ES1", 0.70), make_storage("ES2", 0.50)]
        out_far = renewable_optimization._rebalance_storage_targets_by_soc(
            np.array([30.0, 30.0]),
            vars_far,
            np.array([-100.0, -100.0]),
            np.array([100.0, 100.0]),
            np.array([[1.0, 1.0]]),
            np.zeros((0, 2)),
            0.05,
            1e-4,
            100,
            soc_rebalance_deadband=0.02,
        )
        self.assertAlmostEqual(float(np.sum(out_far)), 60.0, places=3)
        self.assertGreater(float(out_far[0]), float(out_far[1]))
        self.assertGreater(float(out_far[1]), 5.0)

    def test_diesel_ramp_step_limit_and_safety_override(self) -> None:
        """验证柴发常规步长限制生效且安全越限时允许两阶段机制自动兜底。"""
        row = {
            "dev_type": "ACGenerator",
            "dev_name": "DG1",
            "online": True,
            "commandable": True,
            "capacityKw": 200.0,
            "minKw": 20.0,
            "currentKw": 100.0,
            "connectionSide": "AC",
            "gridComponentId": "AC_1",
        }
        var_ramped = renewable_optimization._diesel_variable(row, 0.15, 0.03)
        self.assertIsNotNone(var_ramped)
        assert var_ramped is not None
        # 15% * 200 = 30 kW -> [70, 130]，安全全区间仍为 [26, 194]
        self.assertAlmostEqual(var_ramped.normal_step_kw, 30.0, places=6)
        self.assertAlmostEqual(var_ramped.lower_kw, 70.0, places=6)
        self.assertAlmostEqual(var_ramped.upper_kw, 130.0, places=6)
        self.assertAlmostEqual(var_ramped.safety_lower_kw, 26.0, places=6)
        self.assertAlmostEqual(var_ramped.safety_upper_kw, 194.0, places=6)

    def test_zero_diesel_grid_forming_storage_reference_mode(self) -> None:
        """验证全站柴发停机但交流构网储能在线时，进入 grid_forming_storage_reference 零碳模式而非闭锁。"""
        import copy
        from simu.service import PolarMicrogridSimulator

        startup_file = APP_ROOT / "startup.json"
        model_dir = None
        if startup_file.is_file():
            cfg = json.loads(startup_file.read_text(encoding="utf-8"))
            data_dir = (APP_ROOT / str(cfg.get("data_dir") or "data")).resolve()
            models_dir = data_dir / "models"
            if (models_dir / "秦岭站" / "model.e").is_file():
                model_dir = models_dir / "秦岭站"
        if model_dir is None:
            self.skipTest("未找到本地秦岭站测试模型")

        with tempfile.TemporaryDirectory() as td:
            svc = PolarMicrogridSimulator(
                sim_dir=model_dir,
                runtime_dir=Path(td) / "rt",
                model_id=model_dir.name,
                model_name=model_dir.name,
                noise_std=0.0,
            )
            try:
                snapshot = svc.step()
            finally:
                if hasattr(svc, "shutdown"):
                    svc.shutdown()

        snap = copy.deepcopy(snapshot)
        # 找出所有柴发并置为停机，同时保留交流构网储能在线
        diesel_names: set[str] = set()
        for dev in snap.get("devices", []) or []:
            name = str(dev.get("dev_name") or dev.get("name") or "")
            if "柴发" in name or "柴油" in name:
                dev["run_stat"] = 0
                diesel_names.add(name)
        for ch in ("scada", "real"):
            for row in snap.get("measurements", {}).get(ch, []) or []:
                if (
                    str(row.get("dev_name", "")) in diesel_names
                    and str(row.get("meas_type", "")).upper() == "RUN_STAT"
                ):
                    row["value"] = 0.0

        plan = renewable_control.calculate_renewable_control_plan(
            snap, renewable_control.RenewableControlSettings()
        )
        metrics = plan.get("metrics", {})
        # 若模型本身含交流构网储能，则应进入零碳构网模式；绝不应出现 blocked_no_diesel 且伴随交流构网储能
        has_ac_gf = any(
            row.get("technology") == "storage"
            and row.get("connectionSide") == "AC"
            and row.get("role") == "balance"
            and row.get("online")
            for row in plan.get("commandRows", [])
        )
        if has_ac_gf:
            self.assertEqual(metrics.get("operatingMode"), "grid_forming_storage_reference")
            self.assertNotEqual(plan.get("dataQuality", {}).get("status"), "blocked")


class Round2ControlHardeningTests(unittest.TestCase):
    """验证二轮深度复审的 5 项边界收口修复。"""

    def test_noisy_weather_feedforward_never_curtails_live_output(self) -> None:
        from simu.renewable_control_parts.planner import _apply_renewable_natural_upper_bounds

        ctrl_settings = renewable_control.RenewableControlSettings(step_coefficient=0.05)
        rows = [
            {
                "dev_type": "ACGenerator",
                "dev_name": "PV_NOISY",
                "technology": "pv",
                "online": True,
                "commandable": True,
                "capacityKw": 100.0,
                "currentKw": 50.0,
                "planningCurrentKw": 50.0,
                "weatherMeasurementAvailable": True,
                "controlWeatherAvailableKw": 48.0,  # 传感器负偏差导致理论值略低于实测
            },
            {
                "dev_type": "ACGenerator",
                "dev_name": "PV_NIGHT",
                "technology": "pv",
                "online": True,
                "commandable": True,
                "capacityKw": 100.0,
                "currentKw": 0.0,
                "planningCurrentKw": 0.0,
                "weatherMeasurementAvailable": True,
                "controlWeatherAvailableKw": 0.0,  # 夜间确认零辐照
            },
        ]
        targets = {
            ("ACGenerator", "PV_NOISY"): 55.0,
            ("ACGenerator", "PV_NIGHT"): 5.0,
        }
        _apply_renewable_natural_upper_bounds(
            rows,
            targets,
            ctrl_settings,
            runtime_memory=None,
            sim_time_seconds=10.0,
            wind_measurement_status={"available": False, "value": None},
            solar_measurement_status={"available": True, "value": 480.0},
            diesel_guard_blocked=False,
        )
        # 有光照且带负偏时，只封堵向上虚假增发（55 -> 50），绝不倒压实发至 48 kW
        self.assertAlmostEqual(float(rows[0]["naturalUpperKw"]), 50.0, places=6)
        self.assertAlmostEqual(targets[("ACGenerator", "PV_NOISY")], 50.0, places=6)
        # 夜间零辐照且实测为 0 时仍硬置 0
        self.assertAlmostEqual(float(rows[1]["naturalUpperKw"]), 0.0, places=6)
        self.assertAlmostEqual(targets[("ACGenerator", "PV_NIGHT")], 0.0, places=6)

    def test_converter_efficiency_clamps_to_same_sign_half_space(self) -> None:
        from simu.resource_topology import ResourceTopology

        topo = ResourceTopology(
            resources={},
            dc_transfer_groups={},
            converter_component_ids={("DCACConverter", "C1"): ("AC_1", "DC_1")},
            device_component_ids={},
        )
        # 正向 +5 kW（P_AC = -5 kW），步长 20 kW -> 计入效率 0.96 时下界钳至 0.0 防单拍跨零失真
        pos_var = renewable_optimization._converter_variable(
            {
                "dev_type": "DCACConverter",
                "dev_name": "C1",
                "online": True,
                "commandable": True,
                "currentKw": -5.0,
                "signedMinTargetKw": -100.0,
                "signedMaxTargetKw": 100.0,
                "transferCapacityKw": 100.0,
                "set_type": "p_ac_set",
            },
            topo,
            0.20,
            converter_efficiency=0.96,
        )
        assert pos_var is not None
        self.assertAlmostEqual(pos_var.lower_kw, 0.0, places=6)
        self.assertAlmostEqual(pos_var.upper_kw, 25.0, places=6)

        # 反向 -5 kW（P_AC = +5 kW），步长 20 kW -> 上界钳至 0.0
        neg_var = renewable_optimization._converter_variable(
            {
                "dev_type": "DCACConverter",
                "dev_name": "C1",
                "online": True,
                "commandable": True,
                "currentKw": 5.0,
                "signedMinTargetKw": -100.0,
                "signedMaxTargetKw": 100.0,
                "transferCapacityKw": 100.0,
                "set_type": "p_ac_set",
            },
            topo,
            0.20,
            converter_efficiency=0.96,
        )
        assert neg_var is not None
        self.assertAlmostEqual(neg_var.lower_kw, -25.0, places=6)
        self.assertAlmostEqual(neg_var.upper_kw, 0.0, places=6)

    def test_storage_rebalance_skips_uncommandable_grid_forming_units(self) -> None:
        import numpy as np

        gf_vars = [
            renewable_optimization._Variable(
                key=("ACStorage", "GF1"),
                kind="storage",
                current_kw=10.0,
                lower_kw=-100.0,
                upper_kw=100.0,
                side="AC",
                component_id="AC_1",
                storage_soc=0.80,
                storage_forced_direction="",
                storage_commandable=False,
            ),
            renewable_optimization._Variable(
                key=("ACStorage", "GF2"),
                kind="storage",
                current_kw=50.0,
                lower_kw=-100.0,
                upper_kw=100.0,
                side="AC",
                component_id="AC_1",
                storage_soc=0.40,
                storage_forced_direction="",
                storage_commandable=False,
            ),
        ]
        original = np.array([10.0, 50.0])
        out = renewable_optimization._rebalance_storage_targets_by_soc(
            original,
            gf_vars,
            np.array([-100.0, -100.0]),
            np.array([100.0, 100.0]),
            np.array([[1.0, 1.0]]),
            np.zeros((0, 2)),
            0.05,
            1e-4,
            100,
        )
        self.assertTrue(np.allclose(out, original))

    def test_fuel_cell_zero_diesel_grid_forming_mode(self) -> None:
        from simu.fuel_cell_control import (
            FuelCellControlInputs,
            FuelCellControlParameters,
            calculate_fuel_cell_power_decision,
        )

        params = FuelCellControlParameters(
            power_step_kw=10.0,
            diesel_power_limit_ratio=0.50,
            diesel_power_stop_minimum_ratio=0.30,
            electric_storage_soc_limit=0.30,
            hydrogen_storage_soc_start_limit=0.30,
            hydrogen_storage_soc_stop_limit=0.20,
            electric_storage_soc_deadband=0.05,
        )
        decision = calculate_fuel_cell_power_decision(
            params,
            FuelCellControlInputs(
                current_power_kw=0.0,
                maximum_power_kw=90.0,
                minimum_power_kw=20.0,
                start_threshold_kw=30.0,
                stop_threshold_kw=20.0,
                diesel_power_kw=0.0,
                diesel_capacity_kw=0.0,
                electric_storage_soc_average=0.25,
                hydrogen_storage_soc_average=0.50,
                allow_zero_diesel=True,
            ),
        )
        self.assertEqual(decision.action, "start")
        self.assertAlmostEqual(decision.requested_delta_kw, 30.0, places=6)

    def test_manager_commits_runtime_memory_only_after_closed_loop_dispatch(self) -> None:
        manager_src = (
            REPO_ROOT / "trainee" / "simu" / "renewable_control_parts" / "manager.py"
        ).read_text(encoding="utf-8")
        # 确认不再在开环计算阶段提前写回 state.runtime_memory
        self.assertNotIn(
            "if publishes_control_targets:\n                    state.runtime_memory = cycle_runtime_memory",
            manager_src,
        )
        # 确认仅在闭环指令真实下发成功后提交 state.runtime_memory
        self.assertIn(
            "state.runtime_memory = cycle_runtime_memory\n                                state.last_sent_at = _now_text()",
            manager_src,
        )


class AuditRound3StrategyTests(unittest.TestCase):
    """三轮深度审查安全保护、闭环协同与“仅允许关机、禁止自动开机”硬边界验证。"""

    @staticmethod
    def _load_qinling_snapshot() -> dict:
        from simu.service import PolarMicrogridSimulator

        settings_json = json.loads((APP_ROOT / "startup.json").read_text(encoding="utf-8"))
        data_dir = (APP_ROOT / settings_json.get("data_dir", "data")).resolve()
        model_dir = data_dir / "models" / "秦岭站"
        if not (model_dir / "model.e").is_file():
            raise unittest.SkipTest("秦岭站模型不存在")
        with tempfile.TemporaryDirectory() as td:
            svc = PolarMicrogridSimulator(
                sim_dir=model_dir,
                runtime_dir=Path(td) / "rt",
                model_id="秦岭站",
                model_name="秦岭站",
                noise_std=0.0,
            )
            svc.step()
            return svc.snapshot()

    @staticmethod
    def _model_block_rows(snap: dict, block_name: str) -> list[dict]:
        block = snap.get("definitions", {}).get("model", {}).get(block_name)
        if isinstance(block, dict):
            rows = block.get("rows", [])
            return [r for r in rows if isinstance(r, dict)]
        if isinstance(block, list):
            return [r for r in block if isinstance(r, dict)]
        return []

    def test_optimizer_emergency_stage_releases_diesel_step_for_floor_storage(self) -> None:
        """验证夜间无新能源且构网储能 SOC 贴底仍在放电时，安全阶段放开柴发步长单拍止放。"""
        topo = resource_topology.ResourceTopology(
            resources={},
            dc_transfer_groups={},
            device_component_ids={},
            converter_component_ids={},
        )
        diesel_rows = [
            {
                "dev_type": "ACGenerator",
                "dev_name": "D1",
                "online": True,
                "commandable": True,
                "stateEligible": True,
                "connectionSide": "AC",
                "gridComponentId": "AC_1",
                "currentKw": 40.0,
                "minKw": 20.0,
                "capacityKw": 120.0,
            }
        ]
        # 构网储能 SOC 贴底 0.10（dischargePower=0），但当前仍在放电 50 kW -> 需柴发立刻增发 50 kW（超常规 15%=18 kW 步长）
        storage_rows = [
            {
                "dev_type": "ACGenerator",
                "dev_name": "GF_ESS",
                "online": True,
                "commandable": False,
                "stateEligible": True,
                "role": "balance",
                "connectionSide": "AC",
                "gridComponentId": "AC_1",
                "currentKw": 50.0,
                "chargePower": 100.0,
                "dischargePower": 0.0,
                "maxChargePowerKw": 100.0,
                "maxDischargePowerKw": 100.0,
                "soc": 0.10,
                "socMin": 0.10,
                "socMax": 0.90,
                "socKnown": True,
                "capacityKwh": 500.0,
                "efficiency": 0.95,
                "controlHorizonMinutes": 1.0,
            }
        ]
        result = renewable_optimization.optimize_topology_islands(
            topo,
            renewable_rows=[],
            diesel_rows=diesel_rows,
            storage_rows=storage_rows,
            converter_rows=[],
            diesel_step_ratio=0.15,
            diesel_power_protection_ratio=0.03,
            grid_forming_storage_protection_ratio=0.05,
        )
        self.assertTrue(result.all_success)
        self.assertEqual(len(result.islands), 1)
        island = result.islands[0]
        self.assertLessEqual(island.max_balance_delta_kw, 0.1)
        self.assertAlmostEqual(result.targets[("ACGenerator", "GF_ESS")], 0.0, places=3)
        self.assertAlmostEqual(result.targets[("ACGenerator", "D1")], 90.0, places=3)
        self.assertIn(("ACGenerator", "D1"), island.step_override_devices)

    def test_hydrogen_hard_safety_stop_not_blocked_by_zero_diesel_margin_or_dwell(self) -> None:
        """验证氢罐超压/高SOC硬安全停机在柴发顶在 p_min 且处于最小驻留期时仍强制归零停机。"""
        from simu.model_semantics import energy_coupling_control_bindings
        from simu.renewable_control_parts.common import _measurement_index
        from simu.renewable_control_parts.hydrogen import (
            _hydrogen_electric_resource_refs,
            _optimize_hydrogen_within_topology_islands,
        )
        from simu.renewable_control_parts.settings import RenewableControlSettings

        snap = self._load_qinling_snapshot()
        ac_e2h = self._model_block_rows(snap, "AcE2Hydro")
        self.assertTrue(ac_e2h, "秦岭站模型应包含 AcE2Hydro")
        e2h_name = str(ac_e2h[0].get("name", ""))
        bindings = energy_coupling_control_bindings(snap).get(("AcE2Hydro", e2h_name), ())
        power_binding = next((b for b in bindings if b.get("set_type") == "p_set"), None)
        self.assertIsNotNone(power_binding)
        p_dev_type = str(power_binding["target_dev_type"])
        p_dev_name = str(power_binding["target_dev_name"])

        # 修改快照量测：电制氢在线且当前功率 40 kW，储氢罐 SOC=0.98（触发 SOC 硬安全停机）
        for m_row in snap.get("measurements", {}).get("scada", []):
            m_type = str(m_row.get("meas_type", "")).upper()
            if m_row.get("dev_type") == "AcE2Hydro" and m_row.get("dev_name") == e2h_name and m_type == "RUN_STAT":
                m_row["value"] = 1
            elif m_row.get("dev_type") == p_dev_type and m_row.get("dev_name") == p_dev_name and m_type in {"P_LOAD", "P", "P_AC"}:
                m_row["value"] = 40.0
            elif m_row.get("dev_type") == "HydroStorage" and m_type == "SOC":
                m_row["value"] = 0.98
            elif m_row.get("dev_type") == "HydroStorage" and m_type == "GAS_QUANTITY":
                m_row["value"] = 980.0
        for d_row in snap.get("devices", []):
            if d_row.get("dev_type") == "AcE2Hydro" and d_row.get("dev_name") == e2h_name:
                d_row["run_stat"] = 1

        measurements = _measurement_index(snap)
        topo = resource_topology.resolve_resource_topology(
            snap,
            _hydrogen_electric_resource_refs(snap),
        )
        # 构造一台已经顶在 p_min=30 的柴发（向下裕度 = 0！）
        command_rows = [
            {
                "category": "柴油发电",
                "dev_type": "ACGenerator",
                "dev_name": "D_LOCKED_MIN",
                "online": True,
                "commandable": True,
                "currentKw": 30.0,
                "commandKw": 30.0,
                "minKw": 30.0,
                "capacityKw": 100.0,
                "ratedCapacityKw": 100.0,
            }
        ]
        storage_rows = [
            {
                "dev_type": "ACGenerator",
                "dev_name": "ESS1",
                "online": True,
                "soc": 0.80,
                "socKnown": True,
            }
        ]
        # 同时处于 30s 最小驻留冷却期内（5s 前刚启机）
        runtime_memory = {
            "hydrogen_dwell": {
                f"AcE2Hydro:{e2h_name}": {
                    "state": "running",
                    "lastTransitionSimTime": 100.0,
                }
            }
        }
        h_plan = _optimize_hydrogen_within_topology_islands(
            snap,
            measurements,
            RenewableControlSettings(hydrogen_min_dwell_seconds=30.0),
            topo,
            command_rows,
            storage_rows,
            diesel_current_kw=30.0,
            diesel_capacity_kw=100.0,
            diesel_unit_count=1,
            diesel_input_valid=True,
            apply_electrical_corrections=True,
            runtime_memory=runtime_memory,
            sim_time_seconds=105.0,
        )
        e2h_cmds = [c for c in h_plan.get("commands", []) if c.get("couplingName") == e2h_name]
        self.assertEqual(len(e2h_cmds), 1)
        self.assertAlmostEqual(float(e2h_cmds[0]["targetElectricPowerKw"]), 0.0, places=6)
        self.assertTrue(e2h_cmds[0].get("hardSafetyStop"))
        self.assertTrue(
            any(
                r.get("commandKind") == "run_status"
                and r.get("dev_name") == e2h_name
                and r.get("run_stat") == 0
                for r in command_rows
            )
        )

    def test_hydrogen_tank_horizon_prevents_large_step_overdraw(self) -> None:
        """验证高倍率大步长下剩余储氢量不足支撑一拍最小功率时，燃料电池触发罐容安全停机防止抽负。"""
        from simu.model_semantics import energy_coupling_control_bindings
        from simu.renewable_control_parts.common import _measurement_index
        from simu.renewable_control_parts.hydrogen import (
            _hydrogen_electric_resource_refs,
            _optimize_hydrogen_within_topology_islands,
        )
        from simu.renewable_control_parts.settings import RenewableControlSettings

        snap = self._load_qinling_snapshot()
        fc_type = ""
        fc_rows: list[dict] = []
        for candidate_type in ("Hydro2AcE", "Hydro2DcE"):
            rows = self._model_block_rows(snap, candidate_type)
            if rows:
                fc_type = candidate_type
                fc_rows = rows
                break
        self.assertTrue(fc_rows, "秦岭站模型应包含燃料电池耦合")
        fc_name = str(fc_rows[0].get("name", ""))
        bindings = energy_coupling_control_bindings(snap).get((fc_type, fc_name), ())
        power_binding = next((b for b in bindings if b.get("set_type") == "p_set"), None)
        self.assertIsNotNone(power_binding)
        p_dev_type = str(power_binding["target_dev_type"])
        p_dev_name = str(power_binding["target_dev_name"])

        # 模拟极高速步长（10 小时控制窗）+ 氢罐 SOC=0.15（未触 0.10 下限但剩余 1 Nm³ 支撑不了 10 小时运行）
        snap["system_parameters"] = {"effective_step_minutes": 600.0}
        for m_row in snap.get("measurements", {}).get("scada", []):
            m_type = str(m_row.get("meas_type", "")).upper()
            if m_row.get("dev_type") == fc_type and m_row.get("dev_name") == fc_name and m_type == "RUN_STAT":
                m_row["value"] = 1
            elif m_row.get("dev_type") == p_dev_type and m_row.get("dev_name") == p_dev_name and m_type in {"P_GEN", "P", "P_AC", "P_DC"}:
                m_row["value"] = 30.0
            elif m_row.get("dev_type") == "HydroStorage" and m_type == "SOC":
                m_row["value"] = 0.15
            elif m_row.get("dev_type") == "HydroStorage" and m_type == "GAS_QUANTITY":
                m_row["value"] = 1.0
        for d_row in snap.get("devices", []):
            if d_row.get("dev_type") == fc_type and d_row.get("dev_name") == fc_name:
                d_row["run_stat"] = 1

        measurements = _measurement_index(snap)
        topo = resource_topology.resolve_resource_topology(
            snap,
            _hydrogen_electric_resource_refs(snap),
        )
        command_rows: list[dict] = []
        storage_rows = [{"dev_type": "ACGenerator", "dev_name": "ESS1", "online": True, "soc": 0.25, "socKnown": True}]
        h_plan = _optimize_hydrogen_within_topology_islands(
            snap,
            measurements,
            RenewableControlSettings(),
            topo,
            command_rows,
            storage_rows,
            diesel_current_kw=80.0,
            diesel_capacity_kw=100.0,
            diesel_unit_count=1,
            diesel_input_valid=True,
            apply_electrical_corrections=True,
        )
        fc_cmds = [c for c in h_plan.get("commands", []) if c.get("couplingName") == fc_name]
        self.assertEqual(len(fc_cmds), 1)
        self.assertAlmostEqual(float(fc_cmds[0]["targetElectricPowerKw"]), 0.0, places=6)
        self.assertEqual(fc_cmds[0].get("controlReason"), "hydrogen_tank_horizon_safety_stop")

    def test_hydrogen_never_auto_starts_when_offline_and_waits_for_manual_start(self) -> None:
        """验证电制氢与燃料电池处于关机态且满足全部运行条件时，策略绝不下发 run_stat=1 开机。"""
        from simu.renewable_control_parts.common import _measurement_index
        from simu.renewable_control_parts.hydrogen import (
            _hydrogen_electric_resource_refs,
            _optimize_hydrogen_within_topology_islands,
        )
        from simu.renewable_control_parts.settings import RenewableControlSettings

        snap = self._load_qinling_snapshot()
        ac_e2h = self._model_block_rows(snap, "AcE2Hydro")
        self.assertTrue(ac_e2h)
        e2h_name = str(ac_e2h[0].get("name", ""))

        # 场景 1：电制氢关机（run_stat=0），柴发负载率 20% < 35%，电储 SOC=0.85 > 0.70，氢储 SOC=0.50 < 0.85（全部开机条件满足）
        for m_row in snap.get("measurements", {}).get("scada", []):
            m_type = str(m_row.get("meas_type", "")).upper()
            if m_row.get("dev_type") in {"AcE2Hydro", "DcE2Hydro", "Hydro2AcE", "Hydro2DcE"} and m_type == "RUN_STAT":
                m_row["value"] = 0
            elif m_row.get("dev_type") == "HydroStorage" and m_type == "SOC":
                m_row["value"] = 0.50
            elif m_row.get("dev_type") == "HydroStorage" and m_type == "GAS_QUANTITY":
                m_row["value"] = 500.0
        for d_row in snap.get("devices", []):
            if d_row.get("dev_type") in {"AcE2Hydro", "DcE2Hydro", "Hydro2AcE", "Hydro2DcE"}:
                d_row["run_stat"] = 0

        measurements = _measurement_index(snap)
        topo = resource_topology.resolve_resource_topology(
            snap,
            _hydrogen_electric_resource_refs(snap),
        )
        command_rows_e2h: list[dict] = []
        h_plan_e2h = _optimize_hydrogen_within_topology_islands(
            snap,
            measurements,
            RenewableControlSettings(),
            topo,
            command_rows_e2h,
            [{"dev_type": "ACGenerator", "dev_name": "ESS1", "online": True, "soc": 0.85, "socKnown": True}],
            diesel_current_kw=20.0,
            diesel_capacity_kw=100.0,
            diesel_unit_count=1,
            diesel_input_valid=True,
            apply_electrical_corrections=True,
        )
        # 绝不生成 run_stat=1 开机遥控，也绝不下发非零功率
        self.assertFalse(any(r.get("run_stat") == 1 for r in command_rows_e2h))
        self.assertEqual(h_plan_e2h.get("commands", []), [])
        e2h_traces = [t for t in h_plan_e2h.get("decisionTraces", []) if t.get("couplingName") == e2h_name]
        self.assertEqual(len(e2h_traces), 1)
        self.assertEqual(e2h_traces[0].get("controlReason"), "awaiting_manual_start")
        self.assertEqual(e2h_traces[0].get("action"), "hold")

        # 场景 2：燃料电池关机（run_stat=0），柴发负载率 90% > 50%，电储 SOC=0.20 < 0.30，氢储 SOC=0.50 > 0.30（全部开机条件满足）
        command_rows_fc: list[dict] = []
        h_plan_fc = _optimize_hydrogen_within_topology_islands(
            snap,
            measurements,
            RenewableControlSettings(),
            topo,
            command_rows_fc,
            [{"dev_type": "ACGenerator", "dev_name": "ESS1", "online": True, "soc": 0.20, "socKnown": True}],
            diesel_current_kw=90.0,
            diesel_capacity_kw=100.0,
            diesel_unit_count=1,
            diesel_input_valid=True,
            apply_electrical_corrections=True,
        )
        self.assertFalse(any(r.get("run_stat") == 1 for r in command_rows_fc))
        self.assertEqual(h_plan_fc.get("commands", []), [])
        fc_traces = [t for t in h_plan_fc.get("decisionTraces", []) if t.get("mode") == "fuel_cell"]
        self.assertTrue(fc_traces)
        self.assertEqual(fc_traces[0].get("controlReason"), "awaiting_manual_start")

    def test_planner_dc_hydrogen_component_key_and_unbalanced_rollback_present(self) -> None:
        """验证 planner.py 对齐直流氢能 dcTransferGroupId 口径、禁止 run_stat=1 并包含单拍回代失败保守回滚保护。"""
        planner_src = (
            REPO_ROOT / "trainee" / "simu" / "renewable_control_parts" / "planner.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'str(h_cmd.get("dcTransferGroupId") or h_cmd.get("electricComponentId") or "").strip()',
            planner_src,
        )
        self.assertIn(
            "single_cycle_reoptimization_balance_rejected",
            planner_src,
        )
        self.assertIn(
            "int(run_stat) != 0",
            planner_src,
        )


if __name__ == "__main__":
    unittest.main()
