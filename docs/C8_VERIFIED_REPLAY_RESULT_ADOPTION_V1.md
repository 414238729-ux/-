# C8 已验证 replay result adoption V1

多 seed 原生启动见 `C8_BASELINE_MULTI_SEED_LAUNCHER_V1.md`。下述旧 policy、
latch、proof 继续绑定其历史源码快照；新 generalized checkout 不自动继承
旧 policy 的 current source map，也不把历史 seed0 proof 作为新 seed 输入。

本契约新增明确的 `VERIFIED_RESULT_ADOPTION_AUTHORITY` 第二验收路径。
旧 `verify_full_game_composition_v1` 为 `FRESH_WORKER_AUTHORITY` 路径，源码、
fresh workers、exact comparators、current-only gates 和序列化报告拒绝规则均保留。

生产入口位于 `scripts/sgs_engine/c8_verified_replay_result_adoption_v1.py`。
调用方先从独立可信配置加载 `PinnedAdoptionPolicyV1(expected_sha256=...)`；
该 pin 不能从 envelope、latch 或 proof 自述字段中读取。Policy 精确登记
INNER/TIMED 两行以及全部文件 hash、旧 producer 源码、原 worker verifier
源码、当前完整源码清单、原独立审计和新 current compatibility pair。
不存在 wildcard、任意缓存、缺省信任或失败/不完整结果的采纳。

INNER 和 TIMED 分别绑定 result schema/version/status、natural/seed/cell、
original producer 与 cell execution、worker script/source/environment/profile、
fresh execution evidence identity、comparison contract、原审计和当前 verifier。
Inner 比较合同描述的是原 `_fresh_inner` 和 C6 V1 函数的 exact 源码；不是改写
旧结果的 schema。Timed 历史材料没有 OS PID，因此明确 `NOT_RECORDED`；
它的 execution identity 绑定原命令、源码、环境、起止日志、完成记录和已接受
该次执行的独立审计，不声称事后获得了操作系统进程证明。

新 current latch 是 `C8CurrentReplayAdoptionLatchV1`，其验收域仅限新的
adoption pipeline。B 的不变 contract latch 和 D 的旧 producer latch 不改写，
新 latch 显式记录历史 supersession；原 D/F/G 默认 current gate 仍按原行为拒绝。
新的 adoption implementation/verifier identity 覆盖新增源文件和测试，global
identity 则按既有 `formal_duel` 的实际显式 inventory 重算；另有完整 source fingerprint。
原 G1/G2/G3 snapshot 在新 latch/proof 中明确属于原执行域。

`resign_current_latch_v1` 先完整核验两个 admission envelope 与原证据，再签发
新的 canonical hash-bound latch。审计前 latch 带有 `REQUIRED_BEFORE_CELL_PROOF`。
独立 Grok 审查 source/tests/policy/envelopes/latch 的 exact bytes；audit subject
绑定这些 hash。最终 audit report 的独立 pin 和 subject pin 必须由可信调用方传入。
只有五项判定全部 PASSED/YES，`issue_cell_proof_v1` 才可签发。
这使审计签住既有 latch，而不形成 latch↔audit hash 自引用。

Proof 使用独立 schema `C8VerifiedResultAdoptionCellProofV1` 并嵌入完整 G1
`FullGameResultV1.to_report_dict()`，正式 flags/witness 判定沿用 G1；新 verifier
实时检查全部证据和审核结果后形成内存结果，不通过旧 `from_dict` 恢复 token。
`verify_cell_proof_v1` 必须 fresh 读取独立信任配置，重新核验全部 components，
按相同 contract 派生期望值，再对整份 proof 做 canonical exact 比较。
JSON self-hash 正确本身不能成为 acceptance authority。

本 adoption 不采纳独立 unresolved worker 结果，FG-TIMER-09 保留原 missing witness；
G1 既有 per-cell gate 本就排除此条件性 matrix witness。不得据此声称 matrix gap
已关闭。单个 C8G-FG-000 proof 最多支持 `1/3 PROVISIONAL_AUDIT_PENDING`，
不表示 `C8_FULL_GAME=PASSED`，不自动执行其他 seed。

本次 response-window 修复改变了 E 源码证书，因而当前 driver/profile identity
随正式依赖变化。adoption 的旧结果解析现在在独立固定的原审计源码域中运行
`preflight_composition_v1`，只做只读解析，不调用 natural/inner/timed worker。
新旧 compatibility pair、原源码清单在入口和出口、新验证器清单、原输入文件
hash、解析返回的 exact artifact commitment 都必须匹配。解析失败、超时、
receipt 替换或旧源码漂移均拒绝。当前 fresh-worker/current-only gate 保持原字节。
旧 seed0 execution identity、driver、profile、结果和原 proof 不改写；新 adoption
policy/envelope/latch 明确绑定当前验证器，只属于第二验收路径。
