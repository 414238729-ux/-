# -*- coding: utf-8 -*-
"""C4-GLOBAL2-001：斗地主 canonical 类型与 authority 边界回归测试。"""

from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import replace
from typing import Callable

import pytest

from scripts.sgs_engine.mode_doudizhu import (
    FormalDoudizhuConfiguration,
    FormalDoudizhuConfigurationError,
    FormalDoudizhuSession,
    TrustedFormalDoudizhuConfiguration,
    assert_trusted_formal_doudizhu_configuration,
)
from scripts.sgs_engine.production_replay import (
    ProductionReexecutionReplay,
    ProductionReplayFormatError,
    record_reference_formal_doudizhu,
    reexecute_production_replay,
)


def _canonical_payload() -> dict[str, object]:
    return FormalDoudizhuConfiguration.formal_profile().to_dict()


@pytest.mark.parametrize(
    ("field_name", "type_equal_value"),
    (
        ("feiyang_seat", True),
        ("hand_qi_ka_allowed", 0),
        ("bahu_slash_limit", 2.0),
        ("base_hp", (5.0, 4.0, 4.0)),
        ("base_hp", [5, 4, 4]),
    ),
    ids=(
        "true-vs-one",
        "false-vs-zero",
        "int-vs-float",
        "tuple-element-int-vs-float",
        "tuple-vs-list",
    ),
)
def test_trusted_boundary_uses_recursive_type_strict_canonical_value(
    field_name: str,
    type_equal_value: object,
) -> None:
    """持有真实 token 的对象也不能用 Python 宽松 equality 混过值门禁。"""

    configuration = FormalDoudizhuConfiguration.formal_profile()
    object.__setattr__(configuration, field_name, type_equal_value)

    with pytest.raises(
        FormalDoudizhuConfigurationError,
        match="canonical value invariant",
    ):
        assert_trusted_formal_doudizhu_configuration(configuration)


@pytest.mark.parametrize(
    ("field_name", "type_equal_value"),
    (
        ("feiyang_seat", True),
        ("hand_qi_ka_allowed", 0),
        ("bahu_slash_limit", 2.0),
        ("base_hp", [5.0, 4.0, 4.0]),
        ("base_hp", (5, 4, 4)),
    ),
    ids=(
        "true-vs-one",
        "false-vs-zero",
        "int-vs-float",
        "list-element-int-vs-float",
        "serialized-list-vs-tuple",
    ),
)
def test_canonical_reconstruction_rejects_type_equal_payloads(
    field_name: str,
    type_equal_value: object,
) -> None:
    """正式 replay/factory 重构对容器及其元素执行同一严格类型契约。"""

    payload = _canonical_payload()
    payload[field_name] = type_equal_value

    with pytest.raises(
        FormalDoudizhuConfigurationError,
        match="canonical formal profile",
    ):
        FormalDoudizhuConfiguration.from_canonical_profile_value(payload)


def test_public_trusted_construction_and_from_dict_do_not_mint_capability(
) -> None:
    """公开 exact Trusted 类型与普通 roundtrip 都不能自行铸造 authority。"""

    public = TrustedFormalDoudizhuConfiguration()
    roundtripped = TrustedFormalDoudizhuConfiguration.from_dict(
        _canonical_payload()
    )

    for configuration in (public, roundtripped):
        assert type(configuration) is TrustedFormalDoudizhuConfiguration
        with pytest.raises(
            FormalDoudizhuConfigurationError,
            match="capability identity",
        ):
            assert_trusted_formal_doudizhu_configuration(configuration)
        with pytest.raises(
            FormalDoudizhuConfigurationError,
            match="capability identity",
        ):
            FormalDoudizhuSession(
                seed=1,
                configuration=configuration,
                analysis_only=False,
            )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("feiyang_seat", True),
        ("hand_qi_ka_allowed", 0),
        ("bahu_slash_limit", 2.0),
        ("base_hp", [5.0, 4.0, 4.0]),
    ),
    ids=(
        "true-vs-one",
        "false-vs-zero",
        "int-vs-float",
        "nested-element-type",
    ),
)
def test_trusted_from_dict_does_not_coerce_type_different_input(
    field_name: str,
    invalid_value: object,
) -> None:
    """普通反序列化不得用 bool/int 等转换抹掉输入 representation。"""

    payload = _canonical_payload()
    payload[field_name] = invalid_value
    with pytest.raises(FormalDoudizhuConfigurationError):
        TrustedFormalDoudizhuConfiguration.from_dict(payload)


def test_plain_from_dict_roundtrip_stays_untrusted() -> None:
    configuration = FormalDoudizhuConfiguration.from_dict(
        _canonical_payload()
    )
    assert type(configuration) is FormalDoudizhuConfiguration
    with pytest.raises(FormalDoudizhuConfigurationError, match="exact type"):
        assert_trusted_formal_doudizhu_configuration(configuration)


@pytest.mark.parametrize(
    "reconstructor",
    (
        pytest.param(lambda value: replace(value), id="replace"),
        pytest.param(lambda value: copy(value), id="copy"),
        pytest.param(lambda value: deepcopy(value), id="deepcopy"),
    ),
)
def test_replace_copy_and_deepcopy_cannot_carry_or_mint_capability(
    reconstructor: Callable[
        [TrustedFormalDoudizhuConfiguration],
        TrustedFormalDoudizhuConfiguration,
    ],
) -> None:
    canonical = FormalDoudizhuConfiguration.formal_profile()
    reconstructed = reconstructor(canonical)
    assert type(reconstructed) is TrustedFormalDoudizhuConfiguration
    with pytest.raises(
        FormalDoudizhuConfigurationError,
        match="capability identity",
    ):
        assert_trusted_formal_doudizhu_configuration(reconstructed)


def test_replace_with_type_equal_value_cannot_mint_capability() -> None:
    canonical = FormalDoudizhuConfiguration.formal_profile()
    with pytest.raises(FormalDoudizhuConfigurationError):
        reconstructed = replace(canonical, feiyang_seat=True)
        assert_trusted_formal_doudizhu_configuration(reconstructed)


def test_trusted_subclass_remains_fail_closed() -> None:
    class ForgedTrustedDoudizhuConfiguration(
        TrustedFormalDoudizhuConfiguration
    ):
        pass

    forged = ForgedTrustedDoudizhuConfiguration()
    with pytest.raises(FormalDoudizhuConfigurationError, match="exact type"):
        assert_trusted_formal_doudizhu_configuration(forged)


def test_internal_canonical_factory_retains_unique_formal_authority() -> None:
    canonical = FormalDoudizhuConfiguration.formal_profile()
    reconstructed = (
        FormalDoudizhuConfiguration.from_canonical_profile_value(
            canonical.to_dict()
        )
    )

    for configuration in (canonical, reconstructed):
        assert type(configuration) is TrustedFormalDoudizhuConfiguration
        assert_trusted_formal_doudizhu_configuration(configuration)
        session = FormalDoudizhuSession(
            seed=2,
            configuration=configuration,
            analysis_only=False,
        )
        assert session.formal_result_eligible is True


@pytest.fixture(scope="module")
def canonical_formal_replay() -> ProductionReexecutionReplay:
    replay = record_reference_formal_doudizhu(
        0,
        configuration=FormalDoudizhuConfiguration.formal_profile(),
        analysis_only=False,
        max_steps=6000,
    )
    assert replay.header["formal_result"] is True
    return replay


def test_replay_canonical_reconstruction_remains_verified(
    canonical_formal_replay: ProductionReexecutionReplay,
) -> None:
    result = reexecute_production_replay(canonical_formal_replay)
    assert result.verified is True


def test_formal_replay_ingress_rejects_type_different_configuration(
    canonical_formal_replay: ProductionReexecutionReplay,
) -> None:
    payload = canonical_formal_replay.to_dict()
    initial = payload["header"]["initial_configuration"]  # type: ignore[index]
    config = initial["formal_doudizhu_configuration"]  # type: ignore[index]
    config["feiyang_seat"] = True  # type: ignore[index]
    payload["record_sha256"] = ""

    with pytest.raises(
        ProductionReplayFormatError,
        match="canonical formal profile",
    ):
        ProductionReexecutionReplay.from_dict(payload)


def test_strict_reexecute_rejects_type_different_configuration(
    canonical_formal_replay: ProductionReexecutionReplay,
) -> None:
    payload = canonical_formal_replay.to_dict()
    header = payload["header"]
    header["formal_result"] = False  # type: ignore[index]
    initial = header["initial_configuration"]  # type: ignore[index]
    config = initial["formal_doudizhu_configuration"]  # type: ignore[index]
    config["feiyang_seat"] = True  # type: ignore[index]
    payload["record_sha256"] = ""
    replay = ProductionReexecutionReplay.from_dict(payload)

    with pytest.raises(
        FormalDoudizhuConfigurationError,
        match="canonical formal profile",
    ):
        reexecute_production_replay(replay)
