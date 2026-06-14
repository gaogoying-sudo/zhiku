# Integration Contract

Parser payloads use `parser_version=0.1.0` and `schema_version=log_semantics_v1`.
Consumers must reject or explicitly migrate unsupported schema versions.

## Table Mapping

### `cook_jobs`

Map session ID to `external_session_id`; session type to source/job type; copy recipe ID/name,
start/end, duration, temperature and event counts, risk tags and parser version. Map
`max_output_temp_c` to `max_pot_temp` and `avg_output_temp_c` to `avg_pot_temp`.

### `cook_temperature_samples`

Copy timestamp, session-relative offset, filtered/infrared/output temperature,
`android_output_temp_c` when joined from feedback, source file, line number and raw triplet.

### `cook_power_events`

Copy timestamp, relative offset, command/actual W and kW, bus voltage, output current,
frequency, raw line and evidence location.

### `cook_action_events`

Copy timestamp, relative offset, event type, action label, action parameters JSON, result,
raw line, source file and line number.

### `log_internal_sessions`

Add this table if absent:

`id`, `sn`, `source_file_id`, `session_id`, `session_type`, `start_time`, `end_time`,
`recipe_id`, `recipe_name`, `match_db_job_id`, `match_confidence`, `parser_version`,
`risk_tags_json`, `evidence_json`, `created_at`.

## Ingestion Guidance

`integration_payload.json` is a portability artifact, not an efficient long-term storage format.
A real package may contain hundreds of thousands of temperature and timeline rows. The main
system should stream JSONL files or chunk the payload into table-specific inserts, enforce
idempotency on package + source file + line number, and store the summary/artifact URI
separately. Do not place the full payload in a single MySQL JSON column.

No parser path connects to MySQL. SN and source-file database IDs are assigned by the importer.
