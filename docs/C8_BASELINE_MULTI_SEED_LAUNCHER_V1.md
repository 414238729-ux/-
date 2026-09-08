# C8 baseline 多 seed 身份与启动入口

`scripts.sgs_engine.c8_baseline_launcher_v1` 为 baseline 0、1、49 提供原生
step-0 identity constructor 和默认 dry-run。G1 原有 0..99 sentinel contract
保留；此 baseline launcher 只接纳正式 baseline registry，严格验证 cell/seed。
首个 baseline cell 已封存，constructor 可以静态验证，launcher/owner 拒绝重跑。

四项 B/D fixed guards 保护共享 source/test 原始字节，不含 cell、seed 或结果。
此次将过期 source pin 迁移到已核验 B 和当前 D 字节；没有删除 guard。
B development 使用历史 development、当前 runtime contract 及 source/test SHA256
构造新的 source-bound 身份，D、E、F、G1/G2/G3 按各自正式依赖材料递推。
A/C/E 的源码和全部游戏规则、选牌策略、timeout policy、profile 保持原行为。
E 的 development 以及 G identities 因依赖材料变化而变化，不等于修改其规则。

共享 implementation identity 包含完整 G3 snapshot；cell execution identity
由 G2 正式 `construct_timed_execution_identity_v1` 派生，natural 同样调用它。
G1 ordinal progress 的 run binding 按原定义等于 cell execution identity。
新增 seed input identity 绑定正式 cell ref 与原生 session binding。
run root 属于 launcher 一次性执行位置，由完整 launch plan 独立绑定。

公开 session ID 通过正式 canonical factory 的可选 `session_id` 参数，按
cell/seed/run label 的正式构造材料派生；签名 secret 仍使用原 fresh 随机生成。
不传参数的所有旧调用保持原行为。重复身份描述只构造 step-0 session/B
绑定，绝不签发 C owner 或清除其 process-local tombstone；真实 owner 才
创建一次完整 B/E/C bundle。G3 对 factory source 的固定 pin 同步迁移，
profile 与 A/C/E 的 source bytes 保持不变。

Release JSON 的独立 SHA256 由可信命令参数给出；JSON 自述不能提供信任。
每次 dry-run/launch/owner 都 fresh 校验完整 Git inventory 的原始 SHA256、
共享 G3 身份、解释器、启动前 hashseed、完整 profile 和外部 harness source seal。
run root 必须为 release 指定的 repo-external run parent/cell/attempt-NNN，
拒绝已有目录、跨 cell 路径、symlink/junction。输入 schema 不接收旧 proof、
terminal counts、winner 或 replay result。终局仅从正式 natural runner 产生。

默认 `--dry-run` 不创建 run root，不启动 gameplay worker。`--launch-natural`
及内部 `--owner` 需要对应 cell/seed 的 exact action 字符串，独立一次性 claim，
Windows DETACHED_PROCESS、NEW_PROCESS_GROUP 和 BREAKAWAY_FROM_JOB；失败不降级。
只使用已封存 report-only lightweight harness，新的 owner 不调用旧 seed0 owner。
每次 natural 结束后停止；cold replay、proof 和下一 seed 均需要后续任务。

历史 seed0 proof、latches、policy、audit 不变，继续只属于其历史 source identity。
本轮在 repo 外保存了原 274 文件的 exact source 快照；旧 adoption policy 的
current source map 可在该快照中静态验证。旧 proof 不属于新 generalized implementation，
无需重新签发或把旧 evidence 转入新执行域。既有 compatibility/adoption policy
仍为具体旧 source/artifact pair；其源清单与新 checkout 不同会 fail closed。

回归仅运行 B/D synthetic、identity/launcher cheap tests；不运行 full pytest、
natural、inner/full timed replay 或 profiler。最终报告登记测试、身份迁移、
dry-run 与本机独立只读审计的 exact bytes。

Response-window 修复后的发布使用新的 FASTPATH_V2 授权字符串，release 与
当前 E/G1/F/G2/G3 源码身份一起重新固定。seed1 的历史 attempt-001 失败不覆盖，
新 metadata 指向 attempt-002；dry-run 不创建目录，不启动 natural worker。
历史 seed0 由显式 compatibility/result-adoption 绑定新验证器；原执行和原 proof
保持历史身份。具体语义与范围见 `C8_RESPONSE_WINDOW_SEMANTICS_V1.md`。
