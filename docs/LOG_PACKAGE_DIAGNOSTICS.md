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

每次接口只处理一个 `file_id`，下载继续受 `MAX_LOG_ANALYSIS_DOWNLOAD_MB` 保护。成功结果按 `file_id` 写入磁盘缓存，普通查询优先复用缓存。

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
