"""Web console and real-time API for the standalone digital twin."""

from __future__ import annotations

import argparse
import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse

from digital_twin import DigitalTwin
from iec104_bridge import ScdfeIEC104Bridge
from model_import import load_boundary_bytes, load_model_bytes, sanitize_svg
from scdfe_points import ScdfePointTableManager


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"


class SimulatorApplication:
    def __init__(self, args: argparse.Namespace) -> None:
        self.twin = DigitalTwin(seed=args.seed, step_seconds=args.step_seconds)
        self.point_tables = ScdfePointTableManager(scada_root=args.scada_root, db_path=args.scada_db)
        self.bridge = None
        self._stop = threading.Event()
        if not args.no_iec104:
            try:
                self.bridge = ScdfeIEC104Bridge(
                    self.twin,
                    scada_root=args.scada_root,
                    bind_ip=args.iec104_bind,
                    port=args.iec104_port,
                    common_address=args.common_address,
                    rtu_id=args.rtu_id,
                )
                self.bridge.start()
            except Exception as exc:
                print(f"IEC104 未启动: {exc}", flush=True)
                self.bridge = None
        self.worker = threading.Thread(target=self._loop, name="digital-twin-loop", daemon=True)
        self.worker.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            changed = self.twin.run_cycle()
            if changed and self.bridge is not None:
                try:
                    self.bridge.publish(self.twin.snapshot(history_limit=1))
                except Exception as exc:
                    print(f"IEC104 发布失败: {exc}", flush=True)
            self._stop.wait(0.05)

    def close(self) -> None:
        self._stop.set()
        self.worker.join(timeout=2)
        if self.bridge is not None:
            self.bridge.stop()


class Handler(BaseHTTPRequestHandler):
    server_version = "TraineeDigitalTwin/1.0"

    @property
    def app(self) -> SimulatorApplication:
        return self.server.app  # type: ignore[attr-defined]

    def _send(self, status: int, payload: object, content_type: str = "application/json; charset=utf-8") -> None:
        data = payload if isinstance(payload, bytes) else (
            json.dumps(payload, ensure_ascii=False).encode("utf-8") if content_type.startswith("application/json") else str(payload).encode("utf-8")
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 45 * 1024 * 1024:
            raise ValueError("请求不能超过 45 MB")
        if length <= 0:
            return {}
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body 必须是对象")
        return value

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/health":
                return self._send(200, {"status": "ok", "service": "environment-aware-digital-twin", "model": self.app.twin.model_summary(), "iec104": self.app.bridge.status() if self.app.bridge else {"available": False}})
            if path == "/api/overview":
                snapshot = self.app.twin.snapshot(history_limit=120)
                return self._send(200, {
                    "snapshot": snapshot,
                    "health": {"status": "ok", "service": "environment-aware-digital-twin", "model": snapshot["model"], "iec104": self.app.bridge.status() if self.app.bridge else {"available": False}},
                })
            if path == "/api/snapshot":
                limit = int(parse_qs(parsed.query).get("history", [120])[0])
                return self._send(200, self.app.twin.snapshot(history_limit=limit))
            if path == "/api/scada/telemetry":
                snapshot = self.app.twin.snapshot(history_limit=1)
                point_values = snapshot["point_values"]
                return self._send(200, {
                    "sequence": snapshot["sequence"],
                    "sim_time": snapshot["clock"]["sim_time"],
                    "yc": point_values["yc"],
                    "yx": point_values["yx"],
                    "named": snapshot["measurements"],
                    "iec104": self.app.bridge.status() if self.app.bridge else {"available": False},
                })
            if path == "/api/history":
                limit = int(parse_qs(parsed.query).get("limit", [120])[0])
                return self._send(200, {"items": self.app.twin.history(limit)})
            if path == "/api/events":
                limit = int(parse_qs(parsed.query).get("limit", [50])[0])
                return self._send(200, {"items": self.app.twin.events(limit)})
            if path == "/api/points":
                return self._send(200, {"items": self.app.twin.points()})
            if path == "/api/model":
                return self._send(200, self.app.twin.model_summary())
            if path == "/api/model/detail":
                snapshot = self.app.twin.snapshot(history_limit=1)
                return self._send(200, {"model": snapshot["model"], "devices": snapshot["devices"], "topology": snapshot["topology"], "curves": self.app.twin.curves})
            if path == "/api/devices":
                return self._send(200, {"items": self.app.twin.snapshot(history_limit=1)["devices"]})
            if path == "/api/topology":
                return self._send(200, self.app.twin.snapshot(history_limit=1)["topology"])
            if path == "/api/curves":
                return self._send(200, {"curves": self.app.twin.curves})
            if path == "/api/diagram":
                return self._send(200, self.app.twin.diagram())
            if path == "/api/power-flow":
                return self._send(200, self.app.twin.snapshot(history_limit=1)["power_flow"])
            if path == "/api/scdfe/points":
                return self._send(200, self.app.point_tables.summary())
            if path == "/api/iec104/status":
                return self._send(200, self.app.bridge.status() if self.app.bridge else {"available": False, "running": False, "last_error": "桥接未启用"})
            if path == "/" or path == "/index.html":
                return self._static("index.html", "text/html; charset=utf-8")
            if path.endswith(".html") and path.count("/") == 1:
                return self._static(path[1:], "text/html; charset=utf-8")
            if path in {"/app.js", "/styles.css", "/diagram.js", "/diagram.css", "/boundary.js"}:
                return self._static(path[1:], "application/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8")
            return self._send(404, {"error": "not_found"})
        except Exception as exc:
            return self._send(400, {"error": str(exc)})

    def _static(self, name: str, content_type: str):
        target = (WEB / name).resolve()
        if WEB.resolve() not in target.parents:
            return self._send(404, {"error": "not_found"})
        try:
            return self._send(200, target.read_bytes(), content_type)
        except FileNotFoundError:
            return self._send(404, {"error": "not_found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            body = self._json_body()
            if parsed.path == "/api/clock":
                return self._send(200, {"clock": self.app.twin.command_clock(body.get("action"), body.get("value"))})
            if parsed.path == "/api/model/import":
                source_name = str(body.get("filename") or "model.json")
                encoded = body.get("data_base64")
                if encoded:
                    data = base64.b64decode(str(encoded), validate=True)
                elif isinstance(body.get("model"), dict):
                    data = json.dumps(body["model"], ensure_ascii=False).encode("utf-8")
                else:
                    raise ValueError("需要 data_base64 或 model 对象")
                model = load_model_bytes(data, source_name=source_name)
                summary = self.app.twin.load_model(model)
                if self.app.bridge is not None:
                    self.app.bridge.rebuild()
                return self._send(200, {"model": summary, "points": len(self.app.twin.points()), "message": "模型已导入并已刷新运行点表"})
            if parsed.path == "/api/scdfe/points/generate":
                result = self.app.point_tables.generate(self.app.twin.points(), model_name=self.app.twin.model.get("name", "digital-twin"), rtu_id=int(body.get("rtu_id", 104)), channel_id=int(body.get("channel_id", body.get("rtu_id", 104))), replace=bool(body.get("replace", True)))
                if self.app.bridge is not None:
                    self.app.bridge.rebuild()
                return self._send(200, result)
            if parsed.path == "/api/curves":
                curves = self.app.twin.set_curves(body)
                if self.app.bridge is not None:
                    self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
                return self._send(200, {"curves": curves})
            if parsed.path == "/api/boundary/import":
                source_name = str(body.get("filename") or "boundary.csv")
                encoded = body.get("data_base64")
                if not encoded:
                    raise ValueError("需要 data_base64")
                boundary = load_boundary_bytes(base64.b64decode(str(encoded), validate=True), source_name=source_name)
                curves = self.app.twin.merge_curves(boundary["curves"], source=boundary["source"])
                if self.app.bridge is not None:
                    self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
                return self._send(200, {**boundary, "curves": curves, "message": "外部边界数据已加载"})
            if parsed.path == "/api/diagram/import":
                source_name = str(body.get("filename") or "diagram.svg")
                encoded = body.get("data_base64")
                if not encoded:
                    raise ValueError("需要 data_base64")
                diagram = sanitize_svg(base64.b64decode(str(encoded), validate=True), source_name=source_name)
                return self._send(200, {"diagram": self.app.twin.set_diagram(diagram, source="web"), "message": "SVG 电网图形已加载"})
            if parsed.path == "/api/devices/state":
                result = self.app.twin.set_device_state(str(body.get("device_id")), body.get("running"), source="web")
                if self.app.bridge is not None:
                    self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
                return self._send(200, result)
            if parsed.path == "/api/devices/operate":
                result = self.app.twin.operate_device(body.get("device_id"), body.get("action"), value=body.get("value"), model_revision=body.get("model_revision"))
                if self.app.bridge is not None:
                    self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
                return self._send(200, result)
            if parsed.path == "/api/devices/actions":
                result = self.app.twin.apply_device_actions(body.get("actions"), model_revision=body.get("model_revision"), source="web")
                if self.app.bridge is not None:
                    self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
                return self._send(200, result)
            if parsed.path == "/api/devices/states":
                result = self.app.twin.set_devices_state(body.get("states"), source="web")
                if self.app.bridge is not None:
                    self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
                return self._send(200, result)
            if parsed.path == "/api/scenario":
                result = self.app.twin.apply_scenario(body.get("name"), source=str(body.get("source", "web")))
                if self.app.bridge is not None:
                    self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
                return self._send(200, result)
            if parsed.path == "/api/topology":
                result = self.app.twin.set_topology(body)
                if self.app.bridge is not None:
                    self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
                return self._send(200, result)
            if parsed.path == "/api/commands":
                result = self.app.twin.apply_command(body.get("kind"), int(body.get("point_no")), body.get("value"), selected=bool(body.get("selected")))
                if self.app.bridge is not None:
                    self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
                return self._send(200, result)
            if parsed.path == "/api/iec104/start":
                if self.app.bridge is None:
                    raise RuntimeError("IEC104 桥接未加载，请检查 scada_root")
                return self._send(200, self.app.bridge.start())
            if parsed.path == "/api/iec104/stop":
                if self.app.bridge is None:
                    raise RuntimeError("IEC104 桥接未加载")
                return self._send(200, self.app.bridge.stop())
            return self._send(404, {"error": "not_found"})
        except Exception as exc:
            return self._send(400, {"error": str(exc)})

    def log_message(self, format, *args):
        return


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Environment-aware power-system digital twin")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780, help="Web API port")
    parser.add_argument("--scada-root", default=r"D:\codex\scada")
    parser.add_argument("--scada-db", default=None, help="scdfe_s SQLite path; defaults to D:/codex/scada/db/scdfe_s.sqlite3")
    parser.add_argument("--iec104-bind", default="127.0.0.1")
    parser.add_argument("--iec104-port", type=int, default=2404)
    parser.add_argument("--common-address", type=int, default=1)
    parser.add_argument("--rtu-id", type=int, default=104)
    parser.add_argument("--seed", type=int, default=104)
    parser.add_argument("--step-seconds", type=float, default=1.0)
    parser.add_argument("--no-iec104", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    app = SimulatorApplication(args)
    server = AppServer((args.host, args.port), Handler)
    server.app = app  # type: ignore[attr-defined]
    print(f"digital twin web: http://{args.host}:{args.port}/", flush=True)
    print(f"IEC104: {'enabled' if app.bridge else 'unavailable'} {args.iec104_bind}:{args.iec104_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        app.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

