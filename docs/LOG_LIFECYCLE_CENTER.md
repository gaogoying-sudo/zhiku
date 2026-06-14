# 设备日志生命周期中心

## 目标

日志包不再只有“可下载、排队中、已入库”三个混合状态。系统把每个包拆成远端发现、下载、解压、解析、入库五个可复用阶段，并记录失败阶段、原因码、建议动作和重试时间。

默认查询最近 90 天，单次补齐最多 50 个包。同一设备、时间范围和任务模式只允许一个活动任务。

## 状态口径

### 远端

- `available`
- `missing`
- `deleted`
- `url_missing`
- `unknown`

### 下载

- `not_started`
- `queued`
- `downloading`
- `downloaded`
- `download_failed`
- `download_timeout`
- `file_too_large`
- `skipped`

### 解压

- `not_started`
- `queued`
- `unzipping`
- `unzipped`
- `not_zip`
- `zip_corrupted`
- `unzip_failed`
- `skipped`

### 解析

- `not_started`
- `queued`
- `parsing`
- `parsed`
- `partial_success`
- `parse_failed`
- `key_log_missing`
- `no_time_range`
- `no_internal_session`
- `no_production_match`
- `no_temperature_data`
- `skipped`

### 入库

- `not_stored`
- `storing`
- `stored`
- `partial_stored`
- `store_failed`
- `superseded`

`DB 未匹配` 不等于没有生产。日志内部存在烹饪、养锅、功率、温度或投料片段时，任务记为部分成功，证据继续保留。

## 复用顺序

1. 已入库：直接读取结构化数据库。
2. 已有解析 JSON：直接入库。
3. 已解压：从解压目录解析。
4. 已下载：从本地 ZIP 解压。
5. 只有远端索引：下载后继续。
6. 失败包：遵守指数退避和最大重试次数。
7. 管理员强制重试：可绕过退避。
8. 解析版本变化：重解析，不强制重新下载。
9. 强制重新下载：清除当前包的 ZIP、解压目录和解析缓存，结构化数据单独保留。

## API

- `GET /api/devices/{sn}/log-lifecycle`
- `POST /api/devices/{sn}/log-backfill`
- `GET /api/log-parse-tasks/{task_id}`
- `POST /api/log-packages/{file_id}/retry`
- `POST /api/log-packages/{file_id}/clear-cache`
- `GET /api/log-packages/{file_id}/lineage`

## 缓存与保留

- 下载 ZIP：默认 7 天。
- 解压目录：默认 3 天。
- 解析 JSON：目标保留 30 天。
- 结构化数据库：长期保留。

清理缓存不删除已经入库的结构化作业、温度、功率和动作数据。

## Worker 保护

- 单任务最多 50 包。
- 单包有进程内互斥锁。
- 批次遇到失败继续处理其他包。
- 失败按 5 分钟起步指数退避，最长 24 小时。
- 自动失败最多重试 3 次；达到上限后只允许管理员核查后强制重试。
- 不扩大 `sop_machinelog` 查询范围。
- 下载继续受 `MAX_LOG_ANALYSIS_DOWNLOAD_MB` 保护。
- 不向前端返回 COS 地址和云端缓存物理路径。

部分设备 ZIP 会把成员名写成 `/android*.log`、`/temperature.log`。安全解压器会去掉合法前导斜杠后写入包内目录，但继续拒绝 `..`、盘符和目录穿越路径；这类包不能误判为 ZIP 损坏。

## 页面关系

- 日志生命周期中心：治理包的发现、下载、解压、解析和入库。
- 作业列表：优先读取已入库作业。
- 作业热安全分析：优先读取结构化库，缺失时回退日志内部作业片段。
- 温度校正：复用已下载或已扫描日志，不依赖生产记录匹配。
- 数据血缘：查看一个包产生了多少作业、温度点、动作事件，以及被哪些页面复用。

## 2026-06-14 线上验证

- 设备 `0204212502260019` 最近 90 天识别 59 个日志包。
- 已入库包 `1181494` 重试时直接命中 `structured_db`，没有重新下载。
- 日志包 `1181786` 复用云端 ZIP 后正常解压，识别 11 个日志内作业片段、20,272 个事件、最高锅温 303℃、最高功率 15kW。
- 该包源数据库未匹配生产记录，因此准确落为 `partial_stored / no_production_match`，保留日志内作业证据，不再误报“未生产”或“ZIP 损坏”。
- 再次刷新公司源日志索引后，该包仍保持 `downloaded / unzipped / partial_success / partial_stored`；远端元数据更新不会覆盖本地阶段状态。
