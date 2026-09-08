# C8 原生 replay provenance 与采纳

`scripts.c8_native_replay_proof_v1` 是 seed 通用的正式结果 writer 与独立
proof 验证入口。旧 verified-result-adoption V1、旧 worker/current-only
门禁和 seed0 原 proof 不改。新路径采用明确的新 schema，不把旧缺字段
结果伪装成具备原执行 provenance 的结果。

受信调用方在执行前固定完整 config SHA256、自然原件 SHA256、natural
claim/process/terminal 指针、源码 inventory、解释器和精确 cell/seed。
每种 replay 由独立新 OS worker 执行；worker 原生签出 claim、preflight、
完整 MATCH result。父进程独立观察 child PID/creation FILETIME/image，
在 exit=0 后写 result hash-bound receipt。文件只允许首次创建，失败保留。
OS 时间只记录 provenance，不参与游戏、选择、RNG 或比较裁定。

核心比较仍调用未修改的 G3 `_fresh_inner` / `_fresh_timed`；Inner 包含
原 C6 V1 以及完整增量比较，Timed 比较完整原 transcript，再精确比对
ordered sequence、private record identity。没有字段删减或语义归一化。

采纳使用独立固定 policy SHA256，仅登记 INNER/TIMED 两个精确 pair。
验证重新读取固定 worker 源码域、当前 verifier inventory、config、
natural 和 worker 全部 components，绑定 producer、cell execution、
worker process/command/result 和 current verifier；未知组合均拒绝。
新增入口在引擎目录外，仍由完整 verifier source fingerprint 覆盖；
不无依据改变原游戏全局身份或 driver/profile 版本。

Current latch 明确绑定本 cell 的原生结果与 superseded 旧结果指针。
独立 Grok 对 source/tests/policy/envelopes/latch 的冻结 bytes 审计通过后
可签发 proof；proof fresh verifier 全部重验并逐字段 exact readback。
G1 正式 flags/witness 仍由既有 `_formal_report` 派生。其历史实现身份
算法属于 G1 report 的正式定义，新外层 contract/verifier 同时显式绑定。
最终 baseline 晋升还须 proof bytes 的第二次独立审计通过。

不恢复旧 JSON 的 live token；不重跑 natural；不自动启动下一个 seed。
FG-TIMER-09 条件性 matrix witness 不补造，单个 cell proof 不证明全矩阵。
