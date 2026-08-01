from __future__ import annotations

import pytest

from scripts import sgs_engine
from scripts.sgs_engine.actions import UnsupportedRuleError as ActionUnsupportedRuleError
from scripts.sgs_engine.engine import UnsupportedRuleError as SessionUnsupportedRuleError


def test_public_package_uses_one_unsupported_rule_error_type() -> None:
    assert sgs_engine.UnsupportedRuleError is ActionUnsupportedRuleError
    assert SessionUnsupportedRuleError is ActionUnsupportedRuleError


def test_public_package_does_not_claim_complete_game_support() -> None:
    session = sgs_engine.AuthoritativeCoreSession(
        players=(
            sgs_engine.PlayerState("甲", 1, 4, 4),
            sgs_engine.PlayerState("乙", 2, 4, 4),
        ),
        seed=1,
    )

    with pytest.raises(sgs_engine.UnsupportedRuleError, match="完整对局规则尚未实现"):
        session.run_game()


def test_public_engine_version_explicitly_identifies_scaffold_scope() -> None:
    assert "scaffold" in sgs_engine.ENGINE_VERSION
