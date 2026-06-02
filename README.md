# 智库 Agent - 后台数据检索与规整

## 角色定位
公司后台数据库的专属数据检索与规整 Agent。

## 核心职责
1. **数据检索** — 针对公司后台 MySQL 数据库执行 SQL 查询，获取业务数据
2. **数据规整** — 将查询结果整理为可读、可分析的格式（表格、统计、趋势）
3. **数据导出** — 支持 CSV/JSON/Markdown 格式输出
4. **链路分析** — 追踪工程师、客户、设备、菜谱、执行日志之间的关联关系

## 工作范围
- 数据源：公司后台 MySQL（腾讯云 CDB）
- 只读访问，不执行任何写入操作
- 覆盖库：btyc / btyc_statics / dev_btyc / manage_backend / schedule / schedule2
- 输出：~/Projects/zhiku-agent/output/

## 连接信息
详见 `config/db_config.env`（不在 Git 中存储明文密码）

## 启动方式
```bash
# 直接查询
python3 ~/Projects/zhiku-agent/scripts/query.py "SELECT ..."

# 交互式
python3 ~/Projects/zhiku-agent/scripts/interactive.py
```

## 治理结构
- docs/ — 工程文档（进度、资源、决策）
- scripts/ — 查询脚本与工具
- output/ — 查询结果输出
- config/ — 数据库连接配置
