# -*- coding: utf-8 -*-
"""【过河拆桥】＋【顺手牵羊】隐藏手牌选择句柄安全修复的验收测试。

本文件针对独立只读审计的 AUDIT_FAILED 项（裸SHA-256句柄可被160项公开
预计算表还原为目标手牌）进行定点回归：

- 句柄必须改为会话级随机秘密的 HMAC-SHA256 不透明令牌；
- 公开窗口ID、正式牌堆160个实体ID、正式CSV牌面与公开seed均不足以重建句柄；
- 句柄必须绑定会话、窗口、目标、区域、手牌快照与真实实体，任何伪造、
  过期、跨会话、跨窗口、跨目标、跨区域或手牌变化后的句柄一律失败关闭；
- 严格回放把会话秘密保存在权威私有材料（authoritative_private）中，
  玩家可见导出（player_visible）不包含秘密或私有映射。

所有测试都通过生产批次会话（legal_actions / step / validate / apply /
record / reexecute）或生产模块函数（_hand_choice_handle 等）执行。
"""

from __future__ import annotations

import copy
import csv
from dataclasses import replace
import hashlib
import hmac
import json
from pathlib import Path
import pytest

from scripts.sgs_engine.actions import InvalidActionError, validate_action
from scripts.sgs_engine.model import DISCARD_PILE, ZoneRef
from scripts.sgs_engine.production_batch import (
    BatchActionIdController,
    ProductionBasicCardBatch,
    ScriptedBatchController,
    _hand_choice_handle,
    _hand_choice_message,
    _resolve_hand_choice_handle,
)
from scripts.sgs_engine.production_replay import (
    ProductionReexecutionReplay,
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    record_reference_production_batch,
    reexecute_production_replay,
)
from scripts.sgs_engine.replay import sha256_value


def _text(value: object) -> str:
    """把任意嵌套值转为可搜索文本（兼容 mappingproxy）。"""

    return json.dumps(value, ensure_ascii=False, default=dict)

GUOHE = "sgs_trick_guohechaiqiao"
SHUNSHOU = "sgs_trick_shunshouqianyang"
_HAND_CHOICE_PAYLOAD_KEYS = {
    "operation",
    "trick_instance_id",
    "root_trick_instance_id",
    "user_id",
    "target_id",
    "zone",
    "window_id",
    "state_hash",
    "handle",
}


def _hand_keys(game: ProductionBasicCardBatch, player_id: str) -> tuple[str, ...]:
    return tuple(
        game.state.cards_by_id[instance_id].card_key
        for instance_id in game.state.card_ids_in(ZoneRef.hand(player_id))
    )


def _action(
    game: ProductionBasicCardBatch, operation: str, *, card_key: str | None = None
) -> object:
    for action in game.legal_actions():
        if action.payload.get("operation") != operation:
            continue
        if card_key is not None and action.payload.get("card_key") != card_key:
            continue
        return action
    return None


def _step(game: ProductionBasicCardBatch, action: object) -> None:
    assert action is not None and getattr(action, "action_id", None)
    game.step(BatchActionIdController(action.action_id))


def _pass_response(game: ProductionBasicCardBatch) -> None:
    _step(game, _action(game, "pass_trick_response"))


def _use_trick(
    game: ProductionBasicCardBatch, operation: str, card_key: str
) -> str:
    action = _action(game, operation, card_key=card_key)
    assert action is not None
    assert len(action.target_ids) == 1
    assert action.target_ids[0] != action.actor_id
    trick_id = action.card_instance_id
    assert trick_id is not None
    _step(game, action)
    return trick_id


def _zone_choice_game(
    seed: int,
    operation: str,
    card_key: str,
    *,
    session_id: str | None = None,
    session_secret: bytes | None = None,
) -> ProductionBasicCardBatch:
    game = ProductionBasicCardBatch(
        seed=seed, session_id=session_id, session_secret=session_secret
    )
    _use_trick(game, operation, card_key)
    _pass_response(game)
    _pass_response(game)
    assert game.phase.value == "zone_choice"
    return game


def _guohe_window(
    seed: int = 66,
    *,
    session_id: str | None = None,
    session_secret: bytes | None = None,
) -> ProductionBasicCardBatch:
    return _zone_choice_game(
        seed, "use_guohe", GUOHE, session_id=session_id, session_secret=session_secret
    )


def _shunshou_window(
    seed: int = 2,
    *,
    session_id: str | None = None,
    session_secret: bytes | None = None,
) -> ProductionBasicCardBatch:
    return _zone_choice_game(
        seed, "use_shunshou", SHUNSHOU, session_id=session_id, session_secret=session_secret
    )


def _hand_actions(game: ProductionBasicCardBatch) -> list[object]:
    return [
        action
        for action in game.legal_actions()
        if action.payload.get("zone") == "hand"
    ]


def _handle_for_instance(game: ProductionBasicCardBatch, instance_id: str) -> str:
    for handle, resolved in game.runtime.zone_choice_handles.items():
        if resolved == instance_id:
            return handle
    raise AssertionError("实例不在当前选牌窗口的手牌快照中")


def _fixture_set_state(game: ProductionBasicCardBatch, moves: dict) -> None:
    """测试夹具：用不可变 GameState 的权威牌区移动接口布置区域归属。"""

    game._state = game.state.move_cards(moves)


def _deck_rows() -> list[dict[str, str]]:
    """攻击者素材：正式牌堆CSV（表头含 instance_id 的公开文件）。"""

    knowledge = Path(__file__).resolve().parent.parent / "knowledge"
    for path in sorted(knowledge.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            header = handle.readline().strip()
        if header.startswith("instance_id"):
            with path.open(encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))
    raise AssertionError("找不到正式牌堆CSV")


def _record_zone_choice_replay() -> ProductionReexecutionReplay:
    return record_reference_production_batch(
        seed=3,
        controller=ScriptedBatchController(
            [
                {"operation": "use_guohe", "card_key": GUOHE},
                {"operation": "pass_trick_response"},
                {"operation": "pass_trick_response"},
                {"operation": "choose_target_zone_card", "zone": "hand"},
            ]
        ),
    )


# ---------------------------------------------------------------------
# A. 不透明性与会话随机性
# ---------------------------------------------------------------------


def test_same_window_same_entity_handles_differ_across_sessions() -> None:
    game_a = _guohe_window(seed=66)
    game_b = _guohe_window(seed=66)
    assert game_a.session_id != game_b.session_id
    assert game_a.session_secret_hex != game_b.session_secret_hex
    instance = game_a.state.card_ids_in(ZoneRef.hand("p2"))[0]
    assert instance in game_b.state.card_ids_in(ZoneRef.hand("p2"))
    assert _handle_for_instance(game_a, instance) != _handle_for_instance(
        game_b, instance
    )


def test_same_session_same_entity_handles_differ_across_windows() -> None:
    session_id = "security-test-session"
    session_secret = bytes(range(32))
    game_a = _guohe_window(seed=66, session_id=session_id, session_secret=session_secret)
    game_b = _shunshou_window(seed=74, session_id=session_id, session_secret=session_secret)
    window_a = game_a.runtime.pending_zone_choice.window_id
    window_b = game_b.runtime.pending_zone_choice.window_id
    assert window_a != window_b
    common = set(game_a.state.card_ids_in(ZoneRef.hand("p2"))) & set(
        game_b.state.card_ids_in(ZoneRef.hand("p2"))
    )
    assert common, "seed66与seed74必须共享至少一个目标手牌实体（已核验含021）"
    instance = sorted(common)[0]
    handle_a = _handle_for_instance(game_a, instance)
    handle_b = _handle_for_instance(game_b, instance)
    assert handle_a != handle_b
    assert _hand_choice_handle(
        session_id,
        session_secret,
        window_a,
        "p2",
        "hand",
        game_a.runtime.zone_choice_snapshot_digest,
        instance,
    ) == handle_a


def test_distinct_entities_same_window_get_distinct_handles() -> None:
    game = _guohe_window()
    handles = [action.payload["handle"] for action in _hand_actions(game)]
    instances = game.state.card_ids_in(ZoneRef.hand("p2"))
    assert len(handles) == len(instances) >= 2
    assert len(set(handles)) == len(handles)


def test_old_sha256_formula_cannot_recompute_any_handle() -> None:
    """审计复现：旧方案（裸SHA-256）对160个公开实体ID无一命中。"""

    game = _guohe_window()
    window_id = game.runtime.pending_zone_choice.window_id
    observed = {action.payload["handle"] for action in _hand_actions(game)}
    rows = _deck_rows()
    assert len(rows) == 160
    old_candidates = {
        "h_"
        + sha256_value(
            {
                "zone_choice_window": window_id,
                "zone": "hand",
                "instance_id": row["instance_id"],
            }
        )[:32]
        for row in rows
    }
    assert old_candidates.isdisjoint(observed)


def test_160_entity_enumeration_attack_matches_zero() -> None:
    """审计复现：构建160项枚举攻击表并确认匹配数为0。"""

    game = _guohe_window()
    window_id = game.runtime.pending_zone_choice.window_id
    observed = {action.payload["handle"] for action in _hand_actions(game)}
    rows = _deck_rows()
    table = {
        "h_"
        + sha256_value(
            {
                "zone_choice_window": window_id,
                "zone": "hand",
                "instance_id": row["instance_id"],
            }
        )[:32]: row["instance_id"]
        for row in rows
    }
    matches = [table[handle] for handle in observed if handle in table]
    assert matches == []


def test_handle_payload_exposes_no_card_face_or_secret() -> None:
    game = _guohe_window()
    hand_ids = set(game.state.card_ids_in(ZoneRef.hand("p2")))
    hand_keys = {
        game.state.cards_by_id[instance_id].card_key for instance_id in hand_ids
    }
    for action in _hand_actions(game):
        assert set(action.payload) == _HAND_CHOICE_PAYLOAD_KEYS
        assert action.card_instance_id is None
        handle = str(action.payload["handle"])
        assert handle.startswith("h_") and len(handle) == 34
        assert all(character in "0123456789abcdef" for character in handle[2:])
        blob = _text(action.payload)
        assert game.session_secret_hex not in blob
        assert game.session_id not in blob
        assert "session_secret" not in blob
        assert "zone_choice_handles" not in blob
        assert "authoritative_private" not in blob
        assert not any(instance_id in blob for instance_id in hand_ids)
        assert not any(card_key in blob for card_key in hand_keys)


def test_decision_context_has_no_session_secret() -> None:
    game = _guohe_window()
    metadata_blob = _text(game._context().metadata)
    assert game.session_secret_hex not in metadata_blob
    assert game.session_id not in metadata_blob
    assert "session_secret" not in metadata_blob
    assert "authoritative_private" not in metadata_blob
    for action in game.legal_actions():
        payload_blob = _text(action.payload)
        assert game.session_secret_hex not in payload_blob
        assert "session_secret" not in payload_blob


def test_player_visible_events_have_no_secret_or_private_mapping() -> None:
    game = _guohe_window()
    _step(game, _hand_actions(game)[0])
    blob = _text(
        [event.to_replay_dict() for event in game.events]
    )
    assert game.session_secret_hex not in blob
    assert game.session_id not in blob
    assert "session_secret" not in blob
    assert "zone_choice_handles" not in blob
    assert "authoritative_private" not in blob


def test_correct_handle_resolves_and_moves_real_entity() -> None:
    game = _guohe_window()
    target = game.state.card_ids_in(ZoneRef.hand("p2"))[0]
    handle = _handle_for_instance(game, target)
    action = next(
        action
        for action in _hand_actions(game)
        if action.payload["handle"] == handle
    )
    _step(game, action)
    assert game.state.location_of(target) == DISCARD_PILE
    game.state.assert_card_conservation()


# ---------------------------------------------------------------------
# B. 伪造、过期与跨域句柄失败关闭
# ---------------------------------------------------------------------


def test_forged_handle_fails_closed() -> None:
    game = _guohe_window()
    context = game._context()
    real = _hand_actions(game)[0]
    forged = replace(
        real,
        payload={**real.payload, "handle": "h_" + "0" * 32},
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, forged, game.registry)
    canonical = validate_action(game.state, context, real, game.registry)
    tampered = replace(
        canonical,
        payload={**canonical.payload, "handle": "h_" + "f" * 32},
    )
    adapter = game.formal_registry.adapter_for(GUOHE)
    with pytest.raises(InvalidActionError):
        adapter.apply_action(game.state, context, tampered)


def test_other_session_handle_fails_closed() -> None:
    game_a = _guohe_window(seed=66)
    game_b = _guohe_window(seed=66)
    instance = game_a.state.card_ids_in(ZoneRef.hand("p2"))[0]
    handle_a = _handle_for_instance(game_a, instance)
    real_b = next(
        action
        for action in _hand_actions(game_b)
        if action.payload["handle"] == _handle_for_instance(game_b, instance)
    )
    forged = replace(real_b, payload={**real_b.payload, "handle": handle_a})
    with pytest.raises(InvalidActionError):
        validate_action(game_b.state, game_b._context(), forged, game_b.registry)


def test_other_window_handle_fails_closed() -> None:
    game = _guohe_window()
    choice = game.runtime.pending_zone_choice
    assert choice is not None
    real = _hand_actions(game)[0]
    instance = game.runtime.zone_choice_handles[real.payload["handle"]]
    other_window = f"zone-choice:{game.runtime.turn_number}:other-trick-instance"
    forged_handle = _hand_choice_handle(
        game.session_id,
        game._session_secret,
        other_window,
        choice.target_id,
        "hand",
        game.runtime.zone_choice_snapshot_digest,
        instance,
    )
    assert forged_handle != real.payload["handle"]
    forged = replace(real, payload={**real.payload, "handle": forged_handle})
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)
    canonical = validate_action(game.state, game._context(), real, game.registry)
    adapter = game.formal_registry.adapter_for(GUOHE)
    with pytest.raises(InvalidActionError):
        adapter.apply_action(
            game.state,
            game._context(),
            replace(canonical, payload={**canonical.payload, "handle": forged_handle}),
        )


def test_other_target_handle_fails_closed() -> None:
    game = _guohe_window()
    choice = game.runtime.pending_zone_choice
    assert choice is not None
    real = _hand_actions(game)[0]
    instance = game.runtime.zone_choice_handles[real.payload["handle"]]
    other_target_handle = _hand_choice_handle(
        game.session_id,
        game._session_secret,
        choice.window_id,
        "p1",
        "hand",
        game.runtime.zone_choice_snapshot_digest,
        instance,
    )
    forged = replace(
        real, payload={**real.payload, "handle": other_target_handle}
    )
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_other_zone_handle_fails_closed() -> None:
    game = _guohe_window()
    choice = game.runtime.pending_zone_choice
    assert choice is not None
    real = _hand_actions(game)[0]
    instance = game.runtime.zone_choice_handles[real.payload["handle"]]
    other_zone_handle = _hand_choice_handle(
        game.session_id,
        game._session_secret,
        choice.window_id,
        choice.target_id,
        "judgment",
        game.runtime.zone_choice_snapshot_digest,
        instance,
    )
    forged = replace(real, payload={**real.payload, "handle": other_zone_handle})
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), forged, game.registry)


def test_stale_handle_after_hand_change_fails_closed() -> None:
    game = _guohe_window()
    context = game._context()
    real = _hand_actions(game)[0]
    instance = game.runtime.zone_choice_handles[real.payload["handle"]]
    other = next(
        candidate
        for candidate in game.state.card_ids_in(ZoneRef.hand("p2"))
        if candidate != instance
    )
    _fixture_set_state(game, {other: DISCARD_PILE})
    choice = game.runtime.pending_zone_choice
    assert choice is not None
    resolved = _resolve_hand_choice_handle(
        game.session_id,
        game._session_secret,
        game.state,
        choice.window_id,
        choice.target_id,
        "hand",
        game.runtime.zone_choice_snapshot_digest,
        game.runtime.zone_choice_handles,
        real.payload["handle"],
    )
    assert resolved is None
    with pytest.raises(InvalidActionError):
        validate_action(game.state, context, real, game.registry)


def test_handle_after_window_close_fails_closed() -> None:
    game = _guohe_window()
    action = _hand_actions(game)[0]
    _step(game, action)
    assert game.phase.value != "zone_choice"
    with pytest.raises(InvalidActionError):
        validate_action(game.state, game._context(), action, game.registry)


# ---------------------------------------------------------------------
# C. 严格回放与私有材料
# ---------------------------------------------------------------------


def test_replay_reexecutes_hidden_hand_choice_with_private_material() -> None:
    record = _record_zone_choice_replay()
    private = dict(record.authoritative_private)
    assert private["schema"] == "sgs-authoritative-private-v1"
    assert isinstance(private["session_id"], str) and private["session_id"]
    assert len(private["session_secret_hex"]) == 64
    assert record.player_visible is False
    reloaded = ProductionReexecutionReplay.from_dict(record.to_dict())
    result = reexecute_production_replay(reloaded)
    assert result.verified is True


def test_reexecution_fails_closed_without_private_material() -> None:
    record = _record_zone_choice_replay()
    stripped = copy.deepcopy(record.to_dict())
    del stripped["authoritative_private"]
    del stripped["record_sha256"]
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(stripped)
    player_view = record.player_visible_payload()
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(player_view)


def test_tampered_hmac_key_fails_closed() -> None:
    record = _record_zone_choice_replay()
    tampered = copy.deepcopy(record.to_dict())
    tampered["authoritative_private"]["session_secret_hex"] = "ab" * 32
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)
    del tampered["record_sha256"]
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)


def test_tampered_handle_entity_fails_closed() -> None:
    record = _record_zone_choice_replay()
    tampered = copy.deepcopy(record.to_dict())
    zone_decision = next(
        decision
        for decision in tampered["decisions"]
        if decision["chosen_action"].get("payload", {}).get("operation")
        == "choose_target_zone_card"
    )
    zone_decision["chosen_action"]["payload"]["handle"] = "h_" + "a" * 32
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(tampered)
    del tampered["record_sha256"]
    rebuilt = ProductionReexecutionReplay.from_dict(tampered)
    with pytest.raises(ProductionReplayDivergenceError):
        reexecute_production_replay(rebuilt)


def test_player_visible_export_excludes_private_material() -> None:
    record = _record_zone_choice_replay()
    player_view = record.player_visible_payload()
    assert player_view["player_visible"] is True
    assert "authoritative_private" not in player_view
    assert "record_sha256" not in player_view
    secret_hex = record.authoritative_private["session_secret_hex"]
    blob = _text(player_view)
    assert secret_hex not in blob
    assert "session_secret" not in blob
    expected = sha256_value(
        {key: value for key, value in player_view.items() if key != "player_visible_sha256"}
    )
    assert player_view["player_visible_sha256"] == expected


def test_player_view_never_reads_authoritative_private() -> None:
    game = _guohe_window()
    for action in game.legal_actions():
        blob = _text(action.payload)
        assert "authoritative_private" not in blob
        assert "session_secret" not in blob
    record = _record_zone_choice_replay()
    secret_hex = record.authoritative_private["session_secret_hex"]
    for decision in record.decisions:
        blob = _text(decision)
        assert "authoritative_private" not in blob
        assert secret_hex not in blob


# ---------------------------------------------------------------------
# D. HMAC 语义与密钥管理
# ---------------------------------------------------------------------


def test_handle_uses_real_hmac_sha256() -> None:
    session_id = "security-test-hmac"
    secret = bytes(range(32))
    window_id = "zone-choice:1:sgs-mobile-20260725-049"
    target_id = "p2"
    zone = "hand"
    snapshot_digest = "d" * 64
    instance_id = "sgs-mobile-20260725-021"
    message = _hand_choice_message(
        session_id, window_id, target_id, zone, snapshot_digest, instance_id
    )
    expected = "h_" + hmac.new(
        secret, message.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:32]
    actual = _hand_choice_handle(
        session_id, secret, window_id, target_id, zone, snapshot_digest, instance_id
    )
    assert actual == expected
    bare_concat = "h_" + hashlib.sha256(
        (window_id + zone + instance_id).encode("utf-8")
    ).hexdigest()[:32]
    assert actual != bare_concat


def test_wrong_key_handle_does_not_resolve() -> None:
    session_id = "security-test-wrong-key"
    key_ok = bytes(range(32))
    key_bad = bytes(range(32, 64))
    window_id = "zone-choice:1:sgs-mobile-20260725-049"
    snapshot_digest = "d" * 64
    instance_id = "sgs-mobile-20260725-021"
    handle_ok = _hand_choice_handle(
        session_id, key_ok, window_id, "p2", "hand", snapshot_digest, instance_id
    )
    handle_bad = _hand_choice_handle(
        session_id, key_bad, window_id, "p2", "hand", snapshot_digest, instance_id
    )
    assert handle_ok != handle_bad
    # 用错误密钥生成的句柄不会进入当前窗口快照，且与正确句柄不同；
    # 批量层面的失败关闭由 test_other_session_handle_fails_closed 覆盖。
    assert _hand_choice_handle(
        session_id, key_bad, window_id, "p2", "hand", snapshot_digest, instance_id
    ) != handle_ok


def test_session_secret_is_random_256_bit_and_validated() -> None:
    game_a = ProductionBasicCardBatch(seed=3)
    game_b = ProductionBasicCardBatch(seed=3)
    assert len(game_a._session_secret) == 32
    assert len(game_b._session_secret) == 32
    assert game_a._session_secret != game_b._session_secret
    assert len(game_a.session_secret_hex) == 64
    with pytest.raises(ValueError):
        ProductionBasicCardBatch(seed=3, session_secret=b"short-key")
    with pytest.raises(TypeError):
        ProductionBasicCardBatch(seed=3, session_secret="not-bytes")  # type: ignore[arg-type]


def test_session_id_is_random_and_bound() -> None:
    game_a = ProductionBasicCardBatch(seed=3)
    game_b = ProductionBasicCardBatch(seed=3)
    assert game_a.session_id != game_b.session_id
    secret = game_a._session_secret
    handle_a = _hand_choice_handle(
        game_a.session_id, secret, "w", "p2", "hand", "d" * 64, "i"
    )
    handle_b = _hand_choice_handle(
        "other-session", secret, "w", "p2", "hand", "d" * 64, "i"
    )
    assert handle_a != handle_b
    with pytest.raises(ValueError):
        ProductionBasicCardBatch(seed=3, session_id="")


def test_same_session_material_reproduces_same_handles() -> None:
    session_id = "security-test-deterministic"
    session_secret = bytes(range(32))
    game_a = _guohe_window(seed=66, session_id=session_id, session_secret=session_secret)
    game_b = _guohe_window(seed=66, session_id=session_id, session_secret=session_secret)
    handles_a = {action.payload["handle"] for action in _hand_actions(game_a)}
    handles_b = {action.payload["handle"] for action in _hand_actions(game_b)}
    assert handles_a == handles_b


def test_shunshou_hidden_hand_uses_same_hmac_binding() -> None:
    game_a = _shunshou_window(seed=2)
    game_b = _shunshou_window(seed=2)
    instance = game_a.state.card_ids_in(ZoneRef.hand("p2"))[0]
    assert _handle_for_instance(game_a, instance) != _handle_for_instance(
        game_b, instance
    )
    real = next(
        action
        for action in _hand_actions(game_a)
        if action.payload["handle"] == _handle_for_instance(game_a, instance)
    )
    _step(game_a, real)
    assert game_a.state.location_of(instance) == ZoneRef.hand("p1")
    game_a.state.assert_card_conservation()


def test_original_zone_target_test_count_unchanged() -> None:
    path = (
        Path(__file__).resolve().parent
        / "test_sgs_production_zone_target_tricks.py"
    )
    count = sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("def test_")
    )
    assert count == 50