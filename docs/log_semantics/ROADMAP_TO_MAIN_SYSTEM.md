# Roadmap To Main System

1. Phase 1: stabilize the branch parser against representative, sanitized packages.
2. Phase 2: let the log lifecycle center read `summary.json` and `integration_payload.json`.
3. Phase 3: add idempotent, chunked MySQL ingestion for table-specific JSONL artifacts.
4. Phase 4: move job thermal-safety analysis onto the unified session and timeline model.
5. Phase 5: run risk scanning over versioned session/timeline data and retain rule versions.
6. Phase 6: export fire-review reports with direct source-file and line-number evidence.

Before Phase 3, confirm embedded meanings for temperature-limit scaling, feedback temperature
positions, hall values, weight units, and action runtime units.
