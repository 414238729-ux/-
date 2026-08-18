# POST-B 开发状态（POST_B_DEVELOPMENT_STATUS）

> 状态标签：`PRECOMMIT`、`NOT_INDEPENDENTLY_AUDITED`
>
> 本文件是 POST-B 开发轨（deepseek-post-milestone-b-development）的新增状态文档，
> 未登记进 `docs/CHECKPOINT_MANIFEST.json`，也不修改任何已登记文档
> （`docs/CHECKPOINT_MANIFEST.json` 与 `docs/ENGINE_STATUS.md` 是冻结审计目标，
> 其 sha256 表项不得因本文件而失效）。

## 0. POST-B 轨道状态

- `POST_B_C1_MULTIPLAYER_AUTHORITATIVE_FOUNDATION` = `IMPLEMENTED_NOT_INDEPENDENTLY_AUDITED`
- `POST_B_C2_MULTIPLAYER_CARD_SEMANTICS_CLOSURE` = `IMPLEMENTED_NOT_INDEPENDENTLY_AUDITED`
- `POST_B_C3_FORMAL_NO_SKILL_2V2_MODE` = `PRECOMMIT_NOT_INDEPENDENTLY_AUDITED`

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
| 5 | 模式胜负规则（2v2/身份场/最后一人） | C3 已落地正式2v2（`TwoVsTwoOutcomePolicy`）；身份场/最后一人仍失败关闭 |
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

**状态**：`PRECOMMIT_NOT_INDEPENDENTLY_AUDITED`（实现完成，预提交门禁全部
通过；未独立审计，不做 `git commit/push/tag/merge`，由用户最终提交）。
C3 停止后不自动开始斗地主（§3 模式规则保持 Knowledge-only）。

**范围**：正式、失败关闭、严格可回放的 no-skill 2v2 模式层，复用 C1 多人
基础与 C2 全局卡牌语义（38/38、160 张正式牌堆）；不新建第二套引擎
（无 `TwoVsTwoEngine`），只有 mode profile / team 模型 / OutcomePolicy /
模式层钩子 / 可见性配置。不含：Milestone B 修复、身份模式、斗地主、
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

**实现身份**：当前工作树 `implementation_identity()` =
`474ff7fee7304c03c10ed6d2a4c7d207dd6372a75198bd6665083f152cdc475d`
（C123 正交 remediation 1 后随源码更新；冻结 R8 证据 `06c8b2d3…`
仍是历史证据，未被改写）。状态
`IMPLEMENTED_PENDING_INDEPENDENT_REAUDIT`，不得称为 independently
audited。

**C123 正交 remediation 1**（F-003～F-006；状态
`IMPLEMENTED_PENDING_INDEPENDENT_REAUDIT`，不是 CLOSED，不是
AUDIT_PASSED）：

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

**formal duel 防回归**：seed 0 → p2/388/43、seed 7 → p2/162/17
（与 R5/R8 记录一致；全量套件覆盖）。

**遗留**：斗地主/身份场/最后一人胜负策略、武将技能、改判、AI、Web、
正式胜率阶段仍不在本轨；`multi_player_production_proven` 保持 false。
