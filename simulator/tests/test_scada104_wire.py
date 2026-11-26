"""Loopback acceptance of the real scdfe_s IEC104 service and its simulator bridge."""

from contextlib import ExitStack, closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


APP = Path(__file__).resolve().parents[1]
SCADA = Path(os.environ.get("FES_ROOT") or os.environ.get("SCADA_ROOT") or r"D:\codex\fes").resolve()
HOST = "127.0.0.1"
POWER = "ACLoad.test.p"
SWITCH = "DCBreak.test.status"
SETPOINT = "ACLoad.test.p_set"
ADDED = "ACLoad.test.q"


def free_port():
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def web(base, path, *, method="GET", body=None):
    request = Request(
        base + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=4) as response:
        return json.load(response)


class Model:
    def __init__(self, model_id):
        self.model_id = model_id
        self.lock = threading.Lock()
        self.power = 123.25
        self.switch = True
        self.expanded = False
        self.commands = []

    def measurements(self):
        rows = [
            {"name": POWER, "meas_type": "P", "value": self.power, "valid": 1},
            {"name": SWITCH, "meas_type": "STATUS", "value": int(self.switch), "valid": 1},
        ]
        if self.expanded:
            rows.append({"name": ADDED, "meas_type": "Q", "value": 7.5, "valid": 1})
        stamp = time.time()
        return {"model_id": self.model_id, "definitions": rows, "scada": rows,
                "measurement_clock": {"updated_at": stamp, "step_count": int(stamp)}}

    def execute(self, body):
        accepted = {"remote_adjustments": 0, "remote_controls": 0, "ignored": 0}
        reply = {"model_id": self.model_id, "accepted": accepted}
        for kind, name, key, attribute in (
            ("yk", SWITCH, "remote_controls", "switch"),
            ("yt", SETPOINT, "remote_adjustments", "power"),
        ):
            results = []
            for requested_name, value in zip(body.get(kind + "_names", ()), body.get(kind + "_values", ())):
                self.commands.append((kind, requested_name, value))
                accepted_command = requested_name == name and (kind, value) != ("yt", 99.5)
                accepted[key if accepted_command else "ignored"] += 1
                if accepted_command:
                    setattr(self, attribute, bool(value) if kind == "yk" else value)
                results.append({"name": requested_name, "requested_value": value,
                                "value": getattr(self, attribute), "accepted": accepted_command,
                                "active": accepted_command, "found": requested_name == name,
                                "reason": "" if accepted_command else "fixture rejected command"})
            reply[kind + "_results"] = results
        return reply


@contextmanager
def fixture_server(route):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def dispatch(self):
            body = None
            if self.command == "POST":
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            result = route(urlsplit(self.path).path, body)
            if result is None:
                self.send_error(404)
                return
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = dispatch
        do_POST = dispatch

    with ThreadingHTTPServer((HOST, 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://{HOST}:{server.server_port}"
        finally:
            server.shutdown()
            worker.join(timeout=2)


def model_route(model):
    def route(path, body):
        with model.lock:
            if path == "/api/measurements":
                return model.measurements()
            if path == "/api/external/controls/names":
                return {"model_id": model.model_id, "yk_names": [SWITCH], "yt_names": [SETPOINT]}
            if path == "/api/external/controls/execute":
                return model.execute(body)
            if path == "/api/health":
                return {"ok": True, "model_id": model.model_id}
            return None
    return route


@contextmanager
def bridge_process(root, catalog, web_port):
    logfile = root / "bridge.log"
    with logfile.open("wb") as output:
        process = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-u", str(APP / "scada104.py"),
             "--scada-root", str(SCADA), "--db", str(root / "scdfe_s.db"),
             "--simulator-url", catalog, "--web-port", str(web_port),
             "--first-iec104-port", str(free_port())],
            cwd=root, stdout=output, stderr=subprocess.STDOUT,
        )
        try:
            yield process, logfile
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


@unittest.skipUnless((SCADA / "scdfe_s" / "web" / "server.py").is_file(), "scdfe_s checkout required")
class Scada104WireTest(unittest.TestCase):
    def test_measurements_commands_and_model_point_reconciliation(self):
        with ExitStack() as resources:
            root = Path(resources.enter_context(tempfile.TemporaryDirectory(prefix="simulator-104-test-")))
            source = Model("wire-fixture")
            source_url = resources.enter_context(fixture_server(model_route(source)))
            secondary = Model("second-wire-fixture")
            secondary_url = resources.enter_context(fixture_server(model_route(secondary)))
            registered = [(source.model_id, source_url)]
            catalog = resources.enter_context(fixture_server(
                lambda path, _body: {"models": [{"id": model_id, "service": {"healthy": True, "base_url": url}}
                                                  for model_id, url in registered]} if path == "/api/models" else None
            ))
            web_port = free_port()
            web_url = f"http://{HOST}:{web_port}"
            process, logfile = resources.enter_context(bridge_process(root, catalog, web_port))
            database = root / "scdfe_s.db"

            def rows(query, *params):
                with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
                    return db.execute(query, params).fetchall()

            def point(rtu, kind, name):
                return rows("SELECT pnt_no FROM simulator104_points WHERE rtu_id=? AND kind=? AND source_name=? AND active=1",
                            rtu, kind, name)

            def station(name):
                return rows("SELECT m.rtu_id,c.remote_port FROM simulator104_models m JOIN fes_rtu_define r "
                            "ON r.rtu_id=m.rtu_id JOIN fes_channel_iec104_define c ON c.channel_id=r.channel_id "
                            "WHERE m.model=?", name)

            def port_ready(port):
                with socket.create_connection((HOST, port), timeout=.2):
                    return True

            def eventually(check, description, timeout=12):
                deadline = time.monotonic() + timeout
                last_error = None
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        result = check()
                        if result:
                            return result
                    except (OSError, sqlite3.OperationalError) as exc:
                        last_error = exc
                    time.sleep(.05)
                output = logfile.read_text(encoding="utf-8", errors="replace")[-5000:]
                self.fail(f"{description}; last error: {last_error}; bridge log:\n{output}")

            [(rtu, port)] = eventually(lambda: station(source.model_id), "channel was not created")
            eventually(lambda: port_ready(port), "channel is not listening")
            [(yc,)] = eventually(lambda: point(rtu, "yc", POWER), "YC binding missing")
            [(yx,)] = eventually(lambda: point(rtu, "yx", SWITCH), "YX binding missing")
            [(yk,)] = eventually(lambda: point(rtu, "yk", SWITCH), "YK binding missing")
            [(yt,)] = eventually(lambda: point(rtu, "yt", SETPOINT), "YT binding missing")

            resources.enter_context(patch.object(sys, "path", [str(SCADA), *sys.path]))
            from client.iec104 import IEC104Error, IEC104Master
            from scdfe_s.database import SimulatorStore

            store = SimulatorStore(database)
            resources.callback(store.close)
            client = IEC104Master.from_store(store, rtu, init="NONE", command_timeout_ms=3000)
            try:
                client.connect(timeout=5)
                self.assertTrue(client.general_interrogation())
                eventually(lambda: client.value("yc", yc).value == 123.25, "YC initial sample missing")
                eventually(lambda: client.value("yx", yx).value is True, "YX initial sample missing")
                self.assertIs(client.send_yk_point(yk, False).value, False)
                self.assertAlmostEqual(client.send_yt_point(yt, 44.5).value, 44.5)
                eventually(lambda: client.value("yx", yx).value is False, "YX spontaneous update missing")
                eventually(lambda: client.value("yc", yc).value == 44.5, "YC spontaneous update missing")
                with self.assertRaises(IEC104Error):
                    client.send_yt_point(yt, 99.5)
                with source.lock:
                    self.assertEqual(source.commands, [("yk", SWITCH, False), ("yt", SETPOINT, 44.5), ("yt", SETPOINT, 99.5)])
                self.assertEqual(rows("SELECT value FROM fes_yt_define WHERE rtu_id=? AND pnt_no=?", rtu, yt), [(44.5,)])
            finally:
                client.close()

            row_path = f"/api/rtus/{rtu}/points/yc/{yc}"
            edited = web(web_url, row_path, method="PATCH", body={"name": "operator-edited label"})["item"]
            self.assertEqual(edited["name"], "operator-edited label")
            with source.lock:
                source.expanded = True
            eventually(lambda: point(rtu, "yc", ADDED), "new definition did not generate a point")
            self.assertEqual(point(rtu, "yc", POWER), [(yc,)])
            self.assertEqual(web(web_url, row_path)["item"]["name"], "operator-edited label")

            registered.append((secondary.model_id, secondary_url))
            [(new_rtu, new_port)] = eventually(lambda: station(secondary.model_id), "second channel missing")
            self.assertNotEqual(rtu, new_rtu)
            self.assertNotEqual(port, new_port)
            eventually(lambda: port_ready(new_port), "second model channel is not listening")
            [(new_yk,)] = point(new_rtu, "yk", SWITCH)
            result = web(web_url, f"/api/rtus/{new_rtu}/commands/yk/{new_yk}",
                         method="POST", body={"value": 0})
            self.assertEqual(result["command_status"], "applied")
            with secondary.lock:
                self.assertEqual(secondary.commands, [("yk", SWITCH, False)])
            with source.lock:
                self.assertEqual(len(source.commands), 3)

            registered.remove((source.model_id, source_url))
            eventually(lambda: rows("SELECT status FROM fes_yc_define WHERE rtu_id=? AND pnt_no=?", rtu, yc) == [(128,)],
                       "offline model did not invalidate old telemetry")


if __name__ == "__main__":
    unittest.main()
