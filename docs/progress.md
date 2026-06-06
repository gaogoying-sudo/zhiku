# 智库 Agent 进度日志

## 2026-06-06

### 云端部署：功率诊断交互优化
- 操作人/会话：Codex。
- 目标：修复功率曲线“死图”、右轴看不清、能量单位不可切换、功率页明细不足的问题。
- 本次修改：
  - 功率曲线新增 SVG hover 热区：鼠标移动到图上会显示最近时间点、相对秒、锅体温度、指令功率、实际功率，并用竖线和三组圆点定位。
  - 右侧功率轴留出可读空间，刻度改为 `35kW / 17.5kW / 0kW` 不再贴边被裁。
  - 能量展示新增单位切换：`kWh` 与 `kW·s`，指标卡、作业列表、步骤能量表同步切换。
  - 功率页补回“当前作业明细”：展示菜谱设计步骤/参数，以及真实执行动作/android 日志，避免从温度页切到功率页后细节丢失。
  - 同步 `deploy/frontend/index.html -> deploy/frontend/app.html`。
- 验证结果：
  - 本地小模型委托执行 `make check` 通过。
  - `make deploy` 成功，云端容器已重建启动。
  - 本地小模型委托执行线上 smoke 通过：关键词 `kW·s` 命中，登录 200，设备匹配 200。
- 说明：
  - 本轮不改后端能量公式，只改功率诊断页面的交互、单位呈现和明细完整度。
- 解除锁定：功率诊断前端交互。

### 云端部署：功率诊断能量积分修复
- 操作人/会话：Codex。
- 目标：修复功率诊断中实际能量/指令能量显示为 0 的问题。
- 用户反馈：
  - 功率输出是持续状态，不能把一行日志当成孤立瞬时点。
  - 应按“上一条功率值持续到下一条功率事件时间”计算：`kW * 秒 / 3600 = kWh`。
  - 页面需要同时看指令功率、实际输出功率和能量。
- 本次修改：
  - 后端缓存版本从 `COOK_TEMPERATURE_CACHE_VERSION = 8` 升到 `9`，避免复用旧的 0 能量缓存和旧结构化结果。
  - 安卓日志行为识别放宽：只要行内包含 `功率:x_y` 就识别为 `power_sample`，不再强依赖同一行同时出现 `温度:_x_y_z`。
  - 功率积分从相邻点均值法调整为阶梯积分：当前功率值持续到下一条功率事件或作业/步骤结束。
  - 分步骤能量也继承步骤开始前的最近功率状态，避免步骤内没有新功率行时被算成 0。
  - 功率诊断作业列表新增“平均指令功率”，与平均/最高实际功率并排展示。
  - 同步 `deploy/frontend/index.html -> deploy/frontend/app.html`。
- 验证结果：
  - 本地小模型委托执行 `make check` 通过，两次检查均成功。
  - `make deploy` 成功，云端容器已重建启动。
  - 本地小模型委托执行线上 smoke 通过：关键词 `功率诊断` 命中，登录 200，设备匹配 200。
  - 接口抽样：`0105222506020185` + `1169983 / log_2026_06_04-17_25_59.zip` 返回 1 道菜、功率采样 106 点；示例菜 `凉瓜炒牛肉1份` 指令能量 `0.5206 kWh`，实际能量 `0.51 kWh`，平均实际功率 `8.54 kW`，最高实际功率 `15.15 kW`。
- 低成本委托使用：
  - 本轮已使用本地小模型委托跑机械检查和线上 smoke 摘要。
  - Codex 只负责公式判断、核心代码修改、接口抽样和最终验收。
- 解除锁定：功率诊断/温度解析缓存。

### 云端部署：全站文案与布局统一优化
- 操作人/会话：Codex。
- 目标：按 Product Design 视角，对最新版本所有页面的文字字段、导航命名、按钮口径、状态提示和页面错位风险做一轮专业收敛。
- 本次范围：
  - 统一主导航命名：`设备档案 / 生产记录 / 菜谱资源 / 日志包 / 菜谱检索 / 日志结论 / 温度诊断 / 功率诊断 / 版本治理 / 系统审计 / 重点设备`。
  - 顶部搜索和首页入口统一为 `SN / 客户 / 门店 / 地区`，按钮统一为 `查设备 / 模糊找 / 导出 / 清本地缓存`。
  - 全站 loading 弱提示从英文 `thinking` 改为中文 `处理中`。
  - 日志、温度、功率页统一操作名：`解析温度 / 解析功率 / 选最近3包 / 清空选择 / 下载首选 / 详情 / 曲线`。
  - 收紧页面说明文案，去掉重复/冗长描述，避免同一功能在不同页面叫法不一致。
  - 增强布局韧性：按钮稳定高度、不换行挤压；顶部搜索改为响应式 grid；表格文字和历史设备 SN 增加换行/截断保护；卡片头和指标块固定基础高度；移动/窄屏下搜索区自动单列。
  - 同步 `deploy/frontend/index.html -> deploy/frontend/app.html`。
- 验证结果：
  - `make check` 通过。
  - 部署前线上 smoke 用新词 `温度诊断` 失败，原因为线上尚未部署新 HTML，属预期。
  - `make deploy` 成功，`zhiku-web / zhiku-api / zhiku-mysql` 均重建并启动。
  - 部署后 `make smoke SMOKE_KEYWORD=温度诊断 SMOKE_SN=0105222506020185` 通过：线上 HTML 328361 bytes，登录 200，设备匹配 200，结果 1。
- 遗留/提醒：
  - 本轮主要解决产品文案和表现层错位风险，没有重构前端组件架构。
  - `deploy/frontend/index.html` 仍是超大单文件，后续建议拆分组件或至少拆分样式/脚本，降低多 AI 并行修改冲突。
- 解除锁定：前端 UI 文案与布局。

### 本地小模型委托技能
- 操作人/会话：Codex。
- 目标：把低风险机械工作外包给本机 Ollama 小模型，进一步降低 Codex token 消耗。
- 本机模型发现：
  - Ollama 可用：`http://127.0.0.1:11434`
  - 可用模型：`qwen2.5:3b`、`qwen25-3b:latest`、`qwen3:14b`
- 新增：
  - `scripts/local_agent_delegate.py`
  - Codex Skill：`/Users/kaf/.codex/skills/zhiku-local-delegate/SKILL.md`
  - Make targets：`delegate-check`、`delegate-smoke`、`delegate-status`
- 安全边界：
  - 默认只允许本地小模型执行 `check`、`smoke`、`status`。
  - `deploy/release` 必须显式 `--allow-deploy`。
  - 本地模型只做输出总结和失败初筛，不能自由改核心代码。
  - Codex 仍负责架构、核心修改、安全和最终验收。
- 验证结果：
  - `make delegate-check` 通过，本地模型正确总结 `make check` 输出。
  - `make delegate-smoke SMOKE_KEYWORD=功率诊断 SMOKE_SN=0105222506020185` 通过，本地模型正确总结线上冒烟结果。
- 后续使用原则：
  - Codex 在执行机械检查/冒烟/状态查看前，优先考虑调用本地委托脚本。
  - 失败输出先由本地模型压缩摘要，再由 Codex 处理真正需要判断的部分。
- 解除锁定：本地小模型委托。

### GitHub 自动化接入
- 操作人/会话：Codex。
- 目标：验证 `git@github.com:gaogoying-sudo/zhiku.git` 是否可用，并接入免费 GitHub Actions 机械检查，减少后续 token 消耗。
- GitHub 连通性：
  - 本机 SSH 认证成功。
  - `origin` 已指向 `git@github.com:gaogoying-sudo/zhiku.git`。
  - 已安全快进合并远端提交 `1490edd docs: add browser development protocol`。
- 新增：
  - `.github/workflows/ci.yml`
  - `docs/GITHUB_AUTOMATION.md`
- 提交与推送：
  - commit：`a87ffd1 chore: add automation and github ci`
  - push：`main -> origin/main`
- GitHub Actions 验证：
  - Workflow：`Zhiku CI`
  - 运行结果：completed / success
  - 链接：`https://github.com/gaogoying-sudo/zhiku/actions/runs/27027603916`
- 当前策略：
  - GitHub 先只做免费 CI 检查，不做云端自动部署。
  - 云端部署继续由本机 `make release` 完成，避免把 SSH/数据库密钥放到 GitHub。
- 遗留问题：
  - 如后续要 GitHub 一键部署，建议先配置 SSH key 方式的 GitHub Secrets，不建议直接放服务器密码。
- 解除锁定：GitHub 自动化。

### 本地自动化建设
- 操作人/会话：Codex。
- 目标：降低后续功能开发中的重复 token 消耗，把检查、部署、冒烟和状态查看固化为标准命令。
- 新增文件：
  - `Makefile`
  - `scripts/check_project.sh`
  - `scripts/deploy_cloud.py`
  - `scripts/smoke_cloud.py`
  - `scripts/cloud_status.py`
  - `scripts/progress_note.sh`
  - `docs/AUTOMATION_RUNBOOK.md`
- 更新文件：
  - `docs/AI_COLLABORATION_PROTOCOL.md`：部署和验证优先使用 `make` 命令。
  - `docs/00-PROJECT-INDEX.md`：补充自动化运行手册和脚本索引。
- 可用命令：
  - `make check`：同步 `index.html -> app.html`，检查 Python 和前端内联 JS，检查敏感文件是否被 Git 跟踪。
  - `make deploy`：读取本地敏感交接文件，上传 `deploy/` 并重建云端容器，不打印明文密码。
  - `make smoke SMOKE_KEYWORD=功率诊断 SMOKE_SN=0105222506020185`：检查线上页面、登录、轻量设备匹配。
  - `make status`：查看云端容器和 API 日志，自动脱敏 token。
  - `make release`：串联检查、部署和冒烟。
- 验证结果：
  - `make check` 通过。
  - `make smoke SMOKE_KEYWORD=功率诊断 SMOKE_SN=0105222506020185` 通过，线上 HTML 327616 bytes，登录 200，设备轻量匹配结果 1。
  - `make status` 可返回 `zhiku-api / zhiku-web / zhiku-mysql` 状态，并已修正日志 token 脱敏。
- 遗留问题：
  - `docker-compose.yml` 仍有 `version` obsolete 警告，不影响运行，后续可顺手清理。
  - 完整设备报告 `/api/search/{sn}` 返回可能较大，不再作为默认 smoke；需要重型验证时显式运行 `scripts/smoke_cloud.py --full-device`。
- 解除锁定：部署/运维自动化。

## 2026-06-05

### 云端部署：功率诊断 v1
- ✅ 按用户要求在“日志诊断”下新增“功率诊断”入口，版本标记：`2026.06.05-power-diagnosis1`。
- ✅ 后端在作业温度解析链路中补齐功率诊断字段：`power_samples`、`power_segments`、整道菜 `actual_energy_kwh / command_energy_kwh`、均值/峰值功率、分步骤能量和跟随率。
- ✅ 前端新增功率诊断页：复用日志包多选、大小/耗时预估、解析缓存、进度提示；支持按步骤/食材关键词筛选，支持按实际能量阈值筛选。
- ✅ 页面展示单道菜指令功率、实际输出功率、锅体温度曲线，并展示日志包内作业表和当前菜谱步骤能量表。
- ✅ 已同步 `deploy/frontend/index.html` 到 `deploy/frontend/app.html`。
- ✅ 部署前检查通过：`python3 -m py_compile deploy/backend/main.py`，内联 JS 抽取后 `node --check` 通过并删除 `/tmp/zhiku-inline.js`。
- ✅ 已部署到 `http://82.156.187.35:8085`；线上 HTML 确认包含“功率诊断”和版本号；登录接口返回 200。
- ✅ API 冒烟：`0105222506020185` 的 `1155456 / log_2026_05_27-10_07_14.zip` 返回 52 道菜，52 道均有功率采样；示例单菜返回 `actual_energy_kwh=0.378`、`command_energy_kwh=0.3987`、16 个功率步骤段、功率采样点。

### 遗留/提醒：功率诊断
- ⚠️ `1166976 / 2026-06-02 18:30:04`、`1164095 / 2026-06-01 01:53:11` 这类较大日志包在线同步解析出现 502，说明大包仍会触发网关/超时压力。
- 下一步应继续推进“结构化作业库/异步解析队列/服务器缓存”：大包先入队，解析成功后用户和其他同事同条件查询直接读本地库，不再重复下载解压。
- 当前功率诊断 v1 复用作业温度同步接口，适合作为可用版本先上线，但不是最终性能形态。
- 解除锁定：日志诊断/作业温度/功率诊断模块。

### 完成
- ✅ 新增 `docs/AI_COLLABORATION_PROTOCOL.md`，作为 Codex、agy 和后续 AI/开发者的统一协作协议。
- ✅ 明确本地/云端事实来源、开发检查、部署命令、线上三步验证、云端操作记录格式。
- ✅ 明确防污染原则：开始前看 `git status --short`，不覆盖未知改动，不泄露敏感账号密码。
- ✅ 明确需求状态流转：待确认、开发中、已部署待验收、已验收、挂起、失败/回滚。
- ✅ 明确 Codex 与 agy 分工建议，避免同一模块被多个 AI 同时覆盖。
- ✅ 采纳 agy 补充：锁定模块部署后必须写“解除锁定”，前端语法检查后清理 `/tmp/zhiku-inline.js`，敏感配置只允许本地受控读取。

### 当前重点
- 作业温度和日志结构化入库是近期核心模块。
- 已建立结构化缓存表方向：`watched_devices`、`device_log_packages`、`cook_jobs`、`cook_temperature_samples`、`cook_action_events`、`cook_power_events`。
- 需要继续把每次云端部署、队列修复、解析策略调整写回本日志。

### 遗留
- `deploy/backend/main.py` 仍然过大，后续适合拆分 `parser/`、`worker/`、`routers/`。
- 结构化日志库后续要设计数据淘汰/降采样策略，避免温度采样表无限增长。
- 队列失败重试还可继续升级为指数退避策略。

## 2026-04-29

### 完成
- ✅ 项目目录结构创建
- ✅ 数据库连接测试（6 个库全部可访问）
- ✅ 数据库 Schema 探索脚本编写
- ✅ 核心查询工具脚本编写
- ✅ 项目治理文档创建（INDEX/PROGRESS/TASK_BOARD/RESOURCE）
- ✅ Skill 创建并注册到 Hermes

### 数据库发现
- `btyc` — 281 张表（核心业务库：用户、角色、菜谱、设备、会话等）
- `btyc_statics` — 7 张表（统计数据：烹饪统计、零件使用等）
- `dev_btyc` — 278 张表（开发环境镜像：会话、故障、追踪等）
- `manage_backend` — 18 张表（管理后台：企业、用户、菜谱、命令等）
- `schedule` — 25 张表（调度系统：烹饪日志、商户信息、订单等）
- `schedule2` — 23 张表（调度系统 v2：同上，数据可能更新）

### 下一步
- 验证核心业务表的查询链路
- 建立常用查询模板库
- 与用户开始实际数据检索工作
