import io
import json
from pathlib import Path
import unittest
import zipfile

from model_import import load_model_bytes, load_boundary_bytes, sanitize_svg
from digital_twin import DigitalTwin

MODEL = b'''<Model>\n@ name p_unit\n# demo kW\n</Model>\n<ACNode>\n@ idx name run_stat\n# 1 wind-node 1\n# 2 bus 1\n</ACNode>\n<DCNode>\n@ idx name run_stat\n# 1 dc-bus 1\n</DCNode>\n<ACBreak>\n@ idx name i_node j_node status run_stat\n# 1 breaker 1 2 1 1\n</ACBreak>\n<ACGenerator>\n@ idx name dev_type node rated_capacity p_set run_stat\n# 1 turbine ac-wind-source 1 100 20 1\n</ACGenerator>\n<ACLoad>\n@ idx name node rated_capacity p_set run_stat\n# 1 demand 2 10 2 1\n</ACLoad>'''
SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 200"><defs><symbol id="switch_state_1"><rect width="20" height="20"/></symbol></defs><g device-type="ACBreak"><use dev-id="ACBreak-1" name="breaker" href="#switch_state_1"/></g><g dev="ACGenerator-1"><text mt="p" mti="activePower">0</text></g></svg>'''


class ExternalInputsTest(unittest.TestCase):
    def test_e_identity_and_structure(self):
        model = load_model_bytes(MODEL, source_name='demo.e')
        devices = {d['id']: d for d in model['devices']}
        self.assertEqual(devices['ACNode:1']['type'], 'node')
        self.assertEqual(devices['ACGenerator:1']['node'], 'ACNode:1')
        self.assertIn('DCNode:1', {n['id'] for n in model['topology']['nodes']})
        self.assertIn('ACGenerator-1', devices['ACGenerator:1']['aliases'])

    def test_definition_zip_and_model_replacement(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('manifest.json', '{"version": 1}')
            archive.writestr('model.e', MODEL)
            archive.writestr('diagram.svg', SVG)
            archive.writestr('curves.e', '<EnvironmentCurve>\n@ minute wind_speed_mps\n# 0 12\n</EnvironmentCurve>')
        twin = DigitalTwin()
        twin.load_model(load_model_bytes(buffer.getvalue(), source_name='demo.zip'))
        self.assertTrue(twin.diagram()['available'])
        self.assertEqual(twin.snapshot()['weather']['wind_speed_mps'], 12)
        twin.load_model(load_model_bytes(MODEL, source_name='next.e'))
        self.assertFalse(twin.diagram()['available'])

    def test_partial_boundary_preserves_other_channels(self):
        twin = DigitalTwin()
        previous = twin.snapshot()['weather']
        curves = load_boundary_bytes(b'time,temperature\n00:00,-5\n12:00,5')['curves']
        twin.merge_curves(curves)
        current = twin.snapshot()['weather']
        self.assertEqual(current['air_temp_c'], -5)
        self.assertEqual(current['wind_speed_mps'], previous['wind_speed_mps'])
        self.assertEqual(current['load_kw'], previous['load_kw'])

    def test_invalid_boundaries_rejected(self):
        for data in (b'time,wind\nbad,8', b'time,wind\n00:00,NaN', b'time,wind\n00:00,-1', b'time,wind\n00:00,2\n00:00,3', b'junk,value\nx,y'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                load_boundary_bytes(data)

    def test_svg_safety_and_bindings(self):
        svg = sanitize_svg(SVG)['svg']
        self.assertIn('dev-id="ACBreak-1"', svg)
        self.assertIn('mti="activePower"', svg)
        cleaned = sanitize_svg(b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(1)</script><foreignObject/><use href="https://bad.test/x"/><animate attributeName="href" to="javascript:alert(1)"/></svg>')['svg']
        for token in ('onload', '<script', 'foreignObject', 'bad.test', '<animate'):
            self.assertNotIn(token, cleaned)
        with self.assertRaises(ValueError):
            sanitize_svg(b'<svg><g></svg>')

    def test_switch_operation_and_topology_recovery(self):
        twin = DigitalTwin(model=load_model_bytes(MODEL, source_name='demo.e'))
        twin.operate_device('ACBreak:1', 'open')
        snapshot = twin.snapshot()
        rows = {d['id']: d for d in snapshot['devices']}
        self.assertFalse(rows['ACBreak:1']['closed_status'])
        self.assertFalse(snapshot['topology']['edges'][0]['closed'])
        self.assertFalse(rows['ACGenerator:1']['running'])
        twin.operate_device('ACBreak:1', 'close')
        rows = {d['id']: d for d in twin.snapshot()['devices']}
        self.assertTrue(rows['ACGenerator:1']['running'])
        self.assertTrue(rows['ACBreak:1']['closed_status'])
        with self.assertRaises(ValueError):
            twin.operate_device('ACGenerator:1', 'open')

    def test_device_loads_follow_boundaries_and_run_state(self):
        twin = DigitalTwin(model=load_model_bytes(MODEL, source_name='demo.e'))
        boundary = load_boundary_bytes(json.dumps({'loads': {'demand': [{'minute': 0, 'p_kw': .5}]}}).encode())
        twin.merge_curves(boundary['curves'])
        self.assertEqual(twin.snapshot()['network']['load_kw'], .5)
        twin.set_device_state('ACLoad:1', False)
        self.assertEqual(twin.snapshot()['network']['load_kw'], 0)

    def test_topology_edit_drives_actual_switch_and_node_state(self):
        twin = DigitalTwin(model=load_model_bytes(MODEL))
        topology = json.loads(json.dumps(twin.snapshot()['topology']))
        topology['edges'][0]['closed'] = False
        twin.set_topology(topology)
        switch = next(d for d in twin.snapshot()['devices'] if d['id'] == 'ACBreak:1')
        self.assertFalse(switch['closed_status'])
        twin.set_device_state('ACNode:2', False)
        self.assertFalse(next(n for n in twin.snapshot()['topology']['nodes'] if n['id'] == 'ACNode:2')['run'])

    def test_invalid_model_parameters_do_not_replace_state(self):
        twin = DigitalTwin(model=load_model_bytes(MODEL))
        before = twin.model_summary()
        invalid = {'name': 'invalid', 'devices': [{'type':'wind','parameters':{'cut_in_wind_speed':'bad'}}]}
        with self.assertRaises(ValueError):
            twin.load_model(invalid)
        self.assertEqual(twin.model_summary(), before)

    def test_stale_diagram_operation_rejected(self):
        twin = DigitalTwin(model=load_model_bytes(MODEL))
        revision = twin.diagram()['model_revision']
        twin.load_model(load_model_bytes(MODEL))
        with self.assertRaisesRegex(ValueError, '模型已更换'):
            twin.operate_device('ACBreak:1', 'open', model_revision=revision)
        self.assertTrue(next(d for d in twin.snapshot()['devices'] if d['id'] == 'ACBreak:1')['closed_status'])

    def test_json_total_load_without_load_devices_remains_supported(self):
        twin = DigitalTwin(model={'devices':[{'id':'gen','type':'generator','rated_kw':180}],
                                  'curves':{'weather':[{'minute':0,'load_kw':80}]}})
        snapshot = twin.snapshot()
        self.assertEqual(snapshot['network']['load_kw'], 80)
        self.assertEqual(snapshot['generation']['diesel_kw'], 145)

    def test_reference_package_when_available(self):
        folder = Path(r'D:\codex\power_simu_web\models\simulator\source\秦岭站')
        if not folder.exists():
            self.skipTest('reference checkout unavailable')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for name in ('model.e', 'meas.e', 'control.e', 'curves.e', 'diagram.svg'):
                archive.writestr(name, (folder / name).read_bytes())
        model = load_model_bytes(buffer.getvalue(), source_name='qinling.zip')
        twin = DigitalTwin(model=model)
        self.assertGreater(len(twin.snapshot()['devices']), 100)
        self.assertTrue(twin.diagram()['available'])
        self.assertGreater(len(model['measurements']), 100)
        self.assertEqual(len(model['curves']['weather']), 1440)
        self.assertGreater(twin.snapshot()['network']['load_kw'], 0)


if __name__ == '__main__':
    unittest.main()
