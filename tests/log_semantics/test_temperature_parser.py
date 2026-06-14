import unittest
from pathlib import Path

from deploy.backend.log_semantics.parser import discover_files, parse_temperature_file

FIXTURES = Path(__file__).parent / "fixtures"


class TemperatureParserTest(unittest.TestCase):
    def test_triplets_and_multiple_files(self):
        inventory = discover_files(FIXTURES)
        self.assertEqual(inventory["temperature_file_count"], 2)
        samples, warnings, errors = parse_temperature_file(FIXTURES / "temperature.log", 2026)
        self.assertEqual(samples[0]["filtered_temp_c"], 185.0)
        self.assertEqual(samples[0]["infrared_temp_c"], 184.0)
        self.assertEqual(samples[0]["output_temp_c"], 172.0)
        self.assertFalse(warnings)
        self.assertFalse(errors)

    def test_invalid_line_is_skipped(self):
        samples, warnings, errors = parse_temperature_file(FIXTURES / "temperature_two.log", 2026)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0]["timestamp"], "2026-06-12 10:00:05")
        self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()
