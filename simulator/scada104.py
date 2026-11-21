"""Run an independent scdfe_s Web/IEC104 process backed by simulator models."""

import argparse
from ipaddress import ip_address
import json
import logging
import math
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from urllib.parse import urlencode, urlsplit


LOG = logging.getLogger("simulator.scada104")
KINDS = ("yc", "yx", "yk", "yt")
APP_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = (APP_ROOT / "../../workspace").resolve()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


LOCAL_HTTP = build_opener(ProxyHandler({}), NoRedirect())


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


def request(base, path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = Request(base + path, body, {"Content-Type": "application/json"})
    with LOCAL_HTTP.open(req, timeout=3) as response:
        return json.load(response)


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


class Bridge:
    def __init__(self, server, simulator_url, first_port, interval=1.0):
        self.server = server
        self.simulator_url = simulator_url
        self.first_port = first_port
        self.interval = interval
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.online = {}
        self.models = {}
        self.initialized = set()
        self.pending_reload = set()
        self.last_errors = {}
        with server.store.connection() as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS simulator104_models (
                model TEXT PRIMARY KEY, rtu_id INTEGER UNIQUE NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS simulator104_points (
                rtu_id INTEGER NOT NULL, kind TEXT NOT NULL, source_name TEXT NOT NULL,
                pnt_no INTEGER NOT NULL, active INTEGER NOT NULL,
                PRIMARY KEY (rtu_id, kind, source_name), UNIQUE (rtu_id, kind, pnt_no))""")

    def channel(self, model):
        store = self.server.store
        with store.connection() as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT rtu_id FROM simulator104_models WHERE model=?", (model,)).fetchone()
            if row:
                return int(row[0])
            used = {int(value) for value, in db.execute(
                "SELECT rtu_id FROM fes_rtu_define UNION SELECT channel_id FROM fes_rtu_define "
                "UNION SELECT channel_id FROM fes_channel_iec104_define "
                "UNION SELECT id FROM fes_channel_iec104_define "
                "UNION SELECT rtu_id FROM simulator104_models"
            ) if value is not None}
            ports = {int(port) for port, in db.execute(
                "SELECT remote_port FROM fes_channel_iec104_define WHERE remote_port IS NOT NULL")}
            rtu = next(number for number in range(1, 65535) if number not in used)
            port = next(number for number in range(self.first_port, 65536)
                        if number not in ports and port_available(number))
            db.execute("INSERT INTO fes_channel_iec104_define (id,name,channel_id,rtu_addr,remote_host,remote_port) "
                       "VALUES (?,?,?,?,'127.0.0.1',?)", (rtu, model, rtu, rtu, port))
            db.execute("INSERT INTO fes_rtu_define (rtu_id,channel_id,channel_type,name,process_enable) VALUES (?,?,'iec104',?,1)",
                       (rtu, rtu, model))
            db.execute("INSERT INTO simulator104_models VALUES (?,?)", (model, rtu))
        return rtu

    def sync_points(self, rtu, points):
        now = time.time_ns() // 1_000_000
        changed = False
        with self.server.store.connection() as db, db:
            db.execute("BEGIN IMMEDIATE")
            for kind, current in points.items():
                table = f"fes_{kind}_define"
                known = {name: (no, active) for name, no, active in db.execute(
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
                        db.execute("INSERT INTO simulator104_points VALUES (?,?,?,?,1)", (rtu, kind, name, number))
                        known[name] = (number, True)
                        existing[number] = (0, 128)
                        changed = True
                    no, active = known[name]
                    if not active:
                        db.execute("UPDATE simulator104_points SET active=1 WHERE rtu_id=? AND kind=? AND source_name=?",
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
                for name, (no, active) in known.items():
                    if active and name not in current:
                        db.execute("UPDATE simulator104_points SET active=0 WHERE rtu_id=? AND kind=? AND source_name=?",
                                   (rtu, kind, name))
                        db.execute(f"UPDATE {table} SET status=128,refresh_time=? WHERE rtu_id=? AND pnt_no=?",
                                   (now, rtu, no))
                        changed = True
        return changed

    def command_target(self, rtu, kind, number, value):
        if kind not in {"yk", "yt"}:
            raise ValueError("只允许遥控或遥调")
        with self.server.store.connection() as db:
            row = db.execute(
                f"SELECT b.source_name,p.man_disable,p.auto_disable FROM simulator104_points b "
                f"JOIN fes_{kind}_define p ON p.rtu_id=b.rtu_id AND p.pnt_no=b.pnt_no "
                "WHERE b.rtu_id=? AND b.kind=? AND b.pnt_no=? AND b.active=1",
                (rtu, kind, number)).fetchone()
        with self.lock:
            target = self.online.get(rtu)
        if row is None or target is None:
            raise ValueError("仿真控制点未绑定、已退役或模型离线")
        if row[1] or row[2]:
            raise ValueError("控制点已禁止操作")
        if not isinstance(value, (int, float)) or not math.isfinite(value) or (kind == "yk" and value not in (0, 1)):
            raise ValueError("无效遥控或遥调值")
        return target[0], target[1], row[0]

    def execute(self, rtu, kind, number, value):
        base, model, name = self.command_target(rtu, kind, number, value)
        response = request(base, "/api/external/controls/execute?" + urlencode({"model_id": model}),
                           {kind + "_names": [name], kind + "_values": [value],
                            "source": "scdfe_s", "manual_hold": True})
        key = "remote_controls" if kind == "yk" else "remote_adjustments"
        results = response.get(kind + "_results", [])
        if response.get("accepted", {}).get(key) != 1 or (results and not results[0].get("accepted")):
            raise ValueError("仿真模型未接受该指令")
        LOG.info("模型 %s 已接受 RTU%s %s/%s=%s", model, rtu, kind.upper(), number, value)

    def invalidate_offline(self, seen):
        with self.server.store.connection() as db, db:
            offline = [int(rtu) for rtu, in db.execute("SELECT rtu_id FROM simulator104_models") if rtu not in seen]
            for rtu in offline:
                for kind in ("yc", "yx"):
                    raw_status = ",raw_status=128" if kind == "yc" else ""
                    db.execute(
                        f"UPDATE fes_{kind}_define SET status=128{raw_status},refresh_time=? "
                        "WHERE rtu_id=? AND status IS NOT 128 AND pnt_no IN (SELECT pnt_no FROM simulator104_points "
                        "WHERE rtu_id=? AND kind=?)", (time.time_ns() // 1_000_000, rtu, rtu, kind),
                    )

    def status(self):
        with self.lock:
            models = [dict(value) for value in self.models.values()]
            errors = dict(self.last_errors)
        return {"simulator_url": self.simulator_url, "database": self.server.database_info()["database"],
                "models": models, "errors": errors}

    def poll(self):
        while not self.stop.is_set():
            seen = set()
            try:
                for model in request(self.simulator_url, "/api/models")["models"]:
                    service = model.get("service") or {}
                    if not service.get("healthy"):
                        continue
                    name = model["id"]
                    try:
                        base = loopback_url(service["base_url"])
                        points = read_points(base, name)
                        rtu = self.channel(name)
                        changed = self.sync_points(rtu, points)
                        seen.add(rtu)
                        with self.lock:
                            self.online[rtu] = (base, name)
                        channel = self.server.channel_services(rtu_id=rtu)[f"iec104-rtu-{rtu}"]
                        if rtu not in self.initialized or (changed and channel.status()["running"]):
                            self.pending_reload.add(rtu)
                        if rtu in self.pending_reload:
                            if channel.status()["running"]:
                                channel.stop()
                            channel.start()
                            self.pending_reload.remove(rtu)
                            self.initialized.add(rtu)
                        channel_status = channel.status()
                        with self.lock:
                            self.models[rtu] = {"model": name, "rtu_id": rtu, "model_url": base,
                                                "online": True, "running": channel_status["running"],
                                                "endpoint": channel_status.get("endpoint"),
                                                "points": {key: len(items) for key, items in points.items()},
                                                "updated_ms": time.time_ns() // 1_000_000}
                            self.last_errors.pop(name, None)
                    except Exception as exc:
                        self.report_error(name, exc)
                with self.lock:
                    self.last_errors.pop("catalog", None)
            except Exception as exc:
                self.report_error("catalog", exc)
            with self.lock:
                for rtu in self.online.keys() - seen:
                    self.online.pop(rtu, None)
                    if rtu in self.models:
                        self.models[rtu]["online"] = False
            try:
                self.invalidate_offline(seen)
            except Exception as exc:
                self.report_error("database", exc)
            else:
                with self.lock:
                    self.last_errors.pop("database", None)
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
    parser.add_argument("--scada-root", type=Path, default=Path(r"D:\codex\scada"))
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
    sys.path.insert(0, str(args.scada_root.resolve()))
    from scdfe_s.database import SimulatorStore
    from scdfe_s.web.iec104_service import IEC104Service, IEC104ServiceError
    from scdfe_s.web.server import ApiError, ScadaHandler, ScadaHTTPServer

    if (not hasattr(ScadaHTTPServer, "iec104_service_class")
            or not {"simulator104_models", "simulator104_points"}.issubset(
                getattr(SimulatorStore, "extra_metadata_tables", ()))):
        parser.error("当前 SCADA 缺少联动扩展。请按 simulator/README.md 应用 scada104-dependency.patch")

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
            with self._lock:
                if self._server is None or kind not in {"yk", "yt"}:
                    raise IEC104ServiceError("请启动模型 IEC104 通道并选择遥控或遥调点")
                try:
                    actual = self._server.prepare_value(kind, int(point_no), value)
                    bridge.execute(self._server.rtu_id, kind, int(point_no), actual)
                    table, key, fields = self._point_update(kind, int(point_no), actual, self._server.rtu_id)
                    fields["cmd_handle_time"] = fields["refresh_time"]
                    item = self.store.update_row(table, key, fields)
                    self._server.set_value(kind, int(point_no), value)
                except Exception as exc:
                    raise IEC104ServiceError(str(exc)) from exc
                self._record("INFO", f"Web 指令已由仿真模型接受：{kind.upper()}/{point_no}={actual}")
                return {"kind": kind, "pnt_no": int(point_no), "value": actual,
                        "item": item, "applied_to_simulator": True}

    class BridgeHandler(ScadaHandler):
        def _dispatch(self):
            parts, query = self._path()
            if self.command == "GET" and not query:
                if parts == ["api", "simulator104", "status"]:
                    self._prepare_request()
                    return self._json(200, bridge.status())
                assets = {"simulator104": ("scada104.html", "text/html"),
                          "scada104.js": ("scada104.js", "application/javascript"),
                          "scada104.css": ("scada104.css", "text/css")}
                if len(parts) == 1 and parts[0] in assets:
                    self._prepare_request()
                    file, media = assets[parts[0]]
                    content = (APP_ROOT / "simu/web/simulator" / file).read_bytes()
                    return self._send(200, media + "; charset=utf-8", content)
            return super()._dispatch()

    class ModelScadaServer(ScadaHTTPServer):
        iec104_service_class = ModelIEC104Service

        def __init__(self, address, **kwargs):
            super().__init__(address, **kwargs)
            self.RequestHandlerClass = BridgeHandler
            # The generic IEC104 page and per-RTU pages must both call the simulator.
            self.iec104_service = ModelIEC104Service(
                self.store, startup_catalog=self._channel_service_history,
            )
            self._resources.callback(self.iec104_service.close)

        def switch_database(self, body):
            raise ApiError(409, "此进程绑定仿真专库，切换路径请使用 --db 重新启动")

        def simulator_command(self, rtu, kind, number, body):
            with self.store.connection() as db:
                bound = db.execute("SELECT 1 FROM simulator104_models WHERE rtu_id=?", (rtu,)).fetchone()
            if bound is None:
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
    with ModelScadaServer(("127.0.0.1", args.web_port), db_path=database,
                          workspace_root=workspace_root) as server:
        bridge = Bridge(server, simulator_url, args.first_iec104_port, args.interval)
        worker = threading.Thread(target=bridge.poll, name="simulator104", daemon=True)
        worker.start()
        LOG.info("scdfe_s Web http://127.0.0.1:%s, SQLite %s", args.web_port, database)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            bridge.stop.set()
            worker.join()


if __name__ == "__main__":
    main()
