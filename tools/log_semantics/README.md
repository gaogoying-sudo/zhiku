# Log Semantics CLI

```bash
python3 tools/log_semantics/parse_log_dir.py \
  --input /path/to/extracted_log_dir \
  --output output/log_semantics_result \
  --default-year 2026 \
  --timezone Asia/Shanghai
```

Add `--debug-commands` only when command-level evidence is needed. Normal runs count
`sendMsg`, `readResult`, and `findResult` records without adding them to the unified timeline.
