# 外部旧模拟与审计结果失效声明

> 生效日期：2026-08-01  
> 范围：用户本轮提供、位于 `C:\Users\ASUS\Downloads` 的 2026-07-29／30 近似模拟与行为审计包。  
> 结论：旧胜率整批不得作为当前规则结果；旧 AI 审计整批不得作为真实实现证据。文件可保留用于来源追溯和缺陷研究，但不得进入正式结果集合。

## 1. 失效不是针对单个武将

本次失效依据是生成引擎与审计方法，而不是某一名武将的个别数据错误。因此：

- 不是只废止许攸或鲍信；
- 由同一个外部 worker 生成的三模式、16 将、全部身份／座位结果一并失效；
- 由同一个外部 AI audit 生成的全部微场景统计和 30／30 回归一并失去“实现证据”资格；
- 内部算术一致、CSV 可解析或报告自称“已审计”都不能恢复其规则有效性。

## 2. 生成器状态

| 文件 | 路径 | 状态 | 原因 |
|---|---|---|---|
| `sgs_sim_engine_worker.py` | `C:\Users\ASUS\Downloads\sgs_sim_engine_worker.py` | 外部失效近似器 | 固定武将系数与大量概率／固定收益；只记录手牌和装备整数；不加载正式 Knowledge、160 张实体牌或仓库规则模块；回合上限后启发式强制判胜 |
| `sgs_sim_aggregate.py` | `C:\Users\ASUS\Downloads\sgs_sim_aggregate.py` | 外部旧聚合器 | 只聚合旧 worker pickle，不验证规则、牌堆、武将、unsupported 或 approximation；不能把近似输出升级为正式结果 |
| `sgs_ai_audit_20260729.py` | `C:\Users\ASUS\Downloads\sgs_ai_audit_20260729.py` | 外部自证式审计器 | 不调用正式 AI 或 worker；大量 `chosen = expected`；回归含恒等式／常量真值；2v2 队伍建模也与当前规则不一致 |
| `复现_三国杀16将三模式近似模拟.sh` | `C:\Users\ASUS\Downloads\复现_三国杀16将三模式近似模拟.sh` | 外部旧调用脚本 | 顺序调用 15 个旧 worker 分片和旧 aggregate；固定 `/mnt/data`；不是多进程正式入口 |

这些文件不在 `D:\MyGPT\game-analysis` 内，正式仓库未导入或调用它们。不得复制进 `scripts/`、不得包装成正式入口、不得仅更换报告标题后重新发布。

## 3. 旧胜率结果：整批失效

以下文件统一标记为：

```text
validity = invalid_as_current_rule_results
allowed_use = lineage_and_defect_evidence_only
formal_win_rate = false
```

| 文件 | 路径 | 处置 |
|---|---|---|
| 三模式模拟审计 JSON | `C:\Users\ASUS\Downloads\三国杀_16将三模式实战近似模拟审计_20260729.json` | 保留为旧运行自述；不得用作正式门禁通过证明 |
| 胜率明细 CSV | `C:\Users\ASUS\Downloads\三国杀_16将三模式实战近似胜率明细_20260729.csv` | 全部 180 行不得作为当前胜率引用或聚合 |
| 胜率汇总 CSV | `C:\Users\ASUS\Downloads\三国杀_16将三模式实战近似胜率汇总_20260729.csv` | 全部 16 行不得作为当前武将排名或强度结论 |
| 胜率报告 Markdown | `C:\Users\ASUS\Downloads\三国杀_16将三模式实战近似胜率报告_20260729 .md` | 仅作历史文档；文件名在 `.md` 前含空格 |

主要失效原因：

1. 没有 160 张实体牌及牌实例守恒；
2. 只有手牌数量，没有实体手牌；
3. 技能由固定系数、随机概率或固定收益近似；
4. 无完整卡牌、响应、判定、延时锦囊、属性与铁索状态机；
5. 无正式合法动作枚举和真实 AI；
6. 模式规则不完整；
7. 未实现规则时没有失败关闭；
8. 达到回合上限后用启发式分数强制产生胜者；旧 300,000 局中有 1,622 局以此方式结束；
9. 输出未记录 `unsupported_rules`、`approximation_count`、规则哈希、牌堆哈希、武将数据哈希和确定性测试门禁。

旧 JSON 自身已明确 `full_160_card_engine_loaded=false`，并承认是“规则近似蒙特卡洛，不是客户端完整复刻”。这与正式胜率要求不兼容。

## 4. 旧 AI 行为审计：不得作为实现证据

以下文件统一标记为：

```text
validity = invalid_as_implementation_evidence
allowed_use = audit_method_failure_example_only
real_ai_called = false
```

| 文件 | 路径 | 处置 |
|---|---|---|
| AI 配置与异常 JSON | `C:\Users\ASUS\Downloads\三国杀_三模式AI行为审计配置与异常_20260729.json` | 可保留微场景名称，不得将“零异常”当作真实 AI 结论 |
| AI 行为明细 CSV | `C:\Users\ASUS\Downloads\三国杀_三模式AI行为审计明细_20260729.csv` | 108 行、全部 1.0 只代表同源检查器自洽，不代表合法性／可见性正确 |
| AI 行为审计报告 | `C:\Users\ASUS\Downloads\三国杀_军八2v2斗地主_AI行为审计报告_20260729.md` | 1,500,000 条、100% 通过率不得作为正式 AI 实现证据 |

失效原因：

- checker 自己同时生成 `expected` 和 `chosen`；
- 没有调用正式 AI 决策函数；
- 没有构造统一真实 `GameState`；
- 没有从完整 `enumerate_legal_actions` 集合选择；
- 没有真实牌区、响应、技能、死亡和胜负状态变化；
- 回归案例包含恒等式或固定布尔值；
- 所谓隐藏信息检查由同一测试替身预设，不能证明生产路径没有泄漏。

后续测试若出现以下模式，不得计入正式验收：

```python
chosen = expected
assert chosen == expected
```

真实 AI 测试必须构造生产 `GameState`、调用生产合法动作枚举和评分器，并检查真实选择、状态变化、事件与信息访问记录。

## 5. 后续静态差异审计的有效边界

以下两份文件不是胜率或实现通过证明，可作为历史缺陷线索保留：

| 文件 | 路径 | 可用范围 |
|---|---|---|
| 规则差异清单 JSON | `C:\Users\ASUS\Downloads\三国杀_当前模拟代码与规则差异清单_20260730.json` | 可引用其对外部 worker／AI audit 的静态缺陷条目；不能据此断言当前 Codex 仓库也有同样问题 |
| 一致性总审计 Markdown | `C:\Users\ASUS\Downloads\三国杀_当前模拟代码与实际规则一致性总审计_20260730.md` | 可作外部旧包审计摘要；其生成程序未提供，不能作为可复现自动审计 |

这两份文档已经把旧 300,000 局胜率标为 `invalid_as_current_rule_results`，把旧 1,500,000 条行为审计和 30／30 回归标为 `invalid_as_implementation_evidence`。本项目接受其“旧包不得作为现行证据”的结论，但对正式仓库仍以独立源码审计为准。

### 5.1 `sgs_audit_bundle.zip` 的有效边界

该外部 ZIP 内含 `sgs_audit_harness.py`、`test_sgs_audit.py`、`run_sgs_audit.py`、`sgs_audit_report.json` 和 `sgs_audit_examples.jsonl`。实际源码调用链是 runner 导入 harness、调用同包 unittest，再直接运行 harness 的局部角色／分配／统计函数并写 JSON／JSONL；它不调用本仓库统一核心、完整模式 runner 或真实 AI。

此外，runner 预期同目录存在的 `三国杀牌堆数据.csv` 和 `三国杀卡牌结构化数据.csv` 未包含在 ZIP 中，所以不是自包含复现包。包内报告明确记录 `full_battle_engine_present=false`、`final_strength_results_validated=false`。因此：

```text
validity = local_harness_evidence_only
formal_engine_evidence = false
formal_win_rate_evidence = false
```

包内 23 个 unittest 可以说明该 harness 在当时输入下自洽，不能证明当前正式卡牌、模式、武将、AI 或胜率实现完成。

## 6. 缺失的旧运行材料

当前未找到：

- 15 个 `sgs_partial_{mode}_{chunk}.pkl`；
- 旧运行 stdout／stderr 日志；
- 旧 Python 环境与依赖快照；
- 两份 2026-07-30 静态审计文档的生成程序。

因此不能从聚合 CSV 还原原始逐局记录，也不能完整复现后续静态审计的生成过程。缺少单独 `config.json` **不是**配置缺失：旧配置实际分布在 Shell 环境变量、Python 常量和输出 JSON 中。

同目录还发现：

- `复现_三国杀16将三模式近似模拟 (1).sh`：与明列复现脚本 SHA-256 完全相同的外部重复副本；
- `sgs_audit_bundle.zip`：外部确定性审计包，runner 需要的两份 CSV 未包含在 ZIP 内，不是自包含复现包。

二者均不复制进正式项目。

## 7. 正式结果失败关闭政策

当前已由 `scripts/sgs_engine_gate.py` 和 `scripts/sgs_formal_runner.py` 建立可执行门禁。入口不会调用本声明中的外部脚本；阶段 4 已建立权威核心 foundation，但完整卡牌／阶段循环、模式、生产动作适配器、武将整局实现与 AI 未完成，因此 `run` 仍被拒绝且不会创建结果文件。未来任何结果要标记“正式”，还必须由统一权威核心生成，并在输出中满足：

```text
unsupported_rules = 0
approximation_count = 0
mode_implementation_complete = true
all_participating_generals_complete = true
deterministic_tests_passed = true
deck_loaded = true
deck_count = 160
ruleset_version_known = true
replay_verified = true
```

还必须附带引擎版本、真实 Git 提交（项目恢复 Git 后）、规则／牌堆／武将／策略哈希、seed 范围、局数、进程数和实际测试结果。

未满足门禁的研究运行只能标为：

```text
experimental = true
formal_result = false
```

不得以“近似但规模很大”“内部统计一致”“AI 审计全通过”或“没有报错”为由提升为正式结果。

## 8. 文件保留与删除策略

- 不删除用户 Downloads 中的原始材料；
- 不把外部旧结果上传为自定义 GPT 的正式 Knowledge；
- 不把旧脚本复制进正式仓库；
- 若未来需要研究，可在明确标记的仓库外隔离环境中运行；
- 新正式结果使用新的权威入口与溯源元数据，不覆盖旧文件后冒充同一生成链。

旧材料仍可回答“当时近似器输出了什么”或“旧审计方法为何无效”，但必须同时显示本失效声明，不能脱离来源边界引用数值。
