import math
import unittest
from unittest.mock import patch

from digital_twin import DigitalTwin


def model():
    return {"name": "operations", "devices": [
        {"id": "diesel", "type": "diesel", "rated_kw": 100},
        {"id": "load", "type": "load", "rated_kw": 100},
        {"id": "switch", "type": "switch", "closed_status": True},
        {"id": "a", "type": "battery", "rated_kw": 100, "energy_kwh": 100,
         "parameters": {"soc": .5, "charge_discharge_efficiency": 1}},
        {"id": "b", "type": "battery", "rated_kw": 100, "energy_kwh": 200,
         "parameters": {"soc": .8, "charge_discharge_efficiency": .8}},
    ], "curves": {"diesel": [{"minute": 0, "diesel_kw": 40}],
                  "battery": [{"minute": 0, "battery_kw": 0}]}}


def rows(twin):
    return {row["id"]: row for row in twin.snapshot(history_limit=0)["devices"]}


class OperationsTest(unittest.TestCase):
    def test_batch_is_atomic_and_recalculates_once(self):
        twin = DigitalTwin(model=model())
        count = twin._power_flow_count
        with self.assertRaises(ValueError):
            twin.apply_device_actions([{"device_id": "diesel", "action": "stop"},
                                       {"device_id": "load", "action": "set_power", "value": math.nan}])
        self.assertTrue(rows(twin)["diesel"]["run"])
        self.assertEqual(twin._power_flow_count, count)
        twin.apply_device_actions([{"device_id": "diesel", "action": "stop"},
                                   {"device_id": "switch", "action": "open"}])
        self.assertEqual(twin._power_flow_count, count + 1)
        self.assertFalse(rows(twin)["switch"]["closed_status"])

    def test_setpoint_override_and_follow_curve(self):
        twin = DigitalTwin(model=model())
        twin.apply_device_actions([{"device_id": "diesel", "action": "set_power", "value": 25}])
        self.assertEqual(rows(twin)["diesel"]["p_kw"], 25)
        twin.tick(1, force=True)
        self.assertEqual(rows(twin)["diesel"]["control_mode"], "manual")
        twin.apply_device_actions([{"device_id": "diesel", "action": "follow_curve"}])
        self.assertEqual(rows(twin)["diesel"]["p_kw"], 40)
        self.assertEqual(rows(twin)["diesel"]["control_mode"], "curve")
        with self.assertRaises(ValueError):
            twin.apply_device_actions([{"device_id": "load", "action": "set_power", "value": -1}])
        with self.assertRaises(ValueError):
            twin.apply_device_actions([{"device_id": "switch", "action": "set_power", "value": 1}])

    def test_individual_storage_soc_and_weighted_summary(self):
        twin = DigitalTwin(model=model())
        twin.apply_device_actions([{"device_id": "a", "action": "set_power", "value": 10},
                                   {"device_id": "b", "action": "set_power", "value": -20}])
        twin.tick(360, force=True)
        devices = rows(twin)
        self.assertAlmostEqual(devices["a"]["soc_pct"], 49)
        self.assertAlmostEqual(devices["b"]["soc_pct"], 80.8)
        self.assertAlmostEqual(twin.snapshot()["soc_pct"], (49 * 100 + 80.8 * 200) / 300, places=3)
        twin.set_device_state("a", False)
        before = devices["a"]["soc_pct"]
        twin.tick(360, force=True)
        self.assertEqual(rows(twin)["a"]["soc_pct"], before)

    def test_storage_limits_and_efficiency(self):
        data = model()
        data["devices"][3]["parameters"].update(soc=.10001, soc_lower_limit=.1, soc_upper_limit=.9)
        twin = DigitalTwin(model=data)
        twin.apply_device_actions([{"device_id": "a", "action": "set_power", "value": 100}])
        self.assertAlmostEqual(rows(twin)["a"]["p_kw"], 3.6, places=3)
        twin.tick(1, force=True)
        self.assertEqual(rows(twin)["a"]["soc_pct"], 10)
        self.assertEqual(rows(twin)["a"]["p_kw"], 0)

    def test_seek_does_not_integrate_soc_and_step_not_squared_by_speed(self):
        twin = DigitalTwin(model=model())
        twin.command_clock("speed", 20)
        twin.command_clock("step")
        self.assertEqual(twin.clock()["sim_seconds"], 1)
        soc = rows(twin)["a"]["soc_pct"]
        twin.command_clock("seek", "12:30:00")
        self.assertEqual(twin.clock()["sim_time"], "12:30:00")
        self.assertEqual(rows(twin)["a"]["soc_pct"], soc)

    def test_background_clock_uses_elapsed_wall_time_once(self):
        twin = DigitalTwin(model=model())
        twin._last_wall = twin._last_step_wall = 100.0
        with patch("digital_twin.time.monotonic", return_value=101.0):
            self.assertTrue(twin.tick())
        self.assertAlmostEqual(twin.clock()["sim_seconds"], 1.0)

    def test_sparse_curve_interpolates_each_channel(self):
        twin = DigitalTwin(model={"devices": [], "curves": {"weather": [
            {"minute": 0, "wind_speed_mps": 0}, {"minute": 10, "air_temp_c": 10},
            {"minute": 20, "wind_speed_mps": 20}, {"minute": 30, "air_temp_c": 30}]}})
        value = twin._curve_at("weather", 15)
        self.assertEqual(value["wind_speed_mps"], 15)
        self.assertEqual(value["air_temp_c"], 15)


if __name__ == "__main__":
    unittest.main()
