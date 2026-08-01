# 三国杀正式引擎状态

> 更新日期：2026-08-01  
> 状态：已有权威核心 foundation，但没有完整正式对局引擎；当前还包括正式 Knowledge 与轻量、可测试的规则／技能／策略组件库。  
> 本文是运行能力状态页，不得用测试总数或文档完整度替换完整引擎验收。

## 1. 当前可执行结论

| 问题 | 结论 |
|---|---|
| 当前是否存在唯一权威 `GameState` 基础模型 | 是；已覆盖160张实体牌、玩家基础字段、唯一牌区与区域顺序，但未覆盖完整模式、轮次、阶段、技能和胜负 |
| 当前是否存在可执行的正式失败关闭入口 | 是；`python -m scripts.sgs_formal_runner status/run`，其中 `run` 当前必然拒绝且不写结果 |
| 当前是否存在完整对局入口 | 否 |
| 当前是否能用正式代码完整运行至少一局 | 否 |
| 当前是否存在网页人工对局 | 否 |
| 当前是否存在统一回放 | 部分；已有记录哈希链、JSON／JSONL 保存载入和完整性校验，没有规则重执行、动作控制器重放或 UI |
| 当前是否存在正式多进程胜率入口 | 否 |
| 外部 `sgs_sim_engine_worker.py` 是否是正式引擎 | 否；它位于 Downloads，未被仓库导入，是独立近似器 |
| 外部 `sgs_ai_audit_20260729.py` 是否调用真实 AI | 否；它使用本文件内微场景与自证式 `chosen = expected` |
| 当前组件测试是否通过 | 是；修改前基线为 `947 passed in 3.39s`，本轮最终完整测试为 `1094 passed`，失败0、跳过0 |

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

其中 `enumerate_legal_actions` 只有严格注册和校验基础设施，尚无完整模式的生产适配器；`ReplayRecord` 只验证记录完整性，不会重执行规则。`AuthoritativeCoreSession.run_game` 虽有方法占位，但必然抛出 `UnsupportedRuleError`，所以完整 `run_game / simulate_game` 仍属缺失。现有局部规则和技能状态尚未统一迁移，不能据此宣称完整引擎已经存在。

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

## 5. 当前运行范围

### 可以运行

- 组件级 pytest；
- 通用蒙特卡洛回调、抽牌、统计与排名；
- 明确输入下的局部三国杀规则／技能／策略函数；
- 牌堆 CSV 和结构化卡牌数据校验。
- `python -m scripts.sgs_formal_runner status --mode <模式>` 查看真实牌堆与门禁状态；这不是对局。
- 构造 foundation 会话、确定性洗牌、原子移动实体牌、登记事件并校验回放记录完整性；这仍不是对局。

### 不可作为正式能力运行

- 单挑、2v2、斗地主、五人身份、普通八人或限时八人的完整对局；
- 任意武将的端到端技能对局；
- 网页人工对局、PvE 或 AI 观战；
- 任一模式的完整生产合法动作枚举；
- 规则重执行回放、单步对局和回放 UI；foundation 的 JSON／JSONL 保存载入不等于这些能力；
- 正式多进程胜率。

## 6. 外部旧脚本隔离状态

外部文件均位于 `C:\Users\ASUS\Downloads`，不在正式项目目录中。正式源码全文未发现对下列入口的导入或调用：

- `sgs_sim_engine_worker.py`；
- `sgs_sim_aggregate.py`；
- `sgs_ai_audit_20260729.py`；
- `复现_三国杀16将三模式近似模拟.sh`。

因此这些脚本当前没有污染正式调用链。它们不应复制到 `scripts/`，也不应作为未来权威核心的基础。旧结果的详细失效状态见 `docs/LEGACY_RESULTS_INVALID.md`。

## 7. 测试状态

修改前实际执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 947 passed in 3.39s
```

解释：

- 通过数是现有组件测试数；
- 未发现完整 `GameState` 对局测试；
- 未运行网页测试、类型检查、lint 或 CI，不能宣称这些检查通过；
- 后续任何代码修改必须重新运行完整 pytest，必要时运行 compileall，并记录真实结果。

本任务新增的阶段2专项验证实际执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_sgs_engine_gate.py
# 19 passed
.\.venv\Scripts\python.exe -m pytest -q tests/test_sgs_formal_runner.py
# 9 passed
```

阶段 4 已新增 `tests/test_sgs_engine_model.py`、`test_sgs_engine_events.py`、`test_sgs_engine_actions.py`、`test_sgs_engine_rng_replay.py`、`test_sgs_engine_session.py` 和 `test_sgs_engine_package.py`。最终实际执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 1094 passed；失败0，跳过0
.\.venv\Scripts\python.exe -m compileall -q scripts tests
# 通过
.\.venv\Scripts\python.exe -m scripts.sgs_source_integrity_audit . --fail-on-defect --pretty
# 扫描99个Python文件，defect_count=0；43项均为显式门禁字段或测试证据等audit_item
```

当前开发依赖仅声明 pytest 与 pandas；未发现 mypy、ruff、前端 `package.json` 或 CI 配置。因此类型检查、lint、前端测试和 CI 是“未配置”，不是“已通过”。

## 8. 版本与检查点

当前目录不是 Git 工作树：

```text
git rev-parse --show-toplevel
git status
git log
→ fatal: not a git repository
```

因此：

- `git_commit` 当前不可提供；
- 不创建虚假 Git 提交；
- 当前检查点使用 `SOURCE_AND_CALLCHAIN_AUDIT.md` 中的外部文件哈希、状态文档和测试结果；
- 阶段4 foundation 记为 `CP-04-CORE-FOUNDATION`，证据为 `scripts/sgs_engine/`、对应专项测试、完整 pytest、compileall 与源码防伪扫描；
- 若未来初始化或恢复真实 Git 历史，应更新本页并将每个阶段映射到真实提交。

## 9. 下一可验收版本

下一版本最小目标不是网页或全武将，而是把当前 foundation 接成“无技能单挑权威内核”：

1. 权威状态与事件类型齐全；
2. 160 张实体牌进入完整生命周期；
3. 两名无技能角色可从开局运行到胜负；
4. 未实现卡牌明确失败关闭；
5. 同 seed 和动作序列可确定性复现；
6. 回放记录可校验；
7. 正式入口写入门禁和版本哈希；
8. 完整 pytest 通过。

达到上述门槛后，才能将“完整对局执行”从“缺失”改为针对最小范围的“已完整实现”；其他模式和武将仍需分别验收。
