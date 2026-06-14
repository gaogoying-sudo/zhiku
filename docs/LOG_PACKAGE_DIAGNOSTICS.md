# 日志包稳定诊断机制

## 目标

日志包诊断用于回答三个不同问题：

1. 文件能否下载、是否完整、能否解压。
2. 日志内部是否存在烹饪、养锅、录菜或人工动作。
3. 日志内部作业能否与 `sop_machinelog` 生产记录对齐。

数据库没有匹配记录时，只能表述为 `DB 未匹配`，禁止直接推断为 `未生产`。

## 处理流程

```text
machine_ftp 索引
→ COS 下载与大小检查
→ ZIP 格式与 CRC 检查
→ 关键日志文件识别
→ 日志内部时间范围
→ 内部事件与作业片段重建
→ 有界的 sop_machinelog 时间范围匹配
→ 状态与建议动作
```

每次接口只处理一个 `file_id`，下载继续受 `MAX_LOG_ANALYSIS_DOWNLOAD_MB` 保护。成功结果按 `file_id` 写入磁盘缓存并复用 24 小时；短暂下载、解压或解析失败只缓存 15 分钟。

## 关键日志

- `android*.log`：烹饪场景、菜谱、功率、温度、投料、语音和采集动作。
- `temperature*.log`：滤波温度、红外温度、输出温度三元组。
- `main_board.log`：加热、加油、加水、倾锅、转锅等主控动作。
- `oildrum_board.log`：油桶、油管、泵、电机和加热状态。
- `debug*.log`：MCU 通讯、错误和调试证据。

一个 ZIP 中允许出现多个 Android 或 temperature 日志文件。

## 内部作业类型

- `cooking`：出现烹饪开始、烹饪场景等证据。
- `protect_pot`：快速养锅或养锅开始。
- `recipe_recording`：录制菜谱或 `RecipeMessageActivity onCreate`。
- `manual_action`：没有标准作业开头，但存在功率、温度、投料、倾锅或转锅动作。
- `unknown`：证据不足，暂不能归类。

内部作业输出菜谱名/ID、起止时间、最高功率、温度摘要、事件数量和原始证据行。温度三元组保留原值；锅体温度沿用当前系统口径取第 3 位。

## 作业热安全工作区

`GET /api/thermal-safety-workspace/{sn}` 将日志包诊断结果组织成单次作业工作区：

- DB 匹配成功：复用现有菜谱步骤、温度采样、功率采样和能量结果。
- DB 未匹配但存在内部作业：按日志时间轴积分指令/实际功率，并展示温度、投料、倾锅、转锅和原始证据。
- 无内部作业：返回明确 `failure_reason` 和下一步动作，不返回空白页面。

功率能量按相邻事件的持续时间积分，单段最大按 60 秒保护，避免日志缺口把能量无限放大。页面风险标签均为候选筛查结果。

## 状态定义

| 状态 | 含义 |
| --- | --- |
| 已匹配生产记录 | 日志时间范围内匹配到 DB 生产记录 |
| DB 未匹配，日志内有作业片段 | DB 没记录，但日志内部重建出烹饪或录菜片段 |
| DB 未匹配，日志内仅有养锅/手动动作 | 没有标准烹饪记录，但存在设备动作 |
| DB 未匹配，日志内无有效作业 | 关键日志可读，但没有足够事件形成片段 |
| 日志不可下载 | COS 缺失、删除、超时或下载错误 |
| 日志不可解压 | 不是 ZIP、ZIP 损坏或 CRC 失败 |
| 关键日志缺失 | ZIP 可读，但没有识别到关键日志文件 |
| 时间范围无法识别 | 文件存在，但时间戳格式无法解析 |
| 解析失败 | 未预期解析器异常，需保留原包排查 |

## 失败原因枚举

包体检：

- `machine_ftp_missing`
- `cos_url_missing`
- `cos_deleted`
- `download_failed`
- `download_timeout`
- `file_too_large`
- `not_zip`
- `zip_corrupted`
- `key_log_missing`
- `log_time_not_found`
- `parser_error`

目标作业匹配：

- `db_record_not_found`
- `log_time_not_cover_job`
- `no_internal_session`
- `internal_session_exists_but_no_db_record`
- `timezone_or_clock_drift_suspected`
- `no_temperature_signal`
- `no_power_signal`
- `key_log_missing`
- `parser_error`

## 排查建议

1. 先看下载和 ZIP 诊断，确认文件本身可用。
2. 再看关键文件及日志覆盖时间，确认选包正确。
3. DB 未匹配时查看内部作业片段，不能直接判断设备未生产。
4. 内部作业时间与目标时间接近但 DB 无记录时，检查数据库漏记、时区和设备时钟漂移。
5. 温度或功率信号缺失时，换相邻日志包或确认设备日志版本。
6. `parser_error` 必须保留原始包、文件名和错误信息，补充解析规则后再诊断。

## LOG-RECON-001 数据对账

当页面最终数据和预期不一致时，优先跑日志包对账，不要先改 UI 文案。

入口：

- Admin API：`GET /api/debug/log-reconciliation/{file_id}`
- 脚本：`python deploy/backend/scripts/reconcile_log_package.py --file-id <file_id>`

输出：

- `output/log_reconciliation_<file_id>.json`
- `output/log_reconciliation_<file_id>.md`

对账层级：

| 层级 | 来源 |
| --- | --- |
| 原始日志包 | `machine_ftp` ZIP 与解压目录 |
| 语义解析产物 | `deploy/backend/log_semantics` 的 `ParseResult` |
| integration_payload | `log_semantics/exporters.py` 导出的入库候选 |
| 云端结构化库 | `device_log_packages`、`cook_jobs`、`cook_temperature_samples`、`cook_power_events`、`cook_action_events` |
| 生命周期中心 | `device_log_packages` 五阶段状态和摘要字段 |
| 作业列表 | `cook_jobs` 与事件表聚合 |
| 热安全分析 | `build_thermal_safety_workspace`，优先结构化库，失败回退内部作业 |
| 服务端缓存 | `log_package_diagnostics` 与 `cook_temperature` 磁盘缓存 |
| 浏览器缓存 | 服务端不可直接读取，异常时需强刷或清本地缓存复测 |

核心字段：

- `session_id`
- `recipe_id`
- `recipe_name`
- `start_time`
- `end_time`
- `duration_seconds`
- `max_temperature`
- `avg_temperature`
- `max_command_power_kw`
- `max_actual_power_kw`
- `temperature_sample_count`
- `power_event_count`
- `action_event_count`
- `risk_tags`
- `source_file_id`
- `parser_version`

差异分类：

- 解析问题：原始日志可见，但 `log_semantics` 或旧诊断没有解析出来。
- 入库问题：解析产物存在，但 `cook_jobs` 或事件表没有对应行。
- 缓存问题：服务端磁盘缓存版本不一致，或浏览器本地仍读旧数据。
- 页面映射问题：结构化库数据正确，但页面取错字段或只读取部分来源。
- 导出问题：页面正确，但导出没有包含同一批字段。
- 口径未确认：两套解析器切分规则不同，暂不硬修，只记录差异。

状态保护：

- `stored` 和 `partial_stored` 都属于已有成果，missing-only 后台补齐和自动解析 worker 不应重新排队覆盖。
- 刷新远端索引只更新远端元数据，不得覆盖本地下载、解压、解析、入库阶段。
- 同一个 `source_file_id` 在 `cook_jobs` 中不得重复插入导致统计翻倍。
