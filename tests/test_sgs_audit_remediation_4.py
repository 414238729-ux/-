# -*- coding: utf-8 -*-
"""MILESTONE_B_AUDIT_REMEDIATION_4 定向测试。

覆盖：R3-NEW-001（_PendingWeaponChoice 的 execution 字段 inventory、
canonical serializer、逐字段 mutation、damage_amount 行为复现、重复
slash root 分叉 fail-closed）；R3-NEW-002（explicit enumerated formal
simulation dependency inventory：_validation.py 与 sgs_hash_inventory.py
纳入 digest、LF/CRLF 不变、期望集回归、每个登记输入都被 digest）；
R3-NEW-003（assert_trusted_formal_configuration 单一 authority boundary、
低层反射伪造的非 canonical trusted 对象拒绝、canonical factory 正常通过、
replay value roundtrip）；DOC-OBS-001（manifest R3 source_integrity 无
乱码占位、R3 pre-audit 历史分层、R4 PRECOMMIT/NOT_AUDITED_YET）。
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import shutil
from types import MappingProxyType

import pytest

from scripts.sgs_engine.formal_duel import (
    FORMAL_SIMULATION_TRANSITIVE_INPUT_INVENTORY,
    FormalDuelConfiguration,
    FormalDuelConfigurationError,
    FormalDuelReferenceController,
    FormalNoSkillDuelSession,
    TrustedFormalDuelConfiguration,
    _canonical_formal_profile_value,
    _implementation_source_files,
    assert_trusted_formal_configuration,
    implementation_identity,
    run_formal_duel_seed_sweep,
)
from scripts.sgs_engine.model import CharacterMetadata
from scripts.sgs_engine.production_batch import (
    PENDING_WEAPON_CHOICE_EXECUTION_FIELD_INVENTORY,
    ProductionBatchError,
    ProductionPhase,
    _PendingSlash,
    _PendingWeaponChoice,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _fresh_seed_game(seed: int = 3) -> FormalNoSkillDuelSession:
    game = FormalNoSkillDuelSession(
        seed=seed,
        configuration=FormalDuelConfiguration.formal_profile(),
        analysis_only=False,
    )
    controller = FormalDuelReferenceController()
    while not game.is_finished:
        if game.step_count >= 2000:
            break
        game.step(controller)
    assert game.is_finished
    return game


class _FileMutation:
    """对仓库文件做临时字节级修改并在 finally 恢复（测试自包含）。"""

    def __init__(self, relpath: str) -> None:
        self.path = REPOSITORY_ROOT / relpath
        self.original = self.path.read_bytes()

    def __enter__(self) -> "_FileMutation":
        return self

    def __exit__(self, *exc: object) -> None:
        self.path.write_bytes(self.original)

    def write(self, data: bytes) -> None:
        self.path.write_bytes(data)


# ---------------------------------------------------------------------------
# R3-NEW-001：_PendingWeaponChoice execution snapshot/hash 完整覆盖
# ---------------------------------------------------------------------------


def _weapon_choice_runtime(
    game: FormalNoSkillDuelSession,
    choice_overrides: dict[str, object] | None = None,
    slash_overrides: dict[str, object] | None = None,
):
    slash = _PendingSlash(
        attacker_id="p1",
        target_id="p2",
        slash_instance_id="slash-r4-root",
        boosted=False,
    )
    if slash_overrides:
        slash = dataclasses.replace(slash, **slash_overrides)
    choice = _PendingWeaponChoice(
        weapon_key="sgs_weapon_qilingong",
        kind="qilingong_discard_mount",
        attacker_id="p1",
        target_id="p2",
        slash_instance_id="slash-r4-root",
        damage_event_id=None,
        window_id="window-r4",
        damage_amount=1,
        damage_type="普通",
        card_key="sgs_basic_slash",
        card_user="p1",
        source_id="p1",
        kill_credit="p1",
        resolved_reason="slash_damage_resolved",
        death_reason="slash_damage_death",
        rescue_reason="slash_damage_rescued",
        defer_root_finish=False,
        declared_amount=1,
        modifiers=(),
        armor_ignored=False,
        extra_payload=MappingProxyType({"weapon_damage_bonus": 0}),
    )
    if choice_overrides:
        choice = dataclasses.replace(choice, **choice_overrides)
    return dataclasses.replace(
        game.runtime,
        phase=ProductionPhase.WEAPON_AFTER_DAMAGE,
        pending_slash=slash,
        pending_weapon_choice=choice,
    )


def test_pending_weapon_choice_inventory_matches_dataclass_fields() -> None:
    """inventory 必须与 dataclass 字段集合精确一致，防止静默漂移。"""

    assert PENDING_WEAPON_CHOICE_EXECUTION_FIELD_INVENTORY == {
        item.name for item in dataclasses.fields(_PendingWeaponChoice)
    }


def test_audit_value_serializes_entire_inventory() -> None:
    game = _fresh_seed_game(seed=3)
    runtime = _weapon_choice_runtime(game)
    choice_value = runtime._pending_weapon_choice_value()
    assert choice_value is not None
    assert set(choice_value) == PENDING_WEAPON_CHOICE_EXECUTION_FIELD_INVENTORY
    audit = runtime.audit_value()
    assert (
        set(audit["pending_weapon_choice"])
        == PENDING_WEAPON_CHOICE_EXECUTION_FIELD_INVENTORY
    )


def test_pending_weapon_choice_none_serializes_to_none() -> None:
    game = _fresh_seed_game(seed=3)
    assert game.runtime._pending_weapon_choice_value() is None


A_CLASS_MUTATIONS: tuple[tuple[str, dict[str, object]], ...] = (
    ("weapon_key", {"weapon_key": "sgs_weapon_other"}),
    ("kind", {"kind": "other_kind"}),
    ("window_id", {"window_id": "window-r4-other"}),
    ("damage_event_id", {"damage_event_id": "event-r4-1"}),
    ("damage_amount", {"damage_amount": 2}),
    ("damage_type", {"damage_type": "火属性"}),
    ("card_key", {"card_key": "sgs_basic_fire_slash"}),
    ("card_user", {"card_user": "p2"}),
    ("source_id", {"source_id": "p2"}),
    ("kill_credit", {"kill_credit": "p2"}),
    ("resolved_reason", {"resolved_reason": "other_resolved"}),
    ("death_reason", {"death_reason": "other_death"}),
    ("rescue_reason", {"rescue_reason": "other_rescue"}),
    ("defer_root_finish", {"defer_root_finish": True}),
    ("declared_amount", {"declared_amount": 2}),
    ("modifiers", {"modifiers": ("hanbing_prevent",)}),
    ("armor_ignored", {"armor_ignored": True}),
    (
        "extra_payload",
        {"extra_payload": MappingProxyType({"weapon_damage_bonus": 1})},
    ),
)


@pytest.mark.parametrize(
    "label,overrides",
    A_CLASS_MUTATIONS,
    ids=[item[0] for item in A_CLASS_MUTATIONS],
)
def test_each_a_class_field_mutation_changes_execution_hash(
    label: str, overrides: dict[str, object]
) -> None:
    del label
    game = _fresh_seed_game(seed=3)
    game._runtime = _weapon_choice_runtime(game)
    base_hash = game.execution_hash
    game._runtime = _weapon_choice_runtime(game, choice_overrides=overrides)
    assert game.execution_hash != base_hash


C_CLASS_DIVERGENT_MUTATIONS: tuple[tuple[str, dict[str, object]], ...] = (
    ("slash_instance_id", {"slash_instance_id": "slash-r4-other"}),
    ("attacker_id", {"attacker_id": "p2"}),
    ("target_id", {"target_id": "p1"}),
)


@pytest.mark.parametrize(
    "label,overrides",
    C_CLASS_DIVERGENT_MUTATIONS,
    ids=[item[0] for item in C_CLASS_DIVERGENT_MUTATIONS],
)
def test_repeated_slash_root_divergence_fails_closed(
    label: str, overrides: dict[str, object]
) -> None:
    """C 类字段：与 runtime.pending_slash 重复保存的 identity 字段分叉时，
    execution snapshot 必须 fail-closed，而不是静默序列化。"""

    del label
    game = _fresh_seed_game(seed=3)
    game._runtime = _weapon_choice_runtime(game, choice_overrides=overrides)
    with pytest.raises(ProductionBatchError, match="pending_weapon_choice"):
        _ = game.execution_snapshot


def test_damage_amount_behavior_reproduction() -> None:
    """damage_amount=1 与 =2 的 execution hash 不同，且该字段被生产逻辑
    真实消费（窗口关闭后按 choice.damage_amount 执行 HP/DAMAGE）。"""

    game = _fresh_seed_game(seed=3)
    game._runtime = _weapon_choice_runtime(game, choice_overrides={"damage_amount": 1})
    hash_one = game.execution_hash
    game._runtime = _weapon_choice_runtime(game, choice_overrides={"damage_amount": 2})
    hash_two = game.execution_hash
    assert hash_one != hash_two
    source = (
        REPOSITORY_ROOT / "scripts" / "sgs_engine" / "production_batch.py"
    ).read_text(encoding="utf-8")
    assert "amount=choice.damage_amount" in source
    assert "final_amount=choice.damage_amount" in source


# ---------------------------------------------------------------------------
# R3-NEW-002：implementation dependency inventory
# ---------------------------------------------------------------------------


REQUIRED_EXPLICIT_INVENTORY: frozenset[str] = frozenset(
    {
        "scripts/sgs_engine_gate.py",
        "scripts/sgs_formal_runner.py",
        "scripts/sgs_formal_milestone_b_acceptance.py",
        "scripts/deck_data.py",
        "scripts/_validation.py",
        "scripts/sgs_hash_inventory.py",
        "knowledge/三国杀牌堆数据.csv",
        "knowledge/三国杀卡牌结构化数据.csv",
    }
)


def test_inventory_contains_required_explicit_inputs() -> None:
    declared = set(FORMAL_SIMULATION_TRANSITIVE_INPUT_INVENTORY)
    assert REQUIRED_EXPLICIT_INVENTORY <= declared
    assert "scripts/_validation.py" in declared
    assert "scripts/sgs_hash_inventory.py" in declared


def test_inventory_files_exist_unique_and_normalized() -> None:
    files = _implementation_source_files()
    seen: set[str] = set()
    for path in files:
        assert path.is_file(), path
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        assert "\\" not in relative
        assert not relative.startswith(".")
        assert relative not in seen
        seen.add(relative)
    engine_files = {
        item.relative_to(REPOSITORY_ROOT).as_posix()
        for item in (REPOSITORY_ROOT / "scripts" / "sgs_engine").rglob("*.py")
    }
    assert engine_files <= seen


_DECLARED_INPUTS: tuple[str, ...] = tuple(
    path.relative_to(REPOSITORY_ROOT).as_posix()
    for path in _implementation_source_files()
)


@pytest.fixture(scope="module")
def isolated_identity_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """在隔离副本执行全 inventory mutation，绝不临时改写审计仓库。"""

    root = tmp_path_factory.mktemp("r4-identity-root")
    for path in _implementation_source_files():
        relative = path.relative_to(REPOSITORY_ROOT)
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    return root


@pytest.mark.parametrize("relative", _DECLARED_INPUTS, ids=lambda p: p.replace("/", "_"))
def test_each_declared_input_mutation_changes_identity(
    relative: str, isolated_identity_root: Path
) -> None:
    """inventory 中每个登记文件都必须真正进入 digest。"""

    # 隔离复制树避免 Windows 句柄竞争导致真实审计仓库恢复失败。
    before = implementation_identity(isolated_identity_root)
    path = isolated_identity_root / relative
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"\n# remediation-4 digest mutation\n")
        after = implementation_identity(isolated_identity_root)
    finally:
        path.write_bytes(original)
    assert after != before
    assert implementation_identity(isolated_identity_root) == before


def test_identity_unchanged_on_line_ending_change_of_new_dependency() -> None:
    before = implementation_identity()
    with _FileMutation("scripts/_validation.py") as mutation:
        text = mutation.original.decode("utf-8")
        converted = text.replace("\r\n", "\n").replace("\n", "\r\n")
        mutation.write(converted.encode("utf-8"))
        assert implementation_identity() == before
    assert implementation_identity() == before


# ---------------------------------------------------------------------------
# R3-NEW-003：trusted canonical value guard
# ---------------------------------------------------------------------------


def _forge_trusted(**overrides: object) -> TrustedFormalDuelConfiguration:
    """低层反射伪造：type/token 正确，但 profile value 可被任意篡改。"""

    profile = FormalDuelConfiguration.formal_profile()
    forged = TrustedFormalDuelConfiguration.__new__(
        TrustedFormalDuelConfiguration
    )
    for name in (
        "platform",
        "version",
        "source_location",
        "verification_status",
        "deck_applicable",
        "initial_hand_count",
        "player_hp",
        "player_max_hp",
        "first_player_policy",
        "participants",
    ):
        object.__setattr__(forged, name, getattr(profile, name))
    object.__setattr__(forged, "_capability_token", profile._capability_token)
    for name, value in overrides.items():
        object.__setattr__(forged, name, value)
    return forged


FORGED_NONCANONICAL_VARIANTS: tuple[tuple[str, dict[str, object]], ...] = (
    ("hp_9_9", {"player_hp": (9, 9), "player_max_hp": (9, 9)}),
    ("hand_size_wrong", {"initial_hand_count": 7}),
    ("deck_flag_false", {"deck_applicable": False}),
    (
        "player_key_wrong",
        {
            "participants": (
                CharacterMetadata("other", "none", "none"),
                CharacterMetadata("soldier", "none", "none"),
            )
        },
    ),
    ("version_wrong", {"version": "forged-version"}),
    (
        "gender_wrong",
        {
            "participants": (
                CharacterMetadata("soldier", "male", "male"),
                CharacterMetadata("soldier", "none", "none"),
            )
        },
    ),
)


@pytest.mark.parametrize(
    "label,overrides",
    FORGED_NONCANONICAL_VARIANTS,
    ids=[item[0] for item in FORGED_NONCANONICAL_VARIANTS],
)
def test_forged_noncanonical_trusted_rejected(
    label: str, overrides: dict[str, object]
) -> None:
    del label
    forged = _forge_trusted(**overrides)
    assert type(forged) is TrustedFormalDuelConfiguration
    assert forged.trusted_capability_held is True
    with pytest.raises(FormalDuelConfigurationError):
        assert_trusted_formal_configuration(forged)
    with pytest.raises(FormalDuelConfigurationError):
        FormalNoSkillDuelSession(
            seed=0, configuration=forged, analysis_only=False
        )


def test_sweep_rejects_forged_noncanonical_trusted() -> None:
    forged = _forge_trusted(player_hp=(9, 9), player_max_hp=(9, 9))
    with pytest.raises(FormalDuelConfigurationError):
        run_formal_duel_seed_sweep(
            (0,), configuration=forged, analysis_only=False
        )


def test_canonical_trusted_factory_passes_authority_boundary() -> None:
    profile = FormalDuelConfiguration.formal_profile()
    assert assert_trusted_formal_configuration(profile) is None
    game = FormalNoSkillDuelSession(
        seed=0, configuration=profile, analysis_only=False
    )
    assert game.formal_result_eligible is True


def test_replay_recorded_value_roundtrip_via_canonical_factory() -> None:
    """replay 只记录 profile value；value 比较不携带 capability token，
    current canonical factory 重建 trusted 配置后必须通过 authority
    boundary。"""

    profile = FormalDuelConfiguration.formal_profile()
    serialized = json.dumps(profile.to_dict(), ensure_ascii=False)
    assert "capability" not in serialized
    assert "token" not in serialized
    recorded = json.loads(serialized)
    restored = FormalDuelConfiguration.from_canonical_profile_value(recorded)
    assert_trusted_formal_configuration(restored)
    assert restored.to_dict() == _canonical_formal_profile_value()


def test_plain_untrusted_config_rejected_by_authority_boundary() -> None:
    untrusted = FormalDuelConfiguration.from_dict(
        FormalDuelConfiguration.formal_profile().to_dict()
    )
    with pytest.raises(FormalDuelConfigurationError):
        assert_trusted_formal_configuration(untrusted)


# ---------------------------------------------------------------------------
# DOC-OBS-001：manifest 文本与 R3/R4 状态分层
# ---------------------------------------------------------------------------


def _manifest() -> dict[str, object]:
    return json.loads(
        (REPOSITORY_ROOT / "docs" / "CHECKPOINT_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )


def _checkpoints() -> dict[str, dict[str, object]]:
    return {
        str(item.get("checkpoint_id") or item.get("id")): item
        for item in _manifest()["checkpoints"]  # type: ignore[union-attr]
    }


def test_r3_source_integrity_text_has_no_placeholder() -> None:
    r3 = _checkpoints()["MILESTONE_B_AUDIT_REMEDIATION_3"]
    text = str(r3["final_verification"].get("source_integrity", ""))
    assert "?" not in text
    assert "defect_count=0" in text


def test_r3_pre_audit_history_recorded_not_final_reaudit() -> None:
    r3 = _checkpoints()["MILESTONE_B_AUDIT_REMEDIATION_3"]
    pre = r3.get("pre_audit", {})
    assert isinstance(pre, dict)
    assert pre.get("conclusion") == "MILESTONE_B_REMEDIATION_3_PRE_AUDIT_FAILED"
    assert r3["audit_conclusion"] == "NO_FINAL_SOL_INDEPENDENT_REAUDIT_PERFORMED"
    assert r3["independent_audit_done"] is False


def test_r4_precommit_is_historical_and_final_reaudit_failed() -> None:
    r4 = _checkpoints()["MILESTONE_B_AUDIT_REMEDIATION_4"]
    assert r4["commit"] == "3df02b5cfae9af436ba77d8f1c19a7b9959022b1"
    assert r4["audit_conclusion"] == "MILESTONE_B_REMEDIATION_4_FINAL_REAUDIT_FAILED"
    assert r4["independent_audit_done"] is True
    development = _manifest()["git"]["current_milestone_b_development"]
    snapshot = development["historical_candidate_formation_snapshots"]["remediation_4"]
    assert "HISTORICAL" in snapshot["layer"]
    assert snapshot["worktree_state_at_formation"] == "PRECOMMIT"
    assert snapshot["independent_reaudit_status_at_formation"] == "NOT_AUDITED_YET"
    text = json.dumps(_manifest(), ensure_ascii=False)
    assert "MILESTONE_B_AUDIT_REMEDIATION_4_REAUDIT_PASSED" not in text
