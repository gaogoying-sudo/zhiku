# 智库控制台项目包说明

这个包用于交接项目源码、部署脚本和数据库连接能力。为了避免泄露敏感信息，包内不会包含真实数据库密码、Web 登录密码、服务器密码、历史导出文件或本地缓存。

## 包内包含

- `deploy/`：前后端部署目录，包含 FastAPI、Nginx、Docker Compose。
- `scripts/`：只读数据库查询与导出脚本。
- `docs/`：项目背景、架构、共享上下文和任务记录。
- `config/db_config.env.example`：本地脚本连接只读库的配置模板。
- `deploy/.env.example`：云端/本地 Docker 部署配置模板。

## 首次运行

1. 复制部署环境变量：

```bash
cp deploy/.env.example deploy/.env
```

2. 在 `deploy/.env` 中填入真实的只读库地址、端口、账号、密码，以及 Web 登录账号。

3. 启动服务：

```bash
cd deploy
docker compose up -d --build
```

4. 打开：

```text
http://localhost:8085
```

## 本地查询脚本

如需直接运行 `scripts/` 下的查询脚本：

```bash
cp config/db_config.env.example config/db_config.env
```

然后在 `config/db_config.env` 中填写只读库配置。

## 安全约定

- 不要把 `deploy/.env`、`config/db_config.env`、`output/`、`handover/` 上传到公开仓库或群聊。
- 数据库账号必须是只读账号。
- 导出的 Excel/CSV 通常包含敏感业务数据，按内部资料处理。
- 若交接给新同事，建议通过单独安全渠道发送真实 `.env` 内容，而不是放入项目压缩包。
