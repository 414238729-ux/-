# POST_C8_PLAYABLE_RUNTIME_AI_AND_PARALLEL_SIMULATION_V1：实施矩阵

基线现场核验：HEAD `9991abc8091943e7316875734bae2e5967cc6e64`，annotated tag
`c8-timed-8p-deterministic-virtual-time-v1-audited` 的 commit 相同，初始工作树干净。
开发分支：`codex/post-c8-playable-runtime-ai-parallel-v1`。旧 proof、对局和审计均保持原件。

规则来源为仓库采用的用户确认资料，不是官方统一规则。以下清单是本轮实施依据，
最终实现、测试与缺口以同目录 `POST_C8_PLAYABLE_REPORT.md` 为准。

2026-09-08信息增量已实施：A/B独立接线，最终短测105项通过（87.61秒，PID59400，exit0，前后源码一致）。原64项只属于此前快照。第一轮长测已FAIL；2026-09-09完成五类故障修复、原94项受影响测试、当前121项短验收，第二轮长测与最终独立审查待执行。准确文件与哈希见报告和更新后的handoff。

| 功能／规则 | 来源 | 当前实现分类 | 当前测试 | 缺口 | 本轮处理 |
|---|---|---|---|---|---|
| 生产动作与完整牌堆 | 基础术语、卡牌效果、牌堆及结构化 CSV；production_batch / production_cards | 已实现可复用 | production_*、actions 测试 | 缺正常人工会话 | 保留 enumerate → signed action → validate → apply，接统一运行层 |
| 2v2：1+4／2+3、3/4/4/5、飞扬、死亡奖励、耗尽平局 | 模式 §2 | 已实现但入口绑定 no-skill profile | post_b_c3_* | 武将和控制器未接线 | 共用模式 policy，加载完整生产武将，队友可见实际手牌 |
| 斗地主叫价、物理环旋转、地主加成 | 模式 §3.1–3.4、sgs_modes | 规则函数存在；正式 session 固定地主 | sgs_modes、post_b_c4_* | 交互叫价与武将模式初始体力 | 签名开局决策；保留物理座位；加成在初始化发生 |
| 斗地主飞扬跋扈、死亡奖励、耗尽平局 | 模式 §3 | 已实现可复用 | post_b_c4_* | 与新开局接线 | 共用 DoudizhuModePolicy / OutcomePolicy |
| 普通八人身份：1主2忠4反1内、隐藏身份、主公加成 | 模式 §4、增量汇总 | 已实现但未接可玩运行层 | post_b_c6_* | 固定／随机身份、选将及 AI 信息边界 | 使用普通身份 policy，显式区分固定配置和交互开局 |
| 五人身份、duel、立储择途八人变体 | 各 mode factory；模式 §4/§5 | 已实现可复用 | formal_duel、post_b_c5_*、post_b_c7_* | 统一调用、变体私有事件 | 尽量共用 driver，逐项短测；不借模式名称宣称验收 |
| 武将候选、手气卡 | 模式 §2.8/§3.5/§4.5/§6；增量普通八人8次 | 规则／独立函数有；production 无交互开局 | sgs_modes 等函数测试 | 前后手牌真实回库、候选隔离 | 用户启用池、固定／候选模式；等概率候选标模拟假设；8次上限；自用候选设置不冒充账号／官方池 |
| 沙摩柯、诸葛瞻、王元姬全技能 | 武将补充 §2/§3/§7；generals / skill_impl_v1 | 完整 production，Bridge 限固定单挑验收 | authoritative_general_*、Bridge 三将测试 | 多模式接线、技能决策内容 | 加载完整技能 registry；公开／本人私有选择分别投影 |
| 其余文本武将与单独 proof 技能 | 武将补充其余章节；skill_impl_v1 | 只有文档／策略函数／技能验收切片 | 各规则函数或 proof 测试 | 没有完整 production GeneralDefinition | 明确拒绝，不移除技能变士兵，不扩展整个武将库 |
| reference / Bridge controller | BatchReferenceController、Bridge acceptance controller | 验收专用 | controller tests | 不能作为游戏 AI | 兼容测试用途，新 ProductionAIController 独立评分 |
| V2.2 card/team/focus/chain/general | 模拟规范 §5.12–5.20，现有策略模块 | 只有策略函数，尚未驱动生产候选 | 对应 strategy tests | 输入语义、可见性、场景适配 | 逐项核实并接线；参数是分析约定；所有规则合法候选保留 |
| V2.4专项策略 | 模拟规范 §5.21；v24 `V2.4-pending` | 待定／实验函数，相关完整武将未生产化 | v24 tests | 无完整生产技能 | 不升级 pending，不假称采用未运行策略 |
| 多步选择、幂等、轮询时间片 | 现有 select/unselect/submit 与 current_actor | 引擎已实现，服务层缺失 | 生产弃牌、武器选择测试 | revision 不足以标识决策 | 每次接受后递增决策号；会话／座位／签名／请求幂等；步数及协作式时间片 |
| 玩家视图与事件 | 模式信息规则、现有 replay 脱敏 | 部分回放投影可复用；无 live facade | mode visibility tests | 实体ID、候选、历史与日志泄漏 | 白名单投影；内部实体ID转不透明引用；AI不接触 seed、完整状态或密钥 |
| 无懈公开资格 A | 用户2026-09-08最终澄清；AI信息规则；NullificationKnowledgeState | 旧策略类可复用，旧runtime未接线 | 旧team函数测试；新增真实窗口测试 | 不得预读/依PASS推导，须对全场一致 | 已接正式trick_response/judgment_wuxie；反无懈重观、局部失效、PASS不消费或伪造；AI实际评分使用 |
| 农民公开场景问答 B | 同次用户澄清；AI信息规则 | 旧自动私密桃/杀信号定义过宽，已替换 | 新information/runtime/CLI场景和spawn测试 | 上下文、可选回答、三方公开、禁止自动资源共享 | 已接无懈保护、救援/桃、已成共同知识的借刀、罪论意愿；签名及幂等；未回答UNKNOWN |
| 鲍信分发命题 | 武将补充§30、用户澄清 | 只有规则与策略；未完整生产 | 明确分发命题YES/NO及阻止循环探测 | 无完整武将，不扩张整将 | 仅通用规则场景，不提供runtime整将入口；旧数量对象仅历史分析兼容 |
| 多核 production 自对弈与统计 | 模拟规范、模式胜负统计 | 真正缺失；历史近似 worker 禁用 | 尚无 | Windows spawn、worker无关随机性、失败分母 | 同一 AI、稳定 game_id、真实终局、异常／上限单列；1/N逐局比较 |
| 长测及最终独立审查 | 本轮授权 | 第一轮外部长测已FAIL并完整归档 | 原94项受影响测试已PASS；当前短测121项PASS | 新源码完整矩阵和最终审查 | 第二轮保留相同12组4-seed；最终Grok使用最终字节与真实结果 |
| 真实长局continuation/多步选择/C7接线 | 第一轮真实seed与production语义 | 五类缺陷已修复；没有重写信息模型 | 原9失败seed分别复现并自然终局或越过故障点；25项单元/负例 | 6局有界停止不等于终局验收 | 第二轮继续原seed完整验证；保留fail-closed |
| frozen/current身份边界 | 固定C8 commit与当前真实依赖 | 独立开发pin；原冻结测试使用校验后的原源码子进程 | 88项冻结原测试+6项当前断言；旧verifier拒绝开发源negative | 不沿用旧审计授权新范围 | 保留旧pin/verifier/proof，显式记录执行来源 |

增量核对：普通八人身份组成、主公加成、8次手气卡、许攸3/3及新增武将正文已进入
模式／模拟规范／武将补充；这不代表全部技能已有 production 实现。V2.4 模块仍明确
pending，神吕布原型属于实验。现有历史来源审计包含“尚无引擎”等当时结论，不能
覆盖后来 production 实现。没有将历史、待核验、分析约定升级为当前确认。

工程选择：本轮新入口使用独立开发身份，普通玩法不生成 C8 proof。保留所有旧门禁，
新入口从相同生产核心及模式 policy 组装，不能给旧 formal/Bridge/C8 profile 授予新范围。

实施已落到 `playable_config/game/view/runtime/communication/simulator`、`production_ai`、
`scripts.sgs_playable` CLI及四份样例；多模式短推进、真实人工菜单、生产技能、Windows spawn
与异常分母均有本轮测试。Grok长测前审查及修复记录见 `POST_C8_GROK_REVIEW.md`。
第一轮full pytest和完整矩阵已执行并FAIL；修复后第二轮full pytest、相同完整矩阵及最终字节独立审查仍留到外部执行；
未纳入本轮的是其余完整武将、官方池、复杂AI搜索及产品界面。最终状态见报告，清单不作为额外审批点。


2026-09-09最终核验：第二轮full pytest 4639 passed/224 skipped，12组原矩阵及48个逐局对照全部通过，源码/测试无漂移；原9失败seed均自然终局。此前“待第二轮”的行是实施历史，当前状态以报告最后一节及最终验收为准。当前完整武将仍限三名，不将旧规则文字升级为已实现武将。
