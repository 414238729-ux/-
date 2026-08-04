# 三国杀正式引擎状态

> 更新日期：2026-08-04
> 状态：已有权威核心 foundation、测试专用最小单挑纵向切片、正式160张牌堆上六种基本牌的生产适配器批次、最小普通锦囊垂直切片（【无中生有】、【无懈可击】），以及目标区域选牌批次（【过河拆桥】6张、【顺手牵羊】5张接入生产适配器），以及伤害型普通锦囊批次（【决斗】3张、【火攻】3张接入生产适配器，2026-08-03已通过独立只读审计AUDIT_PASSED_WITH_NONBLOCKING_ISSUES），以及群体普通锦囊批次（【南蛮入侵】3张、【万箭齐发】1张、【桃园结义】1张接入生产适配器并建立逐目标结算框架，已由用户在外部PowerShell提交（实现提交哈希 `5f2fbf27b7041bbf3010636de37306eea5da6256`），2026-08-03 完成独立只读审计：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，最终独立复审结论 AUDIT_PASSED），以及剩余普通锦囊批次（【五谷丰登】2张完整生产语义＋【铁索连环】6张牌本体接入生产适配器，已由用户在外部PowerShell提交，实现提交哈希 `20cb1b1f766529a88aa5f3346a4761b77eca66b7`，提交信息 feat: implement wugu and tiesuo card-body slice，尚未完成独立审计，见 2.9 节）；但正式整局引擎仍未完成，正式入口继续失败关闭。
> 本文是运行能力状态页，不得用测试总数或文档完整度替换完整引擎验收。

## 0. 机器可读状态摘要

```text
authoritative_core_foundation=true
minimal_duel_vertical_slice=true
reexecution_replay_supported=true
production_basic_cards_batch=true
production_single_target_trick_slice=true
production_zone_target_trick_batch=true
hidden_handle_hmac_security_fix=true
production_duel_fire_attack_batch=true
production_group_target_trick_batch=true
production_remaining_ordinary_trick_batch=true
authoritative_full_game_core=false
formal_duel_no_skill_ready=false
formal_run_ready=false
```

`production_basic_cards_batch=true` 只描述正式160张牌堆中六种基本牌（普通【杀】、火【杀】、雷【杀】、【闪】、【桃】、【酒】）已接入生产适配器批次；`production_single_target_trick_slice=true` 只描述【无中生有】（4张）与【无懈可击】（7张）的最小普通锦囊垂直切片；`production_zone_target_trick_batch=true` 只描述【过河拆桥】（6张）与【顺手牵羊】（5张）接入生产适配器并共用“目标区域选牌、隐藏手牌选择、实体牌移动”基础设施；`production_duel_fire_attack_batch=true` 只描述【决斗】（3张）与【火攻】（3张）接入生产适配器并复用【无懈可击】逐张响应链与伤害型普通锦囊结算路径；`production_group_target_trick_batch=true` 只描述【南蛮入侵】（3张）、【万箭齐发】（1张）与【桃园结义】（1张）接入生产适配器并建立“群体普通锦囊按行动顺序逐目标结算框架”（服务器自动目标序列、逐目标独立【无懈可击】窗口、逐目标响应或受伤／回复、濒死救援期间队列暂停与恢复）；`production_remaining_ordinary_trick_batch=true` 只描述【五谷丰登】（2张）完整生产语义与【铁索连环】（6张）牌本体接入生产适配器（公共REVEALED展示池、逐目标独立【无懈可击】、横置状态切换与重铸），属性伤害传导未实现、不计入完整实现。它们都不表示普通锦囊批次完成，也不表示正式160张牌无技能单挑完成；其余21种正式卡牌（含1种未实现普通锦囊：借刀杀人；3种延时锦囊；17种装备）仍未实现，正式整局入口继续失败关闭。当前计数口径必须分开：

```text
[test_only_duel_vertical_slice]
unsupported_rules=0
approximation_count=0

[formal]
unsupported_rules=1  # 至少存在一个完整正式整局能力阻塞的哨兵，不是精确缺项数（38种正式卡牌中仍有21种未接生产适配器）
approximation_count=0  # 正式入口拒绝执行，所以没有运行近似

[production_basic_cards_batch]
implemented=true
tested=true
card_types=6
unsupported_rules=1  # 批次范围外（锦囊、装备等26种正式卡牌）仍失败关闭
approximation_count=0

[production_single_target_trick_slice]
implemented=true
tested=true
card_types=2  # 【无中生有】4张、【无懈可击】7张，共11张实体牌
unsupported_rules=1  # 切片范围外（其余6种普通锦囊、延时锦囊、装备等26种正式卡牌）仍失败关闭
approximation_count=0

[production_zone_target_trick_batch]
implemented=true
tested=true
card_types=2  # 【过河拆桥】6张、【顺手牵羊】5张，共11张实体牌
unsupported_rules=1  # 批次范围外（其余6种普通锦囊、延时锦囊、装备等26种正式卡牌）仍失败关闭
approximation_count=0

[production_duel_fire_attack_batch]
implemented=true
tested=true
card_types=2  # 【决斗】3张、【火攻】3张，共6张实体牌
unsupported_rules=1  # 批次范围外（其余6种普通锦囊、延时锦囊、装备等26种正式卡牌）仍失败关闭
approximation_count=0

[production_group_target_trick_batch]
implemented=true
tested=true
card_types=3  # 【南蛮入侵】3张、【万箭齐发】1张、【桃园结义】1张，共5张实体牌
unsupported_rules=1  # 批次范围外（其余3种普通锦囊、延时锦囊、装备等23种正式卡牌）仍失败关闭
approximation_count=0

[production_remaining_ordinary_trick_batch]
implemented=true
tested=true
card_types=2  # 【五谷丰登】2张（完整实现）、【铁索连环】6张（牌本体接入，属性传导未完成不计入完整实现）
complete_card_kinds=16  # 完整实现卡牌种数：15+【五谷丰登】
adapter_card_kinds=17  # 注册表口径：已接入生产适配器17种（含铁索牌本体6张，不计入完整实现）
adapter_entities=126  # 注册表口径：已接入实体126张（铁索6张仅牌本体接入）
complete_entities=120  # 完整实现实体牌：118+2
remaining_card_kinds=22
remaining_normal_tricks=2  # 借刀杀人、铁索连环（铁索完整语义等待CP-04J）
tiesuo_card_body_implemented=true
tiesuo_chain_damage_implemented=false
tiesuo_full_semantics_complete=false
unsupported_rules=1  # 批次范围外（借刀、延时锦囊、装备等21种正式卡牌）仍失败关闭
approximation_count=0
```

## 1. 当前可执行结论

| 问题 | 结论 |
|---|---|
| 当前是否存在唯一权威 `GameState` 基础模型 | 是；已覆盖160张实体牌、玩家基础字段、唯一牌区与区域顺序，但未覆盖完整模式、轮次、阶段、技能和胜负 |
| 当前是否存在可执行的正式失败关闭入口 | 是；`python -m scripts.sgs_formal_runner status/run`，其中 `run` 当前必然拒绝且不写结果 |
| 当前是否存在完整对局入口 | 部分；存在隔离的测试专用三牌无技能单挑纵向切片，正式完整对局入口仍不存在 |
| 当前是否能完整运行至少一局 | 测试专用三牌切片可以；正式160张牌无技能单挑及其他正式模式不可以 |
| 当前是否存在网页人工对局 | 否 |
| 当前是否存在统一回放 | 部分；测试专用单挑切片已有决策、随机消费、事件和最终状态的严格规则重执行回放；正式通用引擎尚无规则重执行回放或 UI |
| 当前是否存在正式多进程胜率入口 | 否 |
| 外部 `sgs_sim_engine_worker.py` 是否是正式引擎 | 否；它位于 Downloads，未被仓库导入，是独立近似器 |
| 外部 `sgs_ai_audit_20260729.py` 是否调用真实 AI | 否；它使用本文件内微场景与自证式 `chosen = expected` |
| 当前组件测试是否通过 | 是；本轮最终完整测试为 `1403 passed`，失败0、跳过0 |

## 2. 当前正式资产

### 2.1 规则与数据

- `knowledge/` 是正式 Knowledge 唯一来源；
- `knowledge/三国杀牌堆数据.csv` 保存 160 张实体牌资料；
- 卡牌定义、使用方式、模式、基础机制、武将条目和模拟策略已分层维护；
- 本阶段不创建任何带时间戳、“新版”或“副本”后缀的 Knowledge 文件。

### 2.2 可复用代码

- 通用概率、抽牌、伤害统计、触发和排名模块；
- 实体牌堆加载和校验；
- 卡牌、延时锦囊、距离、装备、死亡和模式的局部规则函数；
- 多批武将的局部状态和技能结算函数；
- 集火、卡牌使用、团队救援、无懈、铁索等局部策略评分。

这些资产可以迁移进未来权威核心，但当前彼此没有统一运行时状态、事件队列和合法动作接口。

### 2.3 阶段 4 权威核心 foundation

当前 `scripts/sgs_engine/` 已提供：

- `CardInstance`、最小 `PlayerState`、不可变 `GameState` 和全局／玩家牌区；
- 正式 160 张实体牌装配、单一 `deck_id`、区域顺序、实体牌守恒和确定性洗牌；
- `GameEvent`、强类型 `DamageEvent`、独立归因字段、`EventQueue` 和 `ResponseWindow`；
- `LegalAction`、`RuleAdapter`、`RuleRegistry`、动作枚举／应用的上下文绑定、防伪校验、适配器版本／注册表指纹绑定和枚举副作用检测；
- `DeterministicRNG` 和逐次随机消费记录；
- `ReplayRecord` 的前向哈希链、JSON／JSONL 存取及篡改检测；
- `AuthoritativeCoreSession` 的原子实体牌移动、事件登记、回放登记和未实现规则失败关闭。

本节列出的是基础设施，不代表卡牌、模式、武将或 AI 已接入。

### 2.4 里程碑 A：测试专用最小单挑纵向切片

提交 `455685d6eaa1c297e9ec48a0cfaeb803b81f3406` 增加了一个明确隔离的开发测试切片：

- 模式 ID 为 `test_only_duel_vertical_slice`，牌堆 ID 为 `test_only_duel_three_card_deck`；
- 只支持【杀】【闪】【桃】及完成这三张牌所需的标准六阶段、响应、伤害、濒死、救援、死亡与胜负路径；
- 所有动作经过真实 `enumerate_legal_actions → validate_action → apply_action` 路径；
- 同 seed、配置、决策和随机消费可以严格重执行，回放篡改、动作偏离、随机消费偏离或事件偏离均失败关闭；
- 50 个固定 seed 全部完成，最大动作数为187，没有触发500步安全上限；
- 在这个明确声明的三牌切片范围内，`unsupported_rules=0`、`approximation_count=0`。

这不是160张正式牌堆，也不是正式无技能单挑。不得将本节结果用于正式胜率、正式模式覆盖或 `formal_run_ready=true`。


### 2.5 正式基本牌批次：六种基本牌生产适配器

正式基本牌批次在正式160张牌堆上新增六种基本牌的生产适配器，全部规则以正式 Knowledge（`knowledge/三国杀卡牌效果.md`、`knowledge/三国杀卡牌使用方式.csv`、`knowledge/三国杀牌堆数据.csv`）为唯一来源：

- 模式 ID：`production_basic_cards_batch`；正式牌堆总实体牌数仍为160，实例ID唯一；
- 六种基本牌真实读取 CSV 的实体数量：普通【杀】30、火【杀】5、雷【杀】9、【闪】24、【桃】12、【酒】5，合计85张；
- 所有动作都经过 `enumerate_legal_actions → validate_action → apply_action`，动作绑定状态指纹与适配器版本，伪造／过期动作失败关闭；
- 三种【杀】的差异落实到伤害属性事件（无属性／火属性／雷属性），各自建立真实响应窗口；
- 【闪】响应三种【杀】生成 `card_used` 且不生成普通 `card_played`；【万箭齐发】的“打出【闪】”不属于本批次，遇到时失败关闭；
- 【桃】实现出牌阶段受伤自用、濒死自救与救援他人三种用途，回复不超过体力上限，救援在体力恢复至至少1点后停止；
- 【酒】区分出牌阶段强化下一张【杀】（每出牌阶段限一次、不立即回复体力、状态被下一张【杀】消费或在回合结束时清除）与濒死自救（仅对自己、回复1点、无基础次数限制、不共享强化额度）；
- 未实现卡牌（普通／延时锦囊、武器、防具、坐骑共32种）在注册表层明确标记为未实现，任何结算入口遇到它们都失败关闭，不得 fallback 或跳过继续整局；
- 含【杀】【闪】【桃】【酒】的固定生产路径（seed=5 参考局）支持严格规则重执行回放；篡改动作、事件或随机消费均失败关闭；
- 游戏结束后任何后续动作均被拒绝。

| 卡牌 | card_key | 实体数量 | implemented | tested | production_adapter | replay_verified | remaining_interactions |
|---|---|---|---|---|---|---|---|
| 普通【杀】 | `sgs_basic_sha` | 30 | true | true | true | true | 武器转化／技能转化【杀】、南蛮入侵等“打出【杀】”响应、铁索传导等后续批次 |
| 火【杀】 | `sgs_basic_huosha` | 5 | true | true | true | true | 藤甲火属性增伤、铁索连环传导、技能转化等后续批次 |
| 雷【杀】 | `sgs_basic_leisha` | 9 | true | true | true | true | 铁索连环传导、闪电／技能联动等后续批次 |
| 【闪】 | `sgs_basic_shan` | 24 | true | true | true | true | 响应【万箭齐发】（打出）、八卦阵判定、技能转化等后续批次 |
| 【桃】 | `sgs_basic_tao` | 12 | true | true | true | true | 桃园结义联动、技能无效／转化等后续批次 |
| 【酒】 | `sgs_basic_jiu` | 5 | true | true | true | true | 技能令效果无效、酒杀与铁索联动等后续批次 |

本批次是里程碑 B（正式160张牌无技能单挑）的第一步，不是里程碑 B 完成：正式整局仍被其余32种正式卡牌阻塞。

### 2.6 目标区域选牌批次：【过河拆桥】与【顺手牵羊】

正式160张牌堆上第二批普通锦囊生产适配器，继续复用【无中生有】／【无懈可击】已审计通过的普通锦囊使用窗口与【无懈可击】逐张响应链基础设施，不建立第二套锦囊引擎或事件队列：

- 模式 ID 仍为 `production_basic_cards_batch`（双人生产切片）；正式牌堆总实体牌数仍为160，实例ID唯一；
- 【过河拆桥】6张（♣3、♣4、♥Q、♠3、♠4、♠Q）与【顺手牵羊】5张（♦3、♦4、♠3、♠4、♠J）真实读取牌堆CSV实体并绑定生产适配器，其余28种正式卡牌（含8种未实现普通锦囊）继续失败关闭；
- 两张牌均为出牌阶段主动使用、目标为一名其他角色、目标手牌区／装备区／判定区合计至少一张合法牌；【顺手牵羊】额外要求目标与使用者的实际距离为1，距离条件调用正式 `actual_distance` 座次距离接口，不使用座位编号差或攻击范围代替；坐骑距离修正未实现时（坐骑栏被占用）在枚举与应用层双重失败关闭；
- 【过河拆桥】不检查距离条件，不继承【顺手牵羊】的距离限制；
- 使用后原锦囊实体由手牌区进入处理区，产生 `card_used` 并建立与【无中生有】相同的响应窗口；被【无懈可击】无效后不打开选牌窗口、不移动目标区域内任何牌、原锦囊仍记为已经使用并进入弃牌堆；
- 最终生效时重新读取目标当前区域状态并进入 `zone_choice` 目标区域选牌动作：公开区域（装备区、判定区）以明确实体候选（实体ID＋card_key）展示；隐藏手牌区只暴露绑定“会话＋选择窗口＋目标＋区域＋当前手牌快照”的HMAC-SHA256不透明句柄（`h_`前缀，输出128位，密钥为会话级 `secrets.token_bytes(32)` 随机秘密，消息含会话标识、窗口ID、目标角色、区域、手牌快照摘要与实体ID）；公开窗口ID、正式牌堆160个实体ID、正式CSV牌面与公开seed均不足以重建句柄；决策输入不携带牌名、花色、点数、可识别实体ID、会话秘密或私有映射，权威引擎解析句柄后移动真实实体；过期、伪造、跨会话、跨窗口、跨目标、跨区域、手牌变化后的句柄以及状态哈希不符一律失败关闭；
- 【过河拆桥】生效后把目标区域内一张实体牌直接置入弃牌堆（`discard_direct`，不发生先获得再弃置）；【顺手牵羊】生效后把目标区域内一张实体牌直接从原区域移入使用者手牌（`gain_direct`）；两张牌都记录原区域、原所有者、新所有者、来源锦囊、是否来自隐藏区域以及“结算时无合法区域牌”的可审计原因；
- 无懈链结束时目标三个区域已无合法牌时：不把原使用追溯为非法、不凭空选牌或移动，原锦囊仍进入弃牌堆，结算移动事件带 `no_legal_zone_card=true` 完成；
- 判定区和装备区只作为这两张牌的合法目标区域参与实体牌移动；卡牌本身的装备、判定、延时锦囊使用效果仍未实现，相关测试仅用不可变 `GameState` 与正式牌区移动接口布置夹具，不表示装备或延时锦囊效果已实现；
- 新增 50 项真实生产路径验收测试（`tests/test_sgs_production_zone_target_tricks.py`），覆盖注册表绑定、使用合法性、无懈链、弃置／获得、隐藏信息隔离、严格回放与失败关闭；完整 pytest 为 `1252 passed`。
- 独立只读审计曾判定隐藏手牌句柄（裸SHA-256）可被160项公开预计算表还原为目标手牌（AUDIT_FAILED）；已定点修复为会话级HMAC句柄并新增 29 项安全回归测试（`tests/test_sgs_production_hidden_handle_security.py`）：两会话同实体句柄不同、同会话不同窗口句柄不同、160项枚举攻击匹配数为0、伪造／过期／跨会话／跨窗口／跨目标／跨区域／手牌变化句柄失败关闭、回放私有材料（`authoritative_private`）与玩家可见导出（`player_visible`）隔离及篡改失败关闭；完整 pytest 为 `1281 passed`（失败0、跳过0）。

本批次只验证双人生产切片，不构成普通锦囊批次完成、多人响应链完成、正式单挑完成或里程碑 B 完成。

### 2.7 伤害型普通锦囊批次：【决斗】与【火攻】

正式160张牌堆上第三批普通锦囊生产适配器，继续复用【无中生有】／【无懈可击】已审计通过的普通锦囊使用窗口与【无懈可击】逐张响应链基础设施，不建立第二套锦囊引擎、事件队列或回放系统：

- 模式 ID 仍为 `production_basic_cards_batch`（双人生产切片）；正式牌堆总实体牌数仍为160，实例ID唯一；【决斗】3张与【火攻】3张真实读取牌堆CSV实体并绑定生产适配器，其余26种正式卡牌（含6种未实现普通锦囊）继续失败关闭；
- 【决斗】为出牌阶段以一名其他角色为目标的主动使用，无距离限制、无基础每回合次数限制；使用后实体牌由手牌进入处理区并产生 `card_used`，先进入现有【无懈可击】响应链；被无效后不进入交替出【杀】流程、不造成伤害、原【决斗】仍记已使用并进入弃牌堆；
- 【决斗】生效后建立交替打出【杀】状态：目标先响应，然后双方交替；每轮当前响应者同时拥有“打出一张合法【杀】”与“不打出【杀】”两个候选，即使手中有【杀】也必须允许主动不响应；能响应的【杀】严格按当前卡名为【杀】判断（普通【杀】、火【杀】、雷【杀】），只在使用时临时视为【杀】的材料牌不自动计入；
- 响应【决斗】的【杀】动作为“打出”，产生 `card_played` 事件、不产生普通 `card_used`、不计入使用牌但计入使用或打出牌总数，实体牌经历手牌→处理区→弃牌堆的完整生命周期；
- 当前响应者不打出【杀】时受到1点无属性伤害，伤害来源为另一名仍参与【决斗】的角色（不统一写死为使用者），伤害关联牌为原【决斗】；伤害正常进入濒死、桃／酒救援、死亡、身份击杀归属与胜利流程，胜利后立即停止；
- 已合法生成并开始结算的【决斗】不因来源死亡自动取消已开始的结算，但死亡角色不能继续打出【杀】，轮到死亡角色继续响应时【决斗】立即结束、不向死亡角色凭空补结算伤害；
- 【火攻】为出牌阶段以一名至少有一张手牌的角色为目标的主动使用（可包括自己），无距离限制、无基础每回合次数限制；使用后同样先进入【无懈可击】响应链，被无效时不展示目标手牌、不打开展示／弃置窗口、不移动目标或使用者的其他牌、不造成伤害；
- 【火攻】生效后由目标角色（而非使用者）选择一张自己的手牌展示：目标只能看到自己的完整候选，使用者在选择作出前看不到目标手牌牌面；未选择的手牌不进入其他角色决策视图、事件或玩家可见回放；被展示的牌公开实体、牌名、花色、点数且仍留在目标手牌区（展示不移动区域），产生 `card_revealed` 公开展示事件；目标只有一张手牌时也必须通过合法动作链完成选择；
- 展示完成后由【火攻】使用者选择弃置一张与展示牌花色相同的手牌或不弃置；即使有同花色牌也必须保留“不弃置”候选；只能选择当前仍在使用者手牌中的真实实体牌，原【火攻】已在处理区不得再次作为弃置材料；弃置产生 `CARD_MOVED`、`CARD_LOST`、`CARD_DISCARDED`，不产生普通 `card_used`／`card_played`，不先获得再弃置，并记录弃置原因、根【火攻】实体、展示牌及其花色；
- 成功弃置同花色手牌后【火攻】使用者对目标造成1点火焰伤害（伤害关联牌为原【火攻】）；不弃置、无同花色牌或来源无法继续结算时不造成伤害；结算到展示步骤时目标已无手牌则本次【火攻】无效果完成（不追溯使用非法、不凭空展示、不造成伤害，产生 `fire_attack_effect_resolved_no_legal_reveal_card` 可审计结果）；
- 目标选择展示牌使用仅绑定“会话＋展示窗口＋目标手牌”的HMAC-SHA256不透明句柄（会话级256位随机秘密，消息含会话标识、窗口ID、目标角色、区域与实体牌ID，输出128位）；与“由其他角色选择隐藏手牌”的句柄语义不同，展示选择是手牌所有者本人选择自己的牌；句柄只在当前选择窗口内有效，过期／伪造／跨窗口／手牌变化后的句柄失败关闭；权威引擎解析句柄后公开真实展示牌，玩家可见回放只公开已展示牌、不泄露其余手牌；
- 新增 51 项真实生产路径验收测试（`tests/test_sgs_production_duel_fire_attack.py`），覆盖注册表绑定、使用合法性、无懈链、交替出【杀】、打出与使用的语义区分、伤害来源、死亡响应者边界、目标展示手牌、同花色弃置、隐藏信息隔离、严格回放与失败关闭；2026-08-03 独立只读审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，未发现规则、隐藏信息、伤害来源、回放、第二套引擎或虚假测试阻塞问题，并补充两个确定性回归测试（目标仅一张手牌的【火攻】展示、来源死亡后已开始的【决斗】不自动取消）；当前完整 pytest 为 `1334 passed`（失败0、跳过0）。审计收尾真实提交为 `9c2070017fe624295ebd735bf5163f48a6ac2207`（test: close duel and fire attack audit gaps），里程碑标签 `milestone-b2-duel-fire-attack-audited` 已建立。

本批次只验证双人生产切片，不构成普通锦囊批次完成、多人响应链完成、正式单挑完成或里程碑 B 完成；实现【决斗】不等于正式无技能单挑已完成。

### 2.8 群体普通锦囊批次：【南蛮入侵】与【万箭齐发】与【桃园结义】

正式160张牌堆上第四批普通锦囊生产适配器，建立可复用的“群体普通锦囊按行动顺序逐目标结算框架”，继续复用同一 `GameState`／`CardInstance`／`ZoneRef`、事件队列、合法动作路由、【无懈可击】逐张 `response_to` 链、伤害／濒死／救援／死亡／胜利流程与严格重执行回放，不建立第二套状态、牌区、事件、伤害或回放系统：

- 模式 ID 仍为 `production_basic_cards_batch`（双人生产切片）；正式牌堆总实体牌数仍为160，实例ID唯一；【南蛮入侵】3张（♣7、♠7、♠K，实例061／141／158）、【万箭齐发】1张（♥A，实例082）、【桃园结义】1张（♥A，实例081）真实读取牌堆CSV实体并绑定生产适配器，其余23种正式卡牌（含3种未实现普通锦囊）继续失败关闭；
- 三张牌均为出牌阶段主动使用、无距离限制、无基础每回合次数限制；目标集合由服务器依据规则自动生成（使用时快照、按当前行动顺序从使用者沿座次数字递增循环、跳过已死亡角色，结算时不动态增删）：【南蛮入侵】与【万箭齐发】为“除使用者外的所有角色，依次结算”（`knowledge/三国杀卡牌结构化数据.csv` target_template=all_other_characters），【桃园结义】为“所有已受伤角色”（target_template=all_wounded_characters，包含使用者）；LegalAction 不接受玩家可篡改的任意目标列表，伪造目标集合／顺序／索引一律失败关闭；
- 使用后原锦囊实体由使用者手牌进入处理区并产生一次正常 `card_used`，建立固定逐目标序列；原锦囊在全部目标完成前始终留在处理区，最后目标完成后才进入弃牌堆；每名目标有独立、可审计的目标效果事件（`group_target_resolved`：根锦囊实体ID、使用者、目标、目标索引、总目标数、结果与下一目标）；
- 每个目标单独打开该目标的【无懈可击】窗口：一张无懈只抵消当前目标的效果并推进下一目标，两张连续无懈恢复当前目标效果；每张无懈保留准确逐张 `response_to`，切换目标时新建目标效果窗口，前一目标的无懈状态不泄漏到后一目标；被无懈取消的当前目标不打开【杀】／【闪】响应或回复步骤；
- 【南蛮入侵】生效后当前目标可选择打出一张合法【杀】（普通／火／雷【杀】，按当前卡名判断）或主动不响应；响应为“打出”：产生 `card_played`、不产生普通 `card_used`、不计入使用牌次数、计入使用或打出牌总数，实体经历手牌→处理区→弃牌堆；不响应时受到1点无属性伤害，伤害来源为使用者，关联实体为原【南蛮入侵】；
- 【万箭齐发】生效后当前目标可选择打出一张合法【闪】或主动不响应；响应为“打出【闪】”（`card_played`，不产生 `card_used`、不计入使用牌次数、计入使用或打出总数、经历手牌→处理区→弃牌堆），不得把【闪】实现成“使用”；不响应时受到1点无属性伤害，来源为使用者；一名目标打出【闪】或受伤不影响下一目标（游戏未结束时）；
- 【桃园结义】的目标集合（使用时已受伤角色）与实际回复（结算时逐目标恢复1点、不超过体力上限）分开维护：当前目标结算时已满体力则无效果结算、不产生虚假回复；当前目标被【无懈可击】取消时不产生恢复事件并继续下一目标；自身与其他角色进入同一通用目标队列（双人切片按行动顺序连续处理 p1→p2 两个目标）；恢复事件记录来源（根【桃园结义】）、目标、实际恢复量、目标索引；
- 群体锦囊造成伤害触发濒死时队列暂停，进入现有桃／酒救援；救援结束后游戏未结束时从正确的下一目标继续（不重结算已完成目标、不跳过未处理目标、不提前丢弃原锦囊、不丢失根锦囊／目标索引／伤害来源），游戏已结束时立即停止；
- 群体响应动作以绑定“会话＋响应窗口＋当前目标＋根锦囊”的不透明句柄（`gr_` 前缀）暴露，决策负载不携带实体牌ID、牌名、花色或点数；过期、伪造、非当前目标响应、伪造目标索引／根锦囊／窗口、手牌变化后的句柄、原锦囊离开处理区后或游戏结束后的动作一律失败关闭；玩家可见回放不泄露未打出的目标手牌（与既有火攻批次约定一致：从未公开化的手牌实体在导出事件中只允许公共发牌记录，决策材料中不得出现）；
- 新增 69 项真实生产路径验收测试（`tests/test_sgs_production_group_target_tricks.py`），覆盖注册表绑定、服务器自动目标集合、逐目标推进与独立效果状态、逐目标无懈与双无懈、南蛮／万箭响应与不响应伤害、桃园逐目标回复、濒死救援后队列恢复、牌守恒、隐藏信息隔离、严格回放与篡改失败关闭；当前完整 pytest 为 `1403 passed`（失败0、跳过0）。
- 2026-08-03 独立只读审计完成：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，首次审计问题修复提交 `ef98245aef32848468c7b2c4a7821ec9ae65146b`（test: close group-target trick audit gaps），把南蛮／万箭伪造负载负向测试拆为逐层独立校验（目标绑定、operation、目标索引、窗口、状态哈希、根锦囊、句柄）并补真实枚举正向对照；最终独立复审在专用复审分支上执行，复审残项（非当前响应者提交）由 `d2e4f49925c0bb285d44092821c3a85c496571ef`（test: complete group-target trick reaudit closure）关闭，最终结论 AUDIT_PASSED；未发现规则、隐藏信息、回放、第二套引擎或虚假测试阻塞问题；里程碑标签待用户提交文档后建立。

本批次只验证双人生产切片：当前正式生产入口原生仅支持双人会话，三人以上目标顺序、中间目标濒死／死亡后的继续位置与来源死亡处理仍未由正式生产入口证明（NOT PROVEN），文档不得写成完整军八、2v2或斗地主群体响应链已完成；不构成普通锦囊批次完成、正式单挑完成或里程碑 B 完成。

### 2.9 剩余普通锦囊批次：【五谷丰登】完整生产语义＋【铁索连环】牌本体

正式160张牌堆上第五批普通锦囊生产适配器（CP-04I，2026-08-04 已由用户在外部PowerShell提交实现，提交哈希 `20cb1b1f766529a88aa5f3346a4761b77eca66b7`，尚未完成独立审计），继续复用同一 `GameState`／`CardInstance`／`ZoneRef`、事件队列、合法动作路由、【无懈可击】逐张响应链与群体锦囊逐目标结算框架，不建立第二套状态、牌区、事件或回放系统：

- 模式 ID 仍为 `production_basic_cards_batch`（双人生产切片）；正式牌堆总实体牌数仍为160，实例ID唯一；【五谷丰登】2张（♥3、♥4，实例088／091）、【铁索连环】6张（♣10、♣J、♣Q、♣K、♠J、♠Q，实例071／074／077／080／154／157）真实读取牌堆CSV实体并绑定生产适配器，其余21种正式卡牌（含1种未实现普通锦囊：借刀杀人）继续失败关闭；
- 【五谷丰登】使用时只提交使用动作、不提交目标列表：引擎按当前存活且仍在游戏中的角色数量快照目标序列（含使用者、按行动顺序、跳过已死亡角色），并一次性从牌堆展示等量实体牌到公共 `ZoneKind.REVEALED` 区域；牌堆不足时复用正式重洗与确定性 RNG 逻辑，合计仍不足则 `ProductionBatchDeckExhaustedError` 失败关闭；`CARD_REVEALED` 事件公开实体ID、card_key、牌名、花色、点数与展示池顺序；
- 【五谷丰登】每名目标先打开独立【无懈可击】窗口：被取消目标不选牌、展示池保持并继续下一目标；未取消目标从公开展示池选择一张并获得（`CARD_MOVED`＋`CARD_GAINED`＋`group_target_resolved`）；公共选择动作绑定会话、窗口、根锦囊实例、当前目标与索引、展示池有序摘要（`pool_digest`）与状态哈希，池外实体、重复选择、非当前目标、旧窗口、旧摘要与跨会话选择一律失败关闭；全部目标完成后剩余展示牌统一进入弃牌堆（reason=`wugu_remaining_to_discard`），原锦囊此时才从处理区进入弃牌堆；游戏提前结束执行确定性清理（展示池与处理区不滞留实体）；
- 【铁索连环】正常使用选择一名或两名互不相同的角色（可含使用者、无距离限制）；目标结算顺序由服务器以使用者为锚点按行动顺序规范化，不信任玩家提交顺序；原锦囊保持处理区直到全部目标完成；每名目标独立【无懈可击】窗口，未被无懈的目标切换横置状态（`chained` 进入 `PlayerState` 与状态快照／哈希）并产生 `chained_state` 事件（actor、target、old_value、new_value、root_card_instance_id、reason、目标索引与总数）；
- 【铁索连环】重铸不是使用也不是打出：不产生普通 `card_used`／`card_played`、不指定目标、不接受【无懈可击】；实体从手牌直接进入弃牌堆（`card_recast` 事件，reason=recast）后通过正式摸牌接口摸1张（reason=`tiesuo_recast`），牌堆不足复用正式重洗逻辑；重铸动作进入严格回放决策日志；
- 本批明确只完成铁索牌本体，不实现属性伤害传导：`tiesuo_card_body_implemented=true`、`tiesuo_chain_damage_implemented=false`、`tiesuo_full_semantics_complete=false`；CP-04J 前，横置角色受到火／雷属性伤害时，生产入口在统一伤害前置校验（`_assert_chain_damage_gate`）处抛 `UnsupportedRuleError` 失败关闭，当前动作未被提交，绝不静默生成“未传导但看似完整”的结果；无属性伤害命中横置角色、火／雷属性伤害命中未横置角色仍正常结算；该临时门禁在 CP-04J 实现传导后移除；借刀杀人仅记录用户确认规则（见 Knowledge 4.6.1），等待装备生产切片（CP-04K）；
- CP-04I 独立审计三个非阻塞问题已由审计问题关闭提交 `5b1c2c15b6a8e21563aab02d8a5c181c553e4967`（fix: close wugu and tiesuo card-body audit gaps）正式关闭：`worktree_commit_pending=false`，不再等待用户提交工作树；当前等待的是最终独立复审结论和审计里程碑收尾（`independent_audit_done=false`、`audit_conclusion=NOT_AUDITED_YET`、`status=committed_pending_audit`、`milestone_tag=null`），当前仍不得写成 audited；五谷展示在牌量不足时先做统一可用性预检再登记事件，`ProductionBatchDeckExhaustedError` 与属性伤害 `UnsupportedRuleError` 抛出后状态、事件、RNG、runtime、执行哈希全部保持不变（原子不可见）；铁索重铸在局部不可变状态上先完成“重铸铁索进入弃牌堆→正式摸1张”再一次性登记事件，因重铸牌自身进入弃牌堆即构成至少1张可重洗实体，正式语义下不存在真实可达的牌量不足路径（不可达）；
- 新增 51 项真实生产路径验收测试（`tests/test_sgs_production_remaining_ordinary_tricks.py`），覆盖五谷注册表与2张实体、目标序列含使用者、双人展示2张、公开展示事件、逐目标独立无懈、单无懈跳过／双无懈恢复、选牌进手牌、唯一实体移除、剩余弃置、牌堆不足重洗、池摘要过期、旧窗口重放、非当前目标、池外实体、重复选择、跨会话、严格回放与篡改、玩家可见边界；铁索注册表与6张实体、一／二目标、含使用者、重复／空／三目标拒绝、服务器规范目标顺序、逐目标无懈、false→true／true→false、状态事件、处理区滞留、重铸不是使用或打出、重铸直接弃置并摸1、重铸无目标、非铁索实体／非手牌实体拒绝、严格回放与篡改、chained 进入状态哈希、未实现属性传导不被误写为完成；完整 pytest 为 `1454 passed`（失败0、跳过0）。

本批次只验证双人生产切片：当前正式生产入口原生仅支持双人会话，三人以上五谷展示数量与完整选择顺序、铁索目标顺序与多人属性伤害传导仍未由正式生产入口证明（NOT PROVEN），文档不得写成完整军八、2v2或斗地主完成；不构成普通锦囊批次完成、正式单挑完成或里程碑 B 完成。

## 3. foundation 已有接口与完整对局缺口

当前已经存在以下 foundation 接口：

```text
CardInstance
PlayerState
GameState
EventQueue
ResponseWindow
DamageEvent
LegalAction
DeterministicRNG
ReplayRecord
enumerate_legal_actions
```

其中 `enumerate_legal_actions` 已被测试专用三牌单挑切片真实使用，但尚无正式模式的完整生产适配器；foundation 通用 `ReplayRecord` 仍只验证记录完整性，测试切片则另有 `DuelReexecutionReplay` 完成严格规则重执行。`AuthoritativeCoreSession.run_game` 虽有方法占位，但仍必然抛出 `UnsupportedRuleError`，所以正式完整 `run_game / simulate_game` 仍属缺失。现有局部规则和技能状态尚未统一迁移，不能据此宣称完整正式引擎已经存在。

## 4. 完整性与正式发布门禁

当前正式失败关闭入口会在开局前检查：

```text
unsupported_rules == 0
approximation_count == 0
参战武将程序实现完成
参战武将确定性测试通过
当前模式完整实现
160张牌堆正确加载且实例ID唯一
规则版本可确定
AI合法动作枚举完整
回放可确定性复现
```

`scripts/sgs_engine_gate.py` 提供结构化门禁，`scripts/sgs_formal_runner.py` 会真实加载并审计正式160张牌堆。门禁的正式牌数固定为160，入口类型与核心导入由真实路径、源码 AST 和 SHA-256 现场派生；当前“完整整局核心未完成”状态不可由调用方自行改成通过。虽然权威 foundation 已存在，但完整卡牌／阶段规则循环、模式、AI、参战武将整局实现、生产动作适配器和规则版本尚未就绪；`run` 当前返回退出码2，`simulation_executed=false`，并且不会创建请求的输出目录或文件。任一条件不满足时必须继续拒绝正式模拟，并返回中文结构化错误。禁止：

- 用固定概率或固定收益替代缺失技能；
- 只维护手牌数量而假装执行实体牌操作；
- 遇到 unsupported 后继续计算；
- 以启发式强制判胜掩盖对局未结束；
- 将实验输出标成正式胜率；
- 在没有入口时把 `unsupported_rules` 或 `approximation_count` 虚报为零。

当前不存在正式完整对局，不能给出整局运行所得的 unsupported／approximation 精确总量。状态入口明确记录：`unsupported_rules=1` 是“至少存在一个完整整局能力阻塞”的哨兵值，不是精确的未实现规则条数；`approximation_count=0` 只表示入口拒绝后没有执行任何近似，不表示完整引擎规则已覆盖。

测试专用切片的 `unsupported_rules=0`、`approximation_count=0` 只表示该切片已声明支持的【杀】【闪】【桃】范围内没有静默降级；不得用它覆盖上述正式状态哨兵。

## 5. 当前运行范围

### 可以运行

- 组件级 pytest；
- 通用蒙特卡洛回调、抽牌、统计与排名；
- 明确输入下的局部三国杀规则／技能／策略函数；
- 牌堆 CSV 和结构化卡牌数据校验。
- `python -m scripts.sgs_formal_runner status --mode <模式>` 查看真实牌堆与门禁状态；这不是对局。
- 构造 foundation 会话、确定性洗牌、原子移动实体牌、登记事件并校验回放记录完整性；这仍不是对局。
- 通过生产批处理会话执行【过河拆桥】／【顺手牵羊】目标区域选牌路径：公开装备区／判定区实体候选、隐藏手牌HMAC-SHA256不透明句柄（会话级随机秘密，不可离线枚举）、直接弃置／直接获得、连续【无懈可击】响应链、无合法区域牌结算与严格规则重执行。
- 通过生产批处理会话执行【决斗】／【火攻】伤害型普通锦囊路径：交替打出【杀】与主动不响应（响应【杀】记录为打出而非使用）、伤害来源为另一方参与者、死亡响应者立即结束边界、【火攻】目标本人选择展示手牌（HMAC-SHA256不透明展示句柄，仅选择窗口有效）与使用者同花色弃置／不弃置、1点火焰伤害、被【无懈可击】取消不打开后续窗口、无合法展示牌结算与严格规则重执行。
- 运行测试专用最小单挑切片及其严格规则重执行回放：

  ```powershell
  .\.venv\Scripts\python.exe -m scripts.sgs_dev_runner duel-smoke --seed 20260801 --max-steps 500 --save-replay .\artifacts\test-only-duel.json
  .\.venv\Scripts\python.exe -m scripts.sgs_dev_runner replay .\artifacts\test-only-duel.json
  ```

  两条命令输出均固定带有 `test_only=true`、`formal_result=false`，且不输出胜率。

### 不可作为正式能力运行

- 正式160张牌无技能单挑，以及2v2、斗地主、五人身份、普通八人或限时八人的完整对局；
- 任意武将的端到端技能对局；
- 网页人工对局、PvE 或 AI 观战；
- 任一模式的完整生产合法动作枚举；
- 正式通用规则重执行回放、单步对局和回放 UI；测试专用单挑的严格重执行能力不能外推为正式通用能力；
- 正式多进程胜率。

## 6. 外部旧脚本隔离状态

外部文件均位于 `C:\Users\ASUS\Downloads`，不在正式项目目录中。正式源码全文未发现对下列入口的导入或调用：

- `sgs_sim_engine_worker.py`；
- `sgs_sim_aggregate.py`；
- `sgs_ai_audit_20260729.py`；
- `复现_三国杀16将三模式近似模拟.sh`。

因此这些脚本当前没有污染正式调用链。它们不应复制到 `scripts/`，也不应作为未来权威核心的基础。旧结果的详细失效状态见 `docs/LEGACY_RESULTS_INVALID.md`。

## 7. 测试状态

较早基线实际执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 947 passed in 3.39s
```

上述旧基线不再代表当前能力。现在已经存在测试专用 `GameState` 单挑纵向切片和严格重执行测试，但仍没有正式160张牌整局测试。未运行的网页测试、类型检查、lint 或 CI 不能宣称通过。

本任务新增的阶段2专项验证实际执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_sgs_engine_gate.py
# 19 passed
.\.venv\Scripts\python.exe -m pytest -q tests/test_sgs_formal_runner.py
# 9 passed
```

阶段 4 foundation 和里程碑 A 已覆盖核心模型、动作、随机记录、原子会话、测试专用完整对局、50-seed 完成矩阵、严格规则重执行、篡改检测和开发 CLI。最新完整测试实际执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 1252 passed；失败0、跳过0（新增50项目标区域选牌生产路径测试）
# 1281 passed；失败0、跳过0（在1252基础上新增29项隐藏手牌句柄HMAC安全回归测试）
# 1332 passed；失败0、跳过0（在1281基础上新增51项【决斗】／【火攻】生产路径测试）
# 1334 passed；失败0、跳过0（2026-08-03 独立只读审计 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES 后补充两个确定性回归测试）
# 1403 passed；失败0、跳过0（在1334基础上新增69项群体普通锦囊批次生产路径测试）
# 1454 passed；失败0、跳过0（在1403基础上新增51项剩余普通锦囊批次【五谷丰登】完整生产语义＋【铁索连环】牌本体生产路径测试）
# 1463 passed；失败0、跳过0（在1454基础上新增9项审计问题关闭回归：清单状态、横置角色火／雷／火攻失败关闭原子性、无属性与未横置正常结算、五谷牌量不足原子性、铁索重铸空牌堆空弃牌堆成功重洗摸回、重铸牌参与重洗候选池）
.\.venv\Scripts\python.exe -m compileall -q scripts tests
# 通过
.\.venv\Scripts\python.exe -m scripts.sgs_source_integrity_audit . --fail-on-defect --pretty
# 扫描114个Python文件，defect_count=0；54项均为显式门禁字段或测试证据等audit_item
```

当前开发依赖仅声明 pytest 与 pandas；未发现 mypy、ruff、前端 `package.json` 或 CI 配置。因此类型检查、lint、前端测试和 CI 是“未配置”，不是“已通过”。

## 8. 版本与检查点

当前目录是 Git 工作树。已确认检查点：

- 阶段4 foundation：`858d6ce`；
- 审计基线文档：`5eac686`；
- 里程碑 A 测试专用单挑纵向切片：`455685d6eaa1c297e9ec48a0cfaeb803b81f3406`。
- 隐藏手牌句柄HMAC安全修复：`1b5e125ad0baa129458b42043aac08b18dcfad96`（fix: secure hidden hand choice handles）。
- 【决斗】／【火攻】批次（`CP-04G-PRODUCTION-DUEL-FIRE-ATTACK-BATCH`）：已由用户在外部PowerShell提交（实现提交哈希 `b3587912da97825871ae91ea8a88b3e95c39fdde`，feat: implement production duel and fire attack slice）；2026-08-03 独立只读审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，补充两个确定性回归测试；审计收尾真实提交为 `9c2070017fe624295ebd735bf5163f48a6ac2207`（test: close duel and fire attack audit gaps），里程碑标签 `milestone-b2-duel-fire-attack-audited` 已建立；本批基线为 `85ffee7ca4b06470b0dcb3b1b52155093055b219`（milestone-b2-zone-target-tricks-audited）。
- 群体普通锦囊批次（`CP-04H-PRODUCTION-GROUP-TARGET-TRICK-BATCH`）：【南蛮入侵】3张、【万箭齐发】1张、【桃园结义】1张接入生产适配器并建立逐目标结算框架（见 2.8 节）；已由用户在外部PowerShell提交（实现提交哈希 `5f2fbf27b7041bbf3010636de37306eea5da6256`，feat: implement production group-target trick slice，完整 pytest `1403 passed`）；基线提交 `7414b0661a5cd7599d392f5ae5b287a7147438ac`，检查点文档提交 `8d68231e336dbe213ffad1c5aaa3101896fe5f2f`；2026-08-03 独立只读审计完成：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES（问题修复提交 `ef98245aef32848468c7b2c4a7821ec9ae65146b`，test: close group-target trick audit gaps），最终独立复审结论 AUDIT_PASSED（复审残项关闭提交 `d2e4f49925c0bb285d44092821c3a85c496571ef`，test: complete group-target trick reaudit closure）；里程碑标签待用户提交文档后建立。

里程碑 A 的提交只证明隔离三牌切片，不证明正式160张牌无技能单挑完成。
- 剩余普通锦囊批次（`CP-04I-PRODUCTION-REMAINING-ORDINARY-TRICK-BATCH`）：【五谷丰登】2张完整生产语义＋【铁索连环】6张牌本体接入生产适配器（见 2.9 节）；已由用户在外部PowerShell提交实现（实现提交哈希 `20cb1b1f766529a88aa5f3346a4761b77eca66b7`，提交信息 feat: implement wugu and tiesuo card-body slice）；基线提交 `6af30432993d908546d7cec114fd78ae62798ad5`（里程碑标签 `milestone-b2-group-target-tricks-audited` 指向该提交）；尚未完成独立审计，不得视为 audited。

## 9. 下一可验收版本

下一版本最小目标不是网页或全武将，而是里程碑 B“正式160张牌无技能单挑”。当前明确阻塞为：

1. 正式 Knowledge 尚未把当前160张牌堆纳入单挑适用范围；同名武将、先手首轮摸牌修正等单挑配置仍须由资料或显式配置确定（六种基本牌批次已锁定双人、先手摸2的确定性开局约定）；
2. `AuthoritativeCoreSession.run_game` 仍是失败关闭占位，尚未接入正式对局循环；
3. 38 个正式 `card_key` 中已有六种基本牌、【无中生有】／【无懈可击】、【过河拆桥】／【顺手牵羊】、【决斗】／【火攻】、群体普通锦囊【南蛮入侵】／【万箭齐发】／【桃园结义】以及【五谷丰登】接入生产适配器批次，【铁索连环】已接入牌本体（6张实体，属性伤害传导未完成不计入完整实现），其余21种（含1种普通锦囊：借刀杀人；3种延时锦囊；17种装备）仍未接入权威 `GameState` 的生产适配器；
4. 普通使用牌、响应牌、判定牌和死亡后牌区清理等完整牌生命周期仍有资料或统一实现缺口；
5. 普通锦囊精确事件语义已闭合到当前批次：五谷公开展示池、逐目标选牌与剩余展示牌统一弃置、提前结束确定性清理（CP-04I 用户确认口径）；铁索横置状态切换（`chained_state`）与重铸（`card_recast`）事件已闭合，但属性伤害传导未实现（`tiesuo_chain_damage_implemented=false`，等待CP-04J）；CP-04J 前横置角色受到火／雷属性伤害时生产入口以 `UnsupportedRuleError` 失败关闭（临时门禁，CP-04J 实现传导后移除）；五谷展示牌量不足失败关闭保持原子一致；铁索重铸因重铸牌自身进入弃牌堆而可重洗摸回，正式语义下不存在真实可达的牌量不足路径（不可达）；借刀杀人的武器转移与出杀次数口径（响应借刀不受本出牌阶段已用杀次数的前置限制、成功后正常计入次数、仅次数用尽不构成无合法杀，2026-08-04 用户移动版实测修正，见 Knowledge 4.6.1）依赖装备生产切片（CP-04K）；延时锦囊的精确事件语义以及非摸牌操作彻底耗尽后的处理仍存在歧义或分析约定；
6. 里程碑 B 要求的正式100-seed 门槛尚未执行；测试切片的50-seed 结果不能替代它。

只有解决上述阻塞、正式范围内 `unsupported_rules=0`、`approximation_count=0`，并完成100-seed、严格回放、牌守恒和完整 pytest 验收后，才可将 `formal_duel_no_skill_ready` 改为 `true`。其他模式和武将仍需分别验收。
