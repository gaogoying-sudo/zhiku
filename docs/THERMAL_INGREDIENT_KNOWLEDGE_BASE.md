# 热物性知识库 v0.2

更新时间：2026-06-07

## 目标

建立一套可持续积累的食材热物性底座，供 `热过程分析`、后续温度预测模型和起火风险治理共用。

这套底座现在已经从前端种子数据升级为云端本地 MySQL 表。页面优先读取本地数据库，前端 21 条工程种子数据只作为接口异常或尚未同步时的兜底展示。

```text
食材/物料 -> 分类 -> 别名 -> 比热容 -> 水分/油脂比例 -> 沸点/烟点/闪点/自燃点 -> 风险分类 -> 置信度/来源
```

## 当前数据来源

- `btyc.base_ingredients`：基础食材主数据，全量同步到本地热物性库。
- `manage_backend.recipe_detail.cooking_ingredient`：菜谱执行步骤里的真实配料 JSON，用于补充菜谱使用次数、出现菜谱数、累计用量和别名。
- `manage_backend.main_recipe`：补充菜谱名称、分类等上下文。

当前线上同步口径：

- 基础食材：52,446 条。
- 菜谱配料样本：最近 20,000 条 `recipe_detail`。
- 聚合配料引用：236,112 次。
- 标准分类：8 类，分别为 `未分类`、`蔬菜类`、`肉蛋类`、`油脂`、`液体调料`、`调料`、`水/汤汁`、`干货/香辛料`。

说明：`recipe_detail` 总量约 226,840 条，第一版同步接口默认取最近 20,000 条，避免同步请求长时间阻塞。后续应改成后台任务分批全量同步。

## 当前字段

- `source_ingredient_id`：源库食材 ID；没有 ID 时使用 `name:<名称>` 作为临时键。
- `canonical_name`：标准食材或物料名。
- `aliases_json`：菜谱文本和日志里可能出现的别名。
- `category`：食材分类，例如油脂、水/汤汁、肉蛋类、蔬菜类、干货/香辛料。
- `source_category_1 / source_category_2`：源库原始分类字段，保留用于后续人工校准。
- `ingredient_type / automatic`：源库食材类型与自动投料标记。
- `specific_heat_kj_kg_c`：基础比热，单位 `kJ/kg℃`。
- `water_fraction`：工程估算水分比例。
- `oil_fraction`：工程估算油脂比例。
- `boiling_c`：沸点参考。
- `smoke_point_c`：烟点参考，主要用于油脂。
- `flash_point_c`：闪点参考，主要用于油脂或可燃液体。
- `autoignition_c`：自燃点参考。
- `hazard_class`：工程风险分类。
- `confidence`：当前数据可信度。
- `source_note`：来源说明。
- `recipe_usage_count`：在已同步菜谱配料中出现的次数。
- `recipe_count`：涉及的菜谱数量。
- `total_amount_g / total_amount_ml`：已解析到的累计用量。
- `last_seen_recipe_id`：最近一次引用到的菜谱 ID。

## 使用边界

这些数值只用于工程解释和风险筛选，不能直接作为设备安全阈值。

原因：

- 食材批次、含水率、切配形态会改变吸热行为。
- 油脂的烟点/闪点受品牌、污染程度、重复加热和锅面残渣影响。
- 锅黑、局部热斑、红外污染和线盘效率会让实测温度与真实最高锅温偏离。
- 真实起火风险由功率、时间、油、空烧、投主料延迟、锅状态共同决定。
- 源库分类字段存在数字编码和多语言名称混用，当前分类是规则推断结果，后续需要用公司实验数据和供应商数据持续校准。

## 同步与查询

本地表：

```sql
ingredient_thermal_properties
ingredient_thermal_sync_runs
```

后端接口：

```text
GET  /api/thermal-knowledge
POST /api/thermal-knowledge/sync
```

页面能力：

- 按关键词、食材分类、燃烧风险筛选。
- 支持分页读取本地数据库。
- 显示最近同步时间、基础食材数量、菜谱配料引用次数。
- admin 可点击 `同步源库`，普通用户只查询。

## 表结构摘要

```sql
ingredient_thermal_properties(
  id,
  source_ingredient_id,
  canonical_name,
  aliases_json,
  category,
  source_category_1,
  source_category_2,
  ingredient_type,
  automatic,
  specific_heat_kj_kg_c,
  water_fraction,
  oil_fraction,
  boiling_c,
  smoke_point_c,
  flash_point_c,
  autoignition_c,
  hazard_class,
  confidence,
  source_note,
  recipe_usage_count,
  recipe_count,
  total_amount_g,
  total_amount_ml,
  last_seen_recipe_id,
  created_at,
  updated_at
)
```

后续每新增一种菜谱或食材，都应该补齐或复用这张表的物性数据。

## 后续建议

- 把 `recipe_detail` 226,840 条做成后台分批全量同步，不再依赖单次 HTTP 请求。
- 为源库分类编码建立人工映射表，降低 `未分类` 占比。
- 增加人工校准入口：比热容、水分、油脂比例、烟点、闪点、自燃点都应允许管理员修订并记录来源。
- 建立“实验值 / 供应商值 / 经验估算”三类置信度来源，避免模型把经验估算当作真实安全阈值。
