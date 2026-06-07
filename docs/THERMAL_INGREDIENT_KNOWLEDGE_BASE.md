# 热物性知识库 v0.1

更新时间：2026-06-07

## 目标

建立一套可持续积累的食材热物性底座，供 `热过程分析`、后续温度预测模型和起火风险治理共用。

第一版先在前端内置种子数据，字段结构按后续入库设计：

```text
食材/物料 -> 分类 -> 别名 -> 比热容 -> 水分/油脂比例 -> 沸点/烟点/闪点/自燃点 -> 风险分类 -> 置信度/来源
```

## 当前字段

- `name`：标准食材或物料名。
- `aliases`：菜谱文本和日志里可能出现的别名。
- `category`：食材分类，例如油脂、水/汤汁、肉蛋类、蔬菜类、干货/香辛料。
- `specific_heat`：基础比热，单位 `kJ/kg℃`。
- `water_fraction`：工程估算水分比例。
- `oil_fraction`：工程估算油脂比例。
- `boiling_c`：沸点参考。
- `smoke_point_c`：烟点参考，主要用于油脂。
- `flash_point_c`：闪点参考，主要用于油脂或可燃液体。
- `autoignition_c`：自燃点参考。
- `hazard_class`：工程风险分类。
- `confidence`：当前数据可信度。
- `source`：来源说明。

## 使用边界

这些数值只用于工程解释和风险筛选，不能直接作为设备安全阈值。

原因：

- 食材批次、含水率、切配形态会改变吸热行为。
- 油脂的烟点/闪点受品牌、污染程度、重复加热和锅面残渣影响。
- 锅黑、局部热斑、红外污染和线盘效率会让实测温度与真实最高锅温偏离。
- 真实起火风险由功率、时间、油、空烧、投主料延迟、锅状态共同决定。

## 第一版已覆盖

- 水、汤汁、水淀粉。
- 植物油/色拉油、猪油、牛油。
- 鸡肉、牛肉、猪肉、鸡蛋、豆腐。
- 土豆、叶菜/包菜、鲜辣椒、葱姜蒜。
- 干辣椒、花椒/麻椒。
- 白糖、盐、酱油/生抽、醋/料酒。

## 后续入库建议

建议后续迁移到本地 MySQL 表：

```sql
ingredient_thermal_properties(
  id,
  canonical_name,
  category,
  aliases_json,
  specific_heat_kj_kg_c,
  water_fraction,
  oil_fraction,
  boiling_c,
  smoke_point_c,
  flash_point_c,
  autoignition_c,
  hazard_class,
  confidence,
  source,
  created_at,
  updated_at
)
```

后续每新增一种菜谱或食材，都应该补齐或复用这张表的物性数据。

