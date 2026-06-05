# 自动化运行手册

更新时间：2026-06-06

用途：把重复的检查、部署、冒烟和记录动作固化，减少 Codex、agy 或其他 Agent 在机械操作上消耗 token。

## 常用命令

### 本地检查

```bash
make check
```

等价于：

- 同步 `deploy/frontend/index.html` 到 `deploy/frontend/app.html`
- 编译检查 `deploy/backend/main.py`
- 抽取前端内联脚本到 `/tmp/zhiku-inline.js`
- 运行 `node --check`
- 删除 `/tmp/zhiku-inline.js`
- 检查敏感文件是否被 Git 跟踪

### 云端部署

```bash
make deploy
```

等价于：

- 自动读取本地 `handover/01-SECRETS-AND-ACCOUNTS.md` 中的 SSH 信息
- 打包 `deploy/`
- 排除 `api_cache`、`db_data`、`._*`、`.DS_Store`、`__pycache__`
- 上传到 `/opt/zhiku-dashboard`
- 执行 `docker compose up -d --force-recreate --build`

脚本不会打印明文密码。

### 线上冒烟

```bash
make smoke
```

默认检查：

- 线上 HTML 可访问
- 页面包含 `appVersion`
- admin 登录接口返回 200

可以指定关键词和设备：

```bash
make smoke SMOKE_KEYWORD=功率诊断 SMOKE_SN=0105222506020185
```

这里的 `SMOKE_SN` 走轻量 `/api/devices/search`，只确认设备可匹配，不拉完整设备报告。完整设备报告可能很大，需要人工排障时再直接运行：

```bash
scripts/smoke_cloud.py --keyword 功率诊断 --sn 0105222506020185 --full-device
```

### 完整发布

```bash
make release SMOKE_KEYWORD=功率诊断 SMOKE_SN=0105222506020185
```

等价于：

```bash
make check
make deploy
make smoke
```

### 云端状态

```bash
make status
```

显示：

- `docker compose ps`
- `zhiku-api` 最近 40 行日志

### 追加进度模板

```bash
make progress
```

会向 `docs/progress.md` 追加固定格式模板。完成部署后必须补齐内容。

## 本地小模型委托

本机 Ollama 可承担低风险机械总结。默认使用 `qwen2.5:3b`：

```bash
make delegate-check
make delegate-smoke SMOKE_KEYWORD=功率诊断 SMOKE_SN=0105222506020185
make delegate-status
```

或直接调用：

```bash
python3 scripts/local_agent_delegate.py --mode run --command check --task "本地检查并总结"
```

如需更强模型：

```bash
LOCAL_AGENT_MODEL=qwen3:14b make delegate-smoke SMOKE_KEYWORD=功率诊断
```

限制：

- 本地小模型只总结和执行 allowlist 命令。
- 默认不允许部署；部署/发布必须显式 `--allow-deploy`。
- Codex 仍负责最终验收和安全判断。

## 给便宜 Agent 的边界

允许做：

- 运行 `make check`
- 运行 `make smoke`
- 在明确授权下运行 `make deploy` 或 `make release`
- 根据模板补 `docs/progress.md`
- 把失败输出原样交给 Codex

不要做：

- 自行修改 `deploy/backend/main.py` 的解析器、SQL、缓存、队列逻辑
- 自行修改 `deploy/.env` 或 `handover/`
- 自行处理 SSH 密码或把敏感信息贴到聊天里
- 部署失败后盲目改核心代码

## 推荐协作方式

复杂需求由 Codex 完成核心实现。

简单发布交给自动化：

```text
1. Codex 改代码并通过 make check。
2. 便宜 Agent 或用户运行 make release。
3. 如果失败，把完整错误贴回给 Codex。
4. 成功后用 make progress 追加记录。
```
