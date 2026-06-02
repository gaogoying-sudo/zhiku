# 智库 Agent - 项目索引

## 基本信息
- **称呼：** 「智库」
- **目标：** 公司后台数据库的专属数据检索与规整
- **本地路径：** ~/Projects/zhiku-agent/
- **创建日期：** 2026-04-29
- **阶段：** 初始化完成，开始工作
- **Skill：** zhiku-data-retrieval

## 数据库连接
- **类型：** MySQL 腾讯云 CDB
- **地址：** sh-cdbrg-eoqkyx9i.sql.tencentcdb.com:28028
- **账号：** btyc_hw_read（只读）
- **配置：** config/db_config.env

## 覆盖数据库
| 数据库 | 表数 | 描述 |
|--------|------|------|
| btyc | 281 | 核心业务 |
| btyc_statics | 7 | 统计数据 |
| dev_btyc | 278 | 开发镜像 |
| manage_backend | 18 | 管理后台 |
| schedule | 25 | 调度系统 v1 |
| schedule2 | 23 | 调度系统 v2 |

## 关键文档
- [共享上下文](docs/SHARED_CONTEXT.md) — 给后续对话框快速同频的当前项目背景、状态、风险和下一步
- [进度日志](docs/progress.md)
- [任务看板](docs/TASK_BOARD.md)
- [资源注册表](docs/RESOURCE.md)
- [故障码清单](docs/故障码清单-定位问题看表V3.0.xlsx)
- [猪油桶相关日志说明](docs/猪油桶相关日志说明%20(1).docx)

## 工具脚本
- `scripts/query.py` — SQL 查询执行
- `scripts/explore_schema.py` — Schema 自动探索

## 输出
- `output/` — 所有查询结果文件

## 关联项目
- CLM-REVIEW-TOOL（~/Projects/clm-tools-kw/）— 使用同一数据源的业务系统
