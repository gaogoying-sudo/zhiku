# GitHub 自动化说明

更新时间：2026-06-06

仓库地址：`git@github.com:gaogoying-sudo/zhiku.git`

## 当前连通性

- 本机 SSH 到 GitHub 可用。
- 本地 `origin` 已指向该仓库。
- 远端 `main` 可 fetch / ls-remote。

## 已新增的免费自动化

新增 GitHub Actions：

```text
.github/workflows/ci.yml
```

触发方式：

- push 到 `main`
- Pull Request
- 手动 `workflow_dispatch`

检查内容：

- Python 后端语法：`python -m py_compile deploy/backend/main.py`
- 前端内联 JS：抽取 `<script>` 后 `node --check`
- 检查 `deploy/frontend/index.html` 和 `deploy/frontend/app.html` 是否一致
- 防敏感文件误入仓库：`deploy/.env`、`handover/01-SECRETS-AND-ACCOUNTS.md`、`deploy/api_cache`、`deploy/db_data`

这一步不需要 GitHub Secrets，不涉及云服务器和数据库密码，适合先免费承担机械检查。

## 暂不建议立刻做 GitHub 自动部署

原因：

- 云端部署需要 SSH/sudo 信息。
- 项目运行还依赖 `deploy/.env` 里的数据库和认证配置。
- 直接把这些密钥放 GitHub Secrets 可以做，但需要你在 GitHub 页面手工配置，且要明确权限边界。

更稳的两阶段方案：

1. 现在：GitHub 只做 CI 检查，部署仍由本机 `make release` 完成。
2. 后续：如果你愿意配置 GitHub Secrets，再加手动触发的 deploy workflow。

## 推荐日常流

开发时：

```bash
make check
```

准备推 GitHub 前：

```bash
git status --short
git add <本次确认要提交的文件>
git commit -m "..."
git push origin main
```

GitHub 会自动跑 CI。CI 通过后，再由本机部署：

```bash
make release SMOKE_KEYWORD=功率诊断 SMOKE_SN=0105222506020185
```

## 如果未来要 GitHub 自动部署

需要你在 GitHub 仓库配置 Secrets：

- `ZHIKU_SSH_HOST`
- `ZHIKU_SSH_USER`
- `ZHIKU_SSH_KEY` 或 `ZHIKU_SSH_PASSWORD`
- `ZHIKU_SUDO_PASSWORD`

我更建议使用 SSH key，而不是密码。这样可以撤销、轮换，也更适合自动化。
