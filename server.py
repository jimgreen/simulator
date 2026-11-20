"""Web console and real-time API for the standalone digital twin."""

from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
import threading
import time
from urllib.parse import parse_qs, urlparse

from digital_twin import DigitalTwin
from device_results import DeviceResultStore
from iec104_bridge import ScdfeIEC104Bridge
from model_import import load_boundary_bytes, load_model_bytes, sanitize_svg
from model_database import ModelDatabaseSource
from measurement_mapping import MeasurementMapping
from scdfe_points import ScdfePointTableManager
from scdfe_realtime import ScdfeRealtimeWriter
from workspace import DEFAULT_WORKSPACE_ROOT, Workspace
from state_store import DEFAULT_STATE_DIRECTORY, SimulatorStateStore, encode


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"


class SimulatorApplication:
    def __init__(self, args: argparse.Namespace, *, model_config=None) -> None:
        self.workspace = Workspace(args.workspace_root)
        self._model_lock = threading.RLock()
        self.state_store = SimulatorStateStore(self.workspace, args.state_directory)
        saved_settings = self.state_store.load('global')
        self.preferences = saved_settings.get('preferences', {})
        self.iec104_requested = saved_settings.get('iec104_running', True)
        self.storage_error = ''
        self._checkpoint_at = time.monotonic()
        self.model_source = ModelDatabaseSource(self.workspace, directory=args.model_directory or saved_settings.get('model_directory'),
                                               config_file=model_config or ROOT / 'runtime/model_source.json')
        try:
            model, source_info = self.model_source.prepare()
        except Exception:
            self.state_store.close()
            raise
        self.twin = DigitalTwin(seed=args.seed, step_seconds=args.step_seconds, model=model)
        self.model_source.activate(source_info)
        self._scope = self._model_scope(model)
        saved = self.state_store.load(self._scope)
        self.restored = 'model' in saved and 'runtime' in saved
        if self.restored:
            self.twin.restore_persistent_state(saved)
        self.point_generation = saved.get('point_generation')
        self._seed, self._step_seconds = args.seed, args.step_seconds
        default_db = self.workspace.root / 'simulation/qinling/sqldb/scada/scdfe_s.sqlite3'
        if not default_db.is_file():
            default_db = self.workspace.root / 'simulation/scdfe_s.sqlite3'
        database = self.workspace.root / args.scada_db if args.scada_db else default_db
        self.point_tables = ScdfePointTableManager(scada_root=args.scada_root, db_path=database,
                                                 workspace_root=self.workspace.root)
        mapping_path = self.workspace.root / args.mapping_db if args.mapping_db else database.with_name('scdfe_d.sqlite3')
        if not args.mapping_db and not mapping_path.is_file():
            mapping_path = database.with_name('devices.sqlite3')
        self.measurement_mapping = (MeasurementMapping(mapping_path, workspace_root=self.workspace.root)
                                    if args.mapping_db or mapping_path.is_file() else None)
        self.bridge = None
        self._stop = threading.Event()
        if not args.no_iec104 and self.measurement_mapping is None:
            try:
                self.bridge = ScdfeIEC104Bridge(
                    self.twin,
                    scada_root=args.scada_root,
                    bind_ip=args.iec104_bind,
                    port=args.iec104_port,
                    common_address=args.common_address,
                    rtu_id=args.rtu_id,
                )
                if self.iec104_requested:
                    self.bridge.start()
            except Exception as exc:
                print(f"IEC104 未启动: {exc}", flush=True)
                self.bridge = None
        self._persist()
        self._default_rtu = args.rtu_id
        self._publication_definition = None
        self.device_results = DeviceResultStore(self.state_store.path.with_name('devices.sqlite3'), workspace_root=self.workspace.root)
        self.database_writer = ScdfeRealtimeWriter(self.point_tables, device_store=self.device_results,
                                                  measurement_mapping=self.measurement_mapping)
        self._queue_results()
        self.worker = threading.Thread(target=self._loop, name="digital-twin-loop", daemon=True)
        self.worker.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._model_lock:
                changed = self.twin.run_cycle()
                if changed or self.twin._revision != self._last_queued_revision:
                    self._queue_results()
                if changed and self.bridge is not None:
                    try:
                        self.bridge.publish(self.twin.snapshot(history_limit=1))
                    except Exception as exc:
                        print(f"IEC104 发布失败: {exc}", flush=True)
                if time.monotonic() - self._checkpoint_at >= 5:
                    try:
                        self._persist(runtime_only=True)
                    except Exception as exc:
                        self.storage_error = str(exc)
                        print(f"仿真状态保存失败: {exc}", flush=True)
                    self._checkpoint_at = time.monotonic()
            self._stop.wait(0.05)

    def _queue_results(self):
        with self.twin._lock:
            self._last_queued_revision = self.twin._revision
            key = (self._scope, self.twin._model_revision)
            if self._publication_definition is None or self._publication_definition[0] != key:
                self._publication_definition = (key, self.twin.points())
            options = (self.point_generation or {}).get('options', {})
            rtu_id = options.get('rtu_id', self._default_rtu)
            return self.database_writer.submit(
                points=self._publication_definition[1], model_name=self.twin.model['name'],
                rtu_id=rtu_id, channel_id=options.get('channel_id', rtu_id),
                values=self.twin.point_values(), clock=self.twin.clock(),
                device_results=self.twin.snapshot(profile='devices', history_limit=0))

    def load_database_source(self, body, *, validate_only=False):
        if set(body) - {'directory'}:
            raise ValueError('仅可修改目录，数据库文件名固定为 devices.sqlite3')
        with self._model_lock:
            directory = body.get('directory', self.model_source.directory)
        # Disk I/O and candidate validation must not stall the running simulation.
        model, info = self.model_source.prepare(directory)
        DigitalTwin(seed=self._seed, step_seconds=self._step_seconds, model=model)
        with self._model_lock:
            restored = False
            if not validate_only:
                scope = self._model_scope(model)
                saved = self.state_store.load(scope)
                restored = 'model' in saved and 'runtime' in saved
                revision = self.twin._model_revision
                if restored:
                    self.twin.restore_persistent_state(saved)
                    # A live source switch invalidates commands from previously opened pages.
                    self.twin._model_revision = max(revision, self.twin._model_revision) + 1
                else:
                    self.twin.load_model(model)
                self.model_source.activate(info)
                self._scope = scope
                self.point_generation = saved.get('point_generation') if restored else None
            message = ('已恢复该电网保存的曲线、参数和运行状态，目录配置已保存' if restored
                       else '电网数据库已加载，目录配置已保存')
            return {'source': info, 'model': self.twin.model_summary(), 'validated': True, 'restored': restored,
                    'message': '数据库校验通过' if validate_only else message}

    @staticmethod
    def _model_scope(model):
        return 'model:' + hashlib.sha256(encode(model).encode('utf-8')).hexdigest()

    def _persist(self, *, action=None, detail=None, runtime_only=False):
        sections = self.twin.export_persistent_state(runtime_only=runtime_only)
        settings = None
        if not runtime_only:
            sections['point_generation'] = self.point_generation
            settings = {'model_directory': self.model_source.directory, 'preferences': self.preferences,
                        'iec104_running': self.iec104_requested}
        self.state_store.save(self._scope, sections, settings=settings, action=action, detail=detail)
        self.storage_error = ''
        self._checkpoint_at = time.monotonic()

    def storage_status(self):
        return {**self.state_store.status(), 'restored': self.restored, 'last_error': self.storage_error}

    def mutate(self, path, body, operation):
        """Commit a Web edit before acknowledging it or publishing new values."""
        with self._model_lock:
            with self.twin._lock:
                previous = self.twin.export_persistent_state()
                source = deepcopy(self.model_source.status())
                previous_scope = self._scope
                previous_settings = deepcopy((self.preferences, self.iec104_requested, self.point_generation))
                try:
                    result = operation()
                    # Imported data live in state sections; the journal keeps compact provenance.
                    detail = {key: value for key, value in body.items() if key not in {'data_base64', 'model', 'values', 'curves'}}
                    if 'data_base64' in body:
                        detail['uploaded_base64_bytes'] = len(body['data_base64'])
                    self._persist(action=path, detail=detail)
                except Exception as exc:
                    self.twin.restore_persistent_state(previous)
                    self.model_source.activate(source)
                    self._scope = previous_scope
                    self.preferences, self.iec104_requested, self.point_generation = previous_settings
                    self.storage_error = str(exc) if not isinstance(exc, ValueError) else self.storage_error
                    raise
            # External publication follows durable local commit and is reported separately.
            try:
                if path == '/api/scdfe/points/generate':
                    job = self.point_generation
                    result = (self.database_writer.validate_mapping() if self.measurement_mapping is not None
                              else self.point_tables.generate(job['points'], **job['options']))
                    job['result'], job['status'] = result, 'delivered'
                    self._persist()
                if self.bridge is not None:
                    if path in {'/api/model/source', '/api/scdfe/points/generate'}:
                        self.bridge.rebuild()
                    elif path == '/api/iec104/start':
                        result = self.bridge.start()
                    elif path == '/api/iec104/stop':
                        result = self.bridge.stop()
                    elif path != '/api/preferences':
                        self.bridge.publish(self.twin.snapshot(history_limit=1))
            except Exception as exc:
                result['delivery_error'] = str(exc)
                result['iec104_error'] = str(exc)
                result['message'] = result.get('message', '修改已保存') + '；外部服务同步失败：' + str(exc)
            if path != '/api/preferences':
                result['database_submission'] = self._queue_results()
            result['persistence'] = {'saved': True, 'database': self.state_store.relative_path}
            return result

    def set_preferences(self, body):
        page, values = body.get('page'), body.get('values')
        if not isinstance(page, str) or not page or len(page) > 64 or not isinstance(values, dict) or len(encode(values)) > 64000:
            raise ValueError('页面设置格式无效或超过 64 KB')
        self.preferences.setdefault(page, {}).update(deepcopy(values))
        return {'page': page, 'values': self.preferences[page]}

    def prepare_point_generation(self, body):
        if self.measurement_mapping is not None:
            if set(body) - {'replace'}:
                raise ValueError('映射模式的 RTU 和点号由设备量测库定义，不能在此重编')
            self.point_generation = {'mode': 'device_measurement', 'mapping_database': self.measurement_mapping.relative_path,
                                     'status': 'pending'}
            return {'message': '映射配置已保存，等待核对 scdfe_s 点表'}
        previous = (self.point_generation or {}).get('options', {})
        rtu_id = int(body.get('rtu_id', previous.get('rtu_id', self._default_rtu)))
        channel_id = int(body.get('channel_id', rtu_id if 'rtu_id' in body else previous.get('channel_id', rtu_id)))
        if rtu_id < 1 or channel_id < 1:
            raise ValueError('RTU 和通道编号必须为正整数')
        options = {'model_name': self.twin.model['name'], 'rtu_id': rtu_id,
                   'channel_id': channel_id, 'replace': bool(body.get('replace', True))}
        self.point_generation = {'options': options, 'points': self.twin.points(), 'status': 'pending'}
        return {'message': '四遥点表已保存，等待同步 scdfe_s'}

    def close(self) -> None:
        self._stop.set()
        self.worker.join(timeout=2)
        if self.bridge is not None:
            self.bridge.stop()
        self.database_writer.close()
        self.point_tables.close()
        try:
            with self._model_lock:
                self._persist()
        finally:
            self.state_store.close()


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
            if path == '/api/storage':
                return self._send(200, self.app.storage_status())
            if path == '/api/storage/operations':
                return self._send(200, {'items': self.app.state_store.operations(parse_qs(parsed.query).get('limit', [50])[0])})
            if path == '/api/preferences':
                page = parse_qs(parsed.query).get('page', [''])[0]
                with self.app._model_lock:
                    return self._send(200, {'page': page, 'values': deepcopy(self.app.preferences.get(page, {}))})
            if path == '/api/scdfe/realtime':
                return self._send(200, self.app.database_writer.status())
            if path == "/api/model/source":
                with self.app._model_lock:
                    return self._send(200, {"source": self.app.model_source.status(), "model": self.app.twin.model_summary()})
            if path == "/api/workspace":
                query = parse_qs(parsed.query)
                return self._send(200, self.app.workspace.listing(
                    directory=query.get('directory', ['.'])[0], kind=query.get('kind', ['model'])[0],
                    page=query.get('page', [1])[0], page_size=query.get('page_size', [8])[0],
                    query=query.get('q', [''])[0]))
            if path == "/api/health":
                return self._send(200, {"status": "ok", "service": "environment-aware-digital-twin", "model": self.app.twin.model_summary(), "scdfe_database": self.app.database_writer.status(), "iec104": self.app.bridge.status() if self.app.bridge else {"available": False}})
            if path == "/api/overview":
                profile = parse_qs(parsed.query).get("profile", ["full"])[0]
                snapshot = self.app.twin.snapshot(history_limit=120, profile=profile)
                return self._send(200, {
                    "snapshot": snapshot,
                    "health": {"status": "ok", "service": "environment-aware-digital-twin", "model": snapshot["model"], "iec104": self.app.bridge.status() if self.app.bridge else {"available": False}},
                })
            if path == "/api/snapshot":
                query = parse_qs(parsed.query)
                limit = int(query.get("history", [120])[0])
                profile = query.get("profile", ["full"])[0]
                return self._send(200, self.app.twin.snapshot(history_limit=limit, profile=profile))
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
                if getattr(self.app, 'measurement_mapping', None) is not None:
                    return self._send(200, {"items": self.app.database_writer.point_preview()})
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
                status = self.app.database_writer.status()
                rtus = status.get('rtu_ids') or [status['rtu_id'] or self.app._default_rtu]
                summaries = [self.app.point_tables.summary(rtu_id=rtu) for rtu in rtus]
                counts = {kind: sum(s[kind] for s in summaries) for kind in ('yc', 'yx', 'yk', 'yt', 'total')}
                return self._send(200, {**summaries[0], **counts, 'publication': status})
            if path == "/api/iec104/status":
                return self._send(200, self.app.bridge.status() if self.app.bridge else {"available": False, "running": False, "last_error": "桥接未启用"})
            if path == "/" or path == "/index.html":
                return self._static("index.html", "text/html; charset=utf-8")
            if path.endswith(".html") and path.count("/") == 1:
                return self._static(path[1:], "text/html; charset=utf-8")
            if path in {"/app.js", "/nav.js", "/styles.css", "/diagram.js", "/diagram.css", "/boundary.js", "/workspace.js", "/workspace.css", "/model-source.js", "/model-source.css", "/storage.js", "/storage.css", "/publication.js", "/publication.css"}:
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

    def _import_input(self, body, kind):
        if 'path' in body:
            if 'data_base64' in body or 'model' in body:
                raise ValueError('请选择工作目录路径或上传内容，不可同时提供')
            return self.app.workspace.read(body['path'], kind)
        default = {'model': 'model.json', 'boundary': 'boundary.csv', 'diagram': 'diagram.svg'}[kind]
        source = Path(PureWindowsPath(str(body.get('filename') or default)).name).name
        if body.get('data_base64'):
            return base64.b64decode(str(body['data_base64']), validate=True), source
        if kind == 'model' and isinstance(body.get('model'), dict):
            return json.dumps(body['model'], ensure_ascii=False).encode('utf-8'), source
        raise ValueError('请选择工作目录文件或上传输入文件')

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._json_body()
            def operation():
                return self._dispatch_post(path, body)
            if hasattr(self.app, 'state_store') and path != '/api/model/source/validate':
                result = self.app.mutate(path, body, operation)
            else:
                result = operation()
            return self._send(200, result)
        except NotImplementedError:
            return self._send(404, {"error": "not_found"})
        except Exception as exc:
            return self._send(400, {"error": str(exc)})

    def _dispatch_post(self, path, body):
        if path == '/api/preferences':
            return self.app.set_preferences(body)
        if path in {"/api/model/source", "/api/model/source/validate"}:
            return self.app.load_database_source(body, validate_only=path.endswith('/validate'))
        if path == "/api/clock":
            return {"clock": self.app.twin.command_clock(body.get("action"), body.get("value"))}
        if path == "/api/model/import":
            if hasattr(self.app, 'model_source'):
                raise ValueError('仿真内核电网模型必须来自 devices.sqlite3，请在模型管理中配置数据库目录')
            data, source_name = self._import_input(body, 'model')
            model = load_model_bytes(data, source_name=source_name)
            summary = self.app.twin.load_model(model)
            if self.app.bridge is not None and not hasattr(self.app, 'state_store'):
                self.app.bridge.rebuild()
            return {"model": summary, "points": len(self.app.twin.points()), "message": "模型已导入并已刷新运行点表"}
        if path == "/api/scdfe/points/generate":
            if hasattr(self.app, "state_store"):
                return self.app.prepare_point_generation(body)
            result = self.app.point_tables.generate(self.app.twin.points(), model_name=self.app.twin.model.get("name", "digital-twin"), rtu_id=int(body.get("rtu_id", 104)), channel_id=int(body.get("channel_id", body.get("rtu_id", 104))), replace=bool(body.get("replace", True)))
            if self.app.bridge is not None and not hasattr(self.app, 'state_store'):
                self.app.bridge.rebuild()
            return result
        if path == "/api/curves":
            curves = self.app.twin.set_curves(body)
            if self.app.bridge is not None and not hasattr(self.app, 'state_store'):
                self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
            return {"curves": curves}
        if path == "/api/boundary/import":
            data, source_name = self._import_input(body, 'boundary')
            boundary = load_boundary_bytes(data, source_name=source_name)
            curves = self.app.twin.merge_curves(boundary["curves"], source=boundary["source"])
            if self.app.bridge is not None and not hasattr(self.app, 'state_store'):
                self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
            return {**boundary, "curves": curves, "message": "外部边界数据已加载"}
        if path == "/api/diagram/import":
            data, source_name = self._import_input(body, 'diagram')
            diagram = sanitize_svg(data, source_name=source_name)
            return {"diagram": self.app.twin.set_diagram(diagram, source="web"), "message": "SVG 电网图形已加载"}
        if path == "/api/devices/state":
            result = self.app.twin.set_device_state(str(body.get("device_id")), body.get("running"), source="web")
            if self.app.bridge is not None and not hasattr(self.app, 'state_store'):
                self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
            return result
        if path == "/api/devices/operate":
            result = self.app.twin.operate_device(body.get("device_id"), body.get("action"), value=body.get("value"), model_revision=body.get("model_revision"))
            if self.app.bridge is not None and not hasattr(self.app, 'state_store'):
                self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
            return result
        if path == "/api/devices/actions":
            result = self.app.twin.apply_device_actions(body.get("actions"), model_revision=body.get("model_revision"), source="web")
            if self.app.bridge is not None and not hasattr(self.app, 'state_store'):
                self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
            return result
        if path == "/api/devices/states":
            result = self.app.twin.set_devices_state(body.get("states"), source="web")
            if self.app.bridge is not None and not hasattr(self.app, 'state_store'):
                self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
            return result
        if path == "/api/scenario":
            result = self.app.twin.apply_scenario(body.get("name"), source=str(body.get("source", "web")))
            if self.app.bridge is not None and not hasattr(self.app, 'state_store'):
                self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
            return result
        if path == "/api/topology":
            result = self.app.twin.set_topology(body)
            if self.app.bridge is not None and not hasattr(self.app, 'state_store'):
                self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
            return result
        if path == "/api/commands":
            result = self.app.twin.apply_command(body.get("kind"), int(body.get("point_no")), body.get("value"), selected=bool(body.get("selected")))
            if self.app.bridge is not None and not hasattr(self.app, 'state_store'):
                self.app.bridge.publish(self.app.twin.snapshot(history_limit=1))
            return result
        if path == "/api/iec104/start":
            if self.app.bridge is None:
                raise RuntimeError("IEC104 桥接未加载，请检查 scada_root")
            if hasattr(self.app, "state_store"):
                self.app.iec104_requested = True
                return {"requested": True}
            return self.app.bridge.start()
        if path == "/api/iec104/stop":
            if self.app.bridge is None:
                raise RuntimeError("IEC104 桥接未加载")
            if hasattr(self.app, "state_store"):
                self.app.iec104_requested = False
                return {"requested": False}
            return self.app.bridge.stop()
        raise NotImplementedError(path)

    def log_message(self, format, *args):
        return


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Environment-aware power-system digital twin")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780, help="Web API port")
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT, help="Web 文件访问根目录；模型、边界、SVG 使用根目录内的相对路径")
    parser.add_argument("--model-directory", default=None, help="电网数据库目录；默认 simulation/qinling/sqldb/model，固定读取 devices.sqlite3")
    parser.add_argument("--state-directory", default=DEFAULT_STATE_DIRECTORY, help="根目录内的仿真配置与状态库目录，固定文件 simulator.sqlite3")
    parser.add_argument("--scada-root", default=r"D:\codex\scada")
    parser.add_argument("--scada-db", default=None, help="工作区根目录内的 scdfe_s 数据库；默认使用 simulation 下的数据库")
    parser.add_argument("--mapping-db", default=None, help="设备量测映射库的根目录相对路径；默认读取发布点库同目录的 scdfe_d.sqlite3，兼容 devices.sqlite3")
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

