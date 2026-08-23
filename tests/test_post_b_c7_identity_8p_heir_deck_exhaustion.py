# -*- coding: utf-8 -*-
"""POST-B C7：reshuffle_draw 与摸牌耗尽口径继承 C6，可达性保持 UNRESOLVED。"""

from __future__ import annotations

from scripts.sgs_engine.mode_identity_heir import (
    C7_CANONICAL_DRAW_REACHABILITY_STATUS,
    FormalHeirAndSpyChoiceIdentityConfiguration,
    FormalHeirAndSpyChoiceIdentitySession,
)
from scripts.sgs_engine.model import DISCARD_PILE, DRAW_PILE, ZoneRef

_SECRET = b"c7-exhaustion-session-secret-0001"


def test_c7_canonical_draw_reachability_unresolved() -> None:
    assert C7_CANONICAL_DRAW_REACHABILITY_STATUS == (
        "C7_CANONICAL_DRAW_REACHABILITY_UNRESOLVED"
    )


def test_c7_initial_draw_pile_and_reshuffle_draw_mode() -> None:
    game = FormalHeirAndSpyChoiceIdentitySession(
        seed=0,
        configuration=FormalHeirAndSpyChoiceIdentityConfiguration.formal_profile(),
        analysis_only=False,
        session_id="c7-exhaustion-0",
        session_secret=_SECRET,
    )
    assert game.deck_supply_mode == "reshuffle_draw"
    assert len(game.state.card_ids_in(DRAW_PILE)) == 128
    assert len(game.state.card_ids_in(DISCARD_PILE)) == 0
    for player_id in game.physical_player_ids:
        assert len(game.state.card_ids_in(ZoneRef.hand(player_id))) == 4
