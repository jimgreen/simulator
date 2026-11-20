import base64
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from model_database import DEFAULT_MODEL_DIRECTORY
from server import AppServer, Handler, SimulatorApplication, parse_args
from test_model_database import make_database


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_database(self.root / DEFAULT_MODEL_DIRECTORY)
        make_database(self.root / 'alternate', name='Alternate')
        self.args = parse_args(['--workspace-root', str(self.root), '--no-iec104'])
        self.start()

    def start(self):
        self.app = SimulatorApplication(self.args, model_config=self.root / 'legacy.json')
        self.server = AppServer(('127.0.0.1', 0), Handler)
        self.server.app = self.app
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.app.close()

    def tearDown(self):
        self.stop()
        self.temp.cleanup()

    def request(self, path, body=None):
        req = Request(self.url + path, None if body is None else json.dumps(body).encode(), {'Content-Type': 'application/json'})
        with urlopen(req, timeout=10) as response:
            return json.load(response)

    def test_all_runtime_edits_survive_restart_and_model_file_is_unchanged(self):
        business = self.root / DEFAULT_MODEL_DIRECTORY / 'devices.sqlite3'
        original = business.read_bytes()
        self.request('/api/clock', {'action': 'pause'})
        self.request('/api/clock', {'action': 'speed', 'value': 3})
        self.request('/api/clock', {'action': 'seek', 'value': '12:30'})
        self.request('/api/curves', {'weather': [{'minute': 0, 'wind_speed_mps': 9, 'air_temp_c': -3}], 'battery': [{'minute': 0, 'battery_kw': 12}]})
        self.request('/api/boundary/import', {'filename': 'weather.csv', 'data_base64': base64.b64encode(b'time,temperature\n00:00,-8').decode()})
        self.request('/api/devices/actions', {'actions': [{'device_id': 'ACGenerator:1', 'action': 'set_power', 'value': 15}]})
        topology = deepcopy(self.app.twin.model['topology'])
        topology['nodes'][0]['name'] = 'Edited bus'
        self.request('/api/topology', topology)
        self.request('/api/scenario', {'name': 'island'})
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><text x="10" y="20">Grid</text></svg>'
        self.request('/api/diagram/import', {'filename': 'grid.svg', 'data_base64': base64.b64encode(svg.encode()).decode()})
        self.request('/api/clock', {'action': 'step'})
        before = self.app.twin.export_persistent_state()
        self.assertLess(before['runtime']['storage_soc']['ACGenerator:1'], .5)
        durable = self.app.state_store.load(self.app._scope)
        self.assertEqual(before, {key: durable[key] for key in before})
        self.stop()
        self.start()
        after = self.app.twin.export_persistent_state()
        self.assertEqual(before, after)
        self.assertEqual(original, business.read_bytes())
        status = self.request('/api/storage')
        self.assertEqual(status['database'], 'simulation/qinling/sqldb/simulator/simulator.sqlite3')
        self.assertTrue(status['restored'])
        self.assertGreaterEqual(status['operation_count'], 10)

    def test_failed_sql_write_rolls_back_runtime_and_does_not_publish(self):
        self.request('/api/clock', {'action': 'pause'})
        before = self.app.twin.export_persistent_state()
        with patch.object(self.app.state_store, 'save', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(HTTPError):
                self.request('/api/devices/state', {'device_id': 'ACGenerator:1', 'running': False})
        self.assertEqual(before, self.app.twin.export_persistent_state())

    def test_all_input_categories_are_committed_before_response(self):
        self.request('/api/clock', {'action': 'pause'})
        curves = {
            'weather': [{'minute': 0, 'wind_speed_mps': 8.5, 'solar_irradiance_w_m2': 650,
                         'air_temp_c': -16, 'load_kw': 120}],
            'load': [{'minute': 0, 'load_kw': 150}, {'minute': 720, 'load_kw': 230}],
            'diesel': [{'minute': 0, 'diesel_kw': 70}],
            'battery': [{'minute': 0, 'battery_kw': -25}],
            'source@ACGenerator@source': [{'minute': 0, 'value': 17}],
        }

        def disk_sections():
            # Separate read-only connection proves durability, not an in-memory cache.
            path = self.root / 'simulation/qinling/sqldb/simulator/simulator.sqlite3'
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
                return {row[0]: json.loads(row[1]) for row in connection.execute(
                    'SELECT c1,c2 FROM rtdb_data_simulator_state WHERE c0=?', (self.app._scope,))}

        result = self.request('/api/curves', {'curves': curves})
        self.assertEqual(result['persistence'], {'saved': True, 'database': 'simulation/qinling/sqldb/simulator/simulator.sqlite3'})
        self.assertEqual(disk_sections()['model']['curves'], result['curves'])
        for key in curves:
            self.assertTrue(disk_sections()['model']['curves'][key], key)
        csv = b'time,wind_speed_mps,solar_irradiance_w_m2,air_temp_c,load_kw\n00:00,11,500,-8,210\n12:00,14,750,-2,260\n'
        imported = self.request('/api/boundary/import', {'filename': 'boundary.csv', 'data_base64': base64.b64encode(csv).decode()})
        self.assertEqual(disk_sections()['model']['curves'], imported['curves'])
        self.request('/api/clock', {'action': 'speed', 'value': 4})
        self.request('/api/clock', {'action': 'seek', 'value': '10:15'})
        saved = disk_sections()
        self.assertEqual(saved['runtime']['speed'], 4)
        self.assertEqual(saved['runtime']['sim_seconds'], 36900)
        self.assertEqual(saved['runtime']['step_seconds'], self.app.twin.step_seconds)
        # Suppress shutdown persistence: successful Web responses must suffice.
        with patch.object(self.app, '_persist'):
            self.stop()
        self.start()
        self.assertEqual(self.app.twin.curves, saved['model']['curves'])
        self.assertEqual(self.app.twin.export_persistent_state()['runtime'], saved['runtime'])

    def test_switching_back_restores_saved_curves_and_parameters(self):
        self.request('/api/clock', {'action': 'pause'})
        self.request('/api/clock', {'action': 'speed', 'value': 3})
        first = self.request('/api/curves', {'load': [{'minute': 0, 'load_kw': 246}]})['curves']
        self.request('/api/model/source', {'directory': 'alternate'})
        self.request('/api/clock', {'action': 'speed', 'value': 5})
        second = self.request('/api/curves', {'weather': [{'minute': 0, 'wind_speed_mps': 17}]})['curves']
        revision = self.app.twin._model_revision
        self.request('/api/model/source', {'directory': DEFAULT_MODEL_DIRECTORY})
        self.assertEqual(self.app.twin.curves, first)
        self.assertEqual(self.app.twin.speed, 3)
        self.assertGreater(self.app.twin._model_revision, revision)
        self.request('/api/model/source', {'directory': 'alternate'})
        self.assertEqual(self.app.twin.curves, second)
        self.assertEqual(self.app.twin.speed, 5)
        self.request('/api/model/source', {'directory': 'alternate'})
        self.assertEqual(self.app.twin.curves, second)

    def test_database_directory_and_ui_preferences_are_saved_in_sqlite(self):
        self.request('/api/model/source', {'directory': 'alternate'})
        self.request('/api/preferences', {'page': 'devices', 'values': {'devicePageSize': '24', 'deviceTypeFilter': 'battery'}})
        self.request('/api/preferences', {'page': 'workspace', 'values': {'directory': 'alternate', 'kind': 'database'}})
        self.stop()
        self.start()
        self.assertEqual(self.app.model_source.directory, 'alternate')
        self.assertEqual(self.request('/api/preferences?page=devices')['values']['devicePageSize'], '24')
        self.assertEqual(self.request('/api/preferences?page=workspace')['values'], {'directory': 'alternate', 'kind': 'database'})
        self.assertFalse((self.root / 'legacy.json').exists())

    def test_no_replay_of_single_step_or_commands_on_restart(self):
        self.request('/api/clock', {'action': 'pause'})
        self.request('/api/clock', {'action': 'step'})
        seconds = self.app.twin.sim_seconds
        self.stop()
        self.start()
        self.assertEqual(self.app.twin.sim_seconds, seconds)
        self.assertFalse(self.app.twin.running)

    def test_changed_business_model_does_not_restore_old_device_overrides(self):
        self.request('/api/devices/state', {'device_id': 'ACGenerator:1', 'running': False})
        self.stop()
        with closing(sqlite3.connect(self.root / DEFAULT_MODEL_DIRECTORY / 'devices.sqlite3')) as con:
            con.execute("UPDATE Model SET name='Updated business model'")
            con.commit()
        self.start()
        self.assertEqual(self.app.twin.model['name'], 'Updated business model')
        self.assertTrue(self.app.twin._device_index['ACGenerator:1']['run'])

    def test_scdfe_generation_is_saved_before_external_delivery(self):
        def deliver(points, **options):
            saved = self.app.state_store.load(self.app._scope)['point_generation']
            self.assertEqual(saved['status'], 'pending')
            self.assertEqual(saved['points'], points)
            self.assertEqual(saved['options'], options)
            return {'total': len(points)}
        with patch.object(self.app.point_tables, 'generate', side_effect=deliver):
            result = self.request('/api/scdfe/points/generate', {'replace': True})
        self.assertGreater(result['total'], 0)
        self.assertEqual(self.app.state_store.load(self.app._scope)['point_generation']['status'], 'delivered')

    def test_stop_iec104_is_saved_and_storage_failure_never_publishes(self):
        bridge = Mock()
        bridge.stop.return_value = {'running': False}
        with patch.object(self.app, 'bridge', bridge):
            self.request('/api/iec104/stop', {})
            self.assertFalse(self.app.state_store.load('global')['iec104_running'])
            with patch.object(self.app.state_store, 'save', side_effect=sqlite3.OperationalError('disk full')):
                with self.assertRaises(HTTPError):
                    self.request('/api/devices/state', {'device_id': 'ACGenerator:1', 'running': False})
            bridge.publish.assert_not_called()

    def test_sql_transaction_rolls_back_all_sections_when_journal_write_fails(self):
        store = self.app.state_store
        before = store.load('test')
        store._con.execute("CREATE TRIGGER reject_operation BEFORE INSERT ON rtdb_data_simulator_operations BEGIN SELECT RAISE(ABORT,'injected write failure'); END")
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                store.save('test', {'one': 1, 'two': 2}, action='test')
            self.assertEqual(store.load('test'), before)
        finally:
            store._con.execute('DROP TRIGGER reject_operation')


if __name__ == '__main__':
    unittest.main()
