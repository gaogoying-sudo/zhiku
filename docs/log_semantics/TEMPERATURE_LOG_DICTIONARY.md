# Temperature Log Dictionary

## High-Frequency Triplet

`[2026-06-12_09:31:19] 185_185_172`

| Position | Field |
|---|---|
| 1 | `filtered_temp_c` |
| 2 | `infrared_temp_c` |
| 3 | `output_temp_c` |

All three values, `raw_triplet`, line number and source file are retained. Multiple samples in
one second are distinct records and are not averaged during parsing.

## Android Feedback Temperatures

Android power feedback contains `core_temp_c`, `coil_temp_c`, and
`android_output_temp_c`. These are not aliases for the high-frequency triplet. The Android
measurement belongs to a composite power feedback event; the temperature file is the primary
high-frequency thermal series.

Use `temperature.output_temp_c` for thermal curves and extrema. Use
`android_output_temp_c` for controller-feedback cross-checks. Never collapse the two sources
into one column without an explicit downstream reconciliation rule.

Malformed samples are skipped, counted in `parse_errors`, and never abort the package.
