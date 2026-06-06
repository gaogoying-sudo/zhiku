# 智库需求与变更记录

## 2026-06-06 23:05 CST - 功率诊断增加人工菜谱筛选

### 用户原始意图

- 在 `功率诊断` 页面中，让“能量输入/功率诊断”结果支持由人工选择某一道菜。
- 本需求本身较小，主要用于跑通 ChatGPT → GitHub 分支 → PR → Codex 复核/部署的协作流程，并观察 Codex 后续 token 开销。

### 本轮决策

- 不改后端、不改数据库、不改缓存、不改权限、不改部署凭证。
- 只在前端增加一个 `人工选择菜谱` 下拉筛选。
- 该筛选基于已解析出的 `cookTemperatureCooks`，按 `recipe_id / recipe_name` 聚合生成菜谱选项。
- 筛选后影响 `filteredPowerDiagnosisCooks`，即上方能量指标、功率曲线、日志包内烹饪作业表、步骤功率与能量表均跟随当前选中菜谱变化。

### 改动范围

- 前端：新增 `deploy/frontend/power-diagnosis-recipe-filter.js`，通过 Vue 初始化前补丁方式扩展 `功率诊断` 的筛选状态、筛选计算和模板控件。
- Nginx：更新 `deploy/frontend/nginx.conf`，在 HTML 返回时注入新增前端补丁脚本。
- 文档：新增本记录。

### 不做事项

- 不改 `deploy/backend/main.py`。
- 不调整功率/能量计算口径。
- 不新增 API。
- 不改生产服务器。
- 不处理 `.env`、账号、密钥或部署凭证。

### 验收方式

1. 进入设备 `功率诊断` 页面。
2. 选择一个或多个日志包并点击 `解析功率`。
3. 在 `单次烹饪功率曲线` 上方看到 `人工选择菜谱` 下拉框。
4. 选择某一道菜后：
   - `可诊断作业` 数量只统计该菜。
   - 当前实际能量、当前指令能量、能量跟随率随该菜的当前作业变化。
   - `日志包内烹饪作业` 表只显示该菜。
   - 曲线和步骤功率表随当前选中作业变化。
5. 选择 `全部菜谱` 后恢复原列表。

### 风险点

- 这是为了最小化本轮改动而采用的前端补丁方案，没有直接改动大型单文件 `deploy/frontend/index.html` / `deploy/frontend/app.html`。
- 如果后续 Codex 认为应严格落实“index.html 与 app.html 同步修改”，建议把本补丁合并回两个 HTML 文件，并移除 Nginx `sub_filter` 注入方式。
- 该方案依赖 Nginx `sub_filter` 模块；Codex 部署前应确认线上 Nginx 镜像支持该指令。

### 后续待办

- 若本轮 PR 验证通过，可在下一轮把该筛选正式合并进 `index.html` 与 `app.html` 模板和 Vue data/computed/methods，减少注入式补丁。
