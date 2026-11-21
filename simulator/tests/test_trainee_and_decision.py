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
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

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

            def diagnostics(self):
                return {"active": True}

        class _StubRenewableManager:
            def __init__(self) -> None:
                self._states = {
                    "m1": types.SimpleNamespace(revision=5, plan_revision=2, settings_revision=1)
                }

            def diagnostics(self):
                return {"ready": True}

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

        # 0. /api/health 应正常返回 200 且包含进程诊断字段
        sh, _, dh = _dispatch(b"GET /api/health HTTP/1.1\r\nHost: localhost\r\n\r\n")
        self.assertEqual(sh, 200)
        self.assertTrue(dh.get("ok"))
        self.assertEqual(dh.get("process", {}).get("role"), "trainee")
        self.assertEqual(dh.get("process", {}).get("model_id"), "m1")
        self.assertTrue(dh.get("process", {}).get("trainee_exchange", {}).get("active"))
        self.assertTrue(dh.get("process", {}).get("renewable_control", {}).get("ready"))

        # 1. /api/trainee/ui-frame 连续两次 GET 命中帧缓存，仅计算 1 次
        s1, _, d1 = _dispatch(b"GET /api/trainee/ui-frame?page=overview HTTP/1.1\r\nHost: localhost\r\n\r\n")
        s2, _, d2 = _dispatch(b"GET /api/trainee/ui-frame?page=overview HTTP/1.1\r\nHost: localhost\r\n\r\n")
        self.assertEqual((s1, s2), (200, 200))
        self.assertEqual(d1["snapshot"]["call"], 1)
        self.assertEqual(d2["snapshot"]["call"], 1)
        self.assertEqual(calls["ui_frame"], 1)

        # 2. /api/trainee/renewable-control 连续两次 GET 命中帧缓存
        s3, _, d3 = _dispatch(b"GET /api/trainee/renewable-control HTTP/1.1\r\nHost: localhost\r\n\r\n")
        s4, _, d4 = _dispatch(b"GET /api/trainee/renewable-control HTTP/1.1\r\nHost: localhost\r\n\r\n")
        self.assertEqual((s3, s4), (200, 200))
        self.assertEqual(d3["call"], 1)
        self.assertEqual(d4["call"], 1)
        self.assertEqual(calls["renewable"], 1)

        # 3. 发起 POST 变更后，帧缓存自动清空，再次 GET 重新计算
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
        self.assertEqual(d5["snapshot"]["call"], 2)
        self.assertEqual(calls["ui_frame"], 2)


class TraineeFrontendStructureTests(unittest.TestCase):
    """验证学员端前端模块化拆分与静态资产完整性。"""

    def test_trainee_frontend_modules_exist_and_referenced(self) -> None:
        web_dir = REPO_ROOT / "trainee" / "simu" / "web" / "trainee"
        index_html = (web_dir / "index.html").read_text(encoding="utf-8")
        self.assertFalse((web_dir / "app.js").exists(), "旧单体 app.js 应已移除")
        expected_modules = [
            "01-state-core.js",
            "02-diagram-core.js",
            "03-diagram-editor.js",
            "04-receive-models.js",
            "05-curves.js",
            "06-renewable-control.js",
            "07-measurements-commands.js",
            "08-bootstrap.js",
        ]
        for mod in expected_modules:
            self.assertTrue((web_dir / "js" / mod).is_file(), f"缺少模块文件：{mod}")
            self.assertIn(f"/js/{mod}", index_html, f"index.html 未引用：{mod}")


if __name__ == "__main__":
    unittest.main()
