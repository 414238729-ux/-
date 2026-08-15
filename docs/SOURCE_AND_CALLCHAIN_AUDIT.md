# 三国杀模拟来源与调用链审计

> 审计日期：2026-08-01  
> 审计范围：`D:\MyGPT\game-analysis` 正式项目、用户本轮列出的 `C:\Users\ASUS\Downloads` 外部文件及同目录发现的直接相关审计包。  
> 阶段状态：来源与调用链审计已通过；本文件是本任务对仓库的第一项源文件写入。  
> 证据口径：结论来自文件内容、导入关系、路径、哈希、CSV/JSON解析和修改前测试；不根据文件名猜测来源。
> 时间点说明：第 1–9 节保留“任何代码修改前”的首次审计快照；后续新增的权威核心基础设施见第 10 节。快照中的“当前不存在”不得脱离时间点解释为最终状态。

## 1. 结论摘要

1. 当前正式项目目录不是 Git 工作树：`git rev-parse --show-toplevel`、`git status` 和 `git log` 均返回 `fatal: not a git repository`。因此无法诚实给出“已跟踪／未跟踪”的 Git 状态；下表统一写为“不可判定（无 Git 元数据）”。本任务后续使用状态文档、文件哈希和测试结果作为检查点，不伪造 Git 提交。
2. 用户列出的 13 个文件全部可读，均位于 `C:\Users\ASUS\Downloads`，不在正式项目内。正式项目全文没有这些脚本的副本、导入或调用。
3. 另发现一个同哈希复现脚本副本和一个相关确定性审计压缩包；二者也在正式项目外。
4. 旧胜率的真实调用链是：复现 Shell 脚本顺序执行 15 个 worker 分片，再由聚合器读取 15 个 pickle 分片，生成胜率明细、汇总、审计 JSON、报告和复现脚本。
5. `sgs_sim_engine_worker.py` 不读取正式 Knowledge、牌堆 CSV 或本仓库模块；它在单文件中用固定武将系数、概率和手牌／装备整数建立近似器。
6. `sgs_ai_audit_20260729.py` 不调用 worker、正式规则模块或真实 AI；大量检查直接令 `chosen = expected`，因此输出的 100% 通过率不能证明实现正确。
7. 当前正式项目是“正式 Knowledge + 可测试的轻量规则／技能／策略组件库”，没有统一 `GameState`、完整对局 runner、合法动作枚举、回放、网页或正式批量胜率入口，当前不能完整运行一局。
8. 修改前基线测试实际运行结果为 `947 passed in 3.39s`。这只证明既有组件测试通过，不等于完整规则引擎通过。

## 2. 实际可访问文件清单

### 2.1 用户本轮明列的外部文件

| # | 文件 | 绝对路径 | 大小（字节） | SHA-256 | 正式项目内 | Git 状态 |
|---:|---|---|---:|---|---|---|
| 1 | `sgs_ai_audit_20260729.py` | `C:\Users\ASUS\Downloads\sgs_ai_audit_20260729.py` | 29,275 | `CA54FC27042B5690AC944B6E628177F034F2BB15B148BB07DD7ED78145681C13` | 否 | 不可判定（无 Git 元数据） |
| 2 | `sgs_sim_engine_worker.py` | `C:\Users\ASUS\Downloads\sgs_sim_engine_worker.py` | 36,809 | `297150D8437E4F11857732F2121632AA118CE7C62B121F5A2A3CE3F87DDB94CE` | 否 | 不可判定（无 Git 元数据） |
| 3 | `sgs_sim_aggregate.py` | `C:\Users\ASUS\Downloads\sgs_sim_aggregate.py` | 14,412 | `2D7629B4B26716DCD83B24FB5C1EB34D3393A7D21CAD812EC43936D0F5E68BDD` | 否 | 不可判定（无 Git 元数据） |
| 4 | `三国杀_当前模拟代码与实际规则一致性总审计_20260730.md` | `C:\Users\ASUS\Downloads\三国杀_当前模拟代码与实际规则一致性总审计_20260730.md` | 20,084 | `A20A4E4E6FAC4CF83A7B2F7E31077FF8269C94A18470BF85BC3F01E108FCD826` | 否 | 不可判定（无 Git 元数据） |
| 5 | `三国杀_16将三模式实战近似模拟审计_20260729.json` | `C:\Users\ASUS\Downloads\三国杀_16将三模式实战近似模拟审计_20260729.json` | 8,039 | `C4D0D6F1FA31C00F8B1764EFD86FF9F436A226D60B960DE0AC34AD573789CC53` | 否 | 不可判定（无 Git 元数据） |
| 6 | `三国杀_16将三模式实战近似胜率明细_20260729.csv` | `C:\Users\ASUS\Downloads\三国杀_16将三模式实战近似胜率明细_20260729.csv` | 22,149 | `1ACBF4923AE3CB8629848E052684115A38A34412EC87B1E5E68A2F2D4BB734CE` | 否 | 不可判定（无 Git 元数据） |
| 7 | `三国杀_16将三模式实战近似胜率汇总_20260729.csv` | `C:\Users\ASUS\Downloads\三国杀_16将三模式实战近似胜率汇总_20260729.csv` | 1,778 | `4D7FF5CC70F04B3330699635297DB59781A1E4DD700A541EAF8B51F02F758065` | 否 | 不可判定（无 Git 元数据） |
| 8 | `三国杀_16将三模式实战近似胜率报告_20260729 .md` | `C:\Users\ASUS\Downloads\三国杀_16将三模式实战近似胜率报告_20260729 .md` | 5,713 | `362A670DD768DAE5861BD11F036A29B9674CE191708AF7500D4B7DBA5B499AA9` | 否 | 不可判定（无 Git 元数据） |
| 9 | `三国杀_三模式AI行为审计配置与异常_20260729.json` | `C:\Users\ASUS\Downloads\三国杀_三模式AI行为审计配置与异常_20260729.json` | 5,648 | `F7E1104C231AB442B4B9F94B187F7DBE764AA190EB8E95DA8B3069F1A5A1DEC3` | 否 | 不可判定（无 Git 元数据） |
| 10 | `三国杀_三模式AI行为审计明细_20260729.csv` | `C:\Users\ASUS\Downloads\三国杀_三模式AI行为审计明细_20260729.csv` | 7,996 | `40AEEE68B6A6E164F810909B6D0365F54FE3859B8D6E9AD57572BBA77EF41875` | 否 | 不可判定（无 Git 元数据） |
| 11 | `三国杀_军八2v2斗地主_AI行为审计报告_20260729.md` | `C:\Users\ASUS\Downloads\三国杀_军八2v2斗地主_AI行为审计报告_20260729.md` | 5,351 | `DCE648B70015CA77D94C478F4B036B29C61AD7F33F6E657E3B7DBB494264E517` | 否 | 不可判定（无 Git 元数据） |
| 12 | `三国杀_当前模拟代码与规则差异清单_20260730.json` | `C:\Users\ASUS\Downloads\三国杀_当前模拟代码与规则差异清单_20260730.json` | 18,807 | `8B923366BCF727C86714D81F90A1EB21D529C9F11A0CC15C472C0D6EA921A554` | 否 | 不可判定（无 Git 元数据） |
| 13 | `复现_三国杀16将三模式近似模拟.sh` | `C:\Users\ASUS\Downloads\复现_三国杀16将三模式近似模拟.sh` | 613 | `B5B01B09C19E6AD9EEF6D55BB4D3A2EEA8F0BB10EFF9AFA4AA4782CAC4B9148E` | 否 | 不可判定（无 Git 元数据） |

### 2.2 同目录额外发现的直接相关文件

| 文件 | 绝对路径 | 大小（字节） | SHA-256 | 结论 |
|---|---|---:|---|---|
| 复现脚本副本 | `C:\Users\ASUS\Downloads\复现_三国杀16将三模式近似模拟 (1).sh` | 613 | `B5B01B09C19E6AD9EEF6D55BB4D3A2EEA8F0BB10EFF9AFA4AA4782CAC4B9148E` | 与明列复现脚本逐字节同哈希；外部重复副本，不复制进项目。 |
| 确定性审计包 | `C:\Users\ASUS\Downloads\sgs_audit_bundle.zip` | 14,643 | `EED0988DA9A3B9668E36E90848CE7AF1457E8BC0CC967F3B1B5B83CB3B2BD048` | 内含 `sgs_audit_harness.py`、`test_sgs_audit.py`、`run_sgs_audit.py`、`sgs_audit_report.json`、`sgs_audit_examples.jsonl`；外部审计包，不是正式引擎。 |

压缩包的 runner 固定读取包目录中的两份 CSV，但这两份 CSV 未包含在压缩包内；现有正式项目中的新版同名数据哈希也与包内旧报告记录不同，因此该 ZIP 不是自包含的可复现包。

#### `sgs_audit_bundle.zip` 的内部调用链与产物

该压缩包已经按成员源码实际展开审计，内部调用关系为：

```text
run_sgs_audit.py
  -> 导入同包 sgs_audit_harness.py
  -> 用 pandas 读取同目录 三国杀牌堆数据.csv、三国杀卡牌结构化数据.csv
  -> subprocess 调用当前 Python 执行同目录 test_sgs_audit.py
       -> test_sgs_audit.py 仅导入并测试 sgs_audit_harness.py
  -> 直接调用 harness 中的局部角色、分配、技能与统计函数
  -> 写 sgs_audit_examples.jsonl
  -> 写 sgs_audit_report.json
```

两份 CSV 未包含在 ZIP 中，因此该调用链不能从 ZIP 单独复现。包内 `sgs_audit_report.json` 自身记录 `full_battle_engine_present=false` 和 `final_strength_results_validated=false`；23 个 `unittest` 只覆盖包内 harness，并未调用本仓库统一核心或真实整局 AI。包内报告与 JSONL 可作为该 harness 的历史输出和审计方法样本，不能作为正式规则引擎、武将完整实现或胜率有效性的证据。

### 2.3 正式项目内的可维护源文件

排除 `.venv`、`__pycache__`、`.pyc` 和 `.pytest_cache` 后，修改前共有 100 个可维护源文件：根目录 8 个、`knowledge/` 12 个、`scripts/` 30 个、`tests/` 50 个。正式 Knowledge 以现有 `knowledge/` 目录中的下列 12 个文件为唯一来源，本任务不建立带时间戳或“新版／副本”后缀的 Knowledge：

```text
knowledge/Overlord_DND换算规范.md
knowledge/三国杀基础术语与通用机制.md
knowledge/三国杀卡牌结构化数据.csv
knowledge/三国杀卡牌使用方式.csv
knowledge/三国杀卡牌效果.md
knowledge/三国杀模拟规范.md
knowledge/三国杀模式规则.md
knowledge/三国杀牌堆数据.csv
knowledge/三国杀武将规则补充.md
knowledge/三国杀增量规则整理_第二次汇总之后.md
knowledge/三角洲枪械分析规范.md
knowledge/通用概率分析规范.md
```

本轮相关正式代码由 `scripts/` 下 30 个 Python 源文件和 `tests/` 下 50 个测试文件组成。完整路径清单可由仓库根目录执行以下只读命令重建：

```powershell
rg --files -g '!*.pyc' -g '!**/__pycache__/**' | Sort-Object
```

审计确认正式项目中不存在外部三个 Python 文件、旧输出文件、`GameState` 统一入口、网页资源或另一套隐藏引擎。

### 2.4 任务范围清单口径

“当前任务中实际能够访问的全部文件”按以下边界盘点：

- 正式项目中排除 `.venv`、`__pycache__`、`.pyc` 和 `.pytest_cache` 后的全部可维护文件；
- 用户本轮明列的 13 个 `C:\Users\ASUS\Downloads` 文件；
- 同目录按名称、哈希或直接调用关系发现的复现脚本副本与 `sgs_audit_bundle.zip`；
- 不把 Downloads 中与本任务无关的个人文件纳入审计，也不把依赖环境和缓存误列为项目源文件。

位置类型只有两类：`D:\MyGPT\game-analysis` 内的是正式项目文件；本轮列出的 Downloads 文件是“仓库外、用户提供且本任务可读的材料”，不是正式项目文件。由于项目根目录不存在 `.git`，两类文件均不能获得此项目的 tracked／untracked 状态；仓库外文件同时明确不属于当前项目。第 2.1 节逐项列出全部明列外部材料，第 2.2 节列出额外相关材料，第 2.3 节记录修改前正式文件分类与唯一 Knowledge 集合。后续新增文件必须在状态文档的检查点中登记，不回写为首次审计前就已存在。

### 2.5 正式项目可维护文件逐项清单

以下是首次写入前的100个可维护文件。每项均使用仓库相对路径，绝对路径为 `D:\MyGPT\game-analysis\<相对路径>`；位置类型均为“正式项目内”，Git状态均为“不可判定（无Git元数据）”。这份清单排除依赖环境和缓存。

```text
.gitignore
AGENTS.md
CUSTOM_GPT_UPLOAD_MANIFEST.md
GPT_INSTRUCTIONS.md
pytest.ini
README.md
requirements-dev.txt
UPLOAD_GUIDE.md
knowledge/Overlord_DND换算规范.md
knowledge/三国杀基础术语与通用机制.md
knowledge/三国杀卡牌结构化数据.csv
knowledge/三国杀卡牌使用方式.csv
knowledge/三国杀卡牌效果.md
knowledge/三国杀模拟规范.md
knowledge/三国杀模式规则.md
knowledge/三国杀牌堆数据.csv
knowledge/三国杀武将规则补充.md
knowledge/三国杀增量规则整理_第二次汇总之后.md
knowledge/三角洲枪械分析规范.md
knowledge/通用概率分析规范.md
scripts/__init__.py
scripts/_validation.py
scripts/card_draw.py
scripts/damage.py
scripts/deck_data.py
scripts/monte_carlo.py
scripts/ranking.py
scripts/sgs_ai_strategy_v22.py
scripts/sgs_ai_strategy_v24.py
scripts/sgs_card_rules.py
scripts/sgs_card_strategy.py
scripts/sgs_chain_strategy.py
scripts/sgs_extended_rules.py
scripts/sgs_focus_strategy.py
scripts/sgs_general_ai_v21.py
scripts/sgs_general_rules.py
scripts/sgs_general_strategy.py
scripts/sgs_incremental_generals.py
scripts/sgs_incremental_mechanics.py
scripts/sgs_jink_response.py
scripts/sgs_limited_identity_variant.py
scripts/sgs_mode_evaluation.py
scripts/sgs_modes.py
scripts/sgs_skill_framework.py
scripts/sgs_special_general_rules.py
scripts/sgs_structured_data.py
scripts/sgs_team_strategy.py
scripts/sgs_v24_generals.py
scripts/summary.py
scripts/trigger.py
tests/test_card_draw.py
tests/test_custom_gpt_upload_manifest.py
tests/test_damage.py
tests/test_deck_data.py
tests/test_monte_carlo.py
tests/test_ranking.py
tests/test_sgs_ai_strategy_v22.py
tests/test_sgs_ai_strategy_v24.py
tests/test_sgs_card_data.py
tests/test_sgs_card_rules.py
tests/test_sgs_card_strategy.py
tests/test_sgs_comprehensive_strategy_docs.py
tests/test_sgs_death_card_use_revision.py
tests/test_sgs_delayed_trick_order.py
tests/test_sgs_distance_and_card_effects.py
tests/test_sgs_distance_damage_docs.py
tests/test_sgs_extended_rules.py
tests/test_sgs_final_knowledge.py
tests/test_sgs_focus_strategy.py
tests/test_sgs_general_ai_v21.py
tests/test_sgs_general_knowledge.py
tests/test_sgs_general_rules.py
tests/test_sgs_general_strategy.py
tests/test_sgs_incremental_generals.py
tests/test_sgs_incremental_mechanics.py
tests/test_sgs_incremental_rules.py
tests/test_sgs_jink_bagua_response.py
tests/test_sgs_knowledge_docs.py
tests/test_sgs_landlord_seating.py
tests/test_sgs_limited_identity_variant.py
tests/test_sgs_limited_variant_docs.py
tests/test_sgs_mode_evaluation.py
tests/test_sgs_mode_metadata_probability_and_victory_order.py
tests/test_sgs_modes.py
tests/test_sgs_mounts_and_equipment_frequency.py
tests/test_sgs_platform_round_and_selection.py
tests/test_sgs_precision_rules_docs.py
tests/test_sgs_second_increment_attachment_merge.py
tests/test_sgs_second_increment_program.py
tests/test_sgs_second_round_increment_summary.py
tests/test_sgs_skill_framework.py
tests/test_sgs_structured_layers.py
tests/test_sgs_team_strategy.py
tests/test_sgs_trick_usage_and_chain_ai.py
tests/test_sgs_v24_event_model.py
tests/test_sgs_v24_generals.py
tests/test_sgs_v24_knowledge.py
tests/test_sgs_v24_registry.py
tests/test_summary.py
tests/test_trigger.py
```

本任务新增的25个可维护文件如下；同样全部位于正式项目内且因无Git元数据而没有可判定的tracked/untracked状态：

```text
docs/CHECKPOINT_MANIFEST.json
docs/ENGINE_STATUS.md
docs/IMPLEMENTATION_MATRIX.md
docs/LEGACY_RESULTS_INVALID.md
docs/MASTER_IMPLEMENTATION_PLAN.md
docs/SOURCE_AND_CALLCHAIN_AUDIT.md
scripts/sgs_engine/__init__.py
scripts/sgs_engine/actions.py
scripts/sgs_engine/engine.py
scripts/sgs_engine/events.py
scripts/sgs_engine/model.py
scripts/sgs_engine/replay.py
scripts/sgs_engine/rng.py
scripts/sgs_engine_gate.py
scripts/sgs_formal_runner.py
scripts/sgs_source_integrity_audit.py
tests/test_sgs_engine_actions.py
tests/test_sgs_engine_events.py
tests/test_sgs_engine_gate.py
tests/test_sgs_engine_model.py
tests/test_sgs_engine_package.py
tests/test_sgs_engine_rng_replay.py
tests/test_sgs_engine_session.py
tests/test_sgs_formal_runner.py
tests/test_sgs_source_integrity_audit.py
```

## 3. `.sh` 的实际完整调用链

复现脚本使用 `set -euo pipefail`，按顺序而非并行执行：

```text
for chunk = 0..4
  SGS_SIM_MODE=military
  SGS_SIM_GAMES=20000
  SGS_SIM_SEED=chunk
  SGS_SIM_OUTPUT=/mnt/data/sgs_partial_military_{chunk}.pkl
  python /mnt/data/sgs_sim_engine_worker.py

  SGS_SIM_MODE=2v2
  SGS_SIM_GAMES=20000
  SGS_SIM_SEED=1000+chunk
  SGS_SIM_OUTPUT=/mnt/data/sgs_partial_2v2_{chunk}.pkl
  python /mnt/data/sgs_sim_engine_worker.py

  SGS_SIM_MODE=landlord
  SGS_SIM_GAMES=20000
  SGS_SIM_SEED=2000+chunk
  SGS_SIM_OUTPUT=/mnt/data/sgs_partial_landlord_{chunk}.pkl
  python /mnt/data/sgs_sim_engine_worker.py

python /mnt/data/sgs_sim_aggregate.py
```

因此理论调用量为：每模式 5 片 × 每片 20,000 局 = 每模式 100,000 局，三模式合计 300,000 局。脚本没有 `&`、`xargs`、GNU Parallel 或 Python multiprocessing，不能称为多进程运行。路径硬编码为 Linux `/mnt/data`；当前文件位于 Windows Downloads，原脚本在当前路径不能原样命中输入。

### 3.1 worker 内部调用

```text
环境变量
  -> worker `__main__`
  -> simulate_mode(mode, games, seed, MAX_ROUNDS[mode])
  -> 本文件内 SimGame(...).run(...)
  -> pickle.dump(result, SGS_SIM_OUTPUT)
```

关键证据：worker 第 787–808 行定义并调用单文件 `simulate_mode`；第 810–821 行读取环境变量并写 pickle。它只导入 Python 标准库，不导入本项目 `scripts`、Knowledge 或 CSV。

### 3.2 聚合器内部调用

```text
/mnt/data/sgs_partial_{mode}_{0..4}.pkl 共15个
  -> pickle.load
  -> 汇总 appearances / wins / 置信区间
  -> 写明细CSV、汇总CSV、审计JSON、Markdown报告、复现Shell脚本
```

聚合器第 58–66 行读取分片；第 120–140 行写两份 CSV；第 161–191 行写审计 JSON；第 193–273 行写报告；第 275–292 行写复现脚本。

## 4. 配置的真实来源

没有单独名为 `config.json` 的文件不构成配置缺失。实际配置分布如下：

| 配置 | 来源 | 证据 |
|---|---|---|
| 模式、每片局数、seed、分片输出路径 | Shell 环境变量 | 复现脚本第 3–13 行；worker 第 813–818 行 |
| 16 名候选池 | worker Python 常量 `POOL` | worker 第 6–9 行 |
| 武将静态经济／输出／防御／控制等系数 | worker Python 常量 `PF` | worker 第 24 行起 |
| 模式、角色和开局近似 | worker 类和常量 | worker 第 69–105 行 |
| 最大回合数 | worker `MAX_ROUNDS` | worker 第 785 行 |
| 聚合模式、分片数、每片局数、固定目录 | aggregate 常量 | aggregate 第 5–14、58–60 行 |
| AI 审计 seed、每模式试验数、候选池、模式角色 | AI audit Python 常量 | AI audit 第 10–22 行 |
| 旧输出中自报的运行配置 | 两份 JSON | `三国杀_16将三模式实战近似模拟审计_20260729.json`、`三国杀_三模式AI行为审计配置与异常_20260729.json` |

未发现上述三个 Python 入口读取命令行参数、项目配置文件或本项目环境变量以外的规则数据。

## 5. 输出文件生成映射

| 输出 | 生成程序 | 证据 |
|---|---|---|
| 15 个 `sgs_partial_*.pkl` | `sgs_sim_engine_worker.py` | worker 第 813–821 行 |
| `三国杀_16将三模式实战近似胜率明细_20260729.csv` | `sgs_sim_aggregate.py` | aggregate 第 120–125 行 |
| `三国杀_16将三模式实战近似胜率汇总_20260729.csv` | `sgs_sim_aggregate.py` | aggregate 第 137–142 行 |
| `三国杀_16将三模式实战近似模拟审计_20260729.json` | `sgs_sim_aggregate.py` | aggregate 第 161–191 行 |
| `三国杀_16将三模式实战近似胜率报告_20260729 .md` | `sgs_sim_aggregate.py` | aggregate 第 193–273 行；真实文件名在 `.md` 前含一个空格 |
| `复现_三国杀16将三模式近似模拟.sh` | `sgs_sim_aggregate.py` | aggregate 第 275–292 行 |
| `三国杀_三模式AI行为审计明细_20260729.csv` | `sgs_ai_audit_20260729.py` | AI audit 第 467–479 行 |
| `三国杀_三模式AI行为审计配置与异常_20260729.json` | `sgs_ai_audit_20260729.py` | AI audit 第 481–490 行 |
| `三国杀_军八2v2斗地主_AI行为审计报告_20260729.md` | `sgs_ai_audit_20260729.py` | AI audit 第 492–584 行 |
| `三国杀_当前模拟代码与规则差异清单_20260730.json` | 未提供生成程序 | 文件可读；只能确定为后续静态审计产物 |
| `三国杀_当前模拟代码与实际规则一致性总审计_20260730.md` | 未提供生成程序 | 文档自述对象和方法；无可复现生成入口 |

Downloads 中报告文件名在 `.md` 前多一个空格，但其正文与聚合器模板一致。不能只靠内容一致断言字节级同源；本表的“生成程序”指模板与调用链证据。

## 6. 旧结果与旧审计的有效性

### 6.1 旧胜率

旧胜率只能保留为历史抽象近似基线，不能作为当前正式规则胜率：

- worker 用 `PF` 中的固定 `econ/offense/defense/control/extra_attack/damage2/support/threat` 系数表示武将；
- `Pl` 只保存 `hand: int` 和 `equip: int`，没有实体手牌；
- 摸牌只增加整数；多项技能、命中、伤害、救援用固定概率或固定收益近似；
- 达到回合上限时按存活人数、体力和少量手牌价值启发式强制给出胜者；
- 审计 JSON 明确写明 `full_160_card_engine_loaded=false`、特殊军八未加载、斗地主农民死亡奖励未加载；
- 没有 `unsupported_rules`、`approximation_count`、规则／牌堆／武将哈希或确定性测试门禁。

旧结果中有 1,622／300,000 局达到上限后被启发式判胜（军八 399、2v2 1,000、斗地主 223，合计约 0.5407%），而 CSV 没有逐局截断标记。

### 6.2 旧 AI 审计

AI 审计脚本只调用本文件内 `CHECKERS`，不调用正式 AI。大量检查直接写 `chosen = expected`；确定性回归含恒等式和常量真值。由此生成的 1,500,000 条审计记录、100% 合法率／可见性率、30／30 回归只能证明同源代码自洽，不能证明真实实现路径正确。其 2v2 角色还按 `A,B,A,B` 建模，与当前正式 1／4、2／3 固定队友规则不一致。

### 6.3 外部 CSV/JSON 的数据一致性

文件均成功展开并解析：

- 胜率明细：180 数据行 × 10 列，主键无重复；点估计、胜场／出现数及置信区间内部数学一致；
- 胜率汇总：16 行 × 6 列，主键无重复，汇总值与明细对应值一致；
- AI 明细：108 行 × 9 列，所有通过率／合法率／可见性率均为 1.0，与 JSON／报告内部一致；
- 差异 JSON 的 `issue_count=97` 与实际数组计数一致。

“文件内部数学一致”不等于“规则实现有效”。2026-07-30 差异清单已将旧 300,000 局胜率标为 `invalid_as_current_rule_results`，将旧 1,500,000 条行为审计和 30／30 回归标为 `invalid_as_implementation_evidence`。

### 6.4 `artifact-tool` 只读展开复核

按表格审计流程使用 `@oai/artifact-tool` 的 `Workbook.fromCSV`、`getUsedRange(true)` 和 `workbook.inspect` 实际导入六份 CSV，均可正常展开：

| CSV | Used range | 数据行 | 列数 |
|---|---:|---:|---:|
| 正式 `三国杀牌堆数据.csv` | `A1:U161` | 160 | 21 |
| 正式 `三国杀卡牌结构化数据.csv` | `A1:AY39` | 38 | 51 |
| 正式 `三国杀卡牌使用方式.csv` | `A1:K10` | 9 | 11 |
| 外部胜率明细 | `A1:J181` | 180 | 10 |
| 外部胜率汇总 | `A1:F17` | 16 | 6 |
| 外部 AI 审计明细 | `A1:I109` | 108 | 9 |

三份外部 CSV 的首列表头实际带 UTF-8 BOM，分别为 `﻿mode`、`﻿武将`、`﻿mode`。能使用 `utf-8-sig` 的旧脚本通常可正确处理，但任何按无 BOM 精确字符串取列的工具都可能失败；这是来源数据清洁风险，不影响“规则近似结果整体失效”的结论。正式三份 CSV 的范围和表头与当前加载器预期一致。

### 6.5 指定缺陷模式的搜索证据

| 搜索模式 | 外部旧材料证据 | 修改前正式项目结论 |
|---|---|---|
| 随机概率代替技能 | worker 的命中、技能、伤害和救援含固定概率分支 | 局部策略可显式接收概率参数，但没有整局入口用它们冒充正式技能；当时也没有正式胜率入口 |
| 固定武将系数 | worker 的 `PF` 常量保存 `econ/offense/defense/control/extra_attack/damage2/support/threat` | 未发现正式项目导入或读取该 `PF` |
| 固定摸牌或固定伤害 | worker 主要增加 `hand` 整数并以固定收益更新状态 | 正式项目存在局部规则函数，但修改前没有整局实体牌执行链 |
| `chosen = expected`／`assert chosen == expected` | `sgs_ai_audit_20260729.py` 大量命中；包内 harness 测试也只验证包内函数 | 未发现真实统一 AI 被这些外部检查调用；此模式已明确禁止计入正式验收 |
| 只有 hand 数量而无实体手牌 | worker 的玩家状态使用 `hand: int` | 正式牌堆 CSV 有实体 ID，但修改前未装配进整局 `GameState` |
| 未实现后静默继续 | worker 没有正式 unsupported 门禁，缺失机制以近似继续 | 修改前没有正式整局入口；后续阶段 2 已新增失败关闭门禁 |
| approximation 后生成正式胜率 | aggregate 不检查 approximation 即聚合 worker 输出 | 修改前正式项目没有该调用链；后续正式入口对 approximation 非零明确拒绝 |

本表区分“外部材料实际命中”和“修改前正式项目状态”。不能因正式项目中存在通用概率计算函数，就把它等同于外部 worker 用概率替代未实现技能。

## 7. 修改前正式项目是否存在另一套完整引擎

首次审计时间点结论：不存在可运行完整一局的统一引擎，但存在大量可复用的局部组件。后续新增 foundation 见第 10 节。

| 能力 | 当前状态 | 主要证据 |
|---|---|---|
| 160 张实体牌与唯一 ID | 数据层已实现，未接入对局 | `knowledge/三国杀牌堆数据.csv`；`scripts/deck_data.py` |
| 手牌／装备／判定／特殊区 | 部分局部状态 | `scripts/sgs_extended_rules.py`、`scripts/sgs_card_rules.py` |
| 牌堆／弃牌堆／处理区 | 部分局部状态 | `TableCardState`，未与玩家和回合整合 |
| 使用／打出／响应／获得／失去事件 | 分散实现 | `sgs_card_rules.py`、`sgs_incremental_mechanics.py`、`sgs_jink_response.py` |
| 回合和阶段 | 常量与局部追踪 | `sgs_modes.py`，无逐阶段 runner |
| 判定与延时锦囊 | 局部结算器 | `sgs_card_rules.py`、`sgs_extended_rules.py`，需调用方回调 |
| 伤害／濒死／死亡／胜负 | 局部结算器 | `sgs_modes.py`、`sgs_extended_rules.py`、`sgs_card_rules.py` |
| 距离／装备 | 局部实现 | `sgs_modes.py`、`sgs_extended_rules.py`、`sgs_card_rules.py` |
| 模式状态机 | 部分实现 | 2v2、斗地主、身份和特殊八人均无完整 runner；单挑缺失 |
| 武将技能 | 按需局部函数 | 多个 `sgs_*generals.py`，无统一触发注册器 |
| 合法动作枚举 | 缺失 | 现有策略要求调用方传入候选动作 |
| 决策评分 | 局部实现 | `sgs_ai_strategy_v22.py`、`sgs_focus_strategy.py` |
| 确定性随机 | 函数级 seed | 无全局随机状态、消费记录或回放绑定 |
| 回放 | 缺失 | 无 `ReplayRecord` 或整局序列化 |
| 网页与前端 | 缺失 | 无 HTML／JS／TS／HTTP 入口 |
| 正式批量胜率 | 缺失 | `run_monte_carlo` 只是调用方试验回调器 |

全仓只找到局部 `DamageEvent`；不存在统一 `CardInstance`、`PlayerState`、`GameState`、`EventQueue`、`ResponseWindow`、`LegalAction`、`DeterministicRNG`、`ReplayRecord`、`enumerate_legal_actions`、`run_game` 或 `simulate_game`。`scripts/__init__.py` 是组件导出文件，不是对局入口。

## 8. 缺失文件与不可复现项

1. 15 个 `sgs_partial_{mode}_{chunk}.pkl` 均未在 Downloads 或正式项目中找到；现有聚合器不能仅靠最终 CSV 重做聚合。
2. 未提供旧运行日志、标准输出、运行环境快照或依赖锁文件。
3. 未提供 2026-07-30 差异 JSON 和总审计 Markdown 的生成程序。
4. 外部审计 ZIP 缺少其 runner 预期同目录存在的两份 CSV。
5. 没有独立 `config.json`，但核心配置已经由 Shell 环境变量、Python 常量和输出 JSON 完整承载；这不属于配置缺失。
6. 当前没有 Git 元数据，无法提供 Git 历史、提交或 tracked/untracked 证明。
7. 当前没有统一完整规则引擎、完整对局回放、网页、前端或正式多进程胜率入口。

上述缺失不会要求用户重复提供已经存在的 13 个文件；只会限制重放旧分片、验证旧运行环境和复现后续静态审计生成过程。

## 9. 阶段一验收

| 验收项 | 结果 | 证据 |
|---|---|---|
| 已盘点实际找到文件及路径 | 通过 | 第 2 节 |
| 已说明 Git 状态与项目内／外 | 通过 | 第 1、2 节 |
| 已还原 `.sh` 完整调用链 | 通过 | 第 3 节 |
| 已识别配置来源 | 通过 | 第 4 节 |
| 已建立输出生成映射 | 通过 | 第 5 节 |
| 已列出缺失项 | 通过 | 第 8 节 |
| 已确定两个 GPT 脚本与正式项目关系 | 通过：外部且未被正式入口调用 | 第 1、7 节 |
| 已确定旧胜率真实入口 | 通过：外部 worker + aggregate | 第 3、5 节 |
| 已确定当前是否有完整正式引擎 | 通过：没有；仅局部组件 | 第 7 节 |

修改前基线命令与结果：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 947 passed in 3.39s
```

## 10. 首次审计后的当前 foundation 状态

首次审计完成后，项目在阶段 4 新增了 `scripts/sgs_engine/` 权威核心基础设施。该变化不改写第 1–9 节对“修改前仓库”的历史结论。当前新增能力包括：

- `CardInstance`、`PlayerState`、不可变 `GameState` 与全局／玩家牌区；
- 正式 160 张实体牌装配、唯一位置、区域顺序、牌守恒与确定性洗牌；
- `GameEvent`、`DamageEvent`、`EventQueue` 和按明确顺序处理的 `ResponseWindow`；
- `LegalAction`、严格规则适配器注册、合法动作重新枚举与伪造／过期动作拒绝；
- 单一 `DeterministicRNG` 及随机消费记录；
- `ReplayRecord` 的 JSON／JSONL 存取、状态哈希和前向哈希链完整性校验；
- `AuthoritativeCoreSession` 的实体牌原子移动、事件登记、回放登记和未实现规则失败关闭。

这些都是 foundation，不是完整对局引擎：

- 没有卡牌效果、六阶段、模式、武将技能和 AI 的生产规则适配器；
- `enumerate_legal_actions` 只有通用注册／校验基础设施，尚无完整生产候选集；
- `ReplayRecord` 校验记录完整性，不会自行重执行三国杀规则；
- `AuthoritativeCoreSession.run_game` 仍明确抛出 `UnsupportedRuleError`；
- `scripts.sgs_formal_runner` 仍报告 `authoritative_core_foundation=true`、`authoritative_full_game_core=false`，并拒绝生成结果。

因此阶段 1–3 保持通过，阶段 4 为进行中，阶段 5–9 未开始。本轮代码稳定后的最终验收为 `1094 passed`（失败0、跳过0），compileall 通过；源码防伪扫描覆盖99个 Python 文件且 `defect_count=0`。这证明当前 foundation 与既有组件保持可运行，不表示完整对局核心已经完成。

## 11. Milestone B production formal 调用链（HISTORICAL/AS-OF，2026-08-09）

本节是 `MILESTONE_B_FORMAL_160_CARD_NO_SKILL_DUEL_ADVANCEMENT` 的
**旧**开发调用链快照（PRE-AUDIT SNAPSHOT），不改写第 1–10 节的历史时间点，
也不是 whole-repo audit 的 remediation-7 或独立审计结论。固定基线为
`4c8c4466f1950740c69767a01a0b24cab723b310`，开发分支为
`sol-ultra-milestone-b-formal-duel`；当时工作树尚未提交，`commit=null`、
`pending`。CURRENT 状态以第 12 节为准。

### 11.1 统一权威调用链

```text
scripts/sgs_formal_runner.py
  -> _inspect_formal_duel_safely()
     -> scripts/sgs_engine/formal_duel.py::inspect_formal_duel_readiness()
        -> FormalCardRegistry.from_formal_csv()  # 160 CardInstance / 38 keys
        -> WEAPON_SKILL_STATUS / _semantic_key_sets()  # 派生global与duel语义集合
        -> FormalNoSkillDuelSession(..., analysis_only=True)  # factory probe
           -> ProductionBasicCardBatch  # 同一生产核心，不是第二套引擎
        -> callable(record_reference_formal_duel) and callable(reexecute_production_replay)
           # 此处只检查能力存在，不录制或执行一局 replay
  -> run_formal_simulation()
     -> require_formal_simulation_ready()
        -> evaluate_formal_run_gate()
           -> 现场重新读取 canonical readiness 与仓库内正式 runner 源码
     -> _validated_formal_seed_evidence()  # 复检精确0..99逐seed证据
     -> _atomic_write_json()               # 仅门禁及复检均通过后原子输出
     -> 当前因规则、模式、卡牌与100-seed门禁在接触输出路径前失败关闭
```

formal session 继续使用同一 `GameState`、唯一 `CardInstance`、统一事件队列、`LegalAction` 枚举／重验、响应窗口、伤害、距离、阶段、濒死／死亡／胜负、重洗事务及 `DeterministicRNG`。`test_only_duel_vertical_slice` 没有复制或提升为 formal mode。strict replay 通过 mode-bound canonical factory 重建初态并逐动作执行；formal record 拒绝 fixture 注入；player-visible 投影与 omniscient 审计材料分离。

### 11.2 现场派生能力与失败关闭边界

| 项目 | 当前值／状态 |
|---|---|
| 正式牌堆 | 160 实体、38 类、注册实体 160 |
| global 完整语义 | 36 类／158 实体 |
| duel-scope sufficient | 37 类／159 实体 |
| formal factory | `mode_runtime_reachable=true`（analysis-only） |
| mode | `mode_implemented=false` |
| cards | `all_cards_implemented=false` |
| replay | `reexecution_replay_supported=true` |
| rules | `unsupported_rules=2` |
| approximation | `approximation_count=0` |
| fixed-seed acceptance | 0／100；未运行正式批次 |
| final gate | `formal_duel_no_skill_ready=false` |

两个规则计数项分别是 formal duel 权威 profile 与丈八蛇矛材料生命周期。雌雄双股剑通用状态机和通用性别 schema 已实现，但 formal 参与者的角色／性别来源仍为 MODE_GAP；方天画戟多人附加目标在严格两人 duel 中为 `NOT_APPLICABLE_TO_DUEL`，global 仍保持 `PARTIAL`。通用 `VirtualCardReference` 已进入 `LegalAction`，显式绑定 card key、conversion rule 与材料实体 ID，禁止 physical／virtual 引用并存，并参与公共枚举校验、动作 ID 和 strict production／duel replay；原独立 typed virtual-card `DATA_MODEL_GAP` 已关闭。丈八仍只保留 `VIRTUAL_CARD_SUBCARD_LIFECYCLE_RULE_GAP`，具体材料区域时序接线受 A／B 规则门禁控制。

### 11.3 Analysis-only 固定 seed 诊断边界

`docs/MILESTONE_B_ANALYSIS_SEED_DIAGNOSTIC.json` 保存了固定 seeds 0..99 的逐局诊断证据；没有排除或重采样，单局上限固定为2000。100条记录中55局自然结束（p1=34、p2=21，动作数最小44、最大494），45局非自然结束全部是既有失败关闭 `UnsupportedRuleError`：丈八生命周期23局、雌雄 formal 角色／性别元数据22局。所有记录均为160张牌，联合到达全部38个 card key；safety-cap、`InvalidActionError`、`ProductionBatchError` 及其他异常均为0。因此，本次可观察范围内的非规则 seed blocker 已清零。

该文件明确标记 `diagnostic_only=true`、`formal_acceptance_evidence=false`。运行使用 `analysis_convention`，每个 seed 都因未确认 profile 至少增加1个 unsupported 与1个 approximation，汇总为 unsupported=145、approximation=100；`formal_result_eligible_count=0`、`reexecution_verified_count=0`、`formal_acceptance_passed=false`。这些是诊断运行计数，不覆盖现场 inspector 的 `unsupported_rules=2`、`approximation_count=0`，也不改变 readiness 的 `acceptance_seed_count=0`。

本轮本地验证结果为：full pytest `2024 passed, 1 warning in 830.59s`（唯一 warning 是 `.pytest_cache` WinError5）；compileall exit0；source integrity exit0并扫描125个 Python 文件、117项 finding／audit item（formal source56、test code61）、`defect_count=0`；manifest与诊断JSON解析通过，诊断seed IDs严格为0..99；Git-normalized SHA-256表47个文件条目全部匹配；`git diff --check` exit0。runner status exit0并现场派生 deck160／registered38、global36/158、duel37/159、unsupported2、approximation0、runtime reachable true、mode/cards false、replay true、acceptance0、ready false。runner 的 future-ready 消费／复检／原子输出链已经实现；当前失败关闭来自 live prerequisites 与模块私有 release guard，而不是无条件拒绝占位。因此本节证明 production formal 薄层、现场门禁、诊断执行和 runner 结果路径已经接线并通过本地回归，不证明 Milestone B PASSED，也不是独立审计。旧审计链保持 original `WHOLE_REPO_AUDIT_FAILED`、R1–R5 各自 FAILED、R6 `REMEDIATION_6_REAUDIT_PASSED`、finalization correction verification PASSED；未创建 remediation-7，也未移动旧 audit branch 或 milestone tag。

## 12. MILESTONE_B_AUDIT_REMEDIATION_1/2/3/4/5（PERSISTED PROJECT STATE）

已封存的 Milestone B 审计链为：initial independent audit=FAILED；
R1=`MILESTONE_B_REMEDIATION_1_REAUDIT_FAILED`；
R2=`MILESTONE_B_REMEDIATION_2_REAUDIT_FAILED`；
R3 pre-audit=`MILESTONE_B_REMEDIATION_3_PRE_AUDIT_FAILED`；R4 冻结 target
`3df02b5cfae9af436ba77d8f1c19a7b9959022b1`（parent
`5d970560e306b84af518798e11db12c2a42dfc44`）的 Sol final independent re-audit
=`MILESTONE_B_REMEDIATION_4_FINAL_REAUDIT_FAILED`。R4 仅余
R4-NEW-001/R4-NEW-002 两项 MINOR；R3-NEW-001/002/003 与 DOC-OBS-001
均 CLOSED。

R5 从该固定 R4 target 历史基线开始；R5 已由 Sol final independent re-audit
复审，结论为 `MILESTONE_B_REMEDIATION_5_FINAL_REAUDIT_FAILED`（唯一未关闭项
R4-NEW-002；R4-NEW-001=CLOSED），不写未来 SHA。R5 implementation identity
范围明确加入 `scripts/__init__.py` 及它在当前正式 package import 路径中 eager
执行的 28 项 local-import 闭包。这是 explicit enumerated dependency inventory，
不是自动完整 transitive closure；R6 已由 Sol Ultra targeted independent
re-audit 复审：`MILESTONE_B_REMEDIATION_6_TARGETED_REAUDIT_FAILED`（R4-NEW-002／
R6-NEW-001／R6-NEW-002 OPEN）；R7 候选（`MILESTONE_B_AUDIT_REMEDIATION_7`）
尚未独立复审（`NOT_YET_PERFORMED`），验证结果仅以实际运行记录为准。

【HISTORICAL R4 CANDIDATE FORMATION SNAPSHOT】R4 形成时的
`PRECOMMIT`、`NOT_AUDITED_YET`、`commit=null`、worktree pending 只表达
当时未提交工作树，不表达 persisted current。

【LIVE GIT STATE / runtime-derived policy】branch、HEAD、parent、clean/dirty 与
unmerged 必须由现场 Git 命令派生；本签入文档不将它们硬编码为
`CURRENT LIVE`。

`A committed documentation snapshot must not require knowing the SHA of the commit that contains the snapshot.`

`A precommit Git worktree state must never be labelled persistent CURRENT state.`
【HISTORICAL/AS-OF（R1 PRECOMMIT SNAPSHOT）】开始 HEAD=`ebd656754ed2a528e0d08cd5175b68385fdb8140`；当时工作树尚未提交，`commit=null`、`pending`；独立 Ultra 复审尚未运行：`independent_audit_done=false`、`audit_conclusion=NOT_AUDITED_YET`，不预写当时 reaudit PASSED。

### 12.1 正式单挑调用链

```text
scripts/sgs_formal_runner.py
  -> build_current_status()
     -> _inspect_formal_duel_safely()
        -> scripts/sgs_engine/formal_duel.py::inspect_formal_duel_readiness()
           -> FormalCardRegistry.from_formal_csv()  # 160 CardInstance / 38 keys
           -> _semantic_key_sets()  # global 37/159 vs duel 38/160（MB-B-004 分层）
           -> _load_acceptance_evidence()  # v2 artifact 缓存报告校验（MB-B-001：不是执行凭证）
           -> FormalNoSkillDuelSession(..., analysis_only=True)  # factory probe
  -> run_formal_simulation()
     -> require_formal_simulation_ready()  # 静态 gate（MB-B-001：不依赖缓存 artifact）
     -> run_formal_duel_seed_sweep(0..99)
        -> FormalNoSkillDuelSession(seed, formal_profile, analysis_only=False)
        -> record_reference_production_batch(_game=会话)  # 严格 record
        -> reexecute_production_replay(record)           # strict replay
        -> game.assert_finished_state_invariants()       # MB-M-008
     -> build_formal_acceptance_artifact()  # provenance 绑定 v2
     -> _atomic_write_json()                # simulation_executed=true（执行后才写）
```

### 12.2 作用域与门禁（MB-B-004）

| 项 | 当前值 |
|---|---|
| 牌堆 | 160 实体／38 种类，全部注册 |
| global 完整语义 | `global_all_cards_implemented=false`；37 类／159 实体；方天画戟 global `PARTIAL` |
| duel-scope sufficient | `duel_scope_all_cards_sufficient=true`；38 类／160 实体 |
| formal factory | `mode_runtime_reachable=true`、`mode_implemented=true` |
| replay | `reexecution_replay_supported=true`；严格 record/replay |
| rules | `unsupported_rules=0`（formal duel 上下文） |
| approximation | `approximation_count=0` |
| fixed-seed acceptance | 100/100 自然结束、failures=0、v2 artifact、seeds 0..99、analysis_only=false、max_steps=2000（缓存报告；live 结果由正式 run 现场产生） |
| final gate | `formal_duel_no_skill_ready=true`、`formal_run_ready=true`（静态执行资格） |
| full-core scope | `authoritative_full_game_core=false`、`multi_player_production_proven=false`、`milestone_b_complete=false` |

source integrity 复核结果已记录到 docs/CHECKPOINT_MANIFEST.json 的 source_integrity 字段；checkpoint 的 final_verification 记录 remediation-1 验证证据。历史链保持：original `WHOLE_REPO_AUDIT_FAILED`；R1–R5 对应 `REMEDIATION_*_REAUDIT_FAILED`；R6 `REMEDIATION_6_REAUDIT_PASSED`；finalization correction verification PASSED；不创建 remediation-7，不移动旧 audit branch。
