"""Adapter from the digital twin to the existing scdfe_s IEC 104 server."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

from digital_twin import DigitalTwin


class IEC104Unavailable(RuntimeError):
    pass


def _load_server_class(scada_root: Path):
    root = str(Path(scada_root).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from server.iec104_server import IEC104Command, IEC104Server
    except Exception as exc:  # pragma: no cover - depends on external checkout
        raise IEC104Unavailable(f"无法加载 D:/codex/scada 的 IEC104 接口: {exc}") from exc
    return IEC104Command, IEC104Server


class ScdfeIEC104Bridge:
    """Publish real-time points and receive device yk commands through scdfe_s."""

    def __init__(
        self,
        twin: DigitalTwin,
        *,
        scada_root: str | Path = r"D:\codex\scada",
        bind_ip: str = "127.0.0.1",
        port: int = 2404,
        common_address: int = 1,
        rtu_id: int = 104,
    ) -> None:
        self.twin = twin
        self.scada_root = Path(scada_root)
        self.bind_ip = bind_ip
        self.port = int(port)
        self.common_address = int(common_address)
        self.rtu_id = int(rtu_id)
        self._lock = threading.RLock()
        self._server = None
        self._last_publish_seq = 0
        self._last_error = ""
        self._build()

    def _build(self) -> None:
        _command, server_class = _load_server_class(self.scada_root)
        server = server_class(
            ip=self.bind_ip,
            port=self.port,
            common_address=self.common_address,
            rtu_id=self.rtu_id,
            tick_rate_ms=100,
            select_timeout_ms=10000,
            max_connections=0,
        )
        for point in self.twin.points():
            kind = str(point.get("kind"))
            point_no = int(point.get("point_no", point.get("pnt_no")))
            handler = None
            if kind in {"yk", "yt"}:
                handler = self._on_command
            server.add_point(
                kind,
                point_no,
                data_type=int(point.get("data_type", 1 if kind in {"yx", "yk"} else 13)),
                value=self.twin.point_values().get(kind, {}).get(point_no, point.get("initial", point.get("value", False if kind in {"yx", "yk"} else 0.0))),
                report_ms=1000 if kind in {"yx", "yc"} else 0,
                command_handler=handler,
            )
        self._server = server

    def rebuild(self) -> dict[str, Any]:
        """Rebuild the station after a model import or point-table change."""
        with self._lock:
            was_running = self.running
            if self._server is not None and was_running:
                self._server.stop()
            self._server = None
            self._build()
            if was_running:
                self._server.start()
            return self.status()

    def _on_command(self, command: Any) -> bool:
        try:
            self.twin.apply_command(
                command.kind,
                command.point_no,
                command.value,
                selected=bool(command.selected),
            )
            return True
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            return False

    @property
    def available(self) -> bool:
        return self._server is not None

    @property
    def running(self) -> bool:
        return bool(self._server and self._server.running)

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._server is None:
                raise IEC104Unavailable("IEC104 服务未构造")
            if not self._server.running:
                self._server.start()
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._server is not None:
                self._server.stop()
            return self.status()

    def publish(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._server is None or not self._server.running:
                return {"published": False, "reason": "stopped"}
            values = self.twin.point_values()
            updates = []
            for kind in ("yx", "yc"):
                updates.extend((kind, int(point_no), value, None) for point_no, value in values[kind].items())
            errors = self._server.update_monitoring(updates, transmit=True, cause="SPONTANEOUS", isolate_errors=True)
            self._last_publish_seq = int(snapshot.get("sequence", 0))
            if errors:
                self._last_error = "; ".join(f"{key}: {error}" for key, error in errors.items())
            return {"published": not bool(errors), "points": len(updates), "errors": len(errors)}

    def status(self) -> dict[str, Any]:
        with self._lock:
            server = self._server
            return {
                "available": server is not None,
                "running": bool(server and server.running),
                "bind_ip": self.bind_ip,
                "port": self.port,
                "common_address": self.common_address,
                "rtu_id": self.rtu_id,
                "connections": int(server.active_connection_count) if server else 0,
                "last_publish_seq": self._last_publish_seq,
                "last_error": self._last_error,
                "provider": "D:\\codex\\scada\\server\\iec104_server.py (scdfe_s IEC104Server)",
                "point_count": len(self.twin.points()),
            }

