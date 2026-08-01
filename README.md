# 游戏规则与数值分析资料库

这是一个用于配置私人自定义 GPT、保存游戏规则分析规范，并复用概率与数值计算代码的资料库。

它不是需要普通用户手动配置参数的 EXE，也不是独立网页应用。第一版不包含在线服务、外部 API 或自定义 Action 后端。

## 目录用途

```text
.
├── GPT_INSTRUCTIONS.md       # 可粘贴到私人 GPT 的完整 Instructions
├── knowledge/                # 上传到 GPT Knowledge 的规则规范与牌堆数据
├── scripts/                  # 可复用 Python 计算与轻量规则模块
├── tests/                    # pytest 自动化测试
├── AGENTS.md                 # 后续 Codex 维护规则
├── UPLOAD_GUIDE.md           # 复制、上传与本地保留清单
├── requirements-dev.txt      # 测试依赖
└── pytest.ini                # pytest 配置
```

### `GPT_INSTRUCTIONS.md`

定义“游戏规则与数值模拟器”的行为、证据标签、规则解析流程、精确计算与蒙特卡洛模拟标准，以及默认中文输出格式。

### `UPLOAD_GUIDE.md`

给出最终配置清单：哪个文件复制到 Instructions、哪些文件上传到 Knowledge，以及哪些开发文件只保留在本地。

### `knowledge/`

保存给 GPT 检索的参考资料：

- `三国杀模拟规范.md`
- `三国杀模式规则.md`
- `三国杀基础术语与通用机制.md`
- `三国杀卡牌效果.md`
- `三国杀武将规则补充.md`
- `三国杀增量规则整理_第二次汇总之后.md`
- `三国杀卡牌结构化数据.csv`
- `三国杀卡牌使用方式.csv`
- `三国杀牌堆数据.csv`
- `三角洲枪械分析规范.md`
- `Overlord_DND换算规范.md`
- `通用概率分析规范.md`

九份 Markdown 资料用于说明术语、字段、来源、分析流程、待补充项及本轮增量的证据追溯。三国杀资料按“模式规则、基础机制、完整卡牌效果、按需武将规则、增量来源追溯、一牌一种定义、多用途子表、实体牌实例”分层，避免把模式规则、武将原文、AI策略、使用上下文和花色点数混在同一文件。

`三国杀卡牌结构化数据.csv` 每种卡牌只记录一条核心效果；`三国杀卡牌使用方式.csv` 保存【桃】【酒】的多用途时机与独立额度，以及【闪】按响应对象区分“使用/打出”的事件映射；`三国杀牌堆数据.csv` 每行保存一张实体牌并通过 `card_key` 关联定义。当前160张牌堆初始来源为非官方网络UP主转录，后经用户对照实际卡牌逐张核验；这仍不是官方发布或官方逐牌认证牌表。

该牌堆默认包含 4 张 EX 扩展牌；其余牌的所属扩展包没有在来源中逐张细分。不得根据牌名自行补写扩展包来源。当前160张牌堆不包含宝物牌，这不是待补资料；未启用会生成或加入特殊牌的武将、补充包或模式时，不向基础牌堆添加相关内容。当前 `deck_id` 用于三国杀移动版常规军争身份模式、排位2v2、斗地主和“主公立储、内奸择途”八人军争特殊玩法；该玩法复用同一160张牌堆，不另建重复 CSV。切换到范围外特殊模式、模式专属牌堆、其他服务器或活动模式时必须另行核对。

### `scripts/`

保存纯标准库 Python 模块：

- 通用统计摘要与置信区间；
- 蒙特卡洛试验；
- 不放回抽牌；
- CSV 牌堆加载、完整性审计、按字段统计和至少一张目标牌的精确不放回概率；
- 三国杀2v2与斗地主的轻量规则模型，包括手牌可见性、地主游戏开始前的基础体力、现行8次手气卡、斗地主固定物理环与确定性座次映射、轮次与额外回合、2v2首轮“飞扬”、断线选将加载范围、实际距离与攻击范围、濒死救援和多人依次响应；
- 三国杀卡牌术语与结算的轻量规则模型，包括锦囊通用时机继承与响应例外、牌区措辞、距离1目标、默认伤害属性与来源、无懈可击、延时锦囊、火攻、藤甲、白银狮子、横置属性伤害传导和丈八蛇矛转化；
- 【铁索连环】理性组合的轻量评分模型，分别比较敌方横置、直接火攻、自我引火、友军引火及保留或重铸，并显式约束隐藏手牌与隐藏身份信息；
- 固定阵容按需武将画像、透明目标权重、集火锁定、2v2/斗地主团队救援、桃信号、无懈响应读条，以及五谷、借刀、拆顺、延时锦囊和多人牌的可解释策略；
- 卡牌定义、多用途与实体牌实例的分层导入及空字段三值处理；
- 三国杀扩展轻量规则模型，包括牌堆不足与弃牌重洗、同名延时锦囊限制、跳过判定阶段、任意人数存活角色环，以及军争身份的身份、座次、先查胜利后处理身份奖惩；
- 三国杀移动版八人军争“主公立储、内奸择途”特殊玩法轻量模型，以内部模式开关处理宣传与开放状态、秘密立储、继位、内奸择途、野心家身份与标记，不会自动加载到标准八人军争；
- 条件触发和重复触发；
- 伤害样本与精确伤害分布；
- 加权评分与排名。

通用统计模块不硬编码具体游戏数据；三国杀专用模块只把 Knowledge 中已确认、适合独立测试的规则边界做成轻量适配层。完整规则、版本与牌堆数据仍以 Knowledge 文件为准。

## 配置私人自定义 GPT

根据 OpenAI 的[创建和编辑 GPT 说明](https://help.openai.com/en/articles/8554397)，Instructions 用于定义 GPT 的行为，Knowledge 用于提供对话时参考的资料，代码解释器与数据分析能力用于运行计算。

建议配置步骤：

1. 在 ChatGPT 网页端打开 GPT 编辑器并创建私人 GPT；
2. 将名称设为“游戏规则与数值模拟器”；
3. 把 `GPT_INSTRUCTIONS.md` 的正文复制到 Instructions；
4. 按 `CUSTOM_GPT_UPLOAD_MANIFEST.md` 把 `knowledge/` 中九个 Markdown 文件及三份 CSV 上传到 Knowledge；
5. 启用“代码解释器与数据分析”能力；
6. 在预览中用一个可手算的概率案例和一个有歧义的技能案例测试；
7. 确认回答能分开显示原文、推断、计算假设、结果和误差后再保存。

Knowledge 是参考资料，不等同于自动安装的 Python 包。如果希望 GPT 直接复用本仓库代码，应在可运行 Python 的会话中提供对应脚本，并明确要求导入或执行；也可以让 GPT 按相同接口生成一次性分析代码。

产品界面、账户权限和可用能力可能变化，应以当前 GPT 编辑器和上述官方说明为准。

## Python 环境与测试

要求 Python 3.10 或更高版本。生产模块只使用标准库；pytest 与 pandas 仅作为开发测试依赖。

PowerShell 示例：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

可选编译检查：

```powershell
python -m compileall -q scripts tests
```

## 快速使用

### 通用蒙特卡洛

```python
from scripts import run_monte_carlo

summary = run_monte_carlo(
    lambda rng: rng.randint(1, 6),
    trials=100_000,
    seed=0,
)

print(summary.mean)
print(summary.quantiles)
print(summary.distribution)
```

### 不放回抽牌

```python
from scripts import simulate_draws

deck = ["成功", "成功", "失败", "失败"]
summary = simulate_draws(
    deck,
    draw_count=2,
    score=lambda hand: hand.count("成功"),
    trials=50_000,
    seed=0,
)
```

### 加载并审计三国杀牌堆 CSV

`scripts/deck_data.py` 负责读取结构化牌堆，不把具体游戏牌名或数量硬编码进通用算法。加载时可同时要求总数必须为 160：

```python
from pathlib import Path

from scripts.deck_data import (
    count_by_field,
    load_deck_csv,
    probability_at_least_one_by_field,
)

records, audit = load_deck_csv(
    Path("knowledge/三国杀牌堆数据.csv"),
    expected_total=160,
)

# 审计报告包含总数、必填字段、重复记录和冲突记录。
print(audit.total_quantity)
for issue in audit.issues:
    print(issue.severity, issue.code, issue.message)
if not audit.is_valid:
    raise RuntimeError("牌堆审计失败，停止统计与概率计算")

# 所有查询显式指定单一 deck_id，防止不同平台、模式或版本混算。
deck_id = records[0].deck_id
name_counts = count_by_field(
    records,
    deck_id=deck_id,
    field="card_name",
)

# 精确计算不放回抽取时至少出现一张用户指定牌的概率。
target_name = "由用户指定的牌名"
result = probability_at_least_one_by_field(
    records,
    deck_id=deck_id,
    field="card_name",
    value=target_name,
    draw_count=2,
)
print(result)
```

上述概率由有限总体的不放回组合公式精确计算，不是蒙特卡洛估计。若要按颜色、花色或类别查询，把 `field` 分别设为 `color`、`suit` 或 `card_type`，并使用 CSV 中实际存在的值。数据初始来源非官方、后经用户对照实卡核验；精确计算只表示“在这份 CSV 口径下精确”，不代表官方发布或官方逐牌认证。

### 三国杀模式轻量模型

`scripts/sgs_modes.py` 只实现本资料中适合独立测试的约束，不是完整游戏引擎。示例：

```python
from scripts import (
    TwoVsTwoTable,
    replace_general_candidate,
    resolve_landlord_bidding,
)

# 第一名叫1倍，第二名叫2倍，第三名不叫。
bidding = resolve_landlord_bidding((1, 2, None))

# 交换当前1、2号座位只改变行动顺序，不改变初始队友。
table = TwoVsTwoTable().swap_seats(1, 2)

# 等概率只是一项模拟假设；固定种子用于复现。
replacement = replace_general_candidate(
    unlocked_generals=["甲", "乙", "丙", "丁"],
    current_candidates=["甲", "乙", "丙"],
    slot_index=0,
    seed=0,
)
```

手气卡重抽函数要求调用方只传入仍在牌堆中的牌；其他玩家已经获得且未放回的牌不能放回重抽池。换将卡函数排除当前候选框仍显示的武将，但不会永久排除先前已经被换走、当前不再显示的武将。新增接口只把本次确认的手牌信息、地主双体力修正、座次递增顺序、2v2基础距离、标准回合默认值、濒死救援和逐座状态传递表达成可测试约束；具体技能仍由调用方提供，不构成完整游戏引擎。

### 三国杀卡牌结算轻量模型

`scripts/sgs_modes.py` 中的实际距离接口与攻击范围接口彼此独立，只对已经确认的2v2四座基础距离建模。`scripts/sgs_card_rules.py` 将本资料中已经“当前确认”、且适合独立验证的卡牌边界表达成轻量接口，可检查锦囊“具体特例优先、否则继承通用时机”、空特例不得解释成任意时机、“牌”与“区域内的牌”的可选牌区、顺手牵羊和兵粮寸断的实际距离目标、默认伤害属性与来源、逐目标无懈、三种延时锦囊、火攻、藤甲、白银狮子、横置属性伤害传导，以及丈八蛇矛转化。`scripts/sgs_jink_response.py` 按当前响应对象把实体或【八卦阵】虚拟【闪】严格分派为 `card_used` 或 `card_played`，不会同时生成两类事件。`scripts/sgs_chain_strategy.py` 只评价用户提供候选方案的团队净收益，不把AI策略改写为卡牌强制效果，也不会绕过隐藏信息限制。

横置传导模型要求调用方通过回调提供具体防具、武将技能、体力、濒死、死亡和胜负判断；每名角色的完整结算结束后才会继续下一名角色。它保留伤害来源，分开记录本轮传导基础伤害和单名角色实际伤害，并允许新属性伤害开启独立的嵌套传导。该模块不是完整游戏引擎，也不会用代码中不存在的技能数据补全规则。

`scripts/sgs_extended_rules.py` 进一步提供牌堆逐张取得与弃牌重洗、检索失败不重洗、延时锦囊同名共存检查、不同名延时锦囊后进先出结算、跳过判定阶段留存、存活角色环距离，以及五人和八人军争身份模式的轻量接口。身份死亡接口先检查胜利，只有游戏继续时才执行身份击杀奖惩。军争选将的常备主公奖池名单、具体武将池和未提供客户端细节仍由调用方提供，代码不会自行补全。

`scripts/sgs_incremental_mechanics.py` 分开记录逐点与逐事件伤害触发、铁索传导的原伤害来源和实体牌归属、武将牌旁实体特殊牌权限，以及“已使用／无懈抵消／真正无效／使用完成／效果完成”节点。`scripts/sgs_general_rules.py` 保存当前十四个按需武将或版本的基础记录与十三名普通候选池；`scripts/sgs_incremental_generals.py` 只实现许攸、清河公主、傅佥和谋·公孙瓒本轮确认的轻量边界，`scripts/sgs_special_general_rules.py` 则提供徐荣、王经、魏／吴文鸯、相关主公、鲍信与谋皇甫嵩的专项轻量结算器。两者都不是完整武将数据库，谋皇甫嵩也尚未加入普通候选池。`scripts/sgs_general_ai_v21.py` 保留既有专项计算工具；`scripts/sgs_ai_strategy_v22.py` 是当前策略层，负责完整合法候选、动态牌值与嘲讽、反制分支及可审计决策。`scripts/sgs_mode_evaluation.py` 分开统计内奸原始胜率、主内单挑概率与互斥奖励得分，并实现斗地主身份适性等计算口径。上述策略和权重均属于分析约定，不是技能或模式规则。

`scripts/sgs_limited_identity_variant.py` 只在显式采用内部标识 `mobile_8p_heir_and_spy_choice` 时加载移动版八人军争“主公立储、内奸择途”特殊玩法；该标识不是官方名称。模块分开记录宣传文字与正式名称、最后核验开放状态、开局身份与当前身份、当前主公与座次、真实状态与角色可见信息，并提供立储、储君死亡、继位、择途、转忠、野心家标记及胜利前身份奖惩门控的轻量接口。继位不会重编号；择途锁定后在下一次实际存活角色回合开始事件生效，不绑定预定玩家；【飞扬】与【跋扈】只在当前存活人数不少于3人时生效。该玩法已确认复用现有160张常规军争牌堆。

### 条件与重复触发

```python
from scripts import simulate_trigger_chain

summary = simulate_trigger_chain(
    initial_state_factory=lambda: 0,
    should_trigger=lambda state: state < 3,
    resolve_trigger=lambda state, rng: state + 1,
    score=lambda result: result.trigger_count,
    trials=1_000,
    max_triggers=10,
    seed=0,
)
```

### 精确伤害分布

```python
from scripts import analyze_exact_damage_distribution

summary = analyze_exact_damage_distribution({
    0: 0.25,
    2: 0.75,
})
```

### 加权排名

```python
from scripts import rank_items

results = rank_items(
    items={
        "方案甲": {"伤害": 10, "耗时": 3},
        "方案乙": {"伤害": 8, "耗时": 2},
    },
    weights={"伤害": 0.6, "耗时": 0.4},
    directions={"伤害": "higher", "耗时": "lower"},
)
```

排名只代表给定指标、方向和权重下的结果，不代表官方强度结论。

## 新增一种游戏

1. 在 `knowledge/` 新建 `<游戏名>分析规范.md`；
2. 复制现有规范的来源元数据、术语、数据格式、歧义和待补充结构；
3. 记录平台、版本、模式、来源位置和核验状态；
4. 只填入用户提供或已核验的数据；
5. 若需要专用计算，把游戏规则适配代码放在独立模块中，通过参数调用 `scripts` 的通用函数；
6. 为专用公式增加测试，并在 Knowledge 或 README 说明公式和假设。

不要把具体游戏的卡牌、武器或角色数据写进通用统计模块。

## 新增一个技能或规则

1. 保存技能原文和来源；
2. 分开记录触发事件、时点、条件、成本、目标、结算步骤、随机事件、重复与终止；
3. 把无法由原文确定的内容列为歧义或计算假设；
4. 先建立可手算的小案例；
5. 再决定使用公式、枚举、动态规划或蒙特卡洛；
6. 修改任何公式时同步更新测试和文档。

## ChatGPT 数据分析环境可直接完成的功能

启用代码解释器与数据分析后，可以在单次分析中：

- 运行不依赖网络的 Python 概率模拟；
- 读取用户上传的牌堆、伤害样本或评分表；
- 计算均值、中位数、标准差、分位数和概率分布；
- 对主要规则解释分别运行模型；
- 生成临时表格、图表和可下载结果；
- 使用固定种子复现实验。

这些功能依赖当前会话中实际可用的文件和运行环境，不提供跨会话数据库或持续在线服务。

## 什么功能需要未来的自定义 Action

若要让 GPT 自动获取实时版本数据、查询外部数据库、保存长期记录、调用团队内部服务或触发其他系统，需要：

1. 部署可通过网络访问的 API；
2. 定义稳定的请求和响应；
3. 提供 OpenAPI JSON 或 YAML Schema；
4. 选择无认证、API Key 或 OAuth 等认证方式；
5. 处理隐私、安全、版本、速率限制和运行监控；
6. 在 GPT 编辑器中配置并预览测试 Action。

OpenAI 的[GPT Actions 配置说明](https://help.openai.com/en/articles/9442513-configuring-actions-in-gpts)明确要求外部 API 信息和 OpenAPI Schema。第一版仓库没有这些服务，因此不能仅靠现有 Python 文件成为真正的在线 Action。

## 第一版限制

- 三国杀模式规则来自用户个人总结与游戏内观察，主要适用平台已确认为三国杀移动版；其他服务器或桌游版只在对应章节明确说明时适用；
- 基础机制与通常卡牌效果按本项目的三国杀移动版用户确认规则集使用，但不是官方统一规则原文；
- 结构化卡牌 CSV 只包含本次提供的38种卡牌；空字段表示资料未提供，但锦囊的空 `specific_timing` 必须由 `inherits_generic_timing` 明确继承，不能解释为任意时机；
- 目前只有一份用户提供的三国杀牌堆明细；其初始来源非官方，已由用户对照实卡逐张核验，但不是官方清单；
- 该牌堆默认含 4 张 EX 扩展牌且不含宝物牌；其余牌的扩展包来源没有逐张细分；
- `DeckAuditReport` 的总数与分组统计针对传入的整个记录集合；当前 CSV 只有一个 `deck_id`。未来处理多个牌堆时应分别加载，或只使用强制指定 `deck_id` 的查询接口，不能把全局汇总当成单一版本；
- 只提供标准军争身份、移动版八人军争特殊玩法、2v2、斗地主及通用结算边界的轻量规则模型，不是完整游戏引擎，也不覆盖未提供的边缘规则；
- 武将 Knowledge 当前按需维护原十三个武将/版本条目及本轮新增的十七个条目；普通随机候选池现为十三个实际名额（曹纯两个版本共用一个名额，鲍信已加入），谋皇甫嵩通过准入后才可能成为第十四名。主公池条目不自动混入普通池，全部资料仍不构成完整移动版武将数据库；
- 移动版八人军争特殊玩法没有已确认的独立正式名称，首次已知宣传或开启日期为2026-05-16；未提供具体版本号不阻止按当前规则集模拟，第一轮额外回合的轮次归属及立储窗口已经确认。官方下架日期和未来是否常驻仍未知；其牌堆已确认复用当前移动版常规军争的同一 `deck_id`，逐牌数据已由用户对照实卡核验；
- 客户端武将候选分布已确认为非等概率，但具体权重未知；无权重数据时的合法候选等概率仅是模拟假设，固定阵容不计算刷出概率；
- 蒙特卡洛只处理用户定义的单次试验函数；
- 连续型结果会按精确浮点值形成经验分布，可能产生很多分布项；
- 95% 区间描述抽样误差，不包含规则或数据误差；
- 没有稀有事件加速、并行模拟、持久缓存或可视化前端；
- 没有在线 API、认证、数据库或自定义 Action。
