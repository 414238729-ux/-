# 三国杀正式引擎状态

> 更新日期：2026-08-02
> 状态：已有权威核心 foundation、测试专用最小单挑纵向切片、正式160张牌堆上六种基本牌的生产适配器批次、最小普通锦囊垂直切片（【无中生有】、【无懈可击】），以及目标区域选牌批次（【过河拆桥】6张、【顺手牵羊】5张接入生产适配器）；但正式整局引擎仍未完成，正式入口继续失败关闭。
> 本文是运行能力状态页，不得用测试总数或文档完整度替换完整引擎验收。

## 0. 机器可读状态摘要

```text
authoritative_core_foundation=true
minimal_duel_vertical_slice=true
reexecution_replay_supported=true
production_basic_cards_batch=true
production_single_target_trick_slice=true
production_zone_target_trick_batch=true
authoritative_full_game_core=false
formal_duel_no_skill_ready=false
formal_run_ready=false
```

`production_basic_cards_batch=true` 只描述正式160张牌堆中六种基本牌（普通【杀】、火【杀】、雷【杀】、【闪】、【桃】、【酒】）已接入生产适配器批次；`production_single_target_trick_slice=true` 只描述【无中生有】（4张）与【无懈可击】（7张）的最小普通锦囊垂直切片；`production_zone_target_trick_batch=true` 只描述【过河拆桥】（6张）与【顺手牵羊】（5张）接入生产适配器并共用“目标区域选牌、隐藏手牌选择、实体牌移动”基础设施，不表示普通锦囊批次完成，也不表示正式160张牌无技能单挑完成；其余28种正式卡牌（含8种未实现普通锦囊）仍未实现，正式整局入口继续失败关闭。当前计数口径必须分开：

```text
[test_only_duel_vertical_slice]
unsupported_rules=0
approximation_count=0

[formal]
unsupported_rules=1  # 至少存在一个完整正式整局能力阻塞的哨兵，不是精确缺项数（38种正式卡牌中仍有28种未接生产适配器）
approximation_count=0  # 正式入口拒绝执行，所以没有运行近似

[production_basic_cards_batch]
implemented=true
tested=true
card_types=6
unsupported_rules=1  # 批次范围外（锦囊、装备等32种正式卡牌）仍失败关闭
approximation_count=0

[production_single_target_trick_slice]
implemented=true
tested=true
card_types=2  # 【无中生有】4张、【无懈可击】7张，共11张实体牌
unsupported_rules=1  # 切片范围外（其余8种普通锦囊、延时锦囊、装备等28种正式卡牌）仍失败关闭
approximation_count=0

[production_zone_target_trick_batch]
implemented=true
tested=true
card_types=2  # 【过河拆桥】6张、【顺手牵羊】5张，共11张实体牌
unsupported_rules=1  # 批次范围外（其余8种普通锦囊、延时锦囊、装备等28种正式卡牌）仍失败关闭
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
| 当前组件测试是否通过 | 是；本轮最终完整测试为 `1252 passed`，失败0、跳过0 |

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
- 最终生效时重新读取目标当前区域状态并进入 `zone_choice` 目标区域选牌动作：公开区域（装备区、判定区）以明确实体候选（实体ID＋card_key）展示；隐藏手牌区只暴露绑定“选择窗口＋目标＋区域＋状态哈希”的不透明SHA-256句柄（`h_`前缀摘要），决策输入不携带牌名、花色、点数或可识别实体ID，权威引擎解析句柄后移动真实实体；过期或伪造句柄、区域、实体、状态哈希一律失败关闭；
- 【过河拆桥】生效后把目标区域内一张实体牌直接置入弃牌堆（`discard_direct`，不发生先获得再弃置）；【顺手牵羊】生效后把目标区域内一张实体牌直接从原区域移入使用者手牌（`gain_direct`）；两张牌都记录原区域、原所有者、新所有者、来源锦囊、是否来自隐藏区域以及“结算时无合法区域牌”的可审计原因；
- 无懈链结束时目标三个区域已无合法牌时：不把原使用追溯为非法、不凭空选牌或移动，原锦囊仍进入弃牌堆，结算移动事件带 `no_legal_zone_card=true` 完成；
- 判定区和装备区只作为这两张牌的合法目标区域参与实体牌移动；卡牌本身的装备、判定、延时锦囊使用效果仍未实现，相关测试仅用不可变 `GameState` 与正式牌区移动接口布置夹具，不表示装备或延时锦囊效果已实现；
- 新增 50 项真实生产路径验收测试（`tests/test_sgs_production_zone_target_tricks.py`），覆盖注册表绑定、使用合法性、无懈链、弃置／获得、隐藏信息隔离、严格回放与失败关闭；完整 pytest 为 `1252 passed`。

本批次只验证双人生产切片，不构成普通锦囊批次完成、多人响应链完成、正式单挑完成或里程碑 B 完成。

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
- 通过生产批处理会话执行【过河拆桥】／【顺手牵羊】目标区域选牌路径：公开装备区／判定区实体候选、隐藏手牌不透明句柄、直接弃置／直接获得、连续【无懈可击】响应链、无合法区域牌结算与严格规则重执行。
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
.\.venv\Scripts\python.exe -m compileall -q scripts tests
# 通过
.\.venv\Scripts\python.exe -m scripts.sgs_source_integrity_audit . --fail-on-defect --pretty
# 扫描110个Python文件，defect_count=0；54项均为显式门禁字段或测试证据等audit_item
```

当前开发依赖仅声明 pytest 与 pandas；未发现 mypy、ruff、前端 `package.json` 或 CI 配置。因此类型检查、lint、前端测试和 CI 是“未配置”，不是“已通过”。

## 8. 版本与检查点

当前目录是 Git 工作树。已确认检查点：

- 阶段4 foundation：`858d6ce`；
- 审计基线文档：`5eac686`；
- 里程碑 A 测试专用单挑纵向切片：`455685d6eaa1c297e9ec48a0cfaeb803b81f3406`。

里程碑 A 的提交只证明隔离三牌切片，不证明正式160张牌无技能单挑完成。

## 9. 下一可验收版本

下一版本最小目标不是网页或全武将，而是里程碑 B“正式160张牌无技能单挑”。当前明确阻塞为：

1. 正式 Knowledge 尚未把当前160张牌堆纳入单挑适用范围；同名武将、先手首轮摸牌修正等单挑配置仍须由资料或显式配置确定（六种基本牌批次已锁定双人、先手摸2的确定性开局约定）；
2. `AuthoritativeCoreSession.run_game` 仍是失败关闭占位，尚未接入正式对局循环；
3. 38 个正式 `card_key` 中已有六种基本牌、【无中生有】／【无懈可击】以及【过河拆桥】／【顺手牵羊】接入生产适配器批次，其余28种（含8种普通锦囊、3种延时锦囊、17种装备）仍未接入权威 `GameState` 的生产适配器；
4. 普通使用牌、响应牌、判定牌和死亡后牌区清理等完整牌生命周期仍有资料或统一实现缺口；
5. 【五谷丰登】未被选取亮出牌的最终去向、其余普通锦囊（【决斗】、【火攻】、【借刀杀人】、群体锦囊等）／延时锦囊的精确事件语义，以及非摸牌操作彻底耗尽后的处理仍存在歧义或分析约定（【无懈可击】响应事件已按本项目约定闭合：生成 `card_used`、不生成普通 `card_played`、计入使用或打出总数；【过河拆桥】／【顺手牵羊】的目标区域选牌与直接弃置／直接获得事件已闭合）；
6. 里程碑 B 要求的正式100-seed 门槛尚未执行；测试切片的50-seed 结果不能替代它。

只有解决上述阻塞、正式范围内 `unsupported_rules=0`、`approximation_count=0`，并完成100-seed、严格回放、牌守恒和完整 pytest 验收后，才可将 `formal_duel_no_skill_ready` 改为 `true`。其他模式和武将仍需分别验收。
