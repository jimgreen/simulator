"""Read SCADA's device/measurement/point catalog without changing its definitions."""
from collections import Counter
import math
from pathlib import Path
import sqlite3
import threading


class MeasurementMapping:
    def __init__(self, path, *, workspace_root):
        self.path = Path(path).absolute()
        self.root = Path(workspace_root).resolve()
        self.relative_path = self.path.relative_to(self.root).as_posix()
        self._lock = threading.RLock()
        self._connection = None
        self._identity = None
        self._version = None
        self._rows = []

    def close(self):
        with self._lock:
            if self._connection is not None:
                self._connection.close()
            self._connection = None
            self._version = None

    def bindings(self):
        with self._lock:
            for suffix in ('', '-wal', '-shm', '-journal'):
                if not self.path.with_name(self.path.name + suffix).resolve().is_relative_to(self.root):
                    raise ValueError('设备量测映射库必须位于工作区根目录内')
            stat = self.path.stat()
            identity = (stat.st_dev, stat.st_ino)
            if identity != self._identity:
                self.close()
                self._identity = identity
            if self._connection is None:
                self._connection = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=2, check_same_thread=False)
                self._connection.row_factory = sqlite3.Row
                self._connection.execute('PRAGMA query_only=ON')
            connection = self._connection
            version = connection.execute('PRAGMA data_version').fetchone()[0]
            if version == self._version:
                return self._rows
            connection.execute('BEGIN')
            try:
                rows = [dict(row) for row in connection.execute('''
                    SELECT d.model_table,d.model_idx,d.name device_name,d.active,
                           m.measurement_id,m.metric,m.kind,m.name,m.unit,m.catalog_active,
                           s.rtu_id,s.pnt_no,s.enabled,s.scale,s.offset,s.source_database
                    FROM device_measurement m JOIN device d USING(device_id)
                    JOIN scada_point_mapping s USING(measurement_id)
                    ORDER BY m.kind,s.rtu_id,s.pnt_no,m.measurement_id''')]
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            targets = set()
            for row in rows:
                if row['kind'] not in {'yc', 'yx'}:
                    raise ValueError('设备量测映射仅支持 yc/yx，不能写入控制命令点')
                target = (row['kind'], int(row['rtu_id']), int(row['pnt_no']))
                if target in targets:
                    raise ValueError(f'多个量测映射到同一发布点: {target}')
                if target[1] < 1 or target[2] < 1:
                    raise ValueError(f'量测点号无效: {target}')
                targets.add(target)
                row['device_key'] = f'{row["model_table"]}:{row["model_idx"]}'
            if not rows:
                raise ValueError('设备量测映射库没有可发布的映射')
            self._rows, self._version = rows, version
            return self._rows

    @staticmethod
    def _quantity(row, device, snapshot):
        metric = row['metric'].lower()
        unit = str(row['unit'] or '').strip().lower()
        if metric == 'run':
            return int(device['running']), ''
        if metric == 'position' and device['type'] == 'switch':
            return int(device['closed_status']), ''
        if metric in {'charging', 'discharging'} and device['type'] == 'battery' and device.get('p_kw') is not None:
            return int(device['running'] and (device['p_kw'] < 0 if metric == 'charging' else device['p_kw'] > 0)), ''
        # Explicit computed quantities only; do not substitute nameplate values
        # or aggregate grid voltage for an unsolved device measurement.
        fields = {'p': ('p_kw', 'kw'), 'q': ('q_kvar', 'kvar'),
                  'i_p': ('p_from_kw', 'kw'), 'j_p': ('p_to_kw', 'kw'),
                  'i_q': ('q_from_kvar', 'kvar'), 'j_q': ('q_to_kvar', 'kvar'),
                  'u': ('voltage_v', 'v'), 'f': ('frequency_hz', 'hz'),
                  'soc': ('soc_pct', '%')}
        if metric in fields:
            field, native_unit = fields[metric]
            value = device.get(field)
        elif metric == 'p_set_readback' and device.get('p_kw') is not None:
            value, native_unit = device.get('requested_p_kw'), 'kw'
        elif metric == 'wind_speed' and device['type'] == 'wind':
            value, native_unit = snapshot['weather'].get('wind_speed_mps'), 'm/s'
        elif metric == 'irradiance' and device['type'] == 'pv':
            value, native_unit = snapshot['weather'].get('solar_irradiance_w_m2'), 'w/m²'
        else:
            return None, 'not_computed'
        if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None, 'not_computed'
        conversion = {('kw', 'mw'): .001, ('kw', 'w'): 1000,
                      ('kvar', 'mvar'): .001, ('kvar', 'var'): 1000,
                      ('v', 'kv'): .001, ('%', 'pu'): .01, ('%', 'p.u.'): .01,
                      ('w/m²', 'w/m2'): 1}
        if unit and unit != native_unit:
            factor = conversion.get((native_unit, unit))
            if factor is None:
                return None, 'unsupported_unit'
            value *= factor
        return value, ''

    def project(self, snapshot):
        devices = {str(d['id']): d for d in snapshot['devices']}
        points, reasons = [], Counter()
        for row in self.bindings():
            device = devices.get(row['device_key'])
            reason, value = '', None
            if not (row['active'] and row['catalog_active'] and row['enabled']):
                reason = 'disabled'
            elif device is None or device['name'] != row['device_name']:
                reason = 'device_mismatch'
            else:
                value, reason = self._quantity(row, device, snapshot)
            if not reason:
                scale, offset = row['scale'], row['offset']
                if not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale == 0 or not isinstance(offset, (int, float)) or not math.isfinite(offset):
                    reason, value = 'invalid_transform', None
                else:
                    # scdfe_d collects physical = source * scale + offset.
                    value = (value - offset) / scale
                    if not math.isfinite(value) or (row['kind'] == 'yx' and value not in (0, 1)):
                        reason, value = 'invalid_transform', None
            if reason:
                reasons[reason] += 1
            points.append(dict(kind=row['kind'], rtu_id=int(row['rtu_id']), point_no=int(row['pnt_no']),
                               name=row['name'], description=row['device_name'] + ' / ' + row['metric'],
                               device_id=row['device_key'], measurement_id=row['measurement_id'],
                               metric=row['metric'], unit=row['unit'], value=value, quality=128 if reason else 0,
                               reason=reason, source_database=row['source_database']))
        return points, {'mapping_database': self.relative_path, 'mapping_mode': 'device_measurement',
                        'mapped_points': len(points), 'valid_points': len(points) - sum(reasons.values()),
                        'invalid_reasons': dict(reasons), 'rtu_ids': sorted({p['rtu_id'] for p in points})}
