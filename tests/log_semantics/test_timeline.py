import unittest
from pathlib import Path

from deploy.backend.log_semantics.parser import parse_android_file, parse_temperature_file
from deploy.backend.log_semantics.sessionizer import build_sessions
from deploy.backend.log_semantics.timeline import build_timeline

FIXTURES = Path(__file__).parent / "fixtures"


class TimelineTest(unittest.TestCase):
    def test_timeline_is_sorted_and_temperature_aligned(self):
        events, _, _, _ = parse_android_file(FIXTURES / "android_one.log", 2026)
        samples, _, _ = parse_temperature_file(FIXTURES / "temperature.log", 2026)
        sessions = build_sessions(events, samples)
        timeline = build_timeline(events, samples, sessions)
        self.assertEqual([row["timestamp"] for row in timeline], sorted(row["timestamp"] for row in timeline))
        power = next(row for row in timeline if row["event_type"] == "power_feedback")
        self.assertEqual(power["output_temp_c"], 230.0)
        self.assertEqual(power["nearest_temperature_window"], "1s")


if __name__ == "__main__":
    unittest.main()
