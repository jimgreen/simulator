"""Behavioural contracts taken from power_simu_web definitions."""
import unittest

from digital_twin import DigitalTwin
from model_import import load_model_bytes


E_MODEL = b'''<Model>
@ name p_unit
# structural kW
</Model>
<ACGenerator>
@ idx name dev_type node rated_capacity p_set run_stat
# 1 arbitrary unknown 1 100 80 1
# 2 wind-name-misleading wind 1 100 60 1
</ACGenerator>
<ACStorageGen>
@ idx idx_acgenerator energy_capacity charge_discharge_efficiency max_charge_power max_discharge_power soc soc_lower_limit soc_upper_limit
# 1 1 100 0.8 30 40 0.5 0.1 0.9
</ACStorageGen>
<ACPVGen>
@ idx idx_acgenerator reference_irradiance reference_temperature temp_coefficient
# 1 2 800 20 -0.01
</ACPVGen>'''


class ReferenceAlignmentTest(unittest.TestCase):
    def test_legacy_e_storage_percentages_are_normalized_with_notice(self):
        mixed = E_MODEL.replace(b'0.8 30 40 0.5 0.1 0.9', b'80 30 40 50 0.1 90')
        model = load_model_bytes(mixed)
        parameters = model['devices'][0]['parameters']
        self.assertEqual(parameters['charge_discharge_efficiency'], 0.8)
        self.assertEqual((parameters['soc'], parameters['soc_lower_limit'], parameters['soc_upper_limit']), (0.5, 0.1, 0.9))
        self.assertTrue(model['metadata']['warnings'])
        with self.assertRaises(ValueError):
            load_model_bytes(mixed.replace(b'80 30', b'101 30'))

    def test_technology_is_defined_by_parameter_reference_not_label(self):
        model = load_model_bytes(E_MODEL, source_name='reference.e')
        self.assertEqual([d['type'] for d in model['devices']], ['battery', 'pv'])
        snapshot = DigitalTwin(model=model).snapshot()
        battery = snapshot['devices'][0]
        self.assertEqual(battery['p_kw'], 40)
        self.assertEqual(battery['requested_p_kw'], 80)
        self.assertIn('power_limit', battery['limit_reasons'])

    def test_pv_uses_reference_conditions_and_canonical_temperature(self):
        twin = DigitalTwin(model=load_model_bytes(E_MODEL))
        twin.merge_curves({'weather': [{'minute': 0, 'solar_irradiance_w_m2': 400, 'air_temp_c': 30}]})
        pv = twin.snapshot()['devices'][1]
        self.assertEqual(pv['available_kw'], 45)
        self.assertEqual(pv['p_kw'], 45)
        self.assertIn('weather_limit', pv['limit_reasons'])

    def test_storage_efficiency_at_both_energy_bounds(self):
        for soc, power, expected, bound in ((.10001, 100, 2.88, 10), (.89999, -100, -4.5, 90)):
            with self.subTest(power=power):
                twin = DigitalTwin(model={'devices': [{'id':'b', 'type':'battery', 'rated_kw':100, 'energy_kwh':100,
                    'parameters': {'soc':soc, 'soc_lower_limit':.1, 'soc_upper_limit':.9, 'charge_discharge_efficiency':.8}}]})
                twin.apply_device_actions([{'device_id':'b','action':'set_power','value':power}])
                self.assertAlmostEqual(twin.snapshot()['devices'][0]['p_kw'], expected, places=3)
                twin.tick(1, force=True)
                self.assertAlmostEqual(twin.snapshot()['soc_pct'], bound)

    def test_invalid_parameter_reference_rejects_model(self):
        for data in (E_MODEL.replace(b'# 1 1 100', b'# 1 99 100'), E_MODEL.replace(b'# 1 2 800', b'# 1 1 800')):
            with self.assertRaises(ValueError):
                load_model_bytes(data)

    def test_hh_mm_seek_and_zero_history(self):
        twin = DigitalTwin()
        twin.tick(1, force=True)
        twin.command_clock('seek', '12:30')
        self.assertEqual(twin.clock()['sim_time'], '12:30:00')
        self.assertEqual(twin.snapshot(history_limit=0)['history'], [])

    def test_light_snapshots_preserve_runtime_values(self):
        twin = DigitalTwin(model=load_model_bytes(E_MODEL))
        full = twin.snapshot(history_limit=0)
        light = twin.snapshot(profile='devices', history_limit=0)
        self.assertEqual(light['devices'], full['devices'])
        self.assertEqual(light['model_revision'], full['model_revision'])
        self.assertNotIn('point_values', light)
        self.assertNotIn('diagram_measurements', light)

    def test_dashboard_snapshot_is_compact_but_keeps_runtime_summary(self):
        twin = DigitalTwin(model=load_model_bytes(E_MODEL))
        dashboard = twin.snapshot(profile='dashboard')
        self.assertEqual(dashboard['model']['device_count'], 2)
        self.assertEqual(dashboard['model']['node_count'], 0)
        self.assertIn('generation', dashboard)
        self.assertIn('history', dashboard)
        self.assertNotIn('devices', dashboard)
        self.assertNotIn('topology', dashboard)
        self.assertNotIn('point_values', dashboard)
        self.assertNotIn('diagram_measurements', dashboard)

    def test_builtin_storage_still_evolves(self):
        twin = DigitalTwin()
        twin.merge_curves({'battery':[{'minute':0,'battery_kw':10}]})
        previous = twin.snapshot()['soc_pct']
        twin.tick(360, force=True)
        self.assertLess(twin.snapshot()['soc_pct'], previous)


if __name__ == '__main__':
    unittest.main()
