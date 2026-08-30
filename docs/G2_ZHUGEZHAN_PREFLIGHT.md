# G2 诸葛瞻 Preflight / Implementation Plan

> 状态：`G2_ZHUGEZHAN_PREFLIGHT = PASSED`
> `G2_RULE_SOURCE = COMPLETE`
> `CANONICAL_GENDER = MALE`
> `ZHUGEZHAN = IMPLEMENTATION_READY`
> `READY_FOR_G2_IMPLEMENTATION = YES`
> `ZHUGEZHAN != GENERAL_COMPLETE`
> `AUTHORITATIVE_GENERAL_BATCH_V1 = IN_PROGRESS`
>
> 本文件只做规则来源核对、缺口图、时机图、证明矩阵与确定性测试计划。
> 本轮不实现技能、不跑 full pytest、不 commit / push / tag、不开始 G3。
> 不得把本文件写成 `GENERAL_COMPLETE`。

> 实现时规则裁定补充（2026-08-29）：用户后续明确要求【罪论】未选牌按
> 原始相对顺序回顶；【父荫】比较方向为“使用者用牌后手牌数 `<=` 诸葛瞻
> 手牌数”时对诸葛瞻无效。该后续裁定优先于本 preflight 所引旧文本中的
> 任意排序与反向比较；实现和验收采用后续裁定。

## 0. 分支与冻结点

| 项 | 值 |
| --- | --- |
| G1 frozen commit | `678179214a2260c23c95d03740191b1246024bbc` |
| G1 tag | `authoritative-general-batch-v1-g1-shamoke-audited` |
| G1 tag peeled commit | `678179214a2260c23c95d03740191b1246024bbc` |
| 本轮新建分支 | `codex/authoritative-general-batch-v1-g2-zhugezhan` |
| 本轮 HEAD | `678179214a2260c23c95d03740191b1246024bbc` |
| working tree at branch creation | clean |
| staged | 0 |
| unmerged | 0 |
| G1 tag/history | 未改写 |

G1 冻结结论保持不变：`G1_SHAMOKE_FREEZE = PASSED`，`SHAMOKE = GENERAL_COMPLETE`，`G1 = COMMITTED_TAGGED_PUSHED_AUDITED`。

## 1. 技能名确认

仓库全文检索结果：

- 命中技能名：【罪论】【父荫】
- 【罪己】命中数：0
- 不得沿用任何历史错误报告中的“罪己”

权威技能集合以 `knowledge/三国杀武将规则补充.md` §3 为准：【罪论】【父荫】。

轻量记录 `scripts/sgs_general_rules.py` 的 `GeneralRuleRecord("zhugezhan", …, ("罪论", "父荫"))` 与 Knowledge 一致，但不是生产权威。

## 2. RULE-SOURCE PREFLIGHT

权威顺序（Knowledge §1.3）：

1. 用户本轮新确认
2. `三国杀武将规则补充.md` 项目采用结算
3. 基础术语 / 模式规则 / 卡牌效果通则
4. 模拟规范（只用于策略，不改合法性）
5. 仍无答案则 `待核验`，不得凭记忆补全

策略、嘲讽、牌堆顶 AI 安排属于 `分析约定`，不得写入 rules/engine。

### 2.1 【罪论】

#### 当前仓库中的规则原文

`knowledge/三国杀武将规则补充.md` §3.2（技能原文）：

> 结束阶段，你可以观看牌堆顶三张牌，你每满足以下一项便保留一张，然后以任意顺序放回其余的牌：
> 1.你于此回合内造成过伤害；
> 2.你于此回合内未弃置过牌；
> 3.手牌数为全场最少。
> 若均不满足，你与一名其他角色失去1点体力。

#### 来源文件与位置

| 层 | 文件 | 位置 | 资料状态 |
| --- | --- | --- | --- |
| 基础信息 | `knowledge/三国杀武将规则补充.md` | §3.1 | 当前确认 |
| 技能原文 | 同上 | §3.2 | 用户提供并确认 |
| 项目采用结算 | 同上 | §3.3 | 当前确认 |
| 牌堆顶策略 | 同上 | §3.4 | 分析约定（非规则） |
| 模拟策略 / 嘲讽 | 同上 | §3.7 / §3.8 | 分析约定（非规则） |
| 运行状态字段名 | `knowledge/三国杀模拟规范.md` | §5.16 | 分析约定字段名；结算仍以武将补充为准 |
| 结束阶段 vs 回合结束 | `knowledge/三国杀基础术语与通用机制.md` | §3.6 | 当前确认 |
| 观看不足 | 同上 | §10.2 观看/亮牌/判定彻底不足 | 分析约定 |
| 轻量函数 | `scripts/sgs_general_rules.py` | `resolve_zuilun` | 非生产权威 |
| 轻量测试 | `tests/test_sgs_general_rules.py` | `test_zuilun_*` | 只覆盖轻量模型 |

#### 技能类型

- Knowledge §3.1 明示技能类型只写：【父荫】为锁定技
- 【罪论】原文为“你可以”
- 基础术语锁定技解释：文字写“你可以”时仍按可选择发动处理
- 结论：可选触发技，不是锁定技
- 状态：由原文 + 基础术语得出，不另造技能类型名

#### 字段表

| 项 | 结论 | 依据 | 不得写成 |
| --- | --- | --- | --- |
| 触发时机 | 诸葛瞻自己的 `END_PHASE` | 原文“结束阶段”；未写“一名角色的结束阶段” | `TURN_END` / `AFTER_TURN_END` / 出牌阶段结束 |
| 触发条件 | 进入自己的结束阶段且技能有效 | §3.3 发动时统一检查三项 | 把三项当成触发门槛（三项只决定效果） |
| 是否可选 | 是 | “你可以”；§3.3.1 可以不发动 | 锁定技 |
| 选择对象 | 零条件时选择一名其他角色 | 原文“你与一名其他角色”；§3.3.7 | 默认自己 / 默认下家 |
| 牌移动 | 观看牌堆顶三张；满足 n 项则从这三张中获得 n 张；其余按原始相对顺序放回牌堆顶 | 后续用户裁定（2026-08-29） | 当成摸 n 张；当成亮出到公共 REVEALED |
| 摸牌/弃牌/获得 | “保留”=获得至手牌；不是摸牌 | §3.3.4 | `draw_cards_for_skill` 直接替代获得 |
| 伤害/失去体力 | 仅零条件：自己先失去 1 点体力，再令另一名其他角色失去 1 点体力 | §3.3.7–9 | 造成伤害；两人同时失去体力 |
| 是否读取本回合历史事实 | 是：造成过伤害、未弃置过牌、当前手牌是否全场最少 | 原文三项；§3.3.2–3 | 用“本阶段”替代“本回合” |
| 是否涉及牌堆顶/底 | 牌堆顶三张；其余放回牌堆顶 | 原文；§3.3.5–6 | 牌堆底 |
| 是否涉及隐藏信息 | 是：原文为“观看”不是“亮出” | 原文；基础术语将观看与亮出分列 | 公共展示 |
| 是否需要额外选择窗口 | 是：发动/放弃；n>0 时选择保留哪些牌并排列其余；n=0 时选择其他角色 | 原文 + §3.3 | 无窗口自动拿牌 |
| 是否需要 continuation | 是：结束阶段暂停 `end_turn`，多步选择后才能继续 | 现有 END 阶段只有 `end_turn` | 塞进 `POST_CARD_USED_OR_PLAYED` |
| 是否涉及 replay | 是：选择、牌移动、失去体力、回合事实都要可重放 | G1 replay 合同 | 只测轻量 `resolve_zuilun` |
| 是否涉及 mode visibility | 是：观看结果的可见范围按模式 viewer policy 执行 | 基础术语 2v2 手牌可见是模式级政策；观看牌堆顶不是手牌 | 把 2v2 队友手牌可见套到牌堆顶 |

#### 【罪论】项目采用结算（当前确认，实现必须遵守）

1. 可以不发动。
2. 三个条件在发动时统一检查。
3. 并列全场手牌最少，也满足第三项。
4. “保留”表示将对应牌获得至手牌。
5. 满足几项，就从牌堆顶三张中获得几张。
6. 其余牌按原始相对顺序放回牌堆顶（后续用户裁定）。
7. 一项都不满足：诸葛瞻先失去 1 点体力；再令选择的一名其他角色失去 1 点体力。
8. 诸葛瞻先失去体力后，先完整处理其濒死、死亡和胜负检查。
9. 游戏已经结束时，不再令另一名角色失去体力。
10. “本回合未弃置过牌”只检查明确属于弃置的操作。

明确不算弃置（§3.3）：

- 使用
- 打出
- 重铸
- 装备替换
- 普通置入弃牌堆
- 被其他角色获得
- 普通牌移动

#### 【罪论】条件计数

效果由满足项数 n ∈ {0,1,2,3} 决定。测试必须覆盖全部四档。不得臆造第四项条件。

#### 【罪论】文本推导（不是新确认，实现时必须打标签）

1. 触发者是诸葛瞻自己的结束阶段，不是任意角色结束阶段。依据：原文未写“一名角色的结束阶段”；同文件【尚俭】才使用该句式。
2. 零条件的其他角色在发动时选定，随后按 §3.3.7–9 顺序结算。依据：发动者是活着的诸葛瞻；死亡后不能再选。若用户另行确认“必须在自身濒死处理后再选”，以新确认为准。
3. “观看”不是“亮出”。依据：原文用观看；基础术语把观看牌堆顶与亮出牌堆顶分列。不得把这三张送进公共 `REVEALED`。其他角色是否看见具体牌面：条目未写明；实现默认仅发动者可见，并保持 `文本推导`，不得升级为 `当前确认`。

#### 【罪论】已有通则，不需要新确认

| 边界 | 处理 | 状态 |
| --- | --- | --- |
| 【杀】造成伤害算“造成过伤害” | 是；失去体力不是伤害 | 基础术语 / `DamageEvent` vs `LOSE_HP` |
| 牌堆不足先重洗再观看 | 基础术语 §10.2 | 当前确认 |
| 重洗后仍不足三张 | 基础术语观看彻底不足：暂按平局，且必须披露 `non_draw_deck_exhaustion_assumption` | 分析约定。生产 `_reveal_cards` 对展示不足是失败关闭。G2 实现必须显式二选一并打标签，不得混写 |
| 跳过结束阶段 | 不触发【罪论】 | 基础术语 §3.6：`END_PHASE != TURN_END != AFTER_TURN_END` |

### 2.2 【父荫】

#### 当前仓库中的规则原文

`knowledge/三国杀武将规则补充.md` §3.5：

> 锁定技，你每回合第一次成为【杀】或【决斗】的目标后，若你的手牌数小于等于此牌的使用者，则此牌对你无效。

#### 来源文件与位置

| 层 | 文件 | 位置 | 资料状态 |
| --- | --- | --- | --- |
| 基础信息 / 明示类型 | `knowledge/三国杀武将规则补充.md` | §3.1 | 当前确认；锁定技 |
| 技能原文 | 同上 | §3.5 | 用户提供并确认 |
| 项目采用结算 | 同上 | §3.6 | 当前确认 |
| 【杀】总称含普通/火/雷 | `knowledge/三国杀基础术语与通用机制.md` | §20.12 | 当前确认 |
| 整牌无效 vs 目标取消 vs 指定目标后 | 同上 | §20.14 | 当前确认 |
| 指定目标后武将技能优先于武器 | `knowledge/三国杀卡牌效果.md` 青釭剑 | 用户实测 / 用户整理解释 | 用于时序，不为【父荫】另造例外 |
| 轻量函数 | `scripts/sgs_general_rules.py` | `resolve_fuyin_target` | 非生产权威 |

#### 技能类型

锁定技。有效且第一次成为【杀】或【决斗】目标后必须检查；角色不能放弃这次检查。

#### 字段表

| 项 | 结论 | 依据 | 不得写成 |
| --- | --- | --- | --- |
| 触发时机 | 成为【杀】或【决斗】目标后 | 原文“目标后”；§3.6.2 第一次成为目标时立即消耗 | `CARD_USED` 使用者侧检查点；`CARD_RESOLUTION_FINISHED` |
| 触发条件 | 本独立回合尚未检查，且该牌为【杀】或【决斗】，且诸葛瞻是该牌目标 | §3.6.1–2 | 南蛮/万箭/火攻；第二次【杀】/【决斗】 |
| 是否可选 | 否 | 锁定技 | ACTIVATE/PASS 窗口 |
| 选择对象 | 无 | 锁定技 | 选择是否无效 |
| 牌移动 | 无额外移动 | 原文只令牌对诸葛瞻无效 | 把牌移出处理区当成整牌取消 |
| 摸牌/弃牌/获得 | 无 | 原文 | 摸牌 |
| 伤害/失去体力 | 无效后该目标不因该牌对其结算而受伤 | “此牌对你无效”；防具同类路径现用 `CARD_EFFECT_CANCELLED` | 当成 `TARGET_CANCELLED` 或整牌 `CARD_INVALIDATED` |
| 是否读取本回合历史事实 | 是：`fuyin_checked_this_turn`；比较当时手牌数 | §3.6.1, §3.6.7 | 比较用牌前手牌数 |
| 是否涉及牌堆顶/底 | 否 | 原文 | — |
| 是否涉及隐藏信息 | 否；比较的是公开手牌张数 | §3.6.3–4, §3.6.7 | 偷看手牌内容 |
| 是否需要额外选择窗口 | 否 | 锁定技 | 使用者选择是否撞父荫 |
| 是否需要 continuation | 否（父荫自身无选择）；但必须插在成为目标后、响应窗口前 | §3.6.2 + 现有杀/决斗流程 | 与【蒺藜】共用同一 `POST_CARD_USED_OR_PLAYED` 触发发现 |
| 是否涉及 replay | 是：机会是否已消耗、是否对该目标无效，必须可认证 | G1 replay 合同 | 只改轻量 `FuyinTurnState` |
| 是否涉及 mode visibility | 否 | 手牌张数公开 | 2v2 手牌内容可见性 |

#### 【父荫】项目采用结算（当前确认，实现必须遵守）

1. 每个独立回合记录一次共享检查机会。
2. 第一次成为【杀】或【决斗】目标时，立即消耗该机会。
3. 比较诸葛瞻和使用者当前手牌数。
4. 使用者用牌后手牌数小于等于诸葛瞻时，该牌对诸葛瞻无效（后续用户裁定）。
5. 条件不满足时，该牌正常结算。
6. 无论是否成功令该牌无效，本回合后续【杀】和【决斗】均不再触发【父荫】。
7. 使用者已经使用该牌，比较时读取该牌离开其手牌后的当前手牌数。

#### 【父荫】通则覆盖，不需要新确认

| 边界 | 处理 | 状态 |
| --- | --- | --- |
| 火【杀】/雷【杀】 | 原文写【杀】，按 §20.12 总称包含三种【杀】 | 当前确认 |
| 多目标【杀】 | “此牌对你无效”是目标作用域；其他目标继续 | §20.14；现有藤甲/仁王盾多目标杀路径 |
| 与【帷幕】区别 | 【帷幕】是目标合法性过滤，不能成为目标；【父荫】是成为目标后令牌对你无效 | 不得做成 `TARGET_FILTER` |
| 与整牌无效 / 取消目标 | `CARD_INVALIDATED != TARGET_CANCELLED != 此牌对你无效` | §20.14；本技能用第三种 |
| 额外回合 | “每个独立回合”重新给一次机会；当前生产模式无额外回合 | 与 G1 extra-turn 相同：`NOT_APPLICABLE_TO_CURRENT_MODES` |

### 2.3 规则来源裁定

- 技能名、HP、两项技能原文、项目采用结算、弃置排除表、父荫消耗与手牌时点均有 `当前确认` 文本。
- 不存在必须停工的技能语义空洞。
- `G2_RULE_SOURCE = COMPLETE`
- 性别不属于技能 rule-source；见 §3.4。此前唯一 registry metadata blocker 已关闭。

## 3. CANONICAL GENERAL METADATA

### 3.1 现有权威 GeneralDefinition

`scripts/sgs_engine/generals.py` `create_authoritative_general_batch_v1_registry()` 目前只登记 `shamoke`。

诸葛瞻 **没有** `GeneralDefinition`。

### 3.2 已有非生产记录

`scripts/sgs_general_rules.py`：

```text
GeneralRuleRecord("zhugezhan", "诸葛瞻", "当前条目", 3, 3, ("罪论", "父荫"), …)
```

这不是 `GeneralDefinition`，不能直接当 production HP / skill_ids 权威。

### 3.3 实现登记前必须对齐的字段

| 字段 | 当前仓库 | 状态 |
| --- | --- | --- |
| canonical key | `zhugezhan` | 已有轻量键；生产应沿用，避免再造键 |
| name | 诸葛瞻 | 当前确认 |
| version / profile identity | 无生产定义 | 实现时按 `authoritative-general-v1` 现算；加入 registry 会改变 `registry_identity` |
| gender | `MALE` | 用户确认关闭。来源：无争议历史人物真实性别 / canonical metadata；游戏无相反性别设定。不属于技能 rule-source。不要求 §3.1 技能条目另外写“男”。 |
| max_hp / starting_hp | Knowledge §3.1 体力：3；轻量记录 3/3 | HP 有当前确认。`starting_hp` 未单独写；按条目“体力：3”与轻量 `base_hp == base_max_hp == 3` 登记 3/3。不得另写 4 |
| skill_ids | 尚无生产 ID | 实现时应派生 `sgs_skill_zuilun`、`sgs_skill_fuyin`；不得登记【罪己】 |

### 3.4 Canonical gender 来源政策

资料状态：当前确认。来源类型：canonical metadata（无争议历史人物真实性别）。不是技能 rule-source，也不是新的规则资料状态标签。

1. 对明确的历史人物，如果游戏没有明确给出相反的性别设定，canonical `gender` 可以采用无争议的历史真实性别。
2. 虚构人物、历史性别存在争议、或游戏明确改写性别的角色，仍必须单独确认，禁止自行推断。
3. 不要求 Knowledge 技能规则正文另外写明“男”或“女”。

本轮裁定：`zhugezhan.gender = MALE`。此前唯一 registry metadata blocker 已关闭。实现登记 `GeneralDefinition` 时必须使用该值。

## 4. IMPLEMENTATION GAP MAP

对照冻结能力。AI / strategy 层不得混入 rules/engine。

### 4.1 冻结能力现状（G1 后）

| 能力 | 现状 |
| --- | --- |
| `CARD_USED` / `CARD_PLAYED` generic checkpoint | 已有：`POST_CARD_USED_OR_PLAYED_TRIGGER_CHECKPOINT`。绑定使用者侧 `CARD_USED`/`CARD_PLAYED`。多技能同时触发失败关闭 |
| `CARD_RESOLUTION_FINISHED` | Knowledge §20.14 有合同。生产无同名 checkpoint / 事件 |
| continuation / signed skill choices | 已有：单层 card continuation；ACTIVATE/PASS 签名 |
| step transaction atomicity | 已有 |
| mode-policy snapshot/restore | 已有 |
| draw transaction | 已有 `draw_cards_for_skill`（摸牌，不是观看后获得） |
| card movement | 已有 `move_card` / `transfer_card_for_skill` |
| replay / deep tamper | 已有，但 `skill_replay.py` 生产武将回放硬编码 `sgs_skill_jili` |
| per-turn / per-phase facts | 【蒺藜】按本回合 `CARD_USED`/`CARD_PLAYED` 现算。无 `caused_damage_this_turn` / `discarded_card_this_turn` / `fuyin_checked_this_turn` 生产事实 |
| damage / hp loss / dying | 伤害濒死已有。`lose_hp_for_skill` 在体力将 <1 时失败关闭。C7 储君失去体力濒死是模式专属，不是通用技能 primitive |
| target cancellation vs card invalidation | Knowledge 已冻结三者区分。生产防具“对你无效”发 `CARD_EFFECT_CANCELLED`，不是 `CARD_INVALIDATED`，也不是 `TARGET_CANCELLED`。`CARD_INVALIDATED` 事件类型存在但生产未作为通用技能出口 |

### 4.2 【罪论】缺口

| 项 | 裁定 |
| --- | --- |
| EXISTING_PRIMITIVE | `SkillTimingWindow.PHASE_CHANGE` 仅 schema；`ProductionPhase.END` 阶段存在但只枚举 `end_turn`；`CARD_DISCARDED` / `CARD_RECAST` / `EQUIPMENT_REPLACED` / `CARD_USED` / `CARD_PLAYED` 已区分；`DamageEvent` vs `LOSE_HP` 已区分；signed ACTIVATE/PASS；step 原子性；mode-policy snapshot；濒死/死亡/胜负（伤害路径） |
| NEW_PRIMITIVE_REQUIRED | `END_PHASE` 技能检查点（进入结束阶段后、`end_turn` 前）；私密观看牌堆顶 n 张（不得复用公共 `_reveal_cards`）；从已观看集合获得 n 张（不是摸牌）；将其余牌按选择顺序放回牌堆顶；技能失去体力可进入濒死，并在第二人失去体力前做胜负检查 |
| NEW_RUNTIME_FACT_REQUIRED | `caused_damage_this_turn`；`discarded_card_this_turn`。必须按独立回合重置。弃置事实只由真正的弃置事件置位 |
| NEW_EVENT_REQUIRED | 不新造“罪论事件类型”。复用 `CARD_MOVED` + `CARD_GAINED`、`LOSE_HP`、`DYING`、`DEATH`、`VICTORY`。观看本身不得发公共 `CARD_REVEALED` |
| NEW_SIGNED_ACTION_REQUIRED | 结束阶段 ACTIVATE/PASS；n>0 时选择保留集合；其余牌回顶排列；n=0 时选择一名其他存活角色 |
| NEW_CONTINUATION_REQUIRED | 是。这是阶段 continuation，不是 card continuation。必须遵守当前“单层 continuation”冻结：打开【罪论】窗口时不得再套一层卡牌 continuation |
| REPLAY_SCHEMA_CHANGE? | 不一定改 envelope 字段集。`skill_replay.py` 的 Jili 硬编码必须泛化，否则新技能回放无法认证。观看牌的实体 ID 必须进入 signed payload，不能只活在 UI |
| IDENTITY_CHANGE? | 是。新 `SkillDefinition` / `GeneralDefinition` / registry 加入会改变 profile 与 `registry_identity` |

【罪论】禁止事项：

- 不得把获得写成摸牌。
- 不得把观看写成亮出。
- 不得把 `resolve_zuilun()` 轻量函数当生产结算器。
- 不得把牌堆顶策略（§3.4）写进 engine。

### 4.3 【父荫】缺口

| 项 | 裁定 |
| --- | --- |
| EXISTING_PRIMITIVE | schema 已有 `ON_BECOME_TARGET`；杀在 `CARD_USED` 后 continuation `_resume_slash_target`（此时牌已离开手牌）；多目标杀对单目标防具无效后继续后续目标；`SLASH_CARD_KEYS`；决斗有目标与无懈/响应流程；`CARD_EFFECT_CANCELLED` 目标作用域无效；`on_turn_change` 可清回合状态 |
| NEW_PRIMITIVE_REQUIRED | 生产级 `TARGET_CONFIRMED` / `ON_BECOME_TARGET` 检查点，且必须独立于使用者侧 `POST_CARD_USED_OR_PLAYED`。决斗路径目前没有“对你无效”出口，需要对称接入。锁定技自动生效，不开放 PASS |
| NEW_RUNTIME_FACT_REQUIRED | `fuyin_checked_this_turn`。第一次成为【杀】或【决斗】目标立即置位，无论是否无效成功 |
| NEW_EVENT_REQUIRED | 无效成功时复用目标作用域 `CARD_EFFECT_CANCELLED`（或等价“对你无效”事实）。**禁止**用整牌 `CARD_INVALIDATED` 或 `TARGET_CANCELLED` 顶替 |
| NEW_SIGNED_ACTION_REQUIRED | 无 |
| NEW_CONTINUATION_REQUIRED | 父荫自身无选择窗口。必须排在使用者技能 continuation 恢复之后、闪/决斗响应之前。沙摩柯对诸葛瞻出【杀】时：先【蒺藜】（使用者），再【父荫】（目标）。不得走“多技能同时触发失败关闭” |
| REPLAY_SCHEMA_CHANGE? | 锁定技无决策步。机会消耗与无效事实必须出现在可认证状态/事件中 |
| IDENTITY_CHANGE? | 是。随 `sgs_skill_fuyin` 与 `zhugezhan` 登记而变 |

【父荫】禁止事项：

- 不得做成【帷幕】那样的 `TARGET_FILTER`。
- 不得在 `POST_CARD_USED_OR_PLAYED` 里按使用者技能去发现【父荫】。
- 不得比较用牌前手牌数。
- 不得让条件失败时保留本回合机会。

## 5. TIMING MAP

禁止用“差不多相当于”替代具体 checkpoint。

### 5.1 【罪论】

| 规则时机 | 生产 checkpoint | 说明 |
| --- | --- | --- |
| 结束阶段 | **新** `END_PHASE_SKILL_CHECKPOINT`：`ProductionPhase` 进入 `END` 之后、`end_turn` 之前 | 当前 END 只枚举 `end_turn`，没有技能发现 |
| 出牌阶段结束 | `NOT_APPLICABLE` | 原文不是“出牌阶段结束时” |
| 回合结束 | `NOT_APPLICABLE` | `END_PHASE != TURN_END` |
| 回合结束后 | `NOT_APPLICABLE` | `END_PHASE != AFTER_TURN_END` |
| 跳过结束阶段 | 不触发 | 没有 END_PHASE checkpoint 就不得补触发 |
| 造成伤害后 | `NOT_APPLICABLE` 作为触发 | 只在结束阶段读取 `caused_damage_this_turn` |
| 使用牌后 | `NOT_APPLICABLE` 作为触发 | 使用/打出不是弃置 |
| 牌结算完成 | `NOT_APPLICABLE` | 不是“此牌结算后”技能 |
| `POST_CARD_RESOLUTION_DURING_DYING` | `NOT_APPLICABLE` | 本技能不是牌结算后触发 |
| 获得/失去牌 | 效果内的获得与回顶 | 不是触发器 |
| 弃牌阶段弃置 | 不触发【罪论】，但会置位 `discarded_card_this_turn` | 弃牌阶段在结束阶段之前 |

零条件失去体力顺序必须是：

1. 诸葛瞻 `LOSE_HP` 1
2. 完整濒死 / 死亡 / 胜负
3. 仅当游戏未结束：所选其他角色 `LOSE_HP` 1

`CARD_INVALIDATED != TARGET_CANCELLED`：`NOT_APPLICABLE` 于【罪论】触发，但零条件不是伤害。

### 5.2 【父荫】

| 规则时机 | 生产 checkpoint | 说明 |
| --- | --- | --- |
| 成为【杀】目标后 | **新** `TARGET_CONFIRMED` / `ON_BECOME_TARGET`，位于使用者侧 `POST_CARD_USED_OR_PLAYED` 恢复之后、闪响应窗口之前 | 对应 `_resume_slash_target` 内、雌雄/青釭武器技能之前。卡牌效果青釭条：同一“指定目标后”武将技能优先于武器 |
| 成为【决斗】目标后 | **新** 同一 `ON_BECOME_TARGET`，位于决斗 `CARD_USED` 且目标已确认之后、无懈链/交替出杀之前 | 不得等到决斗伤害结算后 |
| 使用牌后（使用者） | `NOT_APPLICABLE` 作为【父荫】入口 | `POST_CARD_USED_OR_PLAYED` 是【蒺藜】入口 |
| 出牌阶段结束 | `NOT_APPLICABLE` | — |
| 结束阶段 | `NOT_APPLICABLE` | — |
| 回合结束 / 回合结束后 | `NOT_APPLICABLE` 作为触发 | 回合切换只重置 `fuyin_checked_this_turn` |
| 造成伤害后 | `NOT_APPLICABLE` | — |
| 牌结算完成 | `NOT_APPLICABLE` 作为触发 | 【父荫】在成为目标后立即判定，不等 `CARD_RESOLUTION_FINISHED` |
| `POST_CARD_RESOLUTION_DURING_DYING` | `NOT_APPLICABLE` | — |
| 获得/失去牌 | `NOT_APPLICABLE` 作为触发 | 只读取当前手牌张数 |
| `CARD_INVALIDATED` | **禁止**用整牌无效表示“对你无效” | 多目标杀其他目标仍可继续 |
| `TARGET_CANCELLED` | **禁止**把【父荫】做成取消目标 | 目标已经成立，再令牌对该目标无效 |
| 此牌对你无效 | 目标作用域 `CARD_EFFECT_CANCELLED`（与藤甲/仁王盾现网同族） | 已使用、额度已耗；该目标不开闪/不进决斗伤害 |

`END_PHASE != TURN_END != AFTER_TURN_END`：【父荫】不在这些点触发。

`POST_CARD_RESOLUTION_DURING_DYING = USER_CONFIRMED_CURRENT`：与两技能触发均无关，保持 Knowledge 边界，不在 G2 实现 nested dying 系统。

## 6. G2 GENERAL_COMPLETE MATRIX

只允许 `PROVEN` / `FAILED` / `NOT_APPLICABLE` / `NOT_YET_IMPLEMENTED`。
本轮不得把诸葛瞻写成 `GENERAL_COMPLETE`。

| # | Gate | 本轮裁定 |
| --- | --- | --- |
| 1 | Knowledge / rule source | `PROVEN`（技能原文与项目采用结算完整；性别已按 canonical metadata 确认，不属于技能 rule-source） |
| 2 | Canonical GeneralDefinition | `NOT_YET_IMPLEMENTED`（registry 仍无 `zhugezhan`；`gender = MALE` 已确认，不再构成 blocker） |
| 3 | Assignment → derived skills | `NOT_YET_IMPLEMENTED` |
| 4 | 罪论 full semantics | `NOT_YET_IMPLEMENTED` |
| 5 | 父荫 full semantics | `NOT_YET_IMPLEMENTED` |
| 6 | signed choice / continuation authority | `NOT_YET_IMPLEMENTED`（【罪论】需要新阶段 continuation；【父荫】无选择） |
| 7 | card movement / draw / discard transaction | `NOT_YET_IMPLEMENTED`（观看/获得/回顶尚未存在） |
| 8 | turn / phase lifecycle facts | `NOT_YET_IMPLEMENTED` |
| 9 | hidden info / visibility | `NOT_YET_IMPLEMENTED`（【罪论】观看）；【父荫】比较公开手牌张数，无隐藏信息 |
| 10 | replay / deep tamper | `NOT_YET_IMPLEMENTED`（现网回放仍硬编码 Jili） |
| 11 | no-skill / legacy transparency | `NOT_YET_IMPLEMENTED`（G2 实现后必须回归证明） |
| 12 | test / claim quality | `NOT_YET_IMPLEMENTED` |

适用 gate 在实现并证明前不得改写为 `PROVEN`。

## 7. DETERMINISTIC TEST PLAN

不在本轮写测试代码。实现时必须覆盖下列矩阵。策略/嘲讽测试不属于 rules/engine 验收。

### 7.1 【罪论】acceptance matrix

条件计数必须覆盖 n = 0,1,2,3，以及第三项并列最少。

| ID | 类 | 场景 | 期望 |
| --- | --- | --- | --- |
| ZL-P1 | positive | 结束阶段发动，n=3（造成伤害 + 未弃置 + 并列最少） | 观看 3，获得 3，无回顶，无失去体力 |
| ZL-P2 | positive | n=2 | 获得 2，其余 1 张回顶 |
| ZL-P3 | positive | n=1 | 获得 1，其余 2 张按所选顺序回顶 |
| ZL-P4 | positive | n=0 且体力>1、游戏不结束 | 不观看；自己先失去 1 体力；再令所选其他角色失去 1 体力 |
| ZL-N1 | negative | 结束阶段 PASS | 不观看、不获得、不失去体力 |
| ZL-N2 | negative | 非自己的结束阶段 | 不触发 |
| ZL-N3 | negative | 出牌阶段结束 | 不触发 |
| ZL-N4 | negative | 使用/打出/重铸/装备替换/被获得/普通移动后，未真正弃置 | 第二项仍满足 |
| ZL-N5 | negative | 本回合弃牌阶段批量弃置 | 第二项不满足 |
| ZL-N6 | negative | 本回合自己对其他角色使用过河拆桥并弃置其牌 | 自己是弃置执行者，第二项不满足 |
| ZL-N7 | negative | 其他角色拆自己的牌 | 自己未弃置，第二项仍可满足 |
| ZL-N8 | negative | 本回合只失去体力、未造成伤害 | 第一项不满足 |
| ZL-B1 | boundary | 手牌并列全场最少 | 第三项满足 |
| ZL-B2 | boundary | 手牌严格大于场上某存活角色 | 第三项不满足 |
| ZL-B3 | boundary | n=0 且自己失去体力后进入濒死并被救回、游戏未结束 | 仍令所选其他角色失去 1 体力 |
| ZL-B4 | boundary | n=0 且自己失去体力后死亡并导致游戏结束 | 不令另一角色失去体力 |
| ZL-B5 | boundary | 牌堆不足 3 张，重洗后足够 | 观看成立 |
| ZL-B6 | boundary | 重洗后仍不足 3 张 | 按实现选定的已有口径：分析约定平局并披露，或与生产展示一样失败关闭。禁止第三种静默少看 |
| ZL-PH1 | phase reset | 上回合造成伤害/弃置/父荫事实 | 新独立回合开始时三项事实重置后再检查【罪论】 |
| ZL-PH2 | phase reset | 跳过结束阶段 | 本回合不触发【罪论】；TURN_END/AFTER_TURN_END 不得补触发 |
| ZL-M1 | multi-card | n=2 选择保留集合 | 只能从观看的 3 张中选 2 张；顺序回顶可认证 |
| ZL-M2 | multi-target | n=0 选择其他角色 | 不能选自己、不能选死亡角色 |
| ZL-T1 | transaction rollback | 发动后选择非法/过期窗口/异常 | GameState、events、RNG、牌位置、回合事实、continuation 回到 step 前 |
| ZL-R1 | replay | 干净 cold-load / 严格重放 | 选择、获得、回顶、失去体力一致 |
| ZL-R2 | deep tamper | 改观看牌 ID / 改保留集合 / 改回顶顺序 / 改其他角色后重算 identity | 拒绝 |
| ZL-NS1 | no-skill | 未分配诸葛瞻 | 结束阶段只有 `end_turn` |
| ZL-MD1 | mode regression | 2v2 / 斗地主 / 身份代表局 | 无技能路径不出现【罪论】动作或事件 |

### 7.2 【父荫】acceptance matrix

【父荫】没有“按条件数决定效果”，不要臆造计数档。本回合只有一次共享检查。

| ID | 类 | 场景 | 期望 |
| --- | --- | --- | --- |
| FY-P1 | positive | 本回合第一次成为【杀】目标，手牌 ≤ 使用者用牌后手牌 | 机会消耗；该【杀】对诸葛瞻无效；不开闪 |
| FY-P2 | positive | 第一次成为【决斗】目标，手牌 ≤ 用牌后手牌 | 机会消耗；决斗对诸葛瞻无效 |
| FY-P3 | positive | 火【杀】/雷【杀】 | 与普通【杀】相同，按【杀】总称 |
| FY-N1 | negative | 南蛮/万箭/火攻/普通锦囊 | 不检查、不消耗 |
| FY-N2 | negative | 第一次【杀】手牌 > 使用者用牌后手牌 | 机会仍消耗；牌正常结算 |
| FY-N3 | negative | 同独立回合第二次【杀】或【决斗】 | 不检查、不消耗、不无效 |
| FY-N4 | negative | 诸葛瞻不是该牌目标 | 不触发 |
| FY-B1 | boundary | 手牌数相等 | 无效成立 |
| FY-B2 | boundary | 使用者打出最后一张手牌后手牌为 0，诸葛瞻手牌 0 | 无效成立 |
| FY-B3 | boundary | 方天多目标【杀】，诸葛瞻为其中之一且条件成立 | 只对诸葛瞻无效；其他目标继续。不是整牌 `CARD_INVALIDATED`，不是 `TARGET_CANCELLED` |
| FY-B4 | boundary | 与【帷幕】对照：黑色【决斗】 | 【父荫】仍先成为目标再无效；不得在目标合法性阶段被过滤掉 |
| FY-PH1 | phase reset | 下一独立回合第一次【杀】 | 新机会 |
| FY-PH2 | phase reset | 当前生产模式无额外回合 | `NOT_APPLICABLE_TO_CURRENT_MODES`；不得伪造 extra-turn 已实现 |
| FY-M1 | multi-target | 见 FY-B3 | — |
| FY-T1 | transaction rollback | 成为目标后的外层 step 失败 | `fuyin_checked_this_turn` 与无效事件一起回滚 |
| FY-R1 | replay | 无效成功与消耗失败两条干净回放 | 机会与无效事实一致 |
| FY-R2 | deep tamper | 改 `fuyin_checked_this_turn` 或取消事件后重算 identity | 拒绝 |
| FY-NS1 | no-skill | 无诸葛瞻 | 【杀】/【决斗】按无技能结算 |
| FY-MD1 | mode regression | 代表模式 | 无技能路径不注入父荫事实 |
| FY-X1 | 与【蒺藜】同杀 | 沙摩柯对诸葛瞻使用【杀】且双方都触发 | 先完成使用者【蒺藜】窗口，再在成为目标后检查【父荫】。禁止多技能同时触发失败关闭 |

### 7.3 共享回归

- 未分配武将 / no-skill isolation
- legacy 模式 replay schema 不因未使用技能的对局而漂移
- C7 代表回归保持无技能透明
- 不得把 `sgs_general_rules.resolve_*` 轻量测试冒充 production 证明

## 8. FINAL STATUS

```text
G2_ZHUGEZHAN_PREFLIGHT = PASSED
G2_RULE_SOURCE = COMPLETE
CANONICAL_GENDER = MALE
ZHUGEZHAN = IMPLEMENTATION_READY
ZHUGEZHAN != GENERAL_COMPLETE
READY_FOR_G2_IMPLEMENTATION = YES
READY_FOR_G3 = NO
AUTHORITATIVE_GENERAL_BATCH_V1 = IN_PROGRESS
```

最小用户确认：无。此前唯一 registry metadata blocker（性别）已关闭。

本轮仍不开始 handler 实现、不跑 full pytest、不 commit / push / tag、不开始 G3。

## 9. POSTSCRIPT / FINAL DISPOSITION（历史 preflight 保留）

本文件正文与 §8 的 status block 是 G2 实现前的历史 preflight，不改写为最终
status authority。G2 后续实现、两轮独立敌对审计、closure audit 与 final full
pytest 的当前结论，以 `docs/POST_B_DEVELOPMENT_STATUS.md` §21 为准：

```text
G2_ZHUGEZHAN_IMPLEMENTATION = PASSED
G2_ZHUGEZHAN_CLOSURE_AUDIT = PASSED
G2_ZHUGEZHAN_FINAL_FULL_PYTEST = PASSED
G2_ZHUGEZHAN_DOCUMENTATION_FINALIZATION = PASSED
ZHU GEZHAN = GENERAL_COMPLETE
G2_FREEZE_READY = YES
AUTHORITATIVE_GENERAL_BATCH_V1 = IN_PROGRESS
AUTHORITATIVE_GENERAL_BATCH_V1 != COMPLETE
READY_FOR_G2_FREEZE = YES
READY_FOR_G3_IMPLEMENTATION = NO
```

first / second adversarial audit 的 `FAILED` 历史与 F-G2 finding closure 均在
authoritative status 文档中完整保留；本文件不承担最终状态文档职责。
