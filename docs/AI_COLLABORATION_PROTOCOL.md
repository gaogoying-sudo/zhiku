# 智库设备看板 AI 协作协议

更新时间：2026-06-05

用途：给 Codex、agy 或其他 AI/开发者在同一个项目里协作时使用。任何新对话、新工具、新同事接手前，先读本文件，再读 `docs/SHARED_CONTEXT.md` 和 `docs/progress.md`。

## 1. 协作目标

这个项目不是一次性脚本，而是一个已经在线运行的内部系统。协作目标是：

- 不丢需求背景。
- 不污染本地和云端环境。
- 不让两个 AI 对同一功能做相互覆盖的改动。
- 每次云端操作都可追溯。
- 线上出问题时，能从文档和日志快速恢复现场。

## 2. 单一事实来源

所有 AI 都按下面顺序读取信息：

1. `docs/AI_COLLABORATION_PROTOCOL.md`：协作规则、交接格式、部署记录要求。
2. `docs/SHARED_CONTEXT.md`：项目背景、现有功能、关键表、风险和近期状态。
3. `docs/progress.md`：按日期记录已完成事项、线上变更、验证结果和遗留问题。
4. `handover/02-DEPLOYMENT-AND-RECOVERY.md`：部署与恢复步骤。
5. `handover/01-SECRETS-AND-ACCOUNTS.md`：敏感账号密码，只能本地受控阅读，不能复制到聊天、提交到 Git 或打包外发。

代码事实来源：

- 后端主文件：`deploy/backend/main.py`
- 前端主文件：`deploy/frontend/index.html`
- 前端备用入口：`deploy/frontend/app.html`
- Compose 编排：`deploy/docker-compose.yml`
- 云端路径：`/opt/zhiku-dashboard`
- 线上地址：`http://82.156.187.35:8085`

## 3. 防污染原则

每次开始工作前必须做：

```bash
git status --short
```

处理原则：

- 看到已有未提交改动，默认认为是用户或另一个 AI 的工作，不能回滚。
- 只改和本次需求直接相关的文件。
- 如果必须碰同一个文件，先用 `rg`、`sed` 读上下文，理解现有改动后再补丁式修改。
- 不执行 `git reset --hard`、`git checkout --` 这类破坏性命令，除非用户明确要求。
- 不把 `deploy/.env`、`handover/`、真实账号密码、数据库连接明文提交或打包给外部。

## 4. 开发标准流程

每次功能开发按这个流程走：

1. 读上下文：
   - `rg` 搜索相关函数、页面区域、接口路径。
   - 后端优先看 `deploy/backend/main.py`。
   - 前端优先看 `deploy/frontend/index.html`。

2. 改代码：
   - 手工编辑用 `apply_patch`。
   - 前端改完 `index.html` 后，必须同步：

```bash
cp deploy/frontend/index.html deploy/frontend/app.html
```

3. 本地检查：

```bash
make check
```

4. 部署前确认：
   - 确认没有把缓存、数据库目录、Mac 临时文件带上云端。
   - 确认没有把敏感文件输出到聊天或日志。

## 5. 云端部署流程

优先使用标准脚本：

```bash
make deploy
```

脚本会从本地敏感交接文件读取 SSH/sudo 信息，不会打印明文密码。

如需手工排障，从本地 `deploy` 目录上传到云端，必须排除缓存和数据库目录：

```bash
COPYFILE_DISABLE=1 tar --exclude='api_cache' --exclude='db_data' --exclude='._*' -czf - . \
  | ssh -o StrictHostKeyChecking=no ubuntu@82.156.187.35 \
  'mkdir -p /opt/zhiku-dashboard && tar --no-same-owner --warning=no-unknown-keyword -xzf - -C /opt/zhiku-dashboard'
```

然后在云端重建：

```bash
ssh -tt -o StrictHostKeyChecking=no ubuntu@82.156.187.35 \
  'cd /opt/zhiku-dashboard && sudo -S docker compose up -d --force-recreate --build'
```

说明：

- SSH 和 sudo 密码只从 `handover/01-SECRETS-AND-ACCOUNTS.md` 本地读取，不在回复里复述。
- 如果用脚本自动输入密码，输出中必须避免回显密码。
- 部署完成后必须做线上验证。

## 6. 线上验证三步

1. 验前端版本或关键文本：

```bash
make smoke SMOKE_KEYWORD=关键文本
```

2. 验容器状态和后端日志：

```bash
make status
```

3. 验接口：
   - 先登录拿 token。
   - 再调用本次修改相关 API。
   - 验证至少包括 HTTP 状态码、核心字段、返回体大小或关键数量。

作业温度结构化功能常用冒烟：

- `/api/cook-temperature-structured/{sn}?day=YYYY-MM-DD&limit=600`
- 关注字段：`cook_count`、`summary_day.detail_included`、返回体大小、是否 200。

## 7. 云端操作记录规范

每次做过云端操作后，必须在 `docs/progress.md` 追加一条，格式如下：

```markdown
## YYYY-MM-DD

### 云端操作
- 操作人/会话：Codex 或 agy。
- 目标：一句话说明为什么操作云端。
- 变更文件：列出核心文件。
- 部署命令：上传 + docker compose rebuild。
- 验证结果：列出 curl/API/容器验证结果。
- 遗留问题：没有就写“暂无”。
```

如果只是本地分析没有部署，也要写：

```markdown
### 本地分析
- 结论：
- 未改代码：
- 建议下一步：
```

## 8. 需求进度同步规范

每个需求要有状态：

- `待确认`：只做了方案，未改代码。
- `开发中`：正在改代码，未部署。
- `已部署待验收`：已上线，等待用户体验确认。
- `已验收`：用户明确确认。
- `挂起`：方向暂缓或被新需求覆盖。
- `失败/回滚`：线上不可用或方案废弃。

记录内容必须包含：

- 用户原始目标。
- 当前实现范围。
- 未覆盖范围。
- 关键接口/表/文件。
- 是否已部署。
- 线上验证方式。

## 8.1 ChatGPT 协作反馈闭环

当需求来自 ChatGPT 的 GitHub PR，或本轮工作用于验证 ChatGPT → GitHub PR → Codex 复核/部署流程时，Codex 收尾必须额外输出一段“可转发给 ChatGPT 的反馈”。

这段反馈至少包含：

- PR 链接和分支。
- Codex 是否接受 ChatGPT 初版方案。
- Codex 做了哪些修补。
- 哪些内容真正节省了 Codex 的分析成本。
- 哪些内容导致 Codex 额外返工。
- 下轮 ChatGPT 必须怎么交付，尤其包括：
  - 优先直接改主代码，不用运行时补丁或 Nginx 注入绕过主入口。
  - 前端改 `deploy/frontend/index.html` 时必须同步 `deploy/frontend/app.html`，或明确交给 Codex 运行 `make check`。
  - 如果不能运行检查，必须明确写“未运行 make check / 未部署 / 未验证”。
  - 不接触 `.env`、真实账号密码、数据库明文和部署凭证。

固定模板见 `docs/CODEX_HANDOFF_TEMPLATE.md` 的“Codex 复核后给 ChatGPT 的反馈模板”。

## 9. Codex 与 agy 分工建议

为了减少互相覆盖：

- Codex 更适合做：现有代码排错、云端部署、日志解析链路、后端状态机、复杂接口修复。
- agy 更适合做：产品化整理、模块拆分方案、UI/交互结构优化、文档化和长期重构。
- 如果两边都要改同一个功能，先在 `docs/progress.md` 写一句“当前锁定模块”，完成后再解除。
- 锁定模块部署并验证完成后，必须在 `docs/progress.md` 写明“解除锁定：模块名”，让下一个接手者知道可以继续改。

建议锁定粒度：

- `前端/作业温度`
- `后端/结构化解析库`
- `后端/菜谱 Top 榜`
- `前端/设备概览`
- `部署/运维`
- `文档/交接`

敏感配置保护补充：

- `.env`、`handover/01-SECRETS-AND-ACCOUNTS.md`、真实数据库连接、Web 登录密码、SSH 密码都只允许本地受控读取。
- 任何 AI 不得把这些内容复制到聊天、PR、公开仓库、压缩包或日志输出里。
- 如果需要说明部署能力，只描述“从本地敏感交接文件读取”，不复述明文。

## 10. 当前重点背景

截至 2026-06-05，近期重点在“作业温度”和“日志结构化入库”：

- 已建立本地 MySQL 结构化缓存思路，避免每次重复下载、解压、解析 ZIP。
- 关键表包括：
  - `watched_devices`
  - `device_log_packages`
  - `cook_jobs`
  - `cook_temperature_samples`
  - `cook_action_events`
  - `cook_power_events`
- 日志包状态需要区分：
  - `可下载`
  - `已下载`
  - `排队中`
  - `解析中`
  - `已解析`
  - `已入库`
  - `无生产记录`
  - `解析失败`
- 最近修过一个线上问题：点击“读取结构化数据”白屏，原因是前端把结构化按日期结果当作单日志包结果读取，缺少 `file` 空值保护。
- 已加策略：作业多的日期默认返回轻量列表和统计，不一次性返回全部明细，避免浏览器白屏。

## 11. 给 agy 的接手说明

agy 接手时请按下面动作开始：

1. 先读 `docs/AI_COLLABORATION_PROTOCOL.md`、`docs/SHARED_CONTEXT.md`、`docs/progress.md`。
2. 执行 `git status --short`，不要覆盖未知改动。
3. 如果要开发，先说明锁定模块。
4. 修改后先本地检查，再部署。
5. 部署后按“三步验证”做冒烟。
6. 最后把本次操作写回 `docs/progress.md`。

这套规则的目的不是增加流程，而是保护线上系统和需求上下文。后续任何 AI 都可以继续开发，但必须留下清楚的脚印。
