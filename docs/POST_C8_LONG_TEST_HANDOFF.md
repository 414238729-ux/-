# LONG_TEST_HANDOFF ROUND2：POST_C8_PLAYABLE_RUNTIME_AI_AND_PARALLEL_SIMULATION_V1

交接阶段：`POST_C8_LONG_TEST_ROUND1_REMEDIATION_V1`。

- `ROUND1_FAILURES_REMEDIATED = YES`
- `EXACT_FAILED_SEEDS_TARGETED = PASSED`
- `AFFECTED_PYTEST_SET = PASSED`
- `SHORT_TESTS = PASSED`
- `LONG_TESTS = PENDING`

第一轮长测已实际FAIL，原证据保留；本文件只授权外部执行第二轮，不表示新长测已通过。当前项目任务在本交接就绪后STOP，等待外部结果。外部执行者只测不修，不commit/tag/push、不改pin或重签旧proof，不自动重跑失败组。

## 交接现场与修复证据

- 仓库：`D:\MyGPT\game-analysis-grok-eval-c3`；分支：`codex/post-c8-playable-runtime-ai-parallel-v1`。
- HEAD：`9991abc8091943e7316875734bae2e5967cc6e64`；冻结tag：`c8-timed-8p-deterministic-virtual-time-v1-audited`，未移动。当前实现尚未提交，必须使用本工作树全部实际文件，包括untracked源码/测试。
- AI：`production-heuristic-v1.1`；信息策略：`public-timer-and-context-qa-v1`。本轮修复牌实体/continuation、寒冰技能后快照、C7阶段/方法接线，不重写斗地主信息机制、不靠AI回避罪论。
- `FROZEN_C8_IDENTITY = df90380d241bc8342956db3d3d68405fbef60d86185dcb078c836e00544370fe`。
- `POST_C8_CURRENT_IDENTITY = 5083c90d2f6c4913704edbb88161706cec35d136e8d08fe2637d0d832ce38d18`；固定在独立development-current pin，旧pin/verifier保持原字节。
- 当前完整源码包：`eede731b076384ab6fc50d83d1cbec3fd63766948c50747ec90ebd5d75420825`。
- 精确源码/测试哈希：`docs/post_c8_evidence/round1_remediation_01/short_final_01/after.json` 的 `test_and_source_files`。当前报告/handoff等交付文件哈希另见该修复目录 `DELIVERY_MANIFEST.json`。
- 当前短验收：**121 passed in 125.84s**，pytest PID64176，exit0。原25 FAIL/69 ERROR exact集合：**94 passed**，PID62992，exit0；其中88项原冻结测试在真实子进程PID63076执行，6项在当前开发树执行。最后这两组源码/测试完全相同、前后未变。
- 原9个失败seed均先复现，再修复验证：3局自然终局，6局在原故障点后128个已接受步骤停止（ABORTED）；完整终局验证仍由本轮原矩阵完成。详见 `REMEDIATION_RESULTS.json`、`pytest_failure_mapping.json` 和 `docs/FULL_PYTEST_FAILURE_CLASSIFICATION.md`。
- 第一轮外部根目录：`D:\t\pc8-long-20260908-info01`；54个文件按原SHA归档于 `round1_remediation_01/original_long`。原handoff SHA：`9cc45b9b56b7cd405d40199ea00f5b592edb4d976e0dc6d55ec8c73189f85cdf`，原字节在 `round1_remediation_01/prior`。
- 第一轮full pytest：4847 collected，4529 passed、25 failed、69 errors、224 skipped，exit1。12组生成结果全部semantic_equal=True；斗地主fixed/candidates已PASS且真实AI问答发生。这些成功观察继续有效于原快照，新源码仍需本轮复验。
- 本轮未调用Grok，旧限定快照审查不覆盖修复字节；最终完整字节与真实长测结果的独立审查PENDING。

冻结测试使用 `tests/conftest.py` 的显式限定清单，在短路径副本中逐个执行原nodeid与原测试字节。副本来自固定Git commit，逐blob校验内容；仅对内容完全相同的原文件保留旧raw-byte行尾包装，原verifier继续严格检查。独立测试release使用实际冻结字节并禁止启动historical harness；历史migration/proof只读校验。这不是旧C8历史execution，也不使旧artifact接受future source。完整子进程报告随长测归档，缺报告、内部错误或源核验缺失不能被包装成PASS。

## 一次性环境与前置核验

PowerShell，使用实际已验证的Python 3.12.14环境。下面使用独立新短目录；如果目录已存在，改用新的后缀，不删除或覆盖旧轮次。

```powershell
Set-Location -LiteralPath 'D:\MyGPT\game-analysis-grok-eval-c3'
$py = 'D:\MyGPT\game-analysis-grok-eval\.venv\Scripts\python.exe'
$env:PYTHONHASHSEED = '0'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
& $py -B --version
git -c safe.directory=D:/MyGPT/game-analysis-grok-eval-c3 branch --show-current
git -c safe.directory=D:/MyGPT/game-analysis-grok-eval-c3 rev-parse HEAD
git -c safe.directory=D:/MyGPT/game-analysis-grok-eval-c3 rev-parse 'c8-timed-8p-deterministic-virtual-time-v1-audited^{}'
git -c safe.directory=D:/MyGPT/game-analysis-grok-eval-c3 status --short

@'
import hashlib, json, runpy
from pathlib import Path
from scripts.post_c8_validation import snapshot
old = json.loads(Path("docs/post_c8_evidence/round1_remediation_01/short_final_01/after.json").read_text(encoding="utf-8"))
now = snapshot()
same = old["test_and_source_files"] == now["test_and_source_files"]
print(json.dumps({"source_and_tests_equal": same, "source_sha256": now["source"]["sha256"]}))
assert same, "SOURCE_OR_TEST_DRIFT"
assert now["git"]["head"]["output"] == "9991abc8091943e7316875734bae2e5967cc6e64"
assert now["git"]["frozen_tag_commit"]["output"] == now["git"]["head"]["output"]
assert now["git"]["branch"]["output"] == "codex/post-c8-playable-runtime-ai-parallel-v1"
manifest = json.loads(Path("docs/post_c8_evidence/round1_remediation_01/DELIVERY_MANIFEST.json").read_text(encoding="utf-8"))
for name, expected in manifest["files"].items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name
# frozen fixture 的必需历史输入；只读，不构造替代原件。
bootstrap = runpy.run_path("tests/post_c8_frozen_source.py")
assert hashlib.sha256(bootstrap["HISTORY"].read_bytes()).hexdigest() == bootstrap["HISTORY_SHA256"], "HISTORY_DRIFT"
protected = Path("C:/Users/ASUS/.codex/visualizations/2026/09/07/01a07b7e-837c-7b41-8426-ad6b9ceda5c2/cell-proof-final-independent-audit/PROTECTED_INPUT_MANIFEST.json")
assert hashlib.sha256(protected.read_bytes()).hexdigest() == "b0d520a616008f69a20be641951d5bd4f1179cfe987bde444086fbf479f541d1", "PROTECTED_HISTORY_DRIFT"
from scripts.current_post_c8_implementation_pin import FROZEN_C8_IDENTITY, POST_C8_CURRENT_IMPLEMENTATION_IDENTITY
from scripts.sgs_engine.formal_duel import implementation_identity
assert implementation_identity() == POST_C8_CURRENT_IMPLEMENTATION_IDENTITY != FROZEN_C8_IDENTITY
print("Current delivery files and exact historical fixture inputs verified from actual bytes")
'@ | & $py -B -
if ($LASTEXITCODE -ne 0) { throw '现场不一致，保留现场并回传，停止长测。' }
```

不要因原Git全局ignore文件的只读权限警告改变仓库。若Python版本或哈希不同，报告实际差异；不得reset／clean／restore。

## 长测精确命令

这是一整组第二轮外部长测：当前最终开发树只执行一次full pytest，再保持第一轮相同核心配置的六种模式×固定／候选×seeds0..3的1/4worker对照，约96次实际生产对局运行，含正常交互开局、手气卡和三名生产武将。总耗时未知，可能较长；按授权留给外部模型执行。

```powershell
$longOut = 'D:\t\pc8-long-20260909-r2'
$longBase = 'D:\t\pc8b-r2'
if ((Test-Path -LiteralPath $longOut) -or (Test-Path -LiteralPath $longBase)) {
    throw '本轮短目录已存在，请换新后缀，保留已有结果。'
}
& $py -B -m scripts.post_c8_validation long --out $longOut --basetemp $longBase
$longExit = $LASTEXITCODE
[pscustomobject]@{ launcher_exit_code = $longExit; evidence_directory = $longOut } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $longOut 'launcher_exit.json') -Encoding utf8
```

运行器创建输出目录及临时目录的父目录；若外部沙箱限制`D:\t`写入，按已授权测试用途取得该目录权限，不通过搬移仓库或修改测试规避。

运行器实际执行的主测试命令为：

```powershell
& $py -B -m pytest -q -p no:cacheprovider --basetemp 'D:\t\pc8b-r2' --junitxml 'D:\t\pc8-long-20260909-r2\pytest.xml'
```

随后对`duel`、`2v2`、`doudizhu`、`identity5`、`identity8`、`identity8_heir`分别生成`fixed`与`candidates`配置，执行：

```powershell
# 示例；其余11组由运行器生成独立配置及相同格式命令，写在各组.json记录中。
& $py -B -m scripts.sgs_playable compare-workers --config 'D:\t\pc8-long-20260909-r2\2v2_fixed_config.json' --output 'D:\t\pc8-long-20260909-r2\2v2_fixed_result.json'
```

每组配置固定`control=AI_VS_AI`、`ai_seed=10`、`mulligan=true`、`max_steps=20000`，games=4、seeds=[0,1,2,3]、workers=4；比较函数在同一配置下分别实际执行1与4worker。游戏与AI随机性不耦合。角色池与每座候选数采用明确的自用配置，不声称官方池或客户端全部选将配置已经验收。

不运行封存C8单元的natural／inner／timed原验收命令，不生成或重签旧proof。不另开大规模性能测试、长replay或新武将矩阵。

## 原失败seed必须特别回传

以下全部仍属于原12组×4-seed矩阵，不额外启动一套重复对局。逐项提取single/parallel的game_id、seed、物理座位/武将/身份、终局、steps、原错误是否消失、ERROR/ABORTED计数、信息hash与实际事件计数。原game_id映射见 `round1_remediation_01/REMEDIATION_RESULTS.json`。

| 配置 | seed | 原故障与本轮检查 |
|---|---|---|
| duel_candidates | 1 | 736步丈八材料PROCESSING归属，以及后续虚拟触发技能候选；真实card conservation |
| 2v2_candidates | 1 | 366步寒冰多步弃牌与明哲后的最新合法选择，不能EMPTY_LEGAL_SET |
| identity5_candidates | 1 | 1499步闪/蒺藜后的合法重洗与response continuation |
| identity8_heir_fixed | 0 / 1 / 2 / 3 | 罪论legal-set/apply同阶段、同actor；不能出现已签发合法动作被“只能结束阶段”拒绝 |
| identity8_heir_candidates | 2 | 1196步桃/明哲重洗与dying_rescue continuation |
| identity8_heir_candidates | 3 | 912步end后的spy conversion及既有C7 core接线 |

完整full pytest需包含新 `test_post_c8_round1_remediation.py`、旧continuation negatives、签名合法集/duplicate/stale、当前信息和通信回归。查看XML中冻结nodeid的execution_source属性及真实子报告；不能把旧frozen测试通过说成开发引擎玩法已审计。除主pytest exit外也回传冻结子pytest exit、source_verified及其失败记录。

全部12份生成的`*_config.json`应逐值等于第一轮同名核心配置（含seeds、workers、mode、selection、ai_seed、mulligan、max_steps）。不同则报告配置漂移，不自行解释为可比较。SOURCE_TEST_DRIFT=NONE只在真实before/after一致时成立；RERUN_COUNT与FIXES_APPLIED如实记录，本交接预期单次执行、只读源码。

## 记录、失败与结果口径

本轮修复及信息机制验收项：保留原full pytest及96次生产矩阵，不另加大规模模拟、profiler、长replay或随机覆盖搜索。full pytest包含`test_post_c8_information.py`及新增并行场景测试。特别核对：

1. A在真实trick_response/judgment_wuxie窗口直接生成全场一致的资格观察。初始UNKNOWN，普通PASS不伪造曾有资格，已知可用者PASS不耗牌；使用一张不推断用尽，反无懈层可重观，未知取得牌只令受影响角色失效。读取/评分不刷新隐藏信息。
2. B的保护、救援/桃、借刀和技能问题保持明确语境，YES/NO/NO_RESPONSE公开一致；建议不能确定解释为资源事实。借刀须有此前合法共同知识。过期、跨目标、跨方案、跨反无懈层的回答不复用，禁止通用杀数/桃状态与循环探测。鲍信仅是规则场景，不开放整将。
3. 真人回答正确路由，AI只收自身视图；问答不执行游戏动作、不改变原窗口或deadline。签名、重复/过期、提交成功后异常与回执恢复测试继续通过。2v2原有队友共享不受破坏。
4. 逐局`information_version`、`public_information_sha256`、`public_information_counts`纳入单/多worker实际语义比较。命名南蛮/万箭fixture对照包含完整公共事件；自然矩阵仅声称实际触发的场景，不把零次问答当作问答覆盖。
5. 地主/农民视图及事件不含隐藏手牌、精确无懈数量、实体ID、签名密钥或AI私有理由；相同合法输入不因不可见牌变化而改变选择，不错误屏蔽真实读条公开的新信息。

当前短测再次证明命名窗口的公共观察/问答在spawn下相同；250步自然短样本未触发问答的历史如实保留。第一轮真实长局已发生fixed seed1的5/5/5、seed3的2/2/2，以及candidates seed1/2各2/2/2 question/answer/expired。第二轮仍核对实际事件序列摘要与计数；不要把旧计数写作新结果或硬编码为必须相同。未触发场景报告覆盖缺口，不扩大seed范围。第一轮所有已记录的public_information_sha256配对一致；9对ERROR缺少该字段，缺值不能伪造hash。

运行器会保存：

- `before.json` / `after.json`：解释器、父PID、分支／HEAD／tag、Git状态、完整源码与测试哈希。
- `pytest.json` / `pytest.log` / `pytest.xml`：确切命令、子PID、起止时间、真实exit code、原始测试输出与逐nodeid结果。
- `frozen_test_evidence/`：测试专用request/release、独立子进程process.json（command/PID/exit/duration）、pytest.log、reports.jsonl、source_verified.json。运行器自动从短basetemp归档，临时bt不复制；原始basetemp也保留，不删除。
- 每个`模式_选择.json` / `.log`：比较进程的确切命令、PID、退出码；`*_config.json`和`*_result.json`保存配置及完整报告。
- `execution_summary.json`：各子命令结果与源码／测试是否一致。运行器返回0只有在命令实际全部退出0且源码／测试未变时成立；此值仍不等于独立最终审查通过。
- 每组`*_result.json`含两个实际报告：game_id、seeds、终局及参与者、worker PID／耗时、动作与终局状态摘要、公共信息版本/摘要/事件计数、实际使用策略、统计、直接计算出的`semantic_equal`。

过程中从已写入的`*.json`读取PID及RUNNING／EXITED状态，查看对应`.log`；不要从CPU、日志暂时无输出或字段缺失推断通过。若被中止且没有可确认退出码，保留UNKNOWN／实际运行状态，不填0。不要手写MATCH/PASS，不覆盖失败记录，也不要把配置或预期条件当结果。

工程动作上限20000是ABORTED，异常是ERROR，均不能充当平局或败局。自然完成只含WIN与规则DRAW，胜率分母含自然平局、排除异常和中止；队伍每局一次。斗地主L/F及普通八人内奸奖励另列，不将奖励得分叫作胜率。

若full pytest失败但源码未漂移，运行器仍采集后续模式结果；若源码漂移或用户中断，则停止后续组并保留记录。不要拆命令绕过长测安排或自行扩大seed数量。一个模式失败不应静默丢掉对应game_id。

## 回传内容与后续独立审查

把整个新证据目录保留在本机，并向同一项目任务回传其绝对路径、运行器真实exit code、`execution_summary.json`以及：

1. full pytest实际collected／passed／failed／error／skipped、首个失败定位，以及原94项nodeid本轮结果；主/冻结子进程真实退出码分别回传。
2. 12组请求／自然完成／获胜终局／平局／异常／中止数；每组semantic_equal是否由实际运行得到。
3. 每组worker实际PID及异常game_id、seed、阶段、决策代次与原始错误。
4. 前后源码／测试哈希是否相同；分支、HEAD、旧tag是否保持现场。
5. 斗地主实际公共无懈观察、PASS、使用、cooperation_question/answer/expired计数，以及1/4worker公共信息摘要是否相同；未触发场景如实注明。
6. 上表原9个失败seed的逐项结果、每座武将/身份和可定位错误；本轮12份配置是否与第一轮一致。
7. `RERUN_COUNT`、`FIXES_APPLIED`、真实总退出码和源码漂移状态；保留一切失败，不“清洗”结果。

本任务收到结果后自主修复、定向回归，再用最终字节与真实长测结果完成Grok独立审查。审查必须覆盖生产动作链、模式policy及引擎接线、玩家／事件／AI边界、A/B机制分离与真实接线、公开问题语境和私牌边界、真实策略调用、并行确定性、统计口径和实际支持范围。先前限定快照审查不能替代此最终审查；修复后的字节也不能沿用旧审查结论。

在第二轮真实长测和最终独立审查完成前，只保持本文开头的修复/短测完成状态与`LONG_TESTS=PENDING`，不宣称runtime／AI／simulator已最终验收，不创建audited tag或推送远程。
