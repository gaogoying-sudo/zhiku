# 智库 Agent 资源注册表

## 数据库连接
| 项目 | 值 |
|------|-----|
| 类型 | MySQL（腾讯云 CDB） |
| 地址 | sh-cdbrg-eoqkyx9i.sql.tencentcdb.com:28028 |
| 账号 | btyc_hw_read |
| 权限 | 只读 |
| 配置文件 | config/db_config.env |

## 数据库清单
| 数据库 | 表数量 | 描述 |
|--------|--------|------|
| btyc | 281 | 核心业务库（用户、角色、菜谱、设备、会话、烹饪日志等） |
| btyc_statics | 7 | 统计数据库（烹饪统计、零件使用统计等） |
| dev_btyc | 278 | 开发环境镜像（会话、故障追踪、用户会话等） |
| manage_backend | 18 | 管理后台（企业、用户、菜谱、命令日志等） |
| schedule | 25 | 调度系统 v1（烹饪日志、商户信息、订单等） |
| schedule2 | 23 | 调度系统 v2（同上，可能是更新版本） |

## 关键表索引（待完善）

### btyc（核心业务）
- `ums_admin` — 管理员/工程师账户
- `auth_user` — 认证用户
- `ums_company` — 门店/客户
- `sop_recipe` — 菜谱
- `sop_machinelog` — 设备烹饪日志
- `sop_robot` — 设备信息
- `main_recipe` — 主菜谱
- `btyc_user_session` — 用户会话

### schedule / schedule2（调度系统）
- `oms_merchant_cooking_log` — 商户烹饪日志
- `oms_merchant_machine_info` — 商户设备信息
- `oms_merchant_recipe_conf` — 商户菜谱配置

### manage_backend（管理后台）
- `main_company` — 公司/企业信息
- `main_user` — 管理后台用户
- `main_recipe` — 管理后台菜谱
- `recipe_detail` — 菜谱详情

## 工具脚本
| 脚本 | 用途 |
|------|------|
| scripts/query.py | 直接执行 SQL 查询，表格输出 + CSV 保存 |
| scripts/explore_schema.py | 自动探索表结构和字段信息 |

## 输出目录
- output/ — 所有查询结果 CSV 文件保存在此
