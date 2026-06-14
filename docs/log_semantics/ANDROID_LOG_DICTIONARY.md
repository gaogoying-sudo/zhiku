# Android Log Dictionary

Every event retains `source_file`, `line_no`, `raw_line`, `timestamp`, `raw_timestamp`,
`event_type`, `confidence`, and `risk_tags`.

| Event | Example | Structured fields | Timeline | Risk | Status |
|---|---|---|---|---|---|
| `app_version` / `firmware_version` / `jni_version` | `APP版本：5.1.9.4` | matching version field | Yes | No | Confirmed string extraction |
| `network_request` | `network request, url: https://...` | domain, path, SHA-256 URL hash | Yes | No | Full URL never exported |
| `scene_change` | `scene = COOKING` | `scene_name` | Yes | Session evidence | Confirmed |
| `activity_lifecycle` | `ProtectPotActivity onCreate` | activity and lifecycle action | Yes | Session evidence | Confirmed |
| `cooking_start` | `烹饪开始:name_229623` | recipe name and ID | Yes | Session evidence | Strong start |
| `protect_pot_marker` | `快速养锅` | marker | Yes | May produce `protect_pot_high_temp` | Strong start |
| `recipe_recording` | `录制菜谱 , time = 8826` | raw record time | Yes | No | Unit unconfirmed |
| `temp_limit_set` | `设置温度上限:3500 成功` | raw value, derived 350.0 C, result | Yes | Context | Division by 10 needs embedded confirmation |
| `command_power_set` | `功率设置为：12000 W` | W and kW | Yes | Threshold tags | Confirmed conversion |
| `command_power_result` | `功率设置_12000W_成功` | W, kW, result | Yes | Threshold tags | Confirmed |
| `power_feedback` | `功率:15000_14900,...温度:_52_57_227` | command/actual power, bus, current, frequency, three Android temperatures | Yes | Power and temperature tags | Field order follows supplied contract |
| monitor/fan | `开始检测温度` | marker or collection payload | Yes | No | Confirmed marker |
| lean | `开始倾锅操作：OUT_4` | position, result, work time, hall | Yes | Context | Hall semantics unconfirmed |
| roll | `开始转锅：RUN_CW_HIGH` | mode, result, work time, hall | Yes | Context | Mode retained verbatim |
| liquid feed | `开始投液料：..._20.0_GRAM_432_RUNTIME` | sauce, ID, amount, runtime, remaining | Yes | Context | Runtime assumed milliseconds by contract |
| weigh | `开始称重：SPICE_ONE_READ_27.0` | channel, target, raw and origin weight | Yes | No | Raw units unconfirmed |
| speech | `CNEngine speak =...,code = 0` | text and code | Yes | No | Confirmed |
| `data_collect` | `DataCollectManager: ...` | category and parsed key/value payload | Yes | Context | Generic payload is best effort |
| command events | `sendMsg`, `readResult`, `findResult` | raw evidence | Debug only | No | Counted by default |
| `mcu_error` / `error` | `no FrameID for result` | error text | Yes | `no_frame_id` / `heater_error` | Candidate signal |

Auxiliary debug parsing records `heaterGetErrCode` queries as `heater_status`; a status query or
explicit zero error is not labeled as a heater fault.

Keyword-bearing lines that fail stable parsing are written to `unknown_patterns.csv`.
