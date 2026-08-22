# -*- coding: utf-8 -*-
"""POST-B C5：正式身份严格回放与 20 seed sweep。

Replay exit：三种身份胜利必须 authoritative record/reexecute。
identity_draw_deck_exhausted 的 production semantics 仍属正式 runtime，
但 canonical 初始状态自然到达该终局的可达性冻结为
C5_CANONICAL_DRAW_REACHABILITY_UNRESOLVED；不得写成 proven unreachable，
也不得用夹具/预突变冒充 authoritative draw replay。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Sequence

import pytest

from scripts.sgs_engine.actions import LegalAction, UnsupportedRuleError
from scripts.sgs_engine.mode_identity import (
    FORMAL_NO_SKILL_IDENTITY_5P_MODE,
    FormalIdentityConfiguration,
    FormalIdentitySession,
)
from scripts.sgs_engine.production_replay import (
    SUPPORTED_REPLAY_MODES,
    ProductionReexecutionReplay,
    ProductionReplayDivergenceError,
    ProductionReplayFormatError,
    record_reference_formal_identity,
    record_reference_production_batch,
    reexecute_production_replay,
)

C5_CANONICAL_DRAW_REACHABILITY_STATUS = (
    "C5_CANONICAL_DRAW_REACHABILITY_UNRESOLVED"
)


def _deck_exhaustion_helpers() -> Any:
    """Load sibling C5 deck-exhaustion helpers without `tests.` package import.

    Full-suite pytest does not register ``tests`` as an importable package;
    load the helper file by path so live draw coverage stays available.
    """

    path = Path(__file__).with_name("test_post_b_c5_identity_deck_exhaustion.py")
    spec = importlib.util.spec_from_file_location(
        "_c5_identity_deck_exhaustion_helpers", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载C5牌堆耗尽测试辅助模块：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _PacifistController:
    strategy_version = "c5-pacifist-controller.v1"

    def choose(
        self, legal_actions: Sequence[LegalAction], context: Any
    ) -> LegalAction:
        operations = [str(action.payload.get("operation", "")) for action in legal_actions]
        priority_order = (
            "proceed_prepare",
            "proceed_judgment",
            "proceed_draw",
            "heal_self",
            "end_play_phase",
            "discard_phase_submit",
            "select_discard_card",
            "end_turn",
            "pass_trick_response",
            "pass_nanman_slash",
            "pass_wanjian_jink",
            "pass_slash_response",
            "pass_rescue",
            "pass_judgment_wuxie",
        )
        for wanted in priority_order:
            if wanted in operations:
                return next(
                    action
                    for action in legal_actions
                    if action.payload.get("operation") == wanted
                )
        raise AssertionError(
            f"阶段{getattr(context, 'phase', '')!r}没有可脚本化操作：{operations}"
        )


def test_supported_replay_modes_include_identity() -> None:
    assert FORMAL_NO_SKILL_IDENTITY_5P_MODE in SUPPORTED_REPLAY_MODES


def _assert_identity_record(record: ProductionReexecutionReplay) -> None:
    assert record.header["mode_id"] == FORMAL_NO_SKILL_IDENTITY_5P_MODE
    config = record.header["initial_configuration"]
    assert tuple(config["physical_player_ids"]) == ("p1", "p2", "p3", "p4", "p5")
    identities = dict(config["identities"])
    assert len(identities) == 5
    assert list(identities.values()).count("lord") == 1
    assert list(identities.values()).count("loyalist") == 1
    assert list(identities.values()).count("rebel") == 2
    assert list(identities.values()).count("spy") == 1
    lord = config["lord_player_id"]
    assert identities[lord] == "lord"
    numbered = tuple(config["numbered_player_order"])
    physical = tuple(config["physical_player_ids"])
    lord_index = physical.index(lord)
    assert numbered == physical[lord_index:] + physical[:lord_index]
    rng = record.random_consumptions
    assert rng[0]["method"] == "shuffle"
    assert list(rng[0]["arguments"]["before"]) == [
        "lord",
        "loyalist",
        "rebel",
        "rebel",
        "spy",
    ]
    assert rng[1]["method"] == "shuffle"


def test_identity_victory_replay_roundtrip() -> None:
    record = record_reference_formal_identity(
        0,
        configuration=FormalIdentityConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=8000,
    )
    _assert_identity_record(record)
    assert record.header["formal_result"] is True
    assert record.outcome["winner_id"] in (
        "lord_and_loyalists",
        "rebels",
        "spy",
    )
    assert record.outcome["finish_reason"] == "identity_victory"
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id == record.outcome["winner_id"]


@pytest.mark.parametrize(
    ("seed", "expected_winner"),
    (
        pytest.param(0, "lord_and_loyalists", id="lord_and_loyalists"),
        pytest.param(1, "rebels", id="rebels"),
        pytest.param(4, "spy", id="spy"),
    ),
)
def test_identity_victory_token_strict_replay(
    seed: int, expected_winner: str
) -> None:
    """三种身份终局 token 各自独立：正式会话 record + 严格 reexecute。"""

    record = record_reference_formal_identity(
        seed,
        configuration=FormalIdentityConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=8000,
    )
    _assert_identity_record(record)
    assert record.header["formal_result"] is True
    assert record.header["fixture_applied"] is False
    assert record.header["initial_configuration"]["analysis_only"] is False
    assert record.outcome["winner_id"] == expected_winner
    assert record.outcome["finish_reason"] == "identity_victory"
    result = reexecute_production_replay(record)
    assert result.verified is True
    assert result.winner_id == expected_winner


def test_canonical_draw_reachability_status_is_unresolved() -> None:
    """canonical 自然平局可达性未闭合；禁止写成 proven unreachable。"""

    assert (
        C5_CANONICAL_DRAW_REACHABILITY_STATUS
        == "C5_CANONICAL_DRAW_REACHABILITY_UNRESOLVED"
    )
    assert C5_CANONICAL_DRAW_REACHABILITY_STATUS not in {
        "C5_DRAW_PROVEN_UNREACHABLE",
        "N/A",
        "mathematically impossible",
        "proven unreachable",
    }


def test_identity_draw_replay_roundtrip() -> None:
    """Premutated live 确定性路径，不是 authoritative formal draw replay。

    同 seed 两条会话在同一生产 step 上形成 identity_draw_deck_exhausted。
    该路径先把牌移出牌堆/弃牌堆，不能替代
    record_reference_formal_identity 的 canonical strict reexecution。
    canonical formal draw reachability =
    C5_CANONICAL_DRAW_REACHABILITY_UNRESOLVED。
    """
    from scripts.sgs_engine.model import DRAW_PILE, DISCARD_PILE, ZoneRef

    helpers = _deck_exhaustion_helpers()
    _enter_draw_setup = helpers._enter_draw_setup
    _enter_play = helpers._enter_play
    _park_away = helpers._park_away
    _require_op = helpers._require_op
    _session = helpers._session
    _step = helpers._step

    def _drive(seed: int) -> FormalIdentitySession:
        game = _session(seed)
        _enter_play(game)
        _enter_draw_setup(game)
        drawer = game.current_player_id
        holder = next(pid for pid in game.player_ids if pid != drawer)
        remaining = list(game.state.card_ids_in(DRAW_PILE))
        _park_away(game, remaining[1:], holder)
        _park_away(game, list(game.state.card_ids_in(DISCARD_PILE)), holder)
        _step(game, _require_op(game, "proceed_draw"))
        return game

    first = _drive(18)
    second = _drive(18)
    assert first.runtime.game_over_reason == "identity_draw_deck_exhausted"
    assert second.runtime.game_over_reason == "identity_draw_deck_exhausted"
    assert first.winner_id is None and second.winner_id is None
    assert [event.to_replay_dict() for event in first.events] == [
        event.to_replay_dict() for event in second.events
    ]
    assert [call.to_dict() for call in first.rng_calls] == [
        call.to_dict() for call in second.rng_calls
    ]


def test_premutated_identity_draw_cannot_authoritative_reexecute() -> None:
    """夹具式耗尽可以走生产 step，但不能生成可严格重执行的 formal draw 记录。

    把牌移出牌堆/弃牌堆后对局已 FINISHED；canonical recorder 不能把
    该状态写成可重执行的 identity_draw_deck_exhausted 正式记录。不得
    把 fixture_applied 伪装成 formal_result。
    """

    from scripts.sgs_engine.model import DISCARD_PILE, DRAW_PILE

    helpers = _deck_exhaustion_helpers()
    _enter_draw_setup = helpers._enter_draw_setup
    _enter_play = helpers._enter_play
    _park_away = helpers._park_away
    _require_op = helpers._require_op
    _session = helpers._session
    _step = helpers._step

    game = _session(18)
    assert game.analysis_only is False
    assert game.formal_result_eligible is True
    _enter_play(game)
    _enter_draw_setup(game)
    drawer = game.current_player_id
    holder = next(pid for pid in game.player_ids if pid != drawer)
    remaining = list(game.state.card_ids_in(DRAW_PILE))
    _park_away(game, remaining[1:], holder)
    _park_away(game, list(game.state.card_ids_in(DISCARD_PILE)), holder)
    _step(game, _require_op(game, "proceed_draw"))
    assert game.runtime.game_over_reason == "identity_draw_deck_exhausted"
    with pytest.raises(
        (
            UnsupportedRuleError,
            ProductionReplayFormatError,
            ProductionReplayDivergenceError,
        )
    ):
        record_reference_production_batch(18, _game=game)


def test_formal_identity_replay_rejects_fixture() -> None:
    game = FormalIdentitySession(
        seed=1,
        configuration=FormalIdentityConfiguration.formal_profile(),
        analysis_only=True,
    )
    with pytest.raises(ProductionReplayFormatError, match="正式身份回放禁止夹具"):
        record_reference_production_batch(
            1,
            _game=game,
            fixture=lambda _game: None,
        )


@pytest.fixture(scope="module")
def identity_replay() -> ProductionReexecutionReplay:
    # canonical 自然耗尽平局可达性未闭合；可见性夹具走真实击杀终局。
    return record_reference_formal_identity(
        2,
        configuration=FormalIdentityConfiguration.formal_profile(),
        analysis_only=True,
        max_steps=8000,
    )


def test_player_visible_payload_cannot_authoritative_reexecute(
    identity_replay: ProductionReexecutionReplay,
) -> None:
    record = identity_replay
    visible = record.player_visible_payload(
        viewer_id="p1",
        valid_player_ids=("p1", "p2", "p3", "p4", "p5"),
    )
    with pytest.raises((ProductionReplayFormatError, TypeError, ValueError)):
        reexecute_production_replay(ProductionReexecutionReplay.from_dict(visible))


def test_identity_mapping_tamper_fails_closed(
    identity_replay: ProductionReexecutionReplay,
) -> None:
    record = identity_replay
    payload = record.to_dict()
    identities = dict(payload["header"]["initial_configuration"]["identities"])
    lord = payload["header"]["initial_configuration"]["lord_player_id"]
    other = next(pid for pid in identities if pid != lord)
    identities[lord], identities[other] = identities[other], identities[lord]
    payload["header"]["initial_configuration"]["identities"] = identities
    payload["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        tampered = ProductionReexecutionReplay.from_dict(payload)
        reexecute_production_replay(tampered)


def test_numbered_order_tamper_fails_closed(
    identity_replay: ProductionReexecutionReplay,
) -> None:
    record = identity_replay
    payload = record.to_dict()
    payload["header"]["initial_configuration"]["numbered_player_order"] = list(
        reversed(
            payload["header"]["initial_configuration"]["numbered_player_order"]
        )
    )
    payload["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError, match="numbered_player_order"):
        ProductionReexecutionReplay.from_dict(payload)


def test_lord_consistency_tamper_fails_closed(
    identity_replay: ProductionReexecutionReplay,
) -> None:
    record = identity_replay
    payload = record.to_dict()
    lord = payload["header"]["initial_configuration"]["lord_player_id"]
    other = next(
        pid
        for pid in payload["header"]["initial_configuration"]["physical_player_ids"]
        if pid != lord
    )
    payload["header"]["initial_configuration"]["lord_player_id"] = other
    payload["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError, match="lord_player_id"):
        ProductionReexecutionReplay.from_dict(payload)


def test_bool_int_alias_tamper_fails_closed(
    identity_replay: ProductionReexecutionReplay,
) -> None:
    record = identity_replay
    payload = record.to_dict()
    payload["header"]["initial_configuration"]["analysis_only"] = 1
    payload["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(payload)


def test_null_and_extra_missing_fields_fail_closed(
    identity_replay: ProductionReexecutionReplay,
) -> None:
    record = identity_replay
    payload = record.to_dict()
    payload["header"]["initial_configuration"]["identities"] = None
    payload["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(payload)

    payload = record.to_dict()
    payload["header"]["initial_configuration"]["extra"] = True
    payload["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(payload)

    payload = record.to_dict()
    del payload["header"]["initial_configuration"]["physical_player_ids"]
    payload["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(payload)


def test_identity_type_spoof_fails_closed(
    identity_replay: ProductionReexecutionReplay,
) -> None:
    record = identity_replay
    payload = record.to_dict()
    identities = dict(payload["header"]["initial_configuration"]["identities"])
    lord = payload["header"]["initial_configuration"]["lord_player_id"]
    identities[lord] = True
    payload["header"]["initial_configuration"]["identities"] = identities
    payload["record_sha256"] = ""
    with pytest.raises(ProductionReplayFormatError):
        ProductionReexecutionReplay.from_dict(payload)


def test_twenty_seed_strict_reexecution_sweep() -> None:
    """20 seed 正式 record/reexecute。不强制出现 identity_draw_deck_exhausted。

    canonical 自然平局可达性为
    C5_CANONICAL_DRAW_REACHABILITY_UNRESOLVED；若某 seed 自然到达该终局
    仍须 verified=True，但 sweep 不得要求该终局出现。
    """

    winners: dict[int, str | None] = {}
    for seed in range(20):
        record = record_reference_formal_identity(
            seed,
            configuration=FormalIdentityConfiguration.formal_profile(),
            analysis_only=False,
            max_steps=8000,
        )
        _assert_identity_record(record)
        assert record.header["formal_result"] is True
        assert record.outcome["finish_reason"] in (
            "identity_victory",
            "identity_draw_deck_exhausted",
        )
        if record.outcome["finish_reason"] == "identity_victory":
            assert record.outcome["winner_id"] in (
                "lord_and_loyalists",
                "rebels",
                "spy",
            )
        else:
            assert record.outcome["winner_id"] is None
        result = reexecute_production_replay(record)
        assert result.verified is True
        assert result.winner_id == record.outcome["winner_id"]
        winners[seed] = record.outcome["winner_id"]
    assert len(winners) == 20
