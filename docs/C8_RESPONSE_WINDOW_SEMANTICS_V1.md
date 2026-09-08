# C8 响应窗口可选发动语义

状态：分析约定；本文件记录本仓库冻结实现语义，不是官方规则原文。

E 是私有 operation 到公开 family 的唯一分类来源。底层 `ActionType.PASS`
不等于放弃。`response_public_action_family_v1` 同时校验正式 phase、operation、
ActionType 和 window kind；未登记的新阶段/操作失败关闭。G2 只核验 E 投影，
G1 的公开候选只含 ordinal/family，不接收 operation、牌或私有 payload。

| 语义 | E 既有 family | G2 typed family |
|---|---|---|
| OPTIONAL_ACTIVATE_IN_RESPONSE_WINDOW | public_choice | ACTIVATE |
| DECLINE_RESPONSE | pass_response | PASS |
| 正常响应 | mandatory_action | RESPOND |
| 救援 / 放弃救援 | mandatory_action / pass_rescue | RESCUE / PASS |

生产源码核验集合如下。来源是 `production_batch.py` 的 `legal_actions`、
各 response apply 分支及响应枚举，以及 `production_cards.py` 的
`ArmorCardAdapter._enumerate_bagua_activate`，不是按阶段名称推测。

| phase | 响应/进展操作 | 唯一放弃操作 | 八卦 |
|---|---|---|---|
| slash_response | play_dodge | pass_slash_response | activate_bagua |
| wanjian_response | play_jink_for_wanjian | pass_wanjian_jink | activate_bagua |
| nanman_response | play_slash_for_nanman | pass_nanman_slash | N/A：要求杀 |
| duel_response | play_slash_for_duel | pass_duel_slash | N/A：要求杀 |
| trick_response | use_wuxie | pass_trick_response | N/A：无懈响应 |
| judgment_wuxie | use_wuxie | pass_judgment_wuxie | N/A：无懈响应 |
| fire_attack_discard | discard_same_suit_for_fire_attack | pass_fire_attack_discard | N/A：同花色弃牌 |
| dying_rescue | rescue_with_peach / rescue_with_wine | pass_rescue | N/A：救援 |

八卦只在前两行被生产适配器枚举；测试核对这个源码集合与 E 登记一致。
今后新增 response phase/operation 必须显式登记并测试，不能沿用 PASS 推断。
八卦激活不是已成功的闪：红色判定后，杀响应虚拟闪是使用/CARD_USED，
万箭响应虚拟闪是打出/CARD_PLAYED；黑色判定没有虚拟闪，重新枚举剩余响应。
coarse family 不改变这些 C6 事件语义。

seed1 step943 的精确等价集合为
`play_jink_for_wanjian, activate_bagua, pass_wanjian_jink`。
定向隔离样例从 fresh step0 初始化，只以签名合法动作通过 B/E 到达窗口；
timeout 唯一选择 ordinal2 的真实放弃动作，C6 accepted +1 后 POST_OBSERVE/CLOSE。
不恢复原失败会话，不伪装原 turn45/p8/943；样例不具备正式结果资格。
仅激活而无放弃、两项真正放弃都保持 TIMEOUT_UNRESOLVED。
current E 的一提交步后 close 约束保持；无 action、unresolved child 和伪造完成不能 close。

本修复保留 driver material3 和 profile1，仅按实际源码证书依赖刷新 identity。
新启动授权字符串为 `C8G_FG_001_SEED1_NATURAL_FASTPATH_V2`；其元数据必须
独立 pin 当前 release、fresh attempt-002、解释器和 profile。准备/审核不是执行。
attempt-001 永久保留 HISTORICAL_FAILED_AT_943；seed0 只按历史执行域及显式
compatibility/adoption 绑定保存，不重跑 natural/inner/timed。
