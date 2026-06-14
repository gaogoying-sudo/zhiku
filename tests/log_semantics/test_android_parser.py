import unittest
from pathlib import Path

from deploy.backend.log_semantics.parser import discover_files, parse_android_file, parse_auxiliary_file

FIXTURES = Path(__file__).parent / "fixtures"


class AndroidParserTest(unittest.TestCase):
    def test_inventory_and_core_events(self):
        inventory = discover_files(FIXTURES)
        self.assertEqual(inventory["android_file_count"], 2)
        events, unknown, warnings, counts = parse_android_file(FIXTURES / "android_one.log", 2026)
        by_type = {event["event_type"]: event for event in events}
        self.assertEqual(by_type["cooking_start"]["recipe_id"], "229623")
        self.assertEqual(by_type["cooking_start"]["recipe_name"], "4kgChicken Fried Rice [v3.0]")
        self.assertEqual(by_type["command_power_set"]["command_power_w"], 0)
        self.assertEqual(by_type["power_feedback"]["actual_power_kw"], 14.9)
        self.assertEqual(by_type["power_feedback"]["android_output_temp_c"], 227.0)
        self.assertEqual(by_type["temp_limit_set"]["temp_limit_c"], 350.0)
        self.assertIn("liquid_feed_start", by_type)
        self.assertIn("lean_start", by_type)
        self.assertIn("roll_start", by_type)
        self.assertIn("weigh_start", by_type)
        self.assertIn("speech_start", by_type)
        self.assertEqual(len(unknown), 1)
        self.assertFalse(warnings)

    def test_missing_year_is_filled(self):
        events, _, warnings, _ = parse_android_file(FIXTURES / "android_two.log", 2026)
        self.assertEqual(events[0]["timestamp"], "2026-06-12 10:00:00")
        self.assertFalse(warnings)

    def test_main_board_no_frame_id_is_retained(self):
        events, warnings = parse_auxiliary_file(FIXTURES / "main_board.log", 2026, "main_board")
        self.assertEqual(events[0]["event_type"], "mcu_error")
        self.assertIn("no_frame_id", events[0]["risk_tags"])
        self.assertFalse(warnings)


if __name__ == "__main__":
    unittest.main()
