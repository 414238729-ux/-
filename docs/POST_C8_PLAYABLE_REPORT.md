# POST_C8 可玩运行层、启发式 AI 与并行模拟 V1

当前阶段：第二轮长测通过后的最终独立审查与冻结。
第一轮外部长测FAIL历史保留；第二轮已fresh核验PASSED，源码及测试无漂移。最终独立审查、commit/tag及远程核验的实际结果统一记录在 [最终验收](POST_C8_FINAL_ACCEPTANCE.md)。
当前状态：`ROUND1_FAILURES_REMEDIATED=YES`、`EXACT_FAILED_SEEDS_TARGETED=PASSED`、`AFFECTED_PYTEST_SET=PASSED`、`SHORT_TESTS=PASSED`、`LONG_TESTS=PASSED`。
这里的支持表示新入口已经实现相应调用链，不表示整个模式矩阵已经验收。

## 版本与边界

- 冻结基线：`9991abc8091943e7316875734bae2e5967cc6e64`。
- 原 tag：`c8-timed-8p-deterministic-virtual-time-v1-audited`，未移动。
- 开发分支：`codex/post-c8-playable-runtime-ai-parallel-v1`，未提交、打最终 audited tag 或推送。
- 新生产入口身份：`post_c8_playable_production_v1`；AI：`production-heuristic-v1.1`；信息策略：`public-timer-and-context-qa-v1`。
- 每份模拟输出绑定实际 `scripts` 与 `knowledge` 文件 SHA256 清单，包含动态依赖与 CSV；每个 worker 独立核对。同一运行期间源码变化会拒绝发布同一实现结果。
- 信息修正前源码包为`1ce82da683b4b0ef377abaf6f3a5b1b06aba3d2a6148b9800791a881018af918`；旧64项短测只属于该快照。原105项属于随后信息修正快照；当前源码与测试绑定见下方本轮修复记录。
- 旧 C8 proof、历史 pin、自然对局、旧审计未改写；它们的结论仅属于旧冻结版本与原范围。本轮没有重跑四颗已封存的 natural/inner/timed 验收。
- 已有生产文件增量：`production_batch.py`保留开局体力加成参数；`production_cards.py`将实体无懈资格提为生产枚举与可信公开观察共用的方法；`sgs_team_strategy.py`复用三态知识并处理公开获得。旧factory、pin和身份门禁未删除或篡改，新依赖产生真实开发身份。

实施依据见 [GAP_MATRIX](POST_C8_PLAYABLE_GAP_MATRIX.md)。规则依仓库资料的状态使用；用户整理、分析约定和模拟假设不表述为官方原文。

## 模式、开局与武将

| 模式值 | 已接线流程 | 本轮证据与限制 |
|---|---|---|
| `2v2` | 固定物理 1+4／2+3 队伍，3/4/4/5 初手，先手、4号位首轮飞扬、队友手牌共享、死亡奖励、生产胜负和牌堆耗尽平局 | 第一轮 fixed 4 seeds自然终局；candidates seed1 寒冰故障已修复且原seed自然平局。当前单／双worker短测通过；第二轮完整矩阵已通过。通常禁手气卡 |
| `doudizhu` | 首叫者随机；首次1倍、后续不叫或更高叫价、3倍截止；物理环旋转地主先手；地主体力及上限+1、飞扬跋扈；农民死亡可选奖励、耗尽平局 | 第一轮 fixed/candidates 均PASS且真实发生公开问答；本轮保留并通过信息/通信回归。第二轮新源码完整矩阵已通过 |
| `identity8` | 1主2忠4反1内；随机或显式固定身份；主公先选及先手，主公体力及上限+1，普通身份隐藏与死亡揭示、救援及胜负、8次手气卡 | 第一轮 fixed/candidates 8局均自然获胜终局；第二轮新源码完整矩阵及统计对照已通过 |
| `identity5` | 1主1忠2反1内；共用普通身份生产 policy、主公加成、身份隐藏、补牌和胜负 | 第一轮 fixed PASS；candidates seed1 响应 continuation 已修复并越过原故障点。采用仓库五人 profile，不擅加8次手气卡 |
| `identity8_heir` | 八人立储／择途已有 C7 policy；私有立储、内奸择途、继位选牌与野心家路径路由 | 第一轮暴露罪论时机、救援 continuation 和择途方法接线故障；原6个失败seed均已定向验证，第二轮完整矩阵已通过。统计不套用普通八人奖励 |
| `duel` | 仓库现有双人单将对决模型，随机先手，基础初手4张，回合、响应、死亡及 DuelOutcomePolicy | 第一轮 fixed PASS；candidates seed1 虚拟杀材料归属已修复且原seed自然获胜终局。不宣称客户端全部单挑赛制 |

全部模式支持 `ALL_HUMAN`、`HUMAN_VS_AI`（任意非空且非全部人工席位）、`AI_VS_AI`。座位参数始终是固定物理座位；视图另给当前座次。

完整生产武将只开放：

| 配置键 | 基础体力／上限 | 已接技能 |
|---|---|---|
| `shamoke` | 4/4 | 蒺藜 |
| `zhugezhan` | 3/3 | 罪论、父荫 |
| `wangyuanji` | 3/3 | 谦冲、尚俭；谦冲动态授予的明哲／帷幕 |

`soldier` 仅是显式无技能测试角色；不在默认启用池。未完整实现的武将配置会报错，绝不静默变成士兵。

武将补充文档中以下角色尚无完整 production GeneralDefinition，本入口拒绝作为完整武将出场：界钟会、旧版曹纯、新版曹纯、曹婴、张琪瑛、星·甘宁、许攸、清河公主、傅佥、谋·公孙瓒、徐荣、王经、文鸯魏／吴、曹叡、谋袁绍、界曹丕、刘禅、界董卓、谋张角、孙亮、界孙休、谋孙策、界孙策、谋孙权、界孙权、鲍信、谋皇甫嵩、势·孙綝、势·辛宪英、SP郭女王。神吕布重制原型仍是未上线实验规则。单独 proof 技能、策略函数或文字条目不代表完整武将已支持。

`enabled_generals`、`fixed_generals`、`selection=fixed/candidates` 与 `candidate_count` 是自用配置。固定空阵容按启用池轮转填座；候选是每座启用池的等概率无放回子集，允许不同座位重名。这不是项目13人分析池、官方账号将池、主公资格池或权重抽样；本轮仅三名完整武将，八人样例明确使用重复阵容。没有账号拥有权、商城、月度将池或匹配功能。

`landlord_seat=null` 进入交互叫价；填写1..3代表显式固定地主模拟。`identities` 按物理座位填写，留空随机。手气卡每座最多8次，真实整手回库、洗牌再摸等量牌，保留其他座位已发牌；它属于开局，不触发游戏中的失牌技能。

## 可直接运行

在仓库根目录 PowerShell 设置一次环境：

```powershell
Set-Location -LiteralPath 'D:\MyGPT\game-analysis-grok-eval-c3'
$py = 'D:\MyGPT\game-analysis-grok-eval\.venv\Scripts\python.exe'
$env:PYTHONHASHSEED = '0'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
```

实测解释器 Python 3.12.14；生产代码仅依赖标准库，测试使用现有 pytest。

```powershell
# 全手控：同一操作者轮流处理实际行动座位，包括响应和技能选择。
& $py -B -m scripts.sgs_playable play --config examples/post_c8/all_human.json

# 人对AI：斗地主交互叫价、候选选将及手气卡。
& $py -B -m scripts.sgs_playable play --config examples/post_c8/human_vs_ai.json

# 2v2两名人工，按物理座位1和4接管。
& $py -B -m scripts.sgs_playable play --mode 2v2 --control HUMAN_VS_AI --human-seats '1,4'

# 普通八人全AI：明确固定身份、固定重复阵容样例。
& $py -B -m scripts.sgs_playable play --config examples/post_c8/ai_vs_ai.json --output run_identity8_001.json

# 其他已接模式的人工入口。
& $py -B -m scripts.sgs_playable play --mode identity8 --control ALL_HUMAN
& $py -B -m scripts.sgs_playable play --mode identity5 --control HUMAN_VS_AI --human-seats 1
& $py -B -m scripts.sgs_playable play --mode identity8_heir --control ALL_HUMAN
& $py -B -m scripts.sgs_playable play --mode duel --control HUMAN_VS_AI --human-seats 1

# 20局样例及1/4 worker对照可能属于长测试；实施期间未启动。
& $py -B -m scripts.sgs_playable simulate --config examples/post_c8/parallel_simulation.json --output run_parallel_001.json
& $py -B -m scripts.sgs_playable compare-workers --config examples/post_c8/parallel_simulation.json --output run_compare_001.json
```

交互输入编号提交，`v`重看，`q`主动结束记为 `ABORTED/USER_STOP`。农民在明确场景可输入`a 编号`公开询问；回答座位选择1/2/3对应YES/NO/不回答。全部人类和AI都能看到同一个问题与答案。全AI运行仍使用有限时间片，CLI反复调用直到终局。JSON报告拒绝覆盖已有路径；正常胜负／规则平局退出0，中止、异常或比较不一致退出非0。

## API、信息与策略

`scripts.sgs_engine.playable_runtime` 提供 `create_game`、`get_player_view`、`submit_action`、`advance_until_human_or_terminal`、`get_events`、`get_result`、`close_game`，也可创建独立 `GameService`。另提供`ask_question`、`answer_question`，实例还提供`abort_game`、`get_ai_trace`与显式全手控全知观察。旧`submit_signal`明确拒绝自动桃/杀共享。

所有游戏动作来自生产 `legal_actions`；运行层外层HMAC绑定会话、决策代次、行动者、候选枚举序和引擎签名，提交时引擎重新验证。每次接受提交都推进决策号，因此不改变基础 revision 的选择也会使旧决策失效。相同请求返回原回执，锁保护并发重复提交；投影失败后保存已提交回执并停止对局。参考／Bridge验收控制器仍可在原引擎入口使用，不冒充游戏AI。

自动推进按 `current_actor_id` 路由，响应、救援、选牌和技能分支同样适用；到下一人工座位即停止。默认最多32个调度步骤（游戏提交、询问或回答各计一步）或约50毫秒的协作式时间片，在一次完整规则动作之间让出控制；单个原子动作不可中途抢占，未宣称硬实时上界。每局另有工程动作上限，超限单列中止。

AI只得到本座位白名单视图及发生时已过滤的事件历史。2v2队友完整手牌可见，斗地主不共享手牌。两套信息机制独立，当前规则见[三国杀AI信息规则](../knowledge/三国杀AI信息规则.md)：

- A：生产step提交成功后，真实`trick_response`/`judgment_wuxie`挂起时，可信运行层按生产无懈资格生成逐人公共摘要，复用`NullificationKnowledgeState`。首次有效窗口前UNKNOWN；有资格/无资格来自窗口最终可公开判断结果，不根据PASS推导。放弃响应不耗牌、不清掉KNOWN_USABLE，普通PASS也不伪造曾有资格。使用一张不推断用尽，反无懈层重新观察。未知取得/失去手牌只让受影响角色失效，轮询/AI评分不刷新；公开取牌只按已公开事实推理。普通玩家、AI、地主、农民收到相同摘要，不含精确无懈数量或其他私牌。
- B：由当前生产候选和合法公开记忆生成具体问题，另一农民实际回答YES/NO/NO_RESPONSE，问题与答案全场相同。南蛮/万箭无懈保护、救援意愿/明确桃事实、已成共同知识的借刀事实/能力/意愿、罪论目标意愿已接线。保护YES/NO不是确定杀/闪事实；未回答是UNKNOWN。借刀第二目标不覆盖无懈效果目标。鲍信只支持公开分发命题的规则场景，未开放整将生产。
- 问答绑定当前游戏决策、目标、方案、无懈窗口及层次；改变后过期。每个决策最多一问；事实/能力/数量命题在同一回答者手牌时期禁止重复探测，是本AI建模约束。模板不能追加任意数字/牌名/隐藏计划，旧资源对象只作历史分析兼容。
- 问答经独立签名适配器验证，不执行生产step、不移动牌、不刷新窗口或deadline。`advance_until_human_or_terminal`在真人回答处返回`HUMAN_ANSWER`；回答者为AI时仅收到其自身视图。问答步骤也受时间片/步数边界控制；`advanced`只计游戏动作，`communication_steps`另计。沟通策略确定性调度，不使用游戏随机流。

最小调用方式（字段均从当前视图取得）：

```python
view = service.get_player_view(session_id, asker_seat)
menu = view["communication"]  # kind=ask；options可为空，此时没有允许的场景
question = service.ask_question(session_id, asker_seat, menu["decision_id"],
                                menu["options"][0]["action_id"], request_id="ask-1")
reply_view = service.get_player_view(session_id, respondent_seat)
answer = next(o for o in reply_view["communication"]["options"] if o["answer"] == "NO_RESPONSE")
service.answer_question(session_id, respondent_seat, question["question_id"],
                        answer["action_id"], request_id="answer-1")
# 再由原行动者选择正式游戏动作；回答本身不会消费无懈或发动技能。
```

正常视图不包含敌方手牌、隐藏身份、牌堆顺序、原始牌实例ID、引擎状态摘要、seed、内部元数据或密钥；牌引用采用每会话每观察者不透明引用。罪论的牌顶观察只发技能拥有者，不能因2v2共享手牌而共享尚在牌顶的私有观察。立储记忆只给原主公，择途记忆只给选择者；隐秘模式窗口对其他人不展示私有行动者。评分日志仅按本座位取回；不能把其他座位日志用作AI输入。

`omniscient_debug=true`仅允许全手控，独立合并各座位视角；不回传AI，也不提供未来牌序。这里是可信本机进程内服务，没有额外建设账号／座位登录系统，也不宣称能隔离恶意Python代码。

AI对全部合法候选评分，规则层不删除不推荐动作。采用的既有策略包括：

- V2.2 `DynamicCardValue`、`choose_v22_action`、沙摩柯换武器评估。
- card：五谷取牌、拆顺目标、防御牌耗用、群体牌、借刀响应。
- team：最低合法已知资源救援、无懈价值与保留；实际传入公开读条的敌方已知可用者及己方反无懈信息。
- public context：保护建议、救援意愿、明确桃事实、借刀事实/能力/意愿分别解释、罪论目标意愿；不把问答变成共享手牌表。
- general／focus：公开体力、手牌数量、威胁、击杀收益和集火目标；chain：属性传导的敌我净收益。
- 新接线评分：出牌顺序、敌我及公开行为推断身份、承伤／响应、酒桃、装备、判定牌、弃牌、多步代价、技能发动与目标／牌／分支、结束阶段、叫价／候选／手气卡与模式选择。

底层类型为PASS的贯石斧／寒冰剑发动按实际operation评分。已知闪电等动作允许保守通用权重，全部候选保留。未知operation、schema或技能分支抛可定位错误，不吞异常选第一项。V2.4仍pending且所涉完整武将未进入本轮生产池，未接入或宣称覆盖。

游戏随机流、开局随机流和每座AI随机流独立；游戏seed不混入AIseed，AI不接收模拟seed，每局重新初始化配置指定的策略随机流。同分只用权威枚举序和自己的策略随机流，绝不按会话签名排序。可配置 `aggression`、`preservation` 和 `tie_randomness`；后者0固定枚举首项、正值用种子随机同分选择。评分及身份判断均是策略假设，未训练或宣称最强。日志追踪AI版本、参数、所有候选分数及依据、实际调用的策略和选用操作次数。

尚存AI质量限制：身份判断只用公开敌对行为的启发式，复杂卖血／多人协商／罪论留顶规划未做搜索；候选武将权重为普通生存与技能收益偏好，部分模式动作使用通用分数。测试证明会因局势改变选择，不以小样本胜过参考控制器作为强度结论。

## 模拟与统计

`SimulationConfig`外层提供`games`、`seeds`、`workers`，内层`game`复用完全相同配置和AI。每个任务独立初始化注册表、生产会话和AI；Windows使用spawn。game_id由实际单局配置、游戏seed和重复seed序号构成，与worker编号、总worker数、完成顺序无关。结果按请求索引归位。语义比较排除PID／耗时／会话随机签名，保留逐局动作摘要、终局状态、参与者、实际策略、公共信息事件摘要和统计。`public_information_sha256`覆盖实际公共观察、知识失效、问答及过期事件，`public_information_counts`按事件类型统计，连同信息策略版本一起参与1/N逐局比较。为避免大日志，批量结果保存摘要及计数，运行层按座位事件API仍可取历史。动作摘要包含每次实际选中的operation、枚举序、目标、可见牌面、代价与分支，剔除会话牌引用和签名。

报告列请求数、自然完成数、获胜终局数、规则平局、异常和中止；异常带类型、阶段、决策代次及调用栈，worker启动失败也覆盖对应每个game_id。分武将／当前座次／物理座位／当前身份／原始身份／队伍／武将×原始身份记录出场与胜负。未成功初始化的异常无虚构参战阵容。

胜率分母是自然完成出场（包含规则平局），排除ERROR和ABORTED。队伍每局只计一次，队员的个人获胜出场独立统计；农民两人获胜不把团队获胜计成两局。斗地主保留L、F与`S_raw=(L+F)/2`，某角色没有自然完成样本则对应值为空；没有技能适用修正证据，不自行调高`S_selectable`。

普通八人额外记录内奸实际原始胜率、进入主内单挑概率、服务器奖励：实际获胜3分，否则曾进入主内单挑1分，其余0分，互斥计分。此得分不是胜率，不加载到八人限时变体。

全部结果仅表示**该规则、对手分布与AI策略下的模拟胜率**，不代表武将绝对强度或真人胜率。不逐局生成C8 proof、不逐步落大快照、不在线调用大模型思考，也不使用旧近似Monte Carlo战力替代生产执行。

## 第一轮长测修复与实际证据

第一轮原件位于 `D:\t\pc8-long-20260908-info01`。54个文件已逐字节归档到 [original_long](post_c8_evidence/round1_remediation_01/original_long)，SHA清单见 [ORIGINAL_SHA256.json](post_c8_evidence/round1_remediation_01/ORIGINAL_SHA256.json)。修复前源码/测试与该轮 before/after 完全一致；修复结束再次核对54份原件和归档，均未变化。原handoff SHA256：`9cc45b9b56b7cd405d40199ea00f5b592edb4d976e0dc6d55ec8c73189f85cdf`，旧报告/handoff原字节保存在 `round1_remediation_01/prior`。

原full pytest为4847项：4529 passed / 25 failed / 69 errors / 224 skipped，PID53644，exit1，7100.2746秒。分类见 [FULL_PYTEST_FAILURE_CLASSIFICATION](FULL_PYTEST_FAILURE_CLASSIFICATION.md)，其中69 ERROR来自3个初始化根因，不能当成69个独立玩法错误。本轮没有重跑full pytest或12组长矩阵。

第一轮12组已生成的1/4worker对照全部 `semantic_equal=True`。其中39对自然完成结果的公共信息SHA均相同；9对ERROR结果未记录该字段，不能把缺字段填成hash。斗地主fixed与candidates均实际PASS，其8对结果的公共信息hash一致，真实问答计数如下：

| 第一轮配置／seed | question / answer / expired |
|---|---:|
| doudizhu_fixed / 1 | 5 / 5 / 5 |
| doudizhu_fixed / 3 | 2 / 2 / 2 |
| doudizhu_candidates / 1 | 2 / 2 / 2 |
| doudizhu_candidates / 2 | 2 / 2 / 2 |

公开无懈观察、PASS和实际使用也已在真实长局出现。上述成功观察保留，表明AI问答确实执行；它们属于第一轮旧快照，不能替代修复后第二轮验收。本轮未重写信息模型或AI权重。

### 五类生产根因与最小修复

| 类别 | 查明的根因 | 实际修复与边界 |
|---|---|---|
| A：duel候选 | p2沙摩柯丈八虚拟杀在蒺藜checkpoint暂停；139/065材料已合法进入PROCESSING，pending_slash尚未建立，continuation未登记材料根。修好后另暴露虚拟触发牌的技能候选缺少VirtualCardReference | continuation签名身份及invariant登记真实材料；ACTIVATE/PASS引用同一已验证虚拟牌。技能动作投影不把已支付材料再当成本；材料移走或额外无主PROCESSING仍拒绝，不复制实体、不绕过守恒 |
| B：2v2候选 | p3寒冰第一次弃p1红色方天后，第二次选择先生成；p1明哲摸牌使选择快照过期 | 仅在正式技能完成/放弃后重新签发该寒冰步骤；若目标可弃区确已空则调用原正式关闭语义。旧签名仍拒绝，不把全局EMPTY_LEGAL_SET改成PASS |
| C：五人候选／立储候选 | p5沙摩柯闪、p2王元姬自救桃分别在已消耗入弃牌堆后，蒺藜／明哲摸牌使空牌堆重洗，旧DISCARD位置前提过严 | 两局分别精确复现。仅接受continuation建立后权威移动账本证明的discard→reshuffle→draw、可选技能draw→hand链；保持phase/revision/actor/target/dying/duplicate和未结算材料检查，不凭最终位置放行 |
| D：立储固定4 seeds | END中的罪论技能窗口仍挂起时，C7额外模式选择抢占phase为mode_decision；legal候选仍是罪论而apply检查END | C7模式窗口等技能、卡牌continuation、私有选牌与技能扣血窗口结束后再开启，保留原决策owner与阶段。AI评分未回避罪论 |
| E：立储候选seed3 | mode policy引用Formal façade旧方法名，而Playable session仅继承对应C7 core方法 | 核对参数、效果及调用边界后，policy统一调用四个现存`_c7_*` core hooks；无新增alias。对忠臣/野心家转换各加直接生产回归 |

全部失败局只使用已公开支持的沙摩柯、诸葛瞻、王元姬；没有不支持武将混入，也未扩大候选池或降级为士兵。实际物理座位与武将、初始身份和运行座次完整保存在 [逐局修复映射](post_c8_evidence/round1_remediation_01/REMEDIATION_RESULTS.json) 的 `exact_failures[].participants`。候选路径出现这些组合不代表缺陷只可能发生在候选开局。

| 原失败局 | 物理座位武将与相关路径 | 原决策 → 修复后实际结果 |
|---|---|---|
| `2v2_candidates_seed1` | p1..p4均王元姬；p3寒冰→p1明哲 | 366 → 451，DRAW |
| `duel_candidates_seed1` | p1/p2均沙摩柯；p2丈八虚拟杀→蒺藜 | 736 → 785，WIN |
| `identity8_heir_candidates_seed2` | p1..p8均王元姬；p2自救桃→明哲 | 1196 → 1324，ABORTED |
| `identity5_candidates_seed1` | p1..p5均沙摩柯；p5闪→蒺藜 | 1499 → 1627，ABORTED |
| `identity8_heir_fixed_seed0` | 固定三将循环；p8诸葛瞻罪论 | 89 → 217，ABORTED |
| `identity8_heir_fixed_seed1` | 固定三将循环；p8诸葛瞻罪论 | 96 → 224，ABORTED |
| `identity8_heir_fixed_seed2` | 固定三将循环；p2诸葛瞻罪论 | 60 → 188，ABORTED |
| `identity8_heir_fixed_seed3` | 固定三将循环；p5诸葛瞻罪论 | 83 → 211，ABORTED |
| `identity8_heir_candidates_seed3` | p1..p8均王元姬；p2结束回合→p5内奸转换 | 912 → 1012，WIN |

固定三将循环为：p1/p4/p7沙摩柯，p2/p5/p8诸葛瞻，p3/p6王元姬。pN始终表示物理座位；身份模式会旋转实际先手座次，不能把它当作随机选将差异。

原9局在修改引擎前全部复现相同game_id、seed和原错误决策（`exact_before_02`，exit0仅表示复现成功，不表示游戏PASS）。修复后3局自然终局；其余6局按预先设定的“原故障点后128个已接受步骤”边界停止，真实状态为ABORTED。它们证明自然继续越过故障点，不充当自然平局、胜负统计或完整长局验收。原GameConfig及20000上限、seed、AI seed、game_id不变，边界由诊断驱动单独施加；全局最多2个spawn worker。诊断仅在可信测试侧保存，不传给AI。

`exact_after_01`原记录包含duel在737步的第二个故障及真实非0退出；补齐虚拟技能候选后，`exact_after_02`只重跑该局并在785步自然WIN。两个原始结果集均保留，由逐局映射指向各自真实通过证据；没有把`exact_after_01`整体改写成通过。

### 当前身份与测试边界

冻结C8身份：`df90380d241bc8342956db3d3d68405fbef60d86185dcb078c836e00544370fe`。当前POST-C8引擎身份：`5083c90d2f6c4913704edbb88161706cec35d136e8d08fe2637d0d832ce38d18`，由独立 `scripts/current_post_c8_implementation_pin.py`固定到实际依赖；当前完整开发源码包SHA256：`eede731b076384ab6fc50d83d1cbec3fd63766948c50747ec90ebd5d75420825`。后者包括scripts/knowledge，与引擎identity用途不同。

原88项冻结合约测试在固定commit源码副本、原测试字节和新子进程中真实执行，旧pin/证书/verifier不改；6项当前身份和资料断言在开发树执行。父pytest只转发实际报告，源核验缺失、子进程内部错误或不完整测试生命周期不能报通过。冻结source的Git blob与原raw-byte行尾包装分别校验，测试专用release不允许启动historical harness。新negative证明当前开发字节仍被旧frozen verifier拒绝。详细边界与每项映射见分类文件。

### 短测、回归与剩余验收

| 真实执行 | 结果 | PID / exit | 时间及证据 |
|---|---:|---|---|
| 新生产故障单元/集成 + 原9项continuation negatives | 25 passed | 63440 / 0 | 34.93秒；`unit_03` |
| 原25 FAIL + 69 ERROR exact affected set | 94 passed | 62992 / 0 | 命令耗时24.849秒；`affected_04`；冻结子进程PID63076、exit0 |
| 当前短验收 | 121 passed | 64176 / 0 | pytest125.84秒；`short_final_01` |
| 当前正式资料相关子树 | 18 passed | 63700 / 0 | 命令耗时1.022秒；`doc_regression_01` |

上述最后三组源码与测试清单相同，前后核验均无变化。当前完整快照为 [short_final_01/after.json](post_c8_evidence/round1_remediation_01/short_final_01/after.json)；每组真实命令、XML、日志、PID、退出码和时间均存原目录。25项的较早快照身份另存其before/after，不冒充最终快照。

121项包括模式初始化、人工/混合座位、current_actor、签名合法集、重复/过期、多步选择、技能与AI场景、卡牌守恒、寒冰步骤、响应/救援continuation、C7罪论/转换、公开无懈与农民问答、2v2共享、提交后异常和回执恢复，以及实际Windows单/双worker语义/公共事件/统计对照和worker失败。命名南蛮/万箭问答fixture与250步斗地主自然样本保持区分，不要求小自然样本必须触发问答。

历史105项（信息修正，PID59400，87.61秒）和64项（初始实现，PID51056，56.62秒）仍保留原目录，仅表示各自旧快照。第一轮FAIL及本轮诊断/fixture开发失败全部保留，没有重跑或覆盖C8封存natural/inner/timed/proof。未修改历史pin、未commit/tag/push。

上述修复轮未调用Grok，旧限定审查不覆盖修复字节。**第二轮full pytest及原12组4-seed矩阵现已PASSED**。最终current-bytes独立审查与冻结结果见最终验收记录。当前仍只支持上述三名完整武将，鲍信仅通用问答规则场景；复杂身份推断、合作博弈与AI质量不因本次修复自动获得验证。

第二轮命令、原9个失败seed的特别核对、第一轮核心配置保持、公共信息实际事件与统计口径见 [POST_C8_LONG_TEST_HANDOFF](POST_C8_LONG_TEST_HANDOFF.md)。当前交付清单见 [DELIVERY_MANIFEST](post_c8_evidence/round1_remediation_01/DELIVERY_MANIFEST.json)。该handoff及其SHA作为已执行的第二轮历史交接保留；现按用户授权继续最终独立审查及冻结，不重复长测。


## 第二轮fresh核验与最终边界

证据根目录：`D:\t\pc8-long-20260909-r2`。当前工作树scripts/knowledge/tests/examples逐文件SHA与正式before、after和最后短测一致。正式13个命令记录均exit0，没有测试中断或重跑；首次创建目录前的permission denial按用户确认属于未启动测试的前置失败，原历史保留。

Full pytest：4863 collected，4639 passed，224 skipped，0 failed/errors，日志耗时6577.51秒，PID60024，exit0。跳过项主要属于需要独立外部权威资料的历史测试，不被表述为通过。原94项失败/error nodeids本轮全部实际PASS。

12组原配置与第一轮逐值一致；48个single/4worker配对全部由当前比较函数fresh重算相等，public-information、semantic trace和final state hash均无mismatch。48局（每侧）全部自然WIN或DRAW，无ERROR/ABORTED。原9失败seed全部自然终局，不再只凭有界继续作证。斗地主fixed问答总计7/7/7、candidates4/4/4，均是真实question/answer/expired；旧自动teammate_slash_count未进入运行层。

完整逐局状态、实际阵容、统计与原始证据文件SHA索引见 [ROUND2_VERIFICATION](POST_C8_LONG_TEST_ROUND2_VERIFICATION.json)。该文件是读取原件计算出的摘要，不包含原始长日志。初始64项、信息105项、修复121项短测与两轮长测各自绑定不同快照，禁止混同。

最终声明仅适用上述六模式入口、三名完整生产武将、合法信息视图和本阶段AI/模拟器。AI V1为启发式策略，非最优AI；胜率是当前规则、配置、对手分布与AI策略下的模拟结果，非武将绝对强度或真人胜率。UI、LAN、独立launcher、语音动画及新武将开发不属于本阶段。C8旧commit/tag/proof及其原范围保持不变。
