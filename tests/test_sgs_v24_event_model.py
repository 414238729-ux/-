from __future__ import annotations

from scripts.sgs_incremental_mechanics import (
    DamageContext,
    EffectRequirements,
    GainTimeEffect,
    PendingGainCard,
    effect_requirements_satisfied,
    resolve_gain_time_queue,
)


def _pending_cards() -> tuple[PendingGainCard, ...]:
    return (
        PendingGainCard("card-red", "桃", suit="红桃"),
        PendingGainCard("card-black", "杀", suit="黑桃"),
    )


def _observe_only(_context: object) -> None:
    """观察由通用队列自动记录；该效果本身不移动牌。"""


def _redirect_first_red_card(context: object) -> None:
    pending_cards = getattr(context, "pending_cards")
    red_card = next(card for card in pending_cards if card.suit == "红桃")
    getattr(context, "redirect_card")(red_card.card_id, recipient_id="郭女王")


def test_original_recipient_effect_sees_pending_card_when_it_resolves_first() -> None:
    resolution = resolve_gain_time_queue(
        original_recipient_id="曹髦",
        pending_cards=_pending_cards(),
        actor_order=("曹髦", "郭女王"),
        effects=(
            GainTimeEffect("郭女王", "易宠拦截", _redirect_first_red_card),
            GainTimeEffect("曹髦", "获得时观察", _observe_only),
        ),
    )

    assert resolution.effect_order == ("获得时观察", "易宠拦截")
    assert resolution.observations[0].pending_card_ids == ("card-red", "card-black")


def test_original_recipient_cannot_see_intercepted_card_when_guo_resolves_first() -> None:
    resolution = resolve_gain_time_queue(
        original_recipient_id="曹髦",
        pending_cards=_pending_cards(),
        actor_order=("郭女王", "曹髦"),
        effects=(
            GainTimeEffect("曹髦", "获得时观察", _observe_only),
            GainTimeEffect("郭女王", "易宠拦截", _redirect_first_red_card),
        ),
    )

    assert resolution.effect_order == ("易宠拦截", "获得时观察")
    assert resolution.observations[1].pending_card_ids == ("card-black",)


def test_redirected_card_enters_only_guo_hand_and_not_original_recipient_zone() -> None:
    resolution = resolve_gain_time_queue(
        original_recipient_id="曹髦",
        pending_cards=_pending_cards(),
        actor_order=("郭女王", "曹髦"),
        effects=(GainTimeEffect("郭女王", "易宠拦截", _redirect_first_red_card),),
    )

    guo_entries = resolution.entries_for("郭女王")
    original_entries = resolution.entries_for("曹髦")

    assert [(entry.card_id, entry.zone, entry.redirected) for entry in guo_entries] == [
        ("card-red", "手牌区", True)
    ]
    assert [(entry.card_id, entry.redirected) for entry in original_entries] == [
        ("card-black", False)
    ]
    assert sum(entry.card_id == "card-red" for entry in resolution.actual_zone_entries) == 1


def _replaced_damage_context() -> DamageContext:
    return DamageContext(
        card_user_id="郭女王",
        damage_source_id="雀持有者",
        damage_card_name="杀",
        damage_target_id="目标",
        card_type="基本牌",
        skill_activator_id="郭女王",
        equipment_owner_id="郭女王",
        source_replaced=True,
    )


def test_user_source_equipment_name_and_type_requirements_are_independent() -> None:
    context = _replaced_damage_context()

    assert effect_requirements_satisfied(
        "郭女王", context, EffectRequirements(requires_card_user=True)
    )
    assert not effect_requirements_satisfied(
        "雀持有者", context, EffectRequirements(requires_card_user=True)
    )
    assert effect_requirements_satisfied(
        "雀持有者", context, EffectRequirements(requires_damage_source=True)
    )
    assert not effect_requirements_satisfied(
        "郭女王", context, EffectRequirements(requires_damage_source=True)
    )
    assert effect_requirements_satisfied(
        "郭女王", context, EffectRequirements(requires_equipment_owner=True)
    )
    assert not effect_requirements_satisfied(
        "雀持有者", context, EffectRequirements(requires_equipment_owner=True)
    )

    assert effect_requirements_satisfied(
        "任意角色", context, EffectRequirements(requires_card_name="杀")
    )
    assert not effect_requirements_satisfied(
        "任意角色", context, EffectRequirements(requires_card_name="决斗")
    )
    assert effect_requirements_satisfied(
        "任意角色", context, EffectRequirements(requires_card_type="基本牌")
    )
    assert not effect_requirements_satisfied(
        "任意角色", context, EffectRequirements(requires_card_type="普通锦囊")
    )


def test_same_user_and_source_requirement_is_not_satisfied_after_source_replacement() -> None:
    replaced = _replaced_damage_context()
    requirement = EffectRequirements(requires_same_user_and_source=True)

    assert not effect_requirements_satisfied("郭女王", replaced, requirement)
    assert not effect_requirements_satisfied("雀持有者", replaced, requirement)

    unreplaced = DamageContext(
        card_user_id="郭女王",
        damage_source_id="郭女王",
        damage_card_name="杀",
        damage_target_id="目标",
        card_type="基本牌",
    )
    assert effect_requirements_satisfied("郭女王", unreplaced, requirement)


def test_kill_attribution_belongs_to_current_damage_source() -> None:
    context = _replaced_damage_context()

    assert context.kill_owner_id == "雀持有者"
    assert context.kill_owner_id != context.card_user_id
