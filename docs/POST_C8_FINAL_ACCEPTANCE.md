# POST-C8 最终验收与冻结门禁

当前实现的测试与最终独立审查均已通过。单一里程碑commit、annotated tag与远程核验按用户明确授权执行；Git结果在commit产生后记录于本机 `docs/post_c8_evidence/final_acceptance_01/FINAL_GIT_VERIFICATION.json`。只有远程分支/tag peel与实际commit一致才宣称 `AUDITED_AND_FROZEN`，本文件不预填尚未产生的commit SHA。

## 已完成的验收

```text
PLAYABLE_RUNTIME_API_V1 = PASSED
ALL_HUMAN_RUNTIME = PASSED
HUMAN_VS_AI_RUNTIME = PASSED
AI_VS_AI_RUNTIME = PASSED
PRODUCTION_HEURISTIC_AI_V1 = PASSED
MULTIPROCESS_WINRATE_SIMULATOR_V1 = PASSED
PRODUCTION_ACTION_PATH = PRESERVED
PRIVATE_INFORMATION_BOUNDARY = PASSED
LONG_TESTS = PASSED
POST_C8_FINAL_INDEPENDENT_AUDIT = PASSED
ALLOW_POST_C8_FINAL_COMMIT_AND_PUSH = YES
```

- 第二轮fresh核验：4863 collected，4639 passed，224 skipped，0 failed/errors，exit0；12组原配置，48个逐局single/4worker语义、public-information与trace哈希配对无mismatch，原9失败seed均自然终局。详情见 [原件验真摘要](POST_C8_LONG_TEST_ROUND2_VERIFICATION.json)。
- Grok实际调用PID **63536**，exit **0**，耗时 **479.179秒**。审查使用完整相关文件副本、实际只读工具核查20项；前后源码/测试/规则及审查输入文件均一致。
- 源码包SHA256：`eede731b076384ab6fc50d83d1cbec3fd63766948c50747ec90ebd5d75420825`。当前引擎identity：`5083c90d2f6c4913704edbb88161706cec35d136e8d08fe2637d0d832ce38d18`。固定C8 identity与原tag保持不变。
- 审查输入清单SHA256：`e9e37492ca16e66e6759b49499336ad460cc0622e11b33b4cf6651141e5c28be`；提示SHA256：`fea8e47f31741f6af7b0813015e189fe2024ab1cb337f66e3b8e0c9809e31c65`。
- Grok公开审查正文SHA256：`40d3b7372cc002f387c84a30e1d16ae2e5d5ecc28d4eff3e9c18e689010407b9`；流式原始日志SHA256：`dbe332e2c773c5f43b963f4e7124ea5fcf7c662986befad6438f8b1e9191d8ca`。原件只保留本机 `docs/post_c8_evidence/final_acceptance_01/grok_final_01`，不上传原始日志或工具返回内容。下方仅保存公开审查结论正文，不含思考过程。
- 审查未提出生产语义修复。README和失败分类开头的旧PENDING状态已更正；旧handoff作为第二轮执行前证据保持原SHA。未修改受审源码、测试或knowledge规则，不重新运行长测。

## 支持范围与限制

模式：duel、2v2、斗地主、五人身份、普通八人身份、八人立储/择途变体。支持ALL_HUMAN、HUMAN_VS_AI任意有效混合座位、AI_VS_AI和交互CLI。

完整生产武将仅沙摩柯、诸葛瞻、王元姬；soldier仅为显式无技能测试配置。其余仅规则/策略文本的武将（包括鲍信、许攸等）不能完整参战，完整拒绝清单及真实启动命令见 [当前报告](POST_C8_PLAYABLE_REPORT.md)。

AI V1是启发式AI，非最优AI。模拟胜率仅表示当前规则、对手分布、配置及AI策略下的结果，非武将绝对强度或真人胜率。UI、LAN、独立launcher、语音、动画及新增武将不属于本阶段。2v2合法队友共享与斗地主公共无懈知识/公开YES-NO问答边界分别验收；不将旧C8结论扩张到所有武将。

## 提交和发布约束

仅 [最终commit清单](POST_C8_FINAL_COMMIT_MANIFEST.json) 的50项正式文件入库；本机证据目录、repo-external长测/审计原件、大日志、basetemp和凭据全部排除并原地保留。没有来源不明文件被自动加入。

唯一remote：`github` → `https://github.com/414238729-ux/-.git`；唯一分支：`codex/post-c8-playable-runtime-ai-parallel-v1`；唯一新annotated tag：`post-c8-playable-runtime-ai-parallel-v1-audited`。禁止force push、批量tags、覆盖旧C8引用。提交用命令级`core.autocrlf=false`保留实际审查字节；每个staged blob核对SHA256后才commit。恢复精确快照也应关闭自动行尾转换。

审查、运行身份绑定原始文件字节；Git commit包含本报告，因此本报告不能自包含自身commit SHA。最终commit、tag object和remote peel由真实Git读取后写入上述本机核验记录，并在最终交付消息提供。

## Grok公开审查正文

以下为本次返回的结论正文；其中提到的两处旧状态文字已按上文更正，历史handoff保持原件。

独立只读审查已完成。结论依据当前源码、测试、规则与第二轮原件，不以主模型自述为准。

未证实的生产语义缺陷：无。范围外项（其余武将、最优 AI、UI/LAN、官方将池、旧 C8 自然对局重跑）已排除，不当作本阶段通过声明。

README 第 9 行仍写「新功能长测仍待执行」，与 `POST_C8_PLAYABLE_REPORT.md` / 第二轮原件不一致；权威状态以报告与 `POST_C8_LONG_TEST_ROUND2_VERIFICATION.json` 为准，不构成引擎语义否决。

---

## 门禁

POST_C8_FINAL_INDEPENDENT_AUDIT = PASSED  
PRODUCTION_ACTION_PATH = PASSED  
PRIVATE_INFORMATION_BOUNDARY = PASSED  
AI_STRATEGY_WIRING = PASSED  
MODE_RUNTIME_INTEGRATION = PASSED  
PARALLEL_SIMULATION_DETERMINISM = PASSED  
HISTORICAL_FAILURE_PRESERVATION = PASSED  
ALLOW_POST_C8_FINAL_COMMIT_AND_PUSH = YES

---

## 证据总览（第二轮权威）

`evidence/round2/pytest.xml` 的 testsuite 头：`tests="4863" failures="0" errors="0" skipped="224" time="6577.482"`。4863−224=4639，与 `evidence/round2/pytest.json` 的 `4639 passed / 224 skipped`、PID 60024、exit 0 一致。相对第一轮 4847 项，新增恰好 16 项（`test_post_c8_round1_remediation.py` 参数化合计 16）。

`evidence/round2/execution_summary.json`：13 条正式命令均 `EXITED` 且 `exit_code: 0`，无官方 rerun。`source_sha256=eede731b076384ab6fc50d83d1cbec3fd63766948c50747ec90ebd5d75420825`，与本包及 `after.json` 内 `source_after_sha256` 一致。12 组 `*_result.json` 均为 `"semantic_equal": true`；结果中未见 `"status": "ERROR"` / `"ABORTED"`。

原 9 个失败 seed 在第二轮原件中均为自然终局（核对 `game_id`）：

| 原失败局 | 原件位置 | 现状 |
|---|---|---|
| 2v2_candidates seed1 | `2v2_candidates_result.json` 451 步 | DRAW（牌堆耗尽） |
| duel_candidates seed1 | `duel_candidates_result.json` 785 步 | WIN |
| identity5_candidates seed1 | `identity5_candidates_result.json` 1668 步 | WIN |
| identity8_heir_candidates seed2 | `identity8_heir_candidates_result.json` 2402 步 | WIN |
| identity8_heir_candidates seed3 | 同文件 1012 步 | WIN |
| identity8_heir_fixed seed0–3 | `identity8_heir_fixed_result.json` 915/574/2140/635 步 | 全部 WIN |

斗地主问答：fixed 单侧 5+2=7，candidates 2+2=4（question/answer/expired 成对），与报告一致。12 组 config SHA 与第一轮 `ORIGINAL_SHA256.json` 相同，结果 SHA 不同，未混同旧 FAIL。

---

## 20 项核查

### (1) ALL_HUMAN 运行层 — PASSED

位置：`playable_config.py` `CONTROL_MODES` / `human_player_ids`；`playable_runtime.py` `_Session` 对人工座位装 `HumanController`，`advance_until_human_or_terminal` 遇人停 `HUMAN`/`HUMAN_ANSWER`；`sgs_playable.py` `run_interactive`；样例 `examples/post_c8/all_human.json`。

测试：`test_post_c8_playable_runtime.py::test_all_human_stops_and_no_omniscient_default`、`test_post_c8_playable_cli.py` 实际子进程 `play --control ALL_HUMAN` 后 `q` 退出 2 且 stdout 含 `ABORTED`。

全手控全知仅 `omniscient_debug=true` 且 `control=ALL_HUMAN`；默认拒绝。

### (2) HUMAN_VS_AI — PASSED

配置要求人工座位非空且非全员。`advance_until_human_or_terminal` 按 `current_actor_id`（含响应/救援/技能/寒冰）路由。测试 `test_human_response_and_mixed_seats_route_current_actor`：p1 AI 出杀后停在人工 p2 响应，p1 无 decision。样例 `human_vs_ai.json` 为斗地主交互叫价。CLI `--human-seats` 解析物理座位。

### (3) AI_VS_AI — PASSED

`human_player_ids` 为空，全座 `ProductionAIController`，每座独立 `derive_seed(ai_seed, "seat:pN")`。CLI 在 `YIELD` 上继续直到终局。`SimulationConfig` 强制 `AI_VS_AI` 且禁止全知。`test_each_mode_short_real_production_ai_path` 六模式各推进 28 步。第二轮 12 组均为 `AI_VS_AI` 自然终局。

### (4) Production Heuristic AI V1 — PASSED

`production_ai.py`：只消费 `player-view-v1` 与本座事件；对全部合法候选评分，未知 operation/schema/`AISchemaError` 定位失败，不吞异常选第一项。同分用权威 `ordinal` + 独立 AI 随机流，不按会话签名/牌引用排序（`test_new_signatures_do_not_change_tied_semantic_choice`）。贯石斧/寒冰按实际 operation 评分。策略含 V2.2/card/team/focus/chain/general 及公开问答消费。明确启发式，非最优；胜率声明绑定配置与对手分布。

### (5) signed legal action path — PASSED

引擎：`actions.py` `enumerate_legal_actions` → HMAC/`act_` SHA256 绑定 state/context/adapter/action；`validate_action` 重新枚举；`apply_action` 守恒。运行层：`_prepare` 再包会话 HMAC（sid、decision_id、actor、ordinal、engine `action_id`）；提交核对座位、代次、pending 问答、token。接受后 `generation+=1`，无状态 revision 的 select 也会使旧决策失效（`test_multiple_choice_advances_decision_without_state_revision`）。重复提交回执、并发只提交一次、跨会话/错座拒绝。提交成功后投影/统计失败仍保存回执并 `ERROR` 停局（`test_committed_receipt_survives_projection_error_without_double_apply`、`test_post_commit_statistics_exception_keeps_receipt_and_closes_decision`）。开局叫价/选将/手气同样走签名与失败回滚。`submit_signal` 永久拒绝。问答走独立 `CooperationAdapter`，`apply_action` 不改 `GameState`。

### (6) player-view / 私有信息边界 — PASSED

`playable_view.py` 白名单投影：手牌仅本人或 2v2 队友；身份模式隐藏非主/非己/非死亡揭示；罪论牌顶只给拥有者（`test_real_zuilun_private_choice_and_event_never_share_topdeck_with_teammate`）；立储/择途记忆分座位（`test_heir_private_memory_and_no_hidden_role_in_other_views`）；mode_decision 对非行动者投影为 `resolution` 且不暴露私有行动者。牌引用 HMAC 不透明。视图不含 seed、密钥、实体 instance_id、牌堆序。AI `observe`/`choose` 只拿本座过滤事件。`test_hidden_hand_noninterference_with_equal_public_qa_and_observations` 证明轮询/再评分不刷新隐藏资格。

### (7) 2v2 / 斗地主 / 身份模式接线 — PASSED

`playable_game.assemble_production_game`：2v2 固定 1+4/2+3、3/4/4/5 手牌、飞扬/胜负 policy；斗地主叫价或固定地主、体力+1、座位环旋转；identity5/8 正式 profile、主公+1、隐藏身份；identity8_heir 绑 C7 policy；duel 随机先手、不旋转物理座。武将仅 shamoke/zhugezhan/wangyuanji，soldier 显式无技能，未知将报错。`test_each_mode_initializes_complete_generals` 核体力/技能。第二轮六模式 fixed+candidates 均自然 WIN/DRAW。

### (8) 斗地主无懈公共知识 — PASSED

`playable_information.PublicInformation.after_commit`：仅提交后、真实 `trick_response`/`judgment_wuxie`、无技能挂起、合法集含无懈/PASS 时观察。资格来自 `WuxiekejiAdapter.usable_card_ids`（实体无懈，不扫隐藏刷新）。全场同一摘要。PASS 记 `nullification_passed` 且 `consumed=False`，不把 KNOWN_USABLE 改成 NONE。使用一张 `remaining=unknown`，反无懈新层再观察。未知摸/失牌只使该角色失效。`test_real_public_window_pass_and_counter_window`、`test_unknown_gain_invalidates_only_recipient_and_views_do_not_refresh`、五谷公开得无懈 `nullification_public_gain`。规则见 `knowledge/三国杀AI信息规则.md` A 节，标明非官方统一规则。

### (9) 公开 YES/NO 协作问答 — PASSED

`playable_communication.question_offers`：仅斗地主 playing、农民问另一存活农民；模板封闭（保护/救援意愿/桃事实/借刀事实·能力·意愿/罪论同意）。借刀须 `public_known_hand_keys` 已有共同知识。答案 YES/NO/NO_RESPONSE 全场相同，不含手牌/分数/签名。绑定 decision/window/layer，改变后过期。`ProbeBudget` 限制事实/能力每手牌时期一次。鲍信仅 `DistributionPlan` 规则场景，`GameConfig(enabled_generals=("baoxin",))` 拒绝。问答不移动牌、不耗游戏步数（`test_real_protection_public_qa_and_ai_decision` 问答前后 state/runtime/accepted 不变）。

### (10) AI 主动发问 / 回答 / 消费公开回答 — PASSED

`advance_until_human_or_terminal`：AI 先 `choose_question`，否则 `choose`；回答座位 `answer_question`。`current_answer` 只解释匹配命题，NO_RESPONSE 当 UNKNOWN；保护建议不推出杀/闪事实（`test_same_advice_does_not_determine_private_response_cards`）。无懈/救援/借刀/罪论评分分别消费。`test_mixed_ai_ask_stops_for_human_answer_and_ai_answer_has_time_slice`：AI 提问停 `HUMAN_ANSWER`，AI 回答计 `communication_steps` 不计 `advanced`。第二轮斗地主长局真实 question/answer/expired。CLI `a 编号` 路径有回归。

### (11) frozen C8 vs POST-C8 current identity — PASSED

`current_c8_implementation_pin.py`：`df90380d241bc8342956db3d3d68405fbef60d86185dcb078c836e00544370fe`。`current_post_c8_implementation_pin.py`：`5083c90d2f6c4913704edbb88161706cec35d136e8d08fe2637d0d832ce38d18`，并引用冻结 pin，二者不等。`PlayableProductionSession.MODE_ID = post_c8_playable_production_v1`。`conftest.py` + `post_c8_frozen_source.py`：固定 commit `9991abc8091943e7316875734bae2e5967cc6e64`，blob 校验，仅当当前文件归一行尾等于冻结 blob 才保留原包装；测试专用 release 的 harness 拒绝启动 historical 执行。父 pytest 转发真实 setup/call/teardown。`test_frozen_verifier_rejects_current_development_bytes_and_pin_is_separate`：当前树被旧 verifier `AUDITED_HASH_DRIFT` 拒绝。第二轮冻结子进程 PID 60680、exit 0。

### (12) card ownership / continuation — PASSED

`_post_card_semantic_trigger_checkpoint` 登记 `material_ids` 与 `movement_sequence_at_creation`；虚拟材料必须在 PROCESSING。`assert_resolution_invariants` 把 continuation 材料计入 PROCESSING 归属，悬空 fail-closed。`_resume_pending_card_continuation` 校验 phase/dying/actor/target/revision；实体离开预期区仅当 `_spent_continuation_card_was_recycled` 证明 discard→reshuffle→可选 skill draw 链。非法手牌挪位即使改 revision 仍拒绝（`test_spent_card_illegal_move_without_authority_is_not_rebound`）。丈八暂停：材料在 PROCESSING，技能结束后进入 pending_slash（`test_virtual_materials_owned_during_jili_pause_and_finished_once`）。虚拟技能候选补 `VirtualCardReference`，材料已支付不计入技能 cost（`playable_view.action` 对 activate/pass_skill 清空 materials）。

### (13) 寒冰剑多步选择 — PASSED

`apply_hanbing_discard_card` 每次一张；step 绑定 window/state_hash/handle。技能窗口期间枚举优先 `_skill_pending`，旧寒冰签名不可用。技能完成/放弃后 `_resume_hanbing_after_skill_checkpoint` 按最新手牌+装备重签发该 step，空区走原关闭语义，不把 EMPTY_LEGAL_SET 改成 PASS。`test_hanbing_second_choice_refreshes_after_mingzhe_and_rejects_old_choice`：明哲后 digest 变、旧 action fail-closed。第二轮 2v2_candidates seed1 越过原 366 步故障至 451 步 DRAW。

### (14) 罪论 legal-set / apply 一致 — PASSED

枚举：`_enumerate_for_adapter` 在 phase 之前处理 `_skill_pending` / 私有选牌 / 扣血。`resolve_zuilun_activation` 要求 `phase is END` 且 live facts 与 payload 一致。`_c7_maybe_open_mode_decision_checkpoint` 在 skill_pending、card continuation、私有选牌、skill hp loss 未清时直接 return，禁止 MODE_DECISION 抢占。`_c7_after_applied_action` 挂在 `_BatchRuleAdapter.apply_action` 每次正式 apply 之后。第二轮 identity8_heir_fixed 原 4 个罪论故障 seed 全部自然 WIN。`test_c7_zuilun_legal_set_and_apply_have_same_phase` 为短路径存在性回归，强度低于上述代码约束与长局。

### (15) C7 spy conversion — PASSED

`mode_identity_heir.py` 四处 `getattr` 改为现存 core：`_c7_apply_spy_conversion`、`_c7_open_succession_window`、`_c7_apply_lose_hp`、`_c7_open_ambitionist_reward`，无旧 façade 别名。`test_playable_c7_conversion_uses_shared_engine_hook_at_turn_boundary` 忠臣/野心家均在 `end_turn` 边界转换并出 `identity_revealed`。第二轮 heir_candidates seed3 仍 1012 步 WIN（与修复后诊断一致，现为自然终局）。

### (16) single / multiworker determinism — PASSED

`playable_simulator.py`：Windows `spawn`；worker 启动核源码 SHA；`game_id` 由局配置+seed+occurrence 构成，与 worker 数/完成序无关；`semantic_results` 去掉 PID/耗时。12 组 compare-workers 全部 `semantic_equal: true`。短测 `test_windows_spawn_same_game_semantics_and_natural_result`、`test_doudizhu_public_observations_and_questions_match_spawn_workers`、worker 初始化失败覆盖每个 job。

### (17) 胜率统计口径 — PASSED

`aggregate_results`：分母=WIN+DRAW，排除 ERROR/ABORTED；team 每局每队一次；个人获胜出场独立。斗地主 L/F/`S_raw=(L+F)/2`，无样本为 null，不调 `S_selectable`。`identity8` 才有 `spy_statistics`（胜 3 分否则主内单挑 1 分互斥），heir 不加。`test_team_count_role_denominators_and_doudizhu_formula`、`test_spy_reward_mutually_exclusive_and_not_loaded_for_variant`。第二轮结果含 claim 原文。identity8_fixed 原件含 `spy_statistics`。

### (18) 第一轮失败历史保留 — PASSED

`evidence/round1/pytest.json`：exit 1，`25 failed / 4529 passed / 224 skipped / 69 errors`，PID 53644。`ORIGINAL_SHA256.json` 54 项；config SHA 与第二轮相同，result SHA 不同。`pytest_failure_mapping.json` 保留原 ERROR/FAIL 与 94 项 mapping。分类文档保留原 nodeid。本包 round2 结果未覆盖 round1 原件。首次建目录 permission denial 按交接说明为未启动前置失败，不计 seed rerun。

### (19) 第二轮真实长测 authority — PASSED

权威原件在本包 `evidence/round2/`，不是主模型叙述。13 命令一次执行、exit 0、`fixes_applied: false`。pytest 头与 json 一致。before/after 中 `production_batch.py` 等 SHA 与 `AUDIT_INPUT_MANIFEST.json` / 当前审查文件一致（`cf88570501a44359742da13f6c41fd3db744b5552cc0fb0378497b419c360679` 等）。`launcher_exit.json` exit 0。48 对由核验摘要记录 mismatch=0，且 12 份 result 均 `semantic_equal: true`。原 9 seed 已在原件核对。跳过 224 项不表述为通过。

### (20) freeze / commit readiness — PASSED（可提交）

`POST_C8_FINAL_COMMIT_MANIFEST.json`：base `9991abc...`，remote 仅 `https://github.com/414238729-ux/-.git`，分支 `codex/post-c8-playable-runtime-ai-parallel-v1`，拟 annotated tag `post-c8-playable-runtime-ai-parallel-v1-audited`。`files` 49 项且 `manifest_self_excluded`；排除 `docs/post_c8_evidence/**`、仓库外长日志、basetemp；`unexplained_files: []`。`.gitignore` 忽略证据目录。`POST_C8_FINAL_ACCEPTANCE.md` 为占位，通过后只填审查/Git 元数据，源/测试/规则不改。用户已授权，本审查 ALLOW=YES。

残留文档：`README.md` 第 9 行「新功能长测仍待执行」过时；`FULL_PYTEST_FAILURE_CLASSIFICATION.md` 开头仍写第二轮 PENDING（历史分类正文）；`POST_C8_LONG_TEST_HANDOFF.md` 作为第二轮执行前交接保留 PENDING 字样。权威结论以 `POST_C8_PLAYABLE_REPORT.md` 末节与 ROUND2 核验为准。不因此否决提交。

---

## 明确排除（不记 FAIL）

- 完整生产武将仅三名；鲍信无整将入口；其余文档武将拒绝静默降级。
- 六模式入口≠客户端全部规则/全部武将完成。
- AI 为启发式 V1，非最优；结果是固定 AI/配置模拟胜率，非武将绝对强度或真人胜率。
- UI、LAN、独立 launcher、语音动画、新将、V2.4 pending 不在本阶段。
- 旧 C8 tag/proof/verifier/自然对局未改写、未重跑。
- 规则来自仓库用户确认资料，不宣传官方统一规则。
- 2v2 合法共享队友手牌保持；斗地主不共享手牌。

---

**结论：** 当前源码包 SHA256=`eede731b076384ab6fc50d83d1cbec3fd63766948c50747ec90ebd5d75420825` 支持 POST-C8 可玩运行层、签名动作路径、信息边界、启发式 AI、六模式接线、并行确定性与统计口径。第一轮 FAIL 原件保留；第二轮长测原件构成通过权威。允许按 49 文件清单做唯一新 commit 与 annotated tag，并推送到已声明的唯一 GitHub remote。通过后只应填写验收/Git 元数据，不改源、测试与规则。