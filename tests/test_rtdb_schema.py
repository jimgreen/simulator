from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rtdb_schema import STATE_DEFINITIONS, apply_schema, column, read_definitions, schema_api
from state_store import SimulatorStateStore
from workspace import Workspace


class EmbeddedSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'simulator.sqlite3'

    def store(self):
        store = SimulatorStateStore(Workspace(self.root), directory='state')
        self.path = store.path
        self.addCleanup(store.close)
        return store

    def rtdb_rows(self):
        # Real RTDB in a separate process: no external schema files and no
        # interference with SCADA's own top-level `core` package.
        script = '''
import json, sys
from pathlib import Path
from core.sqlite_db import SQLiteDatabase
from core.sqlite_schema import load_embedded_database
from web.sqlite_service import SQLiteManager
path = Path(sys.argv[1])
empty = path.parent / 'empty-schema'
empty.mkdir(exist_ok=True)
document = load_embedded_database(path)
db = SQLiteDatabase(path.parent, schema_directory=empty, database_file=path.name)
try:
    rows = {d.eng_name: db[d.eng_name].all() for d in document.tables}
finally:
    db.close()
manager = SQLiteManager(path.parent, empty)
try:
    manager.select_database_file({'filename': path.name})
    for name, expected in rows.items():
        actual = manager.rows(name, limit=500)
        normalize = lambda records: sorted(json.dumps(row, sort_keys=True) for row in records)
        assert normalize(actual['rows']) == normalize(expected), (name, actual, expected)
finally:
    manager.close()
assert not list(empty.glob('*.json')), 'external definitions were generated'
print(json.dumps(rows, ensure_ascii=False))
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.path)],
                                cwd=Path(__file__).resolve().parents[2] / 'rtdb',
                                text=True, encoding='utf-8', capture_output=True, timeout=30,
                                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_new_store_opens_in_rtdb_without_external_definitions(self):
        store = self.store()
        store.save('model:one', {'curve': [1, 2]}, settings={'speed': 2}, action='曲线保存', detail={'value': 3})
        rows = self.rtdb_rows()
        self.assertEqual(len(rows['simulator_state']), 2)
        self.assertEqual(rows['simulator_operations'][0]['action'], '曲线保存')
        self.assertEqual(json.loads(rows['simulator_operations'][0]['detail']), {'value': 3})
        self.assertEqual(store.status()['operation_count'], 1)

    def test_legacy_migration_preserves_rows_and_deleted_sequence(self):
        directory = self.root / 'state'
        directory.mkdir()
        path = directory / 'simulator.sqlite3'
        with closing(sqlite3.connect(path)) as con, con:
            con.execute('CREATE TABLE simulator_state(scope TEXT NOT NULL,section TEXT NOT NULL,document TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(scope,section))')
            con.execute('CREATE TABLE simulator_operations(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,scope TEXT NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL)')
            con.execute('INSERT INTO simulator_state VALUES (?,?,?,?)', ('model:old', 'svg', '"中文图形"', 'before'))
            con.execute("INSERT INTO simulator_operations VALUES (42,'before','model:old','old','{}')")
            con.execute("INSERT INTO simulator_operations VALUES (100,'before','model:old','deleted','{}')")
            con.execute('DELETE FROM simulator_operations WHERE id=100')
        store = self.store()
        self.assertEqual(store.load('model:old'), {'svg': '中文图形'})
        store.save('model:old', {}, action='next')
        self.assertEqual([r['id'] for r in store.operations()], [101, 42])
        self.assertEqual(self.rtdb_rows()['simulator_state'][0]['updated_at'], 'before')

    def test_create_and_alter_with_reorder_defaults_and_labels(self):
        store = self.store()
        store.save('one', {'speed': 3}, action='first')
        definition = deepcopy(STATE_DEFINITIONS[0])
        definition['head']['chn_name'] = '新的中文名称'
        definition['columns'].reverse()
        definition['columns'].append({**column('note', '备注'), 'default_value': '默认值'})
        definition['indexes'] = [['updated_at']]
        extra = {'head': {'eng_name': 'scenarios', 'chn_name': '场景'},
                 'columns': [column('id', '编号', 'int', primary=True), column('name', '名称')]}
        store.update_schema([definition, extra])
        self.assertEqual(store.load('one'), {'speed': 3})
        store.save('one', {'speed': 4, 'new': True}, action='second')
        rows = self.rtdb_rows()
        self.assertEqual([r['note'] for r in rows['simulator_state']], ['默认值', '默认值'])
        self.assertEqual(rows['scenarios'], [])
        with closing(sqlite3.connect(self.path)) as con:
            defs = read_definitions(con, self.path)
            self.assertEqual(defs['simulator_state'].chn_name, '新的中文名称')
            self.assertEqual(con.execute('SELECT row_count FROM rtdb_metadata_simulator_state').fetchone()[0], 2)
        # Initialization must retain extra fields and altered column order.
        reopened = SimulatorStateStore(Workspace(self.root), 'state')
        try:
            self.assertEqual(reopened.load('one'), {'speed': 4, 'new': True})
        finally:
            reopened.close()

    def test_metadata_write_failure_rolls_back_ddl_and_data(self):
        store = self.store()
        store.save('one', {'value': 'keep'})
        definition = deepcopy(STATE_DEFINITIONS[0])
        definition['columns'].append(column('note', '备注'))
        api = schema_api()[1]
        with patch.object(api, 'write_embedded_definition', side_effect=RuntimeError('injected')):
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                store.update_schema([definition])
        self.assertEqual(store.load('one'), {'value': 'keep'})
        self.assertNotIn('note', self.rtdb_rows()['simulator_state'][0])

    def test_invalid_type_change_and_duplicate_keys_roll_back_all_tables(self):
        with closing(sqlite3.connect(self.path)) as con:
            original = {'head': {'eng_name': 'sample', 'chn_name': '样本'},
                        'columns': [column('id', '编号', 'int', primary=True), column('value', '值')]}
            apply_schema(con, self.path, [original])
            con.executemany('INSERT INTO rtdb_data_sample(c0,c1) VALUES (?,?)', [(1, 'same'), (2, 'same')])
            con.commit()
            invalid = deepcopy(original)
            invalid['columns'][1]['data_type'] = 'int'
            another = deepcopy(original)
            another['head']['eng_name'] = 'new_table'
            with self.assertRaises(ValueError):
                apply_schema(con, self.path, [another, invalid])
            self.assertNotIn('new_table', read_definitions(con, self.path))
            duplicate = deepcopy(original)
            duplicate['columns'][0]['primary_key'] = False
            duplicate['columns'][1]['primary_key'] = True
            with self.assertRaises(sqlite3.IntegrityError):
                apply_schema(con, self.path, [duplicate])
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(con.execute('SELECT row_count FROM rtdb_metadata_sample').fetchone()[0], 2)
        self.assertEqual(len(self.rtdb_rows()['sample']), 2)

    def test_required_state_fields_cannot_be_removed(self):
        store = self.store()
        invalid = deepcopy(STATE_DEFINITIONS[0])
        invalid['columns'].pop()
        with self.assertRaises(ValueError):
            store.update_schema([invalid])
        store.save('one', {'ok': True})
        self.assertEqual(store.load('one'), {'ok': True})

    def test_row_counts_follow_deletes_and_reopen(self):
        store = self.store()
        store.save('one', {'a': 1, 'b': 2}, action='first')
        store.save('one', {'a': 3}, action='second')
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('DELETE FROM rtdb_data_simulator_operations WHERE c0=1')
            self.assertEqual(con.execute('SELECT row_count FROM rtdb_metadata_simulator_operations').fetchone()[0], 1)
            self.assertEqual(con.execute('SELECT row_count FROM rtdb_metadata_simulator_state').fetchone()[0], 2)
            for name, definition in read_definitions(con, self.path).items():
                fingerprint = schema_api()[1].definition_fingerprint(definition)
                self.assertEqual(con.execute('SELECT fingerprint FROM rtdb_schema_tables WHERE table_name=?', (name,)).fetchone()[0], fingerprint)
                self.assertEqual(con.execute('SELECT fingerprint FROM rtdb_metadata_' + name).fetchone()[0], fingerprint)
        self.assertEqual([row['id'] for row in self.rtdb_rows()['simulator_operations']], [2])


if __name__ == '__main__':
    unittest.main()
