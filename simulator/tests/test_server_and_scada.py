"""针对 server 路由安全、时钟调度、scada104 容错、efile_read 与模块拆分兼容性的回归测试。"""

from __future__ import annotations

import ast
import contextlib
import logging
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
SHARED_ROOT = REPO_ROOT / "shared"
TRAINEE_ROOT = REPO_ROOT / "trainee"
for _entry in (str(TRAINEE_ROOT), str(APP_ROOT), str(SHARED_ROOT)):
    if _entry in sys.path:
        sys.path.remove(_entry)
    sys.path.insert(0, _entry)

import scada104
from simu import http_common, renewable_control, server, service
from simu.http_common import resolve_static_target


class _MemoryStore:
    """最小 SQLite 内存点库，用于验证 scada104.Bridge 行为而不依赖外部 SCADA 仓库。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        with self.connection() as db, db:
            db.execute(
                "CREATE TABLE fes_channel_iec104_define ("
                "id INTEGER PRIMARY KEY, name TEXT, channel_id INTEGER, rtu_addr INTEGER, "
                "remote_host TEXT, remote_port INTEGER)"
            )
            db.execute(
                "CREATE TABLE fes_rtu_define ("
                "rtu_id INTEGER PRIMARY KEY, channel_id INTEGER, channel_type TEXT, name TEXT, process_enable INTEGER)"
            )
            for kind in ("yc", "yx", "yk", "yt"):
                extra = ", raw_value REAL, raw_status INTEGER, raw_time INTEGER" if kind == "yc" else ""
                db.execute(
                    f"CREATE TABLE fes_{kind}_define ("
                    "rtu_id INTEGER, pnt_no INTEGER, name TEXT, value REAL, status INTEGER, "
                    f"refresh_time INTEGER, man_disable INTEGER DEFAULT 0, auto_disable INTEGER DEFAULT 0{extra}, "
                    "PRIMARY KEY (rtu_id, pnt_no))"
                )

    @contextlib.contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()


class _FakeChannel:
    def __init__(self) -> None:
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def status(self, **_kwargs) -> dict:
        return {"running": self.running, "endpoint": {"host": "127.0.0.1", "port": 2405}}


class _FakeScadaServer:
    def __init__(self, db_path: Path) -> None:
        self.store = _MemoryStore(db_path)
        self._channels: dict[str, _FakeChannel] = {}

    def channel_services(self, rtu_id: int | None = None) -> dict[str, _FakeChannel]:
        if rtu_id is None:
            return dict(self._channels)
        key = f"iec104-rtu-{rtu_id}"
        return {key: self._channels.setdefault(key, _FakeChannel())}

    def database_info(self) -> dict[str, str]:
        return {"database": str(self.store.db_path)}


class ServerAndScadaTests(unittest.TestCase):
    def test_static_path_traversal_blocks_sibling_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            web_dir = root / "web"
            sibling = root / "web_secret"
            web_dir.mkdir()
            sibling.mkdir()
            (web_dir / "index.html").write_text("safe", encoding="utf-8")
            (sibling / "secret.txt").write_text("LEAK", encoding="utf-8")

            resolved = resolve_static_target(web_dir, "/../web_secret/secret.txt")
            self.assertEqual(resolved, (web_dir / "index.html").resolve())

    def test_clock_step_exception_logs_and_pauses(self):
        paused = []
        runtime_logs = []

        class _BrokenService:
            model_id = "faulty"
            compute_interval_seconds = 0.1

            def clock_state(self):
                return {"state": "running", "speed": 1, "effective_step_seconds": 1}

            def step(self, **kwargs):
                raise RuntimeError("power flow diverged")

            def control_clock(self, payload):
                paused.append(payload)

            def _append_runtime_log(self, level, category, message):
                runtime_logs.append((level, category, message))

        with self.assertLogs("simu.web", level=logging.ERROR) as cm:
            server._advance_clock_if_due(_BrokenService(), time.monotonic() - 1.0)
        self.assertTrue(any("power flow diverged" in msg for msg in cm.output))
        self.assertEqual(paused, [{"action": "pause"}])
        self.assertEqual(len(runtime_logs), 1)
        self.assertIn("power flow diverged", runtime_logs[0][2])

    def test_multi_model_clock_worker_non_blocking(self):
        fast_steps = []
        slow_started = threading.Event()

        class _ModelStub:
            def __init__(self, mid: str, delay: float) -> None:
                self.model_id = mid
                self.compute_interval_seconds = 0.1
                self.delay = delay

            def clock_state(self):
                return {"state": "running", "speed": 1, "effective_step_seconds": 1}

            def step(self, **kwargs):
                if self.delay > 0:
                    slow_started.set()
                    time.sleep(self.delay)
                else:
                    fast_steps.append(time.monotonic())

            def control_clock(self, payload):
                pass

        class _MultiStub:
            def __init__(self, items):
                self._items = items

            def iter_services(self):
                return list(self._items)

        multi = _MultiStub([_ModelStub("slow", 0.5), _ModelStub("fast", 0.0)])
        stop_event = threading.Event()
        worker = server.start_multi_model_clock_worker(multi, stop_event)
        try:
            time.sleep(0.45)
        finally:
            stop_event.set()
            worker.join(timeout=2.0)
        # 慢模型阻塞 0.5s 期间，快模型（0.1s 周期）仍应推进多次（>= 2 次）
        self.assertGreaterEqual(len(fast_steps), 2)

    def test_scada104_catalog_timeout_keeps_online_models_valid(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "scdfe_s.db"
            fake_srv = _FakeScadaServer(db_path)
            bridge = scada104.Bridge(
                fake_srv,
                "http://127.0.0.1:18710",
                first_port=2405,
                interval=0.5,
                offline_failure_threshold=3,
            )

            catalog_fail = [False]
            model_fail = [False]
            sample_val = [100.5]

            def fake_request(base, path, payload=None, **kwargs):
                if path == "/api/models":
                    if catalog_fail[0]:
                        raise TimeoutError("catalog timed out")
                    return {
                        "models": [
                            {"id": "qinling", "service": {"healthy": True, "base_url": "http://127.0.0.1:18716"}}
                        ]
                    }
                if model_fail[0]:
                    raise OSError("model disconnected")
                if path == "/api/measurements":
                    rows = [{"name": "ACLoad.a.p", "meas_type": "P", "value": sample_val[0], "valid": 1}]
                    return {"definitions": rows, "scada": rows}
                if path == "/api/external/controls/names":
                    return {"model_id": "qinling", "yk_names": [], "yt_names": ["ACLoad.a.p_set"]}
                raise AssertionError(f"unexpected path: {path}")

            with patch.object(scada104, "request", side_effect=fake_request), \
                 patch.object(scada104, "port_available", return_value=True):
                # 首次正常上线
                bridge.poll_once()
                with fake_srv.store.connection() as db:
                    row = db.execute("SELECT value, status FROM fes_yc_define WHERE name='ACLoad.a.p'").fetchone()
                self.assertEqual(row, (100.5, 0))

                # 目录超时，但模型服务仍直连可达且数值更新 -> 不应下线、不应置 status=128
                catalog_fail[0] = True
                sample_val[0] = 112.25
                bridge.poll_once()
                self.assertTrue(bridge.models[1]["online"])
                with fake_srv.store.connection() as db:
                    row = db.execute("SELECT value, status FROM fes_yc_define WHERE name='ACLoad.a.p'").fetchone()
                self.assertEqual(row, (112.25, 0))

                # 目录仍超时且直连偶发失败 2 次（< 阈值 3）-> 保持有效防闪断
                model_fail[0] = True
                bridge.poll_once()
                bridge.poll_once()
                self.assertTrue(bridge.models[1]["online"])
                with fake_srv.store.connection() as db:
                    row = db.execute("SELECT status FROM fes_yc_define WHERE name='ACLoad.a.p'").fetchone()
                self.assertEqual(row, (0,))

                # 第 3 次连续失败 -> 达到阈值，正式置离线并标 128
                bridge.poll_once()
                self.assertFalse(bridge.models[1]["online"])
                with fake_srv.store.connection() as db:
                    row = db.execute("SELECT status FROM fes_yc_define WHERE name='ACLoad.a.p'").fetchone()
                self.assertEqual(row, (128,))

    def test_scada104_default_root_from_env(self):
        with patch.dict(os.environ, {"SCADA_ROOT": r"C:\custom\scada"}):
            self.assertEqual(scada104.default_scada_root({}), Path(r"C:\custom\scada"))

    def test_efile_read_without_exec_preserves_conversion(self):
        efile_src = (SHARED_ROOT / "src/hybrid_power_system_analysis/efile_read.py").read_text(encoding="utf-8")
        self.assertNotIn("exec(", efile_src)
        import efile_read

        RowCls = efile_read._row_class_factory(
            "SampleRow",
            ["id", "p", "name"],
            [efile_read._safe_int_cell, efile_read._safe_float_cell, efile_read._identity_cell],
        )
        obj = RowCls(["42", "3.14", "bus_1"])
        self.assertEqual(obj.id, 42)
        self.assertAlmostEqual(obj.p, 3.14)
        self.assertEqual(obj.name, "bus_1")

        DictCls = efile_read._class_factory(
            "SampleDict",
            ["id", "p", "name"],
            [efile_read._safe_int_cell, efile_read._safe_float_cell, efile_read._identity_cell],
        )
        obj2 = DictCls({"id": "7.5", "p": "bad", "name": "n2"})
        self.assertAlmostEqual(obj2.id, 7.5)
        self.assertEqual(obj2.p, "bad")
        self.assertEqual(obj2.name, "n2")

    def test_hybrid_lf_has_no_utf8_bom(self):
        path = SHARED_ROOT / "src/hybrid_power_system_analysis/lfcore/hybrid_lf.py"
        raw = path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "hybrid_lf.py 不应包含 UTF-8 BOM")
        ast.parse(raw.decode("utf-8"))

    def test_facade_modules_export_compatibility(self):
        for name in ("make_http_server", "create_model_from_efile", "make_definition_archive", "JsonApiError"):
            self.assertTrue(hasattr(server, name), f"server missing {name}")
        for name in ("PolarMicrogridSimulator", "MultiModelSimulator", "ClockState"):
            self.assertTrue(hasattr(service, name), f"service missing {name}")
        for name in ("RenewableControlSettings", "calculate_renewable_control_plan", "TraineeRenewableControlManager"):
            self.assertTrue(hasattr(renewable_control, name), f"renewable_control missing {name}")
        self.assertTrue(hasattr(http_common, "local_urlopen"))

    def test_scada104_list_control_points_returns_active_and_disabled_flags(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "scdfe_s.db"
            fake_srv = _FakeScadaServer(db_path)
            bridge = scada104.Bridge(fake_srv, "http://127.0.0.1:18710", first_port=2405)
            with patch.object(scada104, "port_available", return_value=True):
                rtu = bridge.channel("qinling")
            bridge.sync_points(
                rtu,
                {
                    "yc": {},
                    "yx": {},
                    "yk": {"CB1.status": None, "CB2.status": None},
                    "yt": {"ESS1.p_set": None},
                },
            )
            with fake_srv.store.connection() as db, db:
                db.execute("UPDATE fes_yk_define SET man_disable=1 WHERE rtu_id=? AND pnt_no=2", (rtu,))
            yk_items = bridge.list_control_points(rtu, "yk")
            self.assertEqual(len(yk_items), 2)
            self.assertFalse(yk_items[0]["disabled"])
            self.assertTrue(yk_items[1]["disabled"])
            yt_items = bridge.list_control_points(rtu, "yt")
            self.assertEqual(len(yt_items), 1)
            self.assertEqual(yt_items[0]["source_name"], "ESS1.p_set")

    def test_discover_local_simulator_services_sorts_healthy_first(self):
        from simu import http_routes

        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def read(self):
                return (
                    '{"models": ['
                    '{"id": "b", "name": "B站", "service": {"base_url": "http://127.0.0.1:18712", "state": "stopped", "healthy": false}},'
                    '{"id": "a", "name": "A站", "service": {"base_url": "http://127.0.0.1:18711", "state": "running", "healthy": true}}'
                    ']}'
                ).encode("utf-8")

        with patch.object(http_routes, "local_urlopen", return_value=_FakeResp()):
            discovered = http_routes._discover_local_simulator_services("http://127.0.0.1:18710")
        self.assertTrue(discovered["ok"])
        self.assertEqual([s["model_id"] for s in discovered["services"]], ["a", "b"])
        self.assertTrue(discovered["services"][0]["healthy"])

    def test_encoded_response_cache_and_atomic_write_and_log_tail(self):
        import simu_loop
        from simu.simulator_cluster import _read_log_tail

        cache = http_common.EncodedResponseCache(max_entries=4)
        raw, gz = http_common.encode_json_for_cache({"payload": "x" * 2048})
        self.assertGreater(len(raw), len(gz) > 0)
        cache.put(("k1",), raw, gz)
        self.assertEqual(cache.get(("k1",)), (raw, gz))
        cache.clear()
        self.assertIsNone(cache.get(("k1",)))

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "real.e"
            simu_loop._atomic_write_text(target, "hello atomic\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "hello atomic\n")
            self.assertEqual([p.name for p in Path(td).iterdir()], ["real.e"])

            log_file = Path(td) / "crash.log"
            log_file.write_text("line1\nTraceback...\nRuntimeError: boom\n", encoding="utf-8")
            tail = _read_log_tail(log_file, max_lines=2)
            self.assertIn("RuntimeError: boom", tail)

    def test_command_history_pruning_preserves_active_entries(self):
        from simu.service_parts import controls as controls_mod
        from simu.service_parts.controls import _ControlsMixin

        class _DummyCtrl(_ControlsMixin):
            def __init__(self):
                self.clock = type("C", (), {"absolute_minute": 100.0})()
                self.command_history = []
                self._strategy_generation_entries = {}
                self._strategy_generation_index_token = None

            def _command_entry_is_active(self, entry, minute):
                return bool(entry.get("active"))

        ctrl = _DummyCtrl()
        with patch.object(controls_mod, "COMMAND_HISTORY_MEMORY_LIMIT", 205):
            # 构造 5 条最早的活跃指令 + 210 条过期指令
            for i in range(5):
                ctrl.command_history.append({"id": f"active-{i}", "active": True})
            for i in range(210):
                ctrl.command_history.append({"id": f"old-{i}", "active": False})
            ctrl._prune_command_history_locked()
        ids = [e["id"] for e in ctrl.command_history]
        self.assertLessEqual(len(ids), 205)
        for i in range(5):
            self.assertIn(f"active-{i}", ids, "裁剪历史不应丢弃仍生效的控制指令")
        self.assertIn("old-209", ids, "裁剪历史应保留最新的历史记录")

    def test_http_snapshot_and_measurements_frame_cache(self):
        import gzip
        import io
        import json
        from simu.http_routes import make_http_server

        class _FakeSock:
            def __init__(self, req: bytes):
                self._r = io.BytesIO(req)
                self._w = io.BytesIO()
            def makefile(self, mode, bufsize=-1):
                return self._r if "r" in mode else self._w
            def sendall(self, data):
                self._w.write(data)
            def close(self):
                pass
            @property
            def raw(self):
                return self._w.getvalue()

        settings = json.loads((APP_ROOT / "startup.json").read_text(encoding="utf-8"))
        data_dir = (APP_ROOT / settings.get("data_dir", "data")).resolve()
        models_dir = data_dir / "models"
        candidates = sorted(p.parent for p in models_dir.glob("*/model.e"))
        if not candidates:
            self.skipTest("no model.e available in data_dir")
        model_dir = models_dir / "秦岭站" if (models_dir / "秦岭站" / "model.e").is_file() else candidates[0]

        with tempfile.TemporaryDirectory() as td:
            svc = service.PolarMicrogridSimulator(
                sim_dir=model_dir,
                runtime_dir=Path(td) / "rt",
                model_id=model_dir.name,
                model_name=model_dir.name,
                noise_std=0.0,
            )
            with contextlib.redirect_stdout(io.StringIO()):
                svc.step()
            srv = make_http_server(("127.0.0.1", 0), svc, role="simulator")
            try:
                Handler = srv.RequestHandlerClass
                req = b"GET /api/snapshot HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept-Encoding: gzip\r\n\r\n"
                s1 = _FakeSock(req)
                Handler(s1, ("127.0.0.1", 55101), srv)
                head1, _, body1 = s1.raw.partition(b"\r\n\r\n")
                self.assertIn(b"200 OK", head1)
                payload1 = json.loads(gzip.decompress(body1).decode("utf-8"))
                self.assertEqual(payload1["model"]["id"], model_dir.name)
                # 第二次命中缓存，不再调用 target.snapshot()
                with patch.object(svc, "snapshot", side_effect=AssertionError("should hit frame cache")):
                    s2 = _FakeSock(req)
                    Handler(s2, ("127.0.0.1", 55102), srv)
                    head2, _, body2 = s2.raw.partition(b"\r\n\r\n")
                    self.assertIn(b"200 OK", head2)
                    self.assertEqual(body1, body2)
            finally:
                srv.server_close()

    def test_scada104_compact_array_delta_updates_points_across_rounds(self):
        """验证 IEC104 桥接器对 measurement-arrays-v1 紧凑数组增量与无变化帧(frame=False)的精确解析。"""
        import scada104 as scada104_mod

        bridge = scada104_mod.Bridge.__new__(scada104_mod.Bridge)
        bridge._delta_sync_state = {}

        responses = [
            # 第 1 轮全量建基线：/api/measurements?trainee_view=1
            {
                "definitions": [
                    {"name": "M1", "meas_type": "P"},
                    {"name": "M2", "meas_type": "RUN_STAT"},
                ],
                "scada": [
                    {"name": "M1", "value": 12.5, "valid": 1},
                    {"name": "M2", "value": 1.0, "valid": 1},
                ],
            },
            # 第 1 轮全量建基线：/api/controls
            {"remote_controls": [{"name": "YK1"}], "remote_adjustments": [{"name": "YT1"}]},
            # 第 1 轮建立 delta 基线：/api/measurements/delta?after_seq=0&compact=1&trainee_view=1
            {"seq": 10, "definition_signature": "sig-v1", "count": 2},
            # 第 2 轮增量无变化帧（encoding="measurement-arrays-v1", frame=False）
            {"seq": 10, "definition_signature": "sig-v1", "encoding": "measurement-arrays-v1", "frame": False},
            # 第 3 轮增量紧凑数组帧（encoding="measurement-arrays-v1", frame=True）
            {
                "seq": 11,
                "definition_signature": "sig-v1",
                "encoding": "measurement-arrays-v1",
                "frame": True,
                "scada_values": [88.25, 0.0],
                "valid_values": [1, 0],
            },
        ]

        def _fake_pool_request(base, path, payload=None, timeout=None):
            return responses.pop(0)

        with patch.object(scada104_mod._HTTP_POOL, "request_json", side_effect=_fake_pool_request):
            points1, changed1 = bridge._read_points_for_model("http://127.0.0.1:18716", "m1")
            self.assertTrue(changed1)
            self.assertAlmostEqual(points1["yc"]["M1"]["value"], 12.5)
            self.assertEqual(points1["yx"]["M2"]["valid"], 1)

            points2, changed2 = bridge._read_points_for_model("http://127.0.0.1:18716", "m1")
            self.assertFalse(changed2, "frame=False 无变化帧必须跳过下游全表同步")
            self.assertAlmostEqual(points2["yc"]["M1"]["value"], 12.5)

            points3, changed3 = bridge._read_points_for_model("http://127.0.0.1:18716", "m1")
            self.assertTrue(changed3, "measurement-arrays-v1 增量帧必须触发点值更新")
            self.assertAlmostEqual(points3["yc"]["M1"]["value"], 88.25)
            self.assertEqual(points3["yc"]["M1"]["valid"], 1)
            self.assertAlmostEqual(points3["yx"]["M2"]["value"], 0.0)
            self.assertEqual(points3["yx"]["M2"]["valid"], 0)
            self.assertEqual(len(responses), 0)

    def test_command_mutation_seq_invalidates_cache_when_length_unchanged(self):
        """验证控制历史满容量裁剪或原位删除有效指令时 _command_mutation_seq 仍递增，不会返回陈旧快照。"""
        from simu.service_parts import controls as controls_mod
        from simu.service_parts.controls import _ControlsMixin

        class _DummyCtrl(_ControlsMixin):
            def __init__(self):
                self.clock = type("C", (), {"absolute_minute": 100.0})()
                self.command_history = []
                self._strategy_generation_entries = {}
                self._strategy_generation_index_token = None
                self._command_mutation_seq = 0
                self._command_signature_cache = ("stale", "sig")
                self._device_runtime_supplement_cache = ("stale", {"x": 1})

            def _command_entry_is_active(self, entry, minute):
                return bool(entry.get("active"))

        ctrl = _DummyCtrl()
        with (
            patch.object(controls_mod, "COMMAND_HISTORY_RECENT_LIMIT", 5),
            patch.object(controls_mod, "COMMAND_HISTORY_MEMORY_LIMIT", 5),
        ):
            for i in range(5):
                ctrl._append_command_history_entry({"id": f"c-{i}", "active": False})
            seq_before = ctrl._command_mutation_seq
            self.assertEqual(len(ctrl.command_history), 5)
            # 再追加 1 条触发裁剪，长度维持 5 但 seq 必须递增且清理缓存
            ctrl._command_signature_cache = ("k", "v")
            ctrl._append_command_history_entry({"id": "c-5", "active": True})
            self.assertEqual(len(ctrl.command_history), 5)
            self.assertGreater(ctrl._command_mutation_seq, seq_before)
            self.assertIsNone(ctrl._command_signature_cache)

    def test_scada104_reads_external_controls_names_endpoint(self):
        """验证 IEC104 桥接器调用真实的 /api/external/controls/names 并解析 yk_names/yt_names。"""
        import scada104 as scada104_mod

        bridge = scada104_mod.Bridge.__new__(scada104_mod.Bridge)
        bridge._delta_sync_state = {}
        seen_paths: list[str] = []

        def _fake_pool_request(base, path, payload=None, timeout=None):
            seen_paths.append(path)
            if path.startswith("/api/measurements?"):
                return {
                    "definitions": [{"name": "M1", "meas_type": "P"}],
                    "scada": [{"name": "M1", "value": 5.0, "valid": 1}],
                }
            if path == "/api/external/controls/names":
                return {
                    "yk_names": ["ACBreak.CB1.status"],
                    "yt_names": ["ACGenerator.G1.p_set"],
                }
            if path.startswith("/api/measurements/delta"):
                return {"seq": 1, "definition_signature": "sig", "count": 1}
            raise AssertionError(f"unexpected path: {path}")

        with patch.object(scada104_mod._HTTP_POOL, "request_json", side_effect=_fake_pool_request):
            points, changed = bridge._read_points_for_model("http://127.0.0.1:18716", "m1")
            self.assertTrue(changed)
            self.assertIn("/api/external/controls/names", seen_paths)
            self.assertNotIn("/api/controls", seen_paths)
            self.assertIn("ACBreak.CB1.status", points["yk"])
            self.assertIn("ACGenerator.G1.p_set", points["yt"])

    def test_http_routes_use_no_cache_for_etag_and_clear_service_caches_on_post(self):
        """验证 HTTP 路由带 ETag 响应下发 Cache-Control: no-cache 并在 POST 后清理服务层缓存。"""
        from pathlib import Path
        from simu import http_routes

        routes_path = Path(http_routes.__file__).resolve()
        text = routes_path.read_text(encoding="utf-8")
        self.assertIn('cache_control="no-cache"', text)
        self.assertIn("iter_services", text)
        self.assertIn("_command_signature_cache", text)
        self.assertIn("_device_runtime_supplement_cache", text)

    def test_scada104_strict_point_sync_keeps_rtu_channel_unchanged(self):
        """验证模型四遥定义变更时：RTU 与通道定义保持不变，仅严格增删改四遥点表。"""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "scdfe_s.db"
            fake_srv = _FakeScadaServer(db_path)
            bridge = scada104.Bridge(
                fake_srv,
                "http://127.0.0.1:18710",
                first_port=2405,
                interval=0.5,
            )
            with patch.object(scada104, "port_available", return_value=True):
                rtu = bridge.channel("qinling")
            # 模拟用户修改 RTU 名称与通道端口，后续四遥变更不得覆写 RTU 与通道
            with fake_srv.store.connection() as db, db:
                db.execute("UPDATE fes_rtu_define SET name='自定义秦岭站' WHERE rtu_id=?", (rtu,))
                db.execute("UPDATE fes_channel_iec104_define SET name='自定义通道', remote_port=2499 WHERE channel_id=?", (rtu,))

            initial_points = {
                "yc": {
                    "ACLoad.a.p": {"value": 10.0, "valid": 1},
                    "ACLoad.b.p": {"value": 20.0, "valid": 1},
                },
                "yx": {"DCBreak.1.status": {"value": 1, "valid": 1}},
                "yk": {"DCBreak.1.status": None, "DCBreak.2.status": None},
                "yt": {"ACLoad.a.p_set": None},
            }
            self.assertTrue(bridge.sync_points(rtu, initial_points))
            # 模拟操作员手工修改保留测点的展示名
            with fake_srv.store.connection() as db, db:
                a_pnt_no = db.execute(
                    "SELECT pnt_no FROM fes_yc_define WHERE rtu_id=? AND name='ACLoad.a.p'",
                    (rtu,),
                ).fetchone()[0]
                db.execute(
                    "UPDATE fes_yc_define SET name='人工命名-负荷A' WHERE rtu_id=? AND pnt_no=?",
                    (rtu, a_pnt_no),
                )

            # 第二次同步：移除 ACLoad.b.p 与 DCBreak.2.status，新增 ACLoad.c.p 与 ACLoad.c.p_set
            updated_points = {
                "yc": {
                    "ACLoad.a.p": {"value": 12.5, "valid": 1},
                    "ACLoad.c.p": {"value": 33.0, "valid": 1},
                },
                "yx": {"DCBreak.1.status": {"value": 0, "valid": 1}},
                "yk": {"DCBreak.1.status": None},
                "yt": {"ACLoad.a.p_set": None, "ACLoad.c.p_set": None},
            }
            self.assertTrue(bridge.sync_points(rtu, updated_points))

            # 1) RTU 与通道定义完全不变且仍只有 1 个 RTU 与 1 个通道
            with fake_srv.store.connection() as db:
                rtus = db.execute("SELECT rtu_id, channel_id, name FROM fes_rtu_define").fetchall()
                chs = db.execute("SELECT channel_id, name, remote_port FROM fes_channel_iec104_define").fetchall()
                yc_rows = db.execute("SELECT pnt_no, name, value FROM fes_yc_define WHERE rtu_id=? ORDER BY pnt_no", (rtu,)).fetchall()
                yk_rows = db.execute("SELECT name FROM fes_yk_define WHERE rtu_id=? ORDER BY pnt_no", (rtu,)).fetchall()
                yt_rows = db.execute("SELECT name FROM fes_yt_define WHERE rtu_id=? ORDER BY pnt_no", (rtu,)).fetchall()
            self.assertEqual(rtus, [(rtu, rtu, "自定义秦岭站")])
            self.assertEqual(chs, [(rtu, "自定义通道", 2499)])
            # 2) 四遥点表严格同步：保留点 A 原点号与人工名，旧点 B 与 DCBreak.2 被彻底删除，新点 C 已添加
            self.assertEqual(len(yc_rows), 2)
            self.assertEqual(yc_rows[0], (a_pnt_no, "人工命名-负荷A", 12.5))
            self.assertEqual(yc_rows[1][1], "ACLoad.c.p")
            self.assertEqual(yc_rows[1][2], 33.0)
            self.assertEqual(yk_rows, [("DCBreak.1.status",)])
            self.assertEqual(yt_rows, [("ACLoad.a.p_set",), ("ACLoad.c.p_set",)])

    def test_scada104_model_filter_isolates_single_rtu_and_channel(self):
        """验证按模型过滤 status 与 service_overview 时，严格仅返回当前模型对应的 1 个 RTU 和 1 个通道。"""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "scdfe_s.db"
            fake_srv = _FakeScadaServer(db_path)
            bridge = scada104.Bridge(
                fake_srv,
                "http://127.0.0.1:18710",
                first_port=2405,
                interval=0.5,
            )
            with patch.object(scada104, "port_available", return_value=True):
                rtu_a = bridge.channel("ModelA")
                rtu_b = bridge.channel("ModelB")
            self.assertNotEqual(rtu_a, rtu_b)
            bridge.models[rtu_a] = {"model": "ModelA", "rtu_id": rtu_a, "online": True, "running": True}
            bridge.models[rtu_b] = {"model": "ModelB", "rtu_id": rtu_b, "online": True, "running": False}

            # 1) status(model=...) 仅返回目标模型
            st_a = bridge.status(model="ModelA")
            self.assertEqual([m["model"] for m in st_a["models"]], ["ModelA"])
            self.assertEqual(st_a["bound_rtu_id"], rtu_a)
            st_b = bridge.status(model="ModelB")
            self.assertEqual([m["model"] for m in st_b["models"]], ["ModelB"])
            self.assertEqual(st_b["bound_rtu_id"], rtu_b)
            st_none = bridge.status(model="UnboundModel")
            self.assertEqual(st_none["models"], [])
            self.assertIsNone(st_none["bound_rtu_id"])

            # 2) EmbeddedScada104Host.service_overview(model=...) 严格隔离 services/rtus/channels
            host = object.__new__(scada104.EmbeddedScada104Host)
            host.store = fake_srv.store
            host.bridge = bridge
            host.db_path = db_path
            host.bridge_db_path = bridge.bridge_db_path
            host._closed = False
            host._started_at_ms = 123456
            host._first_iec104_port = 2405
            host._interval = 0.5
            host._worker = type("_W", (), {"is_alive": staticmethod(lambda: True)})()
            host.channel_services = fake_srv.channel_services

            ov_a = host.service_overview(model="ModelA")
            self.assertEqual(ov_a["rtu_id"], rtu_a)
            self.assertEqual(ov_a["channel_id"], rtu_a)
            self.assertEqual([s["rtu_id"] for s in ov_a["services"]], [rtu_a])
            self.assertEqual([r["rtu_id"] for r in ov_a["rtus"]], [rtu_a])
            self.assertEqual([c["channel_id"] for c in ov_a["channels"]], [rtu_a])

            ov_b = host.service_overview(model="ModelB")
            self.assertEqual(ov_b["rtu_id"], rtu_b)
            self.assertEqual(ov_b["channel_id"], rtu_b)
            self.assertEqual([s["rtu_id"] for s in ov_b["services"]], [rtu_b])
            self.assertEqual([r["rtu_id"] for r in ov_b["rtus"]], [rtu_b])
            self.assertEqual([c["channel_id"] for c in ov_b["channels"]], [rtu_b])

            ov_unbound = host.service_overview(model="UnboundModel")
            self.assertIsNone(ov_unbound["rtu_id"])
            self.assertEqual(ov_unbound["services"], [])
            self.assertEqual(ov_unbound["rtus"], [])
            self.assertEqual(ov_unbound["channels"], [])


if __name__ == "__main__":
    unittest.main()
