from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from device_results import DeviceResultStore
from digital_twin import DigitalTwin
from rtdb_schema import read_definitions


def snapshot():
    twin = DigitalTwin(model={'name': 'results-test', 'devices': [
        {'id': 'ACGenerator:1', 'idx': '1', 'block': 'ACGenerator', 'name': 'gen',
         'type': 'diesel', 'rated_kw': 100, 'p_set_kw': 15},
        {'id': 'ACBreak:1', 'idx': '1', 'block': 'ACBreak', 'name': 'switch', 'type': 'switch'},
    ]})
    twin.command_clock('pause')
    return twin.snapshot(profile='devices', history_limit=0)


class DeviceResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'devices.sqlite3'
        self.store = DeviceResultStore(self.path, workspace_root=self.root)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def write(self, data=None, frame='session:1', stamp=1234):
        data = data or snapshot()
        return self.store.write(data, frame_id=frame, stamp=stamp, rtu_id=104, channel_id=104)

    def rows(self, table):
        with closing(sqlite3.connect(self.path)) as connection:
            definition = read_definitions(connection, self.path)[table]
            return [dict(zip(definition.column_names, row[1:])) for row in
                    connection.execute('SELECT * FROM rtdb_data_' + table)]

    def test_device_tables_and_metadata_match_computed_frame(self):
        self.assertEqual(self.write(), 2)
        row = self.rows('ACGenerator')[0]
        self.assertEqual(row['p_kw'], 15)
        self.assertEqual(row['device_id'], 'ACGenerator:1')
        self.assertEqual(row['p_quality'], 0)
        self.assertEqual(row['frame_id'], 'session:1')
        self.assertEqual(row['refresh_time'], 1234)
        switch = self.rows('ACBreak')[0]
        self.assertIsNone(switch['p_kw'])
        self.assertEqual(switch['p_quality'], 128)
        self.assertEqual(self.rows('SimulationFrame')[0]['device_count'], 2)
        self.assertEqual(self.rows('SimulationFrame')[0]['calculation'], 'embedded-balance-power-flow')

    def test_replacement_removes_stale_devices_and_updates_without_duplicates(self):
        self.write()
        data = snapshot()
        data['devices'] = data['devices'][:1]
        data['devices'][0]['p_kw'] = 22
        self.write(data, frame='session:2', stamp=5678)
        self.assertEqual(self.rows('ACBreak'), [])
        self.assertEqual(len(self.rows('ACGenerator')), 1)
        self.assertEqual(self.rows('ACGenerator')[0]['p_kw'], 22)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT row_count FROM rtdb_metadata_ACBreak').fetchone()[0], 0)

    def test_failed_write_rolls_back_all_device_tables_and_frame(self):
        self.write()
        before = self.rows('ACGenerator')
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("CREATE TRIGGER fail_frame BEFORE UPDATE ON rtdb_data_SimulationFrame BEGIN SELECT RAISE(ABORT,'disk failure'); END")
        data = snapshot()
        data['devices'][0]['p_kw'] = 99
        with self.assertRaises(sqlite3.DatabaseError):
            self.write(data, frame='session:2')
        self.assertEqual(self.rows('ACGenerator'), before)
        self.assertEqual(self.rows('SimulationFrame')[0]['frame_id'], 'session:1')

    def test_rtdb_opens_device_tables_without_external_definitions(self):
        self.write()
        script = '''
import json,sys
from pathlib import Path
from core.sqlite_db import SQLiteDatabase
from core.sqlite_schema import load_embedded_database
path=Path(sys.argv[1]); empty=path.parent/'schema'; empty.mkdir()
definition=load_embedded_database(path)
db=SQLiteDatabase(path.parent,schema_directory=empty,database_file=path.name)
try:
 result={t.eng_name:db[t.eng_name].all() for t in definition.tables}
 print(json.dumps(result))
finally: db.close()
assert not list(empty.glob('*.json'))
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.path)],
                                cwd=Path(__file__).resolve().parents[2] / 'rtdb', capture_output=True,
                                text=True, timeout=30, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['ACGenerator'][0]['p_kw'], 15)

    def test_existing_non_result_database_is_never_overwritten(self):
        with closing(sqlite3.connect(self.path)) as con:
            con.execute('CREATE TABLE important(value TEXT)')
            con.execute("INSERT INTO important VALUES('keep')")
            con.commit()
        with self.assertRaises(ValueError):
            self.write()
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT value FROM important').fetchone()[0], 'keep')


if __name__ == '__main__':
    unittest.main()
