import unittest
from pathlib import Path

from deploy.backend.log_semantics.parser import parse_android_file, parse_temperature_file
from deploy.backend.log_semantics.sessionizer import _integrate_power, build_sessions

FIXTURES = Path(__file__).parent / "fixtures"


class SessionizerTest(unittest.TestCase):
    def test_cooking_and_protect_pot_sessions(self):
        one, _, _, _ = parse_android_file(FIXTURES / "android_one.log", 2026)
        two, _, _, _ = parse_android_file(FIXTURES / "android_two.log", 2026)
        temp_one, _, _ = parse_temperature_file(FIXTURES / "temperature.log", 2026)
        temp_two, _, _ = parse_temperature_file(FIXTURES / "temperature_two.log", 2026)
        sessions = build_sessions(one + two, temp_one + temp_two)
        self.assertEqual([session["session_type"] for session in sessions], ["cooking", "protect_pot"])
        self.assertEqual(sessions[0]["recipe_id"], "229623")
        self.assertEqual(sessions[0]["max_output_temp_c"], 280.0)
        self.assertIn("protect_pot_high_temp", sessions[1]["risk_tags"])

    def test_energy_interval_is_capped_at_60_seconds(self):
        energy = _integrate_power([
            {"timestamp": "2026-06-12 09:00:00", "command_power_w": 1000, "actual_power_w": 500},
            {"timestamp": "2026-06-12 09:10:00", "command_power_w": 0, "actual_power_w": 0},
        ])
        self.assertEqual(energy, (60.0, 30.0))


if __name__ == "__main__":
    unittest.main()
