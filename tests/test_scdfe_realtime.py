from pathlib import Path
import tempfile
import unittest
import sqlite3
from contextlib import closing
from unittest.mock import patch

from scdfe_points import ScdfePointTableManager
from scdfe_realtime import ScdfeRealtimeWriter
from server import SimulatorApplication, parse_args
from test_model_database import make_database
from rtdb_schema import read_definitions


POINTS = [dict(kind=kind, point_no=1, name=kind, description=kind)
          for kind in ('yc', 'yx', 'yk', 'yt')]


class RealtimeDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = ScdfePointTableManager(db_path=Path(self.temp.name) / 'scdfe_s.sqlite3',
                                             workspace_root=self.temp.name)
        self.writer = ScdfeRealtimeWriter(self.manager)

    def tearDown(self):
        self.writer.close()
        self.manager.close()
        self.temp.cleanup()

    def submit(self, yc=12.5, yx=True):
        return self.writer.submit(points=POINTS, model_name='test', rtu_id=104, channel_id=104,
                                  values={'yc': {1: yc}, 'yx': {1: yx}, 'yk': {1: False}, 'yt': {1: 0}},
                                  clock={'seq': 8, 'sim_time': '12:30:00'})

    def row(self, kind, rtu=104):
        return self.manager._store_for().get_row('fes_' + kind + '_define', [rtu, 1])

    def test_values_quality_timestamps_commands_and_other_rtu(self):
        self.manager.generate(POINTS, model_name='other', rtu_id=1, channel_id=1)
        other = self.row('yc', 1)
        self.assertTrue(self.writer.wait_for(self.submit(), 15))
        store = self.manager._store_for()
        store.update_row('fes_yk_define', [104, 1], {'value': 1, 'status': 3})
        command = self.row('yk')
        self.assertTrue(self.writer.wait_for(self.submit(24.5, False), 5))
        yc, yx = self.row('yc'), self.row('yx')
        self.assertEqual(yc['value'], 24.5)
        self.assertEqual(yx['value'], 0)
        self.assertEqual(yc['status'], 0)
        self.assertEqual(yc['refresh_time'], yx['refresh_time'])
        self.assertGreater(yc['refresh_time'], 0)
        self.assertEqual(yc['raw_value'], 24.5)
        self.assertEqual(yc['raw_time'], yc['refresh_time'])
        self.assertEqual(self.row('yk'), command)
        self.assertEqual(self.row('yc', 1), other)
        self.assertEqual(self.writer.status()['written_points'], 2)

    def test_invalid_retains_value_and_recovers(self):
        self.assertTrue(self.writer.wait_for(self.submit(), 15))
        self.assertTrue(self.writer.wait_for(self.submit(float('nan'), None), 5))
        self.assertEqual(self.row('yc')['value'], 12.5)
        self.assertEqual(self.row('yx')['value'], 1)
        self.assertEqual(self.row('yc')['status'], 128)
        self.assertEqual(self.row('yx')['status'], 128)
        self.assertEqual(self.row('yc')['raw_status'], 128)
        self.assertTrue(self.writer.wait_for(self.submit(9, False), 5))
        self.assertEqual(self.row('yc')['status'], 0)

    def test_same_millisecond_frames_keep_shared_sample_timestamps(self):
        with patch('scdfe_realtime.time.time_ns', return_value=1_700_000_000_000_000_000) as clock:
            self.assertTrue(self.writer.wait_for(self.submit(), 15))
            previous = self.row('yc')['refresh_time']
            for value in (24.5, 36.5):
                self.assertTrue(self.writer.wait_for(self.submit(value, False), 5))
                for kind in ('yc', 'yx'):
                    row = self.row(kind)
                    self.assertEqual(row['refresh_time'], previous + 1)
                    if kind == 'yc':
                        self.assertEqual(row['raw_time'], row['refresh_time'])
                    self.assertEqual(row['refresh_time'], self.writer.status()['last_commit_ms'])
                previous += 1
                clock.return_value -= 1_000_000_000  # A wall-clock correction must not reuse a stamp.

    def test_failed_atomic_batch_retries_latest_frame(self):
        self.assertTrue(self.writer.wait_for(self.submit(), 15))
        store = self.manager._store_for()
        original = store.update_rows
        with patch.object(store, 'update_rows', side_effect=OSError('database locked')):
            seq = self.submit(90)
            self.assertFalse(self.writer.wait_for(seq, .2))
            self.assertEqual(self.row('yc')['value'], 12.5)
            seq = self.submit(99)
        self.assertTrue(self.writer.wait_for(seq, 5))
        self.assertEqual(self.row('yc')['value'], 99)
        self.assertFalse(self.writer.status()['last_error'])
        before = self.row('yc')
        with self.assertRaises(Exception):
            original([('fes_yc_define', [104, 1], {'value': 999}),
                      ('fes_yx_define', [104, 999], {'value': 1})])
        self.assertEqual(self.row('yc'), before)

    def test_restart_preserves_commands_and_existing_mapping(self):
        self.assertTrue(self.writer.wait_for(self.submit(), 15))
        self.manager._store_for().update_row('fes_yt_define', [104, 1], {'value': 45})
        previous = self.row('yt')
        self.writer.close()
        self.writer = ScdfeRealtimeWriter(self.manager)
        with patch.object(self.manager, '_generate', side_effect=AssertionError('unnecessary regeneration')):
            self.assertTrue(self.writer.wait_for(self.submit(), 5))
        self.assertEqual(self.row('yt'), previous)

    def test_invalid_model_definition_does_not_erase_previous_points(self):
        self.assertTrue(self.writer.wait_for(self.submit(), 15))
        before = self.row('yc')
        invalid = [dict(p, data_type=13) if p['kind'] == 'yt' else p for p in POINTS]
        with self.assertRaises(Exception):
            self.manager.generate(invalid, model_name='invalid')
        self.assertEqual(self.row('yc'), before)


class ApplicationRealtimeTests(unittest.TestCase):
    def test_paused_operation_and_step_write_with_listener_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_database(root / 'simulation/qinling/sqldb/model')
            app = SimulatorApplication(parse_args(['--workspace-root', directory, '--no-iec104']),
                                       model_config=root / 'legacy.json')
            try:
                app.mutate('/api/clock', {'action': 'pause'}, lambda: app.twin.command_clock('pause'))
                self.assertIsNone(app.bridge)
                result = app.mutate('/api/device/action', {}, lambda: app.twin.operate_device('ACGenerator:1', 'stop'))
                self.assertTrue(app.database_writer.wait_for(result['database_submission'], 15))
                point = next(p for p in app.twin.points() if p['name'] == 'ACGenerator:1_running')
                row = app.point_tables._store_for().get_row('fes_yx_define', [104, point['point_no']])
                self.assertEqual(row['value'], 0)
                status = app.database_writer.status()
                self.assertEqual(status['last_device_frame'], status['last_point_frame'])
                with closing(sqlite3.connect(app.device_results.path)) as connection:
                    definition = read_definitions(connection, app.device_results.path)['ACGenerator']
                    values = connection.execute('SELECT * FROM rtdb_data_ACGenerator').fetchone()[1:]
                    device = dict(zip(definition.column_names, values))
                    self.assertEqual(device['run_stat'], row['value'])
                    self.assertEqual(device['refresh_time'], row['refresh_time'])
                    self.assertEqual(device['frame_id'], status['last_point_frame'])
                result = app.mutate('/api/clock', {'action': 'step'}, lambda: app.twin.command_clock('step'))
                self.assertTrue(app.database_writer.wait_for(result['database_submission'], 5))
                self.assertEqual(app.database_writer.status()['last_sim_time'], app.twin.clock()['sim_time'])
                submitted = app.database_writer.status()['submitted']
                with patch.object(app, '_persist', side_effect=OSError('disk full')):
                    with self.assertRaises(OSError):
                        app.mutate('/api/device/action', {}, lambda: app.twin.operate_device('ACGenerator:1', 'start'))
                self.assertEqual(app.database_writer.status()['submitted'], submitted)
            finally:
                app.close()

    def test_two_database_failures_are_isolated_and_retry_latest_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_database(root / 'simulation/qinling/sqldb/model')
            app = SimulatorApplication(parse_args(['--workspace-root', directory, '--no-iec104']),
                                       model_config=root / 'legacy.json')
            try:
                app.mutate('/api/clock', {}, lambda: app.twin.command_clock('pause'))
                writer = app.database_writer
                self.assertTrue(writer.wait_for(writer.status()['submitted'], 15))
                store = app.point_tables._store_for()
                for target, method, good_counter, error in (
                    (store, 'update_rows', 'devices_committed', 'point_error'),
                    (app.device_results, 'write', 'points_committed', 'device_error'),
                ):
                    with patch.object(target, method, side_effect=OSError('locked target')):
                        result = app.mutate('/api/clock', {}, lambda: app.twin.command_clock('step'))
                        serial = result['database_submission']
                        with writer._condition:
                            self.assertTrue(writer._condition.wait_for(
                                lambda: writer.status()[good_counter] >= serial and writer.status()[error], 3))
                        self.assertLess(writer.status()['committed'], serial)
                    self.assertTrue(writer.wait_for(serial, 5))
                    self.assertEqual(writer.status()['last_device_frame'], writer.status()['last_point_frame'])
            finally:
                app.close()


if __name__ == '__main__':
    unittest.main()
