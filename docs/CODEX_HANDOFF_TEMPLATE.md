# Codex 承接交接模板

更新时间：2026-06-06 23:34 CST
适用项目：`gaogoying-sudo/zhiku`

本文件用于固定 ChatGPT 浏览器开发完成后的交接输出格式。后续每一轮通过 ChatGPT 创建分支/PR 后，都必须给用户一段可以直接复制给 Codex 的承接文本。

---

## 1. 固定规则

每轮开发完成后，ChatGPT 最终回复必须包含：

```text
【Codex 承接说明】

项目仓库：git@github.com:gaogoying-sudo/zhiku.git
PR：<PR 链接>
分支：<branch>

本轮需求：
<用产品语言说明用户要什么>

本轮已经完成：
- ...

改动文件：
- ...

请 Codex 重点复核：
1. ...
2. ...

请 Codex 执行：
1. 拉取 PR 分支。
2. 查看 diff。
3. 如可运行，请执行 make check。
4. 按验收方式做本地/云端 smoke。
5. 如发现问题，在该 PR 分支继续修补，不要另开无关分支。
6. 确认无问题后，再部署到服务器。

验收方式：
1. ...

风险点：
- ...

本轮未做：
- ...
```

---

## 2. 使用原则

- 交接文本要能让 Codex 不读完整聊天记录也能接上。
- 交接文本必须包含 PR、分支、改动文件、验收方式和风险点。
- 如果本轮未本地验证，必须明确写出。
- 如果涉及后端、数据库、缓存、权限、部署、安全，必须明确列出。
- 如果要求 Codex 继续修补，应明确要求“在该 PR 分支继续修补”，避免另起分支导致上下文断裂。

---

## 3. 本轮样例：功率诊断人工菜谱筛选

```text
【Codex 承接说明】

项目仓库：git@github.com:gaogoying-sudo/zhiku.git
PR：https://github.com/gaogoying-sudo/zhiku/pull/1
分支：feature/power-diagnosis-recipe-filter

本轮需求：
在“功率诊断”页面里，让能量/功率分析结果支持人工选择某一道菜。用户希望用这个小需求跑通 ChatGPT → GitHub PR → Codex 复核/部署的协作流程。

本轮已经完成：
- 新增 `人工选择菜谱` 筛选能力。
- 菜谱下拉选项来自已解析出的 `cookTemperatureCooks`，按 `recipe_id / recipe_name` 聚合。
- 选择某道菜后，`可诊断作业`、当前能量指标、作业表、功率曲线、步骤功率与能量表都会跟随筛选变化。
- 选择 `全部菜谱` 后恢复原列表。

改动文件：
- deploy/frontend/power-diagnosis-recipe-filter.js
- deploy/frontend/nginx.conf
- docs/CHANGELOG_REQUESTS.md
- docs/CODEX_HANDOFF_TEMPLATE.md

请 Codex 重点复核：
1. 当前线上 Nginx 镜像是否支持 `sub_filter` 指令。
2. `power-diagnosis-recipe-filter.js` 是否能在 Vue `createApp(...)` 前完成模板注入和 computed 覆盖。
3. 是否接受本轮“独立 JS 补丁 + Nginx 注入”的轻量方案。
4. 如果不接受，请把补丁逻辑合并回 `deploy/frontend/index.html` 和 `deploy/frontend/app.html`，并移除 `nginx.conf` 的 `sub_filter` 注入。

请 Codex 执行：
1. 拉取 PR #1 分支 `feature/power-diagnosis-recipe-filter`。
2. 查看 diff。
3. 如可运行，请执行 `make check`。
4. 本地或云端验证“功率诊断”页面。
5. 如发现问题，在该 PR 分支继续修补，不要另开无关分支。
6. 确认无问题后再部署到服务器。

验收方式：
1. 进入任意设备的 `功率诊断` 页面。
2. 选择一个或多个日志包，点击 `解析功率`。
3. 在 `单次烹饪功率曲线` 的筛选区看到 `人工选择菜谱` 下拉框。
4. 选择某一道菜后：
   - `可诊断作业` 数量只统计该菜。
   - 当前实际能量、当前指令能量、能量跟随率随当前可见作业变化。
   - `日志包内烹饪作业` 表只显示该菜。
   - 曲线和步骤功率表跟随当前选中作业变化。
5. 选择 `全部菜谱` 后恢复原列表。

风险点：
- 本轮没有直接修改 `deploy/frontend/index.html` 和 `deploy/frontend/app.html`，而是用独立 JS 补丁和 Nginx `sub_filter` 注入。
- 该方案依赖 Nginx `sub_filter`；如果线上镜像不支持，应改成直接同步修改两个 HTML 文件。
- 当前 ChatGPT 环境未能执行本地 `make check`，也未运行 Docker/Nginx 容器。

本轮未做：
- 未改后端。
- 未改数据库。
- 未改缓存策略。
- 未改权限。
- 未处理 `.env`、账号、密钥或部署凭证。
- 未直接部署生产服务器。
```
