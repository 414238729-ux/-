# POST-B 开发状态（POST_B_DEVELOPMENT_STATUS）

> 状态标签：`AUDITED_SCOPE_READY_FOR_NEXT_DEVELOPMENT_STAGE`、`AUDITED_PASSED`
> （CURRENT：`AUTHORITATIVE_GENERAL_BATCH_V1` 的 G1 / `shamoke` 已完成；
> G2 / 诸葛瞻已完成 closure audit、final full pytest 与 documentation
> finalization；G3 / 王元姬尚未开始；Batch V1 仍为 `IN_PROGRESS`）
>
> 本文件是 POST-B 开发轨（deepseek-post-milestone-b-development）的新增状态文档，
> 未登记进 `docs/CHECKPOINT_MANIFEST.json`，也不修改任何已登记文档
> （`docs/CHECKPOINT_MANIFEST.json` 与 `docs/ENGINE_STATUS.md` 是冻结审计目标，
> 其 sha256 表项不得因本文件而失效）。

## 0. POST-B 轨道状态

- `POST_B_C1_MULTIPLAYER_AUTHORITATIVE_FOUNDATION` = `AUDITED_PASSED`（`C123_GLOBAL_AUDIT_2_PASSED`）
- `POST_B_C2_MULTIPLAYER_CARD_SEMANTICS_CLOSURE` = `AUDITED_PASSED`（`C123_GLOBAL_AUDIT_2_PASSED`）
- `POST_B_C3_FORMAL_NO_SKILL_2V2_MODE` = `AUDITED_PASSED`（`C123_GLOBAL_AUDIT_2_PASSED`）
- `POST_B_C4_FORMAL_NO_SKILL_DOUDIZHU_MODE` = `AUDITED_PASSED`（`C4_FINAL_CLOSURE_RECHECK_PASSED`；被审计
  implementation commit = `4c2969fcc0d36da862b6a7f29d827e427c60f501`，实现身份 =
  `a06f0fb2ea614325c9f27bcc44d035cfbe8cc4dfbe5dc961ca343bd872fe3434`。
  本文件随后的 status-closure commit 只记录复审与文档收口结果，不得冒充该
  implementation SHA。当前 C4 scope 完成独立终局复核与全量测试闭环，进入
  `AUDITED_SCOPE_READY_FOR_NEXT_DEVELOPMENT_STAGE`。）
- `POST_B_C5_FORMAL_NO_SKILL_FIVE_PLAYER_STANDARD_IDENTITY_MODE` = `AUDITED_PASSED`
  （最终被独立审计的 implementation SHA =
  `60dc98d0ebc3273087fc55dd44b45ac3f9a5b4b2`，implementation identity =
  `bcb33198b8e3c5551ce53353d0707c579c7febc6e30cd95c20b00b681235bbad`；独立复审结论为
  `C5_INDEPENDENT_AUDIT_PASSED`。本文件后续的 documentation closure commit
  只登记审计与状态，不得冒充被审计 implementation SHA。当前 C5 scope 进入
  `AUDITED_SCOPE_READY_FOR_NEXT_DEVELOPMENT_STAGE`。）
- `POST_B_C6_FORMAL_NO_SKILL_NORMAL_EIGHT_PLAYER_IDENTITY_MODE` = `AUDITED_PASSED`
  （被独立审计的 implementation SHA =
  `259744b6d0cb5aa60313af19f18ebcd9ea3e8675`，implementation identity =
  `b6a312c06ea176ea5f66ad4c1dd4131b74ff56ca14dbc114ceceec25ed9a87f3`；独立审计结论为
  `C6_INDEPENDENT_AUDIT_PASSED`。documentation closure commit 本轮尚未创建；
  未来 docs-only closure SHA 只记录状态，不得冒充被审计 implementation SHA。
  当前 C6 scope 进入 `AUDITED_SCOPE_READY_FOR_NEXT_DEVELOPMENT_STAGE`。）
- `POST_B_C7_FORMAL_NO_SKILL_MOBILE_EIGHT_PLAYER_HEIR_AND_SPY_CHOICE_IDENTITY_MODE`
  = `AUDITED_PASSED`（被独立审计的 implementation SHA =
  `75f91dde8da61265645a00a8ebc153591e66ef8d`，parent remediation baseline =
  `532d678d66342b620d6ed8e464df9fb601190a4d`，implementation identity =
  `5b4a300fda38749b42a1754f5ec9e7814e6a5edabdaa804ab1509f83276df9d4`。
  C7 frozen-scope final independent closure sweep = `PASSED`，confirmed defects =
  `NONE OPEN`。三项 observation 保持 OPEN / non-blocking；本次 docs-only closure
  commit 只登记状态，不得冒充被审计 implementation SHA。当前 C7 scope 进入
  `AUDITED_SCOPE_READY_FOR_NEXT_DEVELOPMENT_STAGE`，见 §13。）
- `AUTHORITATIVE_SKILL_RUNTIME_V1` =
  `IMPLEMENTED / FINAL CLOSURE REAUDIT PASSED /
  2988/2988 FULL PYTEST PASSED / AUDITED_PASSED`
  （当前分支 = `codex/authoritative-skill-runtime-v1`，基线 HEAD =
  `e31c186a3833b0bfaa59969cbca65202e779cfc0`，当前
  `POST_B_CURRENT_IMPLEMENTATION_IDENTITY` =
  `2460d3ac6998746a4aa5c13cf84321d652b965d9a462d325b41519625116c949`。
  不等于 all generals / full skill roster / FULL_GAME_READY / RELEASE_READY /
  formal win-rate ready / AI ready。见 §15。）
- `AUTHORITATIVE_GENERAL_BATCH_V1` = `IN_PROGRESS`
  （G1 / `shamoke` = `GENERAL_COMPLETE`；
  `G1_SHAMOKE_SIXTH_CLOSURE_AUDIT = PASSED`；
  `G1_SHAMOKE_FINAL_FULL_PYTEST = PASSED`；
  G2 / 诸葛瞻 = `GENERAL_COMPLETE`，且
  `G2_ZHUGEZHAN_DOCUMENTATION_FINALIZATION = PASSED`；
  `G2_ZHUGEZHAN_FIRST_ADVERSARIAL_AUDIT = FAILED` 与
  `G2_ZHUGEZHAN_SECOND_ADVERSARIAL_AUDIT = FAILED` 均作为历史结论保留，
  后续 findings 已关闭并完成 closure audit 与 final full pytest；
  G3 / 王元姬尚未开始。Batch V1 不得登记为
  `COMPLETE`、`AUDITED_PASSED` 或 frozen complete。当前 implementation identity / pin =
  `7394e4ca25c85f4e9454bad363c707c7a1487d0b027c014c4d8708c176359c66`，
  见 §16–§21。）
- `F-003` = `CLOSED`
- `F-004` = `CLOSED`
- `F-005` = `CLOSED`
- `F-006` = `CLOSED`
- `C123-R1-NEW-001` = `CLOSED`（`REMEDIATION_2_REAUDIT_PASSED`；被审计
  implementation commit = `677d81c131df1e02842919b47e7ab6c02c8c703b`。
  本文件随后的 status-closure commit 只记录复审结果，不得冒充该
  implementation SHA。历史正交 rem2 独立复审通过。）
- `C123-GLOBAL-001` = `CLOSED`（`C123_GLOBAL_REMEDIATION_1_REAUDIT_PASSED`；被审计
  implementation commit = `7979eca3d27e8a74f29062e344b2fa05081aad66`。
  本文件随后的 status-closure commit 只记录复审结果，不得冒充该
  implementation SHA。HISTORICAL 全局跨检查点敌对审计目标
  `54201375cdb8b82b9af0947de49b0002c5bf4188` 结论为 FAILED /
  BLOCKER FOUND（C123-GLOBAL-001
  MULTITARGET_SLASH_ROOT_PREMATURE_FINISH_AFTER_RESCUED_CHAIN_TARGET），
  不得改写为当时误报或 `C123_GLOBAL_AUDIT_PASSED`。
  历史全局 rem1 独立复审通过。）
- `C123_GLOBAL_AUDIT_2` = `PASSED`（`C123_GLOBAL_AUDIT_2_PASSED`；被审计
  目标 SHA = `18c39c65bb67eb12fcce7e9d2954d2c3a908879c`；
  `checkpoint-post-b-c123-global-remediation-closed` 指向同一 commit；
  审计 worktree 处于 detached HEAD at `18c39c65bb67eb12fcce7e9d2954d2c3a908879c`。
  `PREVIOUS_REPORT_REQUIRED_PROVENANCE_CORRECTION = COMPLETED`，纠错后
  报告为权威定义与证据映射依据。当前 18c39c65 checkpoint 上已实现的
  Post-B C1/C2/C3 scope 完成第二轮跨检查点整体独立敌对审计并通过，
  满足质量门禁，状态为 `AUDITED_SCOPE_READY_FOR_NEXT_DEVELOPMENT_STAGE`。）
- `C4-AUDIT-001` = `CLOSED`（`C4_REMEDIATION_1_REAUDIT_PASSED`；被审计
  implementation commit = `d7db68a2b989bc9b34bdca6ef04fa90ff23b1eb0`。
  非终局农民死亡判定索引清理写回已在异步奖励窗口前恢复；历史首次独立审计结论为
  `C4_INDEPENDENT_AUDIT_1_FAILED`，不得改写为 PASSED。）
- `C4-GLOBAL2-001` = `CLOSED`（`C4_GLOBAL_REMEDIATION_2_REAUDIT_PASSED`；被审计
  implementation commit = `e28fa96917c94ab49e38fb52d7ab10cff8ff4c7a`。
  配置权威 recursive exact-type 与受信任能力工厂已建立；历史跨检查点审计结论为
  `C4_GLOBAL_AUDIT_2_FAILED`，不得改写为 PASSED。）
- `C4-COMPLETION-001` = `CLOSED`（`C4_REMEDIATION_3_REAUDIT_PASSED`；被审计
  implementation commit = `4c2969fcc0d36da862b6a7f29d827e427c60f501`。
  借刀子链非终局农民死亡不再提前触发父根 victory cleanup，借刀 exactly-once finalize；
  历史 completion 审计结论为 `C4_COMPLETION_AUDIT_FAILED`，不得改写为 PASSED。）
- `C4-COMPLETION-002` = `CLOSED`（`C4_REMEDIATION_3_REAUDIT_PASSED`；被审计
  implementation commit = `4c2969fcc0d36da862b6a7f29d827e427c60f501`。
  闪电击中所有者非终局农民死亡不再提前清理判定根与区域所有权，判定牌 exactly-once 完成；
  历史 completion 审计结论为 `C4_COMPLETION_AUDIT_FAILED`，不得改写为 PASSED。）
- `C4_FINAL_CLOSURE_RECHECK` = `PASSED`（`C4_FINAL_CLOSURE_RECHECK_PASSED`；被审计
  implementation commit = `4c2969fcc0d36da862b6a7f29d827e427c60f501`；
  detached HEAD clean；`TECHNICAL_C4_AUDIT_SCOPE = READY_FOR_DOCUMENTATION_CLOSURE`；
  2594 passed in 1611.74s，0 failed，0 errors，0 skipped。）
- `C5-AUD-001` = `CLOSED`（首次 C5 independent audit 结论为
  `C5_INDEPENDENT_AUDIT_FAILED_REMEDIATION_REQUIRED`；该 MEDIUM finding 指出
  readiness probe 未检测 `analysis_only=False` trusted formal runtime，造成
  readiness inflation。remediation 后 independent re-audit 已确认 CLOSED。）
- `C5-AUD-002` = `CLOSED`（首次 C5 independent audit 结论同为
  `C5_INDEPENDENT_AUDIT_FAILED_REMEDIATION_REQUIRED`；该 MEDIUM finding 覆盖
  Borrowed Sword、Fangtian、terminal continuation、Lightning 与弱断言等最高风险
  parent/root tests 的假覆盖。remediation 后 independent re-audit 已确认 CLOSED。）
- **C5 final independent re-audit** = `C5_INDEPENDENT_AUDIT_PASSED`（目标 implementation SHA =
  `60dc98d0ebc3273087fc55dd44b45ac3f9a5b4b2`；`C5-AUD-001 = CLOSED`，
  `C5-AUD-002 = CLOSED`，new confirmed CRITICAL/HIGH/MEDIUM correctness finding =
  `NONE`。首次 C5 independent audit 的历史 FAILED 结论永久保留，不得反写成
  PASSED。）

### 0.1 C2 摘要（MULTIPLAYER CARD SEMANTICS CLOSURE）

- 方天画戟多人多目标语义闭合（Knowledge 7.9 用户整理解释）：装备方天＋
  使用作为最后一张手牌的【杀】时可指定至多3个目标；目标组合由权威枚举
  生成、使用时就地快照、逐目标沿用统一杀响应/伤害/濒死结构；死亡目标
  继续后续目标；酒强化+方天多目标交互未由正式规则源确认 → 失败关闭。
- `WEAPON_SKILL_STATUS` 11 种武器全部 COMPLETE；38 类卡牌
  `global_all_cards_implemented=true`（`multi_player_production_proven`、
  `authoritative_full_game_core` 仍为 false；`2v2_ready` 由 C3 正式门禁
  置为 true，见 §9）。
- replay 债务收敛：`initial_configuration.player_ids` 升为一等回放输入
  （自定义玩家ID/座次权威重建）；`finish_reason` 去 duel 硬编码（与已
  校验身份的 OutcomePolicy 产出值比对，伪造/不匹配失败关闭）。
- 非终局死亡继续路径扩展：群体锦囊（C1）+ 方天多目标（C2）；群体锦囊
  目标死亡时根锦囊保持处理区直到全部目标完成。
- C2 实现身份：`5a2c8feb3d030ad659bbe0522f97ba3a4701f7343e80f74505df7d8d4e9b0e33`
- C2 专项测试 `tests/test_post_b_c2_multiplayer_card_semantics.py`：
  32 项真实生产路径（方天合法/非法/伪造/逐目标响应/死亡继续、4p 南蛮/
  万箭/桃园/五谷、三人无懈链、借刀多候选/距离/拒绝转移、闪电 4p 转移/
  跳死、多人距离坐骑、防具逐目标隔离、player_ids/seat replay 往返、
  custom finish_reason、伪造政策拒绝、4-observer 可见性、38 类覆盖矩阵）。
- 全量 pytest：**2412 passed、0 failed、0 errors**（单进程单次调用，
  940.49s；环境插件与 `--basetemp` 位于仓库外，运行后删除）。
- formal duel 防回归：seed 0 → p2/388/43、seed 7 → p2/162/17（与
  R5/R8 记录一致）；冻结 R8 acceptance artifact 仍为历史证据
  （cached_acceptance_report_valid=false，不授权 C2）。

## 1. 当前轨：POST_B_C1_MULTIPLAYER_AUTHORITATIVE_FOUNDATION

**目标（已完成）**：把正式生产核心中隐含的“恰好两名玩家”假设收敛为可复用的
N≥2 多人权威基础；**不是**完成 2v2。C1 只落地项目 1–4，并为项目 5–7 建立
失败关闭的生产钩子：

| 项目 | 内容 | C1 状态 |
| --- | --- | --- |
| 1 | 多人玩家拓扑（座次、存活角色环、存活遍历） | 已落地（`multiplayer.py::PlayerTopology`） |
| 2 | 多人回合循环（沿存活环座次递增继任、跳过死亡角色） | 已落地（`_apply_end_turn` 等） |
| 3 | 群体锦囊目标顺序（服务器使用时快照，跳过死亡角色） | 已落地（`_group_target_sequence` 接入存活环） |
| 4 | 死亡/座位遍历（死亡不重编号、非终局死亡继续结算边界） | 已落地（统一胜负出口 + 群体锦囊继续分支） |
| 5 | 模式胜负规则（2v2/斗地主/五人身份/其它身份变体） | C3 已落地正式2v2；C4 已落地正式斗地主；C5 五人标准身份已 `AUDITED_PASSED`（见 §11）；C6 普通八人标准身份已 `AUDITED_PASSED`（见 §12）；C7 移动版八人主公立储 / 内奸择途特殊身份已 `AUDITED_PASSED`（见 §13）；限时八人、其它特殊身份变体及通用最后一人模式仍不在已审计范围 |
| 6 | 方天画戟多目标 | C2 已实现（7.9 用户整理解释；见 0.1 节） |
| 7 | 2v2 模式规则 | C3 已实现（formal no-skill 2v2，见 §9） |

**状态标志**：

- `2v2_ready = true`（C3 正式门禁；只指 formal no-skill 2v2 静态执行
  资格，不含客户端30分钟墙钟/评分裁定，§2.12 CONFIRMED_OUT_OF_
  SIMULATION_SCOPE）
- `multi_player_production_proven = false`（比“正式2v2已验收”更宽的
  多人生产语义总声明，本轨不置 true）
- `authoritative_full_game_core = false`

C1 没有新建第二套引擎（没有 `MultiplayerEngine`）：`PlayerTopology`/`OutcomePolicy`
只是把既有不可变 `GameState`/`PlayerState`（本就是 N 泛型）之上的顺序与胜负
语义显式化。

## 2. 二人假设清单与收敛结果

两玩家假设盘点（3 个独立子代理 + 主代理复核）确认集中在 5 处，均已处理：

1. `opponent_of` 静态助手 → 保留为**文档化的双人遗留兼容助手**（docstring
   明确标注 legacy；生产路径不再调用，`scripts/sgs_engine` 内 grep
   `opponent_of` 仅剩该定义本身）。
2. `__init__` 双人断言与 p1/p2 发牌 → 泛化为 `player_hp`/`player_max_hp`/
   `player_ids` 元组（N≥2 校验、轮转发牌；N=2 时发牌顺序与旧行为逐张一致）。
3. 响应/救援顺序 `(current_player_id, opponent_of(...))` 二元组（8 处响应 +
   3 处救援）→ 统一 `_response_order_from_turn_player`（`alive_ring_from`，
   含锚点；两人局退化为 `(当前回合角色, 另一名角色)`）。
4. 死亡胜负 `opponent_of(dying)` → `resolve_victory_after_death`（注册策略
   优先；无策略 + 双人 + 显式回退 → 原语义；无策略 N>2 → `UnsupportedRuleError`）。
5. `_apply_end_turn` 继任 `opponent_of` → `PlayerTopology.next_alive`（沿存活
   角色环座次递增、跳过死亡、环回）。

另：`production_cards.py::SlashAdapter` 的杀目标枚举从唯一对手改为
`all_other_alive_ids`（含朱雀羽扇火杀变体、杀次数上限门禁），
`production_replay.py::player_visible_payload` 移除硬编码 `("p1","p2")` 观察者
集合（改为显式 `valid_player_ids`，非法观察者失败关闭）。

## 3. 变更文件（PRECOMMIT 工作树；未提交）

- 新增 `scripts/sgs_engine/multiplayer.py`：`PlayerTopology`、`OutcomePolicy`、
  `DuelOutcomePolicy`、`resolve_victory_after_death`。
- 修改 `scripts/sgs_engine/production_batch.py`：初始化泛化、拓扑属性、
  响应/救援顺序、回合继任、死亡胜负出口与群体锦囊继续分支、丈八门禁、
  `execution_snapshot` schema v1→v2（新增 `player_count`、
  `outcome_policy_identity`）。
- 修改 `scripts/sgs_engine/production_cards.py`：杀目标枚举泛化。
- 修改 `scripts/sgs_engine/production_replay.py`：观察者集合泛化、
  `initial_configuration.outcome_policy_identity` 记录/校验、政策驱动
  `finish_reason`。
- 修改 `scripts/sgs_engine/formal_duel.py`：注册 `DuelOutcomePolicy`。
- 修改 `scripts/sgs_engine/__init__.py`：导出多人基础符号。
- 新增 `tests/test_post_b_c1_multiplayer_foundation.py`：12 项生产路径验收。
- 新增 `tests/test_post_b_c1_precommit_test_state_closure.py`：冻结 R8 证据
  与当前 C1 身份的边界 6 项回归（测试语义收尾）。
- 修改 `tests/test_sgs_formal_duel.py`、
  `tests/test_sgs_audit_remediation_2.py`：把“冻结证据必须等于当前身份”
  的旧 invariant 修正为“历史证据完整性 vs 当前认证边界”分离语义
  （POST_B_C1_PRECOMMIT_TEST_STATE_CLOSURE，只改 tests，不动冻结证据）。

提交边界：本轨**不**执行 `git commit/push/tag/merge/rebase/reset/clean/PR`，
由用户执行最终提交；不修改/移动任何已冻结 Milestone B 审计分支。

## 4. 行为保持（N=2 不回归）

- formal duel canonical 终局对照 R5 记录：seed 0 → 胜者 p2、388 动作；
  seed 7 → 胜者 p2、162 动作、17 回合。二者与 R5 完全一致。
- 两人局所有拓扑调用退化为既有 `opponent_of` 语义（测试 1 逐项对照）。
- `execution_snapshot` schema v2 与 `outcome_policy_identity` 进入执行哈希属于
  **预期变化**；胜者/动作数/回合数不变。

## 5. 测试结果

- 新测试 `tests/test_post_b_c1_multiplayer_foundation.py`：**14 passed**
  （12 项清单 + 2 个变体）。
- 受影响既有套件回归（turn cycle discard / group target tricks / basic
  cards / milestone advancement / hidden handle security）：**209 passed**。
- `python -m compileall -q scripts tests`：通过（无语法错误）。

### POST_B_C1_PRECOMMIT_TEST_STATE_CLOSURE（测试语义收尾）

C1 首轮全量曾出现 3 项失败，根因是旧测试把“冻结 R8 证据必须等于当前
implementation identity”当作 invariant。该 invariant 已按正确语义修正
（历史证据完整性 vs 当前认证边界分离），未修改任何冻结 artifact/manifest
历史事实、未放宽任何 gate：

| 原失败测试 | 修正后的语义 |
| --- | --- |
| `test_sgs_formal_duel.py::test_live_readiness_has_exact_mode_scoped_card_semantics` | 静态卡牌语义断言保留；缓存有效性断言改为身份关系不变式：`cached_acceptance_report_valid ==（当前身份==冻结R8身份）`；规则/牌堆身份仍必须与冻结值一致；`formal_duel_execution_ready` 恒 True（MB-B-001 与缓存分离） |
| `test_sgs_audit_remediation_2.py::test_cached_report_is_not_live_execution` | 同上的身份关系不变式；`build_current_status` 仍必须 `simulation_executed=False`、静态执行资格 True |
| `test_sgs_audit_remediation_2.py::test_manifest_sha256_inventory_is_true_sha256` | 清单语义拆分：post-B 变更集内文件的表项必须仍等于其 R8 时代冻结哈希（历史证据未被改写）且当前文件已偏离；变更集外文件必须与当前文件逐字一致（防篡改） |

新增 `tests/test_post_b_c1_precommit_test_state_closure.py`（6 项显式回归）：
1) 冻结 R8 artifact identity != 当前 C1 identity；2) artifact 可解析且结构
完整；3) 历史 artifact 完整性仍通过（规则/牌堆身份 + seed 0/7 历史终局
记录不变）；4) current gate 拒绝 stale artifact（valid=False、0 seeds、
非认证）；5) stale artifact 不产生 `simulation_executed`/current
certification；6) fresh C1 live execution（seed 0 真实执行 + 严格重执行）
不依赖旧 artifact 即可运行。

三项原失败测试与 6 项新回归全部通过；全量 pytest：**2380 passed、
0 failed、0 errors**（单进程单次调用 `python -m pytest -q`，1153.53s；
环境插件与 `--basetemp` 均位于仓库外，运行后删除）。

## 6. 实现身份

- `BASE_IMPLEMENTATION_IDENTITY`（R8 记录）：`06c8b2d3ead9adb52a18252e398eae137eb8fb51f657909051500893672b0e33`
- `C1_IMPLEMENTATION_IDENTITY`（当前工作树，`implementation_identity()`）：
  `844728ead0e0c0fa1f41ae1fe80cc46fe6562ed126df38fc6d47b36e34ccf8de`

差异由 C1 源码变更引起（`scripts/sgs_engine/**/*.py` 全部进入身份清单；
新增 `multiplayer.py` 自动覆盖）。身份算法保持行尾无关（CRLF→LF 归一）。

## 7. 失败关闭边界（C1 已验收）

- N>2 未注册胜负策略的死亡：`UnsupportedRuleError`（不猜测 2v2/身份场/
  最后一人）；非终局死亡当前仅证明“群体锦囊目标死亡后继续目标队列”，
  其余挂起根继续结算失败关闭。
- 回放重建策略身份不匹配/缺失：`ProductionReplayFormatError`。
- 玩家可见回放非法观察者（含默认双人集合外的四人局观察者）：`ValueError`。
- 伪造/过期多人动作（非当前角色、死亡目标、状态变化后旧 action_id）：
  `InvalidActionError` / `ProductionBatchError`。

## 8. 环境说明与遗留

- 全量测试使用**临时** pytest 插件（`os.mkdir/makedirs` mode 0o777 +
  `ensure_extended_length_path`/死符号链接清理关闭）绕开 Windows 沙箱 tmp 目录
  ACL 问题；插件与 `--basetemp` 目录在运行后**已删除**，不进入提交。
- 环境遗留：仓库根存在更早会话留下的空目录 `.pytest-temp`（已在
  `.gitignore` 中、不在 git 状态内、非本轨创建）；沙箱对其 ACL 拒绝任何
  删除/重置操作，不影响测试与提交内容。
- 其他观察（子代理只读复审，非 C1 范围、未改代码）：通用层
  `engine.py::canonical_state_snapshot` 按 `seat` 排序玩家（生产执行哈希路径），
  `actions.py::_state_fingerprint` 按 `player_id` 排序玩家（通用动作层指纹）；
  两者各自确定性、生产路径不混用（100 seed 严格重执行与 C1 全量均通过），
  仅当自定义 player_id 不按座次字典序时两快照玩家顺序不同，属维护一致性
  观察项；`duel.py`（TEST_ONLY_DUEL_MODE 遗留分析层）与 `duel_replay.py` 的
  p1/p2 硬编码是模式定义而非待泛化假设；`engine.py` 恰好 160 张是正式牌堆
  规模校验，与玩家人数无关；`_rescue_window_id` 的 `seat` 形参实为
  rescue_index（窗口ID字符串 "seat{n}" 属命名瑕疵，无功能影响，暂不改）；
  `production_cards.py` 方天画戟 `len(state.players)!=2` 门禁是 C1 有意保留的
  失败关闭钩子（项目6未实现，C2/C3 处理）。
- 后续项（C1 边界之外，当前均失败关闭、无泄漏；留给 C2/C3）：
  1) `production_replay.py` 回放完整性校验（约 839 行）与重执行终局比对
  （约 1646 行）仍硬性要求 `finish_reason=="opponent_confirmed_dead"`；注册
  策略使用自定义 `finish_reason` 会被拒绝（C1 的 DuelOutcomePolicy 与测试
  脚手架都用默认串，因此不受影响）。模式层引入真实胜负语义时需同步泛化。
  2) `initial_configuration` 未记录 `player_ids`：自定义玩家ID会话的录制/重执行
  会重建默认 p1..pN 而发散（被严格重执行哈希拒绝，失败关闭）；C1 的回放
  验收刻意使用默认ID。后续需把玩家ID/座次/先手升为回放一等头字段。
  3) 玩家可见投影 `_project_public_context` 目前只脱敏弃牌选择句柄与摘要，
  未审计 `pending_wugu.pool/pool_digest` 等其它私有材料——可见性完整性审计
  项（非两人问题），建议另立审计。
- 后续轨（C2/C3）：项目 5–7 的正式语义（模式胜负、方天画戟多目标、2v2
  规则）在 C1 之后另行推进；C1 停止后不自动开始 C2。

## 9. 当前轨：POST_B_C3_FORMAL_NO_SKILL_2V2_MODE

**状态**：`AUDITED_PASSED`（实现完成，预提交门禁全部通过；已完成第二轮全局跨检查点整体独立敌对审计并通过 `C123_GLOBAL_AUDIT_2_PASSED`，进入 `AUDITED_SCOPE_READY_FOR_NEXT_DEVELOPMENT_STAGE`；由用户进行后续阶段推进）。
（历史 C3 closure 边界：当时 C3 停止后不自动开始斗地主；后续 C4 已由用户显式启动并完成，见 §10。）

**范围**：正式、失败关闭、严格可回放的 no-skill 2v2 模式层，复用 C1 多人
基础与 C2 全局卡牌语义（38/38、160 张正式牌堆）；不新建第二套引擎
（无 `TwoVsTwoEngine`），只有 mode profile / team 模型 / OutcomePolicy /
模式层钩子 / 可见性配置。不含：Milestone B 修复、身份模式、斗地主（历史 C3 范围；C4 已完成独立实现与审计，见 §10）、
武将技能、AI 策略、Web、正式胜率阶段。

**规则源**（Knowledge《三国杀模式规则》§2，全部 `当前确认`）：

- §2.9 胜利条件：一方两名角色全部确认死亡 → 对方立即获胜；一名队友死亡
  游戏继续 + 存活队友摸1张；按真实结算顺序逐次确认死亡，不建立“同时死亡”
  抽象；胜负成立后未开始的普通结算停止、已成立的死亡不回滚。
- §2.10 初始体力：模式不修改基础属性；测试角色档案 base_hp/base_max_hp
  = 4/4（角色属性，不是模式加成）。
- §2.11 牌堆耗尽平局：原子步骤开始时不足 → 不半截取牌直接平局；完整执行
  后牌堆为0 → 完成后立即平局；覆盖摸牌/判定/展示等全部消耗牌堆的步骤；
  不自动重洗避免平局。平局是正式 OutcomePolicy 终局（winner=None +
  `2v2_draw_deck_exhausted`），进入 strict replay / canonical outcome。
- §2.12 客户端30分钟：`CONFIRMED_OUT_OF_SIMULATION_SCOPE`（登记不实现；
  safety action cap 触发 = 测试失败，绝不自动判胜）。
- 基础术语 §15.8 传导候选快照规则：Knowledge-only，C3 不实现；§21.2
  `NESTED_INDEPENDENT_ATTRIBUTE_DAMAGE_DURING_CHAIN = WAITING_FOR_VERIFICATION`
  （不修改 `_PendingChainDamage`/`candidate_order`/嵌套传导生产语义）。

**实现（`scripts/sgs_engine/mode_2v2.py` + 生产核心模式层接线）**：

- `Formal2v2Configuration`（canonical profile：1+4 对 2+3、初始手牌 3/4/4/5、
  先手 1 号位、4 号位首轮飞扬、禁手气卡、死亡奖励 1、no_reshuffle_draw）
  与 `TrustedFormal2v2Configuration`（exact type + capability token +
  canonical value 三项权威边界）。
- `TwoVsTwoOutcomePolicy`：`resolve_winner_after_death` 返回队伍ID
  （team_a/team_b）；两队同时无存活在顺序确认死亡下不可达 → 失败关闭；
  `draw_finish_reason = 2v2_draw_deck_exhausted`。
- `TwoVsTwoModePolicy`：initial_hand_counts / first_player_id /
  deck_supply_mode / teams / teammate_of / seat_of / feiyang_available /
  death_confirmed_hook（存活队友摸1张，复用核心 `_mode_death_reward_draw`
  事务：预检不足就地平局、完整后牌堆为0立即平局）。
- `Formal2v2Session(ProductionBasicCardBatch)`：MODE_ID 替换 + exact-type
  会话边界 + 测试角色士兵档案（性别 NONE，雌雄“异性”判定不触发）。
- 生产核心接线：`FEIYANG_ACTIVATE` 阶段（窗口/枚举/发动/放弃、HMAC 候选
  句柄、判定区 entry_index 清理）；按座次初始手牌发牌；确定性先手不消耗
  RNG；`_deck_supply_precheck`（no_reshuffle_draw 口径）+ 8 个取牌步骤的
  完成后平局检查（摸牌/无中/重铸/雌雄/判定/八卦/五谷展示/死亡奖励）；
  死亡处理 winner-None 分支的模式层继续路径（群体锦囊队列 C1、方天多目标
  C2、传导根恢复、单体根牌 finalize 后 `_complete_root_resolution`、当前
  回合角色死亡立即结束回合推进下家）；执行快照新增 `mode_policy_identity`
  与 `teams`（队伍映射序列化，不按座次奇偶推导）。
- 回放：`SUPPORTED_REPLAY_MODES` 含 2v2；`formal_2v2_configuration` +
  `teams` + `analysis_only` + `max_steps` 为一等初始配置；平局终局
  winner=None + draw finish_reason；队伍映射/配置篡改失败关闭；正式结果
  必须绑定 canonical profile；`record_reference_formal_2v2` canonical
  工厂；可见性按 §2.4 队友可见（visible 集合 = 观察者 ∪ 同队队友，
  队伍映射来自回放一等输入）。
- 正式门禁 `inspect_formal_2v2_readiness()`：`2v2_ready =
  formal_2v2_no_skill_ready`（canonical factory 可达 + 38/38 卡牌语义
  复用 + 严格回放支持）；`unsupported_rules` 由现场 blocker 计数派生，
  不得硬编码 0 自我证明。`2v2_ready` 只是静态执行资格，不是 §2.11
  sibling 路径的自证；那些路径由
  `tests/test_post_b_c3_2v2_draw_remediation.py` 等 production
  regression 作为证据。`client_timeout_score_adjudication` 恒 false
  （§2.12）。`multi_player_production_proven` 与
  `authoritative_full_game_core` 保持 false（比“正式2v2已验收”更宽的
  总声明，本轨不置 true）。

**C123 平局 remediation**（实现完成，未独立复审，不做 commit）：

- RC-1：`_finish_game_as_draw` 对 REVEALED 改走
  `_discard_revealed_zone`（既有 revealed-pool 语义），PROCESSING
  仍走 `_finish_processing`。区域清理成功后才登记事件。
- RC-2：胜利与平局共用 `cleanup_finished_transient_runtime()`，由
  `FINISHED_TRANSIENT_RUNTIME_FIELDS` + `_BatchRuntime` 字段默认值
  驱动；平局不再用 `_return_to_play` 冒充终局清场。
- RC-3：`ProductionBatchResult.winner_id: str | None`，并新增
  `finish_reason`。`run()` 不再因 `winner is None` assert；正式平局
  仅在 OutcomePolicy 声明 `draw_finish_reason` 时合法。二人单挑仍
  必须有胜者。
- C123-004：readiness/status/`__init__.py` 丈八/方天陈旧 PARTIAL
  文字与真实 C2 COMPLETE 状态对齐。

**专项测试**（`tests/test_post_b_c3_2v2_mode.py`、
`test_post_b_c3_2v2_replay.py`、`test_post_b_c3_2v2_visibility.py`、
新增 `test_post_b_c3_2v2_draw_remediation.py`）：canonical profile/
队伍/座次/初始化/回合循环、顺序死亡队伍胜负、濒死救援、死亡奖励与
单体/群体/传导/当前回合角色死亡的继续路径、飞扬窗口全边界、队伍
目标合法性、平局（摸牌/五谷/判定/无中/重铸/死亡奖励/八卦的不足与
恰好耗尽）、`run()` 正式平局返回、FINISHED transient inventory
防漂移、复杂平局 record/reexecute 往返、20 种子自然结束+严格
重执行、跨会话秘密确定性、safety cap 失败语义、回放队伍胜/平局
往返与篡改失败关闭、队友可见性。

**固定种子**：20 种子（pytest 内，全严格重执行）+ 50 种子独立扫查
（seed 20–69）：全部自然结束（队伍全灭胜负，`team_eliminated`）、
unsupported=0、无安全上限触发、严格重执行逐决策验证一致、合法队伍胜者。

**实现身份**：当前实现 `implementation_identity()` =
`710c766dd2d5f910a87822f410e4c1c44f867773a0ec7a4fe314e99fa42029ec`
（C123 全局 remediation 1 后随源码更新；冻结 R8 证据 `06c8b2d3…`
仍是历史证据，未被改写）。

C123 正交 remediation 2 的被审计 implementation commit =
`677d81c131df1e02842919b47e7ab6c02c8c703b`。本文件随后的
status-closure commit 只记录复审结果，不得冒充该 implementation SHA。

HISTORICAL/AS-OF（实现提交当时）：
`IMPLEMENTED_PENDING_INDEPENDENT_REAUDIT`。

CURRENT：C123-R1-NEW-001 = `CLOSED`；独立复审结论
`REMEDIATION_2_REAUDIT_PASSED`。C1/C2/C3 整轨仍不是独立全量审计通过。

**C123 正交 remediation 1**（F-003～F-006；独立 re-audit 已确认
CLOSED。本轮不得重新打开）：

- F-003：`_response_order_from_turn_player` 在当前回合角色已死亡时，
  先用 `PlayerTopology.first_alive_after` 取得座次之后第一名存活角色，
  再交给 `alive_ring_from`。`alive_ring_from` / `next_alive` 的
  “锚点必须存活”失败关闭契约保持不变。
- F-004：传导恢复后若方天根仍打开，不调用 `_end_turn_after_current_death`。
  只在 `_complete_root_resolution` 的最终 `_return_to_play` 出口、且仅当
  方天多目标根已全部完成、回合所有者已确认死亡时结束回合。不改变决斗 /
  普通单目标杀 / 群体锦囊 / 闪电 / 普通 chain 的 root completion 出口。
- F-005：非终局传导子目标死亡不再走 `shandian_victory_cleanup`，也不
  提前 `pending_judgment=None`。chain 结束后回到正常闪电 root
  completion：JUDGMENT → DRAW → PLAY。
- F-006：`_pending_slash_value` 覆盖 `target_sequence` 与
  `current_target_index`；新增 `PENDING_SLASH_EXECUTION_FIELD_INVENTORY`。
- 衍生项 D-003-A / D-004-A / D-003-B 由根修复自然消除，未扩大
  step transaction 重构。
- 回归：`tests/test_post_b_c123_orthogonal_remediation_1.py`。

**C123 正交 remediation 2**（C123-R1-NEW-001
TURN_OWNER_DEATH_CHAIN_CONTINUATION_LOST；CURRENT 状态 `CLOSED`，
独立复审结论 `REMEDIATION_2_REAUDIT_PASSED`。HISTORICAL/AS-OF：
实现提交当时为 `IMPLEMENTED_PENDING_INDEPENDENT_REAUDIT`）：

- 独立区分“当前回合角色已确认死亡”与“立即结束当前回合”。
- `apply_pass_rescue` 在非终局确认当前回合角色死亡时记下
  `deferred_turn_end_after_owner_death`。
- 该责任不因后续 `dying_id` 换成另一名角色而丢失。
- 只在真正 root 完成后的 `_complete_root_resolution` 出口
  （以及群体锦囊全部目标完成出口）询问：游戏未终局、turn owner
  已死、无仍应优先完成的 parent/root 时，才
  `_end_turn_after_current_death`。
- 不把 `phase == PLAY and current player is dead` 当作全局兜底，
  因此不破坏 `test_duel_continues_after_source_death`。
- 不提前结束未完成的方天 `target_sequence`，不修改 F-005 闪电
  非终局子目标清理，不修改 OutcomePolicy。
- 回归：`tests/test_post_b_c123_orthogonal_remediation_2.py`。

**C123 rem2 独立复审证据**（provenance 分层，不得混写）：

- 被审计 implementation SHA：
  `677d81c131df1e02842919b47e7ab6c02c8c703b`
- Independent adversarial re-audit：PASSED
  （Gemini 3.1 Pro High；FINAL_VERDICT=`REMEDIATION_2_REAUDIT_PASSED`）
- Finding 状态：C123-R1-NEW-001=`CLOSED`；F-003=`CLOSED`；
  F-004=`CLOSED`；F-005=`CLOSED`；F-006=`CLOSED`
- Independent production probe：PASSED
  （仓库外路径
  `D:\MyGPT\pytest-temp-gemini\c123-rem2-reaudit\independent_probe.py`；
  exit code=0；关键终态：p1.alive=False、p2.alive=False、
  winner_id=None、phase=PREPARE、current_player_id=p3、
  pending_chain=None、pending_judgment=None、
  deferred_turn_end_after_owner_death=False、PROCESSING zone empty）
- Frozen implementation SHA full pytest：2508 passed in 1466.02s
  （用户本人在 detached 目标 SHA `677d81c…` 上手工执行
  `python -m pytest -q -p no:cacheprovider
  --basetemp=D:\MyGPT\pytest-temp-gemini\c123-rem2-full-manual`；
  运行后 `git status --short` 仍为空。不存在 full-test evidence gap。）
- 独立复审方明确更正：`FULL_TEST_RESULT = NOT_RUN`。
  不得声称 Gemini 自己完成了 full pytest。
- 未知规则未改：酒×方天仍为失败关闭（`BLOCKED_BY_RULE_SOURCE`）；
  `NESTED_INDEPENDENT_ATTRIBUTE_DAMAGE_DURING_CHAIN` 仍为
  `WAITING_FOR_VERIFICATION`。本轮不得借状态收口猜规则。

**C123 全局 remediation 1**（C123-GLOBAL-001
MULTITARGET_SLASH_ROOT_PREMATURE_FINISH_AFTER_RESCUED_CHAIN_TARGET；
CURRENT 状态 `CLOSED`，独立复审结论
`C123_GLOBAL_REMEDIATION_1_REAUDIT_PASSED`。HISTORICAL/AS-OF：
实现提交当时为 `IMPLEMENTED_PENDING_INDEPENDENT_REAUDIT`。
HISTORICAL 全局跨检查点敌对审计目标
`54201375cdb8b82b9af0947de49b0002c5bf4188` 结论为 FAILED /
BLOCKER FOUND，不得改写为当时误报或 `C123_GLOBAL_AUDIT_PASSED`）：

- 原缺陷：方天多目标【火杀】第一目标连环濒死被救后，错误提前 finish 根牌，
  导致实体牌离开 PROCESSING，外层方天根继续剩余目标时二次 finish
  失败关闭。
- 修复收敛至 `_finish_pending_damage_card` /
  `_finish_slash_processing` 统一父根所有权模型。
- 回归：`tests/test_post_b_c123_global_remediation_1.py`。
- 实现者本地全量 pytest 2521 passed 只是 implementation 自证，
  不是独立 closure 依据。

C123 全局 remediation 1 的被审计 implementation commit =
`7979eca3d27e8a74f29062e344b2fa05081aad66`。本文件随后的
status-closure commit 只记录复审结果，不得冒充该 implementation SHA。

HISTORICAL/AS-OF（实现提交当时）：
`IMPLEMENTED_PENDING_INDEPENDENT_REAUDIT`。

CURRENT：C123-GLOBAL-001 = `CLOSED`；独立复审结论
`C123_GLOBAL_REMEDIATION_1_REAUDIT_PASSED`。C1/C2/C3 整轨仍不是
独立全量审计通过。HISTORICAL 全局跨检查点敌对审计 = FAILED /
BLOCKER FOUND，与本轮 rem1 re-audit = PASSED 不得混写。

**C123 全局 rem1 独立复审证据**（provenance 分层，不得混写）：

- 被审计 implementation SHA：
  `7979eca3d27e8a74f29062e344b2fa05081aad66`
- Independent adversarial re-audit：PASSED
  （Grok 4.6 xhigh；FINAL_VERDICT=`C123_GLOBAL_REMEDIATION_1_REAUDIT_PASSED`）
- Finding 状态：C123-GLOBAL-001=`CLOSED`
- 历史 finding 无回归：F-003=`CLOSED`；F-004=`CLOSED`；
  F-005=`CLOSED`；F-006=`CLOSED`；C123-R1-NEW-001=`CLOSED`
  （编号与历史定义不变；本次 independent re-audit 再次确认无回归）
- Independent production probe：PASSED
  （仓库外路径
  `D:\MyGPT\pytest-temp-grok\c123-global-rem1-reaudit\probe_c123_global_001.py`；
  使用真实 `Formal2v2Session.step()` 重构造主 finding。
  关键中间态：p2 桃救回后 root Fire Slash=`PROCESSING`；
  chain 继续处理期间 root Fire Slash=`PROCESSING`；
  回到方天后续直接目标时 root Fire Slash=`PROCESSING`；
  全部 `target_sequence` 真正完成后 root Fire Slash=`DISCARD_PILE`；
  根牌实际 finish exactly once；桃救回该 step 根牌 DISCARD 事件次数=0；
  最终 PROCESSING 无 orphan。
  因此确认本轮不是依靠 `location != PROCESSING` → idempotent return
  把旧 crash 静默吞掉；父 root ownership 中间态真实成立。）
- Independent targeted pytest：实现专项 13 passed；历史正交
  remediation 20 passed；chain / weapon / Borrowed Sword / 2v2 draw /
  mode / replay / C2 等 310 passed。
- Independent full pytest：2521 passed in 1501.78s
  （独立审计在 detached 目标 SHA `7979eca3…` 上实际执行
  `python -m pytest -q -p no:cacheprovider
  --basetemp=D:\MyGPT\pytest-temp-grok\c123-global-rem1-reaudit\basetemp-full`；
  不是继承 implementation report。审计结束 HEAD 仍为
  `7979eca3d27e8a74f29062e344b2fa05081aad66`，detached，
  `git status --short` 为空。）
- C1/C2/C3 整轨仍不是独立全量审计通过。本轮只关闭
  C123-GLOBAL-001，不写成 `FULL_GLOBAL_AUDIT_COMPLETE`。
- 未知规则未改：酒×方天仍为失败关闭（`BLOCKED_BY_RULE_SOURCE`）；
  `NESTED_INDEPENDENT_ATTRIBUTE_DAMAGE_DURING_CHAIN` 仍为
  `WAITING_FOR_VERIFICATION`。本轮不得借状态收口猜规则。
- 非阻塞观察（本次状态收口不改代码）：
  1) `_finish_slash_processing` 中 physical card 不在 PROCESSING
     → empty idempotent return，在当前生产路径中存在合法重复到达
     （例如单目标属性杀已合法 exactly-once finish，后续 chain child
     产生 terminal victory，terminal cleanup 再次进入 finalizer）。
     独立审计未找到 parent still open + root card missing +
     idempotent branch 静默吞错误 的 production reachable defect。
     记录为 NONBLOCKING OBSERVATION。
  2) `assert_resolution_invariants` 尚未直接断言 pending physical
     Slash root open → entity card 必须仍在 PROCESSING。
     同属非阻塞架构观察，不是当前 blocker。

**C123 第二轮全局跨检查点独立敌对审计（Global Audit 2）**（C123_GLOBAL_AUDIT_2_PASSED；进入 AUDITED_SCOPE_READY_FOR_NEXT_DEVELOPMENT_STAGE）：

- 审计目标 SHA：`18c39c65bb67eb12fcce7e9d2954d2c3a908879c`
- Provenance：HEAD detached at `18c39c65bb67eb12fcce7e9d2954d2c3a908879c`；`checkpoint-post-b-c123-global-remediation-closed` 指向同一 commit。
- 最终有效结论：`C123_GLOBAL_AUDIT_2_PASSED`
- Provenance Correction：`PREVIOUS_REPORT_REQUIRED_PROVENANCE_CORRECTION = COMPLETED`。第一版审计报告曾出现 historical finding ID / definition 映射错误，随后在同一独立审计会话内执行 `POST_B_C123_GLOBAL_AUDIT_2_REPORT_CORRECTION_AND_EVIDENCE_REMAP` 完成 provenance correction 与证据重映射。纠错后的报告为 finding definition / evidence mapping 的权威依据（authoritative audit report），不得把第一版错误 mapping 写入状态。
- 历史 Finding 权威定义与状态锁定（全部 `CLOSED`，无回归）：
  1) `F-003`：dead current-player anchor 在后续 chain target DYING/rescue ordering 中不得直接传给 alive_ring_from。alive_ring_from 继续 fail-closed，caller 使用 first_alive_after(dead seat) 寻找合法 alive anchor。状态：`CLOSED`。
  2) `F-004`：Fangtian multi-target Slash 尚有 remaining target_sequence 时，child chain 导致 turn owner 非终局死亡，不得清 pending_slash 跳过剩余直接目标提前切回合。必须完成已锁定 direct target_sequence → root exactly-once finalize → 再结束 dead owner turn。状态：`CLOSED`。（Duel 属于独立交叉覆盖，不是 F-004。）
  3) `F-005`：Lightning original target survives，chain child 非终局死亡时，不得 shandian_victory_cleanup 或提前清 pending_judgment。之后仍必须 JUDGMENT → DRAW（真实摸2） → PLAY。状态：`CLOSED`。（Zhangba 虚拟杀属于独立交叉覆盖，不是 F-005。）
  4) `F-006`：`_PendingSlash` 的 `target_sequence` 与 `current_target_index` 属于 Class-A future-behavior state，必须进入 execution hash。状态：`CLOSED`。
  5) `C123-R1-NEW-001`：turn owner 在 chain 中先死亡，后续 child 再 dying / rescue / death，deferred turn-end responsibility 不得丢失。root 完成后必须下一存活角色 PREPARE，不能 zombie PLAY。状态：`CLOSED`。
  6) `C123-GLOBAL-001`：Fangtian multi-target elemental Slash 第一直接目标触发 chain + DYING/rescue/death 时，child resolution 不得提前 finish 仍被 parent 持有的实体 Slash root。parent 未结束前：root card = PROCESSING，全部 target_sequence 完成后：exactly-once finish。状态：`CLOSED`。
- 独立外部 adversarial probes：**8 / 8 PASSED**
  覆盖：
  - group-target trick
  - Duel
  - Lightning / delayed judgment
  - weapon / armor combinations
  - topology / atomicity / hash
  - C123-GLOBAL-001 regression
  - 2v2 death reward deck-exhaustion draw
  - deterministic replay / reexecution
- 专项 remediation regression：**56 passed in 52.56s**
- 完整独立 pytest：**2521 passed in 1957.95s (0:32:37)**
  （独立审计在 detached 目标 SHA `18c39c65…` 上实际执行
  `python -m pytest -q -p no:cacheprovider --basetemp=D:\MyGPT\pytest-temp-gemini\c123-global-audit-2\basetemp-full`；
  运行后 audit worktree 保持 clean，无仓库内 probe 污染）。
- 编译检查：`python -m compileall -q scripts tests`，Exit Code 0。
- Readiness 范围与边界（`AUDITED_SCOPE_READY_FOR_NEXT_DEVELOPMENT_STAGE`）：
  含义严格限定为：当前 18c39c65 checkpoint 上已实现的 Post-B C1/C2/C3 production scope 完成第二轮跨检查点整体独立敌对审计并通过，满足继续后续开发的质量门禁。
  不声明为 `PRODUCTION_RELEASE_READY` / `FULL_GAME_READY` / `ALL_CARD_RULES_COMPLETE` 或整个三国杀规则已完成独立审计。
- 规则排除项保持保留：
  - 酒 × 方天画戟 = `BLOCKED_BY_RULE_SOURCE` / `N-001`
  - `NESTED_INDEPENDENT_ATTRIBUTE_DAMAGE_DURING_CHAIN` = `WAITING_FOR_VERIFICATION`
- 全局审计历史事实完整保留：
  第一次跨检查点全局审计在 `54201375cdb8b82b9af0947de49b0002c5bf4188` 上的结论为 FAILED / BLOCKER FOUND（发现 C123-GLOBAL-001），随后经 7979eca3 remediation implementation → independent re-audit (CLOSED) → 18c39c65 status closure → 本轮 Global Audit 2 on 18c39c65 (C123_GLOBAL_AUDIT_2_PASSED)。历史审计事实未被改写。

**formal duel 防回归**：seed 0 → p2/388/43、seed 7 → p2/162/17
（与 R5/R8 记录一致；全量套件覆盖）。

**遗留**：斗地主（历史 C3 遗留；C4 阶段已完成，见 §10）/身份场（历史 C3 遗留；后续 C5 五人标准身份已完成，见 §11，C6 普通八人标准身份已完成，见 §12，C7 移动版八人主公立储 / 内奸择途特殊身份已完成，见 §13；限时八人及其它特殊身份变体仍未审计）/最后一人胜负策略（历史 C3 遗留；通用最后一人模式当前仍未审计）、武将技能、改判、AI、Web、
正式胜率阶段仍不在本轨；`multi_player_production_proven` 保持 false。

## 10. 当前轨：POST_B_C4_FORMAL_NO_SKILL_DOUDIZHU_MODE

**状态**：`AUDITED_PASSED`（实现与修复完成，独立终局复核与全量测试闭环全部通过 `C4_FINAL_CLOSURE_RECHECK_PASSED`；状态登记为 `AUDITED_SCOPE_READY_FOR_NEXT_DEVELOPMENT_STAGE`；由用户进行后续阶段推进）。

**范围**：正式、失败关闭、严格可回放的 formal no-skill 斗地主（Doudizhu）combat 模式层。复用 C1 多人基础（`PlayerTopology`）与 C2 全局卡牌语义（38/38 卡牌类型、160 张正式牌堆）。不新建独立引擎（无 `DoudizhuEngine`），基于 `ProductionBasicCardBatch` + `DoudizhuOutcomePolicy` + `DoudizhuModePolicy` + `FormalDoudizhuSession` + 模式层钩子与三方私密可见性实现。

**规则源**（Knowledge《三国杀模式规则》§3，全部 `当前确认`）：

- **Canonical 模式配置与拓扑**：
  - 3 人局拓扑：`p1` = 地主（landlord）、`p2` = 农民（peasant）、`p3` = 农民（peasant）。
  - 出牌顺序：`p1 → p2 → p3`（1 号位地主先手，确定性先手不消耗 RNG）。
  - 初始体力与上限：地主 5/5 HP，两名农民各 4/4 HP（模式权威初始化）。
  - 初始手牌：地主 4 张，农民各 4 张（无手气卡，`allow_reshuffle=False`）。
- **地主常驻模式技能**：
  - 【飞扬】：判定阶段可弃置 2 张手牌移动 1 张判定区牌（复用 2v2 飞扬通用实现与候选清理机制）。
  - 【跋扈】：准备阶段摸牌 +1 张（`PREPARE` 阶段摸 1 张牌）；出牌阶段普通【杀】使用次数上限 +1（`normal PLAY Slash limit +1`）。
- **农民非终局首死奖励（Peasant Death Reward）**：
  - 第一名农民非终局确认死亡时，存活的另一名农民获得奖励选择窗口（`PEASANT_REWARD_CHOICE`）：
    - 恢复 1 点体力（`recover 1`）；
    - 摸 2 张牌（`draw 2`，复用 `_mode_death_reward_draw` 事务）；
    - 放弃（`decline`）。
  - 仅首名农民死亡触发奖励；第二名农民死亡直接终局（地主获胜），不触发奖励窗口。
- **胜负判定与终局（`DoudizhuOutcomePolicy`）**：
  - 地主确认死亡 → 农民阵营获胜（`winner_id = "peasants"`，`finish_reason = "landlord_eliminated"`）。
  - 两名农民全部确认死亡 → 地主获胜（`winner_id = "p1"`，`finish_reason = "peasants_eliminated"`）。
  - 牌堆耗尽平局：摸牌、判定、展示、奖励等原子取牌步骤牌堆不足或完整取牌后牌堆为 0 → 立即正式平局（`winner_id = None`，`finish_reason = "doudizhu_draw_deck_exhausted"`，`no_reshuffle_draw` 模式）。
- **手牌隐私与可见性（Three-player Hand Privacy）**：
  - `p1`、`p2`、`p3` 互不查看其他角色的私有手牌。
  - 农民阵营两名角色即使属于同一队伍，也不共享队友手牌（visible 集合仅包含自身私有手牌与公开区域）。
- **严格回放与重执行（Strict Replay）**：
  - `SUPPORTED_REPLAY_MODES` 支持斗地主；`formal_doudizhu_configuration` + `analysis_only` + `max_steps` 为一等初始配置；胜负与平局均支持完整确定性重执行；配置篡改、非法观察者与伪造动作均严格失败关闭。

**明确不包含（EXPLICIT EXCLUSIONS）**：

- 叫地主 / 抢地主状态机（bidding / claim landlord flow）
- 手气卡 / 换牌系统（redraw / hand shuffling card）
- 选将 / 身份暗置与分配流程（identity selection / hidden identity flow）
- 武将技能系统（除模式固定技能飞扬、跋扈外，不含任何武将特有技能）
- 15分钟限时与积分裁定（15-minute score adjudication）
- AI 策略（AI strategy）
- Web / UI 界面
- 正式胜率阶段（win rate benchmark execution）
- 完整商业客户端流程与其它外围系统

**就绪与门禁边界（READINESS BOUNDARY）**：

- `multi_player_production_proven = false`
- `authoritative_full_game_core = false`
- 正式门禁 `inspect_formal_doudizhu_readiness()` 返回：`doudizhu_ready = formal_doudizhu_no_skill_ready`（canonical factory 可达 + 38/38 卡牌语义复用 + 严格回放支持）。
- `doudizhu_ready` 严格限定为当前 formal no-skill combat scope 静态执行资格，不得扩张为 `FULL_GAME_READY`、`PRODUCTION_RELEASE_READY`、`RELEASE_READY`、`ALL_CARD_RULES_COMPLETE` 或 `AUTHORITATIVE_FULL_GAME_READY`。

**规则源缺口原样保留（RULE GAPS UNCHANGED）**：

- 酒 × 方天画戟 = `BLOCKED_BY_RULE_SOURCE` / `N-001`
- `NESTED_INDEPENDENT_ATTRIBUTE_DAMAGE_DURING_CHAIN` = `WAITING_FOR_VERIFICATION`

**实现身份与 Commit Provenance 分层**：

- 被审计 implementation SHA：`4c2969fcc0d36da862b6a7f29d827e427c60f501`
- 当前实现身份（`implementation_identity()`）：`a06f0fb2ea614325c9f27bcc44d035cfbe8cc4dfbe5dc961ca343bd872fe3434`
- 提交分层：本轮 documentation closure commit 仅修改状态文档以登记审计结果，不得冒充被审计 implementation SHA。

**C4 完整审计与修复历史（AUDIT & REMEDIATION PROVENANCE）**：

1. **Initial C4 Implementation**：
   - Implementation Commit：`d90325938b8e7860b6824597e8f59c63b0fd9f9c`（`feat: implement formal no-skill doudizhu mode`）
   - 历史审计结论：`C4_INDEPENDENT_AUDIT_1_FAILED`
   - 缺陷：`C4-AUDIT-001`（HIGH）。非终局农民死亡清理计算了清洗后的 `judgment_entry_indices`，但在异步 `PEASANT_REWARD_CHOICE` 暂停前未写回 authoritative runtime，导致 stale/ghost judgment entry index。
   - 历史 FAILED 事实永久保留，不得反写为 PASSED。

2. **Remediation 1**：
   - Implementation Commit：`d7db68a2b989bc9b34bdca6ef04fa90ff23b1eb0`（`fix: preserve judgment indices across doudizhu death reward`）
   - 修复：在挂起农民奖励选择前将清洗后的 `judgment_entry_indices` 权威写回 runtime。
   - 独立 Re-audit：`C4-AUDIT-001 = CLOSED`，`C4_REMEDIATION_1_REAUDIT_PASSED`。
   - 随后的 C4 Global Audit 2 在同一 `d7db68a` 候选上发现新 HIGH 缺陷，因此 C4 Global Audit 2 历史结论不能记为 PASSED。

3. **C4 Global Audit 2**：
   - 审计目标 SHA：`d7db68a2b989bc9b34bdca6ef04fa90ff23b1eb0`
   - 历史审计结论：`C4_GLOBAL_AUDIT_2_FAILED`
   - 缺陷：`C4-GLOBAL2-001`（HIGH）。`FormalDoudizhuConfiguration` / `TrustedFormalDoudizhuConfiguration` 使用 Python 宽松 equality、`from_dict` coercion 以及 public Trusted capability minting，使得 `True == 1`、`False == 0`、`2 == 2.0` 等非 exact canonical representation 可能获得 formal authority 并进入 strict replay。
   - 历史 FAILED 事实永久保留。

4. **Remediation 2**：
   - Implementation Commit：`e28fa96917c94ab49e38fb52d7ab10cff8ff4c7a`（`fix: enforce strict doudizhu configuration authority`）
   - 修复：引入 recursive exact-type canonical comparison，去除危险 input coercion，capability minting 移至内部 canonical factory。
   - 独立 Re-audit：`C4-GLOBAL2-001 = CLOSED`，`C4_GLOBAL_REMEDIATION_2_REAUDIT_PASSED`，全量 pytest 2583 passed。

5. **Completion Audit**：
   - 审计目标 SHA：`e28fa96917c94ab49e38fb52d7ab10cff8ff4c7a`
   - 历史审计结论：`C4_COMPLETION_AUDIT_FAILED`
   - 发现两个 HIGH 缺陷：`C4-COMPLETION-001` 与 `C4-COMPLETION-002`。历史 FAILED 事实永久保留。
   - `C4-COMPLETION-001`（HIGH）：借刀强迫杀 → 连锁属性伤害 → 子目标农民非终局死亡 → 农民奖励窗口 → 恢复父级结算。死亡确认阶段提前执行 `jiedaosharen_victory_cleanup`，导致实体借刀牌移出 PROCESSING 区域，但 `pending_borrowed_sword` 仍标记未完成；奖励结算后父级根再次 finalize，触发 double-finalize / `ProductionBatchError`。
   - `C4-COMPLETION-002`（HIGH）：当前回合所有者农民被闪电击中 → DYING → 非终局死亡 → 农民奖励窗口。闪电在 DEATH/reward 前提前调用 `shandian_victory_cleanup`，但 `pending_judgment.cleanup_done=False` 仍指向已被 DISCARD 的实体判定牌，导致 parent ownership 与 physical zone 不一致。

6. **Remediation 3**：
   - Implementation Commit：`4c2969fcc0d36da862b6a7f29d827e427c60f501`（`fix: preserve parent roots across nonterminal death`）
   - 根因分析：`ROOT_CAUSE_RELATION = SHARED`（非终局角色死亡被错误当成 parent root terminal/victory boundary）。
   - 修复：仅在真正产生 terminal winner 时允许 parent victory cleanup；非终局死亡及奖励窗口期间严格保持 parent/root ownership；Borrowed Sword 与 Lightning 均实现 exactly-once completion。
   - 独立 Re-audit：`C4-COMPLETION-001 = CLOSED`，`C4-COMPLETION-002 = CLOSED`，`C4_REMEDIATION_3_REAUDIT_PASSED`，全量 pytest 2594 passed。

**最终收口复核证据（FINAL CLOSURE RECHECK EVIDENCE）**：

- **被审计目标**：`4c2969fcc0d36da862b6a7f29d827e427c60f501`（detached HEAD，clean）
- **最终技术结论**：`C4_FINAL_CLOSURE_RECHECK_PASSED`
- **审计范围状态**：`TECHNICAL_C4_AUDIT_SCOPE = READY_FOR_DOCUMENTATION_CLOSURE`
- **复核项详细结果**：
  - C4-COMPLETION-001 final smoke = `PASS`
  - C4-COMPLETION-002 final smoke = `PASS`
  - true terminal winner cleanup = `PASS`
  - deck-exhaustion terminal draw cleanup = `PASS`
  - parent/root zone consistency = `PASS`
  - event exactly-once = `PASS`
  - stale action fail-closed，event/hash unchanged = `PASS`
  - historical adjacent findings remain `CLOSED`
  - targeted tests = **396 passed in 178.46s**
  - pytest collection = **2594**
  - full pytest = **2594 passed in 1611.74s (0:26:51)**
  - failed = 0, errors = 0, skipped = 0
  - compileall = `Exit Code 0`
  - implementation identity = `a06f0fb2ea614325c9f27bcc44d035cfbe8cc4dfbe5dc961ca343bd872fe3434`（MATCH）
  - worktree clean，无新 HIGH/BLOCKER

**非阻塞技术观察（NON-BLOCKING OBSERVATIONS）**：

1. `assert_resolution_invariants` 当前并不普遍直接断言 “pending physical root open → root 必须在 PROCESSING”；当前修复路径由专项 tests / probes 证明。（NON_BLOCKING）
2. `pending_borrowed_sword.root_discarded` / `pending_judgment.cleanup_done` 当前生产完成通常通过清空 pending 结构，而非把布尔字段写 True。（NON_BLOCKING）
3. 2v2 `TrustedFormal2v2Configuration` 仍使用较早的 authority construction semantics；这是 C4 audit 观察到的既有 2v2 contract，不是 C4 引入 finding，本 closure 不扩大 scope 修复。（NON_BLOCKING）

## 11. 当前轨：POST_B_C5_FORMAL_NO_SKILL_FIVE_PLAYER_STANDARD_IDENTITY_MODE

**状态**：`AUDITED_PASSED`（implementation + remediation 已完成，独立 re-audit 通过
`C5_INDEPENDENT_AUDIT_PASSED`；当前 scope 达到
`AUDITED_SCOPE_READY_FOR_NEXT_DEVELOPMENT_STAGE`）。这是当前 C5 scope 的质量门禁，
不是整个游戏 ready；是否进入下一开发阶段由用户决定。

**范围**：正式五人标准军争身份模式、formal no-skill soldier profile，以及
canonical post-redraw combat initialization。复用 `ProductionBasicCardBatch`、
`PlayerTopology`、`OutcomePolicy`、C2 38/38 card semantics、160-card formal deck，
并复用既有 action / event / damage / DYING / rescue / death / phase、parent/root
continuation 与 strict replay；不建立第二套 identity engine。

**明确不包含（EXPLICIT EXCLUSIONS）**：

- 选将、武将技能、主公技能
- 手气卡 / reroll
- 身份选择动画及其它外围流程
- 普通八人身份、限时八人身份
- 双内奸、野心家、继位等特殊身份变体
- AI、Web / UI、积分 / 限时
- 正式胜率阶段
- 商业客户端外围流程

**Canonical 初始化（CANONICAL INITIALIZATION）**：

- physical player IDs = `("p1", "p2", "p3", "p4", "p5")`。
- identity composition = lord ×1、loyalist ×1、rebel ×2、spy ×1。
- 只 shuffle identities，不执行第二次 physical-seat randomization。
- 整个 session 使用单一 `DeterministicRNG`，消费顺序为 identity role shuffle
  → deck shuffle → later reshuffles。
- lord 的原物理位置不移动，该位置成为 seat1；`numbered_player_order` 从 lord
  的物理位置旋转，lord first。角色死亡后 seat 不重新编号。
- lord 初始 HP = 5/5，其他玩家 = 4/4；这是直接 pregame construction，
  不是 HP bonus event。
- 所有玩家 initial hand = 4；lord 没有 bonus card；无 redraw。

**身份与手牌隐私（IDENTITY & HAND PRIVACY）**：

- 每名玩家知道自己的身份、主公身份与 confirmed-dead 已公开身份；public
  仅公开主公及 confirmed-dead 已公开身份。
- living nonlord identity 保持 hidden；DYING、rescue window 与 rescue success
  均不得 reveal identity。
- 每名玩家的手牌仅自己可见；同阵营不共享手牌。
- player-visible 输出必须脱敏 seed / RNG / authoritative private state、hidden
  hashes、hidden identities 与其他玩家手牌。
- C5 独立 audit 未发现 legal actions、context、公开 hash 或 player-visible
  projection 可稳定泄露隐藏身份或他人手牌。

**胜负判定（`IdentityOutcomePolicy`）**：

- lord alive 且不存在 living rebel / spy → `lord_and_loyalists`。
- lord + spy only → ongoing。
- lord dead 且 sole other survivor 为 spy → `spy`。
- lord dead 的 every other case（包括 nobody alive）→ `rebels`。
- earlier-dead spy 不得在之后获胜。
- 每个 confirmed death 后立即执行 outcome check；正常终局
  `finish_reason = "identity_victory"`。

**死亡、身份后果与 observable event sequence**：

- confirmed death pipeline 的语义职责包括 nonlord identity reveal、death-zone
  cleanup、`DEATH`、outcome check，以及 identity consequences / continuation；
  此职责清单本身不定义 observable ordering。
- 历史合同文字曾同时描述逻辑处理顺序与 observable event sequence；当前已审计
  implementation 的 observable sequence 为：death-zone `CARD_MOVED` cleanup
  → `IDENTITY_REVEALED` → `DEATH` → identity consequence / continuation。
  不再把它写成 `IDENTITY_REVEALED` 必须先于 cleanup `CARD_MOVED`。
- outcome check 在 `DEATH` 后、任何 identity consequences / continuation 前
  立即完成。
- terminal identity victory 立即停止：跳过 identity reward / penalty，不 resume
  parent，remaining group / chain targets 不继续。
- ongoing 时，由 final production `kill_credit` / damage source 驱动身份奖惩：
  - 任何 killer 杀 rebel → draw 3。
  - lord 杀 loyalist → discard all HAND + EQUIPMENT，retain JUDGMENT。
  - nonlord 杀 loyalist → no identity penalty。
  - 无有效 source → no invented killer。
  - 不添加 killer-must-be-alive 限制。

**Parent / Root continuation**：

- C5 已独立复核 Borrowed Sword、Fangtian multi-target Slash、group-target Nanman、
  Lightning pending judgment、current-turn-owner death、elemental chain、rescue 与
  terminal group stop。
- nonterminal death 不是 terminal parent cleanup boundary。
- parent-owned root 保持 `PROCESSING`，直到真正 parent completion，并且 exactly
  once finalize。
- identity reward / penalty 必须发生在 parent continuation 前。
- terminal winner 出现后，future parent target 不再开始。
- 首次 audit 中的测试假覆盖问题由 `C5-AUD-002` 修复，并经独立 re-audit
  确认 `CLOSED`。

**Reshuffle draw**：

- C5 `deck_supply_mode = "reshuffle_draw"`，不同于 C3 / C4 的
  `no_reshuffle_draw`。
- draw empty 时只 reshuffle eligible DISCARD；HAND、EQUIPMENT、JUDGMENT、
  PROCESSING、REVEALED、special / out-of-game 等非 eligible 区域均不参与。
- 若某 operation 恰好取得最后所需牌后供给变为 0，不是 draw，也不产生
  draw-deck-exhausted；只有仍需要下一张、且 draw + eligible discard 均为空时，才产生
  `identity_draw_deck_exhausted`。
- 已发生的 partial movement / events / RNG 消费全部保留，不 rollback。
- production step path 覆盖 normal draw、Wuzhong、Tiesuo recast、ordinary
  judgment、Bagua、Wugu 与 rebel kill draw3。
- Cixiong 对应入口为 N/A：formal no-skill soldier `gender = NONE`。

**修正后的 draw replay contract**：

- `C5_CANONICAL_DRAW_REACHABILITY_UNRESOLVED`。
- `identity_draw_deck_exhausted` production semantics 是 C5 runtime contract，
  已通过真实 production step paths 测试。
- 对 canonical post-redraw initial state → natural
  `identity_draw_deck_exhausted`，当前既没有发现自然 legal-action trajectory，
  也没有形成覆盖全部 legal trajectories 的数学不可达证明。
- 因此不得记录为 N/A、`PROVEN_UNREACHABLE`、mathematically impossible 或
  `C5_DRAW_PROVEN_UNREACHABLE`。
- 本 C5 closure 不要求伪造 canonical authoritative draw replay；不得使用
  fixture、premutated state、`analysis_only=True`、伪造 outcome 或测试后门冒充
  formal authoritative draw。
- 未来若找到自然 canonical draw trajectory，再升级 mandatory authoritative
  strict replay coverage。

**Strict replay**：

- 三种 canonical victory 已 independently verified：
  - seed 0 → `lord_and_loyalists`
  - seed 1 → `rebels`
  - seed 4 → `spy`
- 三者均使用 canonical trusted profile，`analysis_only=False`、
  `fixture_applied=False`，经 `record_reference_formal_identity` 与
  `reexecute_production_replay` 验证，`verified=True`。
- strict replay 一等输入包括 formal identity config、physical players、identity
  assignment、numbered order、lord id、`analysis_only` 与 `max_steps`。
- 身份 / 配置 / 事件 / 动作 / hash / RNG / outcome tamper 全部 fail closed。
- `C5_CANONICAL_DRAW_REACHABILITY_UNRESOLVED` 不表示 strict replay 整体不完整；
  三种自然胜利 strict replay 已闭合。

**Readiness**：

`inspect_formal_identity_readiness()` 当前正常状态：

- `deck_count = 160`
- `registered_card_key_count = 38`
- `registered_instance_count = 160`
- `global_card_semantics_complete = true`
- `mode_runtime_reachable = true`
- `mode_implemented = true`
- `reexecution_replay_supported = true`
- `unsupported_rules = 0`
- `approximation_count = 0`
- `formal_identity_no_skill_ready = true`
- `identity_ready = true`
- `multi_player_production_proven = false`
- `authoritative_full_game_core = false`

首次 independent audit 的 `C5-AUD-001` 指出 readiness 原先只 probe
`analysis_only=True`。remediation 增加 `analysis_only=False` trusted canonical
session live probe 与 `formal_result_eligible` 检查；正式路径损坏时 readiness
fail closed。独立 re-audit Probe A–D 已确认 `C5-AUD-001 = CLOSED`。

`deterministic_controller_implemented=True`、`approximation_count=0` 中仍有
declarative 部分，但它们无法掩盖 formal trusted runtime blocker；此项作为
nonblocking observation 保留。

**C5 审计与修复历史（AUDIT & REMEDIATION PROVENANCE）**：

1. **Initial C5 Implementation**：
   - Implementation Commit：`ae298c312917b1b3d4965958c3f9322ea3583c84`
     （`Implement Post-B C5 formal five-player identity mode`）。
   - 第一次独立敌对审计：
     `C5_INDEPENDENT_AUDIT_FAILED_REMEDIATION_REQUIRED`。
   - `C5-AUD-001`（MEDIUM）：readiness probe 没有检测
     `analysis_only=False` trusted formal runtime，导致 readiness inflation。
   - `C5-AUD-002`（MEDIUM）：若干最高风险 parent/root tests 存在错误
     Borrowed Sword operation、silent return、Fangtian single-target fallback、
     terminal continuation 假覆盖、Lightning 条件退出与 `<=1` 弱断言。
   - 历史 FAILED 事实永久保留，不得把 initial audit 反写成 PASSED。

2. **Audit Remediation**：
   - Implementation Commit：`60dc98d0ebc3273087fc55dd44b45ac3f9a5b4b2`
     （`Remediate Post-B C5 independent audit findings`）。
   - `C5-AUD-001`：补齐 readiness trusted formal live path。
   - `C5-AUD-002`：改用真实 Borrowed Sword / Fangtian / terminal group stop /
     Lightning / lord-kills-loyalist group tests，去除 silent return、fallback 与
     `<=1` 假覆盖。

3. **Independent Re-Audit**：
   - target：`60dc98d0ebc3273087fc55dd44b45ac3f9a5b4b2`。
   - `C5-AUD-001 = CLOSED`。
   - `C5-AUD-002 = CLOSED`。
   - new confirmed CRITICAL/HIGH/MEDIUM correctness finding = `NONE`。
   - FINAL：`C5_INDEPENDENT_AUDIT_PASSED`。

**测试证据分层（TEST EVIDENCE — SOURCES NOT MIXED）**：

- Implementation / remediation-side evidence：
  - C5 collection = 72。
  - all C5 = **72 passed**。
  - adjacent regression = **57 passed**。
  - full pytest = **2667 passed**，failed = 0，errors = 0。
  - compileall = `PASS`。
- Independent re-audit evidence：
  - C5 + C1 closure = **78 passed**。
  - historical C123 / C4 high-risk = **44 passed**。
  - C3 2v2 + C4 Doudizhu smoke = **40 passed**。
  - independent probes：readiness A–D、Borrowed Sword、Fangtian、terminal Nanman、
    Lightning、lord kills loyalist，以及 three outcome strict replay。
- 独立 re-audit 没有重新运行完整 2667 full suite；不得把 implementation-side
  full pytest 写成 “independent audit full pytest = 2667 passed”。

**Implementation identity / provenance 分层**：

- 最终被审计 implementation SHA：
  `60dc98d0ebc3273087fc55dd44b45ac3f9a5b4b2`。
- 当前 implementation identity：
  `bcb33198b8e3c5551ce53353d0707c579c7febc6e30cd95c20b00b681235bbad`。
- identity chunks：`bcb33198` / `b8e3c555` / `1ce53353` / `d0707c57` /
  `9c7febc6` / `e30cd95c` / `20b00b68` / `1235bbad`。
- `FROZEN_R8_IMPLEMENTATION_IDENTITY` 继续保持
  `06c8b2d3ead9adb52a18252e398eae137eb8fb51f657909051500893672b0e33`，
  不改写。
- documentation closure commit 本轮尚未创建；后续 docs-only closure SHA
  不是被审计 implementation SHA，不得混写。

**规则源缺口原样保留（RULE GAPS UNCHANGED）**：

- 酒 × 方天画戟 = `BLOCKED_BY_RULE_SOURCE` / `N-001`
- `NESTED_INDEPENDENT_ATTRIBUTE_DAMAGE_DURING_CHAIN` =
  `WAITING_FOR_VERIFICATION`

**就绪边界与下一阶段（READINESS BOUNDARY & NEXT STAGE）**：

- C5 `AUDITED_PASSED` 只表示
  `POST_B_C5_FORMAL_NO_SKILL_FIVE_PLAYER_STANDARD_IDENTITY_MODE` 当前定义 scope
  已完成 implementation + independent audit，可以进入下一开发阶段。
- 它不得扩张为 `FULL_GAME_READY`、`PRODUCTION_RELEASE_READY`、`RELEASE_READY`、
  `AUTHORITATIVE_FULL_GAME_READY` 或 `ALL_CARD_RULES_COMPLETE`；
  `multi_player_production_proven=false`、`authoritative_full_game_core=false`
  继续保持。
- 既有 Post-B roadmap 为 generic cards → duel → 2v2 → Doudizhu →
  5-player identity → normal 8-player → timed 8-player。C5 closure 当时的下一模式
  候选为普通八人 formal identity；该候选现已由 C6 完成。随后移动版八人
  主公立储 / 内奸择途 special identity variant 已由 C7 完成。CURRENT 仍未启动的
  候选包括 timed 8-player 与其它 special 8-player identity variants；是否开始
  由用户决定。

## 12. 当前轨：POST_B_C6_FORMAL_NO_SKILL_NORMAL_EIGHT_PLAYER_IDENTITY_MODE

**状态**：`AUDITED_PASSED`（implementation 已完成，independent adversarial audit
通过 `C6_INDEPENDENT_AUDIT_PASSED`；confirmed CRITICAL / HIGH / MEDIUM finding =
`NONE`；当前定义 scope 达到
`AUDITED_SCOPE_READY_FOR_NEXT_DEVELOPMENT_STAGE`）。这是 C6 当前冻结 scope 的质量门禁，
不是整个游戏 ready；是否进入下一开发阶段由用户决定。

**冻结合同与范围（FROZEN CONTRACT & SCOPE）**：

- Contract：
  `POST_B_C6_FORMAL_NO_SKILL_NORMAL_EIGHT_PLAYER_IDENTITY_MODE`。
- 范围是标准、非特殊、普通八人军争身份模式，formal no-skill soldier profile，
  以及 canonical post-redraw combat initialization。
- canonical physical player IDs =
  `("p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8")`。
- identity composition = lord ×1、loyalist ×2、rebel ×4、spy ×1。

**明确不包含（EXPLICIT EXCLUSIONS）**：

- 双内奸、主公立储、储君、继位、内奸择途、转忠、野心家
- 限时八人及其它特殊八人玩法
- 选将、武将技能、主公技
- 手气卡 / redraw
- 服务器奖励统计、正式胜率
- AI、Web / UI

**架构（ARCHITECTURE）**：

- C6 没有建立第二套 identity engine。C5 / C6 共用 standard identity internal
  core、`ProductionBasicCardBatch`、`IdentityOutcomePolicy` semantics、
  `IdentityModePolicy`、death hook、parent / root、privacy projection、
  `reshuffle_draw` 与 strict replay infrastructure。
- C5 exact façade 保持为 `FormalIdentityConfiguration`、
  `TrustedFormalIdentityConfiguration`、`FormalIdentitySession`。
- C6 使用独立 façade：`FormalEightPlayerIdentityConfiguration`、
  `TrustedFormalEightPlayerIdentityConfiguration`、
  `FormalEightPlayerIdentitySession`。
- C5 没有被放宽成任意人数配置；5p 与 8p 正式入口继续使用各自 exact profile。

**Canonical 初始化（CANONICAL INITIALIZATION）**：

- physical IDs 固定为 `p1..p8`；只执行 identity-role shuffle，不再二次随机物理位置。
- 整个 session 使用单一 `DeterministicRNG`，消费顺序为 identity-role shuffle
  → formal deck shuffle → later reshuffles。
- 主公原 physical position 不移动；从该位置旋转形成 `seat1..seat8`，主公为
  seat1。死亡玩家退出 alive ring，但原 seat number 保留，其他玩家不重新编号。
- 主公开启第一个正常回合。
- lord 初始 HP / max HP = 5/5，其他玩家 = 4/4。lord +1 HP / max HP 是直接
  pregame construction，不是 recover、damage 或 max-HP event。
- 每人 initial hand = 4，总计 32 张；160 张牌初始发牌后 draw pile = 128。
  lord 没有 bonus card；无 redraw。

**Formal deck 与 reshuffle draw**：

- 复用 `sgs_mobile_non_special_20260725_unofficial`：160 张 physical cards、
  38/38 semantics。
- `deck_supply_mode = "reshuffle_draw"`。
- 只允许 eligible DISCARD 参与 reshuffle；HAND、EQUIPMENT、JUDGMENT、
  PROCESSING、REVEALED、special / out-of-game 及其它 non-eligible zone 均排除。
- partial acquisition 不 rollback：已取得的牌与相应 movement / event / RNG 消费
  保留；只有继续请求下一张且供给不足时才进入 exhaustion。

**身份与手牌隐私（IDENTITY & HAND PRIVACY）**：

- 主公开局公开；每名玩家知道自己的 identity 与自己的 hand。
- living nonlord 对本人以外的观察者保持 hidden；confirmed-dead nonlord 只在死亡
  确认后公开。DYING、waiting rescue 与 rescue success 均不得 reveal identity。
- 其他玩家手牌不可见。
- player-visible 输出不得暴露 seed、RNG state、full identities map、others'
  hands、authoritative private state、private / capability hashes。
- 独立审计检查了 header、context、legal actions、chosen actions、events 与
  derived state / hash，未发现 confirmed privacy finding。

**胜负判定（OUTCOME）**：

- winner tokens：`lord_and_loyalists`、`rebels`、`spy`；正常 finish reason =
  `identity_victory`。
- lord alive 且不存在 living rebel / spy → `lord_and_loyalists`。
- lord + spy only → ongoing。
- lord dead 且唯一其他 living player 为 spy → `spy`。
- lord dead 的其它所有情况（包括 nobody alive）→ `rebels`。
- 已先死亡的 spy 不能在后续获胜。
- 每次 confirmed death 后立即执行 outcome check，不 batch deaths。

**死亡与击杀后果（DEATH / KILL CONSEQUENCES）**：

- terminal death 立即结束；本次跳过 kill-rebel draw3 与
  lord-kills-loyalist penalty，也不再继续 future group target、future chain、
  parent continuation 或 future turn。
- game ongoing 时，任何有效 killer 杀 rebel → exactly draw 3；killer 可以是任何
  标准身份，不要求 killer 当前仍存活。
- lord 杀 loyalist → discard all HAND + all EQUIPMENT，retain JUDGMENT。
- nonlord 杀 loyalist → 无该身份惩罚。
- 如果没有 final `kill_credit` / source，不得猜测 killer。

**Parent / Root continuation**：

- 独立审计实际验证 Borrowed Sword、Fangtian real multi-target、group-target
  Nanman、elemental chain、Lightning、current-turn-owner death、rescue 与
  terminal future-target stop。
- nonterminal death 不是 root cleanup boundary。
- parent-owned physical root 保持 `PROCESSING`，直到真正 parent completion，
  并且 exactly once finalize。
- identity reward / penalty 必须在 parent continuation 前完成。
- terminal 后 future targets 不再开始。

**Draw reachability contract**：

- 当前正式合同为 `C6_CANONICAL_DRAW_REACHABILITY_UNRESOLVED`。
- `identity_draw_deck_exhausted` production semantics 已实现，并通过真实 `step()`
  路径验证。
- 当前没有找到 canonical initial state → natural draw terminal 的 legal
  trajectory，同时也没有覆盖全部 legal trajectories 的不可达证明。
- 因此不得登记为 N/A、`PROVEN_UNREACHABLE`、mathematically impossible 或
  `C6_DRAW_PROVEN_UNREACHABLE`。
- 当前没有 forged authoritative draw replay；不得用 fixture、premutated state、
  analysis-only 或其它伪造权威输入冒充 canonical natural draw。
- future 若找到 natural canonical trajectory，authoritative replay obligation
  重新成立。

**Three natural strict replays**：

- 独立审计确认三种 canonical victory：
  - seed 16 → `lord_and_loyalists`
  - seed 7 → `rebels`
  - seed 49 → `spy`
- 三者均使用 canonical trusted C6 config、`analysis_only=False`、
  `fixture_applied=False`、no premutated state、real legal actions，且
  `formal_result=True`、strict reexecute、`verified=True`。
- decision counts 为 seed 16 = 637、seed 7 = 409、seed 49 = 970；这些数值只是
  针对被审计 implementation 的复核证据，不是 formal contract。

**Authority 与 cross-mode isolation**：

- C6 exact-authority adversarial attacks 全部 fail closed，覆盖 bool / int alias、
  float / int、list / tuple、enum / string、dict subclass、configuration subclass、
  trusted subclass、extra / missing / null、wrong schema、wrong physical IDs、
  wrong role cardinality、wrong lord / order / seat，以及 copy / deepcopy /
  replace / pickle-like reconstruction。
- C5 / C6 cross-mode misuse fail closed；5p schema / 8p schema 不混用，5p / 8p
  player list 不会自动 pad、truncate、auto-detect 或 canonicalize。C5 contract 无回归。
- 独立审计另观察到：若攻击者已经取得真实 private capability token 并复制全部
  canonical fields，可重建等价 trusted object；non-canonical 值仍被 invariant
  拒绝。该观察为 INFO，不是 confirmed authority finding，也不登记为已修复漏洞或
  security finding。

**Readiness**：

`inspect_formal_eight_player_identity_readiness()` 正常值：

- `deck_count = 160`
- `registered_card_key_count = 38`
- `registered_instance_count = 160`
- `global_card_semantics_complete = true`
- `mode_runtime_reachable = true`
- `formal_trusted_runtime_reachable = true`
- `reexecution_replay_supported = true`
- `unsupported_rules = 0`
- `approximation_count = 0`
- `formal_eight_player_identity_no_skill_ready = true`
- `identity_8p_ready = true`
- `multi_player_production_proven = false`
- `authoritative_full_game_core = false`

独立 readiness A–D probes 已确认：

- A：trusted factory / session path 损坏 → ready false。
- B：analysis runtime 可执行、trusted formal runtime 失败 → ready false。
- C：`formal_result_eligible=False` → ready false。
- D：canonical 正常 → ready true。

因此没有 C5 `C5-AUD-001` 式 readiness inflation 回归。

**Special 8p isolation**：

- 独立审计确认标准 C6 production 未加载 `heir_player_id`、`current_lord`
  replacement、`ambitionist_mark`、spy choice、converted loyalist、heir
  succession 或野心家技能 / 奖励。
- 测试出现的 `heir_player_id` 仅用于 extra-field tamper rejection，不表示
  production 已支持特殊八人。

**C5 regression**：

- C6 shared-core 改造后，C5 全部 72 tests 独立通过。
- C5 canonical 保持 `p1..p5`、role composition 1/1/2/1、initial hands total
  20、remaining draw 140，以及 5p mode / schema、authority / privacy / outcome /
  reward / readiness。
- C5 three natural strict replay 保持 seed 0 → `lord_and_loyalists`、seed 1 →
  `rebels`、seed 4 → `spy`，全部 `verified=True`。
- C5 draw contract `C5_CANONICAL_DRAW_REACHABILITY_UNRESOLVED` 保持不变。

**C6 implementation / audit provenance**：

1. **Initial implementation**：
   - implementation commit = `259744b6d0cb5aa60313af19f18ebcd9ea3e8675`
     （`Implement Post-B C6 formal normal eight-player identity mode`）。
2. **Independent audit**：
   - audit target = `259744b6d0cb5aa60313af19f18ebcd9ea3e8675`。
   - confirmed CRITICAL / HIGH / MEDIUM findings = `NONE`。
   - FINAL = `C6_INDEPENDENT_AUDIT_PASSED`。
3. **Closure history boundary**：
   - C6 没有 remediation commit，也没有 remediation / re-audit 阶段；不得虚构
     finding ID 或额外 recheck 状态。
   - documentation closure commit 本轮尚未创建；未来 docs-only closure SHA
     只登记状态，不是被审计 implementation SHA。

**测试证据分层（TEST EVIDENCE — SOURCES NOT MIXED）**：

- Implementation-side evidence：
  - C6 collection = 80。
  - C6 = **80 passed in 358.15s**。
  - C5 + C6 = **152 passed in 1256.08s**。
  - adjacent C3 / C4 = **140 passed in 671.48s**。
  - historical parent / root = **81 passed in 12.92s**。
  - full pytest = **2747 passed in 3121.81s**，failed = 0，errors = 0。
  - compileall = `PASS`。
  - 第一次 full-suite 尝试因仓库外 basetemp 权限产生 setup error；权限处理后
    从头重新完整执行并取得 2747 passed。该次 setup error 是 environment / setup
    问题，不是 test failure。
- Independent-audit evidence：
  - C6 collection = 80。
  - C6 = **80 passed in 556.00s**。
  - C5 collection = 72。
  - C5 + C6 = **152 passed in 1923.93s**。
  - C123 + C4 targeted = **61 passed in 10.23s**。
  - C1 identity closure = **6 passed in 40.99s**。
  - parent / root 高风险总验证 = **81 tests / paths evidence**。
  - independent full pytest = **2747 passed**，failed = 0，errors = 0，
    **3762.48s (1:02:42)**。
  - independent full suite 是一次成功完整执行，不是失败后局部拼接。
  - compileall = `PASS`。

以上 implementation-side 与 independent-audit full-suite evidence 分别登记，
不得互相冒充来源。

**独立审计结果（INDEPENDENT AUDIT RESULT）**：

- audit target：`259744b6d0cb5aa60313af19f18ebcd9ea3e8675`。
- `CONFIRMED_FINDINGS = NONE`。
- confirmed CRITICAL = 0；confirmed HIGH = 0；confirmed MEDIUM = 0。
- FINAL：`C6_INDEPENDENT_AUDIT_PASSED`。

**非阻塞技术观察（NON-BLOCKING OBSERVATIONS）**：

1. closure 前本文件 CURRENT 状态仍写普通八人未启动；本轮只修正该状态滞后。
2. `scripts/sgs_engine/__init__.py` 长 docstring 仍偏 C5 五人措辞；行为 / API 已
   支持 C6，不是 correctness blocker。
3. `production_replay.py` 注释仍有“仅三种正式模式”的陈旧措辞；实际 allowlist
   已包含 C5 / C6，不是运行时错误。
4. C6 visibility tests 未复制 C5 的专门 DYING 用例；独立 probe 已命中 production
   path 并确认不 reveal。
5. C6 repository 初始化单测 seed 较少；独立审计已额外检查 seeds 0–31。
6. `IdentityOutcomePolicy` internal core 接受 5 或 8；正式 C5 / C6 session 入口
   仍为 exact profile。
7. C6 runtime integrity overlay 比 C5 更强；这不是 C5 regression。
8. `record_reference_formal_eight_player_identity` 默认 `analysis_only=True`；正式
   tests 显式使用 `False`，默认值偏保守。
9. 已掌握 private capability token 时可复制 canonical trusted object；
   non-canonical 值仍 fail closed。该项保持 INFO。
10. `DEATH` event 展示 `damage_source`，实际 identity consequence 使用
    `DeathConfirmationContext.kill_credit`；这是既有共享管线差异。独立 Borrowed
    Sword / rebel-kill probe 结果正确，不是 C6 finding。

**Implementation identity / provenance 分层**：

- 被审计 implementation SHA：
  `259744b6d0cb5aa60313af19f18ebcd9ea3e8675`。
- C6 audited implementation identity：
  `b6a312c06ea176ea5f66ad4c1dd4131b74ff56ca14dbc114ceceec25ed9a87f3`；
  该 C6 implementation identity 随当前 Post-B runtime 更新。
- `FROZEN_R8_IMPLEMENTATION_IDENTITY` 保持
  `06c8b2d3ead9adb52a18252e398eae137eb8fb51f657909051500893672b0e33`，
  不改写。
- documentation closure commit 本轮尚未创建；未来 documentation closure commit
  不会成为 audited implementation SHA。

**规则源缺口原样保留（RULE GAPS UNCHANGED）**：

- 酒 × 方天画戟 = `BLOCKED_BY_RULE_SOURCE` / `N-001`
- `NESTED_INDEPENDENT_ATTRIBUTE_DAMAGE_DURING_CHAIN` =
  `WAITING_FOR_VERIFICATION`

**就绪边界与下一阶段（READINESS BOUNDARY & NEXT STAGE）**：

- C6 `AUDITED_PASSED` 只表示
  `POST_B_C6_FORMAL_NO_SKILL_NORMAL_EIGHT_PLAYER_IDENTITY_MODE` 当前冻结 scope
  已完成 implementation + independent audit。
- 不得扩张为 `FULL_GAME_READY`、`PRODUCTION_RELEASE_READY`、`RELEASE_READY`、
  `AUTHORITATIVE_FULL_GAME_READY` 或 `ALL_CARD_RULES_COMPLETE`；
  `multi_player_production_proven=false`、`authoritative_full_game_core=false`
  继续保持。
- 既定 roadmap 为 generic cards → duel → 2v2 → Doudizhu → 5-player identity
  → normal 8-player → timed 8-player。C6 closure 后候选中的移动版八人主公立储 /
  内奸择途 special identity variant 已由 C7 完成；CURRENT 仍未启动的候选包括
  timed 8-player 与其它 special 8-player identity variants，是否开始由用户决定。

## 13. 当前轨：POST_B_C7_FORMAL_NO_SKILL_MOBILE_EIGHT_PLAYER_HEIR_AND_SPY_CHOICE_IDENTITY_MODE

**状态**：`AUDITED_PASSED`。C7 frozen formal no-skill scope final independent
closure sweep = `PASSED`；新增 confirmed defect = **0**；C7 frozen-scope
confirmed defects = `NONE OPEN`。这是当前冻结 scope 的质量门禁，不是整个游戏或
release ready；是否进入下一开发阶段由用户决定。

**冻结合同与关闭范围（FROZEN CONTRACT & CLOSURE SCOPE）**：

- Contract：
  `POST_B_C7_FORMAL_NO_SKILL_MOBILE_EIGHT_PLAYER_HEIR_AND_SPY_CHOICE_IDENTITY_MODE`。
- 范围是基于 C6 普通八人身份 core 的移动版特殊八人 formal no-skill profile，
  覆盖主公立储、储君继位、内奸择途、实际 spy → ambitionist 转换及相应胜负语义。
- final closure sweep 只关闭 C7 frozen formal no-skill scope；本轮没有重审完整
  三国杀引擎、全部模式、武将技能、AI、Web / UI 或 release packaging。

**Implementation / remediation / audit provenance**：

1. **Initial implementation**：
   - implementation commit = `a1749459da63aa62b3a38c2026ab0ab581972912`
     （`Implement Post-B C7 formal special eight-player identity mode`）。
2. **Remediation baseline**：
   - parent remediation baseline = `532d678d66342b620d6ed8e464df9fb601190a4d`
     （`Fix C7 asynchronous heir and spy decision checkpoints`）。
3. **Audited implementation**：
   - audit target / final implementation HEAD =
     `75f91dde8da61265645a00a8ebc153591e66ef8d`
     （`Fix C7 nested lord death after heir loss`）。
   - audited implementation identity =
     `5b4a300fda38749b42a1754f5ec9e7814e6a5edabdaa804ab1509f83276df9d4`。
4. **Closed defect / remediation records**：
   - `A1-CONFIRMED-001` = `CLOSED`。
   - `A2-CONFIRMED-001` = `CLOSED`。
   - `A2-REMEDIATION-001` = `CLOSED`。
   - final sweep 新增 confirmed defect = 0；C7 confirmed defects = `NONE OPEN`。
5. **Documentation closure boundary**：
   - 本次 docs-only closure commit 只登记状态，不是被审计 implementation SHA，
     也不改写以上 implementation / remediation / audit provenance。

**Final independent closure sweep evidence**：

以下是已完成的 independent sweep 现场证据；本次 docs-only closure 只登记结果，
不冒充新一轮 implementation、remediation 或 audit：

- C7 专项 = **61 passed in 825.35s**。
- C5 / C6 定向回归 = **152 passed in 1344.43s**。
- implementation identity gate = **1 passed**。
- final gate 合计 = **214 passed**，failed = 0。
- compileall = `exit 0`。
- final sweep 结束时 worktree、index、unmerged 均干净；`git diff --check`、
  cached diff check 与 EOL gate 通过。
- 本轮 final sweep 未重跑完整 **2815** 项全套测试；不得把 214 项 closure gate
  表述成 full-suite evidence。

**Readiness 与 strict canonical replay gate**：

- `formal_heir_and_spy_choice_identity_no_skill_ready = true`。
- `identity_8p_heir_ready = true`。
- `unsupported_rules = 0`；`approximation_count = 0`；`blockers = ()`。
- strict canonical evidence 使用 `fixture_applied=false`、`analysis_only=false`、
  `formal_result=true`，覆盖成功继位、真实 spy → ambitionist 转换与
  ambitionist victory。
- strict reexecute = `verified=true`。

**非阻塞观察（OPEN / NON-BLOCKING OBSERVATIONS）**：

1. `C7_CANONICAL_DRAW_REACHABILITY_UNRESOLVED` 保持 `OPEN`。它是测试强制保留的
   observation，不是 C7 frozen-scope closure blocker；不得升级为 canonical natural
   deck exhaustion 已证明、不可达已证明或已有 canonical strict draw replay。
2. `A1-OBS-001` 保持 `OPEN`：latent kill-credit model observation。当前没有建立
   production-reachable divergent gameplay defect；该观察不是已解决 finding。
3. `mode_identity_heir.py` readiness 对
   `C6_CANONICAL_DRAW_REACHABILITY_STATUS ==
   "C6_CANONICAL_DRAW_REACHABILITY_UNRESOLVED"` 的精确相等耦合保持 `OPEN` /
   non-blocking。当前行为正确；如果未来 C6 status 改变，该耦合可能脆弱。本轮没有
   为此修改代码，也不把它登记为已解决。

**Draw reachability 边界**：

- `identity_draw_deck_exhausted` 仍是允许的 production formal outcome；“允许”不等于
  已实际覆盖 canonical natural exhaustion。
- 当前没有 canonical initial state → natural `identity_draw_deck_exhausted` 的
  strict replay，也没有覆盖全部 legal trajectories 的不可达证明。
- 有限 search / sweep 不能据此宣称不可达；不得登记为 N/A、
  `PROVEN_UNREACHABLE` 或 mathematically impossible。

**就绪边界与下一阶段（READINESS BOUNDARY & NEXT STAGE）**：

- C7 `AUDITED_PASSED` 只表示上述 frozen formal no-skill scope 已完成 implementation、
  remediation 与 independent final closure sweep，且 confirmed defects = `NONE OPEN`。
- 三项 observation 继续保持 OPEN / non-blocking；C7 closure 不将其改写为 resolved。
- `multi_player_production_proven=false`、`authoritative_full_game_core=false` 继续保持。
- 不得扩张为 `FULL_GAME_READY`、`PRODUCTION_RELEASE_READY`、`RELEASE_READY`、
  `AUTHORITATIVE_FULL_GAME_READY`、`ALL_CARD_RULES_COMPLETE` 或完整游戏无缺陷证明。
- 下一阶段是否为 timed 8-player、其它 special identity variant 或其它工作，由用户决定。

## NEXT_STAGE_C7_ACTIVE_MODE_DECISION_FULL_GAME_ACCEPTANCE_V1

状态：`IMPLEMENTED / AUDITED`

本批在不修改 C7 规则语义与旧 full-game/replay 合同的前提下，新增独立的
C7 主动模式决策完整整局动态验收。冻结场景矩阵恰好三行：

- `HEIR_SUCCESSION`：seed `1`，实际选择 `select_heir(p3)`；
- `SPY_TO_LOYALIST`：seed `1`，实际选择 `choose_spy_path(path="loyalist")`；
- `SPY_TO_AMBITIONIST`：seed `2`，实际选择 `choose_spy_path(path="ambitionist")`。

控制器身份为
`c7-active-mode-decision-acceptance-controller-v1` / version `1`，场景配置
schema 为 `sgs-c7-active-mode-decision-scenario-v1`。控制器输入仅限当前签发
的 `legal_actions`、公开的 mode/phase/actor/turn-player/response-window/revision
投影及冻结场景配置；不读取 session、state、私有手牌、RNG、deck、身份映射
或 `ActionContext.metadata`。场景配置与控制器中不存在 frozen-seed 私密身份
actor、protected-player 或 pre/post-transition target table；主公、实际择途者与
保护对象只能从此前公开签发的合法动作窗口学习，战斗目标只从当前公开合法
动作确定。

独立 replay schema 为
`sgs-c7-active-mode-decision-full-game-replay-v1`。它绑定场景、seed、控制器与
配置 hash、implementation/ruleset/mode-profile/deck identity 及 production
replay-v1 hash；production replay hash 与 outer replay hash 都是包含随机
session authentication material 的 per-record hash，不是同 seed 的 canonical
deterministic hash。反序列化时先核 schema/hash/identity，再 strict reexecute
production replay-v1，并以全新控制器沿 live legal actions 重算动作与动态
proof。serialized proof 与 derived gate 均不是可信真相源。

全部 exact schema、contract/mode/scenario/seed/controller/configuration、内外层
hash 与 implementation/ruleset/mode-profile/deck identity preflight 均在任何
C7 session 构造之前完成；current ruleset identity 由静态正式注册 profile
派生。active proof 绑定 chosen action 的 actor/revision/state hash、live state
revision、response-window/pending-window、对应 decision event slice、真实
event type/target/card-user/payload、角色/继位 transition 与 downstream 状态/
终局。忠臣转化公告没有 `target_ids`，因此不写入 verifier 自填 target；actor
由真实 chooser、pending/locked、role transition 与自然回合推进共同绑定。
野心家标记必须存在 conversion 后的非空真实 mark-use event indices，不接受
自填布尔值替代。

独立 matrix schema 为
`sgs-c7-active-mode-decision-full-game-matrix-v1`。唯一新增 derived gate 是
`c7_active_mode_decision_full_game_v1_proven`；它只表示上述三行主动决策整局
轨迹均经严格重执行与场景 proof 重新派生通过。

本状态登记不提升或改写：

- `authoritative_no_skill_full_game_v1_ready`；
- `FULL_GAME_READY`；
- `RELEASE_READY`；
- `ALL_CARD_RULES_COMPLETE`；
- 原 Stage3 126-cell contract、runner、tests 或 artifacts；
- C5/C6/C7 正式模式构造器或 C8/manifest/tag 状态。

本轮 production remediation 后的 current implementation identity 为
`d059061e0345e5ed89e86600a7dcd8bd68b49af1db9030259cc72656c94a5355`。
第一次与第二次独立 closure audit 的历史结论均为 `FAILED`，不得改写。
第三次独立 closure audit 结论为
`C7_ACTIVE_MODE_DECISION_FULL_GAME_V1_THIRD_CLOSURE_AUDIT` = `PASSED`，
因此本节登记 `IMPLEMENTED / AUDITED`。本节仍不登记 `COMPLETE`、
`FULL_GAME_READY`、`RELEASE_READY` 或 C8。

第二次审计前记录的第一次 full pytest 与第二次本机 full pytest（旧
`2877 passed` 记录）只属于当时的 implementation identity
`801d60edbc2d1508b33ee34442fa8159d2a4885785ad0e254180bc1c57461236`。
那些旧结果不得作为当前 identity 的最终 full-suite gate。

当前 identity 的最终 full pytest 已经完成并 PASS：
`2887 passed in 5887.85s (1:38:07)`；`0 failed`；`0 errors`；
exit code = `0`。Python 为
`D:\MyGPT\game-analysis-grok-eval\.venv\Scripts\python.exe`；
basetemp 为
`D:\MyGPT\basetemp\c7-active-mode-decision-final-full-20260827T185415`。

当前 identity 在最终 full pytest 之前的定向证据（不是 full pytest）：
新 acceptance/adversarial tests 为 `32 passed in 599.13s`；identity
closure 为 `6 passed in 33.31s`；authoritative V1 与必要旧 C7
regressions 为 `73 passed in 1240.55s`；compileall 与
`git diff --check` 均为 exit `0`。

第三次独立 closure audit 已审计以下仓库外固定 artifact，不得只引用
replay hash：

- path：`D:\MyGPT\basetemp\c7-active-mode-decision-full-game-v1-final\20260827T181631+0800`；
- `matrix.json` SHA-256：
  `a925e77848678342558ecfe0db21e417812c9fc28fb50931a2b2d351f8eb5e78`；
- seeds：`HEIR_SUCCESSION=1`、`SPY_TO_LOYALIST=1`、
  `SPY_TO_AMBITIONIST=2`；
- 磁盘冷加载后，正式 `Matrix.from_dict()`、三行 strict reexecute 与重新计算
  `c7_active_mode_decision_full_game_v1_proven=true` 全部通过。

## 15. AUTHORITATIVE_SKILL_RUNTIME_V1

- **状态**：`IMPLEMENTED / FINAL CLOSURE REAUDIT PASSED /
  2988/2988 FULL PYTEST PASSED / AUDITED_PASSED`
- **开发分支**：`codex/authoritative-skill-runtime-v1`
- **基线 Commit**：`e31c186a3833b0bfaa59969cbca65202e779cfc0`（tag: `c7-active-mode-decision-full-game-v1-audited`）
- **Implementation Identity（POST_B_CURRENT）**：
  `2460d3ac6998746a4aa5c13cf84321d652b965d9a462d325b41519625116c949`
- **不等于**：all generals、full skill roster、`FULL_GAME_READY`、
  `RELEASE_READY`、formal win-rate ready、AI ready。
- Skill Runtime V1 的 foundation、opt-in production integration 与 strict
  replay 可以独立于 proof skill 的完整度成立；这些基础设施结论不把任一
  proof skill 提升为完整武将语义，也不扩大到全武将表或整局技能模式。

### 15.1 审计与修复历史链（不得改写）

- `FIRST ADVERSARIAL AUDIT = FAILED`：当时 production integration、生产
  replay 与 proof skill 声明不满足冻结合同。
- 第一轮 remediation：targeted gates passed；【募讨】从 mandatory proof
  移除，改用【破降】；production opt-in、trigger 与 replay 接线完成。
- `SECOND ADVERSARIAL AUDIT = PASSED`：同一 implementation identity
  `50c676f7d7e8f1d8a149f72654aaf83b8fb08c029f93806bbab760bc85f24b22`；
  随后 full pytest 为 `2956 passed in 6052.68s (1:40:52)`、exit 0。
- 第一次 `FINAL CLOSURE AUDIT = FAILED`：F-01 exact cold-load/identity、
  F-02 no-skill/C7 真实 replay、F-03 proof skill production boundary、
  F-04 文档边界均未达到最终冻结合同；这不是前述 full pytest 的失败。
- `FINAL CLOSURE REMEDIATION = PASSED`
  （`AUTHORITATIVE_SKILL_RUNTIME_V1_FINAL_CLOSURE_REMEDIATION`）：
  production / test / replay remediation gates passed；新 identity 的 final
  full pytest 为 `2988 passed in 4577.58s (1:16:17)`、exit code 0，failed = 0、
  errors = 0、skipped = 0、xfailed = 0、xpassed = 0。
- `FINAL CLOSURE REAUDIT = PASSED`：F-01 exact replay schema 与 identity、
  F-02 no-skill/C7 真实 strict replay、F-03 proof skill production boundary、
  F-04 文档状态与边界均通过独立只读复核。因此当前冻结 scope 登记为
  `AUDITED_PASSED`；该结论不等于 release readiness，也不扩大 proof skill
  已证明范围。

### 15.2 当前基础设施与 replay 合同

1. `skill_registry=None` 仍是唯一 opt-in seam；旧 no-skill/C7 构造器与
   replay schema 不新增 skill 字段，真实 fixed-seed replay 已执行
   `to_dict → JSON → from_dict → strict reexecute`。
2. `SkillProductionReplayEnvelope` 现在是 exact cold JSON schema：required
   fields 精确、extra/missing 拒绝、`bool` 不得冒充 `int`、嵌套 action/event
   unknown fields 拒绝、空/重复 ID 拒绝。
3. 新增并绑定 `contract_identity` 与 `implementation_identity`；内层步骤材料
   由 `records_identity` 认证，outer envelope 由 `execution_identity` 认证。
   静态 schema/contract/implementation/registry/profile/assignment/hash
   preflight 全部通过后才允许构造 fresh `ProductionBasicCardBatch`。
4. serialized `verified` / `scenario_proven` 不是输入字段，出现即按 unknown
   field 拒绝；PASS 只来自 fresh live `legal_actions → action_id → step`。
5. 多 trigger 无正式排序仍 `UnsupportedRuleError`；`VIEW_AS` 仍失败关闭。

### 15.3 Proof skill 当前声明边界

- **【破降】=`PARTIAL / NOT FULL GENERAL SEMANTICS`**：当前证明交一张
  手牌/装备、摸三、流失 1 体力、阶段限一次，以及所摸实体牌在本正常回合
  弃牌阶段不计入 excess；下一正常换回合豁免清除。完整“绝”机制未实现，
  因此“移除所有绝”只在当前无“绝”的证明切片中是 no-op；技能导致濒死
  仍 fail closed / `NOT_PROVEN`；extra turn 豁免语义 `NOT_PROVEN`。
- **【帷幕】=已证明范围有限**：红色普通锦囊与基本牌不会被误过滤；黑色
  单体普通锦囊过滤、失效/失去/死亡后的恢复，以及一个黑色群体锦囊
  【南蛮入侵】边界有 production proof。AoE 的更广组合与延时锦囊适用范围
  不提升为完整语义；黑色延时锦囊当前显式 `NOT_PROVEN` 并失败关闭。
- **【明哲】=CURRENT CONFIRMED 已证明范围**：只声明真实 production
  `CARD_USED` / `CARD_PLAYED` / `CARD_DISCARDED` 触发、消费防重复、PASS
  无效果与 production draw；不外推到未测试事件/技能组合。

### 15.4 Final-closure checkpoints

- F-01 = TARGETED PASSED：exact schema/types/nested fields、contract +
  implementation identity、inner/outer hash、cold load、constructor sentinel
  0-call 与重算 hash 后的 deep tamper matrix。
- F-02 = TARGETED PASSED：真实 authoritative no-skill duel seed 0 与 C7
  `HEIR_SUCCESSION` seed 1 均完成 JSON cold load + `from_dict` + strict
  reexecute；skill-disabled path 无技能动作、技能事件或 runtime 配置。
- F-03 = TARGETED PASSED：【破降】真实 DISCARD excess 修复；【帷幕】红色/
  基本牌/lost/invalidated/death/黑色群体/延时 gap 边界。
- F-04 = PASSED：本节同步完整历史链、proof skill 限制、targeted 与 final
  full pytest 结果，并在独立 final closure reaudit 通过后准确登记
  `AUDITED_PASSED`；不提升为任何 release readiness。

### 15.5 Targeted evidence（final-closure remediation）

- Skill V1 八文件最终 targeted：`96 passed in 101.69s (0:01:41)`。
- 旧 replay 子集（no-skill duel + 单个 C7 `HEIR_SUCCESSION`）：
  `2 passed in 95.27s (0:01:35)`。
- `python -m compileall -q scripts tests`：exit 0；`git diff --check`：exit 0。
- final full pytest：`2988 passed in 4577.58s (1:16:17)`，exit code 0；
  failed = 0、errors = 0、skipped = 0、xfailed = 0、xpassed = 0。
- 当前 computed implementation identity 与唯一
  `POST_B_CURRENT_IMPLEMENTATION_IDENTITY` 均为
  `2460d3ac6998746a4aa5c13cf84321d652b965d9a462d325b41519625116c949`；
  `FROZEN_R8_IMPLEMENTATION_IDENTITY` 未改变。
- 本轮 finalization 未创建 PR，未进入 Stage3 / C8，未重跑 full pytest。
- `FINAL CLOSURE REAUDIT = PASSED`；当前冻结 scope 进入
  `AUDITED_PASSED`，但不提升为 §15 开头列出的任何更宽 readiness。

## 16. AUTHORITATIVE_GENERAL_BATCH_V1 — G1 SHAMOKE

### 16.1 当前裁定与 Batch 边界

- `G1_SHAMOKE_DOCUMENTATION_FINALIZATION = PASSED`
- `G1_SHAMOKE_SIXTH_CLOSURE_AUDIT = PASSED`
- `G1_SHAMOKE_FINAL_FULL_PYTEST = PASSED`
- `SHAMOKE = GENERAL_COMPLETE`
- `G1_FREEZE_READY = YES`
- `READY_FOR_G2_IMPLEMENTATION = NO`
- `AUTHORITATIVE_GENERAL_BATCH_V1 = IN_PROGRESS`
- `AUTHORITATIVE_GENERAL_BATCH_V1 != COMPLETE`

G1 的 canonical general key 为 `shamoke`，HP / max HP 为 `4 / 4`，
authoritative skill 为 `sgs_skill_jili`。当前 G1 已满足 `GENERAL_COMPLETE`；
但 Batch V1 还计划 G2 / 诸葛瞻与 G3 / 王元姬，二者均未开始。因此本节不把
Batch V1 登记为 implemented complete、audited complete 或 frozen complete，也不授权开始 G2。

### 16.2 Snapshot、identity 与冻结来源

- 开发分支：`codex/authoritative-general-batch-v1-prep`
- HEAD baseline：`5e1c05ddc777a3b8d13d394acd3e4d7158e0ecad`
- computed implementation identity：
  `af66c568eb0c4b166139e24349f6e46e2a4735949125a326dde0490b8ade434e`
- `POST_B_CURRENT_IMPLEMENTATION_IDENTITY`：
  `af66c568eb0c4b166139e24349f6e46e2a4735949125a326dde0490b8ade434e`
- computed identity 与 current pin 精确一致。
- G1 final full pytest 的 PRE / POST branch、HEAD、identity、pin、exact
  changed-path set、staged、unmerged 与 `git diff --check` 均无漂移。
- 既有 frozen historical identities、commits 与 tags 均未改写；当前开发 pin
  不反向覆盖任何历史冻结 identity。

### 16.3 审计与修复历史链（必须完整保留）

1. `G1_SHAMOKE_FIRST_ADVERSARIAL_AUDIT = FAILED`
2. `G1_SHAMOKE_REMEDIATION = PASSED`
3. `G1_SHAMOKE_SECOND_ADVERSARIAL_AUDIT = FAILED`
4. `G1_SHAMOKE_SECOND_AUDIT_REMEDIATION = PASSED`
5. `G1_SHAMOKE_THIRD_ADVERSARIAL_AUDIT = FAILED`
6. `G1_SHAMOKE_THIRD_AUDIT_REMEDIATION = PASSED`
7. `G1_SHAMOKE_FOURTH_ADVERSARIAL_AUDIT = FAILED`
8. `G1_SHAMOKE_FOURTH_AUDIT_REMEDIATION = PASSED`
9. `G1_SHAMOKE_FIFTH_ADVERSARIAL_AUDIT = FAILED`
10. `G1_SHAMOKE_FIFTH_AUDIT_REMEDIATION = PASSED`
11. `G1_SHAMOKE_SIXTH_CLOSURE_AUDIT = PASSED`
12. `G1_SHAMOKE_FINAL_FULL_PYTEST = PASSED`

前五次敌对审计的 `FAILED` 是永久历史事实；后续 remediation 与第六轮 closure
通过不把这些历史结果改写为 `PASSED`。

### 16.4 GENERAL_COMPLETE 12 gates

| Gate | 最终裁定 |
| --- | --- |
| 1. Knowledge / rule source | `PROVEN` |
| 2. Canonical `GeneralDefinition` | `PROVEN` |
| 3. Assignment → derived skills | `PROVEN` |
| 4. Jili count / range / semantics | `PROVEN` |
| 5. Generic pre-effect checkpoint | `PROVEN` |
| 6. Signed continuation authority | `PROVEN` |
| 7. Draw transaction | `PROVEN` |
| 8. Normal turn lifecycle | `PROVEN` |
| 9. Extra-turn | `NOT_APPLICABLE_TO_CURRENT_MODES` |
| 10. Replay / deep tamper | `PROVEN` |
| 11. No-skill / legacy transparency | `PROVEN` |
| 12. Test and claim quality | `PROVEN` |

全部适用 gate 均为 `PROVEN`；extra-turn 在当前模式中没有可适用的 production
capability，因此准确状态为 `NOT_APPLICABLE_TO_CURRENT_MODES`，不得伪造成已实现能力。

Closure findings：

- `F-THIRD-001 = CLOSED`
- `F-THIRD-002 = CLOSED`
- `F-THIRD-003 = CLOSED`
- `F-FOURTH-001 = CLOSED`
- `F-FOURTH-002 = CLOSED`
- `F-FIFTH-001 = CLOSED`

### 16.5 最终证明的 production properties

1. `GeneralDefinition` 是 canonical HP 与 skill authority；registry、assignment 与
   replay 均以 live canonical definition 派生并认证 `shamoke` 的 `4 / 4` 与
   `sgs_skill_jili`。
2. 所有适用的正式 `CARD_USED` / `CARD_PLAYED` emitter 均进入 generic
   pre-effect `POST_CARD_USED_OR_PLAYED_TRIGGER_CHECKPOINT`；遗漏 checkpoint 的路径
   fail closed。
3. Jili 只统计真实 use / play，按触发前攻击范围比较本回合计数，并覆盖正式
   attack-range、回合累计与自然 turn reset 语义。
4. 技能选择通过 signed `legal_actions → action_id → step`；ACTIVATE / PASS 与
   single-use continuation 绑定 source event、actor、card、target、phase、revision
   及 continuation identity。
5. `step()` 与 continuation resume 具有事务原子性；异常时 GameState、events、
   sequence、RNG、SkillRuntime、batch runtime、continuation、card locations 与
   已应用外层效果恢复到调用前状态。
6. mode-policy 使用 authoritative snapshot / restore；失败事务恢复原 mode policy，
   C7 variant 身份、mark、胜负语义与相关可变容器能够回滚。
7. `GeneralProductionReplayEnvelope` 覆盖 exact cold-load、fresh strict reexecute、
   canonical general / assignment / derived skill / semantic payload、trigger、usage、
   marks、continuation、state、event 与 RNG 认证；重算 envelope identities 后的
   deep tamper 仍被拒绝。
8. no-skill / legacy 路径保持透明，不注入技能动作、技能事件或空 skill registry，
   既有模式与 replay schema 未发生技能语义漂移。

### 16.6 Knowledge 边界

- 【帷幕】对黑色延时锦囊的 target-legality completion 是当前开发分支内容；
  §15.3 的较早 `AUTHORITATIVE_SKILL_RUNTIME_V1` proof-slice 边界属于其冻结历史
  scope，不得用来撤销当前分支的 completion，也不得反写历史 Skill Runtime V1
  identity / tag。
- `POST_CARD_RESOLUTION_DURING_DYING = USER_CONFIRMED_CURRENT` 仅是 Knowledge
  future boundary；它不声称孙綝、【戮连】或 nested dying production 已实现。
- 2v2 teammate hand visibility 仅登记为 Knowledge 边界；本轮不声称已实现完整
  hand-visibility engine。

### 16.7 Final full pytest evidence

实际执行的完整无过滤命令为：

```powershell
D:\MyGPT\game-analysis-grok-eval\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=D:\MyGPT\basetemp\general-batch-v1-g1-full-20260829T1647
```

- exact summary：`3111 passed in 4657.65s (1:17:37)`
- exit code：`0`
- failed = `0`；errors = `0`；skipped = `0`；xfailed = `0`；xpassed = `0`
- stderr：empty
- PRE / POST exact changed-path set：`22` paths（`15` tracked modified + `7`
  untracked），完全一致；staged = `0`；unmerged = `0`；`git diff --check` = exit `0`

该 full pytest 只绑定 §16.2 的当前 identity / pin，不替代或重写任何历史 identity
上的测试记录。

### 16.8 Documentation finalization / freeze-readiness

本轮只更新本权威状态文档并执行文档、Knowledge、compileall、diff-check 与 identity
定向 sanity checks；没有重跑 full pytest。完成后状态为：

```text
G1_SHAMOKE_DOCUMENTATION_FINALIZATION = PASSED
SHAMOKE = GENERAL_COMPLETE
G1_FREEZE_READY = YES
READY_FOR_G2_IMPLEMENTATION = NO
```

本轮未执行 commit、push、tag 或 PR，未开始 G2 / G3，也未进入 Stage3 / C8。
后续生命周期由用户另行决定：可以单独冻结 G1，或保留当前工作树进入 G2 后再按
Batch V1 一起冻结；本节本身不授权其中任一路径。

G1 冻结完成后的 G2 preflight 见 §17 与 `docs/G2_ZHUGEZHAN_PREFLIGHT.md`。
本节 G1 历史状态值保持冻结当时的原样，不把后来的 G2 preflight 回写进
`READY_FOR_G2_IMPLEMENTATION = NO`。

## 17. AUTHORITATIVE_GENERAL_BATCH_V1 — G2 ZHUGEZHAN PREFLIGHT

### 17.1 本轮范围

本轮只做 G2 诸葛瞻 preflight：

- 从 G1 frozen commit 新建分支
- rule-source preflight
- implementation-gap map
- timing/checkpoint map
- GENERAL_COMPLETE proof matrix
- deterministic test plan

未实现技能，未跑 full pytest，未 commit / push / tag，未开始 G3。

### 17.2 分支与冻结点

- 新分支：`codex/authoritative-general-batch-v1-g2-zhugezhan`
- 起点 / 当前 HEAD：`678179214a2260c23c95d03740191b1246024bbc`
- G1 tag：`authoritative-general-batch-v1-g1-shamoke-audited`
- G1 tag peeled commit 仍为上述 G1 frozen commit
- G1 tag 与 G1 历史未改写

### 17.3 Preflight 裁定

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

技能名确认为【罪论】【父荫】。仓库中不存在【罪己】。不得沿用该错误名。

`zhugezhan.gender = MALE`。来源是无争议历史人物真实性别 / canonical metadata，不属于技能 rule-source。游戏没有给出相反性别设定。不要求 Knowledge 诸葛瞻技能条目另外写“男”。虚构人物、历史性别有争议、或游戏改写性别的角色仍必须单独确认。

完整缺口图、时机图、12 门矩阵与确定性测试计划见
`docs/G2_ZHUGEZHAN_PREFLIGHT.md`。

### 17.4 最小用户确认

无。此前唯一 registry metadata blocker 已关闭。

## 18. AUTHORITATIVE_GENERAL_BATCH_V1 — G2 ZHUGEZHAN IMPLEMENTATION

### 18.1 实现范围与 canonical metadata

本轮在 `codex/authoritative-general-batch-v1-g2-zhugezhan` 上实现诸葛瞻，
保持 G1 frozen commit
`678179214a2260c23c95d03740191b1246024bbc` 与 tag
`authoritative-general-batch-v1-g1-shamoke-audited` 不变。canonical
`GeneralDefinition` 为：

- key = `zhugezhan`
- gender = `MALE`
- starting_hp / max_hp = `3 / 3`
- skill_ids = `sgs_skill_zuilun`、`sgs_skill_fuyin`

assignment 通过 live canonical definition 自动派生技能；replay 重新
canonicalize live payload。未分配诸葛瞻时，no-skill / legacy path 保持透明。

### 18.2 【罪论】production 语义

- 在真正的 `END_PHASE_START` checkpoint 发现可选触发，不使用
  `TURN_END` / `AFTER_TURN_END` 近似；跳过结束阶段时不发现。
- 统一读取当回合伤害、弃牌与最少手牌三项通用事实，记录
  `SKILL_CONDITION_EVALUATED` 与 `n ∈ {0,1,2,3}`；事实按 turn identity
  确定性重置。
- `ACTIVATE / PASS` 使用 signed action 与 single-use continuation。`n > 0`
  进入私有 top-3 窗口，恰好选择 `n` 张获得，未选牌保留原始相对顺序
  回到牌堆顶；记录 `PRIVATE_CARDS_OBSERVED`，不触发普通 `DRAW`。
- top-3 供牌复用现有 deck-supply / reshuffle 规则；若仍不足且没有权威
  private-view terminal 规则，则 fail closed。
- `n = 0` 先令诸葛瞻失去 1 点体力，复用正式 dying / death /
  victory 链。若游戏未结束，再通过 signed target choice 令一名其他存活角色
  失去 1 点体力，第二段也走完整链。
- decision、top-3 选择、目标选择、牌移动、HP、runtime、continuation、
  events 与 RNG 全部纳入 authoritative step transaction 回滚。

### 18.3 【父荫】production 语义

- 作为锁定技在用牌者侧 `POST_CARD_USED_OR_PLAYED` 之后、目标效果之前
  进入独立 mandatory target-effect checkpoint，不生成 `ACTIVATE / PASS`。
- 每个独立回合第一次成为【杀】或【决斗】目标后立即消耗机会，无论比较
  结果如何；非该类牌不消耗，下一 turn identity 自然重置。
- 比较用牌后用牌者手牌数与诸葛瞻手牌数。当前者 `<=` 后者时，
  只为该 target 记录 `TARGET_EFFECT_INEFFECTIVE`，不改写成
  `CARD_INVALIDATED` 或 `TARGET_CANCELLED`。
- marker 以 source card-event / target 为作用域；Fangtian 多目标【杀】的其他目标仍
  独立正常结算。
- 【蒺藜】先走已冻结的可选技能 continuation，然后进入父荫的独立锁定技
  checkpoint；发现顺序确定，不争用或覆盖 Jili continuation。

### 18.4 通用 primitive、replay 与 deep tamper

本轮最小扩展了 `END_PHASE_START`、per-turn skill fact / state、私有
top-deck 观看与选择、ordered skill HP-loss continuation，以及 target-scoped
effect ineffectiveness。core 不以诸葛瞻技能名作为牌类特例布尔分支。

`GeneralProductionReplayEnvelope` 的 cold-load strict replay 现在认证 canonical
assignment / derived skills、罪论时机与条件事实、`n`、抉择、top-3 身份与
顺序、未选牌顶顺序、HP-loss 目标、父荫消耗状态、双方手牌数、
target-effect 结果、continuation、state / events / RNG before-after。
deep tamper 测试在重算外层 record 与 execution identities 后，仍拒绝篡改
`n` / 条件事实、top-3 牌或顺序、所选牌、父荫消耗状态、双方手牌数或
ineffective 结果。

### 18.5 定向验证与 implementation identity

本轮仅运行 G2 registry / production / replay-tamper、G1 代表回归、Skill Runtime、
card / Slash / Duel / target-effect、turn lifecycle / END_PHASE、no-skill、source
integrity、Knowledge 与 pin comparison 相关定向集：

```text
collected = 617
passed = 617
failed = 0
deselected = 0
skipped = 0
xfail = 0
duration = 216.24s (0:03:36)
```

本轮没有运行 full pytest。新的 current development implementation identity / pin 为：

```text
c87b984a10034d6ac9de336eb17895e1892fe5c3b4dc817e2e6b27790d0e316c
```

该 pin 只更新当前开发身份；G1 frozen identity
`af66c568eb0c4b166139e24349f6e46e2a4735949125a326dde0490b8ade434e`
与 G1 tag 均未修改。

### 18.6 当前门禁

```text
G2_ZHUGEZHAN_IMPLEMENTATION = PASSED
ZHU GEZHAN = GENERAL_COMPLETE_CANDIDATE
READY_FOR_G2_FIRST_ADVERSARIAL_AUDIT = YES
READY_FOR_G2_FULL_PYTEST = NO
READY_FOR_G3_IMPLEMENTATION = NO
```

本轮未执行 commit、push、tag 或 PR，未进入 G3、Stage3 或 C8。
下一步仅是 G2 第一轮独立敌对审计；在该审计与后续门禁通过前，
不得将诸葛瞻登记为 `GENERAL_COMPLETE`。

## 19. AUTHORITATIVE_GENERAL_BATCH_V1 — G2 ZHUGEZHAN FIRST AUDIT REMEDIATION

### 19.1 历史审计状态

第一轮独立敌对审计历史结论原样保留：

```text
G2_ZHUGEZHAN_IMPLEMENTATION = PASSED
G2_ZHUGEZHAN_FIRST_ADVERSARIAL_AUDIT = FAILED
ZHU GEZHAN = GENERAL_COMPLETE_CANDIDATE
REMEDIATION_REQUIRED
READY_FOR_G2_FULL_PYTEST = NO
READY_FOR_G3_IMPLEMENTATION = NO
```

该审计记录了 `F-G2-001` 至 `F-G2-004`；本节只记录随后 remediation 的
生产改动与正式 repo proof，不把历史 `FAILED` 改写为通过。

### 19.2 F-G2-001 — private observation projection

权威事件继续保存 `PRIVATE_CARDS_OBSERVED` 的真实 `observed_card_ids`、
顺序、选择与剩余牌序，供 strict replay 做 live semantic validation。通用
`_redact_private_hand_event` 现在识别所有 `private_cards_observed` 事件；只有
`skill_owner` 本人视图保留实体字段。公共视图与其他角色视图只保留
`skill_id`、stage、数量等安全 metadata，并删除 card ids、顺序、选择、
`window_id` 与 `continuation_identity`。

| 投影视图 | top-3 / selected 实体 | 权威 strict replay 真相 |
| --- | --- | --- |
| owner (`p1`) | 可见 | 保留并验证 |
| public (`None`) | 不可见 | 不修改权威记录 |
| other player (`p2`) | 不可见 | 不修改权威记录 |

正式测试从真实 `END_PHASE_STARTED → signed ACTIVATE → private selection`
生成事件，并同时验证 owner/public/other 三视图、权威事件不变、clean replay
通过，以及在重算 `records_identity` / `execution_identity` 后篡改观察牌身份或
顺序仍被拒绝。

### 19.3 F-G2-002 — Fuyin event semantics

修复前，比较失败仍生成 `TARGET_EFFECT_INEFFECTIVE`，仅在 payload 写入
`target_effect_ineffective=false`，事件类型与事实矛盾。修复后：

- 首次机会的消费和比较结果由一条 `SKILL_CONDITION_EVALUATED` 认证；
- 只有比较成立、该目标牌效实际无效时，才生成恰好一条
  `TARGET_EFFECT_INEFFECTIVE`；
- 比较失败时机会仍消费、牌效正常，且该事件数量严格为零；
- 同回合第二次【杀】/【决斗】不再判定，下一 turn identity 恢复机会；
- Fangtian 其他目标不继承诸葛瞻的 target-scoped ineffective；
- 【蒺藜】`PASS` 与 `ACTIVATE` 两条 continuation 均先完成，再进入父荫。

strict replay 分别记录 true / false 两条 clean path，并独立认证
`consumed_after=true` 与 ineffective event presence；重算外层 identities 后，
把 false 改成 true、删除 true path 的 ineffective event 或篡改手牌数/mark
均被 live reexecution 拒绝。

### 19.4 F-G2-003 — n=0 replay / deep tamper

`GeneralProductionReplayEnvelope` 增加通用 `initial_hand_count` 初始配置字段，
fresh reexecution 按记录重建同一生产会话；长回放允许合法动作集合哈希重复，
但仍逐步比较每一项 live legal-set hash。正式覆盖两条完全由 signed production
actions 生成的 `n=0`：

1. `END_PHASE_STARTED → ACTIVATE(n=0) → self LOSE_HP → signed p2 target
   choice → p2 LOSE_HP → continuation consumed`，诸葛瞻存活且游戏未结束；
2. 两次真实【决斗】响应令诸葛瞻降至 1 HP、对手手牌降至 0，弃牌阶段自然
   形成零条件；随后 `ACTIVATE(n=0) → self LOSE_HP → DYING → DEATH →
   VICTORY`，终局严格停止第二段。

两条 fresh strict reexecution 均通过。deep-tamper 在重算外层 identities 后覆盖：
`n`、三项事实、self HP-loss、pending target legal set、未知/过期/自身目标、
target choice、trigger sequence/type、continuation identity、per-turn runtime、
state before/after、event slice 与 RNG hash；终局路径另拒绝伪造的第二段
`LOSE_HP`。

### 19.5 F-G2-004 — production facts

四档主证明不再依赖直接写 `_state` / `_events`：

| n | 真实生产动作与事实 | 最终事实 |
| --- | --- | --- |
| 0 | 正常摸牌后进入真实弃牌阶段；对手手牌更少 | damage=false, discarded=true, minimum=false |
| 1 | 不造成伤害、不弃置；对手手牌更少 | false, false, false，仅“未弃置”成立 |
| 2 | 真实【杀】成功伤害；不弃置；对手手牌更少 | true, false, false |
| 3 | 真实装备【寒冰剑】后使用【杀】并选择正常伤害；不弃置；与对手并列最少 | true, false, true |

附加 production boundaries 覆盖藤甲阻止普通【杀】时 damage=false、两次成功
伤害仍只形成 bool fact、使用牌/决斗中打出【杀】进入弃牌堆不等于弃置、
寒冰剑由行为执行者弃置装备区牌计为执行者弃置、【过河拆桥】弃置诸葛瞻
的牌不计为诸葛瞻本人弃置，以及方天多目标真实死亡后 dead player 不参与
live minimum-hand 比较。

### 19.6 定向验证与 identity

显式定向矩阵覆盖 G2 registry/production/replay、全部新增 visibility 与 tamper
节点、Slash/Duel/armor/weapon/group-target、turn lifecycle、G1 Shamoke、
Skill Runtime（含 6 个按设计修改并恢复源码的 identity mutation 节点）、
no-skill、C7 代表集、source integrity 与 Knowledge：

```text
collected = 648
passed = 648
failed = 0
deselected = 0
skipped = 0
xfail = 0
duration = 1009.05s (0:16:49)
```

本轮没有运行 full pytest。新的 current development implementation identity / pin：

```text
84b78fe832f19c6055b1d44bc50c03a8ea763b44743bf4bf74c602129a6d5e3a
```

只更新 current development pin；G1 frozen identity
`af66c568eb0c4b166139e24349f6e46e2a4735949125a326dde0490b8ade434e`
与 tag `authoritative-general-batch-v1-g1-shamoke-audited` 均未修改。

最终静态与 Git 门禁：`compileall = exit 0`；`git diff --check = exit 0`
（仅保留既有 LF/CRLF 提示）；`staged = 0`；`unmerged = 0`。开发分支仍为
`codex/authoritative-general-batch-v1-g2-zhugezhan`，HEAD / merge-base / G1 tag
peeled commit 均为 `678179214a2260c23c95d03740191b1246024bbc`。

### 19.7 当前门禁

```text
F-G2-001 = CLOSED
F-G2-002 = CLOSED
F-G2-003 = CLOSED
F-G2-004 = CLOSED

G2_ZHUGEZHAN_FIRST_AUDIT_REMEDIATION = PASSED
ZHU GEZHAN = GENERAL_COMPLETE_CANDIDATE
READY_FOR_G2_SECOND_ADVERSARIAL_AUDIT = YES
READY_FOR_G2_FULL_PYTEST = NO
READY_FOR_G3_IMPLEMENTATION = NO
```

未运行 full pytest，未执行 commit、push、tag 或 PR，未进入 G3、Stage3 或 C8。
下一步只能是第二轮独立敌对审计；不得据此自行登记 `GENERAL_COMPLETE`。

## 20. AUTHORITATIVE_GENERAL_BATCH_V1 — G2 SECOND AUDIT REMEDIATION

### 20.1 历史状态与本轮边界

以下历史结论原样保留，不因 remediation 改写：

```text
G2_ZHUGEZHAN_IMPLEMENTATION = PASSED
G2_ZHUGEZHAN_FIRST_ADVERSARIAL_AUDIT = FAILED
F-G2-001 = CLOSED
F-G2-002 = CLOSED
F-G2-003 = CLOSED
F-G2-004 = CLOSED
G2_ZHUGEZHAN_FIRST_AUDIT_REMEDIATION = PASSED
G2_ZHUGEZHAN_SECOND_ADVERSARIAL_AUDIT = FAILED
ZHU GEZHAN = GENERAL_COMPLETE_CANDIDATE
```

第二轮审计确认首轮四项 finding 仍为 `CLOSED`，并新增 `F-G2-005`、
`F-G2-006` 两个 HIGH correctness finding。本节只记录这两项的修复与正式
targeted proof，不运行 full pytest，不进入 G3 / Stage3 / C8。

### 20.2 F-G2-005 — 统一 END_PHASE 入口

修复前，`_enter_discard_or_end` 在 hand <= limit 时只返回
`phase=ProductionPhase.END`。正常 `end_play_phase` 与弃牌提交会另行调用
`_open_end_phase_skill_checkpoint`，但【乐不思蜀】跳过 PLAY 后的 auto-END
以及【兵粮寸断】+【乐不思蜀】从 `_advance_past_judgment` 直接 END 不会调用，
导致规则上真实存在的结束阶段没有 `END_PHASE_STARTED` 与【罪论】窗口。

修复后由通用 `_enter_end_phase(state, previous, next_runtime)` 统一提交真实
END 阶段边界并打开一次 skill checkpoint。当前所有普通生产入口为：

1. 正常 PLAY 结束且 hand <= limit：`PLAY → END`；
2. 正常 PLAY 结束且 hand > limit：`PLAY → DISCARD → END`；
3. 判断/摸牌流程跳过 PLAY，摸牌后 hand <= limit：`DRAW → END`；
4. 判断/摸牌流程跳过 PLAY，摸牌后 hand > limit：`DRAW → DISCARD → END`；
5. DRAW 与 PLAY 均被延时锦囊跳过：`JUDGMENT → END`。

`DYING_RESCUE` 或多步技能 continuation 返回同一个 END 阶段不是新的阶段
边界，继续走 continuation 专用恢复路径，因此不会再发第二条
`END_PHASE_STARTED`；`end_turn` 也不会补发。当前引擎没有正式的全局
“跳过整个 END_PHASE”能力，该 zero-event 边界为 `NOT_APPLICABLE`，未臆造
测试夹具。

正式 signed production tests 覆盖：乐命中且手牌恰等于体力上限的 auto-END、
乐命中且超上限的 DISCARD→END、兵粮+乐直接越过 DRAW/PLAY、普通非跳过
PLAY→END；每条均断言 END checkpoint exactly once、【罪论】ACTIVATE/PASS
可见，且 `end_turn` 后事件数不增加。turn facts 仍在原 turn boundary 重置，
统一入口未提前或重复调用 `on_turn_change`。

### 20.3 F-G2-006 — post-resume live SkillRuntime commit

修复前，`_apply_production_skill_action` 在决策窗口开始时捕获旧
`skill_runtime`；Jili ACTIVATE 完成摸牌并恢复 card continuation 后，父荫已在
`_post_target_effect_checkpoint` 写入 `fuyin_consumed_turn`，但末尾仍以旧对象
执行 `increment_usage` 并整棵写回，覆盖了 live mark。

修复后，handler 与 continuation 全部成功后重新读取
`self._skill_runtime`，只在该 live runtime 上增量执行 Jili usage commit。该设计
不依赖 Fuyin 字段，不做武将特判；resume 期间任何其他 owner/skill 的
marks、usage 或 queued resolution 所形成的 runtime 变化都会保留。

正式 proof 在同一真实 `CARD_USED` 中执行 p2 Shamoke 对 p1 Zhugezhan 的第一张
Slash、Jili ACTIVATE、Fuyin mandatory target-effect checkpoint 与 continuation
resume。结束后同时断言：

- `p2/sgs_skill_jili.uses_this_turn == 1`；
- `p1/sgs_skill_fuyin.marks.fuyin_consumed_turn == live turn_number`；
- 同回合第二张 Duel 不再增加 Fuyin condition event，也不增加 ineffective event；
- Fuyin condition=false 时机会仍消费，第二张牌同样不再判定；
- 注入另一技能的无关 mark 后，Jili usage、Fuyin mark 与该 mark 三者同时保留；
- continuation 内部在 Fuyin 写 mark 后抛错时，外层 step transaction 将 state、
  events、Jili usage、Fuyin mark、完整 SkillRuntime 与 continuation authority
  原子回滚。

Jili PASS 对照、duplicate/stale continuation 与既有 two-phase consumption 合同
继续由 G1/G2 targeted suites 覆盖。

### 20.4 Replay / deep tamper

乐 skip-PLAY → auto-END → Zuilun PASS 已加入 fresh cold-load strict
reexecution；记录中必须同时存在一条 `PHASE_SKIPPED(play)` 与恰好一条
`END_PHASE_STARTED`，live legal-actions/semantic hashes、事件切片、状态和 RNG
逐步重算一致。

通用 `GeneralProductionReplayEnvelope` 现在认证完整 `skill_runtime_after`，而不只
认证 primary skill 的 usage/marks。Jili ACTIVATE + Fuyin 同事件 mixed-general
回放同时记录 Jili usage 与 Fuyin consumed mark；攻击者即使修改其中任一、重算
`records_identity` 与 `execution_identity`，fresh live reexecution 仍因完整
SkillRuntime 不一致而失败关闭。回放构造器从第一步 signed semantics 绑定
`first_player_id`，支持同一双人信封中 p1 Zhugezhan + p2 Shamoke 的真实顺序。

### 20.5 Targeted validation、identity 与门禁

统一 targeted matrix 覆盖 G2 registry/production/replay、END/延时锦囊/phase
skip、Slash/Duel/Fuyin/Jili、G1 Shamoke production/replay、Skill Runtime
identity mutation（测试后源码原样恢复）、no-skill isolation、C7 mode-policy
代表集、privacy/replay projection、source integrity 与 Knowledge：

```text
collected = 420
passed = 420
failed = 0
deselected = 0
skipped = 0
xfail = 0
duration = 786.50s (0:13:06)
```

本轮没有运行 full pytest。新的 current development implementation identity / pin：

```text
7394e4ca25c85f4e9454bad363c707c7a1487d0b027c014c4d8708c176359c66
```

G1 frozen identity
`af66c568eb0c4b166139e24349f6e46e2a4735949125a326dde0490b8ade434e`
与 tag `authoritative-general-batch-v1-g1-shamoke-audited` 未修改。

最终状态：

```text
F-G2-005 = CLOSED
F-G2-006 = CLOSED
G2_ZHUGEZHAN_SECOND_AUDIT_REMEDIATION = PASSED
ZHU GEZHAN = GENERAL_COMPLETE_CANDIDATE
READY_FOR_G2_CLOSURE_AUDIT = YES
READY_FOR_G2_FULL_PYTEST = NO
READY_FOR_G3_IMPLEMENTATION = NO
```

未登记 `GENERAL_COMPLETE`；未运行 full pytest；未执行 commit、push、tag 或
PR；未进入 G3、Stage3 或 C8。下一步只能是 G2 closure audit。

## 21. AUTHORITATIVE_GENERAL_BATCH_V1 — G2 ZHUGEZHAN DOCUMENTATION / STATUS FINALIZATION

本节是 G2 诸葛瞻的当前 authoritative status。§17 的 preflight、§18 的
implementation、§19 的 first-audit remediation 与 §20 的 second-audit
remediation 均为历史记录，保留其当时的 `FAILED` / `GENERAL_COMPLETE_CANDIDATE`
结论；本节不把历史失败改写成“从未失败”。

### 21.1 General metadata 与 rule-source status

| 字段 | authoritative 值 |
| --- | --- |
| general key | `zhugezhan` |
| gender | `MALE` |
| starting HP / max HP | `3 / 3` |
| skill IDs | `sgs_skill_zuilun`、`sgs_skill_fuyin` |

- `G2_RULE_SOURCE = COMPLETE`；Knowledge source 已完成并与最终生产语义一致。
- gender source = user-confirmed historical canonical metadata；它不属于
  skill rule-source。`MALE` 是 canonical `GeneralDefinition` 的元数据裁定，
  不是由技能规则文本推导出的事实。
- `sgs_skill_zuilun` 对应【罪论】，`sgs_skill_fuyin` 对应【父荫】；仓库中没有
  把【罪论】误写成【罪己】的 authoritative skill ID。

### 21.2 Implementation summary

#### 【罪论】

- 触发点是当前角色真实结束阶段的 `END_PHASE_START`，由真实
  `END_PHASE_STARTED` checkpoint 打开；不以 `TURN_END` 或
  `AFTER_TURN_END` 近似，也不在跳过结束阶段后补触发。
- 发动时从 live production facts 统一计算 `n = 0/1/2/3`：本回合造成伤害、
  本回合明确弃置过牌、以及手牌数为全场存活角色最少。三项事实按独立 turn
  identity 重置，不从普通牌移动、使用、打出、重铸、装备替换或被他人获得
  推导“弃置”。
- `n > 0` 时私有观看牌堆顶三张，并在私有窗口中恰好选择 `n` 张获得；未选牌
  以观看时的原始相对顺序回到牌堆顶。`PRIVATE_CARDS_OBSERVED` 的实体牌信息
  只向技能拥有者投影，public / other-player 视图不泄漏牌 ID、顺序、选择、
  `window_id` 或 continuation identity。
- `n = 0` 时按有序链先令诸葛瞻失去 1 点体力，再在游戏尚未结束时通过 signed
  target choice 令一名其他存活角色失去 1 点体力；两段都复用正式的 dying /
  death / victory 链。诸葛瞻死亡并结束游戏时严格停止第二段。
- 【罪论】的观看/获得/回顶不是普通 `DRAW`；相关 decision、牌移动、HP、
  runtime、continuation、events 与 RNG 均受 authoritative step transaction、
  strict replay 与 visibility projection 约束。

#### 【父荫】

- 每个 independent turn 只有第一次成为【杀】或【决斗】目标时检查并立即消耗
  机会；非该类牌不消耗，同回合后续【杀】/【决斗】不再检查，下一独立回合
  自动恢复。
- 比较发生在用牌者完成用牌后的 hand count：当用牌者当前手牌数
  `<=` 诸葛瞻当前手牌数时，只对诸葛瞻这个 target 令该牌效果无效。
- 该结果是 target-scoped `TARGET_EFFECT_INEFFECTIVE`，不是整张牌的
  `CARD_INVALIDATED`，也不是 `TARGET_CANCELLED`；比较不成立时机会仍消耗，
  牌效正常结算且不生成虚假的 ineffective event。
- 与【蒺藜】共存：同一真实用牌中先完成用牌者的 Jili `ACTIVATE / PASS`
  continuation，再进入诸葛瞻成为目标后的 Fuyin mandatory checkpoint；live
  `SkillRuntime` commit 保留双方 usage / mark，不互相覆盖。

### 21.3 Audit history（完整保留）

1. `G2_ZHUGEZHAN_IMPLEMENTATION = PASSED`。
2. first adversarial audit = `FAILED`，发现：
   - `F-G2-001`：private top3 leak；
   - `F-G2-002`：错误生成 false `TARGET_EFFECT_INEFFECTIVE` event；
   - `F-G2-003`：replay / deep-tamper evidence gap；
   - `F-G2-004`：production-facts proof gap。
3. first-audit remediation = `PASSED`；`F-G2-001`、`F-G2-002`、`F-G2-003`、
   `F-G2-004` 均为 `CLOSED`。
4. second adversarial audit = `FAILED`，新增：
   - `F-G2-005`：skip-PLAY auto-END 漏掉真实 `END_PHASE_START`；
   - `F-G2-006`：Jili `ACTIVATE` 后 stale `SkillRuntime` 覆盖 Fuyin mark。
5. second-audit remediation = `PASSED`；`F-G2-005`、`F-G2-006` 均为
   `CLOSED`。
6. closure audit = `PASSED`；12/12 gates `PROVEN`，诸葛瞻正式达到
   `GENERAL_COMPLETE`。
7. final full pytest first run = `FAILED`，原因与规则语义审计分开记录：
   manifest 中 `scripts/sgs_engine/actions.py` 的 SHA-256 mismatch，以及
   pytest cleanup 的 `PermissionError [WinError 32]` harness errors。
8. manifest / harness remediation = `PASSED`；最终 rerun = `3195/3195`
   passed，未把首次失败改写成“从未失败”。

### 21.4 Closure audit proof matrix

`G2_ZHUGEZHAN_CLOSURE_AUDIT = PASSED`，12/12 gates 均已证明：

| Gate | 最终裁定 |
| --- | --- |
| 1. Knowledge / rule source | `PROVEN` |
| 2. Canonical `GeneralDefinition` | `PROVEN` |
| 3. Assignment → derived skills | `PROVEN` |
| 4. 【罪论】count / range / semantics | `PROVEN` |
| 5. Generic pre-effect target checkpoint | `PROVEN` |
| 6. Signed continuation authority | `PROVEN` |
| 7. Card movement / draw / discard transaction | `PROVEN` |
| 8. Normal turn lifecycle facts | `PROVEN` |
| 9. Extra-turn | `NOT_APPLICABLE_TO_CURRENT_MODES` |
| 10. Replay / deep tamper | `PROVEN` |
| 11. No-skill / legacy transparency | `PROVEN` |
| 12. Test and claim quality | `PROVEN` |

第 9 项是当前生产模式没有 extra-turn capability 的准确边界，不把“不适用”
伪造为已实现能力；其余 11 项均为 `PROVEN`，因此 closure audit 的 12/12
矩阵已闭合。

### 21.5 Frozen identities 与 final full pytest evidence

#### Identity pins

- branch：`codex/authoritative-general-batch-v1-g2-zhugezhan`
- G1 frozen base commit：`678179214a2260c23c95d03740191b1246024bbc`
- G1 tag：`authoritative-general-batch-v1-g1-shamoke-audited`
- G1 tag object：`9eed018b7263c6af41869ee85982db005b2584c1`
- G1 tag peeled commit：`678179214a2260c23c95d03740191b1246024bbc`
- G1 frozen identity：
  `af66c568eb0c4b166139e24349f6e46e2a4735949125a326dde0490b8ade434e`
- G2 current implementation identity / pin：
  `7394e4ca25c85f4e9454bad363c707c7a1487d0b027c014c4d8708c176359c66`
- manifest `scripts/sgs_engine/actions.py` canonical SHA-256：
  `4f35207296fcac5265ff8c928abf70775b3f995da1570dd0179dbf3a5aa6355b`

#### Full pytest history

首次 final full pytest 必须保留为历史失败：

```text
command:
D:\MyGPT\game-analysis-grok-eval\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=D:\MyGPT\basetemp\general-batch-v1-g2-full-20260830-153626-155

exit=1
collected=3195
passed=3029
failed=1
errors=165
skipped=0
xfail=0
xpass=0
deselected=0
```

唯一真实 failure 是
`tests/test_sgs_audit_remediation_2.py::test_manifest_sha256_inventory_is_true_sha256`，
`mismatches=['scripts/sgs_engine/actions.py']`。165 个 errors 是日志捕获文件
被占用导致 pytest 清理 basetemp 时产生的 `PermissionError [WinError 32]`
harness cleanup issue。

修复后 final rerun 的 exact evidence 为：

```text
command:
D:\MyGPT\game-analysis-grok-eval\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=D:\MyGPT\basetemp\general-batch-v1-g2-full-rerun-20260830-172440306

exit=0
collected=3195
passed=3195
failed=0
errors=0
skipped=0
xfail=0
xpass=0
deselected=0
duration=4484.38s (1:14:44)
```

remediation 同步了 manifest canonical SHA-256，并将 TEMP/TMP、basetemp 与
日志目录分离；final rerun 的 PRE / POST gate 均稳定：branch、HEAD、merge-base、
G1 tag peeled commit、computed identity / pin、changed set、staged、unmerged 与
`git diff --check` 均无漂移。full pytest 只证明当前 G2 implementation identity
对应的这次全量测试，不改写 G1 frozen identity，也不把 Batch V1 写成 complete。

### 21.6 Documentation finalization validation

本轮文档收尾只运行轻量验证，没有重跑 full pytest：

- targeted Knowledge / docs / source-integrity / manifest / identity-pin 集：
  `44 passed in 0.53s`，exit `0`；无 failed、errors、skipped、xfail、xpass 或
  deselected。仓库中未发现针对 `POST_B_DEVELOPMENT_STATUS.md` 的独立
  status-doc contract test。
- 实际 source-integrity CLI：`exit=0`，`scanned_file_count=200`、
  `audit_item_count=190`、`defect_count=0`。
- `compileall`：`exit=0`；使用仓库外 pycache，仓库内新增
  `__pycache__` / `.pyc` 数量为 `0`。
- computed implementation identity =
  `7394e4ca25c85f4e9454bad363c707c7a1487d0b027c014c4d8708c176359c66`
  = current pin；文档变更没有改变 implementation identity。
- 最终 `git diff --check = exit 0`；`staged = 0`；`unmerged = 0`；变更集仍为
  既有 18 项加 `docs/CHECKPOINT_MANIFEST.json`，共 19 项，无未知路径。

### 21.7 Final status

```text
G2_ZHUGEZHAN_DOCUMENTATION_FINALIZATION = PASSED
G2_ZHUGEZHAN_CLOSURE_AUDIT = PASSED
G2_ZHUGEZHAN_FINAL_FULL_PYTEST = PASSED
ZHU GEZHAN = GENERAL_COMPLETE
G2_FREEZE_READY = YES
AUTHORITATIVE_GENERAL_BATCH_V1 = IN_PROGRESS
AUTHORITATIVE_GENERAL_BATCH_V1 != COMPLETE
READY_FOR_G2_FREEZE = YES
READY_FOR_G3_IMPLEMENTATION = NO
```

G3 / 王元姬仍未开始，因此 `AUTHORITATIVE_GENERAL_BATCH_V1` 不能写成
`COMPLETE`。本轮没有 commit、tag、push、PR，没有开始 G3、Stage3 或 C8；
当前工作停止在 G2 freeze 前，等待用户授权 freeze。
