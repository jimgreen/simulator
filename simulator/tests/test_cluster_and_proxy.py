"""针对 SimulatorClusterManager 与 SimulatorProxy 的并发、安全、容错与原子性回归测试。"""

from __future__ import annotations

import concurrent.futures
import gzip
import io
import json
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
for _entry in (str(APP_ROOT), str(SHARED_ROOT)):
    if _entry in sys.path:
        sys.path.remove(_entry)
    sys.path.insert(0, _entry)

from simu.simulator_cluster import SimulatorClusterManager, _rotate_log_if_needed
from simu.simulator_proxy import make_simulator_proxy_server


class _FakeSocket:
    """内存伪造 Socket，支持无真实端口连接的 HTTP Handler 单元验证。"""

    def __init__(self, raw_request: bytes, *, abort_on_write: bool = False) -> None:
        self._r = io.BytesIO(raw_request)
        self._w = io.BytesIO()
        self._abort = abort_on_write

    def makefile(self, mode: str, bufsize: int = -1):
        if "r" in mode:
            return self._r
        if self._abort:
            class _AbortingWriter(io.BytesIO):
                def write(self, b):
                    raise ConnectionAbortedError(10053, "client aborted connection")
            return _AbortingWriter()
        return self._w

    def sendall(self, data: bytes) -> None:
        if self._abort:
            raise ConnectionAbortedError(10053, "client aborted connection")
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


class ClusterAndProxyTests(unittest.TestCase):
    def _make_models(self, root: Path, names=("m1", "m2", "m3")):
        models_root = root / "models"
        runtime_root = root / "runtime"
        for name in names:
            (models_root / name).mkdir(parents=True)
            (models_root / name / "model.e").write_text("dummy", encoding="utf-8")
        return models_root, runtime_root

    def test_catalog_concurrency_singleflight_and_cache(self):
        with tempfile.TemporaryDirectory() as td:
            models_root, runtime_root = self._make_models(Path(td))
            probe_calls = []

            def slow_health(host, port, model_id, timeout):
                probe_calls.append(model_id)
                if model_id == "m2":
                    time.sleep(0.25)
                return True, {
                    "ok": True,
                    "model_id": model_id,
                    "process": {"pid": 22222},
                    "snapshot": {"model": {"id": model_id}, "clock": {"state": "running"}},
                }, ""

            mgr = SimulatorClusterManager(
                sim_dir=APP_ROOT,
                models_root=models_root,
                runtime_root=runtime_root,
                health_checker=slow_health,
                port_checker=lambda h, p: False,
                health_cache_ttl_seconds=1.5,
            )
            with mgr.lock:
                for entry in mgr._registry["services"].values():
                    entry["pid"] = 22222

            # 冷启动 6 并发：Singleflight 应合并为每模型 1 次（总计 3 次）而非 18 次，总耗时接近单次慢探测
            t0 = time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(lambda _: mgr.catalog(), range(6)))
            cold_elapsed = time.perf_counter() - t0
            self.assertEqual(len(results), 6)
            self.assertEqual(len(probe_calls), 3)
            self.assertLess(cold_elapsed, 0.9)

            # 热缓存 6 并发：0 次探测且毫秒级返回
            probe_calls.clear()
            t1 = time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(lambda _: mgr.catalog(), range(6)))
            warm_elapsed = time.perf_counter() - t1
            self.assertEqual(len(probe_calls), 0)
            self.assertLess(warm_elapsed, 0.2)

    def test_stop_waits_for_adopted_process_exit_and_does_not_block_catalog(self):
        with tempfile.TemporaryDirectory() as td:
            models_root, runtime_root = self._make_models(Path(td), names=("m1", "m2"))
            m1_alive = [True]
            killed_pids = []

            def health(host, port, model_id, timeout):
                if model_id == "m1" and not m1_alive[0]:
                    return False, {}, "stopped"
                return True, {
                    "ok": True,
                    "model_id": model_id,
                    "process": {"pid": 33333 if model_id == "m1" else 44444},
                    "snapshot": {"model": {"id": model_id}, "clock": {"state": "stopped"}},
                }, ""

            def fake_terminate(pid: int) -> None:
                killed_pids.append(pid)
                def _delayed_exit():
                    time.sleep(0.25)
                    m1_alive[0] = False
                threading.Thread(target=_delayed_exit, daemon=True).start()

            mgr = SimulatorClusterManager(
                sim_dir=APP_ROOT,
                models_root=models_root,
                runtime_root=runtime_root,
                health_checker=health,
                port_checker=lambda h, p: False,
                poll_interval_seconds=0.05,
                shutdown_timeout_seconds=2.0,
                health_cache_ttl_seconds=1.5,
            )
            with mgr.lock:
                mgr._registry["services"]["m1"]["pid"] = 33333
                mgr._registry["services"]["m2"]["pid"] = 44444
            mgr.port_checker = lambda h, p: m1_alive[0] if p == 8711 else False
            mgr.catalog()

            catalog_latencies = []
            with patch.object(SimulatorClusterManager, "_terminate_pid", side_effect=fake_terminate):
                stop_thread = threading.Thread(target=mgr.stop, args=("m1",))
                stop_thread.start()
                time.sleep(0.05)
                s = time.perf_counter()
                mgr.model_info("m2")
                catalog_latencies.append(time.perf_counter() - s)
                stop_thread.join(timeout=3.0)

            self.assertEqual(killed_pids, [33333])
            self.assertFalse(m1_alive[0], "stop() 应等待已领养进程实际退出后再返回")
            self.assertLess(catalog_latencies[0], 0.15, "停止 m1 不应阻塞 m2 查询")

    def test_proxy_static_etag_gzip_disconnect_413_and_cors(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            models_root, runtime_root = self._make_models(root, names=("m1",))
            static_dir = root / "web"
            static_dir.mkdir()
            (static_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")
            (static_dir / "bundle.js").write_text("const x = 'hello world';\n" * 200, encoding="utf-8")

            mgr = SimulatorClusterManager(
                sim_dir=APP_ROOT,
                models_root=models_root,
                runtime_root=runtime_root,
                health_checker=lambda h, p, m, t: (False, {}, ""),
                port_checker=lambda h, p: False,
            )
            srv = make_simulator_proxy_server(("127.0.0.1", 0), mgr, static_root=static_dir)
            try:
                Handler = srv.RequestHandlerClass

                # 1. 静态资源 gzip + ETag
                sock = _FakeSocket(
                    b"GET /bundle.js HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    b"Accept-Encoding: gzip\r\nOrigin: http://127.0.0.1:18720\r\n\r\n"
                )
                Handler(sock, ("127.0.0.1", 50001), srv)
                status, headers, body = _parse_http_response(sock.raw_response)
                self.assertEqual(status, 200)
                self.assertEqual(headers.get("content-encoding"), "gzip")
                self.assertIn("etag", headers)
                self.assertEqual(headers.get("access-control-allow-origin"), "http://127.0.0.1:18720")
                self.assertIn("hello world", gzip.decompress(body).decode("utf-8"))

                # 2. If-None-Match 命中 304
                etag = headers["etag"]
                sock_304 = _FakeSocket(
                    f"GET /bundle.js HTTP/1.1\r\nHost: 127.0.0.1\r\nIf-None-Match: {etag}\r\n\r\n".encode("ascii")
                )
                Handler(sock_304, ("127.0.0.1", 50002), srv)
                status_304, _h304, body_304 = _parse_http_response(sock_304.raw_response)
                self.assertEqual(status_304, 304)
                self.assertEqual(body_304, b"")

                # 3. 第三方恶意 Origin 不应获得 CORS 放行头
                sock_evil = _FakeSocket(
                    b"GET /api/models HTTP/1.1\r\nHost: 127.0.0.1\r\nOrigin: https://evil.example.com\r\n\r\n"
                )
                Handler(sock_evil, ("127.0.0.1", 50003), srv)
                status_evil, headers_evil, _ = _parse_http_response(sock_evil.raw_response)
                self.assertEqual(status_evil, 200)
                self.assertNotIn("access-control-allow-origin", headers_evil)

                # 4. 超大 Content-Length 返回 413
                sock_413 = _FakeSocket(
                    b"POST /api/simulator-services/stop HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    b"Content-Type: application/json\r\nContent-Length: 999999999\r\n\r\n"
                )
                Handler(sock_413, ("127.0.0.1", 50004), srv)
                status_413, _h413, _b413 = _parse_http_response(sock_413.raw_response)
                self.assertEqual(status_413, 413)

                # 5. 客户端写响应中断连不抛出二次异常
                sock_abort = _FakeSocket(
                    b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
                    abort_on_write=True,
                )
                Handler(sock_abort, ("127.0.0.1", 50005), srv)
            finally:
                srv.server_close()

    def test_child_log_rotation(self):
        with tempfile.TemporaryDirectory() as td:
            log_file = Path(td) / "model.log"
            log_file.write_bytes(b"A" * 2048)
            _rotate_log_if_needed(log_file, max_bytes=1024, backup_count=2)
            self.assertFalse(log_file.exists())
            self.assertTrue((Path(td) / "model.log.1").exists())

    def test_proxy_hosts_simulator104_page_and_apis(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            models_root, runtime_root = self._make_models(root, names=("m1",))
            static_dir = root / "web"
            static_dir.mkdir()
            (static_dir / "index.html").write_text("<html>sim</html>", encoding="utf-8")
            (static_dir / "scada104.html").write_text("<html>iec104-ui</html>", encoding="utf-8")

            calls = []

            class _FakeIec104Host:
                available = True
                closed = False

                def status(self):
                    return {
                        "available": True,
                        "hosted_by": "simulator",
                        "database": "test.sqlite3",
                        "scada_web_url": "",
                        "models": [{"model": "m1", "rtu_id": 1, "online": True, "running": True}],
                        "errors": {},
                    }

                def list_points(self, rtu, kind):
                    return [{"pnt_no": 1, "name": "SW1", "source_name": "CB.1.status", "disabled": False, "value": 1, "status": 0}]

                def set_point_disabled(self, rtu, kind, pnt_no, disabled):
                    calls.append(("disable", rtu, kind, pnt_no, disabled))
                    return {"rtu_id": rtu, "kind": kind, "pnt_no": pnt_no, "disabled": disabled}

                def execute_command(self, rtu, kind, point_no, value):
                    calls.append(("cmd", rtu, kind, point_no, value))
                    return {"kind": kind, "pnt_no": point_no, "value": value, "applied_to_simulator": True}

                def control_channel(self, rtu, action):
                    calls.append(("channel", rtu, action))
                    return {"rtu_id": rtu, "action": action, "running": action != "stop"}

                def channel_logs(self, rtu, limit=120):
                    return [{"time": "2026-11-23T00:00:00", "level": "INFO", "message": "ready"}]

                def service_overview(self, rtu_id=None):
                    return {
                        "available": True,
                        "hosted_by": "simulator",
                        "host": {"pid": 12345, "running": True, "running_channels": 1, "total_channels": 1},
                        "services": [{"rtu_id": 1, "model": "M1", "bind_ip": "127.0.0.1", "port": 2405, "running": True}],
                        "rtus": [{"rtu_id": 1, "channel_id": 1, "name": "M1", "process_enable": 1}],
                        "channels": [{"channel_id": 1, "name": "M1", "remote_host": "127.0.0.1", "remote_port": 2405}],
                    }

                def list_point_definitions(self, rtu, kind):
                    return [{"pnt_no": 1, "name": "P1", "io_address": 16385, "io_address_hex": "0x4001", "type_id": 13, "type_name": "M_ME_NC_1"}]

                def control_service_process(self, action, *, rtu_id=None, scope="single"):
                    calls.append(("service_process", action, rtu_id, scope))
                    return {"scope": scope, "action": action, "results": [{"rtu_id": rtu_id or 1, "running": action != "stop"}]}

                def update_service_config(self, rtu, values, *, apply_restart=True):
                    calls.append(("service_config", rtu, values.get("port"), apply_restart))
                    return {"rtu_id": rtu, "config": values, "running": True, "restarted": apply_restart}

                def update_rtu_definition(self, rtu, values):
                    calls.append(("rtu_update", rtu, values.get("name")))
                    return {"rtu_id": rtu, "name": values.get("name")}

                def update_channel_definition(self, channel_id, values, *, apply_restart=True):
                    calls.append(("channel_def_update", channel_id, values.get("remote_port")))
                    return {"channel": {"channel_id": channel_id, "remote_port": values.get("remote_port")}, "restarted": apply_restart}

                def export_channel_efile(self, rtu):
                    calls.append(("export_efile", rtu))
                    return {
                        "filename": f"scdfe_s_rtu{rtu}_ch1_iec104_M1.e",
                        "content": "<! System=SCADA Version=1.0 Source=scdfe_s !>\n<fes_rtu_define::scada rtu_id = 1>\n@rtu_id\n#1\n</fes_rtu_define>\n",
                        "summary": {"rtu_id": rtu, "channel_id": 1, "channel_type": "iec104", "total_points": 4},
                    }

                def close(self):
                    self.closed = True

            fake_host = _FakeIec104Host()
            mgr = SimulatorClusterManager(
                sim_dir=APP_ROOT,
                models_root=models_root,
                runtime_root=runtime_root,
                health_checker=lambda h, p, m, t: (False, {}, ""),
                port_checker=lambda h, p: False,
            )
            srv = make_simulator_proxy_server(
                ("127.0.0.1", 0),
                mgr,
                static_root=static_dir,
                iec104_host=fake_host,
            )
            try:
                Handler = srv.RequestHandlerClass

                def _req(raw: bytes):
                    sock = _FakeSocket(raw)
                    Handler(sock, ("127.0.0.1", 50010), srv)
                    return _parse_http_response(sock.raw_response)

                s_page, _, b_page = _req(b"GET /simulator104 HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                self.assertEqual(s_page, 200)
                self.assertIn(b"iec104-ui", b_page)

                s_st, _, b_st = _req(b"GET /api/simulator104/status HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                self.assertEqual(s_st, 200)
                self.assertEqual(json.loads(b_st.decode("utf-8"))["hosted_by"], "simulator")

                s_pts, _, b_pts = _req(b"GET /api/simulator104/points?rtu_id=1&kind=yc HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                self.assertEqual(s_pts, 200)
                self.assertEqual(len(json.loads(b_pts.decode("utf-8"))["items"]), 1)

                s_logs, _, b_logs = _req(b"GET /api/simulator104/logs?rtu_id=1 HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                self.assertEqual(s_logs, 200)
                self.assertEqual(len(json.loads(b_logs.decode("utf-8"))["items"]), 1)

                cmd_body = json.dumps({"rtu_id": 1, "kind": "yk", "pnt_no": 1, "value": 1}).encode("utf-8")
                s_cmd, _, b_cmd = _req(
                    b"POST /api/simulator104/commands HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    b"Content-Type: application/json\r\n"
                    + f"Content-Length: {len(cmd_body)}\r\n\r\n".encode("ascii")
                    + cmd_body
                )
                self.assertEqual(s_cmd, 200)
                self.assertTrue(json.loads(b_cmd.decode("utf-8"))["item"]["applied_to_simulator"])

                ch_body = json.dumps({"rtu_id": 1, "action": "stop"}).encode("utf-8")
                s_ch, _, b_ch = _req(
                    b"POST /api/simulator104/channel HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    b"Content-Type: application/json\r\n"
                    + f"Content-Length: {len(ch_body)}\r\n\r\n".encode("ascii")
                    + ch_body
                )
                self.assertEqual(s_ch, 200)
                self.assertFalse(json.loads(b_ch.decode("utf-8"))["channel"]["running"])

                s_svc, _, b_svc = _req(b"GET /api/simulator104/service HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                self.assertEqual(s_svc, 200)
                self.assertEqual(json.loads(b_svc.decode("utf-8"))["host"]["pid"], 12345)

                s_pdef, _, b_pdef = _req(b"GET /api/simulator104/point-definitions?rtu_id=1&kind=yc HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                self.assertEqual(s_pdef, 200)
                self.assertEqual(json.loads(b_pdef.decode("utf-8"))["items"][0]["io_address"], 16385)

                s_exp, _, b_exp = _req(b"GET /api/simulator104/export-efile?rtu_id=1 HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                self.assertEqual(s_exp, 200)
                exp_payload = json.loads(b_exp.decode("utf-8"))
                self.assertEqual(exp_payload["filename"], "scdfe_s_rtu1_ch1_iec104_M1.e")
                self.assertIn("<! System=SCADA Version=1.0 Source=scdfe_s", exp_payload["content"])

                def _post_json(route: str, obj: dict):
                    raw = json.dumps(obj).encode("utf-8")
                    return _req(
                        f"POST {route} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\n\r\n".encode("ascii")
                        + raw
                    )

                self.assertEqual(_post_json("/api/simulator104/service/process", {"action": "restart", "rtu_id": 1, "scope": "single"})[0], 200)
                self.assertEqual(_post_json("/api/simulator104/service/config", {"rtu_id": 1, "config": {"bind_ip": "0.0.0.0", "port": 2406}})[0], 200)
                self.assertEqual(_post_json("/api/simulator104/rtu/update", {"rtu_id": 1, "name": "StationA", "process_enable": 1})[0], 200)
                self.assertEqual(_post_json("/api/simulator104/channel-define/update", {"channel_id": 1, "remote_port": 2406})[0], 200)
            finally:
                srv.server_close()
            self.assertTrue(fake_host.closed)
            self.assertIn(("cmd", 1, "yk", 1, 1), calls)
            self.assertIn(("channel", 1, "stop"), calls)
            self.assertIn(("service_process", "restart", 1, "single"), calls)
            self.assertIn(("service_config", 1, 2406, True), calls)
            self.assertIn(("rtu_update", 1, "StationA"), calls)
            self.assertIn(("channel_def_update", 1, 2406), calls)
            self.assertIn(("export_efile", 1), calls)


if __name__ == "__main__":
    unittest.main()
