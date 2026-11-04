"""Run with: python3 -m unittest discover -s tests"""

from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import unittest

# model.py has no HA imports; load it by path so the package __init__ (which needs HA) is skipped.
_spec = importlib.util.spec_from_file_location(
    "model", Path(__file__).parent.parent / "custom_components" / "ahc_preheat" / "model.py"
)
model = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(model)

T0 = datetime(2026, 11, 4, 6, 0)


def run_ramp(tracker: model.RampTracker, temps: list[float], target: float, step_min: int = 5):
    result = None
    for i, temp in enumerate(temps):
        result = tracker.update(T0 + timedelta(minutes=i * step_min), temp, target, outdoor=5.0)
    return result


class LeadTimeTest(unittest.TestCase):
    def test_default_model_uses_default_rate_and_deadtime(self):
        room = model.RoomModel()
        lead = room.lead_minutes(current=19.0, target=22.0, outdoor=None, buffer_min=10)
        self.assertAlmostEqual(lead, 10 + 3 / 1.5 * 60 + 10)

    def test_no_lead_when_already_warm(self):
        self.assertEqual(model.RoomModel().lead_minutes(22.5, 22.0, 5.0, 10), 0.0)

    def test_colder_outside_means_longer_lead(self):
        room = model.RoomModel()
        for gap, rate in [(5, 3.0), (10, 2.5), (15, 2.0), (20, 1.5), (25, 1.0)]:
            room.add_sample(rate, gap)
        mild = room.lead_minutes(18.0, 21.0, outdoor=13.0, buffer_min=0)
        cold = room.lead_minutes(18.0, 21.0, outdoor=-2.0, buffer_min=0)
        self.assertGreater(cold, mild)

    def test_inverted_fit_falls_back_to_mean(self):
        room = model.RoomModel()
        for gap, rate in [(5, 1.0), (10, 1.5), (15, 2.0), (20, 2.5)]:
            room.add_sample(rate, gap)
        self.assertAlmostEqual(room.rate_for(30), 1.75)

    def test_samples_are_capped(self):
        room = model.RoomModel()
        for _ in range(model.MAX_SAMPLES + 5):
            room.add_sample(2.0, 10.0)
        self.assertEqual(len(room.samples), model.MAX_SAMPLES)

    def test_roundtrip_dict(self):
        room = model.RoomModel()
        room.add_sample(2.0, 12.0)
        room.add_deadtime(20)
        restored = model.RoomModel.from_dict(room.to_dict())
        self.assertEqual(restored.to_dict(), room.to_dict())


class WindowTest(unittest.TestCase):
    def test_window_opens_only_within_lead(self):
        start = T0 + timedelta(minutes=60)
        self.assertFalse(model.preheat_window_open(T0, start, lead_min=45, max_lead_min=180))
        self.assertTrue(model.preheat_window_open(T0, start, lead_min=75, max_lead_min=180))

    def test_window_capped_by_max_lead(self):
        start = T0 + timedelta(minutes=200)
        self.assertFalse(model.preheat_window_open(T0, start, lead_min=300, max_lead_min=180))

    def test_window_closed_once_comfort_started(self):
        self.assertFalse(model.preheat_window_open(T0, T0 - timedelta(minutes=1), 60, 180))


class RampTrackerTest(unittest.TestCase):
    def test_measures_rate_and_deadtime(self):
        # setpoint 21: flat for 10 min (deadtime), then +0.5 K per 15 min
        temps = [18.0, 18.0, 18.0, 18.2, 18.4, 18.5, 18.7, 18.9, 19.0, 19.2, 19.4, 19.5,
                 19.7, 19.9, 20.0, 20.2, 20.4, 20.5, 20.7, 20.9]
        result = run_ramp(model.RampTracker(), temps, target=21.0)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.deadtime_min, 15.0)
        self.assertAlmostEqual(result.rate, 2.0, delta=0.15)
        self.assertAlmostEqual(result.gap, 13.0)

    def test_no_ramp_for_small_setpoint_change(self):
        tracker = model.RampTracker()
        self.assertIsNone(tracker.update(T0, 20.8, 21.0, 5.0))
        self.assertFalse(tracker.active)

    def test_short_ramp_yields_no_rate(self):
        result = run_ramp(model.RampTracker(), [20.0, 20.3, 20.9], target=21.0)
        self.assertIsNotNone(result)
        self.assertIsNone(result.rate)

    def test_setpoint_lowered_aborts_without_rise(self):
        tracker = model.RampTracker()
        tracker.update(T0, 18.0, 21.0, 5.0)
        self.assertIsNone(tracker.update(T0 + timedelta(minutes=5), 18.0, 17.0, 5.0))
        self.assertFalse(tracker.active)


if __name__ == "__main__":
    unittest.main()
