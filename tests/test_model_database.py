import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch

from model_database import DEFAULT_MODEL_DIRECTORY, ModelDatabaseSource, read_model_database
from server import AppServer, Handler, SimulatorApplication, parse_args
from workspace import Workspace


def make_database(directory, name='SQL grid', embedded=False):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'devices.sqlite3'
    tables = {
        'Model': (['name', 'p_unit'], [(name, 'kW')]),
        'ACNode': (['idx', 'name', 'run_stat'], [(1, 'bus', 1)]),
        'ACGenerator': (['idx', 'name', 'node', 'run_stat', 'rated_capacity', 'p_set'], [(1, 'source', 1, 1, 100, 20)]),
        'ACStorageGen': (['idx', 'idx_acgenerator', 'energy_capacity', 'charge_discharge_efficiency', 'soc'], [(1, 1, 200, .9, .5)]),
    }
    with closing(sqlite3.connect(path)) as con:
        if embedded:
            con.execute('CREATE TABLE rtdb_schema_tables(table_name TEXT, ordinal INTEGER)')
            con.execute('CREATE TABLE rtdb_schema_columns(table_name TEXT, ordinal INTEGER, eng_name TEXT)')
        for ordinal, (table, (columns, rows)) in enumerate(tables.items()):
            if embedded:
                con.execute('INSERT INTO rtdb_schema_tables VALUES (?,?)', (table, ordinal))
                con.executemany('INSERT INTO rtdb_schema_columns VALUES (?,?,?)', [(table, i, col) for i, col in enumerate(columns)])
                physical = 'rtdb_data_' + table
                con.execute('CREATE TABLE ' + physical + '(_pos INTEGER, ' + ','.join('c'+str(i) for i in range(len(columns))) + ')')
                con.executemany('INSERT INTO ' + physical + ' VALUES (' + ','.join('?' for _ in range(len(columns)+1)) + ')', [(i, *row) for i, row in enumerate(rows)])
            else:
                con.execute('CREATE TABLE ' + table + '(' + ','.join(columns) + ')')
                con.executemany('INSERT INTO ' + table + ' VALUES (' + ','.join('?' for _ in columns) + ')', rows)
        con.commit()
    return path


class ModelDatabaseTests(unittest.TestCase):
    def test_plain_and_embedded_schema_produce_same_model_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace = Workspace(root)
            models = []
            for layout in ('plain', 'embedded'):
                path = make_database(root / layout, embedded=layout == 'embedded')
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                model, info = read_model_database(workspace, layout)
                models.append(model)
                self.assertEqual(info['table_count'], 4)
                self.assertEqual(info['row_count'], 4)
                self.assertEqual(next(d for d in model['devices'] if d['id'] == 'ACGenerator:1')['type'], 'battery')
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            self.assertEqual(sorted(models[0]['devices'], key=lambda d: d['id']), sorted(models[1]['devices'], key=lambda d: d['id']))

    def test_missing_corrupt_wrong_schema_and_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace = Workspace(root)
            for name in ('missing', 'corrupt', 'wrong'):
                (root / name).mkdir()
            (root / 'corrupt/devices.sqlite3').write_bytes(b'not a database')
            with closing(sqlite3.connect(root / 'wrong/devices.sqlite3')) as con:
                con.execute('CREATE TABLE unrelated(id INTEGER)')
                con.commit()
            for directory in ('missing', 'corrupt', 'wrong', '../outside', str(root)):
                with self.subTest(directory=directory), self.assertRaises(ValueError):
                    read_model_database(workspace, directory)
            self.assertFalse((root / 'missing/devices.sqlite3').exists())

    def test_default_and_saved_directory_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace = Workspace(root)
            make_database(root / DEFAULT_MODEL_DIRECTORY)
            make_database(root / 'another')
            source = ModelDatabaseSource(workspace, config_file=root / 'settings.json')
            self.assertEqual(source.prepare()[1]['directory'], DEFAULT_MODEL_DIRECTORY)
            source.remember('another')
            self.assertEqual(ModelDatabaseSource(workspace, config_file=root / 'settings.json').directory, 'another')
            explicit = ModelDatabaseSource(workspace, directory=root / DEFAULT_MODEL_DIRECTORY, config_file=root / 'settings.json')
            self.assertEqual(explicit.directory, DEFAULT_MODEL_DIRECTORY)

    def test_missing_database_stops_startup_without_demo_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / DEFAULT_MODEL_DIRECTORY).mkdir(parents=True)
            args = parse_args(['--workspace-root', str(root), '--no-iec104'])
            with self.assertRaises(ValueError):
                SimulatorApplication(args, model_config=root / 'settings.json')
            self.assertFalse((root / DEFAULT_MODEL_DIRECTORY / 'devices.sqlite3').exists())


class ModelSourceAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_database(self.root / DEFAULT_MODEL_DIRECTORY, name='Default SQL')
        make_database(self.root / 'other', name='Other SQL', embedded=True)
        args = parse_args(['--workspace-root', str(self.root), '--no-iec104'])
        self.config = self.root / 'config/model_source.json'
        self.app = SimulatorApplication(args, model_config=self.config)
        self.server = AppServer(('127.0.0.1', 0), Handler)
        self.server.app = self.app
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.app.close()
        self.temp.cleanup()

    def request(self, path, body=None):
        request = Request(self.base+path, data=None if body is None else json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    def test_startup_check_switch_reload_and_persistence(self):
        self.assertEqual(self.app.twin.model['name'], 'Default SQL')
        source = self.request('/api/model/source')['source']
        self.assertEqual(source['filename'], 'devices.sqlite3')
        self.request('/api/model/source/validate', {'directory': 'other'})
        self.assertEqual(self.app.twin.model['name'], 'Default SQL')
        self.request('/api/model/source', {'directory': 'other'})
        self.assertEqual(self.app.twin.model['name'], 'Other SQL')
        self.assertEqual(self.app.state_store.load('global')['model_directory'], 'other')
        with closing(sqlite3.connect(self.root / 'other/devices.sqlite3')) as con:
            con.execute("UPDATE rtdb_data_Model SET c0='Updated SQL'")
            con.commit()
        self.request('/api/model/source', {'directory': 'other'})
        self.assertEqual(self.app.twin.model['name'], 'Updated SQL')
        restarted = SimulatorApplication(parse_args(['--workspace-root', str(self.root), '--no-iec104']), model_config=self.config)
        try:
            self.assertEqual(restarted.twin.model['name'], 'Updated SQL')
            self.assertEqual(restarted.model_source.directory, 'other')
        finally:
            restarted.close()

    def test_failed_switch_preserves_current_model_and_config(self):
        self.request('/api/model/source', {'directory': 'other'})
        before = self.app.twin.model_summary()
        config = self.app.state_store.load('global')
        with self.assertRaises(HTTPError):
            self.request('/api/model/source', {'directory': 'missing'})
        self.assertEqual(self.app.twin.model_summary(), before)
        self.assertEqual(self.app.state_store.load('global'), config)

    def test_runtime_grid_source_cannot_be_replaced_by_file_upload(self):
        with self.assertRaises(HTTPError) as error:
            self.request('/api/model/import', {'model': {'name': 'replacement'}})
        self.assertEqual(error.exception.code, 400)
        self.assertEqual(self.app.twin.model['name'], 'Default SQL')

    def test_config_write_failure_preserves_active_model(self):
        before = self.app.twin.model_summary()
        with patch.object(self.app.state_store, 'save', side_effect=OSError('read-only settings')):
            with self.assertRaises(HTTPError):
                self.request('/api/model/source', {'directory': 'other'})
        self.assertEqual(self.app.twin.model_summary(), before)
        self.assertFalse(self.config.exists())

    def test_database_browser_and_fixed_filename_contract(self):
        (self.root / 'other/unrelated.sqlite3').write_bytes(b'ignored')
        listing = self.request('/api/workspace?directory=other&kind=database')
        self.assertEqual([e['name'] for e in listing['entries']], ['devices.sqlite3'])
        with self.assertRaises(HTTPError):
            self.request('/api/model/source', {'directory': 'other', 'filename': 'unrelated.sqlite3'})
        self.assertEqual(self.app.twin.model['name'], 'Default SQL')

    def test_bridge_failure_reports_committed_model_and_error_separately(self):
        bridge = Mock()
        bridge.rebuild.side_effect = RuntimeError('port busy')
        with patch.object(self.app, 'bridge', bridge):
            result = self.request('/api/model/source', {'directory': 'other'})
        self.assertEqual(result['model']['name'], 'Other SQL')
        self.assertEqual(result['iec104_error'], 'port busy')
        self.assertEqual(self.app.state_store.load('global')['model_directory'], 'other')


if __name__ == '__main__':
    unittest.main()
