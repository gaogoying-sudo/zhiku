# 智库 Agent 进度日志

## 2026-06-07

### 云端部署：安全治理看板
- 操作人/会话：Codex / Claude。
- 目标：把起火风险从"事后分析"变成"自动扫描 + 全局可见"，新增安全总览和告警明细两个页面。
- 本次修改：
  - 新增 4 张 MySQL 表：`safety_scan_runs`、`safety_scan_alerts`、`safety_daily_stats`（+ 已有 `cook_jobs` 复用）。
  - 后端新增 5 个 API：`GET /api/safety/overview`、`GET /api/safety/alerts`、`POST /api/safety/scan`、`POST /api/safety/alerts/{id}/dismiss`、`GET /api/safety/trends`。
  - 安全扫描规则：实测高温 > 330℃（高危）、280-330℃（中危）、投料间隔 > 60s、缺功率采样、缺温度样本。
  - 前端新增「安全治理」导航组：安全总览（温度分布柱状图、高危设备/菜谱 TOP 10、摘要卡片）和告警明细（按风险等级/规则/SN 筛选、分页、dismiss 处理、跳转设备）。
  - 新增 `safety_daily_stats` 每日聚合表，支持按天趋势查询。
  - 同步 `deploy/frontend/index.html -> deploy/frontend/app.html`。
- 验证结果：
  - `make check` 通过。
  - `make deploy` 成功，云端容器已重建启动。
  - `make smoke SMOKE_KEYWORD=安全总览 SMOKE_SN=0105222506020185` 通过。
  - API 测试通过：771 作业，5 条临界高温（≥330℃），68 条警示（300-330℃），历史最高 339℃，活跃告警 646 条。
- 说明：
  - 安全扫描基于本地 MySQL `cook_jobs` 表，覆盖范围取决于已解析入库的日志包数量。当前仅 1 台设备数据，需持续解析更多设备日志以扩大覆盖面。
  - 告警规则目前是离线批量扫描（按需触发），后续可做成后台定时任务。
  - 温度阈值 330/280℃ 是工程初始值，需结合真实起火数据持续校准。
- 解除锁定：安全风险可观测性从零到一。

### 云端部署：能量单位统一选择
- 操作人/会话：Codex。
- 目标：按用户补充要求，把页面里分散出现的 `kJ / kWh / kW·s` 统一成可选单位，避免同一页面混用多种能量口径。
- 本次修改：
  - 将原功率诊断的能量单位选择升级为全局共享单位，支持 `kJ 千焦`、`kWh 千瓦时`、`kW·s 千瓦秒`。
  - 热物性库新增能量单位选择，升温能量速查和明细表吸热值跟随切换。
  - 热过程分析新增能量单位选择，实际/指令能量、累计入热、投料吸热、散热损失、阶段能量和风险窗口能量统一展示。
  - 温度诊断展开图里的能量值也改为跟随统一单位。
  - 默认单位调整为 `kJ`，便于热过程和投料吸热分析。
  - 同步 `deploy/frontend/index.html -> deploy/frontend/app.html`。
- 验证结果：
  - `make check` 通过。
  - `make deploy` 成功。
  - `make smoke SMOKE_KEYWORD=能量单位 SMOKE_SN=0105222506020185` 通过。
- 解除锁定：能量单位展示。

### 云端部署：热物性库与单菜热模型底座
- 操作人/会话：Codex。
- 目标：按用户要求搭建单菜温度预测的基础数据底座，并优化热过程分析中食材入锅后的能量模型。
- 本次修改：
  - 新增 `管理与治理 / 热物性库` 页面，展示食材分类、别名、比热容、水分/油脂比例、升温能量、烟点/沸点、闪点、自燃点、风险分类和置信度。
  - 内置第一版工程种子库，覆盖水/汤汁、水淀粉、植物油、猪油、牛油、鸡/牛/猪/蛋/豆腐、蔬菜、干辣椒、花椒、糖、盐、酱油、醋/料酒等常见物料。
  - 热过程分析的投料识别改为优先匹配热物性库，不再只靠硬编码分类比热。
  - 温度预测曲线新增累计入热、投料吸热和散热损失记录，并在页面新增三张解释卡片。
  - 食材热负载表新增燃烧参考列，油脂类风险会根据烟点/闪点/自燃点参考触发风险标签。
  - 新增 `docs/THERMAL_INGREDIENT_KNOWLEDGE_BASE.md`，明确字段、边界和后续入库建议。
  - 同步 `deploy/frontend/index.html -> deploy/frontend/app.html`。
- 验证结果：
  - `make check` 通过。
  - `make deploy` 成功，云端容器已重建启动。
  - `make smoke SMOKE_KEYWORD=热物性库 SMOKE_SN=0105222506020185` 通过：线上 HTML 400679 bytes，登录 200，设备轻量匹配结果 1。
- 说明：
  - 本轮数据是工程参考种子库，不是最终安全阈值；油脂烟点、闪点、自燃点必须结合公司实验和真实菜谱复盘持续校准。
  - 下一阶段建议把热物性库迁移到本地 MySQL，并让菜谱解析/热过程分析统一读库。
- 解除锁定：热物性库/热过程分析前端模型。

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

## 2026-06-06

### PR #1 功率诊断人工菜谱筛选复核部署
- 操作人/会话：Codex，本地接手 ChatGPT PR #1。
- 目标：跑通 ChatGPT → GitHub PR → Codex 复核/修补/部署流程，并让功率诊断支持人工选择某一道菜。
- 变更文件：
  - `deploy/frontend/index.html`
  - `deploy/frontend/app.html`
  - `deploy/frontend/nginx.conf`
  - `docs/CHANGELOG_REQUESTS.md`
  - `docs/CODEX_HANDOFF_TEMPLATE.md`
- 技术结论：
  - 不接受 ChatGPT 初版“独立 JS 补丁 + Nginx sub_filter 注入”方案，原因是依赖线上 Nginx 模块能力，且本地/线上入口容易不一致。
  - 已把筛选逻辑直接合并进主前端入口，并删除 `deploy/frontend/power-diagnosis-recipe-filter.js`。
  - `make check` 已同步 `index.html` 到 `app.html`。
- 功能结果：
  - 功率诊断页新增 `人工选择菜谱` 下拉框。
  - 选项来自 `cookTemperatureCooks`，按 `recipe_id / recipe_name` 聚合并显示次数。
  - 筛选后联动可诊断作业数量、当前能量指标、日志包内烹饪作业表、功率曲线和步骤功率/能量表。
  - 读取结构化数据或重新解析日志包时会清空旧菜谱选择，避免跨包残留。
- 部署命令：
  - `make check`
  - `git push origin feature/power-diagnosis-recipe-filter`
  - `make deploy`
- 验证结果：
  - `make check` 通过。
  - `make smoke SMOKE_KEYWORD="人工选择菜谱" SMOKE_SN="0105222506020185"` 通过：线上 HTML 341221 bytes，关键词命中，登录 200，设备查询 200，匹配设备 1。
- 遗留问题：
  - 该 PR 尚未合并到 `main`；当前线上已经部署 PR 分支代码，后续如接受应合并 PR 或同步 main。
- 解除锁定：功率诊断前端筛选模块。

## 2026-06-07

### 单菜热过程分析 v0.1
- 操作人/会话：Codex。
- 目标：针对单台设备、单次烹饪、单道菜，建立“理论能量输入 -> 投料热负载 -> 预测锅温 -> 实测偏差 -> 安全风险窗口”的第一版工作台。
- 变更文件：
  - `deploy/frontend/index.html`
  - `deploy/frontend/app.html`
  - `docs/THERMAL_PROCESS_ANALYSIS_PRD.md`
- 功能结果：
  - 新增 `日志诊断 / 热过程分析` 页面。
  - 复用现有日志包多选、温度诊断和功率诊断解析链路，不新增后端接口和数据库表。
  - 支持选择单道菜/单次作业。
  - 支持模型参数：室温/食材初温、热效率、锅体等效热容、散热系数、初始锅温。
  - 支持 `包含当前作业内热锅/润锅` 开关；关闭时从第一个非热锅/润锅阶段重新计算能量和预测曲线。
  - 展示实际输出能量、指令能量、预测最高锅温、实测最高锅温。
  - 展示预测锅温、实测锅温、实际功率、指令功率曲线，并标注热锅、投油、第一主料节点。
  - 展示动作阶段能量、投料热负载、偏差解释和安全风险标签。
- 技术口径：
  - 第一版是可解释工程近似模型，不是最终安全阈值。
  - 功率优先使用 `actual_power_kw`，缺失时退回 `command_power_kw`。
  - 投料从菜谱步骤/android 动作文本中按重量解析，按默认比热容估算吸热。
  - 外部润锅关联字段表、锅型/锅龄/锅黑/红外状态暂未接入。
- 部署命令：
  - `make check`
  - `make deploy`
  - `git push -u origin codex/thermal-process-analysis`
- 验证结果：
  - `make check` 通过。
  - `make deploy` 成功。
  - `make smoke SMOKE_KEYWORD="热过程分析" SMOKE_SN="0105222506020185"` 通过：线上 HTML 378026 bytes，关键词命中，登录 200，设备查询 200，匹配设备 1。
  - 已创建 PR #2：https://github.com/gaogoying-sudo/zhiku/pull/2。
- 遗留问题：
  - PR #2 基于上一轮已部署但未合并的 PR #1 继续开发；如果 PR #1 未合并，PR #2 会包含其基础变更。
  - GitHub 返回 `mergeable=false`，本地 `git merge-tree` 未发现冲突，可能与 PR #1 未合并或 GitHub 状态刷新有关，后续合并前需要再看一次。
- 解除锁定：热过程分析前端模块。

### 热物性库数据库底座 v0.2
- 操作人/会话：Codex。
- 目标：把“热物性库”从前端 21 条种子数据升级为云端本地数据库底座，后续作为热过程分析、温度预测和起火风险筛选的核心资产复用。
- 变更文件：
  - `deploy/backend/main.py`
  - `deploy/frontend/index.html`
  - `deploy/frontend/app.html`
  - `docs/THERMAL_INGREDIENT_KNOWLEDGE_BASE.md`
  - `docs/progress.md`
- 新增本地表：
  - `ingredient_thermal_properties`
  - `ingredient_thermal_sync_runs`
- 数据来源：
  - `btyc.base_ingredients` 全量基础食材。
  - `manage_backend.recipe_detail.cooking_ingredient` 最近 20,000 条菜谱配料 JSON。
  - `manage_backend.main_recipe` 菜谱名称和分类上下文。
- 功能结果：
  - 新增 `GET /api/thermal-knowledge`，支持关键词、分类、燃烧风险、分页查询。
  - 新增 `POST /api/thermal-knowledge/sync`，admin 可触发源库同步。
  - 前端 `热物性库` 页面优先读取云端本地数据库；未同步或接口异常时才使用前端种子数据兜底。
  - 页面展示最近同步时间、基础食材数量、菜谱配料引用次数，并支持 `同步源库 / 查询底座 / 清筛选`。
  - 规则归类 8 个标准大类：`未分类`、`蔬菜类`、`肉蛋类`、`油脂`、`液体调料`、`调料`、`水/汤汁`、`干货/香辛料`。
- 线上同步结果：
  - 基础食材源数据：54,224 行。
  - 本地食材底座：52,446 条。
  - 菜谱配料样本：20,000 条 `recipe_detail`。
  - 菜谱配料引用聚合：236,112 次。
  - `牛油` 查询返回 38 条，能识别为 `油脂 / 可燃油脂`，并带菜谱出现次数和累计用量。
- 部署命令：
  - `make check`
  - `make deploy`
  - 线上 admin 调用 `/api/thermal-knowledge/sync?recipe_limit=20000`
- 遗留问题：
  - `recipe_detail` 总量约 226,840 条，当前同步接口默认取最近 20,000 条，后续应升级为后台队列分批全量同步。
  - 源库分类字段存在数字编码，当前保留原始字段并用名称规则推断标准分类；后续需要人工映射和实验/供应商数据校准。
- 解除锁定：热物性库数据库底座。

### 热物性库分类与可信度修正
- 操作人/会话：Codex。
- 背景：用户指出页面中大量香辛料显示 `260℃` 自燃点不可信，且食材名称归类粗糙。
- 修正内容：
  - 删除 `干货/香辛料` 默认 `260℃` 自燃点，不再展示无来源依据的燃点/自燃点。
  - 油脂不再默认写入烟点/闪点/自燃点，统一标记为 `可燃油脂/温度待校准`。
  - 比热容、水分、油脂比例允许为空；前端空值显示 `待校准`，不再被强行算成 `0 kJ`。
  - 修正老表结构：`specific_heat_kj_kg_c / water_fraction / oil_fraction` 允许 NULL。
  - 扩展规则分类：鲜椒/蔬菜、香辛料/干货、液体调料、酱料/发酵调料、油脂、水产、主食/淀粉食材、蛋奶豆制品、粉类/增稠、糖类、盐味精/基础调味等。
  - 增加中英繁体和海外菜谱常见别名：`Soy Sauce / 醬油 / water / oil / Onion / Beef / Rice / Prawn / Fettucine / MSG / salt / sugar` 等。
  - 增加源库数字分类兜底映射，例如 `3/1` 蔬菜、`6/43` 香辛料、`6/40` 酱料、`4/46/47` 油脂。
- 线上同步结果：
  - 本地食材底座：52,449 条。
  - 最近 20,000 条菜谱配料聚合：236,859 次引用。
  - 未分类从 24,023 条降至 14,614 条。
  - 抽样验证：`樟树港辣椒 -> 鲜椒/蔬菜`，`八角 -> 香辛料/干货，燃点待测`，`酱油 -> 液体调料`，`牛油 -> 油脂，温度待校准`。
- 验证结果：
  - `make check` 通过。
  - `make deploy` 成功。
  - 线上 `/api/thermal-knowledge/sync?recipe_limit=20000` 成功。
  - `make smoke SMOKE_KEYWORD=热物性库 SMOKE_SN=0105222506020185` 通过。
- 遗留问题：
  - 剩余未分类多为源库低频、无语义、品牌名或外语名称，不能继续用硬猜方式强制归类；建议下一步做 `待归类队列 + 人工确认 + 映射表`。
- 解除锁定：热物性库分类规则。
