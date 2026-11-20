"""Latest computed device results, with RTDB-readable embedded table definitions."""
from __future__ import annotations

import math
from pathlib import Path
import re
import sqlite3
import threading

from rtdb_schema import apply_schema, column, physical, quote, read_definitions


DEVICE_COLUMNS = [
    column('device_id', '设备标识', primary=True), column('idx', '模型索引'),
    column('name', '设备名称'), column('device_type', '设备类型'), column('node', '接入节点'),
    column('run_stat', '实际投运状态', 'int'), column('run_command', '投运指令', 'int'),
    column('closed_status', '开关实际合位', 'int'),
    column('p_kw', '有功计算结果 kW', 'float'), column('p_quality', '有功质量码', 'int'),
    column('available_kw', '可用功率上限 kW', 'float'), column('requested_p_kw', '请求功率 kW', 'float'),
    column('soc_pct', '荷电状态 %', 'float'), column('control_mode', '控制方式'),
    column('manual_p_kw', '手动功率设定 kW', 'float'), column('limit_reasons', '限幅原因'),
    column('frame_id', '计算帧标识'), column('revision', '计算版本', 'int'),
    column('sim_seconds', '仿真时刻 秒', 'float'), column('sim_time', '仿真时刻'),
    column('refresh_time', '本帧采样时间 毫秒', 'int'),
]
FRAME_COLUMNS = [
    column('id', '当前帧', 'int', primary=True), column('frame_id', '计算帧标识'),
    column('model_name', '模型名称'), column('model_revision', '模型版本', 'int'),
    column('revision', '计算版本', 'int'), column('calculation', '计算方法'),
    column('converged', '计算收敛', 'int'), column('iterations', '迭代次数', 'int'),
    column('mismatch_kw', '功率残差 kW', 'float'), column('device_count', '设备数', 'int'),
    column('sim_seconds', '仿真时刻 秒', 'float'), column('sim_time', '仿真时刻'),
    column('refresh_time', '本帧采样时间 毫秒', 'int'),
    column('rtu_id', '发布 RTU', 'int'), column('channel_id', '发布通道', 'int'),
]


def finite(value):
    return float(value) if isinstance(value, (float, int)) and math.isfinite(value) else None


class DeviceResultStore:
    APPLICATION_ID = int.from_bytes(b'SIMD', 'big')

    def __init__(self, path, *, workspace_root):
        self.path = Path(path).absolute()
        self.root = Path(workspace_root).resolve()
        self._validate_path()
        self.relative_path = self.path.relative_to(self.root).as_posix()
        self._con = None
        self._lock = threading.RLock()
        self._schema_version = None
        self._definitions = {}

    def _validate_path(self):
        for suffix in ('', '-wal', '-shm', '-journal'):
            path = self.path.with_name(self.path.name + suffix)
            if not path.resolve().is_relative_to(self.root):
                raise ValueError('设备结果数据库必须位于工作区根目录内')

    def _open(self):
        self._validate_path()
        if self._con is not None:
            return self._con
        connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        try:
            application = connection.execute('PRAGMA application_id').fetchone()[0]
            occupied = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()
            if application != self.APPLICATION_ID and (application != 0 or occupied):
                raise ValueError('devices.sqlite3 已存在且不是仿真结果库，拒绝覆盖')
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA synchronous=FULL')
        except BaseException:
            connection.close()
            raise
        self._con = connection
        return connection

    def _schema(self, connection, tables):
        version = connection.execute('PRAGMA schema_version').fetchone()[0]
        if version == self._schema_version and (set(tables) | {'SimulationFrame'}) <= self._definitions.keys():
            return
        if version != self._schema_version:
            self._definitions = read_definitions(connection, self.path)
        mappings = []
        for name in [*sorted(tables), 'SimulationFrame']:
            required = DEVICE_COLUMNS if name != 'SimulationFrame' else FRAME_COLUMNS
            previous = self._definitions.get(name)
            required_names = {c['eng_name'] for c in required}
            # Retain additional columns when an RTDB user extends the output schema.
            extras = [c for c in previous.to_mapping()['columns'] if c['eng_name'] not in required_names] if previous else []
            mapping = {'head': {'eng_name': name, 'chn_name': name + ' 实时计算结果'}, 'columns': [*required, *extras]}
            if previous is None or mapping != previous.to_mapping():
                mappings.append(mapping)
        if mappings:
            self._definitions = apply_schema(connection, self.path, mappings, database_label='仿真设备计算结果')
        self._schema_version = connection.execute('PRAGMA schema_version').fetchone()[0]

    def _upsert(self, connection, table, rows, columns):
        definition = self._definitions[table]
        offsets = {name: f'c{i}' for i, name in enumerate(definition.column_names)}
        names = [c['eng_name'] for c in columns]
        primary = [c['eng_name'] for c in columns if c['primary_key']]
        fields = ','.join(offsets[n] for n in names)
        assignments = ','.join(f'{offsets[n]}=excluded.{offsets[n]}' for n in names if n not in primary)
        sql = (f'INSERT INTO {quote(physical(table))} ({fields}) VALUES ({",".join("?" for _ in names)}) '
               f'ON CONFLICT ({",".join(offsets[n] for n in primary)}) DO UPDATE SET {assignments}')
        definition.validate_rows([definition.apply_defaults(row) for row in rows])
        connection.executemany(sql, [tuple(row.get(n) for n in names) for row in rows])

    def write(self, snapshot, *, frame_id, stamp, rtu_id, channel_id):
        groups = {}
        common = dict(frame_id=frame_id, revision=snapshot['revision'],
                      sim_seconds=snapshot['clock']['sim_seconds'], sim_time=snapshot['clock']['sim_time'],
                      refresh_time=stamp)
        for device in snapshot['devices']:
            table = str(device.get('block') or 'Device')
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', table) or table.lower() == 'simulationframe':
                raise ValueError(f'设备表名无效: {table}')
            power = finite(device.get('p_kw'))
            row = dict(common, device_id=str(device['id']), idx=str(device.get('idx', '')),
                       name=device['name'], device_type=device['type'], node=str(device.get('node', '')),
                       run_stat=int(device['running']), run_command=int(device.get('run', True)),
                       closed_status=int(device['closed_status']) if device['type'] == 'switch' else None,
                       p_kw=power, p_quality=0 if power is not None else 128,
                       available_kw=finite(device.get('available_kw')),
                       requested_p_kw=finite(device.get('requested_p_kw')) if power is not None else None,
                       soc_pct=finite(device.get('soc_pct')), control_mode=device.get('control_mode'),
                       manual_p_kw=finite(device.get('manual_p_kw')),
                       limit_reasons=','.join(device.get('limit_reasons', [])))
            groups.setdefault(table, []).append(row)
        flow = snapshot['power_flow']
        frame = dict(common, id=1, model_name=snapshot['model']['name'], model_revision=snapshot['model_revision'],
                     calculation=flow['calculation'], converged=int(flow['converged']), iterations=flow['iterations'],
                     mismatch_kw=finite(flow.get('mismatch_kw')), device_count=len(snapshot['devices']),
                     rtu_id=rtu_id, channel_id=channel_id)
        with self._lock:
            connection = self._open()
            try:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute(f'PRAGMA application_id={self.APPLICATION_ID}')
                self._schema(connection, groups)
                for table, rows in groups.items():
                    self._upsert(connection, table, rows, DEVICE_COLUMNS)
                # A model switch must not leave old devices visible as current results.
                for table, definition in self._definitions.items():
                    if table != 'SimulationFrame' and {'device_id', 'frame_id'} <= set(definition.column_names):
                        field = 'c' + str(list(definition.column_names).index('frame_id'))
                        connection.execute(f'DELETE FROM {quote(physical(table))} WHERE {field} IS NULL OR {field}<>?', (frame_id,))
                self._upsert(connection, 'SimulationFrame', [frame], FRAME_COLUMNS)
                connection.commit()
            except BaseException:
                connection.rollback()
                self._schema_version = None
                raise
        return len(snapshot['devices'])

    def close(self):
        with self._lock:
            if self._con is not None:
                self._con.close()
                self._con = None
