# 三国杀统一模拟项目总实施计划

> 更新日期：2026-08-07
> 当前定位：正式 Knowledge、轻量规则／技能／策略组件库、阶段 4 的权威核心基础设施、测试专用无技能单挑垂直切片、正式160张牌堆六种基本牌的生产适配器批次、最小普通锦囊垂直切片（【无中生有】、【无懈可击】）、目标区域选牌批次（【过河拆桥】、【顺手牵羊】接入生产适配器），以及伤害型普通锦囊批次（【决斗】、【火攻】接入生产适配器）、群体普通锦囊批次（【南蛮入侵】、【万箭齐发】、【桃园结义】接入生产适配器）、剩余普通锦囊批次（【五谷丰登】完整生产语义＋【铁索连环】牌本体）、属性伤害传导生产基础设施（CP-04J），以及【借刀杀人】＋11种武器牌本体批次（CP-04K，已由用户在外部PowerShell提交，最终实现提交 `75c596b12f34a6222d972b2190148386bb670653`，amend 替代旧提交 `7456377f...`）；以及三种延时锦囊＋判定与阶段基础设施批次（CP-04L：【乐不思蜀】【兵粮寸断】【闪电】接入生产适配器，已由用户在外部PowerShell提交实现，提交哈希 `35c06bd50a431a62e7c3ad01d10384bf6884c403`）；但尚不是正式 160 张牌完整对局引擎。、四种防具＋伤害修正／防止基础设施批次（CP-04M：【八卦阵】【仁王盾】【藤甲】【白银狮子】接入生产适配器，实现提交 29ab73e006408e1e1582a300801e7aa6e04bd9c4 已由用户在外部PowerShell提交）、正式坐骑＋距离／攻击范围基础设施批次（CP-04N：【攻击坐骑】【防御坐骑】接入生产适配器，正式160张实体牌全部注册，实现提交 fd7d69f53e9827877b6a29d67c067012ead6a7af 已由用户在外部PowerShell提交）；以及正式弃牌阶段＋权威回合循环基础设施批次（CP-04O：正式阶段流收敛为 PREPARE→JUDGMENT→DRAW→PLAY→DISCARD→END 单一权威回合循环并正式实现弃牌阶段，实现提交 b1afb1a613a45c630ae1e42975d276d62915e76d 已由用户在外部PowerShell提交，2026-08-07 Grok 网页端独立只读静态审计最终结论 STATIC_AUDIT_PASSED）；以及正式武器技能完整化批次（CP-04P：诸葛连弩、青釭剑[QINGGANG_LIFECYCLE_CONFIRMED]、寒冰剑[逐张弃置语义]、古锭刀、青龙偃月刀[追杀不消耗普通出牌阶段杀额度，USER_CONFIRMED_MOBILE_RULE]、贯石斧[批量代价；自身不能作为代价，USER_CONFIRMED_MOBILE_RULE]、朱雀羽扇[含借刀转火杀]、麒麟弓8种武器完成正式生产语义；雌雄双股剑（DATA_MODEL_GAP: CHARACTER_GENDER_METADATA_NOT_AVAILABLE，规则本身已知）、丈八蛇矛（实现完成但subcard生命周期时点规则缺口VIRTUAL_CARD_SUBCARD_LIFECYCLE_RULE_GAP，暂计PARTIAL）、方天画戟（多人生产基础环未建立）3种保持PARTIAL，完整工作树实现已在本轮完成，完整 pytest 1974 passed；实现提交 f0a50ce9ace71c5bf0a22540fbdca9e03aa918b3（feat: implement verified production weapon skills）与检查点文档提交 c30b26880b947217d64304ce430d32030b42941e 均已由用户在外部PowerShell创建；2026-08-08 Grok 独立静态审计 STATIC_AUDIT_PASSED（16章全PASSED、BLOCKING/NONBLOCKING NONE），检查点状态 audited、worktree_commit_pending=false（审计记录文档提交 08d78cb6fed86360d647728a6f70422326918ff2 已产生并回填）；里程碑标签 milestone-b2-weapon-skills-audited 已实际建立并指向 398ea58c9006ee9141ea1acfba35f6d9c497be48）；以及整仓敌对式总审计定向修复批次（WHOLE_REPO_AUDIT_REMEDIATION_1：原总审计 CP04L_TO_CP04P_WHOLE_REPO_ADVERSARIAL_AUDIT 结论 WHOLE_REPO_AUDIT_FAILED（G-001..G-005、N-001）；修复实现提交 f1731b95199165a3449f1a0ce84d9facfc1b41c5（fix: remediate whole-repo audit findings）已由用户在外部PowerShell提交，检查点状态 committed_pending_audit、NOT_AUDITED_YET（HISTORICAL/AS-OF：R1文档回填时；CURRENT：remediation-1 targeted re-audit=REMEDIATION_REAUDIT_FAILED，R1未获得通过的独立审计）；以及整仓敌对式总审计定向修复第二轮（WHOLE_REPO_AUDIT_REMEDIATION_2：G-001 dead-self、R1-NEW-001 Qilin resolved final amount、R1-NEW-002 Qinggang cleanup、G-003保持、G-004/G-005、【杀】family通则与8项游戏内文本source同步、G-002=G-002_SOURCE_GAP_LOCALLY_RESOLVED_PENDING_INDEPENDENT_REAUDIT（HISTORICAL/AS-OF：R2实现时本地状态；CURRENT：G-002=CLOSED，由 remediation-2 targeted independent re-audit 确认）；实现提交 e63b40ac1690e03315fd3e0734d5723fb80d5182（fix: complete second whole-repo audit remediation）已由用户在外部PowerShell提交，检查点状态 committed_pending_audit、worktree_commit_pending=true（HISTORICAL/AS-OF：R2文档回填时 NOT_AUDITED_YET；CURRENT：remediation-2 targeted re-audit=REMEDIATION_2_REAUDIT_FAILED，原因是当时G-004/G-005仍OPEN）；以及整仓敌对式总审计定向修复第三轮/最小收尾（WHOLE_REPO_AUDIT_REMEDIATION_3：G-004 ba64历史引用分层、G-005 stale清理、R2-NEW-001 annotation统一tuple[str,str]|None；实现提交 9c63496e7f34430d8aff3c23e9afc5b5c4482557（fix: close remaining whole-repo audit findings）已由用户在外部PowerShell提交，检查点状态 committed_pending_audit、NOT_AUDITED_YET、worktree_commit_pending=true，独立 re-audit 尚未进行）
> 进度口径：只有满足本文件所列验收门槛，阶段才可标记为“通过”。文档存在、局部函数通过单元测试或旧脚本能够输出 CSV，均不等于完整引擎通过。

## 1. 状态与检查点约定

阶段状态只使用：

- `通过`：验收门槛全部满足并有实际证据；
- `进行中`：已有可运行成果，但至少一个门槛未满足；
- `未开始`：尚未实施；
- `阻塞`：存在当前环境或资料阻塞，并已记录可恢复状态。

当前目录已经建立 Git 仓库。CP-01 至 CP-04 的哈希检查点继续作为历史审计资料保留；自 Git 基线建立后，以真实提交作为主要检查点。当前相关提交为：

1. `858d6ced315dfa3df78636528c720c0117fdf3de`：经审计的权威核心基础层 Git 基线；
2. `5eac686`：基线检查点元数据；
3. `455685d6eaa1c297e9ec48a0cfaeb803b81f3406`：测试专用无技能单挑垂直切片及严格规则重执行。

当前检查点：

| 检查点 | 内容 | 证据 | Git提交 |
|---|---|---|---|
| `CP-01-SOURCE-AUDIT` | 外部旧脚本、结果、配置来源和正式仓库调用链盘点 | `docs/SOURCE_AND_CALLCHAIN_AUDIT.md`；13 个用户明列文件的路径与哈希；修改前 `947 passed in 3.39s` | 纳入基线 `858d6ced315dfa3df78636528c720c0117fdf3de` |
| `CP-02-LEGACY-STATUS` | 旧近似胜率与自证式 AI 审计的失效范围，以及可执行失败关闭门禁 | `docs/LEGACY_RESULTS_INVALID.md`、`scripts/sgs_engine_gate.py`、`scripts/sgs_formal_runner.py`；28 项门禁／入口专项测试 | 纳入基线 `858d6ced315dfa3df78636528c720c0117fdf3de` |
| `CP-03-ENGINE-INVENTORY` | 正式组件库的 15 项能力盘点 | `docs/IMPLEMENTATION_MATRIX.md`、`docs/ENGINE_STATUS.md` | 纳入基线 `858d6ced315dfa3df78636528c720c0117fdf3de` |
| `CP-04-CORE-FOUNDATION` | 不可变实体／状态、事件、响应窗口、动作路由、确定性随机、回放完整性与失败关闭基础会话 | `scripts/sgs_engine/`、对应测试；基线时 `1094 passed`，compileall 通过，源码防伪扫描 `defect_count=0` | 基线 `858d6ced315dfa3df78636528c720c0117fdf3de`；元数据 `5eac686` |
| `MILESTONE-A-DUEL-VERTICAL-SLICE` | `test_only_duel_vertical_slice` 无技能单挑最小闭环及严格规则重执行 | 50 个 seed 全部自然结束；最大 187 动作；完整测试 `1135 passed` | `455685d6eaa1c297e9ec48a0cfaeb803b81f3406` |
| `MILESTONE-B1-PRODUCTION-BASIC-CARDS` | 正式160张牌堆中六种基本牌（普通【杀】、火【杀】、雷【杀】、【闪】、【桃】、【酒】）的生产适配器批次 | 六种基本牌共85张实体牌接入生产注册表；37项批次验收测试、严格规则重执行与篡改失败关闭；完整测试 `1172 passed` | 本批次提交（feat: implement production basic-card adapter batch） |
| `MILESTONE-B2-SINGLE-TARGET-TRICK-SLICE` | 正式160张牌堆最小普通锦囊垂直切片：【无中生有】（4张）与【无懈可击】（7张）接入生产适配器及普通锦囊无效响应基础设施 | 两种锦囊共11张实体牌接入生产注册表；无效响应窗口、连续【无懈可击】响应、放弃响应、被无效仍记已使用、牌区生命周期与严格规则重执行、篡改失败关闭均有验收测试；完整测试 `1197 passed` | 提交 `18fb9916796a34a60b62fd490529d80bd9eb75ef`（feat: implement production single-target trick slice） |
| `MILESTONE-B2-ZONE-TARGET-TRICKS` | 正式160张牌堆目标区域选牌批次：【过河拆桥】（6张）与【顺手牵羊】（5张）接入生产适配器，及共用“目标区域选牌、隐藏手牌选择、实体牌移动”基础设施 | 两牌共11张实体牌接入生产注册表；目标区域选牌动作、公开区域实体候选、隐藏手牌HMAC-SHA256不透明句柄、直接弃置／直接获得事件、连续【无懈可击】响应、无合法区域牌结算、严格规则重执行与失败关闭均有验收测试；完整测试 `1252 passed`；隐藏句柄HMAC安全修复后完整测试 `1281 passed` | 提交 `2a73e5c3b3d17dab87bb13168db6e0e4e05a5130`（feat: implement production zone-target trick slice） |
| `MILESTONE-B2-ZONE-TARGET-HANDLE-HMAC-FIX` | 目标区域选牌隐藏手牌句柄安全定点修复：裸SHA-256（可被160项公开预计算表还原，独立只读审计判 AUDIT_FAILED）改为会话级 `secrets.token_bytes(32)` 随机秘密的HMAC-SHA256句柄，绑定会话／窗口／目标／区域／手牌快照；权威回放以 `authoritative_private` 保存会话标识与密钥，`player_visible` 导出不含秘密或私有映射 | 新增29项安全回归测试（160项枚举攻击匹配数为0、伪造／过期／跨会话／跨窗口／跨目标／跨区域／手牌变化失败关闭、回放私有材料删除或篡改失败关闭）；完整测试 `1281 passed`，失败0、跳过0 | 已由用户在外部PowerShell提交（提交哈希 1b5e125ad0baa129458b42043aac08b18dcfad96，fix: secure hidden hand choice handles） |
| `MILESTONE-B2-DUEL-FIRE-ATTACK-BATCH` | 正式160张牌堆伤害型普通锦囊批次：【决斗】（3张）与【火攻】（3张）接入生产适配器，复用【无懈可击】逐张响应链与普通锦囊使用窗口 | 【决斗】交替打出【杀】状态机（目标先响应、双方交替、响应【杀】记录为打出而非使用、不响应者受另一方参与者1点无属性伤害、死亡响应者立即结束）；【火攻】目标本人选择展示手牌（HMAC-SHA256不透明展示句柄，仅选择窗口有效）、未展示手牌隔离、同花色弃置／不弃置与1点火焰伤害；完整测试 `1334 passed`，失败0、跳过0 | 已由用户在外部PowerShell提交（实现提交哈希 `b3587912da97825871ae91ea8a88b3e95c39fdde`，feat: implement production duel and fire attack slice）；2026-08-03 独立只读审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，补充两个确定性回归测试；审计收尾真实提交 `9c2070017fe624295ebd735bf5163f48a6ac2207`（test: close duel and fire attack audit gaps），里程碑标签 `milestone-b2-duel-fire-attack-audited` 已建立 |
| `CP-04I-REMAINING-ORDINARY-TRICKS` | 正式160张牌堆剩余普通锦囊批次：【五谷丰登】（2张）完整生产语义＋【铁索连环】（6张）牌本体接入生产适配器 | 【五谷丰登】：按当前存活角色数量快照展示等量牌到公共REVEALED区域、逐目标独立【无懈可击】窗口、公开展示池选牌、剩余展示牌统一弃置、提前结束确定性清理；【铁索连环】牌本体：一至二目标（可含使用者、无距离）、服务器规范化目标顺序、逐目标独立【无懈可击】、横置状态切换（chained_state事件）、重铸（card_recast事件＋正式摸牌接口摸1）；属性伤害传导未实现（tiesuo_chain_damage_implemented=false，等待CP-04J）；CP-04J 前横置角色受到火／雷属性伤害时生产入口在统一伤害前置校验处抛 `UnsupportedRuleError` 失败关闭（当前动作未被提交，临时门禁，CP-04J 实现传导后移除）；五谷展示牌量不足失败关闭保持状态／事件／RNG／runtime 原子一致；铁索重铸在局部不可变状态完成“弃置→正式摸1张”后一次性登记事件，因重铸牌自身进入弃牌堆构成可重洗实体，正式语义下牌量不足不可达；借刀等待装备生产切片（CP-04K）；严格规则重执行与篡改失败关闭；完整测试 `1463 passed`，失败0、跳过0 | 已由用户在外部PowerShell提交（实现提交哈希 `20cb1b1f766529a88aa5f3346a4761b77eca66b7`，提交信息 feat: implement wugu and tiesuo card-body slice）；基线提交 `6af30432993d908546d7cec114fd78ae62798ad5`；2026-08-04 独立审计完成：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES（审计问题关闭提交 `5b1c2c15b6a8e21563aab02d8a5c181c553e4967`，fix: close wugu and tiesuo card-body audit gaps），最终独立复审结论 AUDIT_PASSED（最终措辞修正提交 `b2d4ffca18092938437d15826efdaddba8a0a689`，docs: correct CP-04I audit closure wording）；`status=audited`、`independent_audit_done=true`、`audit_conclusion=AUDIT_PASSED`；里程碑标签 `milestone-b2-wugu-tiesuo-card-body-audited` 为本次最终文档提交后由用户立即建立的标签名称（本轮未执行 git tag、未验证标签已存在） |
| `CP-04K-PRODUCTION-BORROWED-SWORD-WEAPON-SYSTEM` | 正式160张牌堆【借刀杀人】＋11种武器牌本体批次：普通锦囊最后一张【借刀杀人】完整双人生产语义，11种／12张武器牌本体主动装备与同槽替换，按角色出杀计数，武器专属技能集中式失败关闭门禁 | 【借刀杀人】两次目标检测、第一目标以HMAC-SHA256不透明句柄选择实体杀或拒绝、强制使用【杀】、拒绝后武器直接进入使用者手牌、挂起与终局清理；武器装备三事件（`equipment_equipped`／`equipment_removed`／`equipment_replaced`，reason 封闭枚举：equip／replaced）、攻击范围按正式结构化CSV动态计算；新增80项专项与12项装备事件契约测试；首次独立只读审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，N1（装备事件reason契约）、N2（12张武器实体逐张真实装备路径）、N3（拒绝计数不变、胜利清理严格回放、no_weapon_to_transfer单字段篡改、第二目标无独立无懈窗口）已在本工作树关闭（待用户提交），审计残项关闭后批次测试文件84项、事件契约测试85项、完整 pytest `1649 passed` | 已由用户在外部PowerShell提交（最终实现提交 `75c596b12f34a6222d972b2190148386bb670653`，feat: implement borrowed sword and weapon card-body system；amend 替代旧提交 `7456377f5fdc94588f6e872be6505b4e0159c803`；测试文件末尾多余空行已在 amend 前修正）；检查点文档提交 `f0008b571f502e0d6b7cc1800de9c2a8e39074e3`（docs: record borrowed sword and weapon system checkpoint）；审计残项关闭提交 `79acc6ff514af4900acfe87507374fc8d696ec97`（fix: close borrowed sword weapon audit gaps）；2026-08-05 最终独立复审结论 AUDIT_PASSED（status=audited、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、milestone_tag=计划标签）；里程碑标签 `milestone-b2-borrowed-sword-weapon-system-audited` 由用户在本次最终文档提交后立即建立（本轮未执行 git tag） |
| `CP-04J-CHAIN-DAMAGE-INFRASTRUCTURE` | 横置角色火／雷属性伤害传导生产基础设施：统一传导入口、原始与派生伤害区分、确定性候选顺序、濒死挂起恢复、事件与严格回放 | 火杀／雷杀／火攻与通用伤害管线统一接入；原始角色实际受属性伤害后解除横置并建立传导根；以当前回合角色为锚点、座次递增动态检查候选；每名目标以根基数独立结算、继承来源／根牌／属性并标记 `is_chain_transmitted`；濒死暂停并在救援后恢复准确索引；胜利成立清理未开始目标；`chain_damage_started`／`chain_target_resolved`／`chain_damage_finished` 进入事件哈希链；链事件契约完整校验（stopped_winner 非合法 result）；prevented_zero 采用 CONTINUE/FINISHED/PAUSED 控制流立即结束；CP-04I 临时失败关闭门禁移除；批次测试文件44项（40项生产路径＋4项审计残项关闭）、`tests/test_sgs_engine_events.py` 63项（含36项链事件契约）；完整测试 `1543 passed`，失败0、跳过0 | 已由用户在外部PowerShell提交（实现提交哈希 `c094bff5dab127917e8d0b9a2d3422e3ab736783`，提交信息 feat: implement production chain damage infrastructure；检查点文档提交 `55228c9d464daac6eb061ba356b0497ec814eba6`；审计残项关闭提交 `68e419b79e379184c1f1cc7ad650039771530f89`，fix: close chain damage audit gaps）；2026-08-04 独立审计完成：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，最终独立复审结论 AUDIT_PASSED（status=audited、independent_audit_done=true、audit_conclusion=AUDIT_PASSED）；里程碑标签 `milestone-b2-chain-damage-infrastructure-audited` 为本次最终文档提交后由用户立即建立的标签名称（本轮未执行 git tag、未验证标签已存在）；三人以上传导顺序 NOT PROVEN，prevented_zero 无正式减伤路径端到端证明 |
| `CP-04K-JIEDAO-SLASH-COUNT` | 借刀杀人生产实现（依赖装备系统）的必测验收要求，2026-08-04 记录（规则见 Knowledge 4.6.1，必测清单见 4.6.2） | 必测：①第一目标已达正常杀次数上限但有合法【杀】时仍可响应借刀使用、不得自动交武器；②借刀要求使用的【杀】成功后产生正常 `card_used` 且杀使用次数增加；③借刀使用使杀次数达到或超过通常上限后，后续主动使用【杀】按正常次数规则被禁止（除非另有增加次数或无限次数效果）；④第一目标仅因次数达到上限不属于“无合法杀”；⑤只有无牌、目标失效、超出攻击范围或受禁止效果影响时，才按没有合法杀处理并交出武器 | 本批（CP-04I）不实现借刀代码；装备与攻击范围实现属于 CP-04K |
| `CP-04L-PRODUCTION-DELAYED-TRICK-JUDGMENT-INFRASTRUCTURE` | 正式160张牌堆三种延时锦囊＋判定与阶段基础设施批次：【乐不思蜀】（3张）、【兵粮寸断】（2张）、【闪电】（2张）接入生产适配器；正式阶段流（PREPARE→JUDGMENT→DRAW→PLAY→END）、判定区进入序号与动态LIFO判定队列、判定前【无懈可击】链、判定牌生命周期、乐不思蜀／兵粮寸断阶段跳过、闪电无来源雷属性伤害与转移／回置、死亡与胜利清理、判定彻底不足原子失败关闭、player_visible 双视角手牌隐私与牌堆顺序脱敏 | 3种／7张实体牌接入生产注册表；35项专项测试（`tests/test_sgs_production_delayed_tricks.py`）＋23项判定事件契约测试（`tests/test_sgs_engine_events.py`）；完整 pytest 见第 5 节；已由用户在外部PowerShell提交实现（提交哈希 `35c06bd50a431a62e7c3ad01d10384bf6884c403`，提交信息 feat: implement delayed tricks and judgment infrastructure；status=audited、commit=35c06bd50a431a62e7c3ad01d10384bf6884c403、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、milestone_tag=已建立标签 `milestone-b2-delayed-trick-judgment-infrastructure-audited`、worktree_commit_pending=false）；检查点文档提交 `4f2c9b61fccb4337a8e84ae560835d705be65bda`（docs: record delayed trick and judgment checkpoint）；最终修复提交 `eeeaf558cdaeeea0eb90456f907f83dce52286f3`（fix: harden player-visible replay privacy）；文档收口提交 `ba64b750fabd99f2bfc93697cea83e1272216d02`（docs: finalize delayed trick and judgment audit milestone）——HISTORICAL/AS-OF：当时里程碑标签已实际建立并推送，本地与 GitHub 远程标签均指向该提交；CURRENT LIVE REF：当前Git标签 `milestone-b2-delayed-trick-judgment-infrastructure-audited` 解析为 fc3df95202b23dccfd9abf5e476485a224d6fc2c，当前标签目标以Git标签解析结果为准 | 2026-08-05 第一次独立审计 AUDIT_FAILED_BLOCKING_ISSUES（唯一阻塞项 B1：player_visible 未脱敏 reshuffle 事件）；第一次审计修复提交 `96f536e1f392fd97faf61518a849a0d515b6a82e`（fix: close delayed trick audit gaps）完成 B1 修复与 N1–N9 关闭（完整 pytest 1724 passed）；2026-08-06 第二次最终复审 AUDIT_FAILED_BLOCKING_ISSUES（B1-a/B1-b/B1-c 与两个复审观察项），最终修复提交 `eeeaf558cdaeeea0eb90456f907f83dce52286f3` 完成修复与关闭（本地修复会话完整 pytest 1733 passed）；2026-08-06 Grok 网页端独立静态审计 STATIC_AUDIT_PASSED（经 GitHub 连接器读取精确目标提交，完整读取18个强制文件，PARTIAL_READ=无、NOT_READ=无；未亲自运行 pytest／Git／本地虚拟环境，运行类证据来自本地修复会话）；最终审计结论 AUDIT_PASSED | 三人以上延时锦囊与无懈响应顺序、三人以上闪电合法目标搜索、多人传导、改判、判定牌获得、判定结果修改、正式牌堆彻底不足平局、坐骑距离修正完整语义、防具与 prevented_zero 正式路径、弃牌阶段、武将技能均 NOT PROVEN |
| `MILESTONE-B2-GROUP-TARGET-TRICKS` | 正式160张牌堆群体普通锦囊批次：【南蛮入侵】（3张）、【万箭齐发】（1张）与【桃园结义】（1张）接入生产适配器，建立“群体普通锦囊按行动顺序逐目标结算框架” | 服务器自动目标序列（使用时快照、按行动顺序、跳过死亡角色）；逐目标独立【无懈可击】窗口（一张无懈只抵消当前目标、双无懈恢复、切换目标重置）；南蛮／万箭响应【杀】／【闪】记录为打出而非使用、不响应者受使用者1点无属性伤害；桃园目标集合与实际回复分开、逐目标回复不超过体力上限；濒死救援期间队列暂停与恢复；原锦囊全部目标完成前留在处理区；严格规则重执行与篡改失败关闭；完整测试 `1403 passed`，失败0、跳过0 | 已由用户在外部PowerShell提交（实现提交哈希 `5f2fbf27b7041bbf3010636de37306eea5da6256`，feat: implement production group-target trick slice）；基线提交 `7414b0661a5cd7599d392f5ae5b287a7147438ac`，检查点文档提交 `8d68231e336dbe213ffad1c5aaa3101896fe5f2f`；2026-08-03 独立只读审计完成：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES（问题修复提交 `ef98245aef32848468c7b2c4a7821ec9ae65146b`，test: close group-target trick audit gaps），最终独立复审结论 AUDIT_PASSED（复审残项关闭提交 `d2e4f49925c0bb285d44092821c3a85c496571ef`，test: complete group-target trick reaudit closure）；里程碑标签待用户提交文档后建立 |
| `CP-04M-PRODUCTION-ARMOR-DAMAGE-PREVENTION-INFRASTRUCTURE` | 正式160张牌堆四种防具＋伤害修正／防止基础设施批次：【八卦阵】（2张）、【仁王盾】（1张）、【藤甲】（2张）、【白银狮子】（1张）接入生产适配器；统一防具伤害修正管线（藤甲火属性伤害+1、白银狮子限伤）、仁王盾黑杀无效、藤甲免疫普通杀／南蛮／万箭、八卦阵响应窗口内可选判定与虚拟闪、白银狮子统一离区恢复、统一无视防具接口、prevented_zero 语义与伤害事件审计字段 | 4种／6张实体牌接入生产注册表；42项专项测试（`tests/test_sgs_production_armor_damage_prevention.py`）＋24项防具与伤害防止事件契约测试（`tests/test_sgs_engine_events.py`）；完整 pytest 见第 5 节；已由用户在外部PowerShell提交实现（提交 29ab73e006408e1e1582a300801e7aa6e04bd9c4，feat: implement armor and damage prevention infrastructure）；2026-08-06 Grok 网页端独立静态审计最终结论 STATIC_AUDIT_PASSED（status=audited、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、worktree_commit_pending=true）；里程碑标签 milestone-b2-armor-damage-prevention-infrastructure-audited 已实际建立并推送（本地与 GitHub 远程标签均已验证存在；标签在最终状态回填开始时指向最终审计文档提交 2db702fde037b501190950687059d660c32b56da，随后用户已将标签移动到承载最终仓库状态记录的提交，当前标签指向以Git标签解析结果为准，不硬编码具体SHA为永久标签目标） | 检查点文档提交 f0db82afcea9944143e224aed147d108c6eae061 与最终审计文档提交 2db702fde037b501190950687059d660c32b56da 均已存在 | 真实武器无视防具调用、三人以上传导顺序、防止类效果（如寒冰剑）、坐骑语义均 NOT PROVEN |
| `CP-04N-PRODUCTION-MOUNT-DISTANCE-INFRASTRUCTURE` | 正式160张牌堆坐骑＋距离／攻击范围基础设施批次：【攻击坐骑（-1坐骑）】（3张）、【防御坐骑（+1坐骑）】（4张）接入生产适配器；统一有效距离模型（基础座次距离＋进攻／防御坐骑方向性修正）、武器攻击范围与有效距离分离、杀／借刀／顺手／兵粮距离接入、坐骑装备与同栏位替换；正式160张实体牌全部注册 | 2种／7张实体牌接入生产注册表；33项专项测试（`tests/test_sgs_production_mount_distance.py`）；完整 pytest 见第 5 节；已由用户在外部PowerShell提交实现（提交 fd7d69f53e9827877b6a29d67c067012ead6a7af，feat: implement mounts and distance infrastructure）；2026-08-07 Grok 网页端独立静态审计最终结论 STATIC_AUDIT_PASSED（status=audited、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、worktree_commit_pending=false）；里程碑标签 milestone-b2-mount-distance-infrastructure-audited 已实际建立并推送（本地与 GitHub 远程标签均已验证存在） | 检查点文档提交 3231adef9aa97cc152c7476195e9f169c3b14a15 与最终审计文档提交 fbeec9c5ad14e8f4b5da85672dab4a70f961bd4e 均已存在 | 多人生产语义、多人死亡后的座次距离、完整武器技能、正式整局入口均 NOT PROVEN |
| `CP-04P-PRODUCTION-WEAPON-SKILL-COMPLETION` | 正式武器技能完整化：11种武器中8种／9张（诸葛连弩、青釭剑、寒冰剑、古锭刀、青龙偃月刀、贯石斧、朱雀羽扇、麒麟弓）完成正式生产语义——连弩无限出杀与失去后恢复、青釭剑真实防具无效生命周期（armor invalid；代码历史字段 ignore_armor。QINGGANG_LIFECYCLE_CONFIRMED：起点=杀指定一个目标后的武器技能实际生效时点、终点A=闪结算完成、终点B=本次伤害结算完成，显式清理点；抑制仁王盾／藤甲／白银狮子／八卦阵、防具实体不移除、结算后不残留）、寒冰剑伤害前防止＋逐张弃置目标手牌＋装备至多2张（2026-08-08 用户移动版实测确认一张一张弃置、两次连续正式弃置步骤）、古锭刀“造成伤害时”判定伤害+1（USER_CONFIRMED_MOBILE_RULE＋IN_GAME_CARD_TEXT_CONFIRMED：伤害时读取目标当前权威手牌，不使用指定目标时快照；与酒强化合并进入统一防具修正管线）、青龙偃月刀被闪后继续使用一张杀（追杀不消耗普通出牌阶段【杀】次数额度，USER_CONFIRMED_MOBILE_RULE）、贯石斧弃2张强制命中（两张牌一起选择并一起弃置的发动代价；贯石斧自身不能作为代价，USER_CONFIRMED_MOBILE_RULE）、朱雀羽扇转火杀（普通杀完成目标指定后转换，USER_CONFIRMED_MOBILE_UI_TIMING；含被借刀杀人要求使用杀时同样可转换）、麒麟弓（本次伤害真正结算、HP扣减/DAMAGE之前弃坐骑/放弃——USER_CONFIRMED_MOBILE_RULE）；其余3种（雌雄双股剑[DATA_MODEL_GAP: 无权威性别元数据，规则本身已知]、丈八蛇矛[VIRTUAL_CARD_SUBCARD_LIFECYCLE_RULE_GAP：subcard生命周期时点待确认]、方天画戟[多人生产基础环未建立]）保持集中式门禁失败关闭 | 70项武器专项测试（`tests/test_sgs_production_weapon_skills.py`）＋7项借刀朱雀专项（`tests/test_sgs_production_borrowed_sword_weapon_system.py`）；完整 pytest 1974 passed（失败0、跳过0）；compileall 通过；源码完整性审计 scanned_file_count=122、defect_count=0、audit_item_count=55；完整语义统计35种／157张；检查点状态为 audited、commit=implementation_commit=f0a50ce9ace71c5bf0a22540fbdca9e03aa918b3（实现提交，feat: implement verified production weapon skills，父提交 ef340c42e180ab14832b291bc0fc83f449a771a6）、checkpoint_commit=c30b26880b947217d64304ce430d32030b42941e（docs: record weapon skill completion checkpoint，已真实回填）、independent_audit_done=true、audit_conclusion=STATIC_AUDIT_PASSED、milestone_tag=milestone-b2-weapon-skills-audited（已实际建立并指向最终稳定基线 398ea58c9006ee9141ea1acfba35f6d9c497be48）、worktree_commit_pending=false；final_doc_commit=08d78cb6fed86360d647728a6f70422326918ff2 已真实回填；2026-08-08 Grok 独立静态审计 STATIC_AUDIT_PASSED（16章全PASSED、BLOCKING/NONBLOCKING NONE）；milestone_tag_verified=true | 本批基线为 `ef340c42e180ab14832b291bc0fc83f449a771a6`（milestone-b2-turn-cycle-discard-infrastructure-audited）；里程碑标签 milestone-b2-weapon-skills-audited（已实际建立并指向最终稳定基线 398ea58c9006ee9141ea1acfba35f6d9c497be48） | 完整武器技能（雌雄双股剑、丈八蛇矛、方天画戟3种）、神赵云龙魂等武将技能交互、正式整局入口均 NOT PROVEN |
| `WHOLE_REPO_AUDIT_REMEDIATION_1` | 整仓敌对式总审计定向修复：G-001死亡座次距离（alive-seat ring、dead target拒绝、3/4/5人死亡座次回归）、麒麟弓时序修正（Qilin先于HP扣减/DAMAGE，游戏内文本＋USER_CONFIRMED_MOBILE_RULE）、诸葛连弩来源等级 IN_GAME_CARD_TEXT_CONFIRMED、丈八统一fail-closed（不再split-brain）、G-004/G-005 live清理 | 实现提交 f1731b95199165a3449f1a0ce84d9facfc1b41c5（fix: remediate whole-repo audit findings，父提交 398ea58c9006ee9141ea1acfba35f6d9c497be48）已由用户在外部PowerShell提交；完整 pytest 1966 passed（implementation/regression evidence）；检查点状态为 committed_pending_audit、checkpoint_commit=null、independent_audit_done=false、audit_conclusion=NOT_AUDITED_YET、milestone_tag=null、worktree_commit_pending=true | 原总审计 CP04L_TO_CP04P_WHOLE_REPO_ADVERSARIAL_AUDIT=WHOLE_REPO_AUDIT_FAILED（G-001..G-005、N-001）；remediation-1 targeted re-audit=REMEDIATION_REAUDIT_FAILED（HISTORICAL/AS-OF：回填时 NOT_AUDITED_YET；CURRENT：已进行且失败，R1未获得通过的独立审计，不得改写为 PASSED） | multi_player_production_proven=false；WHOLE_REPO_AUDIT_PASSED 未成立 |
| `WHOLE_REPO_AUDIT_REMEDIATION_2` | 整仓敌对式总审计定向修复第二轮（remediation-1 targeted re-audit 失败后）：G-001 dead-self 统一fail-closed、R1-NEW-001 Qilin resolved final amount 跨pending、R1-NEW-002 Qinggang cleanup 绑定真正damage completion、G-003丈八fail-closed保持、G-004/G-005清理、【杀】family通则（基础术语20.12）与8项游戏内正式文本source同步 | 实现提交 e63b40ac1690e03315fd3e0734d5723fb80d5182（fix: complete second whole-repo audit remediation，父提交 4aafd95...）已由用户在外部PowerShell提交；完整 pytest 1974 passed（implementation/regression evidence，不是独立审计结论）；检查点状态为 committed_pending_audit、checkpoint_commit=null、milestone_tag=null、worktree_commit_pending=true；independent_audit_done=true、audit_conclusion=REMEDIATION_2_REAUDIT_FAILED（HISTORICAL/AS-OF：回填时 NOT_AUDITED_YET；CURRENT：remediation-2 targeted re-audit 已进行且失败，原因是当时G-004/G-005仍OPEN，R2整体不视为PASSED） | 原整仓审计 WHOLE_REPO_AUDIT_FAILED；remediation-1 targeted re-audit=REMEDIATION_REAUDIT_FAILED；G-002=G-002_SOURCE_GAP_LOCALLY_RESOLVED_PENDING_INDEPENDENT_REAUDIT（HISTORICAL/AS-OF：R2 实现完成、独立 re-audit 尚未发生时本地状态；CURRENT：remediation-2 targeted independent re-audit 已确认 G-002=CLOSED）；remediation-2 targeted re-audit=REMEDIATION_2_REAUDIT_FAILED（R2已确认CLOSED项G-001/G-002/G-003/QILIN_TIMING_BUG/R1-NEW-001/R1-NEW-002保持，但R2整体不视为PASSED） | multi_player_production_proven=false；WHOLE_REPO_AUDIT_PASSED 未成立 |
| `WHOLE_REPO_AUDIT_REMEDIATION_3` | 整仓敌对式总审计定向修复第三轮/最小收尾（remediation-2 targeted re-audit 失败后）：G-004 CP-04L ba64历史引用全部分层为HISTORICAL/AS-OF且current live ref统一fc3df952...（tag未移动）、G-005 stale清理（Zhuque borrowed/weapon test header/ignore_armor caller/turn-cycle discard header）、R2-NEW-001 annotation统一tuple[str,str]|None | 实现提交 9c63496e7f34430d8aff3c23e9afc5b5c4482557（fix: close remaining whole-repo audit findings，父提交 3121a300...）已由用户在外部PowerShell提交；完整 pytest 1974 passed（implementation/regression evidence，不是独立审计结论）；检查点状态为 committed_pending_audit、checkpoint_commit=null、independent_audit_done=false、audit_conclusion=NOT_AUDITED_YET、milestone_tag=null、worktree_commit_pending=true | 原整仓审计 WHOLE_REPO_AUDIT_FAILED；remediation-1 targeted re-audit=REMEDIATION_REAUDIT_FAILED；remediation-2 targeted re-audit=REMEDIATION_2_REAUDIT_FAILED；独立 re-audit 尚未进行 | multi_player_production_proven=false；WHOLE_REPO_AUDIT_PASSED 未成立 |
| `CP-04O-PRODUCTION-TURN-CYCLE-DISCARD-INFRASTRUCTURE` | 正式弃牌阶段＋权威回合循环基础设施：正式阶段流收敛为 PREPARE→JUDGMENT→DRAW→PLAY→DISCARD→END 单一权威回合循环；正式弃牌阶段（手牌上限默认等于当前体力值、装备区与判定区不计入手牌数；超限时“选择＋取消选择＋一次性提交”批量弃置——UI逐张选择只是选择过程，确认前不移动牌、不产生正式失牌／弃牌事件，提交时权威验证数量恰好等于超限数并作为同一次弃牌阶段操作一次性离开手牌；不接受负载伪造excess／hand_limit、旧动作失败关闭）；延时锦囊阶段跳过（乐不思蜀跳过出牌阶段、兵粮寸断跳过摸牌阶段）接入回合推进；出牌阶段次数在当前角色自己的下一个出牌阶段开始时清零；回合结束清理回合级临时状态、按座次转交下一存活角色、胜利后不再启动下一回合 | 49项专项测试（`tests/test_sgs_production_turn_cycle_discard.py`）；完整 pytest 1889 passed（失败0、跳过0）；compileall 通过；源码完整性审计 scanned_file_count=121、defect_count=0、audit_item_count=55；检查点状态为 audited、commit=b1afb1a613a45c630ae1e42975d276d62915e76d（实现提交）、checkpoint_commit=7aacd06cdfcf1725307061a3f5c03c233a2199f7、independent_audit_done=true、audit_conclusion=AUDIT_PASSED（2026-08-07 Grok 网页端独立只读静态审计 STATIC_AUDIT_PASSED，Grok 未亲自运行 pytest／Git／本地虚拟环境）、final_doc_commit=17246077776ef8a8c7f957706d60fd91e2c0a440（最终审计文档提交）、milestone_tag=已建立标签 milestone-b2-turn-cycle-discard-infrastructure-audited（已实际建立并推送：本地标签已由本轮亲自验证存在并在最终仓库状态回填开始时解析到 17246077776ef8a8c7f957706d60fd91e2c0a440，GitHub远程标签建立／推送事实来自用户外部PowerShell验证；当前标签目标以Git标签解析结果为准）、worktree_commit_pending=false；独立审计已通过 | 本批基线为 `f2eb98a03a56f57ddfd4d5d0a24c0ddb26176989`（milestone-b2-mount-distance-infrastructure-audited）；计划里程碑标签 milestone-b2-turn-cycle-discard-infrastructure-audited（待用户提交后建立） | 正式整局入口未接入权威回合循环；武器专属技能、武将技能、正式单挑、多人生产均 NOT PROVEN |

## 2. 阶段总览

| 阶段 | 状态 | 验收门槛 | 当前验收证据 | Git提交／检查点 | 遗留问题 |
|---|---|---|---|---|---|
| 1. 来源与调用链审计 | 通过 | 确定旧胜率入口、两个外部脚本与仓库关系、当前是否存在完整引擎 | `SOURCE_AND_CALLCHAIN_AUDIT.md` | `CP-01-SOURCE-AUDIT` | 旧 15 个 pickle 分片、旧运行日志及两份后续审计文档的生成程序未提供 |
| 2. 废止无效结果与失败关闭 | 通过 | 正式入口不能调用旧近似器；近似器不能输出“正式胜率”；所有旧结果有明确状态 | `LEGACY_RESULTS_INVALID.md`；`sgs_engine_gate.py`；`sgs_formal_runner.py` 真实读取160张牌后仍因核心／模式／AI未完成而拒绝运行且不写结果；28项专项测试通过 | `CP-02-LEGACY-STATUS` | 入口现在只提供状态与拒绝路径；完整对局属于阶段4，不在本阶段伪造 |
| 3. 正式引擎能力复核 | 通过 | 15 项能力逐项标记且能回答是否可完整运行一局 | `IMPLEMENTATION_MATRIX.md`、`ENGINE_STATUS.md` | `CP-03-ENGINE-INVENTORY` | 结论为“轻量组件库，无完整对局 runner”，不是引擎验收通过 |
| 4. 唯一权威规则核心 | 进行中 | 同一核心具备实体牌、玩家／游戏状态、事件队列、响应窗口、合法动作、确定性随机和回放；无技能完整对局可复现；静默近似为零 | foundation 已完成；`test_only_duel_vertical_slice` 使用同一核心完成【杀】【闪】【桃】双人无技能闭环；正式160张牌堆六种基本牌生产批次已接入同一核心（普通【杀】30、火【杀】5、雷【杀】9、【闪】24、【桃】12、【酒】5）；最小普通锦囊垂直切片（【无中生有】4、【无懈可击】7）已接入同一核心并建立普通锦囊无效响应窗口与连续无懈链；目标区域选牌批次（【过河拆桥】6、【顺手牵羊】5）已接入同一核心并完成目标区域选牌动作、隐藏手牌不透明句柄选择与直接弃置／直接获得实体牌事件；伤害型普通锦囊批次（【决斗】3、【火攻】3）已接入同一核心并完成交替打出【杀】状态机、目标展示手牌与同花色弃置／不弃置及伤害结算；群体普通锦囊批次（【南蛮入侵】3、【万箭齐发】1、【桃园结义】1）已接入同一核心并建立按行动顺序逐目标结算框架（服务器自动目标序列、逐目标独立【无懈可击】窗口、响应【杀】／【闪】或受伤／回复、濒死救援期间队列暂停与恢复）；剩余普通锦囊批次（【五谷丰登】2、【铁索连环】6）已接入同一核心并完成公共展示池与逐目标选牌、横置状态切换、重铸与属性伤害传导（统一生产管线，CP-04J）；【借刀杀人】＋武器牌本体批次（【借刀杀人】2、11种武器12张）已接入同一核心并完成两次目标检测、强制使用【杀】与按角色出杀计数、拒绝后武器直接进入使用者手牌、装备三事件与终局清理（CP-04K）；严格规则重执行已通过；完整测试 `1974 passed`（CP-04P 工作树验收；CP-04O 基线1889＋70项武器专项＋7项借刀朱雀专项；WHOLE_REPO_AUDIT_REMEDIATION_1 新增13项＋R2 新增8项：G-001 dead-self 1项、R1-NEW-001 Qilin×armor 7项；R2 实现提交 e63b40ac1690e03315fd3e0734d5723fb80d5182 已由用户在外部PowerShell创建） | `CP-04-CORE-FOUNDATION`；`455685d6eaa1c297e9ec48a0cfaeb803b81f3406`；`MILESTONE-B1-PRODUCTION-BASIC-CARDS`；`CP-04O-PRODUCTION-TURN-CYCLE-DISCARD-INFRASTRUCTURE` | 正式单挑规则范围仍未全部闭合；38种正式卡牌已全部接入生产适配器（35种／157张完整语义，雌雄双股剑／丈八蛇矛／方天画戟3种武器牌partial）；正式整局入口尚未接入权威回合循环，故 `authoritative_full_game_core=false`、`formal_run_ready=false` |
| 5. 卡牌与全部模式底层 | 未开始 | 正式范围卡牌和单挑、2v2、斗地主、五人身份、普通八人、限时八人 `unsupported=0`；每模式至少一局可复现 | 已有测试专用单挑垂直切片；正式范围仍仅有 Knowledge 与局部规则函数 | 待建立 | 测试专用切片不能替代正式160张牌逐阶段 runner；正式单挑生产适配器仍缺失 |
| 6. 当前武将逐名实现 | 未开始 | 每名武将的规则、状态机、确定性测试、网页人工场景、AI、反制均通过，才能允许正式胜率 | 现有多个武将局部函数和单元测试 | 待建立 | 所有武将当前均不得标记“允许正式胜率”；实验武将须隔离 |
| 7. 网页人工对局与回放 | 未开始 | 前端只消费统一核心；人工、PvE、AI观战、合法视角、全知审计视角、日志和回放可用 | 无网页或 HTTP 入口 | 待建立 | 图片不应阻塞功能；前端不得复制规则 |
| 8. 统一 AI 与反制审计 | 未开始 | AI 从完整合法动作集合选择；错误候选剪枝为零；隐藏信息隔离；记录选择与拒绝原因 | 现有策略评分函数为局部组件；foundation 已有严格动作路由 | 待建立 | 尚无完整模式的生产 `enumerate_legal_actions` 适配器，也无统一决策日志 |
| 9. 多进程正式胜率 | 未开始 | 使用同一核心和 AI；所有失败关闭门禁通过；输出完整溯源元数据 | 无正式批量入口 | 待建立 | 旧 worker／aggregate 不得复用为正式入口 |

## 3. 分阶段实施要求

### 阶段 1：来源与调用链审计

已完成事项：

- 盘点用户明列的 13 个外部文件及同目录直接相关文件；
- 还原 Shell → 15 个 worker 分片 → aggregate 的完整调用链；
- 确认配置来自 Shell 环境变量、Python 常量及输出 JSON，而不是依赖独立 `config.json`；
- 确认外部 worker 和 AI audit 均未导入正式仓库模块；
- 确认当前仓库没有另一套隐藏的完整引擎。

阶段结论以 `docs/SOURCE_AND_CALLCHAIN_AUDIT.md` 为准。

### 阶段 2：废止与失败关闭

已经完成：

- 对外部近似胜率、AI 自证审计及其派生报告建立统一失效声明；
- 明确后续文档可以引用它们作为历史缺陷证据，但不得引用数值作为现行胜率；
- 确认外部脚本不在当前正式导入链中；
- 建立纯函数门禁 `scripts/sgs_engine_gate.py`，拒绝 unsupported、近似替代、未实现／未测试武将、未完成模式／AI、错误牌堆、缺失规则版本、仓库外或非权威入口；
- 建立 `scripts/sgs_formal_runner.py`：`status` 真实加载并审计160张实体牌，`run` 在当前能力不足时返回结构化阻塞原因、退出码2，且不创建结果目录或文件；
- 入口源码不引用 Downloads legacy；门禁会现场重读入口、固定检查160张牌，并以不可由调用方写入的“完整整局核心未完成”哨兵阻止自证；目标测试实际为门禁19项、正式入口9项，均通过。

本阶段已经通过。正式对局、输出元数据和批量结果仍属于阶段4及阶段9；不能因为门禁存在就声称引擎已经存在。

### 阶段 3：现有能力复核

已经完成静态源码、正式 Knowledge、测试结构与可执行入口盘点。结论是：

- 160 张实体牌数据和唯一实例 ID 已存在，但没有装配进完整对局；
- 区域、事件、阶段、判定、伤害、模式、技能、策略均存在不同程度的局部实现；
- 没有统一 `GameState`、事件队列、响应窗口、合法动作枚举、完整 runner、全局确定性随机或回放；
- 无法用当前正式代码完整运行一局。

详细矩阵见 `docs/IMPLEMENTATION_MATRIX.md`。本阶段“通过”表示盘点完成，不表示引擎完成。

以上是阶段 3 完成时的修改前盘点。阶段 4 后续新增了统一基础类型与最小会话；这不改变阶段 3 的审计结论，也不等于已能完整运行一局。当前实时能力以本文件阶段 4、`ENGINE_STATUS.md` 和更新后的 `IMPLEMENTATION_MATRIX.md` 为准。

### 阶段 4：权威规则核心

当前状态：`进行中`。已完成失败关闭契约、基础类型、事件语义、160 张实体牌装配、确定性随机流及完整性回放基础。里程碑 A 已在专用模式 `test_only_duel_vertical_slice` 中完成【杀】【闪】【桃】双人无技能完整生命周期，并完成真正重新创建初始状态、重放决策、核对随机消费、事件序列、最终状态哈希和胜者的严格规则重执行；这不是仅读取既存事件的“播放”。

里程碑 A 的实际验收证据：

- Git 提交：`455685d6eaa1c297e9ec48a0cfaeb803b81f3406`；
- 50 个固定 seed 全部在安全上限内自然产生胜负，未使用启发式超时判胜；
- 最大对局长度为 187 个动作；
- 完整 pytest 为 `1135 passed`；
- `minimal_duel_vertical_slice=true`；
- `reexecution_replay_supported=true`，其当前通过范围为测试专用垂直切片；
- `authoritative_full_game_core=false`；
- `formal_run_ready=false`。

里程碑 B1（正式基本牌批次）的实际验收证据：

- Git 提交：`feat: implement production basic-card adapter batch`（本批次）；
- 从正式160张牌堆 CSV 真实读取六种基本牌共85张实体牌（普通【杀】30、火【杀】5、雷【杀】9、【闪】24、【桃】12、【酒】5）并关联生产适配器，实例ID唯一、总实体牌数仍为160；
- 六种基本牌的所有动作都经过 `enumerate_legal_actions → validate_action → apply_action`，伪造／过期动作失败关闭；
- 三种【杀】的伤害属性、响应窗口、每出牌阶段次数限制、目标与距离检查均落到真实事件；【闪】响应生成 `card_used` 且不生成普通 `card_played`；
- 【桃】三种用途与【酒】两种用途按正式 Knowledge 分开结算；牌区生命周期、牌守恒、唯一牌区与游戏结束后停止均有真实测试；
- 未实现卡牌（普通／延时锦囊、武器、防具、坐骑共26种）失败关闭，测试专用适配器未进入生产注册表；
- 含【杀】【闪】【桃】【酒】的 seed=5 生产路径可严格规则重执行，篡改动作／事件／随机消费均失败关闭；
- 完整 pytest 为 `1172 passed`；`production_basic_cards_batch=true`，`authoritative_full_game_core=false`、`formal_run_ready=false`。

里程碑 B2 目标区域选牌批次（【过河拆桥】／【顺手牵羊】）的实际验收证据：

- 从正式160张牌堆 CSV 真实读取【过河拆桥】6张（♣3、♣4、♥Q、♠3、♠4、♠Q）与【顺手牵羊】5张（♦3、♦4、♠3、♠4、♠J）并绑定生产适配器，实例ID唯一、总实体牌数仍为160；
- 两张牌继续复用【无中生有】／【无懈可击】已审计通过的普通锦囊使用窗口与逐张【无懈可击】响应链；被无效后不打开选牌窗口、不移动目标牌、原锦囊仍记已使用并进入弃牌堆；
- 目标区域选牌动作经过 `enumerate_legal_actions → validate_action → apply_action`；公开区域（装备区、判定区）以明确实体候选展示，隐藏手牌只暴露绑定“会话＋选择窗口＋目标＋区域＋当前手牌快照”的HMAC-SHA256不透明句柄（会话级 `secrets.token_bytes(32)` 随机秘密，输出128位；公开窗口ID、正式牌堆160个实体ID、正式CSV牌面与公开seed均不足以重建句柄；原裸SHA-256设计已被独立只读审计判定可被160项枚举攻击还原并定点修复），决策输入不泄露牌名、花色、点数、实体ID、会话秘密或私有映射；过期、伪造、跨会话、跨窗口、跨目标、跨区域、手牌变化后的句柄与状态哈希不符一律失败关闭；
- 【过河拆桥】把目标区域牌直接置入弃牌堆（不发生先获得再弃置）；【顺手牵羊】把目标区域牌直接从原区域移入使用者手牌；两者均记录原区域、原所有者、新所有者与来源锦囊；
- 【顺手牵羊】距离条件调用正式 `actual_distance` 接口，坐骑修正未实现时失败关闭；【过河拆桥】不继承距离限制；
- 结算时目标已无合法区域牌时不凭空选牌或移动，按“无合法区域牌”原因完成结算；
- 新增50项生产路径验收测试；隐藏句柄HMAC安全修复另新增29项安全回归测试（160项枚举攻击匹配数为0）；完整 pytest 为 `1281 passed`；`production_zone_target_trick_batch=true`，`hidden_handle_hmac_security_fix=true`，`authoritative_full_game_core=false`、`formal_run_ready=false`、`formal_duel_no_skill_ready=false`。

里程碑 B2 伤害型普通锦囊批次（【决斗】／【火攻】）的实际验收证据：

- 从正式160张牌堆 CSV 真实读取【决斗】3张与【火攻】3张并绑定生产适配器，实例ID唯一、总实体牌数仍为160；
- 两张牌继续复用【无中生有】／【无懈可击】已审计通过的普通锦囊使用窗口与逐张【无懈可击】响应链；被无效后不进入出【杀】链或展示／弃置窗口、不移动目标或使用者的其他牌、原锦囊仍记已使用并进入弃牌堆；
- 【决斗】生效后从目标开始交替打出【杀】；当前响应者同时拥有“打出合法【杀】”与“不打出”两个候选；响应【杀】按当前卡名为【杀】判断（普通／火／雷【杀】）；响应动作类型为打出，产生 `card_played`、不产生普通 `card_used`，实体牌完整经历手牌→处理区→弃牌堆；不响应者受到另一方参与者造成的1点无属性伤害，伤害关联牌为原【决斗】；死亡角色不能继续打出【杀】，轮到死亡角色响应时【决斗】立即结束且不补结算伤害；
- 【火攻】生效后由目标本人选择一张手牌展示（展示牌留在目标手牌区、公开牌面并产生 `card_revealed`），未展示手牌不进入其他角色决策视图与玩家可见回放；使用者随后选择弃置一张同花色手牌或不弃置（弃置产生 `CARD_MOVED`／`CARD_LOST`／`CARD_DISCARDED`，不产生使用／打出事件）；成功弃置后对目标造成1点火焰伤害；结算时目标已无手牌则本次【火攻】无效果完成；
- 新增51项生产路径验收测试（`tests/test_sgs_production_duel_fire_attack.py`）；2026-08-03 独立只读审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES（未发现规则、隐藏信息、回放、第二套引擎或虚假测试阻塞问题），并补充两个确定性回归测试（目标仅一张手牌的【火攻】展示、来源死亡后已开始的【决斗】不自动取消）；当前完整 pytest 为 `1334 passed`（失败0、跳过0）；`production_duel_fire_attack_batch=true`，`authoritative_full_game_core=false`、`formal_run_ready=false`、`formal_duel_no_skill_ready=false`。审计收尾真实提交为 `9c2070017fe624295ebd735bf5163f48a6ac2207`（test: close duel and fire attack audit gaps），里程碑标签 `milestone-b2-duel-fire-attack-audited` 已建立。

里程碑 B2 群体普通锦囊批次（【南蛮入侵】／【万箭齐发】／【桃园结义】）的实际验收证据：

- 从正式160张牌堆 CSV 真实读取【南蛮入侵】3张（♣7、♠7、♠K，实例061／141／158）与【万箭齐发】1张（♥A，实例082）与【桃园结义】1张（♥A，实例081）并绑定生产适配器，实例ID唯一、总实体牌数仍为160；三张牌均为出牌阶段主动使用、无距离限制、无基础每回合次数限制；
- 目标集合由服务器依据规则自动生成（使用时快照、按当前行动顺序从使用者沿座次数字递增循环、跳过已死亡角色、结算时不动态增删）：【南蛮入侵】与【万箭齐发】为“除使用者外的所有角色，依次结算”（target_template=all_other_characters），【桃园结义】为“所有已受伤角色”（target_template=all_wounded_characters，包含使用者）；LegalAction 不接受玩家可篡改的任意目标列表，伪造目标集合／顺序／索引一律失败关闭；
- 原锦囊使用后由使用者手牌进入处理区并产生一次正常 card_used，建立固定逐目标序列；每名目标有独立、可审计的目标效果事件（group_target_resolved：根锦囊实体ID、使用者、目标、目标索引、总目标数、结果与下一目标）；原锦囊在全部目标完成前始终留在处理区，最后目标完成后才进入弃牌堆；
- 每个目标单独打开该目标的【无懈可击】窗口：一张无懈只抵消当前目标的效果并推进下一目标，两张连续无懈恢复当前目标效果；每张无懈保留准确逐张 response_to，切换目标时新建目标效果窗口，前一目标的无懈状态不泄漏到后一目标；被无懈取消的当前目标不打开【杀】／【闪】响应或回复步骤；
- 【南蛮入侵】生效后当前目标可选择打出一张合法【杀】（普通／火／雷【杀】，按当前卡名判断）或主动不响应；响应为“打出”：产生 card_played、不产生普通 card_used、不计入使用牌次数、计入使用或打出牌总数，实体经历手牌→处理区→弃牌堆；不响应时受到1点无属性伤害，伤害来源为使用者，关联实体为原【南蛮入侵】；
- 【万箭齐发】生效后当前目标可选择打出一张合法【闪】或主动不响应；响应为“打出【闪】”（card_played、不产生 card_used、不计入使用牌次数、计入使用或打出总数、经历手牌→处理区→弃牌堆），不得把【闪】实现成“使用”；不响应时受到1点无属性伤害，来源为使用者；一名目标打出【闪】或受伤不影响下一目标（游戏未结束时）；
- 【桃园结义】的目标集合（使用时已受伤角色）与实际回复（结算时逐目标恢复1点、不超过体力上限、满体力目标无效果结算、不产生虚假回复）分开维护；自身与其他角色进入同一通用目标队列（双人切片按行动顺序连续处理 p1→p2 两个目标）；恢复事件记录来源（根【桃园结义】）、目标、实际恢复量、目标索引；
- 群体锦囊造成伤害触发濒死时队列暂停，进入现有桃／酒救援；救援结束后游戏未结束时从正确的下一目标继续（不重结算已完成目标、不跳过未处理目标、不提前丢弃原锦囊、不丢失根锦囊／目标索引／伤害来源），游戏已结束时立即停止；
- 群体响应动作以绑定“会话＋响应窗口＋当前目标＋根锦囊”的不透明句柄（gr_ 前缀）暴露，决策负载不携带实体牌ID、牌名、花色或点数；过期、伪造、非当前目标响应、伪造目标索引／根锦囊／窗口、手牌变化后的句柄、原锦囊离开处理区后或游戏结束后的动作一律失败关闭；玩家可见回放不泄露未打出的目标手牌；
- 新增69项生产路径验收测试（tests/test_sgs_production_group_target_tricks.py）；当前完整 pytest 为 `1403 passed`（失败0、跳过0）；`production_group_target_trick_batch=true`，`authoritative_full_game_core=false`、`formal_run_ready=false`、`formal_duel_no_skill_ready=false`。当前正式生产入口原生仅支持双人会话：三人以上目标顺序、中间目标濒死／死亡后的继续位置与来源死亡处理均未由正式生产入口证明（NOT PROVEN），不得写成完整军八、2v2或斗地主群体响应链已完成。2026-08-03 独立只读审计完成：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，首次审计问题修复提交 `ef98245aef32848468c7b2c4a7821ec9ae65146b`（test: close group-target trick audit gaps）；最终独立复审结论 AUDIT_PASSED，复审残项关闭提交 `d2e4f49925c0bb285d44092821c3a85c496571ef`（test: complete group-target trick reaudit closure）；里程碑标签待用户提交文档后建立。
- 新增40项生产路径验收测试（tests/test_sgs_production_chain_damage.py），审计残项关闭另增4项（prevented_zero控制流与文档检查，文件合计44项），链事件契约测试 `tests/test_sgs_engine_events.py` 63项（含36项新增）；当前完整 pytest 为 `1543 passed`（失败0、跳过0），compileall 通过，源码完整性审计 scanned_file_count=116、defect_count=0、audit_item_count=55；`production_chain_damage_infrastructure=true`，`authoritative_full_game_core=false`、`formal_run_ready=false`、`formal_duel_no_skill_ready=false`。当前正式生产入口仍为双人：三人以上传导顺序与多人属性伤害传导 NOT PROVEN，prevented_zero 仅完成状态机分支与事件契约、尚无正式减伤路径端到端证明。CP-04J 已由用户在外部PowerShell提交实现（实现提交哈希 `c094bff5dab127917e8d0b9a2d3422e3ab736783`，提交信息 feat: implement production chain damage infrastructure；检查点文档提交 `55228c9d464daac6eb061ba356b0497ec814eba6`；审计残项关闭提交 `68e419b79e379184c1f1cc7ad650039771530f89`，fix: close chain damage audit gaps），2026-08-04 独立审计完成：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，最终独立复审结论 AUDIT_PASSED（status=audited、independent_audit_done=true、audit_conclusion=AUDIT_PASSED）；里程碑标签 `milestone-b2-chain-damage-infrastructure-audited` 由用户在本次最终文档提交后立即建立（本轮未执行 git tag）。

里程碑 B2 借刀＋武器牌本体批次（CP-04K）的实际验收证据：

- 从正式160张牌堆 CSV 真实读取【借刀杀人】2张与11种武器12张实体牌并绑定生产适配器，实例ID唯一、总实体牌数仍为160；完整实现口径18种／128张（武器实体不计入完整实现），注册表口径29种适配器／140张实体，剩余9种（3种延时锦囊、4种防具、2种坐骑）；
- 武器牌本体：出牌阶段主动使用、武器进入weapon槽、同槽替换时旧武器原子移入弃牌堆、攻击范围每次从当前装备区按正式结构化CSV动态计算；新增 `equipment_equipped`／`equipment_removed`／`equipment_replaced` 三个最小装备事件并进入事件哈希链；
- 出杀次数升级为按角色记录的 `slash_used_counts`：主动使用【杀】增加自己的计数，某角色自己的新出牌阶段开始时只重置该角色计数；借刀强制【杀】绕过通常次数上限但仍增加第一目标自己的计数；
- 【借刀杀人】两次目标检测（使用时与无懈链结束后动态重检）、`card_used` 的 `target_ids` 只包含第一目标、只对第一目标打开【无懈可击】窗口、第一目标以HMAC-SHA256不透明句柄选择实体普通／火／雷【杀】或拒绝、成功使用即履行要求（被闪或未造成伤害也不交武器）、拒绝或无法使用时武器直接进入使用者手牌（`jiedaosharen_weapon_gain`，无牌可交时记录 `no_weapon_to_transfer`）；
- 借刀是外层根、被要求使用的【杀】是子结算：杀等待闪、濒死救援与属性传导期间保持挂起，子结算完成后恢复并只弃置根借刀一次；终局清理时根借刀从处理区确定性进入弃牌堆；
- 11种武器专属技能全部保持 partial，建立集中式 `check_weapon_skill_gate` 影响矩阵：可证明无影响时继续通用牌本体流程，否则在首次相关判断前抛 `UnsupportedRuleError`；
- 新增80项专项测试（`tests/test_sgs_production_borrowed_sword_weapon_system.py`）并扩展12项装备事件契约测试（`tests/test_sgs_engine_events.py`）；首次独立只读审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES（N1：装备事件reason封闭契约；N2：第二张诸葛连弩正式装备路径；N3：关键专项断言和严格回放），N1-N3 已由审计残项关闭提交 `79acc6ff514af4900acfe87507374fc8d696ec97`（fix: close borrowed sword weapon audit gaps）正式关闭，最终独立复审结论 AUDIT_PASSED；审计残项关闭后批次测试文件84项、事件契约测试85项、完整 pytest 为 `1649 passed`（失败0、跳过0），最终独立复审有效完整重跑 `1649 passed`，compileall 通过，源码完整性审计 `defect_count=0`（扫描117个Python文件）；`production_borrowed_sword_weapon_system=true`，`authoritative_full_game_core=false`、`formal_run_ready=false`、`formal_duel_no_skill_ready=false`、`multi_player_production_proven=false`。


里程碑 B2 三种延时锦囊＋判定与阶段基础设施批次（CP-04L）的实际验收证据：

- 从正式160张牌堆 CSV 真实读取【乐不思蜀】3张（058♣6／098♥6／137♠6）、【兵粮寸断】2张（053♣4／151♠10）、【闪电】2张（117♥Q／122♠A）并绑定生产适配器，实例ID唯一、总实体牌数仍为160；实施后完整实现口径21种／135张、注册表口径32种适配器／147张实体，剩余6种（4种防具、2种坐骑），剩余锦囊0；
- 正式回合阶段 PREPARE→JUDGMENT→DRAW→PLAY→END 由正式推进动作驱动，初始化与回合交接不再直接摸2；延时锦囊出牌阶段使用后直接进入目标判定区并分配单调递增 `judgment_zone_entry_index`，使用时不打开普通锦囊响应窗口；同名延时锦囊不得在同一角色判定区共存（枚举与apply双重验证），不同名可共存；
- 判定前【无懈可击】链复用已审计通过的逐张 `response_to` 基础设施（响应顺序：当前回合角色→对方，可连续抵消恢复）；被抵消时不翻判定牌、不产生判定结果与阶段跳过、不造成伤害；判定牌生命周期（牌堆→REVEALED→公开展示→judgment_result→弃牌堆）进入严格回放；
- 动态LIFO：判定阶段按 entry_index 从大到小逐张处理、本阶段已处理实例不再重复；闪电未命中或不被抵消时按“下家开始、存活座次递增”搜索合法目标（跳过死亡与已有闪电角色），无合法目标时回置当前角色并追加新 entry_index，回置后本阶段不再判定；
- 闪电命中执行3点无来源雷属性伤害（damage_source=None），完整处理传导、濒死、救援、死亡后本体才弃置；乐不思蜀判定非红桃只跳过本回合PLAY、兵粮寸断判定非梅花只跳过本回合DRAW（phase_skipped 事件精确记录）；角色死亡时手牌／装备／判定区以系统区域移动置入弃牌堆，幸存角色区域不因胜利清空；
- 判定彻底不足（牌堆＋可重洗弃牌堆合计不足1张）原子失败关闭：不生成判定牌、不移动本体、不消费随机、不改变牌堆顺序，不得描述为正式平局（正式平局出口 NOT PROVEN）；
- player_visible 导出按观察者身份过滤：移除 seed、初始随机状态与随机消费记录，初始发牌与摸牌的非公开获得只对获得角色本人暴露实体，五谷／顺手／借刀等公开获得路径保持公开；
- 新增35项专项测试（`tests/test_sgs_production_delayed_tricks.py`）并扩展23项判定事件契约测试（`tests/test_sgs_engine_events.py`：`judgment_started`／`judgment_result`／`phase_skipped`／`delayed_trick_transferred` 的合法构造与非法构造参数化）；已由用户在外部PowerShell提交实现（提交哈希 `35c06bd50a431a62e7c3ad01d10384bf6884c403`，提交信息 feat: implement delayed tricks and judgment infrastructure）；2026-08-05 第一次独立审计 AUDIT_FAILED_BLOCKING_ISSUES（唯一阻塞项 B1），B1 修复与 N1–N9 关闭已完成（第一次审计修复提交 `96f536e1f392fd97faf61518a849a0d515b6a82e`，完整 pytest 1724 passed）；2026-08-06 第二次最终复审 AUDIT_FAILED_BLOCKING_ISSUES 后，B1-a/B1-b/B1-c 修复与两个复审观察项关闭新增9项测试，本地修复会话完整 pytest 1733 passed；最终修复提交 `eeeaf558cdaeeea0eb90456f907f83dce52286f3`（fix: harden player-visible replay privacy）；2026-08-06 Grok 网页端独立静态审计 STATIC_AUDIT_PASSED（经 GitHub 连接器读取精确目标提交 eeeaf558，完整读取18个强制生产、测试和状态文件，PARTIAL_READ=无、NOT_READ=无；Grok 未亲自运行 pytest、Git 或本地虚拟环境，1733 passed 等运行结果来自本地修复会话，两类证据分别记录、不得混写）；最终审计结论 AUDIT_PASSED（status=audited、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、milestone_tag=已建立标签 `milestone-b2-delayed-trick-judgment-infrastructure-audited`、worktree_commit_pending=false）；文档收口提交 `ba64b750fabd99f2bfc93697cea83e1272216d02`（docs: finalize delayed trick and judgment audit milestone）——HISTORICAL/AS-OF：当时里程碑标签已实际建立并推送，本地与 GitHub 远程标签均指向该提交；CURRENT LIVE REF：当前Git标签 `milestone-b2-delayed-trick-judgment-infrastructure-audited` 解析为 fc3df95202b23dccfd9abf5e476485a224d6fc2c，当前标签目标以Git标签解析结果为准。


里程碑 B2 四种防具＋伤害修正／防止基础设施批次（CP-04M）的实际验收证据：

- 从正式160张牌堆 CSV 真实读取【八卦阵】2张（045♣2／125♠2）、【仁王盾】1张（047♣2 EX）、【藤甲】2张（046♣2／126♠2）、【白银狮子】1张（043♣A）并绑定生产适配器，实例ID唯一、总实体牌数仍为160；实施后完整实现口径25种／141张、注册表口径36种适配器／153张实体，剩余2种（攻击坐骑、防御坐骑），剩余锦囊0；
- 统一伤害修正管线：全部伤害入口（杀／属性杀／决斗／火攻／南蛮／万箭／闪电／传导／无来源）经统一防具解析，修正顺序为“藤甲火属性伤害+1 → 白银狮子限伤”；最终伤害不得为负、最终为0时不扣HP／不濒死／不传导并产生可审计防止结果；传导目标各自独立修正且不改变后续基数；
- 统一防具无效判断：仁王盾黑色杀无效、藤甲普通杀／南蛮／万箭无效，发生在响应窗口前，不消耗响应牌、不受伤、不濒死、不传导，杀仍计已使用并弃置；群体锦囊逐目标以 armor_invalidated 推进；
- 八卦阵：响应杀／万箭窗口内可选发动判定（每窗口一次），红判产生虚拟闪（card_used／card_played，不创建实体），黑判失败后可继续真实响应；判定牌牌堆顶→REVEALED→公开→弃牌堆，无判定前无懈窗口，牌量不足原子失败关闭；
- 白银狮子：限伤适用于全部伤害；离区恢复挂在统一装备离区钩子（替换／过河弃置／顺手获得），满血或已死亡不恢复、死亡清理不触发、同一实例每次离区只触发一次；
- 统一无视防具接口（ignore_armor）可抑制无效与修正；当前无真实武器调用者，青釭剑等仍由集中式武器门禁失败关闭（真实武器无视防具 NOT PROVEN）；
- 新增42项专项测试（`tests/test_sgs_production_armor_damage_prevention.py`）并扩展24项事件契约测试（`tests/test_sgs_engine_events.py`：`armor_judgment_started`／`armor_judgment_result`／`armor_recovered`／`damage_prevented` 的合法与非法构造参数化）；实现提交 29ab73e006408e1e1582a300801e7aa6e04bd9c4（feat: implement armor and damage prevention infrastructure）已由用户在外部PowerShell提交；2026-08-06 Grok 网页端经 GitHub 连接器独立静态审计最终结论 STATIC_AUDIT_PASSED（24个强制文件全部完成相关正文阅读，PARTIAL_READ=空、NOT_READ=空，13个强制章节均为PASSED，未发现阻塞问题；首轮 STATIC_AUDIT_INCOMPLETE 是强制文件正文阅读范围尚未补齐，不是代码阻塞缺陷）；正确生产文件路径为 scripts/sgs_engine/__init__.py；最终审计文档提交 2db702fde037b501190950687059d660c32b56da（docs: finalize armor and damage prevention audit milestone）已由用户在外部PowerShell提交；里程碑标签 milestone-b2-armor-damage-prevention-infrastructure-audited 已实际建立并推送，本地与 GitHub 远程标签均已由用户在外部PowerShell验证存在。


里程碑 B2 正式坐骑＋距离／攻击范围基础设施批次（CP-04N）的实际验收证据：

- 从正式160张牌堆 CSV 真实读取【攻击坐骑（-1坐骑）】3张（039紫骍♦K／094赤兔♥5／159大宛♠K）与【防御坐骑（+1坐骑）】4张（040骅骝♦K／055的卢♣5／119爪黄飞电♥K／135绝影♠5）并绑定生产适配器，实例ID唯一、总实体牌数仍为160；实施后注册表38种／160张、完整实现27种／148张、剩余未注册0种／0张，正式160张实体牌全部注册（formal_deck_registration_complete=true）；
- 统一权威距离模型：`base_seat_distance`（环形座次较小值）＋坐骑修正得到 `effective_distance`；进攻坐骑只影响装备者到别人的距离（-1）、防御坐骑只影响别人到装备者的距离（+1），有效距离不得小于0、自己到自己的距离固定为0；距离由权威状态实时计算，不接受动作负载伪造；
- 武器攻击范围与有效距离分离：杀及属性杀目标合法性＝有效距离≤攻击范围，借刀第二目标按第一目标攻击范围与双方坐骑计算；顺手与兵粮的“实际距离为1”使用有效距离，武器攻击范围不扩大该限制；装备变化后旧动作失败关闭、非法距离不消耗牌；
- 坐骑装备复用统一装备路径（`use_mount`），同栏位替换原子化、进攻与防御坐骑可同时存在、四类栏位互不覆盖；被过河弃置、顺手获得或死亡清理移走后距离立即重算，坐骑离区不触发白银狮子防具恢复；
- 新增33项专项测试（`tests/test_sgs_production_mount_distance.py`，覆盖 A–H 语义矩阵）与提交前距离下限纠正测试（DISTANCE_FLOOR_FIXED，专项共41项）；实现提交 fd7d69f53e9827877b6a29d67c067012ead6a7af（feat: implement mounts and distance infrastructure）已由用户在外部PowerShell提交；2026-08-07 Grok 网页端经 GitHub 连接器独立静态审计最终结论 STATIC_AUDIT_PASSED（24个强制文件全部完成要求范围阅读，PARTIAL_READ=空、NOT_READ=空，14个强制审计章节全部PASSED，Blocking issues 无；正确生产文件路径为 scripts/sgs_engine/__init__.py）；最终审计文档提交 fbeec9c5ad14e8f4b5da85672dab4a70f961bd4e（docs: finalize mount and distance audit milestone）已由用户在外部PowerShell提交；里程碑标签 milestone-b2-mount-distance-infrastructure-audited 已实际建立并推送（本地与 GitHub 远程标签均已由用户验证存在）。

阶段 4 仍不得标记为“通过”：里程碑 B 的正式 160 张牌无技能单挑尚未实现。六种基本牌生产批次（里程碑 B1）与多个普通锦囊批次（里程碑 B2）只是步骤，当前阻塞不是缺少测试闭环，而是必须先锁定正式单挑的规则适用范围，并把正式牌堆实际包含的 38 种卡牌逐一接入同一权威状态、事件、响应和动作路径；目前仍有6种（4种防具、2种坐骑）未接入；铁索连环完整语义（含属性伤害传导）、【借刀杀人】完整语义与11种武器牌本体已接入。不得用测试小牌堆、概率替代或跳过未实现卡牌来伪造里程碑 B。

实施顺序建议：

1. 定义不可绕过的失败关闭契约与规则版本标识；
2. 定义 `CardInstance`、`PlayerState`、`GameState`、`EventQueue`、`ResponseWindow`、`DamageEvent`、`LegalAction`、`DeterministicRNG`、`ReplayRecord`；
3. 统一现有分散事件语义；
4. 接入 160 张实体牌与牌区移动；
5. 先完成无技能最小对局；（已由里程碑 A 完成）
6. 建立同 seed、同动作序列的严格规则重执行回放；（已由里程碑 A 完成）
7. 所有未实现分支抛出明确错误，禁止概率近似和默认收益。

### 阶段 5：卡牌与模式

按“通用卡牌底层 → 单挑最小模式 → 2v2 → 斗地主 → 五人身份 → 普通八人 → 限时八人”的顺序推进。每个模式必须通过：

- 开局与座次；
- 完整回合；
- 救援、死亡与胜负；
- 模式专属技能／奖励；
- 固定 seed 回放；
- 至少一个极端边界；
- `unsupported=0`。

未通过的模式不得进入武将正式胜率。

### 阶段 6：武将

以正式候选池、主公池和实验池为输入逐名维护，不凭旧外部 16 将列表限定范围。每名武将的七项门禁记录在 `IMPLEMENTATION_MATRIX.md`：

1. 规则正文完整；
2. 程序实现完成；
3. 确定性测试通过；
4. 网页人工场景通过；
5. AI 策略完成；
6. 反制策略完成；
7. 允许正式胜率。

现有局部函数和测试可复用，但必须重新接入统一核心并验证真实状态变化。

### 阶段 7：网页与回放

只有阶段 4 与对应模式通过后才开始。前端不得计算规则；合法动作、可见状态和回放均由后端权威核心提供。合法视角与全知审计视角必须物理隔离 AI 输入。

### 阶段 8：统一 AI

只有完整合法动作枚举存在后才可验收。每个关键决策必须记录完整候选、拒绝项、评分分解、使用信息、规则来源、策略来源和原因。局部策略函数可以迁移为评分组件，不能继续由调用方手工裁剪候选。

### 阶段 9：正式批量胜率

只有阶段 4 至 8 对参战范围全部通过后才允许正式运行。每份产物至少包含：

```text
engine_version
git_commit（必须记录生成产物时的真实提交）
ruleset_hash
deck_hash
general_data_hash
strategy_version
seed_range
game_count
process_count
unsupported_rules
approximation_count
tests_passed
```

## 4. 全局失败关闭门槛

正式模拟入口对以下任一情况必须拒绝运行，而不是降级：

```text
unsupported_rules > 0
approximation_count > 0
参战武将未实现
参战武将确定性测试未通过
模式未完整实现
牌堆未正确加载
规则版本无法确定
合法动作枚举不完整
回放无法确定性复现
```

若仅进行明确标注的研发实验，可在隔离入口运行，但输出必须含 `experimental=true`，不得使用“正式胜率”标签，也不得与正式结果聚合。

## 5. 测试与报告纪律

1. 每次代码变更至少实际运行 `python -m pytest -q`；
2. 必要时运行 `python -m compileall -q scripts tests`；
3. 后续新增类型检查、lint、前端测试或 CI 后，将真实命令补入本文件；
4. 不把 `chosen = expected; assert chosen == expected` 或未调用真实程序路径的测试计入验收；
5. 失败、跳过和未运行必须分别报告；
6. 修改前基线 `947 passed in 3.39s` 只证明当时组件测试通过；Git 基线建立后为 `1094 passed`；里程碑 A 验收为 `1135 passed`；正式基本牌批次验收为 `1172 passed`；最小普通锦囊垂直切片验收为 `1197 passed`；目标区域选牌批次验收为 `1252 passed`；隐藏句柄HMAC安全修复验收为 `1281 passed`（在1252基础上新增29项安全回归测试）；伤害型普通锦囊批次（【决斗】／【火攻】）验收为 `1332 passed`（在1281基础上新增51项生产路径测试），独立只读审计 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES（2026-08-03）补充2项确定性回归测试后为 `1334 passed`；【借刀杀人】＋武器牌本体批次（CP-04K）验收为 `1635 passed`（在1543基础上新增80项专项与12项装备事件契约测试）；CP-04K 首次独立审计非阻塞问题 N1-N3 关闭新增14项（4项借刀武器专项＋10项装备事件reason契约）后验收为 `1649 passed`；群体普通锦囊批次（【南蛮入侵】／【万箭齐发】／【桃园结义】）验收为 `1403 passed`（在1334基础上新增69项生产路径测试）；剩余普通锦囊批次（【五谷丰登】完整生产语义＋【铁索连环】牌本体）验收为 `1454 passed`（在1403基础上新增51项生产路径测试，2026-08-04 已由用户在外部PowerShell提交实现，提交哈希 `20cb1b1f766529a88aa5f3346a4761b77eca66b7`），2026-08-03 独立只读审计完成（初次结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES，首次审计问题修复提交 `ef98245aef32848468c7b2c4a7821ec9ae65146b`，最终独立复审结论 AUDIT_PASSED，复审残项关闭提交 `d2e4f49925c0bb285d44092821c3a85c496571ef`）；CP-04I 独立审计于 2026-08-04 完成：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES（审计问题关闭提交 `5b1c2c15b6a8e21563aab02d8a5c181c553e4967`），最终独立复审结论 AUDIT_PASSED（最终措辞修正提交 `b2d4ffca18092938437d15826efdaddba8a0a689`），审计问题关闭后新增9项回归测试，批次测试文件共60项、完整 pytest 为 `1463 passed`；CP-04J 属性伤害传导基础设施新增40项生产路径测试，完整 pytest 为 `1503 passed`；CP-04J 审计残项关闭新增40项（36项链事件契约＋4项prevented_zero控制流与文档检查）后完整 pytest 为 `1543 passed`。；CP-04L 三种延时锦囊＋判定与阶段基础设施批次（【乐不思蜀】【兵粮寸断】【闪电】）实现提交时验收为 `1707 passed`（在1649基础上新增35项延时锦囊专项与23项判定事件契约测试），已由用户在外部PowerShell提交实现（提交哈希 `35c06bd50a431a62e7c3ad01d10384bf6884c403`）；2026-08-05 第一次独立审计 AUDIT_FAILED_BLOCKING_ISSUES（唯一阻塞项 B1：player_visible 未脱敏 reshuffle 事件）后，B1 实质修复与 N1–N9 关闭新增17项测试，完整 pytest 为 `1724 passed`（第一次审计修复提交 `96f536e1f392fd97faf61518a849a0d515b6a82e`）；2026-08-06 第二次最终复审 AUDIT_FAILED_BLOCKING_ISSUES（B1-a/B1-b/B1-c 与两个复审观察项）后，最终修复与关闭新增9项测试，本地修复会话完整 pytest 为 `1733 passed`（1724 保留为第一次修复后历史结果）；最终修复提交 `eeeaf558cdaeeea0eb90456f907f83dce52286f3`（fix: harden player-visible replay privacy）；2026-08-06 Grok 网页端独立静态审计 STATIC_AUDIT_PASSED（经 GitHub 连接器读取精确目标提交，完整读取18个强制文件，PARTIAL_READ=无、NOT_READ=无；未亲自运行 pytest／Git／本地虚拟环境，运行类证据来自本地修复会话）；最终审计结论 AUDIT_PASSED（status=audited、independent_audit_done=true、audit_conclusion=AUDIT_PASSED、milestone_tag=已建立标签 `milestone-b2-delayed-trick-judgment-infrastructure-audited`、worktree_commit_pending=false）；文档收口提交 `ba64b750fabd99f2bfc93697cea83e1272216d02`（docs: finalize delayed trick and judgment audit milestone）——HISTORICAL/AS-OF：当时里程碑标签已实际建立并推送，本地与 GitHub 远程标签均指向该提交；CURRENT LIVE REF：当前Git标签 `milestone-b2-delayed-trick-judgment-infrastructure-audited` 解析为 fc3df95202b23dccfd9abf5e476485a224d6fc2c，当前标签目标以Git标签解析结果为准。；CP-04M 四种防具＋伤害修正／防止基础设施批次（【八卦阵】【仁王盾】【藤甲】【白银狮子】）工作树验收为 `1799 passed`（在1733基础上新增42项防具专项与24项防具事件契约测试）；实现提交已由用户在外部PowerShell提交，独立审计尚未进行；CP-04N 正式坐骑＋距离／攻击范围基础设施批次（【攻击坐骑】【防御坐骑】）工作树验收为 `1832 passed`（在1799基础上新增33项坐骑与距离专项测试），提交前距离下限阻塞性复核新增6项边界测试后为 `1838 passed`；距离下限纠正（DISTANCE_FLOOR_FIXED：自己到自己的距离永远为0；两名不同角色之间的最终距离最低为1；-1坐骑不得把相邻角色距离1修正为0）新增2项测试后为 `1840 passed`；实现提交与检查点文档提交均已由用户在外部PowerShell提交，独立静态审计已通过（STATIC_AUDIT_PASSED）。这些结果证明对应范围的实现与回归测试，不把测试专用垂直切片或基本牌批次扩大解释为正式160张牌完整引擎。

## 6. 下一验收目标

当前已通过阶段 1–3和阶段 4 内部里程碑 A；阶段 4 总体仍为“进行中”。下一精确门槛是里程碑 B：在不建立第二套引擎的前提下，完成正式 160 张牌无技能单挑。必须同时满足：

- 锁定正式单挑的规则适用范围，对 Knowledge 未确认的先手首轮摸牌、距离、手气卡等项目给出明确配置或保持阻塞，不凭模型记忆补齐；
- 真实加载并核验160张实体牌，保持唯一实例ID和全程牌区守恒；
- 对正式牌堆实际包含的38种卡牌建立生产适配器，覆盖使用时机、次数、目标、距离、响应、无懈链、装备、判定、延时锦囊、伤害及处理区生命周期（六种基本牌、全部普通锦囊（含【借刀杀人】完整语义）与11种武器牌本体已接入，其余9种仍未实现：3种延时锦囊、4种防具、2种坐骑）；
- 正式 `duel` 模式使用与里程碑 A 相同的 `GameState`、事件、动作枚举、唯一 `DeterministicRNG` 和严格规则重执行机制；
- 多个固定 seed（目标至少100个）均自然结束，任何安全上限触发都算失败，不允许排除失败 seed；
- 正式门禁现场达到 `deck_count=160`、`unsupported_rules=0`、`approximation_count=0`、`mode_implemented=true`、`all_cards_implemented=true`、`reexecution_replay_supported=true`；
- 完整 pytest、compileall 和源码防伪扫描继续通过。

里程碑 B 当前为“阻塞／未通过”：正式单挑规则范围与完整卡牌语义尚未完成（38种已全部注册，但“全部注册”不等于全部语义完成），项目已保持失败关闭，没有用测试专用实现生成正式结果。

在此之前，网页、完整武将池和正式多进程胜率均保持“未开始”。

里程碑 A 最终验收实际结果：完整 pytest 为 `1135 passed`；50 个 seed 全部自然结束，最大187个动作；规则重执行回放及篡改拒绝测试通过。正式基本牌批次最终验收实际结果：完整 pytest 为 `1172 passed`，compileall 通过，源码完整性审计 `defect_count=0`（扫描109个Python文件）。最小普通锦囊垂直切片最终验收实际结果：完整 pytest 为 `1197 passed`（新增20项均为生产路径测试，失败0、跳过0），compileall 通过，源码完整性审计 `defect_count=0`（扫描110个Python文件）。目标区域选牌批次最终验收实际结果：完整 pytest 为 `1252 passed`（新增50项均为生产路径测试，失败0、跳过0），compileall 通过，源码完整性审计 `defect_count=0`（扫描111个Python文件）。隐藏句柄HMAC安全修复最终验收实际结果：完整 pytest 为 `1281 passed`（新增29项均为安全回归测试，失败0、跳过0），160项公开枚举攻击匹配数为0，回放私有材料删除或篡改均失败关闭，compileall 通过，源码完整性审计 `defect_count=0`。伤害型普通锦囊批次（【决斗】／【火攻】）最终验收实际结果：完整 pytest 为 `1334 passed`（新增51项均为生产路径测试，2026-08-03 独立只读审计 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES 后补充2项确定性回归测试，失败0、跳过0），compileall 通过，源码完整性审计 `defect_count=0`（扫描113个Python文件，audit_item_count=54）。群体普通锦囊批次（【南蛮入侵】／【万箭齐发】／【桃园结义】）最终验收实际结果：完整 pytest 为 `1403 passed`（新增69项均为生产路径测试，失败0、跳过0），compileall 通过，源码完整性审计 `defect_count=0`（扫描114个Python文件，audit_item_count=54）；2026-08-03 独立只读审计完成：初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES（首次审计问题修复提交 `ef98245aef32848468c7b2c4a7821ec9ae65146b`），最终独立复审结论 AUDIT_PASSED（复审残项关闭提交 `d2e4f49925c0bb285d44092821c3a85c496571ef`），里程碑标签 `milestone-b2-group-target-tricks-audited` 已由用户真实建立（指向基线提交 `6af30432993d908546d7cec114fd78ae62798ad5`，2026-08-04 回填）。剩余普通锦囊批次（【五谷丰登】完整生产语义＋【铁索连环】牌本体）最终验收实际结果：完整 pytest 为 `1454 passed`（新增51项均为生产路径测试，失败0、跳过0）；CP-04I 独立审计三个非阻塞问题关闭后新增9项回归测试（清单状态、横置角色火／雷／火攻失败关闭原子性、无属性与未横置正常结算、五谷牌量不足原子性、铁索重铸空牌堆空弃牌堆成功重洗摸回、重铸牌参与重洗候选池），完整 pytest 为 `1463 passed`（失败0、跳过0），compileall 通过，源码完整性审计 `defect_count=0`；铁索完整语义已由 CP-04J 完成（`tiesuo_chain_damage_implemented=true`），CP-04I 临时失败关闭门禁已移除，借刀等待装备生产切片（CP-04K）；CP-04I 状态 audited（实现提交 `20cb1b1f766529a88aa5f3346a4761b77eca66b7`，提交信息 feat: implement wugu and tiesuo card-body slice；检查点文档提交 `e8116c1d16e879d8445bbcf3fa0e89a161cf426d`；审计问题关闭提交 `5b1c2c15b6a8e21563aab02d8a5c181c553e4967`；最终措辞修正提交 `b2d4ffca18092938437d15826efdaddba8a0a689`），初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES、最终独立复审结论 AUDIT_PASSED，批次测试文件共60项；里程碑标签 `milestone-b2-wugu-tiesuo-card-body-audited` 由用户在本次最终文档提交后立即建立（本轮未执行 git tag）。CP-04J 属性伤害传导基础设施最终验收实际结果：新增40项生产路径测试（tests/test_sgs_production_chain_damage.py），审计残项关闭另增4项（文件合计44项），链事件契约测试 tests/test_sgs_engine_events.py 63项（含36项新增），最终独立复审定向回归 434 passed，完整 pytest 为 `1543 passed`（失败0、跳过0），compileall 通过，源码完整性审计 scanned_file_count=116、defect_count=0、audit_item_count=55，git diff --check 通过，SHA-256 清单31项全部匹配；完整实现口径更新为17种／126张，剩余21种（剩余普通锦囊仅借刀杀人）；tiesuo_chain_damage_implemented=true、tiesuo_full_semantics_complete=true（均限于当前双人正式生产入口范围）；CP-04I 临时失败关闭门禁已移除；CP-04J 状态 audited（实现提交 `c094bff5dab127917e8d0b9a2d3422e3ab736783`，提交信息 feat: implement production chain damage infrastructure；检查点文档提交 `55228c9d464daac6eb061ba356b0497ec814eba6`；审计残项关闭提交 `68e419b79e379184c1f1cc7ad650039771530f89`，fix: close chain damage audit gaps），初次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES、最终独立复审结论 AUDIT_PASSED（independent_audit_done=true、audit_conclusion=AUDIT_PASSED）；里程碑标签 `milestone-b2-chain-damage-infrastructure-audited` 由用户在本次最终文档提交后立即建立（本轮未执行 git tag）；三人以上传导顺序 NOT PROVEN，prevented_zero 仅完成状态机分支与事件契约、尚无正式防具减伤或伤害防止路径端到端证明。【借刀杀人】＋武器牌本体批次（CP-04K）最终验收实际结果：完整 pytest 为 `1635 passed`（在1543基础上新增80项借刀＋武器专项与12项装备事件契约测试，失败0、跳过0）；首次独立只读审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES（N1-N3 已由审计残项关闭提交 `79acc6ff514af4900acfe87507374fc8d696ec97` 正式关闭，最终独立复审结论 AUDIT_PASSED），审计残项关闭新增14项（4项借刀武器专项＋10项装备事件reason契约）后完整 pytest 为 `1649 passed`（失败0、跳过0），compileall 通过，源码完整性审计 `defect_count=0`（扫描117个Python文件，audit_item_count=55），SHA-256 清单33个文件条目全部匹配；另有1个 `hash_note` 元数据项，不计作文件哈希；检查点状态为 audited、commit=75c596b12f34a6222d972b2190148386bb670653、independent_audit_done=true、audit_conclusion=AUDIT_PASSED；检查点文档提交 f0008b571f502e0d6b7cc1800de9c2a8e39074e3；审计残项关闭提交 79acc6ff514af4900acfe87507374fc8d696ec97（fix: close borrowed sword weapon audit gaps）；首次审计结论 AUDIT_PASSED_WITH_NONBLOCKING_ISSUES（N1-N3 已关闭），最终独立复审结论 AUDIT_PASSED；里程碑标签 milestone-b2-borrowed-sword-weapon-system-audited 计划在本次最终文档提交后由用户建立（本轮未执行 git tag）。阶段 4 总体和里程碑 B 仍未通过，`authoritative_full_game_core=false`、`formal_run_ready=false`、`formal_duel_no_skill_ready=false`。项目没有 mypy、ruff、前端工程或 CI 配置，因此类型检查、lint、前端测试和 CI 均为“未配置”，不得表述为通过。
