"""Commit simulator monitoring frames through the existing scdfe_s store API."""
from __future__ import annotations

import math
import threading
import time
from uuid import uuid4


class ScdfeRealtimeWriter:
    """One bounded latest-frame slot; SQLite waits never block the simulation loop."""

    def __init__(self, manager, *, device_store=None, measurement_mapping=None):
        self.manager = manager
        self.device_store = device_store
        self.measurement_mapping = measurement_mapping
        self._mapped_preview = []
        self._session = uuid4().hex
        self._condition = threading.Condition()
        self._pending = None
        self._last_stamp_ms = 0
        self._closing = False
        self._prepared = None
        self._columns = {}
        self._status = dict(database=manager._display_path(), rtu_id=None, channel_id=None,
                            submitted=0, committed=0, batches=0, coalesced=0, written_points=0,
                            last_commit_ms=None, last_duration_ms=None, last_sim_time=None,
                            last_error='', failures=0, device_database=device_store.relative_path if device_store else None,
                            written_devices=0, devices_committed=0, points_committed=0,
                            last_device_frame=None, last_point_frame=None, device_error='', point_error='',
                            mapping_mode='device_measurement' if measurement_mapping else 'generated',
                            mapping_database=measurement_mapping.relative_path if measurement_mapping else None)
        self._thread = threading.Thread(target=self._run, name='scdfe-database-writer', daemon=True)
        self._thread.start()

    def submit(self, *, points, model_name, rtu_id, channel_id, values, clock, device_results=None):
        with self._condition:
            if self._closing:
                raise RuntimeError('scdfe_s 写库线程已关闭')
            self._status['submitted'] += 1
            if self._pending is not None:
                self._status['coalesced'] += 1
            serial = self._status['submitted']
            # Distinct frames must not reuse a timestamp: scdfe_s fills unchanged
            # refresh_time on value changes, which would split the shared sample time.
            self._last_stamp_ms = max(time.time_ns() // 1_000_000, self._last_stamp_ms + 1)
            # Definitions are immutable copies owned by the application until model replacement.
            self._pending = dict(serial=serial, points=points, model_name=model_name,
                                 frame_id=f'{self._session}:{serial}', stamp_ms=self._last_stamp_ms,
                                 device_results=device_results,
                                 rtu_id=int(rtu_id), channel_id=int(channel_id),
                                 values={k: dict(values.get(k, {})) for k in ('yc', 'yx')}, clock=dict(clock))
            if self.measurement_mapping is None:
                self._status.update(rtu_id=int(rtu_id), channel_id=int(channel_id))
            self._condition.notify_all()
            return serial

    def status(self):
        with self._condition:
            result = dict(self._status)
            result['pending'] = result['submitted'] > result['committed']
            result['running'] = self._thread.is_alive() and not self._closing
            return result

    def wait_for(self, serial, timeout=5):
        with self._condition:
            return self._condition.wait_for(lambda: self._status['committed'] >= serial, timeout)

    def point_preview(self):
        with self._condition:
            return list(self._mapped_preview)

    def validate_mapping(self):
        rows = self.measurement_mapping.bindings()
        rtus = sorted({int(r['rtu_id']) for r in rows})
        channels = []
        counts = dict(yc=0, yx=0)
        with self.manager.lock:
            store = self.manager._store_for()
            for rtu in rtus:
                channels.append(int(store.get_row('fes_rtu_define', [rtu])['channel_id']))
            with store.connection() as connection:
                for kind in counts:
                    expected = {(int(r['rtu_id']), int(r['pnt_no'])) for r in rows if r['kind'] == kind}
                    actual = {tuple(r) for r in connection.execute(f'SELECT rtu_id,pnt_no FROM fes_{kind}_define')}
                    if missing := expected - actual:
                        raise ValueError(f'scdfe_s 缺少映射点 {kind}: {sorted(missing)[:5]}')
                    counts[kind] = len(expected)
        return dict(database=self.manager._display_path(), mapping_database=self.measurement_mapping.relative_path,
                    rtu_ids=rtus, channel_ids=sorted(set(channels)), counts=counts, total=len(rows),
                    message='设备量测映射与 scdfe_s 点表已核对，不重编点号')

    def close(self):
        with self._condition:
            self._closing = True
            self._condition.notify_all()
        self._thread.join(timeout=30)
        if self._thread.is_alive():
            raise RuntimeError('scdfe_s 写库线程未能按时停止')
        if self.device_store is not None:
            self.device_store.close()
        if self.measurement_mapping is not None:
            self.measurement_mapping.close()

    def _write(self, frame):
        errors = []
        if self.measurement_mapping is not None:
            frame['rtu_id'], frame['channel_id'] = 0, 0
            try:
                points, info = self.measurement_mapping.project(frame['device_results'])
                frame['mapped_points'] = points
                frame['rtu_id'] = info['rtu_ids'][0] if len(info['rtu_ids']) == 1 else 0
                store = self.manager._store_for()
                channels = sorted({int(store.get_row('fes_rtu_define', [rtu])['channel_id']) for rtu in info['rtu_ids']})
                frame['channel_id'] = channels[0] if len(channels) == 1 else 0
                with self._condition:
                    self._status.update(info, rtu_id=frame['rtu_id'], channel_id=frame['channel_id'], channel_ids=channels)
            except Exception as exc:
                frame['mapping_error'] = str(exc)
            else:
                frame.pop('mapping_error', None)
        if self.device_store is not None:
            try:
                if frame['device_results'] is None:
                    raise ValueError('缺少设备计算结果帧')
                devices = self.device_store.write(frame['device_results'], frame_id=frame['frame_id'],
                                                  stamp=frame['stamp_ms'], rtu_id=frame['rtu_id'], channel_id=frame['channel_id'])
            except Exception as exc:
                errors.append('设备结果库: ' + str(exc))
                with self._condition:
                    self._status['device_error'] = str(exc)
                    self._condition.notify_all()
            else:
                with self._condition:
                    self._status.update(written_devices=devices, devices_committed=frame['serial'],
                                        last_device_frame=frame['frame_id'], device_error='')
                    self._condition.notify_all()
        try:
            stamp, count = self._write_points(frame)
        except Exception as exc:
            errors.append('scdfe_s 点库: ' + str(exc))
            with self._condition:
                self._status['point_error'] = str(exc)
                self._condition.notify_all()
        else:
            with self._condition:
                self._status.update(points_committed=frame['serial'], last_point_frame=frame['frame_id'], point_error='')
                self._condition.notify_all()
        if errors:
            raise RuntimeError('；'.join(errors))
        return stamp, count

    def _write_points(self, frame):
        key = (frame['rtu_id'], frame['channel_id'], frame['model_name'],
               tuple((p['kind'], p['point_no'], p.get('name'), p.get('description')) for p in frame['points']))
        with self.manager.lock:
            if self.measurement_mapping is not None and frame.get('mapping_error'):
                raise ValueError(frame['mapping_error'])
            if self.measurement_mapping is None and key != self._prepared:
                self.manager.ensure(frame['points'], model_name=frame['model_name'],
                                    rtu_id=frame['rtu_id'], channel_id=frame['channel_id'])
                self._prepared = key
            store = self.manager._store_for()
            stamp = frame['stamp_ms']
            updates = []
            points = frame.get('mapped_points', frame['points'])
            for kind in ('yc', 'yx'):
                table = f'fes_{kind}_define'
                if table not in self._columns:
                    self._columns[table] = {c['eng_name'] for c in store.schema(table)['columns']}
                columns = self._columns[table]
                for point in points:
                    if point['kind'] != kind:
                        continue
                    no = int(point['point_no'])
                    value = point.get('value') if self.measurement_mapping is not None else frame['values'][kind].get(no)
                    valid = isinstance(value, (int, float)) and math.isfinite(value)
                    if kind == 'yx':
                        valid = valid and value in (0, 1)
                    quality = 0 if valid else 128
                    row = {'status': quality, 'refresh_time': stamp}
                    if valid:
                        row['value'] = int(value) if kind == 'yx' else float(value)
                    for field, item in (('raw_status', quality), ('raw_time', stamp)):
                        if field in columns:
                            row[field] = item
                    if valid and 'raw_value' in columns:
                        row['raw_value'] = row['value']
                    updates.append((table, [point.get('rtu_id', frame['rtu_id']), no], row))
            count = store.update_rows(updates)
            if self.measurement_mapping is not None:
                with self._condition:
                    self._mapped_preview = points
            return stamp, count

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending is not None or self._closing)
                if self._pending is None:
                    return
                frame, self._pending = self._pending, None
            started = time.perf_counter()
            try:
                stamp, count = self._write(frame)
            except Exception as exc:
                # Retry definition checks too, e.g. after an external table rebuild.
                self._prepared = None
                with self._condition:
                    self._status['last_error'] = str(exc)
                    self._status['failures'] += 1
                    if self._closing:
                        return
                    if self._pending is None:
                        self._pending = frame
                    self._condition.wait(timeout=.5)
            else:
                with self._condition:
                    self._status.update(committed=frame['serial'], batches=self._status['batches'] + 1,
                                        written_points=count, last_commit_ms=stamp,
                                        last_duration_ms=round((time.perf_counter() - started) * 1000, 2),
                                        last_sim_time=frame['clock'].get('sim_time'), last_error='')
                    self._condition.notify_all()
