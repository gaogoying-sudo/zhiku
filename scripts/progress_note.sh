#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TODAY="$(date +%F)"
TITLE="${1:-云端操作}"

cat >> docs/progress.md <<EOF

## ${TODAY}

### ${TITLE}
- 操作人/会话：
- 目标：
- 变更文件：
- 部署命令：\`make release\` / \`make deploy\` / 其他：
- 验证结果：
- 遗留问题：
- 解除锁定：
EOF

echo "Appended progress template to docs/progress.md"
