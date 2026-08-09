# 三国杀正式引擎状态

> 更新日期：2026-08-07
> 状态：已有权威核心 foundation、测试专用最小单挑纵向切片、正式160张牌堆上六种基本牌的生产适配器批次、最小普通锦囊垂直切片（【无中生有】、【无懈可击】），以及目标区域选牌批次（【过河拆桥】6张、【顺手牵羊】5张接入生产适配器），以及伤害型普通锦囊批次（【决斗】3张、【火攻】3张接入生产适配器，2026-08-03已通过独立只读审计AUDIT_PASSED_WITH_NONBLOCKING_ISSUES），以及群体普通锦囊批次（【南蛮入侵】3张、【万箭齐发】1张、【桃园结义】1张接入生产适配器并建立逐目标结算框架，已由用户在外部PowerShell提交（实现提交哈希 `5f2fbf27b7041bbf3010636de37306eea5da6256`），2026-08-03 完成独立只读审计：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，最终独立复审结论 AUDIT_PASSED），以及剩余普通锦囊批次（【五谷丰登】2张完整生产语义＋【铁索连环】6张牌本体接入生产适配器，已由用户在外部PowerShell提交，实现提交哈希 `20cb1b1f766529a88aa5f3346a4761b77eca66b7`，提交信息 feat: implement wugu and tiesuo card-body slice；2026-08-04 完成独立审计：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，最终独立复审结论 AUDIT_PASSED，见 2.9 节），以及属性伤害传导生产基础设施（CP-04J，已由用户在外部PowerShell提交实现提交 `c094bff5dab127917e8d0b9a2d3422e3ab736783`，审计残项关闭提交 `68e419b79e379184c1f1cc7ad650039771530f89`；2026-08-04 完成独立审计：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，最终独立复审结论 AUDIT_PASSED，见 2.10 节），以及【借刀杀人】＋11种武器牌本体批次（CP-04K：普通锦囊最后一张【借刀杀人】完整双人生产语义、11种／12张武器牌本体主动装备与同槽替换、按角色出杀计数、武器专属技能集中式失败关闭门禁；已由用户在外部PowerShell提交，最终实现提交 `75c596b12f34a6222d972b2190148386bb670653`（feat: implement borrowed sword and weapon card-body system），amend 替代旧提交 `7456377f...`；首次独立只读审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES（N1-N3 已由审计残项关闭提交 `79acc6ff514af4900acfe87507374fc8d696ec97` 正式关闭），最终独立复审结论 AUDIT_PASSED；里程碑标签计划为 `milestone-b2-borrowed-sword-weapon-system-audited`）；以及三种延时锦囊＋判定与阶段基础设施批次（CP-04L：【乐不思蜀】3张、【兵粮寸断】2张、【闪电】2张接入生产适配器；正式回合阶段 PREPARE／JUDGMENT／DRAW／PLAY／END、判定区进入序号与动态LIFO判定队列、判定前【无懈可击】链、判定牌生命周期、乐不思蜀／兵粮寸断阶段跳过、闪电无来源雷属性伤害与转移／回置、死亡与胜利清理、判定彻底不足原子失败关闭、player_visible 双视角手牌隐私与牌堆顺序脱敏；已由用户在外部PowerShell提交实现（实现提交哈希 `35c06bd50a431a62e7c3ad01d10384bf6884c403`，提交信息 feat: implement delayed tricks and judgment infrastructure）；2026-08-05 第一次独立审计结论 AUDIT_FAILED_BLOCKING_ISSUES（唯一阻塞项 B1：player_visible 未脱敏 reshuffle 事件），修复提交 `96f536e1f392fd97faf61518a849a0d515b6a82e`（fix: close delayed trick audit gaps）；2026-08-06 第二次最终复审结论 AUDIT_FAILED_BLOCKING_ISSUES：新发现 B1-a（动作负载 state_hash 等权威状态摘要旁路）、B1-b（legal_actions/chosen_action 泄露行动者完整手牌）、B1-c（tiesuo_recast 等隐藏摸牌未统一脱敏）三个 player_visible 阻塞问题与两个复审观察项（N5 篡改测试结构、judgment_entry_indices 陈旧残留）；最终修复提交 `eeeaf558cdaeeea0eb90456f907f83dce52286f3`（fix: harden player-visible replay privacy）；2026-08-06 Grok 网页端独立静态审计 STATIC_AUDIT_PASSED（经 GitHub 连接器读取精确目标提交，未亲自运行 pytest／Git／本地虚拟环境；1733 passed 等运行结果来自本地修复会话）；文档收口提交 `ba64b750fabd99f2bfc93697cea83e1272216d02`（docs: finalize delayed trick and judgment audit milestone）；最终审计结论 AUDIT_PASSED（status=audited、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、milestone_tag=已建立标签 `milestone-b2-delayed-trick-judgment-infrastructure-audited`（本地与 GitHub 远程标签均已验证存在；HISTORICAL/AS-OF：当时标签状态记录为指向 ba64b750fabd99f2bfc93697cea83e1272216d02，随后用户将标签移动到承载最终仓库状态记录的提交；CURRENT LIVE REF：当前Git标签解析为 fc3df95202b23dccfd9abf5e476485a224d6fc2c，当前标签目标以Git标签解析结果为准）、worktree_commit_pending=false），见 2.12 节），以及四种防具＋伤害修正／防止基础设施批次（CP-04M：【八卦阵】2张、【仁王盾】1张、【藤甲】2张、【白银狮子】1张接入生产适配器；统一防具伤害修正管线、仁王盾黑杀无效、藤甲免疫与火属性伤害+1、八卦阵响应窗口内可选判定与虚拟闪、白银狮子统一离区恢复、统一无视防具接口；实现提交 29ab73e006408e1e1582a300801e7aa6e04bd9c4（feat: implement armor and damage prevention infrastructure）已由用户在外部PowerShell提交，2026-08-06 完成独立静态审计（STATIC_AUDIT_PASSED），见 2.13 节），以及正式坐骑＋距离／攻击范围基础设施批次（CP-04N：【攻击坐骑（-1坐骑）】3张、【防御坐骑（+1坐骑）】4张接入生产适配器；统一有效距离模型、武器攻击范围与有效距离分离、杀／借刀／顺手／兵粮距离接入、坐骑装备与同栏位替换、正式160张实体牌全部注册；实现提交 fd7d69f53e9827877b6a29d67c067012ead6a7af（feat: implement mounts and distance infrastructure）已由用户在外部PowerShell提交，2026-08-07 完成独立静态审计（STATIC_AUDIT_PASSED），见 2.14 节）；以及正式弃牌阶段＋权威回合循环基础设施批次（CP-04O：正式阶段流收敛为 PREPARE／JUDGMENT／DRAW／PLAY／DISCARD／END 单一权威循环；正式弃牌阶段（手牌上限默认等于当前体力值、装备区与判定区不计入手牌数、超限时UI逐张选择待弃手牌但确认前不产生正式弃牌状态转换、确认后所选牌作为一次批量弃置统一离开手牌、接受一次性提交动作且不接受负载伪造excess／hand_limit、旧动作失败关闭）；延时锦囊阶段跳过接入回合推进（乐不思蜀跳过出牌阶段、兵粮寸断跳过摸牌阶段均真实影响状态机）；回合结束清理回合级临时状态、按座次转交下一存活角色、胜利后不再启动下一回合；实现提交 b1afb1a613a45c630ae1e42975d276d62915e76d（feat: implement turn cycle and discard infrastructure）与检查点文档提交 7aacd06cdfcf1725307061a3f5c03c233a2199f7（docs: record turn cycle and discard checkpoint）均已由用户在外部PowerShell提交，2026-08-07 完成独立静态审计（STATIC_AUDIT_PASSED）；最终审计文档提交 17246077776ef8a8c7f957706d60fd91e2c0a440（docs: finalize turn cycle and discard audit milestone）已由用户在外部PowerShell提交；里程碑标签 milestone-b2-turn-cycle-discard-infrastructure-audited 已实际建立并推送（见 2.15 节）；以及正式武器技能完整化批次（CP-04P：11种武器中8种／9张完成正式生产语义——诸葛连弩无限出杀、青釭剑令目标防具无效生命周期（armor invalid；代码历史字段 ignore_armor。QINGGANG_LIFECYCLE_CONFIRMED，2026-08-07 用户移动版实测确认：起点=杀指定一个目标后的武器技能实际生效时点、终点A=闪结算完成、终点B=本次伤害结算完成，清除后防具恢复）、寒冰剑伤害前防止＋逐张弃置目标手牌/装备至多2张（2026-08-08 用户移动版实测确认：一张一张弃置、两次连续正式弃置步骤，不是同时选择同时弃置）、古锭刀“造成伤害时”判定伤害+1（游戏内文本与用户实测确认：伤害时读取目标当前手牌，不使用指定目标时快照）、青龙偃月刀被闪后继续使用一张杀（追杀不消耗普通出牌阶段【杀】次数额度，USER_CONFIRMED_MOBILE_RULE）、贯石斧弃2张强制命中（两张牌一起选择并一起弃置的发动代价；贯石斧自身不能作为代价，USER_CONFIRMED_MOBILE_RULE）、朱雀羽扇普通杀转火杀（含被借刀杀人要求使用杀时同样可转换）、麒麟弓在本次伤害真正结算（HP扣减/DAMAGE）之前弃坐骑/放弃（USER_CONFIRMED_MOBILE_RULE，2026-08-08用户移动版确认；坐骑移动/失牌事件先于DAMAGE）；雌雄双股剑（性别数据RULE_GAP）、丈八蛇矛（实现已完成但subcard生命周期时点存在规则缺口VIRTUAL_CARD_SUBCARD_LIFECYCLE_RULE_GAP，暂计PARTIAL不计COMPLETE）、方天画戟（多人多目标语义未进入生产实现）2种保持PARTIAL并按集中式门禁失败关闭；雌雄双股剑保持PARTIAL＋DATA_MODEL_GAP（CHARACTER_GENDER_METADATA_NOT_AVAILABLE，规则本身已知）；完整工作树实现与70项武器专项＋7项借刀朱雀专项已在本轮完成，完整 pytest 1974 passed；实现提交 f0a50ce9ace71c5bf0a22540fbdca9e03aa918b3（feat: implement verified production weapon skills，父提交 ef340c42e180ab14832b291bc0fc83f449a771a6）与检查点文档提交 c30b26880b947217d64304ce430d32030b42941e（docs: record weapon skill completion checkpoint）均已由用户在外部PowerShell提交；2026-08-08 完成独立静态审计（CP_04P_INDEPENDENT_STATIC_AUDIT）：Grok 网页端经 GitHub 连接器对审计分支 deepseek-audit-weapon-skill-completion 上的精确目标 c30b26880b947217d64304ce430d32030b42941e 进行只读静态审计（implementation f0a50ce9ace71c5bf0a22540fbdca9e03aa918b3，baseline ef340c42e180ab14832b291bc0fc83f449a771a6）；16个强制审计章节全部PASSED，BLOCKING_FINDINGS=NONE、NONBLOCKING_FINDINGS=NONE；NOT_READ=none of the mandatory implementation/docs files；PARTIAL_READ=仅production_batch.py非武器外围部分以及非关键docs全文（武器相关changed hunks、调用链、pending、gate及关键状态均已完整追踪，不构成关键审计缺口）；独立复算 registered=38种/160张、complete semantics=35种/157张、complete weapons=8种/9张、partial weapons=3种/3张、unregistered=0种/0张；PARTIAL分类均被审计确认合理且真正fail-closed。Grok未亲自执行pytest、compileall或本地虚拟环境；本地运行证据（pytest 1953 passed 等）来自本地实现会话，两类证据不得混写。检查点状态为 audited、independent_audit_done=true、audit_conclusion=STATIC_AUDIT_PASSED、milestone_tag=milestone-b2-weapon-skills-audited（已实际建立并指向最终稳定基线 398ea58c9006ee9141ea1acfba35f6d9c497be48）、worktree_commit_pending=false（审计记录文档提交 08d78cb6fed86360d647728a6f70422326918ff2 已回填）（见 2.16 节）；以及整仓敌对式总审计定向修复批次（WHOLE_REPO_AUDIT_REMEDIATION_1：原总审计 CP04L_TO_CP04P_WHOLE_REPO_ADVERSARIAL_AUDIT 结论 WHOLE_REPO_AUDIT_FAILED（G-001 MAJOR 死亡座次距离与目标合法性泄漏、G-002 MAJOR 完整规则来源未独立闭合、G-003 MINOR 丈八PARTIAL枚举split-brain、G-004 MINOR 最终文档与Git状态漂移、G-005 MINOR 历史规则文本未完全传播、N-001 麒麟弓濒死顺序待规则确认[后升级为实际修复项]）；修复实现提交 f1731b95199165a3449f1a0ce84d9facfc1b41c5（fix: remediate whole-repo audit findings，父提交 398ea58c9006ee9141ea1acfba35f6d9c497be48）已由用户在外部PowerShell提交；G-001存活角色环距离、麒麟弓先于HP扣减/DAMAGE、丈八统一fail-closed、G-004/G-005 live清理已在本批完成（完整 pytest 1966 passed 为 implementation/regression evidence，不是新的独立审计结论）；检查点状态 committed_pending_audit、NOT_AUDITED_YET（HISTORICAL/AS-OF：R1文档回填时）、worktree_commit_pending=true；CURRENT：remediation-1 targeted independent re-audit 结论 REMEDIATION_REAUDIT_FAILED（R1 未获得通过的独立审计）；以及整仓敌对式总审计定向修复第二轮（WHOLE_REPO_AUDIT_REMEDIATION_2：G-001 dead-self 统一fail-closed、R1-NEW-001 Qilin resolved final amount 跨pending保存、R1-NEW-002 Qinggang cleanup 绑定真正damage completion、G-003丈八fail-closed保持、G-004/G-005清理、【杀】family通则与8项游戏内正式文本source同步、G-002本地source gap清零[pending independent re-audit]；实现提交 e63b40ac1690e03315fd3e0734d5723fb80d5182（fix: complete second whole-repo audit remediation，父提交 4aafd95...）已由用户在外部PowerShell提交；完整 pytest 1974 passed 为 implementation/regression evidence，不是独立审计结论；检查点状态 committed_pending_audit、worktree_commit_pending=true（HISTORICAL/AS-OF：R2文档回填时 NOT_AUDITED_YET；CURRENT：remediation-2 targeted re-audit=REMEDIATION_2_REAUDIT_FAILED，原因是当时G-004/G-005仍OPEN）；以及整仓敌对式总审计定向修复第三轮/最小收尾（WHOLE_REPO_AUDIT_REMEDIATION_3：G-004 CP-04L ba64历史引用全部分层为HISTORICAL/AS-OF且current live ref统一fc3df952...、G-005 stale清理、R2-NEW-001 annotation统一tuple[str,str]|None；实现提交 9c63496e7f34430d8aff3c23e9afc5b5c4482557（fix: close remaining whole-repo audit findings，父提交 3121a300...）已由用户在外部PowerShell提交；完整 pytest 1974 passed 为 implementation/regression evidence，不是独立审计结论；检查点状态 committed_pending_audit、worktree_commit_pending=true（HISTORICAL/AS-OF：R3文档回填时 NOT_AUDITED_YET；CURRENT：remediation-3 targeted re-audit=REMEDIATION_3_REAUDIT_FAILED，原因是当时G-004仍有§8漏项与R3-NEW-001 G-002矛盾；R3 re-audit已确认G-005/R2-NEW-001=CLOSED、其余六项NO_REGRESSION）；以及整仓敌对式总审计定向修复第四轮/docs-only治理收尾（WHOLE_REPO_AUDIT_REMEDIATION_4：G-004 §8 CP-04L tag-target漏项修正、R3-NEW-001 G-002分层；实现提交 5eb367599e9d7deb26220cfff8b81144d0d88eff（docs: close remaining whole-repo audit governance findings，父提交 6bef086...）已由用户在外部PowerShell提交；docs-only、无runtime/gameplay修改；检查点状态 committed_pending_audit、NOT_AUDITED_YET、worktree_commit_pending=true，独立 re-audit 尚未进行）；但正式整局引擎仍未完成，正式入口继续失败关闭。
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
production_chain_damage_infrastructure=true
production_borrowed_sword_weapon_system=true
production_delayed_trick_judgment_infrastructure=true
production_armor_damage_prevention_infrastructure=true
production_mount_distance_infrastructure=true
production_turn_cycle_discard_infrastructure=true
production_weapon_skill_completion=true
authoritative_full_game_core=false
formal_duel_no_skill_ready=false
formal_run_ready=false
```

`production_basic_cards_batch=true` 只描述正式160张牌堆中六种基本牌（普通【杀】、火【杀】、雷【杀】、【闪】、【桃】、【酒】）已接入生产适配器批次；`production_single_target_trick_slice=true` 只描述【无中生有】（4张）与【无懈可击】（7张）的最小普通锦囊垂直切片；`production_zone_target_trick_batch=true` 只描述【过河拆桥】（6张）与【顺手牵羊】（5张）接入生产适配器并共用“目标区域选牌、隐藏手牌选择、实体牌移动”基础设施；`production_duel_fire_attack_batch=true` 只描述【决斗】（3张）与【火攻】（3张）接入生产适配器并复用【无懈可击】逐张响应链与伤害型普通锦囊结算路径；`production_group_target_trick_batch=true` 只描述【南蛮入侵】（3张）、【万箭齐发】（1张）与【桃园结义】（1张）接入生产适配器并建立“群体普通锦囊按行动顺序逐目标结算框架”（服务器自动目标序列、逐目标独立【无懈可击】窗口、逐目标响应或受伤／回复、濒死救援期间队列暂停与恢复）；`production_remaining_ordinary_trick_batch=true` 只描述【五谷丰登】（2张）完整生产语义与【铁索连环】（6张）完整语义接入生产适配器（公共REVEALED展示池、逐目标独立【无懈可击】、横置状态切换、重铸与属性伤害传导，CP-04J）；`production_chain_damage_infrastructure=true` 只描述横置角色火／雷属性伤害传导生产基础设施（统一传导入口、原始与派生伤害区分、确定性候选顺序、濒死挂起恢复、严格回放与链事件契约，CP-04J；三人以上传导未由正式生产入口证明）；`production_borrowed_sword_weapon_system=true` 只描述【借刀杀人】（2张）完整双人生产语义与11种／12张武器牌本体接入生产适配器（主动装备、同槽替换、攻击范围动态计算、装备区公开、按角色出杀计数、武器专属技能按集中式影响门禁失败关闭，CP-04K）。它们都不表示普通锦囊批次完成，也不表示正式160张牌无技能单挑完成；`production_turn_cycle_discard_infrastructure=true` 只描述正式阶段流收敛为单一权威回合循环（PREPARE→JUDGMENT→DRAW→PLAY→DISCARD→END）并正式实现弃牌阶段（手牌上限默认等于当前体力值；UI逐张选择只是选择过程，确认后所选牌作为一次批量弃置统一结算并自动推进）与回合级状态清理／下一行动者转交。正式160张牌38种卡牌已全部接入生产适配器（formal_deck_registration_complete=true），其中35种／157张完整语义（CP-04P 将8种／9张武器升级为COMPLETE；丈八蛇矛因subcard生命周期规则缺口暂不计入），剩余未注册0种／0张；未完整语义能力（雌雄双股剑[性别数据缺口]、方天画戟[多人生产环缺口]、武将技能等）与正式整局入口继续失败关闭。当前计数口径必须分开：

```text
[test_only_duel_vertical_slice]
unsupported_rules=0
approximation_count=0

[formal]
unsupported_rules=1  # 至少存在一个完整正式整局能力阻塞的哨兵，不是精确缺项数（38种正式卡牌已全部注册，35种完整语义，未完整语义能力仍失败关闭）
approximation_count=0  # 正式入口拒绝执行，所以没有运行近似

[production_turn_cycle_discard_infrastructure]
implemented=true
tested=true
card_types=0  # 本批不新增卡牌种类：正式阶段流与弃牌阶段核心状态机能力
phase_flow=prepare_judgment_draw_play_discard_end
hand_limit=current_hp
hand_limit_excludes_equipment_and_judgment_zones=true
discard_model=select_then_batch_submit
auto_advance_when_within_limit=true
per_turn_slash_count_reset=own_next_play_phase_start
phase_skip_markers_cleared_at_turn_end=true
complete_card_kinds=27
complete_entities=148
adapter_card_kinds=38
adapter_entities=160
remaining_card_kinds=0
remaining_normal_tricks=0
formal_deck_registration_complete=true
all_card_semantics_complete=false
multi_player_production_proven=false
unsupported_rules=1  # 武器专属技能、武将技能、正式整局等仍失败关闭
approximation_count=0

[production_basic_cards_batch]
implemented=true
tested=true
card_types=6
unsupported_rules=1  # 批次范围外（防具、坐骑等6种正式卡牌）仍失败关闭
approximation_count=0

[production_single_target_trick_slice]
implemented=true
tested=true
card_types=2  # 【无中生有】4张、【无懈可击】7张，共11张实体牌
unsupported_rules=1  # 切片范围外（防具、坐骑等6种正式卡牌）仍失败关闭
approximation_count=0

[production_zone_target_trick_batch]
implemented=true
tested=true
card_types=2  # 【过河拆桥】6张、【顺手牵羊】5张，共11张实体牌
unsupported_rules=1  # 批次范围外（防具、坐骑等6种正式卡牌）仍失败关闭
approximation_count=0

[production_duel_fire_attack_batch]
implemented=true
tested=true
card_types=2  # 【决斗】3张、【火攻】3张，共6张实体牌
unsupported_rules=1  # 批次范围外（防具、坐骑等6种正式卡牌）仍失败关闭
approximation_count=0

[production_group_target_trick_batch]
implemented=true
tested=true
card_types=3  # 【南蛮入侵】3张、【万箭齐发】1张、【桃园结义】1张，共5张实体牌
unsupported_rules=1  # 批次范围外（防具、坐骑等6种正式卡牌）仍失败关闭
approximation_count=0

[production_remaining_ordinary_trick_batch]
implemented=true
tested=true
card_types=2  # 【五谷丰登】2张（完整实现）、【铁索连环】6张（完整实现，含属性伤害传导）
complete_card_kinds=21  # 完整实现卡牌种数：18+3种延时锦囊完整语义（武器实体不计入完整实现）
adapter_card_kinds=32  # 注册表口径：已接入生产适配器32种
adapter_entities=147  # 注册表口径：已接入实体147张
complete_entities=148  # 完整实现实体牌：141+7（两种坐骑7张实体）
remaining_card_kinds=0
remaining_normal_tricks=0
tiesuo_card_body_implemented=true
tiesuo_chain_damage_implemented=true
tiesuo_full_semantics_complete=true
unsupported_rules=1  # 批次范围外（防具、坐骑等6种正式卡牌）仍失败关闭
approximation_count=0

[production_borrowed_sword_weapon_system]
implemented=true
tested=true
card_types=12  # 【借刀杀人】2张完整语义；11种武器12张牌本体（全部partial，0种完整实现）
weapon_card_body_implemented=true
weapon_skill_complete=0  # 11种武器专属技能全部未实现，按集中式门禁失败关闭
complete_card_kinds=18
complete_entities=128
adapter_card_kinds=29
adapter_entities=140
remaining_card_kinds=9
remaining_normal_tricks=0
multi_player_production_proven=false
unsupported_rules=1  # 批次范围外（防具、坐骑等6种正式卡牌）仍失败关闭
approximation_count=0

[production_delayed_trick_judgment_infrastructure]
implemented=true
tested=true
card_types=3  # 【乐不思蜀】3张、【兵粮寸断】2张、【闪电】2张，共7张实体牌
complete_card_kinds=21
complete_entities=135
adapter_card_kinds=32
adapter_entities=147
remaining_card_kinds=0
remaining_normal_tricks=0
phase_flow=prepare_judgment_draw_play_end
judgment_lifo=true
judgment_wuxie=true
shandian_damage_type=雷属性
shandian_damage_source=none
multi_player_production_proven=false
formal_draw_exhausted_tie=false  # 正式平局出口保持NOT PROVEN
unsupported_rules=1  # 批次范围外（防具、坐骑、弃牌阶段、改判等6种正式卡牌与能力）仍失败关闭
approximation_count=0
[production_armor_damage_prevention_infrastructure]
implemented=true
tested=true
card_types=4  # 【八卦阵】2张、【仁王盾】1张、【藤甲】2张、【白银狮子】1张，共6张实体牌
complete_card_kinds=25
complete_entities=141
adapter_card_kinds=36
adapter_entities=153
remaining_card_kinds=0
remaining_normal_tricks=0
armor_invalidation=renwangdun_black_slash;tengjia_normal_slash_nanman_wanjian
armor_damage_modifiers=tengjia_fire_plus_one;baiyin_cap_one
bagua_virtual_dodge=true
baiyin_leave_recovery=true
ignore_armor_interface=true
ignore_armor_real_weapon_caller=true  # CP-04P 已由青釭剑真实调用（QINGGANG_LIFECYCLE_CONFIRMED）
multi_player_production_proven=false
unsupported_rules=1  # 批次范围外（坐骑、武器技能、弃牌阶段等）仍失败关闭
approximation_count=0
[production_mount_distance_infrastructure]
implemented=true
tested=true
card_types=2  # 【攻击坐骑（-1坐骑）】3张、【防御坐骑（+1坐骑）】4张，共7张实体牌
complete_card_kinds=27
complete_entities=148
adapter_card_kinds=38
adapter_entities=160
remaining_card_kinds=0
remaining_normal_tricks=0
formal_deck_registration_complete=true
all_card_semantics_complete=false
effective_distance=base_seat_distance_plus_mount_modifiers
mount_direction=attack_horse_owner_to_others_minus_one;defense_horse_others_to_owner_plus_one
weapon_range_separate_from_effective_distance=true
distance_sensitive_cards=slash;attribute_slash;jiedaosharen;shunshou;bingliang
multi_player_production_proven=false
multi_player_death_seat_distance_not_proven=true
unsupported_rules=1  # 弃牌阶段、完整正式回合循环、武器技能等仍失败关闭
approximation_count=0
```
```
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
| 当前组件测试是否通过 | 是；本轮最终完整测试为 `1974 passed`，失败0、跳过0 |

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

正式160张牌堆上第五批普通锦囊生产适配器（CP-04I，2026-08-04 已由用户在外部PowerShell提交实现，提交哈希 `20cb1b1f766529a88aa5f3346a4761b77eca66b7`；2026-08-04 独立审计完成：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，最终独立复审结论 AUDIT_PASSED；审计问题关闭提交 `5b1c2c15b6a8e21563aab02d8a5c181c553e4967`，最终措辞修正提交 `b2d4ffca18092938437d15826efdaddba8a0a689`；里程碑标签 `milestone-b2-wugu-tiesuo-card-body-audited` 由用户在本次最终文档提交后立即建立（本轮未执行 git tag）），继续复用同一 `GameState`／`CardInstance`／`ZoneRef`、事件队列、合法动作路由、【无懈可击】逐张响应链与群体锦囊逐目标结算框架，不建立第二套状态、牌区、事件或回放系统：

- 模式 ID 仍为 `production_basic_cards_batch`（双人生产切片）；正式牌堆总实体牌数仍为160，实例ID唯一；【五谷丰登】2张（♥3、♥4，实例088／091）、【铁索连环】6张（♣10、♣J、♣Q、♣K、♠J、♠Q，实例071／074／077／080／154／157）真实读取牌堆CSV实体并绑定生产适配器，其余21种正式卡牌（含1种未实现普通锦囊：借刀杀人）继续失败关闭；
- 【五谷丰登】使用时只提交使用动作、不提交目标列表：引擎按当前存活且仍在游戏中的角色数量快照目标序列（含使用者、按行动顺序、跳过已死亡角色），并一次性从牌堆展示等量实体牌到公共 `ZoneKind.REVEALED` 区域；牌堆不足时复用正式重洗与确定性 RNG 逻辑，合计仍不足则 `ProductionBatchDeckExhaustedError` 失败关闭；`CARD_REVEALED` 事件公开实体ID、card_key、牌名、花色、点数与展示池顺序；
- 【五谷丰登】每名目标先打开独立【无懈可击】窗口：被取消目标不选牌、展示池保持并继续下一目标；未取消目标从公开展示池选择一张并获得（`CARD_MOVED`＋`CARD_GAINED`＋`group_target_resolved`）；公共选择动作绑定会话、窗口、根锦囊实例、当前目标与索引、展示池有序摘要（`pool_digest`）与状态哈希，池外实体、重复选择、非当前目标、旧窗口、旧摘要与跨会话选择一律失败关闭；全部目标完成后剩余展示牌统一进入弃牌堆（reason=`wugu_remaining_to_discard`），原锦囊此时才从处理区进入弃牌堆；游戏提前结束执行确定性清理（展示池与处理区不滞留实体）；
- 【铁索连环】正常使用选择一名或两名互不相同的角色（可含使用者、无距离限制）；目标结算顺序由服务器以使用者为锚点按行动顺序规范化，不信任玩家提交顺序；原锦囊保持处理区直到全部目标完成；每名目标独立【无懈可击】窗口，未被无懈的目标切换横置状态（`chained` 进入 `PlayerState` 与状态快照／哈希）并产生 `chained_state` 事件（actor、target、old_value、new_value、root_card_instance_id、reason、目标索引与总数）；
- 【铁索连环】重铸不是使用也不是打出：不产生普通 `card_used`／`card_played`、不指定目标、不接受【无懈可击】；实体从手牌直接进入弃牌堆（`card_recast` 事件，reason=recast）后通过正式摸牌接口摸1张（reason=`tiesuo_recast`），牌堆不足复用正式重洗逻辑；重铸动作进入严格回放决策日志；
- 本批明确只完成铁索牌本体，不实现属性伤害传导：`tiesuo_card_body_implemented=true`、`tiesuo_chain_damage_implemented=false`、`tiesuo_full_semantics_complete=false`；CP-04J 前，横置角色受到火／雷属性伤害时，生产入口在统一伤害前置校验（`_assert_chain_damage_gate`）处抛 `UnsupportedRuleError` 失败关闭，当前动作未被提交，绝不静默生成“未传导但看似完整”的结果；无属性伤害命中横置角色、火／雷属性伤害命中未横置角色仍正常结算；该临时门禁在 CP-04J 实现传导后移除；借刀杀人仅记录用户确认规则（见 Knowledge 4.6.1），等待装备生产切片（CP-04K）；
- CP-04I 独立审计三个非阻塞问题已由审计问题关闭提交 `5b1c2c15b6a8e21563aab02d8a5c181c553e4967`（fix: close wugu and tiesuo card-body audit gaps）正式关闭，最终措辞修正提交 `b2d4ffca18092938437d15826efdaddba8a0a689`（docs: correct CP-04I audit closure wording）；2026-08-04 独立审计完成：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，最终独立复审结论 AUDIT_PASSED（`status=audited`、`independent_audit_done=true`、`audit_conclusion=AUDIT_PASSED`）；里程碑标签 `milestone-b2-wugu-tiesuo-card-body-audited` 为本次最终文档提交后由用户立即建立的标签名称（本轮未执行 git tag、未验证标签已存在）；五谷展示在牌量不足时先做统一可用性预检再登记事件，`ProductionBatchDeckExhaustedError` 与属性伤害 `UnsupportedRuleError` 抛出后状态、事件、RNG、runtime、执行哈希全部保持不变（原子不可见）；铁索重铸在局部不可变状态上先完成“重铸铁索进入弃牌堆→正式摸1张”再一次性登记事件，因重铸牌自身进入弃牌堆即构成至少1张可重洗实体，正式语义下不存在真实可达的牌量不足路径（不可达）；
- CP-04I 审计关闭记录：①`worktree_commit_pending` 字段与真实提交状态矛盾（已置 `worktree_commit_pending=false`）；②横置角色受火／雷属性伤害时缺乏运行时失败关闭（统一伤害前置校验抛 `UnsupportedRuleError`，当前动作未被提交）；③五谷牌量不足异常后事件与状态原子性（统一可用性预检，失败后状态／事件／RNG／runtime／执行哈希不变）；后续复核修正：铁索重铸的动作前牌量预检错误排除重铸牌自身，最终语义为铁索先进入弃牌堆、再进入正式重洗和摸牌流程，初始牌堆、弃牌堆均为空时仍可洗回并摸回该铁索，重铸牌量不足在当前正式语义下不可达；
- 新增 51 项真实生产路径验收测试（`tests/test_sgs_production_remaining_ordinary_tricks.py`），覆盖五谷注册表与2张实体、目标序列含使用者、双人展示2张、公开展示事件、逐目标独立无懈、单无懈跳过／双无懈恢复、选牌进手牌、唯一实体移除、剩余弃置、牌堆不足重洗、池摘要过期、旧窗口重放、非当前目标、池外实体、重复选择、跨会话、严格回放与篡改、玩家可见边界；铁索注册表与6张实体、一／二目标、含使用者、重复／空／三目标拒绝、服务器规范目标顺序、逐目标无懈、false→true／true→false、状态事件、处理区滞留、重铸不是使用或打出、重铸直接弃置并摸1、重铸无目标、非铁索实体／非手牌实体拒绝、严格回放与篡改、chained 进入状态哈希、未实现属性传导不被误写为完成；完整 pytest 为 `1454 passed`（失败0、跳过0）；审计问题关闭后新增9项回归测试，批次测试文件共60项，完整 pytest 为 `1463 passed`（失败0、跳过0）。

本批次只验证双人生产切片：当前正式生产入口原生仅支持双人会话，三人以上五谷展示数量与完整选择顺序、铁索目标顺序与多人属性伤害传导仍未由正式生产入口证明（NOT PROVEN），文档不得写成完整军八、2v2或斗地主完成；不构成普通锦囊批次完成、正式单挑完成或里程碑 B 完成。

### 2.10 属性伤害传导生产基础设施（CP-04J）

CP-04J 在双人生产入口上接通统一属性伤害传导管线（实现提交 `c094bff5dab127917e8d0b9a2d3422e3ab736783` 已由用户在外部PowerShell创建，提交信息 feat: implement production chain damage infrastructure；检查点文档提交 `55228c9d464daac6eb061ba356b0497ec814eba6`；审计残项关闭提交 `68e419b79e379184c1f1cc7ad650039771530f89`，fix: close chain damage audit gaps；2026-08-04 完成独立审计：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，最终独立复审结论 AUDIT_PASSED（status=audited、independent_audit_done=true、audit_conclusion=AUDIT_PASSED）；里程碑标签 `milestone-b2-chain-damage-infrastructure-audited` 为本次最终文档提交后由用户立即建立的标签名称（本轮未执行 git tag、未验证标签已存在））：

- 触发条件：伤害类型为火属性或雷属性、原始受伤角色在本次伤害结算时 `chained=true`、最终实际伤害大于0、非传导派生伤害、游戏未结束；无属性伤害、实际伤害0、未横置角色、伤害被防止、已标记为 chain-transmitted 的派生伤害与胜利成立均不触发；
- 原始角色结算顺序：计算并提交原始伤害→得到最终实际伤害→实际伤害大于0且横置时解除横置并产生 `chained_state`→建立传导根（`chain_damage_started`）→完整处理原始角色的伤害、濒死、救援、死亡与已有后续→全部结束且游戏未结束时才开始下一名传导目标；不得在濒死救援窗口提前扣除下一名角色体力；
- 候选顺序：以当前回合角色为锚点、按座次递增方向循环，永久排除原始受伤角色；每名候选轮到时动态检查存活、在游戏中、横置与是否已处理，不依赖玩家提交顺序；当前双人正式入口只能证明最多一名其他传导目标，三人以上传导顺序 NOT PROVEN；
- 传导伤害语义：每名合法目标一条独立 `damage` 事件，继承原始来源角色、伤害属性、根实体牌与使用记录，并以 `root_damage_event_id` 指向根事件；基数等于原始受伤角色最终实际伤害，不等于牌面初始伤害或上一名目标实际值；事件负载标记 `is_chain_transmitted=true`、`chain_base_damage`、`chain_target_index`；派生伤害不得重新启动同根传导；当前无正式武将技能可在传导中产生新属性伤害，嵌套新根保持结构支持但不宣称已证明；
- 目标结算与终止：目标实际伤害大于0时解除横置并产生 `chained_state`，完整处理伤害、濒死、救援、死亡后处理下一候选；实际伤害为0时不解除横置、按已确认规则终止本轮后续未开始目标并记录 `prevented_zero`（当前仅具备状态机分支与事件契约，尚未由正式减伤路径端到端证明，等待减伤机制接入后补端到端验证）；死亡或已解除横置目标确定性跳过；胜利成立时已开始伤害按现有规则收尾、未开始目标全部停止并清理挂起状态（`stop_reason=winner`，不产生 `stopped_winner` 目标结算事件）；
- 濒死暂停：新增 `_PendingChainDamage` 挂起结构保存根事件ID、来源、根牌、damage_type、基数、原始角色、已处理集合、候选顺序、当前索引、当前目标、暂停原因、父级挂起上下文与会话绑定；与既有 `DYING_RESCUE` 状态机集成，原始角色与传导目标濒死时暂停、救援结束且游戏未结束后从准确索引恢复，不重复处理已处理目标、不跳过尚未处理合法目标；
- 事件：`chain_damage_started`、`chain_target_resolved`（damaged|skipped_dead|skipped_unchained|prevented_zero）、`chain_damage_finished`（completed|prevented_zero|winner|no_candidates）进入严格回放事件哈希链；事件契约在构造时对三个链事件做完整字段、类型、枚举与组合校验，`stopped_winner` 不是生产实现值；玩家可见回放不泄露私有手牌或会话秘密；
- 门禁：CP-04I 的 `_assert_chain_damage_gate` 已移除，火杀、雷杀、火攻与通用伤害入口统一接入，不再存在部分入口抛错、部分入口静默传导的分裂行为；未支持的多人与装备边界不因门禁移除而误标完成；
- 审计残项关闭（N1-N4，提交 `68e419b79e379184c1f1cc7ad650039771530f89`，fix: close chain damage audit gaps）：N1 `stopped_winner` 不再是合法 `chain_target_resolved.result`，winner 只产生 `chain_damage_finished(stop_reason=winner)`；N2 三个链事件在构造时做完整字段集、类型、枚举与组合校验，缺字段、多余字段、bool 冒充整数、非法 result、非法 stop_reason、非法列表结构等均被拒绝；N3 `prevented_zero` 控制流改为明确结果（`_ChainStepOutcome`）驱动——目标伤害归零后 `_advance_chain` 立即返回，不再循环访问已清理的 `pending_chain`、不重复产生 `chain_damage_finished`、不处理后续尚未开始目标、不抛二次 `ProductionBatchError`；N4 保留 CP-04I 历史说明并追加 CP-04J 当前双人生产范围说明；
- 验证：批次测试文件 `tests/test_sgs_production_chain_damage.py` 44项（40项生产路径＋4项审计残项关闭：prevented_zero 控制流与文档检查）、`tests/test_sgs_engine_events.py` 63项（含36项链事件契约）；最终独立复审定向回归 434 passed，完整 pytest `1543 passed`（失败0、跳过0），compileall 通过，源码完整性审计 scanned_file_count=116、defect_count=0、audit_item_count=55，git diff --check 通过，SHA-256 清单31项全部匹配；`tiesuo_card_body_implemented=true`、`tiesuo_chain_damage_implemented=true`、`tiesuo_full_semantics_complete=true`（均限于当前双人正式生产入口范围）；`authoritative_full_game_core=false`、`formal_run_ready=false`、`formal_duel_no_skill_ready=false`、`unsupported_rules=1`、`approximation_count=0`、`multi_player_production_proven=false`；`prevented_zero` 仅完成状态机分支与事件契约，尚无正式防具、减伤或伤害防止路径端到端证明；剩余普通锦囊仅【借刀杀人】等待 CP-04K，里程碑 B 未完成，正式胜率模拟未开放。

### 2.11 【借刀杀人】＋11种武器牌本体批次（CP-04K）

正式160张牌堆上最后一张普通锦囊与全部武器牌本体的生产批次，继续复用现有权威核心、普通锦囊使用窗口、【无懈可击】逐张响应链、隐藏句柄体系与严格重执行回放：

- 模式 ID 仍为 `production_basic_cards_batch`（双人生产切片）；正式牌堆总实体牌数仍为160，实例ID唯一；【借刀杀人】2张与11种武器12张实体牌真实读取牌堆CSV并绑定生产适配器；其余9种正式卡牌（3种延时锦囊、4种防具、2种坐骑）继续失败关闭，普通锦囊已全部实现；
- 武器牌本体：出牌阶段主动使用、武器进入weapon槽、同槽替换时旧武器原子移入弃牌堆（不伪造主动弃牌）、攻击范围每次从当前装备区按正式结构化CSV动态计算、装备区公开、实体身份保持；新增 `equipment_equipped`／`equipment_removed`／`equipment_replaced` 三个最小装备事件并进入事件哈希链；
- 出杀次数由单一布尔值升级为按角色记录的 `slash_used_counts`：当前回合角色主动使用【杀】增加自己的计数；某角色自己的新出牌阶段开始时只重置该角色计数；借刀强制【杀】绕过通常次数上限但仍增加第一目标自己的计数；
- 【借刀杀人】：第一目标为装备区有武器的其他角色，第二目标为第一目标攻击范围内的角色且可以是使用者本人；`card_used` 的 `target_ids` 只包含第一目标，第二目标以公开负载记录；只对第一目标打开【无懈可击】窗口，第二目标无独立无懈窗口但本人仍可对第一目标效果使用【无懈可击】；无懈链结束后进行第二次动态合法性检测并重新读取第一目标当前武器；
- 生效后第一目标通过绑定“会话＋窗口＋第一目标＋第二目标＋手牌快照＋杀实体＋卡牌键＋阶段＋执行上下文”的HMAC-SHA256不透明句柄选择实体普通／火／雷【杀】或拒绝；裸实体ID提交、过期、伪造与手牌变化后的句柄失败关闭；
- 选择【杀】即视为履行借刀要求：产生第一目标自己的正常 `card_used`、正常进入闪响应、伤害、濒死、救援、死亡与属性传导，即使被闪抵消或未造成伤害也不再交武器；拒绝或没有合法【杀】时把第一目标当前武器直接移入使用者手牌（`card_moved`／`card_lost`／`card_gained`，reason=`jiedaosharen_weapon_gain`），无武器或使用者已死亡时记录 `no_weapon_to_transfer` 且不移动；
- 借刀是外层根，被要求使用的【杀】是子结算：杀等待闪、濒死救援与属性传导期间借刀保持挂起，子结算完成后恢复并只弃置根借刀一次；终局清理时根借刀从处理区确定性进入弃牌堆，处理区不遗留；
- 11种武器专属技能全部保持 partial，建立集中式 `check_weapon_skill_gate` 影响矩阵：能从当前完整公开状态证明不影响本次合法性、可选动作或结算结果时继续通用牌本体流程，否则在首次相关判断前抛 `UnsupportedRuleError`（如雌雄双股剑因无性别字段对另一角色出杀一律失败关闭、丈八蛇矛手牌≥2张时失败关闭、朱雀羽扇实体普通杀失败关闭、诸葛连弩主动额外杀依赖技能时失败关闭但借刀强制杀不依赖连弩）；
- 装备事件 reason 封闭枚举（N1）：`equipment_equipped` 仅允许 `equip`、`equipment_removed` 仅允许 `replaced`、`equipment_replaced` 无 reason 字段；非字符串、空字符串与未知 reason 一律拒绝，正常主动装备与同槽替换事件不受影响；
- 12张武器实体路径覆盖（N2）：从正式注册表枚举全部12张武器实体（含两张诸葛连弩）分别走 enumerate→validate→apply 真实装备路径，断言实体ID、离开手牌、进入weapon槽与 equipment_equipped 事件实体ID；
- 关键专项与严格回放（N3）：拒绝出杀后第一目标与借刀使用者 `slash_used_counts` 均完全不变；借刀→子杀→濒死→救援失败→胜利的完整回放严格重执行（挂起清空、根借刀只清理一次且进弃牌堆、无后续武器交付、状态/执行/事件链/record哈希一致）；`no_weapon_to_transfer` 单字段篡改失败关闭；第二目标在回放与实况中均无独立无懈窗口（`pending_trick.target_id` 始终为第一目标，伪造第二目标窗口决策重执行失败关闭）；
- 新增80项专项测试（`tests/test_sgs_production_borrowed_sword_weapon_system.py`）并扩展12项装备事件契约测试（`tests/test_sgs_engine_events.py`）；CP-04K 首次独立审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES（N1：装备事件reason封闭契约；N2：第二张诸葛连弩正式装备路径；N3：关键专项断言和严格回放），N1-N3 已由审计残项关闭提交 `79acc6ff514af4900acfe87507374fc8d696ec97`（fix: close borrowed sword weapon audit gaps）正式关闭，最终独立复审结论 AUDIT_PASSED；审计残项关闭后批次测试文件84项、事件契约测试85项、完整 pytest 为 `1649 passed`（失败0、跳过0），最终独立复审有效完整重跑 `1649 passed`（复审首次运行因不可写 --basetemp 导致的48个 tmp_path setup 错误不计入验收，有效结果以标准临时目录重跑为准）；SHA-256 清单33个文件条目全部匹配；另有1个 `hash_note` 元数据项，不计作文件哈希。

本批次只验证双人生产切片：不构成武器技能完成、装备全部完成、正式单挑完成或里程碑 B 完成；三人以上借刀与“使用者死亡但游戏未结束”等边界未由正式生产入口证明。

### 2.12 三种延时锦囊＋判定与阶段基础设施批次（CP-04L）

正式160张牌堆上全部三种延时锦囊与判定／阶段基础设施的生产批次，继续复用现有权威核心、正式牌区移动接口、【无懈可击】逐张响应链、隐藏句柄体系与严格重执行回放，不建立第二套锦囊引擎或事件队列：

- 模式 ID 仍为 `production_basic_cards_batch`（双人生产切片）；正式牌堆总实体牌数仍为160，实例ID唯一；【乐不思蜀】3张（058♣6／098♥6／137♠6）、【兵粮寸断】2张（053♣4／151♠10）、【闪电】2张（117♥Q／122♠A）真实读取牌堆CSV并绑定生产适配器；实施后注册表32种／147张、完整实现21种／135张、剩余未接入6种（4种防具＋2种坐骑）、剩余锦囊0；
- 正式回合阶段：PREPARE → JUDGMENT → DRAW → PLAY → END；构造正式会话后的首名角色也必须完整经过阶段流，初始化不再直接摸2进入PLAY，`_apply_end_turn` 不再给下一角色直接摸2；PREPARE／JUDGMENT／DRAW 均通过正式推进动作进入下一阶段；弃牌阶段仍不实现，不得虚构；
- 延时锦囊使用：出牌阶段从本人手牌使用，直接进入目标判定区（不经处理区），产生正式 `card_used` 与 `card_moved`（reason=`delayed_trick_placed`），分配单调递增 `judgment_zone_entry_index`；使用时不打开普通 TRICK_RESPONSE 窗口，刚使用或刚进入判定区时不能使用【无懈可击】；同一角色判定区不得有同名延时锦囊（枚举与apply双重验证），不同名可共存；【乐不思蜀】与【兵粮寸断】必须指定其他角色（兵粮还要求实际距离=1、武器攻击范围无关、坐骑栏被夹具占用时失败关闭），【闪电】只能对自己使用；
- 判定前无懈：到判定阶段即将处理某张延时锦囊时建立 `pending_judgment` 并打开 JUDGMENT_WUXIE（响应顺序：当前回合角色→对方），【无懈可击】可被另一张无懈抵消，一整轮无人响应后关闭；被抵消时不翻判定牌、不产生判定结果与阶段跳过、不造成伤害，乐不思蜀／兵粮寸断本体经处理区弃置，闪电从判定区直接进入合法目标转移且不立即打开新无懈窗口；
- 判定牌生命周期：判定前先预检牌堆＋可重洗弃牌堆合计至少1张，不足则原子失败关闭（不生成判定牌、不移动本体、不消费随机、不改变牌堆顺序；失败不得描述为正式平局，正式平局出口 NOT PROVEN）；判定牌从牌堆顶取得→REVEALED（`CARD_REVEALED` reason=`judgment`，公开实体、牌名、花色、点数、目标与延时锦囊本体ID）→`judgment_result`→弃牌堆（reason=`judgment_card_resolved`）；判定牌与本体实例ID必须不同；每次判定完成后REVEALED不得残留判定用途牌；
- 动态LIFO：判定阶段每次重新读取当前角色判定区，排除本阶段已处理实例，按 `judgment_zone_entry_index` 选择最大者，一次只完整处理一张；闪电转移或回置时追加新的 entry_index，同一实例已进入 `processed_judgment_instance_ids` 后本阶段不得再次判定；entry_index 跨回合保留，回合结束清理 processed 与跳过标记；
- 阶段跳过：乐不思蜀判定非红桃只跳过本回合PLAY（phase_skipped 事件精确记录 player_id／turn_number／skipped_phase／reason／delayed_trick_instance_id），兵粮寸断判定非梅花只跳过本回合DRAW；DRAW被跳过时不摸牌，PLAY被跳过时不允许出牌动作；回合结束清除跳过标记、不得继承到下一回合；
- 闪电：判定为黑桃2至9时本体判定区→处理区→执行3点无来源雷属性伤害（damage_source=None、damage_type=雷属性）→完整处理伤害、传导、濒死、救援、死亡后本体才弃置（传导开始前不提前弃置本体，`_complete_root_resolution` 优先恢复 `pending_judgment` 再恢复借刀挂起）；未命中或不被抵消时按“下家开始、存活座次递增”搜索合法目标（跳过死亡与判定区已有闪电角色），无合法目标时回置当前结算角色自己并追加新 entry_index，回置后本阶段不再判定；
- 死亡与胜利清理：角色正式死亡时手牌区、装备区与判定区全部实体牌以系统区域移动事件（reason=`death_cleanup`）置入弃牌堆，不生成玩家主动弃置事件，保持实体身份与确定顺序；当前判定根导致死亡或胜利时判定牌已弃置、本体经处理区弃置、`pending_judgment` 清理、REVEALED与PROCESSING无残留，幸存角色区域不因胜利清空；
- player_visible 双视角：导出按观察者身份过滤（`viewer_id=None` 为公共／旁观者视图），移除 seed、initial_rng_state、initial_rng_state_sha256、根级随机消费记录与 `authoritative_private`；初始发牌与摸牌阶段的非公开获得只对获得角色本人暴露实体，对手与公共视图只见数量变化与reason；五谷公开选择、顺手牵羊公开获得、借刀交付武器等公开获得路径保持公开；
- 事件：新增 `judgment_started`、`judgment_result`、`phase_skipped`、`delayed_trick_transferred` 四个领域事件并进入严格回放事件哈希链；事件契约在构造时做精确字段集、类型、枚举与 target 绑定校验（缺字段、多余字段、bool冒充整数、非法阶段枚举、索引非负整数等均被拒绝）；
- 新增专项测试 `tests/test_sgs_production_delayed_tricks.py`（35项，覆盖 A–Z 语义矩阵：7张正式实体、使用与判定区、同名限制、使用时无懈不可响应、判定前无懈链、判定牌生命周期、动态LIFO与entry_index、乐不思蜀／兵粮跳阶段、闪电命中／转移／回置、无来源雷伤与传导、濒死救援、死亡与胜利清理、判定彻底不足原子失败、player_visible 双视角与公开获得、严格回放篡改失败关闭、事件契约、牌守恒与终局停止）并扩展 `tests/test_sgs_engine_events.py`（新增23项判定事件契约测试：4项合法构造＋19项非法构造参数化）；
- 本批已由用户在外部PowerShell创建真实实现提交（提交哈希 `35c06bd50a431a62e7c3ad01d10384bf6884c403`，提交信息 feat: implement delayed tricks and judgment infrastructure）；检查点文档提交 `4f2c9b61fccb4337a8e84ae560835d705be65bda`（docs: record delayed trick and judgment checkpoint）；2026-08-05 第一次独立审计结论 AUDIT_FAILED_BLOCKING_ISSUES：唯一阻塞项 B1 为 player_visible 未脱敏 reshuffle 事件（逐卡 card_moved 带实体身份与洗后顺序，且公开投影保留绑定未脱敏材料的权威哈希，可被小候选空间穷举），另有非阻塞残项 N1–N9；第一次审计修复提交 `96f536e1f392fd97faf61518a849a0d515b6a82e`（fix: close delayed trick audit gaps）完成 B1 实质修复（reshuffle 聚合为公开汇总事件、移除 event_hash_chain／initial／final／决策级状态哈希等全部旁路、隐藏获得与死亡清理按实体ID排序并重写批次 sequence、decisions 删除 action_id 并稳定排序、viewer_id 契约失败关闭）与 N1–N9 关闭（新增17项专项测试），完整 pytest 1724 passed；2026-08-06 第二次最终复审结论 AUDIT_FAILED_BLOCKING_ISSUES：B1-a（动作负载 state_hash 等权威状态摘要旁路）、B1-b（legal_actions/chosen_action 泄露行动者完整手牌）、B1-c（tiesuo_recast 等隐藏摸牌泄漏）与两个复审观察项（N5 篡改测试结构、judgment_entry_indices 陈旧残留）；最终修复提交 `eeeaf558cdaeeea0eb90456f907f83dce52286f3`（fix: harden player-visible replay privacy）完成 B1-a/B1-b/B1-c 修复与两个观察项关闭（递归移除动作负载与选择数据中的权威摘要、decisions 按观察者投影（行动者本人可见、非行动者/公共视图省略私有动作）、隐藏摸牌以来源区域语义统一脱敏、N5 拆分为格式层与语义层两类明确测试、判定区离开路径清理 entry_index 并扩展不变量；新增9项测试，本地修复会话完整 pytest 1733 passed）；2026-08-06 Grok 网页端完成独立静态审计 STATIC_AUDIT_PASSED：通过 GitHub 连接器读取精确目标提交 `eeeaf558cdaeeea0eb90456f907f83dce52286f3`（仓库 414238729-ux/-，分支 deepseek-final-reaudit-delayed-trick-infrastructure），完整读取18个强制生产、测试和状态文件，PARTIAL_READ=无、NOT_READ=无；Grok 未亲自运行 pytest、Git 或本地虚拟环境验证，1733 passed 等运行结果来自本地修复会话，两类证据分别记录、不得混写；最终独立审计结论 AUDIT_PASSED；文档收口提交 `ba64b750fabd99f2bfc93697cea83e1272216d02`（docs: finalize delayed trick and judgment audit milestone）；检查点状态为 status=audited、commit=35c06bd50a431a62e7c3ad01d10384bf6884c403、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、milestone_tag=已建立标签 `milestone-b2-delayed-trick-judgment-infrastructure-audited`（HISTORICAL/AS-OF：当时本地与 GitHub 远程标签均已验证存在并指向文档收口提交 ba64b750fabd99f2bfc93697cea83e1272216d02；CURRENT LIVE REF：当前Git标签解析为 fc3df95202b23dccfd9abf5e476485a224d6fc2c，当前标签目标以Git标签解析结果为准）、worktree_commit_pending=false。

本批次只验证双人生产切片：不构成延时锦囊全部完成、多人响应链完成、正式单挑完成或里程碑 B 完成；三人以上延时锦囊与无懈响应顺序、三人以上闪电合法目标搜索、多人属性传导、改判、判定牌获得、判定结果修改、正式牌堆彻底不足平局、坐骑距离修正完整语义、防具与 prevented_zero 正式路径、弃牌阶段与武将技能均保持 NOT PROVEN。

### 2.13 四种防具＋伤害修正／防止基础设施批次（CP-04M）

正式160张牌堆上全部四种防具与统一伤害修正／防止基础设施的生产批次，继续复用现有权威核心、正式牌区移动接口、【无懈可击】逐张响应链、判定基础设施与严格重执行回放，不建立第二套伤害或装备引擎：

- 模式 ID 仍为 `production_basic_cards_batch`（双人生产切片）；正式牌堆总实体牌数仍为160，实例ID唯一；【八卦阵】2张（045♣2／125♠2）、【仁王盾】1张（047♣2 EX）、【藤甲】2张（046♣2／126♠2）、【白银狮子】1张（043♣A）真实读取牌堆CSV并绑定生产适配器；实施后注册表36种／153张、完整实现25种／141张、剩余未接入2种（攻击坐骑、防御坐骑）、剩余锦囊0；
- 统一防具伤害修正管线：所有正式伤害（杀／属性杀／决斗／火攻／南蛮／万箭／闪电／传导／无来源）在扣减体力前经统一 `resolve_armor_damage` 解析，修正顺序确定为“藤甲火属性伤害+1 → 白银狮子限伤（2点或更多改为1点）”，最终伤害不得为负；最终为0时不扣HP、不进入濒死、不触发传导并产生可审计防止结果（DAMAGE_PREVENTED）；伤害事件携带 declared_amount／final_amount／modifiers／armor_ignored 审计字段；
- 统一防具无效判断 `armor_invalidates_effect`：仁王盾令黑色杀无效、藤甲令普通杀／南蛮入侵／万箭齐发无效，发生在响应窗口之前（不打开闪／杀／闪响应窗口、不消耗响应牌、不造成伤害、不触发濒死或传导），杀仍算已经使用并进入弃牌堆，群体锦囊逐目标以 `armor_invalidated` 结果推进；
- 八卦阵：响应【杀】／【万箭齐发】窗口内由装备者选择发动判定（`activate_bagua`，每窗口限一次）；判定红色视为使用／打出一张虚拟【闪】（响应杀只产生 card_used、响应万箭只产生 card_played，不创建实体），判定黑色本次失败、仍可选择真实【闪】或不响应；判定牌牌堆顶→REVEALED→公开→弃牌堆，判定前无【无懈可击】窗口，牌量不足原子失败关闭；
- 白银狮子：限伤适用于有来源／无来源／传导伤害（失去体力不受限）；离区恢复挂在统一装备离区钩子上（主动替换 `equip_replaced`、过河弃置 `guohechaiqiao_discard`、顺手获得 `shunshouqianyang_gain`），恢复不超过体力上限、满血或已死亡不恢复、死亡清理不触发、同一实例每次离区只触发一次；
- 统一防具无效接口（armor invalid；代码字段 `ignore_armor`）可同时抑制防具无效与伤害修正；当前统一接口已由 CP-04P 青釭剑真实调用（QINGGANG_LIFECYCLE_CONFIRMED：target-scoped、slash-resolution-scoped，闪结算完成或本次伤害结算完成后清除，见 2.16 节）；
- 事件：新增 `armor_judgment_started`、`armor_judgment_result`、`armor_recovered`、`damage_prevented`四个领域事件并进入严格回放事件哈希链，契约在构造时做精确字段集、类型、枚举与绑定校验；防具判定牌公开展示，公开装备移动不被隐藏摸牌脱敏误伤；
- 新增专项测试 `tests/test_sgs_production_armor_damage_prevention.py`（42项，覆盖 A–G 语义矩阵）并扩展 `tests/test_sgs_engine_events.py`（新增24项防具与伤害防止事件契约测试：4项合法＋20项非法参数化）；
- 实现提交 29ab73e006408e1e1582a300801e7aa6e04bd9c4（feat: implement armor and damage prevention infrastructure）已由用户在外部PowerShell提交，实现父提交 fc3df95202b23dccfd9abf5e476485a224d6fc2c；检查点 `CP-04M-PRODUCTION-ARMOR-DAMAGE-PREVENTION-INFRASTRUCTURE` 状态为 audited、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、worktree_commit_pending=true；2026-08-06 Grok 网页端经 GitHub 连接器独立静态审计最终结论 STATIC_AUDIT_PASSED（24个强制文件全部完成相关正文阅读，PARTIAL_READ=空、NOT_READ=空，13个强制章节均为PASSED，未发现阻塞问题；首轮 STATIC_AUDIT_INCOMPLETE 是强制文件正文阅读范围尚未补齐，不是代码阻塞缺陷；正确生产文件路径记录为 scripts/sgs_engine/__init__.py（中间报告曾出现路径书写笔误，遗漏双下划线前缀）；最终审计文档提交 2db702fde037b501190950687059d660c32b56da（docs: finalize armor and damage prevention audit milestone）已由用户在外部PowerShell提交；里程碑标签 milestone-b2-armor-damage-prevention-infrastructure-audited 已实际建立并推送，本地与 GitHub 远程标签均已由用户在外部PowerShell验证存在；标签在最终状态回填开始时指向 2db702fde037b501190950687059d660c32b56da，随后用户已将标签移动到承载最终仓库状态记录的提交；当前标签指向以Git标签解析结果为准。

本批次只验证双人生产切片：不构成完整武器技能完成、坐骑完成、装备系统全部完成、正式单挑完成或里程碑 B 完成；青釭剑等真实武器无视防具调用、寒冰剑等防止类效果、坐骑语义、完整武器技能、三人以上传导与响应顺序、正式单挑、弃牌阶段及其他尚未完成的正式回合能力、authoritative_full_game_core 与正式胜率模拟均保持 NOT PROVEN；不得把通用 ignore_armor 接口的通过扩大为真实青釭剑技能完成，不得把 CP-04M 通过扩大为整个正式游戏核心通过。

### 2.14 正式坐骑＋距离／攻击范围基础设施批次（CP-04N）

正式160张牌堆上剩余两种坐骑与统一距离／攻击范围基础设施的生产批次，继续复用现有权威核心、统一装备路径与严格重执行回放，不建立第二套装备或目标合法性引擎：

- 模式 ID 仍为 `production_basic_cards_batch`（双人生产切片）；正式牌堆总实体牌数仍为160，实例ID唯一；【攻击坐骑（-1坐骑）】3张（039紫骍♦K／094赤兔♥5／159大宛♠K）与【防御坐骑（+1坐骑）】4张（040骅骝♦K／055的卢♣5／119爪黄飞电♥K／135绝影♠5）真实读取牌堆CSV并绑定生产适配器；实施后注册表38种／160张、完整实现27种／148张、剩余未注册0种／0张，正式160张实体牌全部注册（formal_deck_registration_complete=true）；
- 统一权威距离模型：`base_seat_distance`（环形座次顺时针／逆时针较小值）＋坐骑修正得到`effective_distance`；进攻坐骑只影响装备者到别人的距离（-1），防御坐骑只影响别人到装备者的距离（+1），两者同时存在时按同一公式组合；正式距离不变量：自己到自己的距离永远为0，两名不同角色之间的最终距离最低为1（-1坐骑不得把相邻角色距离1修正为0，基础距离2经-1坐骑修正后变为1；【顺手牵羊】／【兵粮寸断】的“实际距离为1”在相邻角色＋源-1坐骑时仍为1、目标保持合法）；距离由权威GameState与装备区真实实体实时计算，不接受动作负载传入的 distance／range／mount modifier；
- 武器攻击范围（`attack_range_of`）与有效距离分离：攻击范围只用于“攻击范围内”类检查（【杀】及属性【杀】目标合法性＝有效距离≤攻击范围、【借刀杀人】第二目标），不参与【顺手牵羊】／【兵粮寸断】的“实际距离为1”检查，进攻坐骑不是“武器范围+1”；
- 距离敏感卡牌接入：普通／火／雷【杀】（`is_valid_slash_target`）、【顺手牵羊】（`is_valid_shunshou_target` 移除坐骑失败关闭门禁）、【兵粮寸断】（枚举与apply均使用有效距离，移除坐骑门禁）、【借刀杀人】第二目标（按第一目标的攻击范围与双方坐骑计算，使用时与无懈链后重新验证）；装备变化后旧动作失败关闭，非法距离不消耗牌、不改变状态；
- 坐骑装备：`use_mount` 正式动作复用统一装备路径进入 attack_horse／defense_horse 栏位，同栏位替换原子化、进攻与防御坐骑可同时存在互不覆盖、武器／防具／坐骑栏位互不覆盖；被过河弃置、顺手获得或死亡清理移走后装备引用立即清理、距离立即重算；坐骑离区不触发【白银狮子】防具恢复；
- 新增专项测试 `tests/test_sgs_production_mount_distance.py`（41项，覆盖 A–H 语义矩阵及距离下限边界测试：注册与160张牌堆、坐骑装备与替换／弃置／获得／死亡清理、距离公式与方向性、杀与武器范围组合、借刀第二目标、顺手与兵粮距离边界、严格回放与隐私、防具／延时锦囊回归、距离下限 A–G 边界与顺手防回归）；
- 实现提交 fd7d69f53e9827877b6a29d67c067012ead6a7af（feat: implement mounts and distance infrastructure）已由用户在外部PowerShell提交，实现父提交 733940b4a5e278ae3eba11e5c6522b0f1832d6b4；距离下限结论为 DISTANCE_FLOOR_FIXED（提交前纠正，无audit fix commit）；检查点 `CP-04N-PRODUCTION-MOUNT-DISTANCE-INFRASTRUCTURE` 状态为 audited、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、worktree_commit_pending=true；2026-08-07 Grok 网页端经 GitHub 连接器独立静态审计最终结论 STATIC_AUDIT_PASSED（24个强制文件全部完成要求范围阅读，PARTIAL_READ=空、NOT_READ=空，14个强制审计章节全部PASSED，Blocking issues 无；正确生产文件路径为 scripts/sgs_engine/__init__.py；Grok未亲自执行 pytest、compileall 或本地虚拟环境，本地运行证据来自实现会话）；最终审计文档提交 fbeec9c5ad14e8f4b5da85672dab4a70f961bd4e（docs: finalize mount and distance audit milestone）已由用户在外部PowerShell提交；里程碑标签 milestone-b2-mount-distance-infrastructure-audited 已实际建立并推送（本地标签已由本轮亲自验证存在、GitHub 远程标签已由用户在外部PowerShell验证存在，标签在最终状态回填开始时指向 fbeec9c5ad14e8f4b5da85672dab4a70f961bd4e，当前标签目标以Git标签解析结果为准）。

本批次只验证双人生产切片：不构成完整武器技能完成、装备系统全部完成、正式单挑完成或里程碑 B 完成；完整武器技能、青釭剑真实 ignore_armor 调用、寒冰剑等伤害防止类武器效果、多人生产语义、多人死亡后的座次距离、武将技能、正式单挑、正式胜率模拟与里程碑 B 均保持 NOT PROVEN；“全部注册”不等于全部卡牌语义完成，也不等于正式游戏核心完成。

### 2.15 正式弃牌阶段＋权威回合循环基础设施批次（CP-04O）

正式160张牌堆上弃牌阶段与权威回合循环的生产批次，继续复用现有权威核心、既有阶段推进与严格重执行回放，不建立第二套状态机或回放系统：

- 正式阶段流收敛为单一权威回合循环：PREPARE→JUDGMENT→DRAW→PLAY→DISCARD→END→下一存活角色PREPARE；阶段推进由生产引擎根据权威状态决定，客户端不得通过负载声明 next_phase／next_player／skip_phase；
- 正式弃牌阶段：进入时从权威状态重新计算手牌数与手牌上限（默认等于当前体力值，`hand_limit_of`）；手牌数不超过上限时自动完成弃牌阶段并进入结束阶段，不开放伪弃牌动作；超限时采用“选择（select）＋取消选择（unselect）＋一次性提交（submit）”模型——UI逐张选择只是选择过程，被选牌在确认前仍属于该角色手牌、不逐张产生失牌／弃牌事件；提交时权威重算并验证数量恰好等于超限数、无重复、全部为当前角色真实手牌，所选牌作为同一次弃牌阶段操作一次性离开手牌（原子move_cards），事件以公开稳定的选择窗口ID表达同一批次；excess／hand_limit 不接受负载伪造，装备区／判定区／其他角色区域牌不可弃置，选择窗口打开后手牌或体力变化的旧动作失败关闭；弃置产生 CARD_MOVED＋CARD_LOST＋CARD_DISCARDED（reason=discard_phase，同一window_id），不产生 card_used／card_played；
- 延时锦囊阶段跳过接入回合推进：乐不思蜀命中跳过出牌阶段、兵粮寸断命中跳过摸牌阶段，跳过标记与理由只在当前回合生效，回合结束清理；
- 回合级状态生命周期：出牌阶段次数（【杀】使用次数）在当前角色自己的下一个出牌阶段开始时清零；回合结束清理阶段跳过标记、响应窗口、判定处理索引等回合级临时状态，不统一清空整局持久状态；
- 回合转交：当前角色回合结束后按座次转交下一名存活角色；胜利成立后不再启动下一回合；当前玩家在判定/出牌中死亡时按既有死亡与胜负规则安全结束，不继续让死亡角色摸牌、出牌或弃牌；
- 新增专项测试 `tests/test_sgs_production_turn_cycle_discard.py`（49项，覆盖标准回合顺序、批量弃置语义（一次性提交、确认前无状态变化、少选／多选／重复／装备／他人牌原子失败、stale选择、同一批次事件身份）与动作安全、延时锦囊跳阶段、每回合状态重置、下一行动者／死亡／胜利、严格回放与玩家可见隐私、回归）；旧批次相关测试已按正式弃牌阶段更新（延时锦囊60项、基本牌41项、防具42项、借刀85项、群体60项、单目标61项均随本批回归通过）；
- 完整 pytest 1889 passed（基线1840＋新专项49项；失败0、跳过0）；compileall 通过；源码完整性审计 scanned_file_count=121、defect_count=0、audit_item_count=55；检查点 `CP-04O-PRODUCTION-TURN-CYCLE-DISCARD-INFRASTRUCTURE` 状态为 audited、commit=b1afb1a613a45c630ae1e42975d276d62915e76d（实现提交）、checkpoint_commit=7aacd06cdfcf1725307061a3f5c03c233a2199f7（检查点文档提交）、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、milestone_tag=已建立标签 milestone-b2-turn-cycle-discard-infrastructure-audited（已实际建立并推送：本地标签已由本轮亲自验证存在，并在最终仓库状态回填开始时解析到 17246077776ef8a8c7f957706d60fd91e2c0a440，GitHub远程标签建立／推送事实来自用户外部PowerShell验证；当前标签目标以Git标签解析结果为准）、worktree_commit_pending=false（最终审计文档提交 17246077776ef8a8c7f957706d60fd91e2c0a440 已由用户在外部PowerShell提交）；独立静态审计已通过（STATIC_AUDIT_PASSED）。

### 2.16 正式武器技能完整化（CP-04P；提交前规则校准收尾，2026-08-08）

正式160张牌堆11种武器中8种／9张完成正式生产语义并计入完整实现（规则来源：
knowledge/三国杀卡牌效果.md 7.1—7.11、knowledge/三国杀基础术语与通用机制.md
第12节与结构化CSV攻击范围）：

- 【诸葛连弩】（2张，攻击范围1）：出牌阶段使用【杀】无次数限制；每次使用
  仍正常计数与结算；武器离开装备区后次数限制立即恢复；
- 【青釭剑】（1张，攻击范围2）：QINGGANG_LIFECYCLE_CONFIRMED（2026-08-07
  用户移动版实测确认）——起点为【杀】指定目标后的青釭剑武器技能实际生效
  时点（同一“指定目标后”时机武将技能优先于武器技能；项目无武将技能系统，
  武将技能调度保持 FUTURE_CHARACTER_SKILL_INTEGRATION_NOT_PROVEN，生命周期
  模型与该时序兼容）；终点A=目标以【闪】成功完成响应时该【闪】结算完成
  （实测：神赵云响应中把装备区【白银狮子】当【闪】使用/打出，不触发回复）；
  终点B=进入伤害时本次伤害结算完成（实测：伤害结算后由后续效果弃置【白银
  狮子】可正常回复）；target-scoped、slash-resolution-scoped、不移除防具
  实体、不永久改变装备状态、不跨下一独立牌结算；外部无名杀嵌套案例只记
  EXTERNAL_SUPPORTING_EVIDENCE_ONLY，不升级为移动版正式规则；生产实现已在
  闪结算完成与伤害结算应用完成两个清理点显式清除 ignore_armor，并由专项
  测试证明伤害结算完成后【过河拆桥】弃置【白银狮子】正常触发回复；
- 【寒冰剑】（1张，攻击范围2）：使用【杀】将要造成伤害时打开“防止伤害／
  放弃”窗口；防止后由攻击者选择目标手牌区＋装备区内的牌逐张弃置（基础
  术语第12节：牌=手牌区＋装备区，不含判定区）。2026-08-08 用户移动版实测
  确认逐张弃置语义：两张牌不是同时选择、同时弃置，而是一张一张弃置——
  第1张弃置及其状态变化（含白银狮子离区回复）完成后，根据此刻最新权威
  状态重新枚举第2张可弃牌再弃第2张；两次弃置是两个连续的正式弃置步骤，
  各自独立 enumerate→validate→apply，第二次不使用第一次弃置前的旧zone
  快照；目标只有1张时弃1张（第1张后无可弃牌直接完成）、没有牌时窗口不
  打开；第2步stale动作失败关闭且不回滚已合法完成的第1次弃置。防止路径
  不扣HP、不产生damage事件、不进入濒死或传导（防止在伤害真正发生前
  完成，HP不得先减后补）；放弃时按正常伤害结算；与贯石斧“一次选择两张
  →一次批量弃置代价”、CP-04O“一次选择多张→一次批量弃置”在生产语义上
  明确区分；
- 【古锭刀】（1张，攻击范围2）：判定时机为“造成伤害时”——游戏内正式卡牌
  文本“锁定技，当你使用【杀】对目标角色造成伤害时，若该角色没有手牌，
  则此伤害+1”（IN_GAME_CARD_TEXT_CONFIRMED）与用户移动版实测（神甘宁杀
  势王昶：指定时0手牌、伤害前目标因技能获得1张手牌→伤害时1手牌→不+1，
  USER_CONFIRMED_MOBILE_RULE）确认。生产实现：伤害管线前读取目标当前权威
  hand zone 动态判定，不使用指定目标时的旧快照；客户端不得提交
  weapon_damage_bonus／target_handless；与【酒】强化合并后进入统一防具伤害
  修正管线（【白银狮子】限伤按防具规则修正）；
- 【青龙偃月刀】（1张，攻击范围3）：被【闪】响应后若攻击者手牌中仍有【杀】，
  打开“继续使用一张杀／放弃”窗口；继续杀只能以原目标为目标并按正常【杀】
  流程结算；次数额度 USER_CONFIRMED_MOBILE_RULE（2026-08-08 用户移动版实测
  确认）：追杀不消耗普通出牌阶段【杀】次数额度——A.历史意义保留（每张追杀
  仍是一次真实【杀】使用，产生独立 CARD_USED 事件并进入完整结算），B.额度
  意义（`slash_used_counts` 不因追杀增加，普通手牌【杀】不被锁定）；每次被闪
  都可再次触发，连续多张由引擎自然实现，每一张追杀都不消耗额度；
- 【贯石斧】（1张，攻击范围3）：被【闪】响应后若攻击者手牌区＋装备区合计
  至少2张，打开“强制命中／放弃”窗口；强制命中由攻击者选择自己手牌区＋
  装备区合计2张弃置后按原【杀】参数造成伤害（【杀】本体已因【闪】完成
  结算，不再重复完成结算），进入统一伤害管线（濒死、救援、属性传导）；
  自身排除 USER_CONFIRMED_MOBILE_RULE（2026-08-08 用户移动版实测确认）：
  当前正在发动技能的【贯石斧】实体自身不能作为两张代价之一（候选=手牌＋
  其他合法装备，枚举层排除＋提交时权威验证，伪造提交失败关闭；通用“牌=
  手牌区＋装备区”区域规则不变）；两张合法代价仍是一次性批量弃置；
- 【朱雀羽扇】（1张，攻击范围4）：普通【杀】进入使用流程并完成目标指定后
  枚举提供“转火杀”动作（USER_CONFIRMED_MOBILE_UI_TIMING：转换选择早于
  防具检查／闪响应／damage／连环等依赖Slash最终属性的结算），转火杀从
  使用入口开始按火【杀】身份结算
  （火属性伤害、不被藤甲普通杀免疫、火属性伤害+1正常生效、转化未提供
  颜色按基础术语20.6记为“无”不触发仁王盾黑杀无效化）。2026-08-08 用户
  移动版实测确认借刀入口：被【借刀杀人】要求使用【杀】时同样可以发动
  朱雀羽扇把普通【杀】转换为火【杀】（借刀选杀窗口提供普通使用／转火杀
  两个动作，转换后按火杀身份结算；未转换的普通杀仍按普通杀身份接受防具
  无效化检查；武器在选择前失去则旧转换动作失败关闭）；
- 【麒麟弓】（1张，攻击范围5）：本次【杀】确定将造成伤害（统一防具解析后
  最终伤害>0）时，在 HP 扣减与 DAMAGE event 之前打开“弃置目标装备区一张
  坐骑牌／放弃”选择窗口（USER_CONFIRMED_MOBILE_RULE＋IN_GAME_CARD_TEXT_
  CONFIRMED，2026-08-08 用户移动版卡面文本与牌局记录确认：麒麟弓触发/选择/
  弃置坐骑发生在本次伤害真正结算、HP扣减之前）；若发动，坐骑正式离开装备区
  并完成对应牌移动/事件（先于DAMAGE），然后本次伤害正式结算、HP扣减／DAMAGE
  event，HP<=0 再进入dying/rescue；目标无坐骑或未造成伤害（被防止/无效）时
  不打开窗口；已合法进入结算的【杀】不因麒麟弓导致距离变化而倒退取消；

- 【丈八蛇矛】（1张，攻击范围3）：PARTIAL＋VIRTUAL_CARD_SUBCARD_LIFECYCLE_
  RULE_GAP——两张手牌当作普通【杀】使用或打出（7.8 当前确认），最小正式
  虚拟牌表示已实现并通过专项测试（虚拟杀不进入实体牌目录，身份为确定性
  合成标识，材料非弃置代价、随本次使用/打出进入弃牌堆、不产生
  CARD_DISCARDED，颜色按7.8当前确认组合规则、仁王盾按颜色判断，出牌使用
  消耗正常额度，决斗/南蛮响应支持虚拟打出，材料对只通过不透明句柄暴露，
  forged/stale失败关闭）；但材料在“使用/打出”时的精确zone生命周期时点
  （A.先作为subcards进入PROCESSING、结算完成后再进入弃牌堆；B.开始结算前
  直接进入弃牌堆）在项目Knowledge没有确认通则，暂不计COMPLETE、不计入
  完整语义统计，待用户确认后恢复；

其余3种武器保持 PARTIAL（rule_spec.skill_status=partial，集中式门禁失败关闭）：

- 【雌雄双股剑】（1张，攻击范围2）：规则本身已知（异性=性别不同的两名
  角色），不是规则缺口；未完成原因是生产数据模型尚无权威武将性别来源
  （DATA_MODEL_GAP: CHARACTER_GENDER_METADATA_NOT_AVAILABLE——PlayerState
  无性别字段，客户端动作不得自行提交目标性别作为规则真相）；若后续建立
  武将实体元数据的 gender 字段则按该权威来源接入；
- 【方天画戟】（1张，攻击范围4）：双人环境“至多3个目标”不会产生额外目标，
  但多人多目标正式语义未进入生产实现；安全接入依赖多人生产基础环（N人
  回合推进、濒死救援顺序、死亡/胜负边界均仍为双人假设），属多人生产
  基础设施缺口（infrastructure gap），双人环境技能不可产生额外目标不等于
  技能已实现，保持PARTIAL；

- 新增专项测试 `tests/test_sgs_production_weapon_skills.py`（70项，覆盖武器
  清单与状态、连弩次数豁免与失去后恢复、青釭剑真实 ignore_armor 生命周期
  （抑制仁王盾／藤甲／白银狮子／八卦阵、闪结算与伤害结算两个清理点、伤害
  结算完成后白银狮子恢复回复）、古锭刀“造成伤害时”判定时机（含指定后伤害前获得/失去手牌的边界回归）、朱雀羽扇转火杀
  与藤甲/仁王交互、麒麟弓伤害后弃坐骑窗口与动作安全、贯石斧弃2张强制命中
  （含不足2张不开窗、放弃无伤害、伪造与跨角色拒绝）、寒冰剑逐张弃置（含顺序两步窗口、第1张弃置产生真实事件、第2次基于最新
  权威状态重新枚举、第1张弃置造成白银狮子离区回复后第2次选择看到变化、
  目标只有1张弃1张、放弃走正常伤害、第2步stale不回滚）、青龙偃月刀继续杀
  （含无杀不开窗、放弃无伤害、追杀不消耗普通出牌阶段杀额度[USER_CONFIRMED_
  MOBILE_RULE：额度计数不变／连续追杀链／每张追杀独立CARD_USED与结算／
  无残留锁定]）、朱雀羽扇×借刀转换（含借刀时普通／转火杀
  双动作、转火杀按火杀身份结算、与藤甲真实交互、未装备朱雀不转换、武器
  失去后旧动作stale、严格回放与篡改拒绝）、贯石斧自身排除（含自身不在合法
  候选、伪造提交自身失败、自身＋另一张组合原子失败状态不变、手牌＋其他
  装备合法代价仍一次批量弃置并造成伤害）、方天画戟双人正常杀、雌雄/丈八
  /方天集中式门禁失败关闭、跨系统距离／守恒／严格回放／篡改拒绝）；借刀
  武器系统新增7项朱雀借刀专项（`tests/test_sgs_production_borrowed_sword_weapon_system.py`），
  旧批次相关测试已按新武器状态更新（武器门禁断言按 COMPLETE/PARTIAL 新
  清单更新）；
- 完整 pytest 1974 passed（基线1889＋70项武器专项＋7项借刀朱雀专项；失败0、
  跳过0）；
  compileall 通过；源码完整性审计 scanned_file_count=122、defect_count=0、
  audit_item_count=55；完整语义统计35种／157张（原27种／148张＋8种／9张
  COMPLETE武器，以registry真实重算；丈八因规则缺口暂不计入）；unsupported_rules=1 保持整局哨兵定义
  （不是精确缺项数，见第4节）；检查点 `CP-04P-PRODUCTION-WEAPON-SKILL-COMPLETION`
  状态为 committed_pending_audit、independent_audit_done=false、
  audit_conclusion=NOT_AUDITED_YET、milestone_tag=null、worktree_commit_pending=
  true；实现提交 f0a50ce9ace71c5bf0a22540fbdca9e03aa918b3（feat: implement verified production weapon skills）与检查点文档提交 c30b26880b947217d64304ce430d32030b42941e（docs: record weapon skill completion checkpoint）均已由用户在外部PowerShell提交；2026-08-08 完成独立静态审计（CP_04P_INDEPENDENT_STATIC_AUDIT）：Grok 网页端经 GitHub 连接器对审计分支 deepseek-audit-weapon-skill-completion 上的精确目标 c30b26880b947217d64304ce430d32030b42941e 进行只读静态审计（implementation f0a50ce9ace71c5bf0a22540fbdca9e03aa918b3，baseline ef340c42e180ab14832b291bc0fc83f449a771a6）；16个强制审计章节全部PASSED，BLOCKING_FINDINGS=NONE、NONBLOCKING_FINDINGS=NONE；NOT_READ=none of the mandatory implementation/docs files；PARTIAL_READ=仅production_batch.py非武器外围部分以及非关键docs全文（武器相关changed hunks、调用链、pending、gate及关键状态均已完整追踪，不构成关键审计缺口）；独立复算 registered=38种/160张、complete semantics=35种/157张、complete weapons=8种/9张、partial weapons=3种/3张、unregistered=0种/0张；PARTIAL分类均被审计确认合理且真正fail-closed。Grok未亲自执行pytest、compileall或本地虚拟环境；本地运行证据（pytest 1953 passed 等）来自本地实现会话，两类证据不得混写。检查点状态为 audited、independent_audit_done=true、audit_conclusion=STATIC_AUDIT_PASSED、milestone_tag=milestone-b2-weapon-skills-audited（已实际建立并指向 398ea58c9006ee9141ea1acfba35f6d9c497be48）、worktree_commit_pending=false；final_doc_commit=08d78cb6fed86360d647728a6f70422326918ff2 已真实回填；milestone_tag_verified=true、milestone_tag_target_resolution=git_tag_resolution。


### 2.17 整仓敌对式总审计定向修复（WHOLE_REPO_AUDIT_REMEDIATION_1；实现提交后 checkpoint 记录）

- remediation-1 targeted independent re-audit：结论 REMEDIATION_REAUDIT_FAILED（HISTORICAL/AS-OF：R1 实现提交后文档回填时为
  NOT_AUDITED_YET；CURRENT LIVE REF：随后 remediation-1 targeted independent re-audit 结论为 REMEDIATION_REAUDIT_FAILED，
  R1 未获得通过的独立审计，该失败是 WHOLE_REPO_AUDIT_REMEDIATION_2 的启动依据）；不得把 R1 改写为 PASSED。
- 原总审计：CP04L_TO_CP04P_WHOLE_REPO_ADVERSARIAL_AUDIT，最终结论 WHOLE_REPO_AUDIT_FAILED。原finding：
  G-001 MAJOR DEAD_SEAT_DISTANCE_AND_TARGET_VALIDITY_LEAK；G-002 MAJOR COMPLETE_RULE_SOURCE_NOT_INDEPENDENTLY_CLOSED；
  G-003 MINOR ZHANGBA_PARTIAL_ENUMERATION_SPLIT_BRAIN；G-004 MINOR FINAL_DOC_AND_GIT_STATE_DRIFT；
  G-005 MINOR HISTORICAL_RULE_TEXT_NOT_FULLY_PROPAGATED；N-001 QILIN_DYING_ORDER_REQUIRES_RULE_CONFIRMATION
  （用户移动版实测证明麒麟弓当前生产timing确实错误，N-001 升级为实际修复项）。不得把原审计改写成 PASSED。
- 修复结果：
  - G-001：`base_seat_distance` 改为存活角色环（alive-seat ring）索引计算；`is_valid_slash_target` 拒绝死亡目标；
    3/4/5人死亡座次回归（中间死亡收缩、多死亡、相邻收缩、dead participant fail-closed、坐骑修正与下限）；
    `multi_player_production_proven` 仍为 false。
  - 麒麟弓：游戏内正式文本（IN_GAME_CARD_TEXT_CONFIRMED）＋USER_CONFIRMED_MOBILE_RULE；正确顺序为
    Slash确定将造成伤害 → Qilin choice → 坐骑离区 → HP扣减/DAMAGE → DYING；不再写旧 DAMAGE → Qilin。
  - 诸葛连弩：来源等级 IN_GAME_CARD_TEXT_CONFIRMED（生产语义未改）。
  - 丈八蛇矛：PARTIAL/fail-closed；不再在正式公共枚举中先生成 virtual:zhangba:* candidate 再撞公共实体验证器；
    global virtual: 豁免仍不存在。
  - G-004/G-005：当前 live docs/comments 已清理（CP-04P tag 已实际存在并解析到 398ea58c9006ee9141ea1acfba35f6d9c497be48、
    CP-04L live tag 当前解析到 fc3df95202b23dccfd9abf5e476485a224d6fc2c、`__init__.py` 弃牌阶段/武器技能状态、麒麟弓时序表述、
    discard phase 批量弃置、Zhuque borrowed 无旧“未提供转换”表述）；历史 as-of 记录保留未改。
- G-002 边界：针对审计明确点名的诸葛连弩、麒麟弓，独立来源证据已补齐；不得写 G-002 global finding =
  independently re-audited closed，也不得写 WHOLE_REPO_AUDIT_PASSED（HISTORICAL/AS-OF：R1 修复时 targeted independent re-audit 尚未发生；CURRENT LIVE REF：后续 remediation-1 targeted independent re-audit 结论为 REMEDIATION_REAUDIT_FAILED）。
- 验证证据（implementation/regression evidence，不是新的独立审计结论）：完整 pytest 1966 passed（0 failed、0 skipped、
  0 xfailed）；compileall passed；source integrity scanned_file_count=122、defect_count=0、audit_item_count=55；JSON passed；
  SHA-256 passed；git diff --check passed；git ls-files -u empty；统计 registered 38种/160张、complete semantics 35种/157张、
  COMPLETE weapons 8种/9张、PARTIAL weapons 3种/3张、unregistered 0种/0张。
- 门禁保持：authoritative_full_game_core=false、formal_run_ready=false、formal_duel_no_skill_ready=false、
  multi_player_production_proven=false、milestone_b_complete=false、unsupported_rules=1、approximation_count=0。
- 检查点状态：`WHOLE_REPO_AUDIT_REMEDIATION_1` 为 committed_pending_audit、commit=implementation_commit=
  f1731b95199165a3449f1a0ce84d9facfc1b41c5（fix: remediate whole-repo audit findings）、implementation_parent=
  398ea58c9006ee9141ea1acfba35f6d9c497be48、checkpoint_commit=null（尚未产生）、milestone_tag=null、
  worktree_commit_pending=true；independent_audit_done=true、audit_conclusion=REMEDIATION_REAUDIT_FAILED
  （HISTORICAL/AS-OF：R1 文档回填时为 independent_audit_done=false、audit_conclusion=NOT_AUDITED_YET；
  CURRENT LIVE REF：remediation-1 targeted independent re-audit 已进行且结论为 REMEDIATION_REAUDIT_FAILED，
  R1 未获得通过的独立审计，不得改写为 PASSED）。
- R2（WHOLE_REPO_AUDIT_REMEDIATION_2，remediation-1 targeted independent re-audit 失败后的第二轮；实现提交后 checkpoint 记录）：
  G-001 dead-self 边界（base_seat_distance/effective_distance/actual_distance/is_target_within_distance 对死亡参与者
  统一 fail-closed，先验证参与者存在与存活再应用 alive self→0）；R1-NEW-001 Qilin pending 改保存
  resolution.final_amount（不再使用 pre-armor base amount；weapon_choice tuple 移除 amount 职责）；
  R1-NEW-002 青釭 ignore_armor 清除绑定真正 damage completion（Qilin 窗口期间保持防具无效状态，
  amount==0 防止路径在 resolution 结束清理，dodge path 原清理不变）；G-004 CP-04L live tag 当前解析
  fc3df95202b23dccfd9abf5e476485a224d6fc2c 与 HISTORICAL/AS-OF 分层；G-005 stale comments 清理
  （__init__.py discard batch 单一表述、_PendingSlash 古锭快照注释删除、Zhuque borrowed 无旧表述）；
  G-002 source provenance inventory（见 2.18 节）：用户已补齐原 8 项游戏内正式文本并全部升级为
  IN_GAME_CARD_TEXT_CONFIRMED（决斗另有 USER_CONFIRMED_MOBILE_RULE），G-002 达到
  G-002_SOURCE_GAP_LOCALLY_RESOLVED_PENDING_INDEPENDENT_REAUDIT（HISTORICAL/AS-OF：R2 实现完成、
  独立 re-audit 尚未发生时的本地状态；CURRENT：remediation-2 targeted independent re-audit 已确认 G-002=CLOSED）；
  验证证据（implementation/regression evidence，不是独立审计结论）：完整 pytest 1974 passed（0 failed、0 skipped、
  0 xfailed）；compileall passed；source integrity scanned_file_count=122、defect_count=0、audit_item_count=55；
  JSON passed；SHA-256 38 entries mismatch=0；git diff --check passed；git ls-files -u empty。
  实现提交 e63b40ac1690e03315fd3e0734d5723fb80d5182（fix: complete second whole-repo audit remediation，父提交
  4aafd95...）已由用户在外部PowerShell创建；检查点状态：status=committed_pending_audit、checkpoint_commit=null
  （尚未产生）、milestone_tag=null、worktree_commit_pending=true；independent_audit_done=true、
  audit_conclusion=REMEDIATION_2_REAUDIT_FAILED（HISTORICAL/AS-OF：R2 文档回填时为 NOT_AUDITED_YET；CURRENT LIVE REF：
  remediation-2 targeted independent re-audit 已进行且结论为 REMEDIATION_2_REAUDIT_FAILED，原因是当时 G-004/G-005 仍
  OPEN；R2 re-audit 已确认 CLOSED 项 G-001、G-002、G-003、QILIN_TIMING_BUG、R1-NEW-001、R1-NEW-002 保持，但 R2 整体
  不视为 PASSED，不得改写为 PASSED）。原整仓审计 WHOLE_REPO_AUDIT_FAILED、remediation-1 re-audit
  REMEDIATION_REAUDIT_FAILED、remediation-2 re-audit REMEDIATION_2_REAUDIT_FAILED 均保持，
  不得写任何 PASSED／WHOLE_REPO_AUDIT_PASSED。
- R3（WHOLE_REPO_AUDIT_REMEDIATION_3，remediation-2 targeted independent re-audit 失败后的最小收尾轮；实现提交后
  checkpoint 记录）：
  G-004——CP-04L 旧 ba64b750... 所有历史引用明确标记 HISTORICAL/AS-OF，current/live 语态统一为
  fc3df95202b23dccfd9abf5e476485a224d6fc2c（真实 Git tag 未移动）；
  G-005——清除当前非历史 stale（Zhuque borrowed“未提供转换”旧说明、weapon skill test header 旧 COMPLETE/PARTIAL 状态、
  ignore_armor“无真实武器调用者”旧说明、turn-cycle discard test header 旧“逐张正式弃置”说明）；
  R2-NEW-001——weapon_choice 运行时二元结构与 annotation 统一为 tuple[str, str] | None（静态契约修复，无 gameplay 语义变化）。
  R2 re-audit 已确认 CLOSED 项（G-001、G-002、G-003、QILIN_TIMING_BUG、R1-NEW-001、R1-NEW-002）保持，未重新设计或重构。
  验证证据（implementation/regression evidence，不是独立审计结论）：完整 pytest 1974 passed（0 failed、0 skipped、
  0 xfailed）；compileall passed；source integrity scanned_file_count=122、defect_count=0、audit_item_count=55；
  JSON passed；SHA-256 38 entries mismatch=0；git diff --check passed；git ls-files -u empty。
  实现提交 9c63496e7f34430d8aff3c23e9afc5b5c4482557（fix: close remaining whole-repo audit findings，父提交
  3121a300...）已由用户在外部PowerShell创建；检查点状态：status=committed_pending_audit、checkpoint_commit=null
  （尚未产生）、milestone_tag=null、worktree_commit_pending=true；independent_audit_done=true、
  audit_conclusion=REMEDIATION_3_REAUDIT_FAILED（HISTORICAL/AS-OF：R3 文档回填时为 NOT_AUDITED_YET；CURRENT LIVE REF：
  remediation-3 targeted independent re-audit 已进行且结论为 REMEDIATION_3_REAUDIT_FAILED，原因是当时 G-004 仍有
  ENGINE_STATUS §8 CP-04L tag-target 无限定漏项与 R3-NEW-001 G-002 状态矛盾；R3 re-audit 已确认 G-005=CLOSED、
  R2-NEW-001=CLOSED，并确认 G-001/G-002/G-003/QILIN_TIMING_BUG/R1-NEW-001/R1-NEW-002=NO_REGRESSION，但 R3 整体
  不视为 PASSED，不得改写为 PASSED）。历史四次失败结论（WHOLE_REPO_AUDIT_FAILED／REMEDIATION_REAUDIT_FAILED／
  REMEDIATION_2_REAUDIT_FAILED／REMEDIATION_3_REAUDIT_FAILED）均保持，不得写任何 PASSED／WHOLE_REPO_AUDIT_PASSED。
- R4（WHOLE_REPO_AUDIT_REMEDIATION_4，remediation-3 targeted independent re-audit 失败后的 docs-only 治理收尾轮；
  实现提交后 checkpoint 记录）：
  G-004——ENGINE_STATUS §8“当前目录是 Git 工作树。已确认检查点”中 CP-04L 条目最后一个 current tag-target 漏项修正
  （HISTORICAL/AS-OF：当时标签状态记录为指向 ba64b750...；CURRENT LIVE REF：当前 Git tag 解析为
  fc3df95202b23dccfd9abf5e476485a224d6fc2c，以当前 Git ref 解析结果为准；真实 Git tag 未移动）；全仓 ba64b750
  tag-target 陈述均明确 HISTORICAL/AS-OF；
  R3-NEW-001——G-002 状态分层（HISTORICAL/AS-OF：R2 implementation 完成但独立 re-audit 尚未发生时状态为
  G-002_SOURCE_GAP_LOCALLY_RESOLVED_PENDING_INDEPENDENT_REAUDIT；CURRENT：R2 targeted independent re-audit 已明确
  G-002=CLOSED；R2 整体历史结论仍为 REMEDIATION_2_REAUDIT_FAILED，因当时 G-004/G-005 仍 OPEN，不得把 R2 整体
  FAILED 误写成 G-002 仍 OPEN）。
  R3 已确认 CLOSED（G-005、R2-NEW-001）与 NO_REGRESSION（G-001、G-002、G-003、QILIN_TIMING_BUG、R1-NEW-001、
  R1-NEW-002）保持；本轮无 runtime/gameplay 修改（runtime/gameplay files modified=0），未重新运行 pytest
  （引用 R3 已记录的 1974 passed 作为实现回归证据）。
  验证（docs 治理证据）：JSON parse 通过；SHA-256 38 entries mismatch=0；docs consistency scan current-state
  contradiction=0；git diff --check passed；git ls-files -u empty。
  实现提交 5eb367599e9d7deb26220cfff8b81144d0d88eff（docs: close remaining whole-repo audit governance findings，
  父提交 6bef086...）已由用户在外部PowerShell创建；检查点状态：status=committed_pending_audit、
  independent_audit_done=false、audit_conclusion=NOT_AUDITED_YET、checkpoint_commit=null（尚未产生）、
  milestone_tag=null、worktree_commit_pending=true；独立 re-audit 尚未进行。历史四次失败结论均保持，
  不得提前写 REMEDIATION_4_REAUDIT_PASSED 或 WHOLE_REPO_AUDIT_PASSED。


### 2.18 G-002 全 35 COMPLETE source provenance inventory（WHOLE_REPO_AUDIT_REMEDIATION_2）

- 说明：本清单区分 implementation semantic status 与 rule source verification status；
  不得把“代码测试全绿”表述为“规则源已验证”，也不得把规则源未确认表述为“代码一定不完整”。
- 2026-08-09 新增用户确认通则（USER_CONFIRMED_RULE_TEXT＋USER_CONFIRMED_MOBILE_RULE）：【杀】牌名/子类型通则（基础术语20.12）——
  普通／火／雷【杀】均属规则总称【杀】；规则文本仅写“【杀】”未进一步限定时默认包含三种（使用/打出/响应/要求一张【杀】均可满足）；
  明确写“普通【杀】”“火【杀】”“雷【杀】”时只指对应子类（明确限定优先）；转化规则同理（“当作普通【杀】”只能生成普通杀，
  “当作【杀】”且无其他特殊限制时可在三种中选择合法具体结果）；历史文本结合当时牌池解释，不得倒推旧版本可转化尚不存在的属性杀。
  用户移动版决斗实测确认：决斗要求“打出一张【杀】”时，雷杀、火杀均可作为合法响应牌。生产实现已按 `SLASH_CARD_KEYS=(sgs_basic_sha|sgs_basic_huosha|sgs_basic_leisha)`
  统一决斗／南蛮／借刀／青龙追杀／杀使用等入口的 family 语义，不把 generic【杀】硬编码为普通杀。
- IN_GAME_CARD_TEXT_CONFIRMED（游戏内正式卡面文本，用户已提供）：
  2026-08-08 移动版：诸葛连弩（7.1，锁定技，你使用【杀】无次数限制）、古锭刀（7.5，锁定技，当你使用【杀】对目标角色造成伤害时，
  若该角色没有手牌，则此伤害+1）、麒麟弓（7.11，当你使用【杀】对目标角色造成伤害时，你可以弃置其装备区里的一张坐骑牌）。
  2026-08-09 用户提供移动版“军争卡组/卡牌说明”截图补齐其余 8 项：杀（3.1，出牌阶段，对你攻击范围内的一名其他角色使用。
  若命中，则对目标角色造成1点伤害）、雷杀（3.2，……1点雷电伤害）、火杀（3.3，……1点火焰伤害）、过河拆桥（4.1，出牌阶段，
  对一名区域里有牌的其他角色使用。你弃置其区域里的一张牌）、决斗（4.3，出牌阶段，对一名其他角色使用。由该角色开始，
  你与其可以轮流响应此牌——打出一张【杀】。然后首先未打出【杀】的角色受到另一名角色造成的1点伤害）、无中生有（4.7，
  出牌阶段，对你使用。你摸两张牌）、桃园结义（4.11，出牌阶段，对所有角色使用。每名目标角色回复1点体力）、仁王盾（8.2，
  锁定技，黑色的【杀】对你无效）。以上均已同步 Knowledge（三国杀卡牌效果.md）与两个结构化 CSV source 字段
  （三国杀牌堆数据.csv notes；三国杀卡牌结构化数据.csv confidence_status=当前确认）。
- USER_CONFIRMED_MOBILE_RULE（用户移动版实测确认）：青釭剑（7.2.1 QINGGANG_LIFECYCLE_CONFIRMED）、
  寒冰剑（7.3.1 逐张弃置实测）、青龙偃月刀（7.6.1 追杀不耗普通PLAY额度实测）、贯石斧（7.7.1 自身不能作为代价实测）、
  朱雀羽扇（7.10.1 借刀转换＋USER_CONFIRMED_MOBILE_UI_TIMING 目标确定后转换）、决斗（4.3，2026-08-09 用户移动版实际牌局记录：
  目标先响应、双方交替打出【杀】、普通/火/雷杀均可满足“打出一张【杀】”）。
- USER_CONFIRMED_RULE_TEXT / 用户明确规则确认（仓库存在可追溯确认记录）：
  闪（3.4）、桃（3.5）、酒（3.6）、顺手牵羊（4.2）、火攻（4.4）、南蛮入侵（4.8）、万箭齐发（4.9）、无懈可击（4.12）、
  乐不思蜀（5.1，游戏内截图依据）、兵粮寸断（5.2，游戏内截图依据）、闪电（5.3，游戏内截图依据）、铁索连环（4.5.1 用户确认口径
  2026-08-04）、借刀杀人（4.6.1/4.6.3 用户确认口径 2026-08-04）、五谷丰登（4.10.1 用户确认口径 2026-08-04）、
  八卦阵（8.1）、白银狮子（8.3）、藤甲（8.4）、攻击坐骑（9.1）、防御坐骑（9.2）——资料状态为“当前确认”。
- USER_OR_EXTERNAL_SUMMARY_UNVERIFIED：无剩余项（此前 8 项已于 2026-08-09 全部升级为 IN_GAME_CARD_TEXT_CONFIRMED）。
- USER_RULE_CONFIRMATION_REQUIRED：无剩余项（原 8 项清单已全部获得所要求证据，见上方 IN_GAME_CARD_TEXT_CONFIRMED 组）。
- G-002 结论（分层）：HISTORICAL/AS-OF——R2 实现完成、独立 re-audit 尚未发生时本地结论为
  G-002_SOURCE_GAP_LOCALLY_RESOLVED_PENDING_INDEPENDENT_REAUDIT（35 项 declared COMPLETE 的 source provenance
  已全部具备可追溯确认来源（IN_GAME_CARD_TEXT_CONFIRMED／USER_CONFIRMED_MOBILE_RULE／USER_CONFIRMED_RULE_TEXT·当前确认），
  本地不存在 USER_OR_EXTERNAL_SUMMARY_UNVERIFIED 或 MODEL_INFERENCE 支撑 COMPLETE 规则真值，最终关闭当时仍需
  同一 5.6 Sol independent targeted re-audit）；CURRENT——remediation-2 targeted independent re-audit 已实际完成并
  明确判定 G-002=CLOSED；不得把 R2 整体（REMEDIATION_2_REAUDIT_FAILED，因当时 G-004/G-005 仍 OPEN）与
  G-002 单项 CLOSED 混为一谈。
- implementation_status=COMPLETE 与 rule_source_verified 在本清单中独立表达；未因 source 缺口改变生产实现或 registry gate。

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
- 通过生产批处理会话执行【借刀杀人】与11种武器牌本体路径：主动装备与同槽替换（三个最小装备事件）、攻击范围动态计算、两次目标检测、第一目标以HMAC-SHA256不透明句柄选择实体杀或拒绝、强制使用【杀】与按角色出杀计数、拒绝后武器直接进入使用者手牌、挂起与终局清理、武器专属技能集中式失败关闭门禁与严格规则重执行。
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
# 1503 passed；失败0、跳过0（在1463基础上新增40项CP-04J属性伤害传导基础设施生产路径测试）
# 1543 passed；失败0、跳过0（在1503基础上新增40项CP-04J审计残项关闭测试：36项链事件契约＋4项prevented_zero控制流与文档检查）
# 1635 passed；失败0、跳过0（在1543基础上新增80项借刀＋武器专项与12项装备事件契约测试；CP-04K 实现提交时验收）
# 1649 passed；失败0、跳过0（在1635基础上新增14项CP-04K审计残项N1-N3关闭测试：4项借刀武器专项＋10项装备事件reason封闭枚举契约；最终独立复审有效完整重跑 1649 passed）
# 1707 passed；失败0、跳过0（在1649基础上新增35项CP-04L延时锦囊专项测试与23项判定事件契约测试；CP-04L 实现提交时验收，提交哈希 `35c06bd50a431a62e7c3ad01d10384bf6884c403`，独立审计尚未进行）
# 1724 passed；失败0、跳过0（在1707基础上新增17项CP-04L第一次独立审计修复测试：B1 reshuffle 脱敏与哈希旁路、viewer_id 契约、N1–N9 关闭；审计修复提交 96f536e1f392fd97faf61518a849a0d515b6a82e）
# 1733 passed；失败0、跳过0（在1724基础上新增9项CP-04L第二次最终复审修复测试：B1-a state_hash 递归脱敏攻击、B1-b 行动者手牌攻击、B1-c tiesuo_recast 隐藏获得攻击、判定窗口行动者投影、公开/隐藏获得成对回归、judgment_entry_indices 清理与陈旧失败关闭、zone-choice 窗口投影、N5 语义层重执行篡改；最终修复提交 `eeeaf558cdaeeea0eb90456f907f83dce52286f3`（fix: harden player-visible replay privacy）；Grok 网页端独立静态审计 STATIC_AUDIT_PASSED（未亲自运行 pytest，运行类证据来自本地修复会话）；最终审计结论 AUDIT_PASSED（2026-08-06，status=audited、independent_audit_done=true、audit_conclusion=AUDIT_PASSED）；文档收口提交 `ba64b750fabd99f2bfc93697cea83e1272216d02` 后里程碑标签已实际建立（HISTORICAL/AS-OF：当时本地与 GitHub 远程标签均已验证存在并指向该提交）、worktree_commit_pending=false））
# 1799 passed；失败0、跳过0（在1733基础上新增42项CP-04M防具专项测试与24项防具事件契约测试；CP-04M 工作树验收）
# 1832 passed；失败0、跳过0（在1799基础上新增33项CP-04N坐骑与距离专项测试；CP-04N 工作树验收）
# 1838 passed；失败0、跳过0（在1832基础上新增6项CP-04N距离下限阻塞性复核边界测试；CP-04N 工作树验收）
# 1840 passed；失败0、跳过0（在1838基础上新增2项CP-04N距离下限纠正测试；DISTANCE_FLOOR_FIXED；CP-04N 工作树验收，尚未由用户提交）
# 1889 passed；失败0、跳过0（在1840基础上新增49项CP-04O弃牌阶段＋权威回合循环专项测试；其中批量弃置语义修正把逐张弃置改为选择＋一次性提交，专项测试由43项增至49项；CP-04O 实现提交 b1afb1a613a45c630ae1e42975d276d62915e76d与检查点文档提交 7aacd06cdfcf1725307061a3f5c03c233a2199f7 均已由用户在外部PowerShell提交；2026-08-07 Grok 网页端独立只读静态审计最终结论 STATIC_AUDIT_PASSED（Grok 未亲自运行 pytest／Git／本地虚拟环境，1889 passed 等运行结果来自本地实现会话）；最终审计文档提交 17246077776ef8a8c7f957706d60fd91e2c0a440（docs: finalize turn cycle and discard audit milestone）已由用户在外部PowerShell提交；里程碑标签 milestone-b2-turn-cycle-discard-infrastructure-audited 已实际建立并推送（本地标签已由本轮亲自验证存在并在最终仓库状态回填开始时解析到 17246077776ef8a8c7f957706d60fd91e2c0a440，GitHub远程标签建立／推送事实来自用户外部PowerShell验证；当前标签目标以Git标签解析结果为准）
# 1911 passed；失败0、跳过0（在1889基础上新增22项CP-04P正式武器技能专项测试：诸葛连弩、青釭剑、古锭刀、方天画戟（双人范围）4种武器完成生产语义，其余7种保持失败关闭；CP-04P 工作树验收，尚未由用户提交）
# 1933 passed；失败0、跳过0（在1889基础上新增44项CP-04P正式武器技能专项测试：8种武器COMPLETE——诸葛连弩、青釭剑（QINGGANG_LIFECYCLE_CONFIRMED）、寒冰剑、古锭刀、青龙偃月刀、贯石斧、朱雀羽扇、麒麟弓；雌雄双股剑、丈八蛇矛、方天画戟3种保持PARTIAL失败关闭；CP-04P 工作树验收记录，尚未由用户提交，独立审计尚未进行）
# 1942 passed；失败0、跳过0（在1933基础上新增9项提交前规则修正测试：寒冰剑逐张弃置状态边界2项（顺序两步窗口／白银狮子离区状态变化）、朱雀羽扇×借刀转换7项（普通不转换／转火杀／藤甲交互／未装备不转换／武器失去后stale／严格回放与篡改）；寒冰剑由批量弃置改为逐张顺序弃置，朱雀羽扇借刀强制杀可转换火杀，均为2026-08-08用户移动版实测确认；CP-04P 工作树验收记录，尚未由用户提交，独立审计尚未进行）
# 1949 passed；失败0、跳过0（在1942基础上新增7项最终规则确认测试：青龙偃月刀追杀不消耗普通出牌阶段杀额度4项（额度计数不变／无残留锁定／连续追杀链不耗额度／每张追杀独立CARD_USED与结算）、贯石斧自身不能作为发动代价3项（自身不在合法候选／伪造提交自身与自身＋另一张组合原子失败状态不变／手牌＋其他装备合法代价仍一次批量弃置并造成伤害）；均为USER_CONFIRMED_MOBILE_RULE（2026-08-08用户移动版实测确认）；CP-04P 工作树验收记录，尚未由用户提交，独立审计尚未进行）
# 1951 passed；失败0、跳过0（在1949基础上新增2项提交前边界测试：贯石斧仅剩自身＋1张手牌不得打开弃牌窗口、submit 时权威验证拒绝贯石斧自身（整批不移动）；贯石斧自身排除在枚举、选择、提交三层一致生效；CP-04P 工作树验收记录，尚未由用户提交，独立审计尚未进行）
# 1957 passed；失败0、跳过0（在1951基础上新增6项丈八蛇矛专项测试：两手牌转虚拟杀与材料原子性、正常杀额度、forged/stale/跨玩家拒绝、严格回放与篡改、决斗响应虚拟打出、南蛮响应虚拟打出；丈八蛇矛由PARTIAL升级为COMPLETE，完整语义36种／158张；CP-04P 工作树验收记录，尚未由用户提交，独立审计尚未进行）
# 1959 passed；失败0、跳过0（在1957基础上古锭刀触发时机修正：删除基于旧错误规则“使用杀时锁定”的测试1项，新增伤害时判定回归3项——指定时0手牌/伤害前获得1张手牌→不+1（用户实测核心回归）、指定时有手牌/伤害前失去最后1张→+1、replay中weapon_damage_bonus与伤害时权威状态一致且篡改被strict replay拒绝；古锭刀判定改为伤害时动态读取目标当前手牌，不使用指定目标时快照；CP-04P 工作树验收记录，尚未由用户提交，独立审计尚未进行）
# 1953 passed；失败0、跳过0（在1959基础上丈八蛇矛规则源复核：确认材料非弃置代价（移除CARD_DISCARDED事件，依据基础术语第12节措辞通则），颜色组合规则有明确来源（7.8特殊说明，当前确认）；材料在“使用/打出”时的精确zone生命周期时点无项目确认通则，报告VIRTUAL_CARD_SUBCARD_LIFECYCLE_RULE_GAP，丈八蛇矛暂降回PARTIAL并从36种/158张统计移除（回35种/157张），删除6项丈八正向专项；完整语义35种/157张；CP-04P 工作树验收记录，尚未由用户提交，独立审计尚未进行）
# 1966 passed；失败0、跳过0（在1953基础上 WHOLE_REPO_AUDIT_REMEDIATION_1 新增13项：G-001死亡座次距离7项（3/4/5人环、中间死亡收缩、多死亡、相邻收缩、dead participant fail-closed、dead target非法、坐骑修正与下限）、麒麟弓时序2项（1HP先麒麟弓再扣0进DYING、1HP放弃后damage进DYING）、麒麟弓replay/重执行1项（坐骑移动/失牌先于DAMAGE且篡改顺序被拒）、G-003丈八统一fail-closed 3项（PLAY/决斗/南蛮 public legal_actions 在枚举virtual proposal前直接UnsupportedRule失败关闭）；麒麟弓时序修正：窗口移到HP扣减/DAMAGE之前；base_seat_distance改为存活角色环索引计算；完整语义35种/157张（8种/9张COMPLETE武器）；CP-04P 工作树修复记录，尚未由用户提交）
# 1974 passed；失败0、跳过0（在1966基础上 WHOLE_REPO_AUDIT_REMEDIATION_2 新增8项：G-001 dead-self 1项（死亡参与者统一fail-closed、alive self=0保持）、R1-NEW-001 Qilin×armor 7项（Baiyin Wine 弃马/PASS=1、Baiyin dying边界、Tengjia Fire 弃马/PASS=2、Tengjia dying边界、replay DAMAGE value与篡改拒绝）；Qilin pending改保存resolution.final_amount；青釭ignore_armor清除绑定真正damage completion；G-004/G-005/G-002 inventory见2.17/2.18节；CP-04P 工作树修复记录，尚未由用户提交）
.\.venv\Scripts\python.exe -m compileall -q scripts tests
# 通过
.\.venv\Scripts\python.exe -m scripts.sgs_source_integrity_audit . --fail-on-defect --pretty
# 扫描122个Python文件，defect_count=0；55项均为显式门禁字段或测试证据等audit_item
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
- 剩余普通锦囊批次（`CP-04I-PRODUCTION-REMAINING-ORDINARY-TRICK-BATCH`）：【五谷丰登】2张完整生产语义＋【铁索连环】6张牌本体接入生产适配器（见 2.9 节）；已由用户在外部PowerShell提交实现（实现提交哈希 `20cb1b1f766529a88aa5f3346a4761b77eca66b7`，提交信息 feat: implement wugu and tiesuo card-body slice）；基线提交 `6af30432993d908546d7cec114fd78ae62798ad5`（里程碑标签 `milestone-b2-group-target-tricks-audited` 指向该提交）；2026-08-04 独立审计完成：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES（审计问题关闭提交 `5b1c2c15b6a8e21563aab02d8a5c181c553e4967`），最终独立复审结论 AUDIT_PASSED（最终措辞修正提交 `b2d4ffca18092938437d15826efdaddba8a0a689`）；里程碑标签 `milestone-b2-wugu-tiesuo-card-body-audited` 由用户在本次最终文档提交后立即建立（本轮未执行 git tag）。
- 【借刀杀人】＋11种武器牌本体批次（`CP-04K-PRODUCTION-BORROWED-SWORD-WEAPON-SYSTEM`）：普通锦囊最后一张【借刀杀人】完整双人生产语义与11种／12张武器牌本体接入生产适配器（见 2.11 节）；已由用户在外部PowerShell提交真实实现提交（最终提交哈希 `75c596b12f34a6222d972b2190148386bb670653`，feat: implement borrowed sword and weapon card-body system；amend 替代旧提交 `7456377f...`；测试文件末尾多余空行已在 amend 前修正）、检查点文档提交（`f0008b571f502e0d6b7cc1800de9c2a8e39074e3`）与审计残项关闭提交（`79acc6ff514af4900acfe87507374fc8d696ec97`，fix: close borrowed sword weapon audit gaps）；首次独立只读审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES（N1-N3 已关闭），最终独立复审结论 AUDIT_PASSED；里程碑标签 `milestone-b2-borrowed-sword-weapon-system-audited` 计划在本次最终文档提交后由用户建立（本轮未执行 git tag）；本批基线为 `3ea01f4e8603dd96698a2e5deee09c1e9b3fccef`（milestone-b2-chain-damage-infrastructure-audited）。
- 三种延时锦囊＋判定与阶段基础设施批次（`CP-04L-PRODUCTION-DELAYED-TRICK-JUDGMENT-INFRASTRUCTURE`）：【乐不思蜀】3张、【兵粮寸断】2张、【闪电】2张接入生产适配器并建立判定与阶段基础设施（见 2.12 节）；已由用户在外部PowerShell提交实现（实现提交哈希 `35c06bd50a431a62e7c3ad01d10384bf6884c403`，提交信息 feat: implement delayed tricks and judgment infrastructure）、检查点文档提交（`4f2c9b61fccb4337a8e84ae560835d705be65bda`）与文档收口提交（`ba64b750fabd99f2bfc93697cea83e1272216d02`，docs: finalize delayed trick and judgment audit milestone）；2026-08-05 第一次独立审计结论 AUDIT_FAILED_BLOCKING_ISSUES（唯一阻塞项 B1：player_visible 未脱敏 reshuffle 事件），B1 实质修复与 N1–N9 关闭已完成（修复提交 `96f536e1f392fd97faf61518a849a0d515b6a82e`，完整 pytest 1724 passed）；2026-08-06 第二次最终复审结论 AUDIT_FAILED_BLOCKING_ISSUES：B1-a（动作负载权威状态摘要旁路）、B1-b（legal_actions/chosen_action 泄露行动者手牌）、B1-c（tiesuo_recast 等隐藏摸牌泄漏）与两个复审观察项（N5 篡改测试结构、judgment_entry_indices 陈旧残留）；最终修复提交 `eeeaf558cdaeeea0eb90456f907f83dce52286f3`（fix: harden player-visible replay privacy）完成修复与关闭（新增9项测试，本地修复会话完整 pytest 1733 passed）；2026-08-06 Grok 网页端独立静态审计 STATIC_AUDIT_PASSED（经 GitHub 连接器读取精确目标提交，完整读取18个强制文件，PARTIAL_READ=无、NOT_READ=无；未亲自运行 pytest／Git／本地虚拟环境，运行类证据来自本地修复会话）；最终独立审计结论 AUDIT_PASSED（status=audited、commit=35c06bd50a431a62e7c3ad01d10384bf6884c403、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、milestone_tag=已建立标签 `milestone-b2-delayed-trick-judgment-infrastructure-audited`（HISTORICAL/AS-OF：当时标签状态记录为指向文档收口提交 ba64b750fabd99f2bfc93697cea83e1272216d02；CURRENT LIVE REF：当前 Git tag 解析为 fc3df95202b23dccfd9abf5e476485a224d6fc2c，以当前 Git ref 解析结果为准）、worktree_commit_pending=false）；本批基线为 `185cc555324b077d0e81bef10a4518ba2dae3748`（milestone-b2-borrowed-sword-weapon-system-audited）。
- 属性伤害传导基础设施（`CP-04J-PRODUCTION-CHAIN-DAMAGE-INFRASTRUCTURE`）：横置角色受火／雷属性伤害后按统一生产管线确定性传导（见 2.10 节）；已由用户在外部PowerShell提交实现（实现提交哈希 `c094bff5dab127917e8d0b9a2d3422e3ab736783`，提交信息 feat: implement production chain damage infrastructure；检查点文档提交 `55228c9d464daac6eb061ba356b0497ec814eba6`；审计残项关闭提交 `68e419b79e379184c1f1cc7ad650039771530f89`，fix: close chain damage audit gaps）；2026-08-04 独立审计完成：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，最终独立复审结论 AUDIT_PASSED（status=audited、independent_audit_done=true、audit_conclusion=AUDIT_PASSED）；里程碑标签 `milestone-b2-chain-damage-infrastructure-audited` 由用户在本次最终文档提交后立即建立（本轮未执行 git tag、未验证标签已存在）。
- 四种防具＋伤害修正／防止基础设施批次（`CP-04M-PRODUCTION-ARMOR-DAMAGE-PREVENTION-INFRASTRUCTURE`）：【八卦阵】2张、【仁王盾】1张、【藤甲】2张、【白银狮子】1张接入生产适配器并建立统一伤害修正／防止基础设施（见 2.13 节）；实现提交 29ab73e006408e1e1582a300801e7aa6e04bd9c4（feat: implement armor and damage prevention infrastructure）已由用户在外部PowerShell提交；检查点状态为 audited、commit=29ab73e006408e1e1582a300801e7aa6e04bd9c4、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、milestone_tag=计划标签 milestone-b2-armor-damage-prevention-infrastructure-audited（待用户建立）、worktree_commit_pending=true；本批基线为 `fc3df95202b23dccfd9abf5e476485a224d6fc2c`（milestone-b2-delayed-trick-judgment-infrastructure-audited）。
- 正式坐骑＋距离／攻击范围基础设施批次（`CP-04N-PRODUCTION-MOUNT-DISTANCE-INFRASTRUCTURE`）：【攻击坐骑】3张、【防御坐骑】4张接入生产适配器并建立统一有效距离模型（见 2.14 节）；实现提交 fd7d69f53e9827877b6a29d67c067012ead6a7af（feat: implement mounts and distance infrastructure）已由用户在外部PowerShell提交；检查点状态为 audited、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、milestone_tag=已建立标签 `milestone-b2-mount-distance-infrastructure-audited`、worktree_commit_pending=false；本批基线为 `733940b4a5e278ae3eba11e5c6522b0f1832d6b4`（milestone-b2-armor-damage-prevention-infrastructure-audited）。
- 正式弃牌阶段＋权威回合循环基础设施批次（`CP-04O-PRODUCTION-TURN-CYCLE-DISCARD-INFRASTRUCTURE`）：正式阶段流收敛为 PREPARE→JUDGMENT→DRAW→PLAY→DISCARD→END 单一权威回合循环并正式实现弃牌阶段（批量弃置语义 DISCARD_BATCH_SEMANTICS_FIXED，见 2.15 节）；实现提交 b1afb1a613a45c630ae1e42975d276d62915e76d（feat: implement turn cycle and discard infrastructure）与检查点文档提交 7aacd06cdfcf1725307061a3f5c03c233a2199f7（docs: record turn cycle and discard checkpoint）均已由用户在外部PowerShell提交；2026-08-07 Grok 网页端独立只读静态审计最终结论 STATIC_AUDIT_PASSED（READ COVERAGE：FULL_RELEVANT_SCOPE_READ，PARTIAL_READ=空、NOT_READ=空，16个强制审计章节全部PASSED，Blocking issues=NONE、Non-blocking issues=NONE；提示中不存在的knowledge/三国杀完整游戏规则.md 已由 Grok 正确使用实际仓库规则文件 knowledge/三国杀模式规则.md，这只是提示路径修正不是仓库缺陷；Grok 未亲自运行 pytest、compileall 或本地虚拟环境，1889 passed 等运行结果来自本地实现会话，两类证据不得混写）；完整 pytest 1889 passed（专项49项）；检查点状态为 audited、commit=b1afb1a613a45c630ae1e42975d276d62915e76d、checkpoint_commit=7aacd06cdfcf1725307061a3f5c03c233a2199f7、final_doc_commit=17246077776ef8a8c7f957706d60fd91e2c0a440（最终审计文档提交，docs: finalize turn cycle and discard audit milestone）、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、milestone_tag=已建立标签 milestone-b2-turn-cycle-discard-infrastructure-audited（已实际建立并推送：本地标签已由本轮亲自验证存在，并在最终仓库状态回填开始时解析到 17246077776ef8a8c7f957706d60fd91e2c0a440，GitHub远程标签建立／推送事实来自用户外部PowerShell验证；当前标签目标以Git标签解析结果为准）、worktree_commit_pending=false；本批基线为 `f2eb98a03a56f57ddfd4d5d0a24c0ddb26176989`。
- 正式武器技能完整化批次（`CP-04P-PRODUCTION-WEAPON-SKILL-COMPLETION`）：11种武器中8种／9张（诸葛连弩、青釭剑[QINGGANG_LIFECYCLE_CONFIRMED]、寒冰剑、古锭刀、青龙偃月刀、贯石斧、朱雀羽扇、麒麟弓）完成正式生产语义，雌雄双股剑[DATA_MODEL_GAP]、丈八蛇矛[VIRTUAL_CARD_SUBCARD_LIFECYCLE_RULE_GAP]、方天画戟[多人生产环缺口]3种保持PARTIAL失败关闭（见 2.16 节）；完整工作树实现与70项武器专项＋7项借刀朱雀专项已在本轮完成（完整 pytest 1974 passed；WHOLE_REPO_AUDIT_REMEDIATION_1/2 修复：G-001死亡座次距离（含dead-self）、麒麟弓时序与resolved final damage、R1-NEW-001/002、G-003丈八统一fail-closed、G-004/G-005清理）；实现提交已由用户在外部PowerShell创建：commit=implementation_commit=f0a50ce9ace71c5bf0a22540fbdca9e03aa918b3（feat: implement verified production weapon skills）、implementation_parent=ef340c42e180ab14832b291bc0fc83f449a771a6；checkpoint_commit=c30b26880b947217d64304ce430d32030b42941e（docs: record weapon skill completion checkpoint，已真实回填）；2026-08-08 完成独立静态审计（CP_04P_INDEPENDENT_STATIC_AUDIT）：Grok 网页端经 GitHub 连接器对审计分支 deepseek-audit-weapon-skill-completion 上的精确目标 c30b26880b947217d64304ce430d32030b42941e 进行只读静态审计（implementation f0a50ce9ace71c5bf0a22540fbdca9e03aa918b3，baseline ef340c42e180ab14832b291bc0fc83f449a771a6）；16个强制审计章节全部PASSED，BLOCKING_FINDINGS=NONE、NONBLOCKING_FINDINGS=NONE；NOT_READ=none of the mandatory implementation/docs files；PARTIAL_READ=仅production_batch.py非武器外围部分以及非关键docs全文（武器相关changed hunks、调用链、pending、gate及关键状态均已完整追踪，不构成关键审计缺口）；独立复算 registered=38种/160张、complete semantics=35种/157张、complete weapons=8种/9张、partial weapons=3种/3张、unregistered=0种/0张；PARTIAL分类均被审计确认合理且真正fail-closed。Grok未亲自执行pytest、compileall或本地虚拟环境；本地运行证据（pytest 1953 passed 等）来自本地实现会话，两类证据不得混写。检查点状态为 audited、independent_audit_done=true、audit_conclusion=STATIC_AUDIT_PASSED、milestone_tag=milestone-b2-weapon-skills-audited（已实际建立并指向 398ea58c9006ee9141ea1acfba35f6d9c497be48）、worktree_commit_pending=false；final_doc_commit=08d78cb6fed86360d647728a6f70422326918ff2 已真实回填；milestone_tag_verified=true；本批基线为 `ef340c42e180ab14832b291bc0fc83f449a771a6`（milestone-b2-turn-cycle-discard-infrastructure-audited）。

## 9. 下一可验收版本

下一版本最小目标不是网页或全武将，而是里程碑 B“正式160张牌无技能单挑”。当前明确阻塞为：

1. 正式 Knowledge 尚未把当前160张牌堆纳入单挑适用范围；同名武将、先手首轮摸牌修正等单挑配置仍须由资料或显式配置确定（六种基本牌批次已锁定双人、先手摸2的确定性开局约定）；
2. `AuthoritativeCoreSession.run_game` 仍是失败关闭占位，尚未接入正式对局循环；
3. 38 个正式 `card_key` 已全部接入权威 `GameState` 的生产适配器（formal_deck_registration_complete=true，剩余未注册0种；其中六种基本牌、全部普通锦囊（含【借刀杀人】）、3种延时锦囊、4种防具与2种坐骑中27种／148张完整语义，11种武器牌本体为partial且专属技能全部未实现；“全部注册”不等于全部卡牌语义完成）；
4. 弃牌阶段与完整基础阶段循环已由 CP-04O 生产接入（手牌上限默认等于当前体力值；选择＋一次性批量提交，确认前不产生正式弃牌状态转换），但正式整局入口仍未接入权威回合循环；
5. 普通锦囊精确事件语义已闭合到当前批次：五谷公开展示池、逐目标选牌与剩余展示牌统一弃置、提前结束确定性清理（CP-04I 用户确认口径）；铁索横置状态切换（`chained_state`）、重铸（`card_recast`）与属性伤害传导（`chain_damage_started`／`chain_target_resolved`／`chain_damage_finished`）事件已闭合；CP-04I 临时失败关闭门禁已由 CP-04J 统一传导管线移除；五谷展示牌量不足失败关闭保持原子一致；铁索重铸因重铸牌自身进入弃牌堆而可重洗摸回，正式语义下不存在真实可达的牌量不足路径（不可达）；借刀杀人的武器转移与出杀次数口径（响应借刀不受本出牌阶段已用杀次数的前置限制、成功后正常计入次数、仅次数用尽不构成无合法杀，2026-08-04 用户移动版实测修正，见 Knowledge 4.6.1）；CP-04K 已闭合：两次目标检测、第一目标以不透明句柄选择实体杀或拒绝、强制使用【杀】与按角色出杀计数、武器从第一目标装备区直接进入使用者手牌（`jiedaosharen_weapon_gain`）、装备三事件（`equipment_equipped`／`equipment_removed`／`equipment_replaced`）、挂起恢复与终局清理（见 Knowledge 4.6.3）；CP-04L 已闭合：正式阶段流、判定区进入序号与动态LIFO、判定前【无懈可击】、判定牌生命周期、乐不思蜀／兵粮寸断阶段跳过、闪电无来源雷属性伤害与转移／回置、死亡与胜利清理、判定彻底不足原子失败关闭、player_visible 双视角隐私与判定事件契约（见 Knowledge 5.3.1）；CP-04M 已闭合：四种防具完整语义（统一伤害修正管线、仁王盾黑杀无效、藤甲免疫与火属性伤害+1、八卦阵响应窗口内可选判定与虚拟闪、白银狮子限伤与统一离区恢复、统一防具无效接口（armor invalid）、prevented_zero 语义与伤害事件审计字段，见 Knowledge 8.4.1）；CP-04N 已闭合：两种坐骑完整语义与统一有效距离模型（基础座次距离＋进攻／防御坐骑方向性修正、武器攻击范围与有效距离分离、杀／借刀／顺手／兵粮距离接入、正式160张实体牌全部注册，见 Knowledge 9.3）；CP-04O 已闭合：正式弃牌阶段与单一权威回合循环（PREPARE→JUDGMENT→DRAW→PLAY→DISCARD→END，手牌上限默认等于当前体力值、逐张弃置、自动推进、回合级状态清理与下一行动者转交，见 Knowledge 3.5.1）；正式牌堆彻底不足平局出口、改判／判定牌获得／判定结果修改、雌雄双股剑／丈八蛇矛／方天画戟3种武器专属技能、多人死亡后的座次距离、武将技能、正式单挑仍为 NOT PROVEN，不得视为歧义已全部消除；青釭剑真实防具无效调用与生命周期（armor invalid；代码字段 ignore_armor。QINGGANG_LIFECYCLE_CONFIRMED）已由 CP-04P 真实接入并移除对应 NOT PROVEN；寒冰剑逐张弃置防止伤害、青龙偃月刀继续杀（不消耗普通出牌阶段杀额度，USER_CONFIRMED_MOBILE_RULE）、贯石斧批量代价强制命中（自身不能作为代价，USER_CONFIRMED_MOBILE_RULE）、朱雀羽扇借刀转火杀路径均已由 CP-04P 真实实现；“青龙追杀是否计入通常杀次数”与“贯石斧弃自身后技能是否继续”不再列为 NOT PROVEN（神赵云龙魂把装备区【白银狮子】当【闪】使用的完整武将技能交互保持 FUTURE_CHARACTER_SKILL_INTEGRATION_NOT_PROVEN）；
6. 里程碑 B 要求的正式100-seed 门槛尚未执行；测试切片的50-seed 结果不能替代它。

只有解决上述阻塞、正式范围内 `unsupported_rules=0`、`approximation_count=0`，并完成100-seed、严格回放、牌守恒和完整 pytest 验收后，才可将 `formal_duel_no_skill_ready` 改为 `true`。其他模式和武将仍需分别验收。
