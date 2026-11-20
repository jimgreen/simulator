"""One-click generation of a scdfe_s IEC104 real-time point table."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Mapping


class ScdfePointTableError(RuntimeError):
    pass


class ScdfePointTableManager:
    """Write generated definitions into the dedicated scdfe_s SQLite store."""

    def __init__(self, *, scada_root: str | Path = r"D:\codex\scada", db_path: str | Path | None = None,
                 workspace_root: str | Path | None = None) -> None:
        self.scada_root = Path(scada_root).resolve()
        self.db_path = Path(db_path).resolve() if db_path else self.scada_root / "db" / "scdfe_s.sqlite3"
        self.workspace_root = Path(workspace_root).resolve() if workspace_root is not None else None
        self._validate_path()
        self._store = None

    def _validate_path(self):
        if self.workspace_root is not None and not self.db_path.resolve().is_relative_to(self.workspace_root):
            raise ScdfePointTableError('scdfe_s 数据库必须位于工作区根目录内')

    def _display_path(self):
        return self.db_path.relative_to(self.workspace_root).as_posix() if self.workspace_root else str(self.db_path)

    def _store_for(self):
        self._validate_path()
        if self._store is not None:
            return self._store
        import sys
        root = str(self.scada_root)
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            from scdfe_s.database import SimulatorStore
            from scdfe_c.web.service import SCHEMA_DIR
            self._store = SimulatorStore(self.db_path, SCHEMA_DIR)
        except Exception as exc:
            raise ScdfePointTableError(f"无法打开 scdfe_s 数据库: {exc}") from exc
        return self._store

    @staticmethod
    def _point_row(point: Mapping[str, Any], rtu_id: int) -> tuple[str, dict[str, Any]]:
        kind = str(point.get("kind"))
        no = int(point.get("point_no", point.get("pnt_no")))
        name = str(point.get("description") or point.get("name") or f"{kind.upper()}-{no}")
        value = point.get("initial", point.get("value", False if kind in {"yx", "yk"} else 0.0))
        if kind in {"yx", "yk"}:
            value = int(bool(value))
        else:
            value = float(value)
        common = {"rtu_id": rtu_id, "pnt_no": no, "name": name, "value": value, "status": 0, "refresh_time": int(time.time() * 1000)}
        return kind, common

    def generate(self, points: list[Mapping[str, Any]], *, model_name: str, rtu_id: int = 104, channel_id: int = 104, replace: bool = True) -> dict[str, Any]:
        store = self._store_for()
        tables = {"yc": "fes_yc_define", "yx": "fes_yx_define", "yk": "fes_yk_define", "yt": "fes_yt_define"}
        try:
            with store.connection() as connection:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("BEGIN IMMEDIATE")
                if replace:
                    for table in tables.values():
                        connection.execute(f"DELETE FROM {table} WHERE rtu_id=?", (int(rtu_id),))
                    connection.execute("DELETE FROM fes_channel_iec104_point_define WHERE channel_id=?", (int(channel_id),))
                # Use INSERT with schema defaults through the store's normalizer
                # after the cleanup transaction is committed.
                connection.commit()
            def upsert(table: str, key: list[Any], values: dict[str, Any]) -> dict[str, Any]:
                try:
                    store.get_row(table, key)
                except Exception:
                    return store.create_row(table, values)
                primary_by_table = {
                    "fes_rtu_define": {"rtu_id"},
                    "fes_channel_iec104_define": {"id"},
                    "fes_yc_define": {"rtu_id", "pnt_no"},
                    "fes_yx_define": {"rtu_id", "pnt_no"},
                    "fes_yk_define": {"rtu_id", "pnt_no"},
                    "fes_yt_define": {"rtu_id", "pnt_no"},
                    "fes_channel_iec104_point_define": {"channel_id", "kind", "pnt_no"},
                }
                updates = {name: value for name, value in values.items() if name not in primary_by_table.get(table, set())}
                return store.update_row(table, key, updates)
            now = int(time.time() * 1000)
            upsert("fes_rtu_define", [rtu_id], {"rtu_id": rtu_id, "name": f"{model_name} 数字孪生", "status": 1, "refresh_time": now, "channel_id": channel_id, "channel_type": "iec104", "packet_recording": 0, "process_enable": 1})
            upsert("fes_channel_iec104_define", [channel_id], {"id": channel_id, "name": f"{model_name} IEC104", "channel_id": channel_id, "rtu_addr": 1, "ycbegin_addr": 0x4001, "yxbegin_addr": 1, "ykbegin_addr": 0x6001, "ytbegin_addr": 0x6201, "yx_data_type": 1, "yk_excute_type": 1, "yc_data_type": 13, "yt_excute_type": 3, "remote_host": "127.0.0.1", "remote_port": 2404, "k": 12, "w": 8, "t1": 15.0, "t2": 10.0, "t3": 20.0, "max_asdu_length": 249})
            counts = {kind: 0 for kind in tables}
            for point in points:
                kind, values = self._point_row(point, rtu_id)
                if kind not in tables:
                    continue
                upsert(tables[kind], [rtu_id, int(values["pnt_no"])], values)
                type_id = int(point.get("data_type", 1 if kind in {"yx", "yk"} else 13))
                mapping = {"channel_id": channel_id, "kind": kind, "pnt_no": int(values["pnt_no"]), "io_address": {"yx": 1, "yc": 0x4001, "yk": 0x6001, "yt": 0x6201}[kind] + int(values["pnt_no"]) - 1, "type_id": type_id, "time_tag": "NONE", "report_ms": 1000 if kind in {"yx", "yc"} else 0, "command_mode": "DIRECT", "qualifier": 0, "related_io_autoreturn": 0}
                try:
                    store.get_row("fes_channel_iec104_point_define", [channel_id, kind, int(values["pnt_no"])])
                except Exception:
                    store.create_row("fes_channel_iec104_point_define", mapping)
                else:
                    store.update_row("fes_channel_iec104_point_define", [channel_id, kind, int(values["pnt_no"])], {name: value for name, value in mapping.items() if name not in {"channel_id", "kind", "pnt_no"}})
                counts[kind] += 1
            return {"database": self._display_path(), "rtu_id": int(rtu_id), "channel_id": int(channel_id), "model_name": model_name, "replace": bool(replace), "counts": counts, "total": sum(counts.values())}
        except Exception as exc:
            raise ScdfePointTableError(f"生成 scdfe_s 四遥点表失败: {exc}") from exc

    def summary(self, *, rtu_id: int = 104) -> dict[str, Any]:
        store = self._store_for()
        with store.connection() as connection:
            result = {"database": self._display_path(), "rtu_id": int(rtu_id)}
            for kind, table in (("yc", "fes_yc_define"), ("yx", "fes_yx_define"), ("yk", "fes_yk_define"), ("yt", "fes_yt_define")):
                result[kind] = int(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE rtu_id=?", (int(rtu_id),)).fetchone()[0])
            result["total"] = sum(result[kind] for kind in ("yc", "yx", "yk", "yt"))
            return result

