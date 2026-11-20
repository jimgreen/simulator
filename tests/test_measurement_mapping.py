from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from measurement_mapping import MeasurementMapping
from scdfe_points import ScdfePointTableManager
from scdfe_realtime import ScdfeRealtimeWriter
from test_device_results import snapshot


def catalog(path):
    with closing(sqlite3.connect(path)) as con:
        con.executescript('''
            CREATE TABLE device(device_id INTEGER PRIMARY KEY,model_table TEXT,model_idx INTEGER,name TEXT,active INTEGER);
            CREATE TABLE device_measurement(measurement_id INTEGER PRIMARY KEY,device_id INTEGER,metric TEXT,kind TEXT,name TEXT,unit TEXT,catalog_active INTEGER);
            CREATE TABLE scada_point_mapping(measurement_id INTEGER PRIMARY KEY,rtu_id INTEGER,pnt_no INTEGER,enabled INTEGER,scale REAL,offset REAL,source_database TEXT);
            INSERT INTO device VALUES(51,'ACGenerator',1,'gen',1),(84,'ACBreak',1,'switch',1);
            INSERT INTO device_measurement VALUES(1,51,'p','yc','active','kW',1),(2,51,'q','yc','reactive','kvar',1),(3,84,'position','yx','position','',1);
            INSERT INTO scada_point_mapping VALUES(1,1,42,1,2,3,'simulation/scdfe_c.sqlite3'),(2,1,43,1,1,0,'simulation/scdfe_c.sqlite3'),(3,1,84,1,1,0,'simulation/scdfe_c.sqlite3');
        ''')


class MeasurementMappingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'devices.sqlite3'
        catalog(self.path)
        self.mapping = MeasurementMapping(self.path, workspace_root=self.root)

    def tearDown(self):
        self.mapping.close()
        self.temp.cleanup()

    def edit(self, sql):
        with closing(sqlite3.connect(self.path)) as con:
            con.execute(sql)
            con.commit()

    def test_identity_units_inverse_scale_and_unknown_measurements(self):
        points, info = self.mapping.project(snapshot())
        self.assertEqual((points[0]['rtu_id'], points[0]['point_no'], points[0]['value']), (1, 42, 6))
        self.assertEqual(points[1]['reason'], 'not_computed')
        self.assertEqual(points[2]['value'], 1)
        self.assertEqual(info['valid_points'], 2)
        self.edit("UPDATE device_measurement SET unit='MW' WHERE measurement_id=1")
        value = self.mapping.project(snapshot())[0][0]['value']
        self.assertAlmostEqual(value * 2 + 3, .015)

    def test_runtime_mapping_edits_invalidate_cache_and_bad_transforms(self):
        self.mapping.project(snapshot())
        self.edit('UPDATE scada_point_mapping SET pnt_no=99,enabled=0 WHERE measurement_id=1')
        point = self.mapping.project(snapshot())[0][0]
        # Ordering is by target point; locate the remapped measurement explicitly.
        point = next(p for p in self.mapping.project(snapshot())[0] if p['measurement_id'] == 1)
        self.assertEqual(point['point_no'], 99)
        self.assertEqual(point['reason'], 'disabled')
        self.edit('UPDATE scada_point_mapping SET enabled=1,scale=0 WHERE measurement_id=1')
        point = next(p for p in self.mapping.project(snapshot())[0] if p['measurement_id'] == 1)
        self.assertEqual(point['reason'], 'invalid_transform')
        self.edit('UPDATE scada_point_mapping SET pnt_no=43 WHERE measurement_id=1')
        with self.assertRaisesRegex(ValueError, '同一发布点'):
            self.mapping.project(snapshot())

    def test_publishes_existing_mapped_points_without_rebuilding_or_overwriting_commands(self):
        manager = ScdfePointTableManager(db_path=self.root / 'scdfe_s.sqlite3', workspace_root=self.root)
        definitions = [dict(kind='yc', point_no=42, name='active'), dict(kind='yc', point_no=43, name='reactive', initial=9),
                       dict(kind='yx', point_no=84, name='position'), dict(kind='yk', point_no=1, name='command', initial=True)]
        manager.generate(definitions, model_name='existing', rtu_id=1, channel_id=1)
        store = manager._store_for()
        command = store.get_row('fes_yk_define', [1, 1])
        writer = ScdfeRealtimeWriter(manager, measurement_mapping=self.mapping)
        try:
            frame = snapshot()
            serial = writer.submit(points=[], model_name='test', rtu_id=104, channel_id=104,
                                   values={}, clock=frame['clock'], device_results=frame)
            self.assertTrue(writer.wait_for(serial, 5), writer.status())
            self.assertEqual(writer.status()['rtu_id'], 1)
            self.assertEqual(store.get_row('fes_yc_define', [1, 42])['value'], 6)
            unknown = store.get_row('fes_yc_define', [1, 43])
            self.assertEqual((unknown['value'], unknown['status']), (9, 128))
            self.assertEqual(store.get_row('fes_yk_define', [1, 1]), command)
            self.assertEqual(writer.validate_mapping()['total'], 3)
            self.assertEqual(manager.summary(rtu_id=104)['total'], 0)
        finally:
            writer.close()
            manager.close()


if __name__ == '__main__':
    unittest.main()
