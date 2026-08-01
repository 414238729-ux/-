# Overlord / DND 换算规范

> 状态：第一版结构模板  
> 数据原则：本文件不包含任何未经用户提供或未经来源核验的角色能力、等级、属性、法术、怪物数据或官方规则。

## 1. 用途与边界

本文件用于把 Overlord 相关设定或能力描述结构化，并记录向指定 DND 版本进行数值化换算时的来源、设计目标、假设和结果。

换算结果属于指定目标下的设计方案，除非有明确来源，否则不得称为官方属性或官方对应关系。

## 2. 来源元数据

每条 Overlord 来源或 DND 目标规则资料至少记录：

| 字段 | 含义 |
|---|---|
| `source_id` | 本资料库中的唯一来源编号 |
| `title` | 作品、章节、规则、公告或资料名称 |
| `source_system` | Overlord 来源或目标 DND 规则集 |
| `version_or_edition` | 作品版本、规则版本或目标版本 |
| `source_type` | 用户粘贴、出版物、规则书、公告、截图转写等 |
| `locator` | 卷、章、页码、规则章节、链接或消息位置 |
| `published_at` | 资料发布日期；未知则写待填写 |
| `verification_status` | 待核验、已核验、有冲突 |
| `reliability` | 来源可靠性及判断依据 |
| `notes` | 翻译、版本差异、冲突与使用限制 |

## 3. 必须区分的来源层

1. **Overlord 来源原文**：角色、能力、装备或事件的可核验描述；
2. **DND 目标规则原文**：指定版本中相关机制的可核验规则；
3. **直接推断**：从来源原文可以较直接得到的机械约束；
4. **设计选择**：为可玩性、平衡或叙事表现选定的换算方案；
5. **计算假设**：战斗轮数、目标数量、命中率等数值分析条件；
6. **换算结果**：在上述前提下得到的属性、难度或分布。

## 4. 分析术语

- **源系统**：提供待换算叙事或能力的作品与版本。
- **目标系统**：承载换算结果的 DND 版本、规则集及可选规则。
- **叙事定位**：希望保留的身份、风格和代表性能力。
- **机械定位**：目标系统中的职责、强度区间和资源结构。
- **行动经济**：每轮可使用的行动、反应、额外行动或其他目标版本资源。
- **资源频率**：常驻、每轮、每次休息、每日或其他恢复方式；具体类型必须来自目标规则或明确设计选择。
- **直接映射**：来源与目标机制之间有清楚对应依据的映射。
- **近似映射**：为保留功能而选择的相似机制。
- **原创机制**：目标规则中无直接对应、需要新设计的机制。
- **平衡基准**：用于比较的目标系统对象或数值区间，必须注明来源。

## 5. 结构化数据格式

```yaml
metadata:
  project_id: 待填写
  source_work_version: 待填写
  target_system: DND
  target_edition: 待填写
  optional_rules: 待填写
  source_ids:
    - 待填写

conversion_goal:
  use_case: 玩家角色或非玩家角色或其他
  narrative_priority: 待填写
  balance_priority: 待填写
  target_tier_or_range: 待填写
  party_and_encounter_context: 待填写

source_entity:
  entity_id: 待填写
  name: 待填写
  narrative_role: 待填写
  demonstrated_capabilities:
    - statement: 待填写
      source_id: 待填写
      locator: 待填写
      reliability: 待填写

mechanical_mapping:
  - capability_id: 待填写
    source_statement: 待填写
    source_id: 待填写
    mapping_type: direct_or_approximate_or_original
    target_mechanic: 待填写
    action_cost: 待填写
    resource_cost: 待填写
    usage_frequency: 待填写
    target_and_range: 待填写
    attack_or_save: 待填写
    damage_or_effect: 待填写
    duration: 待填写
    counters_and_limits: 待填写
    design_reason: 待填写

statistics:
  ability_scores: 待填写
  defenses: 待填写
  health_model: 待填写
  movement: 待填写
  proficiency_or_scaling: 待填写
  source_or_design_basis: 待填写

resource_model:
  pools: 待填写
  recovery: 待填写
  competing_uses: 待填写

evaluation:
  comparison_baselines:
    - 待填写
  scenarios:
    - 待填写
  metrics:
    - 待填写
  exact_or_simulation: 待填写
  trials: 待填写
  seed: 待填写

ambiguities:
  - statement: 待填写
    interpretation_a: 待填写
    interpretation_b: 待填写
    chosen_design: 待填写
    reason: 待填写
```

## 6. 换算流程

1. 锁定源作品版本与目标 DND 版本；
2. 只记录有来源的能力表现；
3. 提取必须保留的叙事特征；
4. 为每项能力标注直接、近似或原创映射；
5. 明确行动经济、资源、频率、目标与反制；
6. 选择有来源的目标系统平衡基准；
7. 在明确场景下计算输出、防御和资源消耗；
8. 对不同设计选择分别给出结果；
9. 标注最终结果为自定义换算，而非官方数据。

## 7. 待补充项

- [ ] Overlord 来源版本与引用规范；
- [ ] 目标 DND 版本及可选规则清单；
- [ ] 经来源核验的能力描述；
- [ ] 可接受的换算目标和强度区间；
- [ ] 目标系统平衡基准及来源；
- [ ] 行动经济与资源频率的检查表；
- [ ] 典型战斗场景和评价指标；
- [ ] 不同设计解释的对照案例。
