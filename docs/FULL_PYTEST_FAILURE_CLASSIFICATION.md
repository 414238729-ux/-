# FULL_PYTEST_FAILURE_CLASSIFICATION

状态：根因分类与定向修复已完成；原 25 FAIL / 69 ERROR 的 exact nodeids 已实际得到 **94 passed**。第一轮原始 FAIL 不改写；该修复轮结束时第二轮 full pytest 尚 PENDING；现第二轮实际 4639 passed / 224 skipped、0 failed/errors，原94项均PASS，见 `POST_C8_LONG_TEST_ROUND2_VERIFICATION.json`。

原结果：4847 项，4529 passed / 25 failed / 69 errors / 224 skipped，exit 1。原 54 个文件已逐字节归档，见 `post_c8_evidence/round1_remediation_01/original_long` 及 `ORIGINAL_SHA256.json`。当前修复前源码/测试与长测 before/after 一致。

| 根因组 | FAIL / ERROR | 根因 | 层次 | 性质 | 本轮修复 |
|---|---:|---|---|---|---|
| CURRENT_PIN | 2 / 0 | 当前开发 identity 被误要求等于冻结 C8 pin | 测试/开发 identity | stale/frozen-compat | 新增独立 POST_C8 current pin，保留冻结 pin 与其精确来源 |
| C8_G3 | 5 / 15 | 冻结 G3 serializer/shared source 校验使用当前开发依赖 | 测试 fixture/冻结 source 边界 | stale/frozen-compat | 冻结验证测试使用精确冻结依赖；当前源被旧 verifier 拒绝的 negative 保留 |
| C8_RELEASE_ENV | 1 / 12 | 普通 full pytest 未提供外部 release/history 环境变量 | 测试 fixture | missing fixture | 提供仅测试用、按真实冻结字节生成的 release fixture；历史 proof 校验读取原件，不重签 |
| C8_F | 1 / 42 | 冻结 C8-F audited production_batch hash 与当前开发源码不同 | 测试 fixture/冻结 source 边界 | stale/frozen-compat | 为冻结测试提供经固定 commit 校验的完整 frozen-source fixture；不放宽 verifier |
| C8_ORDER | 12 / 0 | 已固定的 execution-order certificate 拒绝当前 production_batch bytes | 测试 fixture/冻结 source 边界 | stale/frozen-compat | 冻结 certificate 测试绑定精确冻结源；开发引擎使用本阶段测试验证 |
| KNOWLEDGE_INDEX | 2 / 0 | 新增独立 AI 信息规则未登记唯一正式资料清单 | 资料 manifest/测试 fixture | stale inventory | 登记独立正式资料并保持唯一副本校验 |
| INFO_DOC_ASSERT | 2 / 0 | 旧规则文字断言与用户已确认的公开读条/场景问答定义不同 | 规则语义测试 | stale semantics | 改验当前 A/B 分离及公开边界，不恢复旧私密信号或共享杀数 |

69 项 ERROR 来自 G3 字节边界（15）、独立 release 环境缺失（12）和 F 字节边界（42），不是 69 个独立玩法缺陷。release 环境缺失是独立根因，不能误写成 G3 初始化的级联。实际对局故障另按 A/B/C/D/E 处理；本表不把字节兼容失败说成玩法通过。

## 原 nodeid 与逐项映射

机器可读 exact mapping：`post_c8_evidence/round1_remediation_01/pytest_failure_mapping.json`。每行保留 old outcome、nodeid、root cause、fix、fresh nodeid/result、实际日志与 XML。

最新执行：`affected_04/pytest.xml`、`pytest.log`、`pytest.json`，父 pytest PID **62992**，exit **0**，24.849 秒；前后源码及测试一致。88 项冻结合约测试由真实子 pytest 执行（PID **63076**，exit **0**，22.794 秒），6 项当前身份/规则断言在开发树执行。父测试转发实际 setup/call/teardown 报告；不跳过原断言、不手工生成 PASS。94 项不等于本轮 full pytest。

冻结边界实现位于 `tests/conftest.py` 与 `tests/post_c8_frozen_source.py`：限定旧 C8 模块/函数清单；从固定 commit 建立独立短路径源码副本，逐文件核对 Git blob、原测试字节和 frozen implementation identity，在全新进程首次导入。Git 保存的 LF 与旧 raw-byte pins 的混合行尾分开处理：仅当当前文件归一行尾后完全等于固定 blob 时保留其原始行尾；开发内容绝不进入冻结树，旧 raw-byte verifier 继续严格核验。副本的原始 SHA 清单及测试后核验保存到 `frozen_test_evidence/source_verified.json`。原仓库的 refs、index、源码、proof 均不被该 fixture 改写。

仅测试 release 指向实际冻结文件及一个拒绝执行的 harness；历史 migration/proof 仍按原 SHA 只读验证。它不是新生产 release，也不是重签或重跑历史验收。当前生产源码若交给原 frozen verifier 仍被拒绝，见 `test_post_c8_round1_remediation.py::test_frozen_verifier_rejects_current_development_bytes_and_pin_is_separate`。两个 current identity 测试使用独立 `current_post_c8_implementation_pin.py`；所有旧 pin、证书及 verifier 字节均未修改。

本轮中间失败也保留：`affected_01` 是临时 Git alternates 行尾写入错误，`affected_02` 是 Git LF 与旧 raw-byte 包装不一致；修复只涉及 fixture。`affected_03` 已 94 passed；随后加强不完整子测试报告的拒绝与长测证据归档，`affected_04` 再次 94 passed。没有把级联错误改记为独立玩法缺陷。

### C8_G3

```text
ERROR tests/test_c8_baseline_launcher_v1.py::test_constructor_valid_and_deterministic[0]
ERROR tests/test_c8_baseline_launcher_v1.py::test_constructor_valid_and_deterministic[1]
ERROR tests/test_c8_baseline_launcher_v1.py::test_constructor_valid_and_deterministic[49]
ERROR tests/test_c8_baseline_launcher_v1.py::test_wrong_shared_or_cell_hash_rejected[shared_implementation_identity]
ERROR tests/test_c8_baseline_launcher_v1.py::test_wrong_shared_or_cell_hash_rejected[cell_execution_identity]
ERROR tests/test_c8_baseline_launcher_v1.py::test_wrong_shared_or_cell_hash_rejected[run_binding_identity]
ERROR tests/test_c8_baseline_launcher_v1.py::test_wrong_shared_or_cell_hash_rejected[seed_specific_input_identity]
ERROR tests/test_c8_baseline_launcher_v1.py::test_wrong_shared_or_cell_hash_rejected[session_binding_identity]
ERROR tests/test_c8_baseline_launcher_v1.py::test_wrong_shared_or_cell_hash_rejected[global_source_identity]
ERROR tests/test_c8_baseline_launcher_v1.py::test_wrong_shared_or_cell_hash_rejected[controller_instance_identity]
ERROR tests/test_c8_baseline_launcher_v1.py::test_shared_and_seed_specific_definition
ERROR tests/test_c8_baseline_launcher_v1.py::test_formal_formula_preserved
ERROR tests/test_c8_baseline_launcher_v1.py::test_step_zero_live_binding_matches_description[0]
ERROR tests/test_c8_baseline_launcher_v1.py::test_step_zero_live_binding_matches_description[1]
ERROR tests/test_c8_baseline_launcher_v1.py::test_step_zero_live_binding_matches_description[49]
FAILED tests/test_c8_baseline_launcher_v1.py::test_four_shared_guards_remain_strict[c8_b_source]
FAILED tests/test_c8_baseline_launcher_v1.py::test_four_shared_guards_remain_strict[c8_b_test]
FAILED tests/test_c8_baseline_launcher_v1.py::test_four_shared_guards_remain_strict[c8_d_source]
FAILED tests/test_c8_baseline_launcher_v1.py::test_four_shared_guards_remain_strict[c8_d_test]
FAILED tests/test_c8_baseline_launcher_v1.py::test_description_does_not_consume_controller_owner_registry
```

### C8_RELEASE_ENV

```text
ERROR tests/test_c8_baseline_launcher_v1.py::test_launch_dry_run_no_terminal_or_old_proof[1]
ERROR tests/test_c8_baseline_launcher_v1.py::test_launch_dry_run_no_terminal_or_old_proof[49]
ERROR tests/test_c8_baseline_launcher_v1.py::test_other_cell_root_and_seed0_root_rejected[1]
ERROR tests/test_c8_baseline_launcher_v1.py::test_other_cell_root_and_seed0_root_rejected[49]
ERROR tests/test_c8_baseline_launcher_v1.py::test_seed0_proof_or_identity_cannot_be_injected_into_launcher[old_cell_proof]
ERROR tests/test_c8_baseline_launcher_v1.py::test_seed0_proof_or_identity_cannot_be_injected_into_launcher[terminal]
ERROR tests/test_c8_baseline_launcher_v1.py::test_seed0_proof_or_identity_cannot_be_injected_into_launcher[winner]
ERROR tests/test_c8_baseline_launcher_v1.py::test_seed0_proof_or_identity_cannot_be_injected_into_launcher[accepted_steps]
ERROR tests/test_c8_baseline_launcher_v1.py::test_seed0_proof_or_identity_cannot_be_injected_into_launcher[identities]
ERROR tests/test_c8_baseline_launcher_v1.py::test_seed0_sealed_launcher_rejected
ERROR tests/test_c8_baseline_launcher_v1.py::test_release_wrong_independent_pin_rejected
ERROR tests/test_c8_baseline_launcher_v1.py::test_response_remediated_release_requires_fresh_v2_authority
FAILED tests/test_c8_baseline_launcher_v1.py::test_seed0_historical_source_and_proof_preserved
```

### C8_F

```text
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_trace_a_is_real_bounded_multiwindow_interleaved_turn_trace
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_window_refresh_close_and_event_chain_are_continuous
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_stale_prior_window_context_and_action_evidence_are_rejected_cross_turn
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_public_trace_has_no_private_payload_keys
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_strict_json_round_trip_and_fresh_rerun_match
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_duplicate_json_key_is_rejected
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_required_unknown_and_type_drift_fail_closed[missing-required]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_required_unknown_and_type_drift_fail_closed[type-drift]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_required_unknown_and_type_drift_fail_closed[bool-version-drift]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_required_unknown_and_type_drift_fail_closed[bool-seed-drift]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_required_unknown_and_type_drift_fail_closed[int-full-game-drift]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_required_unknown_and_type_drift_fail_closed[unknown-field]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_required_unknown_and_type_drift_fail_closed[serialized-passed]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_stored_trace_reorder_duplicate_delete_fail_closed[reorder]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_stored_trace_reorder_duplicate_delete_fail_closed[duplicate]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_stored_trace_reorder_duplicate_delete_fail_closed[delete]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_sibling_trace_splice_fails_closed_after_outer_rehash
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_wrong_seed_session_mode_current_or_e_identity_fails_closed[seed]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_wrong_seed_session_mode_current_or_e_identity_fails_closed[session]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_wrong_seed_session_mode_current_or_e_identity_fails_closed[mode]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_wrong_seed_session_mode_current_or_e_identity_fails_closed[current-implementation]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_wrong_seed_session_mode_current_or_e_identity_fails_closed[e-adapter]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_stale_context_carried_into_later_turn_fails_closed
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_on_time_evidence_at_exact_deadline_fails_closed
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_timeout_evidence_before_deadline_fails_closed
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_same_context_deadline_refresh_tamper_fails_closed
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_nested_driver_policy_bool_int_alias_fails_closed
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_nested_proposal_count_bool_int_alias_fails_closed
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_public_proposal_order_tamper_fails_closed
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_timeout_receipt_controller_result_mismatch_fails_closed
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_wrong_actor_turn_phase_binding_fails_closed_after_rehash[phase]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_wrong_actor_turn_phase_binding_fails_closed_after_rehash[turn]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_wrong_actor_turn_phase_binding_fails_closed_after_rehash[actor]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_private_payload_injection_fails_before_outer_hash_authority
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_bounded_limits_or_full_game_terminal_claim_tamper_fails_closed[max_bounded_production_steps-4000]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_bounded_limits_or_full_game_terminal_claim_tamper_fails_closed[max_windows-800]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_bounded_limits_or_full_game_terminal_claim_tamper_fails_closed[bounded_limit_reached-True]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_bounded_limits_or_full_game_terminal_claim_tamper_fails_closed[full_game-True]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_bounded_limits_or_full_game_terminal_claim_tamper_fails_closed[formal_matrix-True]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_bounded_limits_or_full_game_terminal_claim_tamper_fails_closed[terminal_claimed-True]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_bounded_limits_or_full_game_terminal_claim_tamper_fails_closed[production_session_finished-True]
ERROR tests/test_c8_bounded_timed_8p_trace_v1.py::test_deep_tamper_with_recomputed_nonsecret_hashes_still_fails_semantics
FAILED tests/test_c8_bounded_timed_8p_trace_v1.py::test_frozen_scope_and_fresh_a_e_dependency_identity
```

### CURRENT_PIN

```text
FAILED tests/test_authoritative_skill_runtime_v1.py::test_implementation_identity_matches_pin
FAILED tests/test_post_b_c1_precommit_test_state_closure.py::test_frozen_r8_artifact_identity_differs_from_c1_current_identity
```

### C8_ORDER

```text
FAILED tests/test_c8_timed_8p_full_game_runner_v1.py::test_step1362_g1_non_decline_eligibility_and_profile_migration
FAILED tests/test_c8_timed_8p_full_game_runner_v1.py::test_w592_certificate_constructs_new_driver_and_rejects_old_profile
FAILED tests/test_c8_timed_8p_full_game_runner_v1.py::test_v3_gate_two_fresh_processes_agree_on_public_order
FAILED tests/test_c8_timed_8p_full_game_runner_v1.py::test_v3_gate_diagnostic_50_rows_atomic_private_separation_and_no_resume
FAILED tests/test_c8_timed_8p_full_game_runner_v1.py::test_v3_gate_io_retries_exact_bytes_once_and_does_not_advance_gameplay
FAILED tests/test_c8_timed_8p_full_game_runner_v1.py::test_v3_gate_diagnostic_snapshot_strict_rehashed_envelope[version-True]
FAILED tests/test_c8_timed_8p_full_game_runner_v1.py::test_v3_gate_diagnostic_snapshot_strict_rehashed_envelope[last_accepted_step-True]
FAILED tests/test_c8_timed_8p_full_game_runner_v1.py::test_v3_gate_diagnostic_snapshot_strict_rehashed_envelope[gameplay_authority-True]
FAILED tests/test_c8_timed_8p_full_game_runner_v1.py::test_v3_gate_diagnostic_snapshot_strict_rehashed_envelope[resume_capability-LIVE]
FAILED tests/test_c8_timed_8p_full_game_runner_v1.py::test_v3_gate_diagnostic_snapshot_strict_rehashed_envelope[payload-value4]
FAILED tests/test_c8_timed_8p_full_game_runner_v1.py::test_v3_gate_failed_accepted_evidence_tail_keeps_unknown_metrics_explicit
FAILED tests/test_c8_timed_8p_full_game_runner_v1.py::test_v3_gate_private_write_before_pointer_and_unwritable_tail_is_truthful
```

### KNOWLEDGE_INDEX

```text
FAILED tests/test_custom_gpt_upload_manifest.py::test_knowledge_root_has_one_unique_formal_copy_per_manifest_entry
FAILED tests/test_sgs_second_increment_attachment_merge.py::test_only_one_formal_file_exists_for_each_sgs_knowledge_kind
```

### INFO_DOC_ASSERT

```text
FAILED tests/test_sgs_comprehensive_strategy_docs.py::test_mode_visibility_and_team_rescue_boundaries_are_explicit
FAILED tests/test_sgs_comprehensive_strategy_docs.py::test_nullification_timer_knowledge_is_dynamic_and_limited
```

