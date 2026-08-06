from __future__ import annotations

import pytest

from scripts.sgs_engine.events import (
    DamageEvent,
    EventQueue,
    EventType,
    GameEvent,
    ResponseDecision,
    ResponseWindow,
)


def test_event_type_contains_required_rule_events() -> None:
    assert {event.value for event in EventType} >= {
        "card_used",
        "card_played",
        "card_effect_cancelled",
        "card_invalidated",
        "card_gained",
        "card_lost",
        "card_discarded",
        "damage",
        "lose_hp",
        "dying",
        "death",
        "victory",
    }


def test_game_event_keeps_all_attribution_fields_independent() -> None:
    event = GameEvent(
        event_type=EventType.CARD_USED,
        card_instance_id="card-001",
        card_user="牌使用者",
        damage_source="伤害来源",
        skill_owner="技能拥有者",
        equipment_owner="装备拥有者",
        kill_credit="击杀归属者",
        target_ids=("目标甲", "目标乙"),
    )

    assert event.card_user == "牌使用者"
    assert event.damage_source == "伤害来源"
    assert event.skill_owner == "技能拥有者"
    assert event.equipment_owner == "装备拥有者"
    assert event.kill_credit == "击杀归属者"
    assert event.target_ids == ("目标甲", "目标乙")


def test_event_payload_is_recursively_copied_and_frozen() -> None:
    source = {
        "zone": {"cards": ["牌一", "牌二"]},
        "flags": ["公开", "处理区"],
    }
    event = GameEvent(
        event_type=EventType.CARD_GAINED,
        card_instance_id="牌一",
        target_ids=("甲",),
        payload=source,
    )

    source["zone"]["cards"].append("外部篡改")
    source["flags"].append("外部标记")

    assert event.payload["zone"]["cards"] == ("牌一", "牌二")
    assert event.payload["flags"] == ("公开", "处理区")
    with pytest.raises(TypeError):
        event.payload["新增键"] = "非法"  # type: ignore[index]
    with pytest.raises(TypeError):
        event.payload["zone"]["cards"][0] = "非法"  # type: ignore[index]


def test_damage_event_has_damage_type_and_single_real_target() -> None:
    event = DamageEvent(
        target_id="乙",
        amount=2,
        damage_type="火",
        card_user="甲",
        damage_source="丙",
        skill_owner="丁",
        kill_credit="戊",
    )

    assert event.event_type is EventType.DAMAGE
    assert event.target_ids == ("乙",)
    assert event.amount == 2
    assert event.card_user == "甲"
    assert event.damage_source == "丙"
    assert event.skill_owner == "丁"
    assert event.kill_credit == "戊"


@pytest.mark.parametrize("amount", [0, -1])
def test_damage_event_rejects_non_positive_damage(amount: int) -> None:
    with pytest.raises(ValueError, match="伤害值必须大于0"):
        DamageEvent(target_id="乙", amount=amount)


def test_event_rejects_missing_required_target_identifier() -> None:
    with pytest.raises(ValueError, match="角色标识必须是非空字符串"):
        GameEvent(event_type=EventType.DEATH, target_ids=(None,))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="伤害目标必须是非空字符串"):
        DamageEvent(target_id="", amount=1)


def test_event_contract_rejects_wrong_or_incomplete_core_events() -> None:
    with pytest.raises(TypeError, match="必须使用DamageEvent"):
        GameEvent(event_type=EventType.DAMAGE)

    with pytest.raises(ValueError, match="实体牌ID.*card_key"):
        GameEvent(event_type=EventType.CARD_USED, card_user="甲")
    with pytest.raises(ValueError, match="card_user"):
        GameEvent(event_type=EventType.CARD_PLAYED, card_instance_id="闪-1")

    with pytest.raises(ValueError, match="必须且只能指定一名"):
        GameEvent(event_type=EventType.DYING)
    with pytest.raises(ValueError, match="必须且只能指定一名"):
        GameEvent(event_type=EventType.DEATH, target_ids=("甲", "乙"))


def test_virtual_card_event_uses_card_key_and_keeps_material_ids_distinct() -> None:
    event = GameEvent(
        event_type=EventType.CARD_PLAYED,
        card_key="杀",
        material_card_instance_ids=("手牌-1", "手牌-2"),
        card_user="甲",
        skill_owner="甲",
    )

    assert event.card_instance_id is None
    assert event.card_key == "杀"
    assert event.material_card_instance_ids == ("手牌-1", "手牌-2")
    assert event.to_replay_dict()["material_card_instance_ids"] == ["手牌-1", "手牌-2"]


@pytest.mark.parametrize(
    "payload",
    [
        {"bad": {"集合"}},
        {1: "非字符串键"},
        {"bad": float("nan")},
        {"bad": float("inf")},
    ],
)
def test_event_payload_rejects_noncanonical_json_values(payload: object) -> None:
    with pytest.raises((TypeError, ValueError), match="不受支持|映射键|NaN|无穷"):
        GameEvent(
            event_type=EventType.CARD_MOVED,
            card_instance_id="牌-1",
            payload=payload,  # type: ignore[arg-type]
        )


def test_event_queue_assigns_monotonic_sequence_and_preserves_fifo() -> None:
    queue = EventQueue()
    used = GameEvent(
        event_type=EventType.CARD_USED,
        card_instance_id="杀-1",
        card_user="甲",
        target_ids=("乙",),
    )
    damage = DamageEvent(
        target_id="乙",
        amount=1,
        damage_source="甲",
        kill_credit="甲",
    )
    dying = GameEvent(event_type=EventType.DYING, target_ids=("乙",))

    queued_used = queue.enqueue(used)
    queued_damage, queued_dying = queue.extend((damage, dying))

    assert [event.sequence for event in queue.snapshot()] == [1, 2, 3]
    assert queue.peek() is queued_used
    assert queue.dequeue() is queued_used
    assert queue.dequeue() is queued_damage
    assert queue.dequeue() is queued_dying
    assert queue.next_sequence == 4
    assert not queue


def test_event_queue_snapshot_cannot_mutate_queue_or_nested_payload() -> None:
    queue = EventQueue(
        (
            GameEvent(
                event_type=EventType.CARD_GAINED,
                card_instance_id="牌一",
                target_ids=("甲",),
                payload={"zone": {"cards": ["牌一"]}},
            ),
        )
    )
    snapshot = queue.snapshot()

    with pytest.raises(TypeError):
        snapshot[0] = GameEvent(  # type: ignore[index]
            event_type=EventType.CARD_LOST,
            card_instance_id="牌一",
            target_ids=("甲",),
        )
    with pytest.raises(TypeError):
        snapshot[0].payload["zone"]["cards"][0] = "非法"  # type: ignore[index]

    assert queue.peek().payload["zone"]["cards"] == ("牌一",)


def test_event_queue_does_not_allow_numbered_event_to_be_requeued() -> None:
    queue = EventQueue()
    numbered = queue.enqueue(
        GameEvent(
            event_type=EventType.CARD_GAINED,
            card_instance_id="牌一",
            target_ids=("甲",),
        )
    )

    with pytest.raises(ValueError, match="只能由EventQueue分配"):
        queue.enqueue(numbered)


def test_empty_event_queue_reports_clear_chinese_error() -> None:
    queue = EventQueue()

    with pytest.raises(IndexError, match="事件队列为空"):
        queue.peek()
    with pytest.raises(IndexError, match="事件队列为空"):
        queue.dequeue()


def test_response_window_processes_each_current_seat_in_order() -> None:
    trick = GameEvent(
        event_type=EventType.CARD_USED,
        card_instance_id="锦囊-1",
        card_user="P2",
        target_ids=("P1",),
    )
    window = ResponseWindow(
        ("P3", "P4", "P1", "P2"),
        window_id="无懈窗口-1",
        source_event=trick,
    )

    assert window.current_responder == "P3"
    window.pass_response("P3")
    response = GameEvent(
        event_type=EventType.CARD_PLAYED,
        card_instance_id="无懈-1",
        card_user="P4",
    )
    window.respond("P4", response)
    window.pass_response("P1")
    window.pass_response("P2")

    assert window.is_closed
    assert window.current_responder is None
    assert [record.player_id for record in window.history] == ["P3", "P4", "P1", "P2"]
    assert window.decision_for("P3") is ResponseDecision.PASSED
    assert window.decision_for("P4") is ResponseDecision.RESPONDED
    bound_response = window.response_for("P4")
    assert bound_response is not response
    assert bound_response is not None
    assert bound_response.payload["response_window_id"] == "无懈窗口-1"
    assert bound_response.payload["source_event_type"] == "card_used"
    assert window.waiting_responders == ()


def test_response_window_rejects_out_of_order_choice_without_changing_state() -> None:
    window = ResponseWindow(("P1", "P2"), window_id="救援窗口-1")

    with pytest.raises(ValueError, match="当前应由.*P1"):
        window.pass_response("P2")

    assert window.current_responder == "P1"
    assert window.history == ()
    assert window.decision_for("P1") is ResponseDecision.WAITING
    assert window.decision_for("P2") is ResponseDecision.WAITING


def test_response_window_can_close_after_first_legal_response() -> None:
    window = ResponseWindow(
        ("P1", "P2", "P3"),
        window_id="单响应窗口-1",
        close_on_first_response=True,
    )
    response = GameEvent(
        event_type=EventType.CARD_PLAYED,
        card_instance_id="响应牌-1",
        card_user="P1",
    )

    window.respond("P1", response)

    assert window.is_closed
    assert window.decision_for("P1") is ResponseDecision.RESPONDED
    assert window.decision_for("P2") is ResponseDecision.SKIPPED
    assert window.decision_for("P3") is ResponseDecision.SKIPPED
    with pytest.raises(RuntimeError, match="已经关闭"):
        window.pass_response("P2")


def test_response_window_rejects_duplicate_players() -> None:
    with pytest.raises(ValueError, match="不能包含重复角色"):
        ResponseWindow(("P1", "P1"), window_id="错误窗口")


def test_response_window_rejects_non_card_response_by_default() -> None:
    window = ResponseWindow(("P1",), window_id="默认窗口")
    wrong_type = GameEvent(
        event_type=EventType.CARD_MOVED,
        card_instance_id="牌-1",
        card_user="P1",
    )

    with pytest.raises(ValueError, match="只接受以下事件类型"):
        window.respond("P1", wrong_type)

    assert window.current_responder == "P1"
    assert window.history == ()


def test_response_window_rejects_impersonated_card_user() -> None:
    window = ResponseWindow(("P1", "P2"), window_id="身份绑定窗口")
    impersonated = GameEvent(
        event_type=EventType.CARD_PLAYED,
        card_instance_id="无懈-冒用",
        card_user="P2",
    )

    with pytest.raises(ValueError, match="card_user必须与当前响应角色一致"):
        window.respond("P1", impersonated)

    assert window.current_responder == "P1"
    assert window.decision_for("P1") is ResponseDecision.WAITING


def test_response_window_supports_explicit_allowed_event_types() -> None:
    window = ResponseWindow(
        ("P1",),
        window_id="技能响应窗口",
        allowed_event_types=(EventType.CARD_INVALIDATED,),
    )
    event = GameEvent(
        event_type=EventType.CARD_INVALIDATED,
        card_key="无懈可击",
        card_user="P1",
    )

    window.respond("P1", event)

    assert window.is_closed
    assert window.response_for("P1") is not event
    assert window.response_for("P1").payload["response_window_id"] == "技能响应窗口"


def test_response_window_rejects_numbered_or_conflicting_causal_event() -> None:
    numbered = EventQueue().enqueue(
        GameEvent(
            event_type=EventType.CARD_PLAYED,
            card_instance_id="无懈-1",
            card_user="P1",
        )
    )
    window = ResponseWindow(("P1",), window_id="窗口-1")
    with pytest.raises(ValueError, match="尚未入队编号"):
        window.respond("P1", numbered)

    conflicting = GameEvent(
        event_type=EventType.CARD_PLAYED,
        card_instance_id="无懈-2",
        card_user="P1",
        payload={"response_window_id": "其他窗口"},
    )
    with pytest.raises(ValueError, match="其他响应窗口"):
        window.respond("P1", conflicting)


def test_damage_event_replay_payload_preserves_rule_specific_fields() -> None:
    event = DamageEvent(
        target_id="乙",
        amount=2,
        damage_type="雷属性",
        damage_source="甲",
        kill_credit="甲",
    )

    payload = event.to_replay_dict()
    assert payload["target_id"] == "乙"
    assert payload["target_ids"] == ["乙"]
    assert payload["amount"] == 2
    assert payload["damage_type"] == "雷属性"
    assert payload["damage_source"] == "甲"


def test_response_window_snapshot_is_immutable_and_detached() -> None:
    window = ResponseWindow(("P1", "P2"), window_id="快照窗口")
    snapshot = window.snapshot()

    with pytest.raises(TypeError):
        snapshot.decisions["P1"] = ResponseDecision.PASSED  # type: ignore[index]
    with pytest.raises(AttributeError):
        snapshot.responder_order.append("P3")  # type: ignore[attr-defined]

    window.pass_response("P1")

    assert snapshot.current_responder == "P1"
    assert snapshot.decisions["P1"] is ResponseDecision.WAITING
    assert window.snapshot().current_responder == "P2"
    assert window.snapshot().decisions["P1"] is ResponseDecision.PASSED


# ----------------------------------------------------------------------
# 属性伤害传导链事件契约（CP-04J 审计残项 N2）
# ----------------------------------------------------------------------


def _chain_started_payload() -> dict[str, object]:
    return {
        "root_damage_event_id": "42",
        "source_id": "甲",
        "original_target_id": "乙",
        "damage_type": "火属性",
        "root_card_instance_id": "铁索-1",
        "chain_base_damage": 1,
        "candidate_order": ["甲"],
    }


def _chain_resolved_payload(
    *,
    result: str = "damaged",
    actual: int = 1,
    old: bool = True,
    new: bool = False,
) -> dict[str, object]:
    return {
        "root_damage_event_id": "42",
        "target_id": "乙",
        "target_index": 0,
        "result": result,
        "chain_base_damage": 1,
        "actual_damage": actual,
        "chained_old": old,
        "chained_new": new,
    }


def _chain_finished_payload(
    stop_reason: str = "completed",
) -> dict[str, object]:
    return {
        "root_damage_event_id": "42",
        "processed_targets": ["乙"],
        "skipped_targets": [],
        "stop_reason": stop_reason,
    }


def _chain_event(
    event_type: EventType, payload: dict[str, object]
) -> GameEvent:
    return GameEvent(
        event_type=event_type,
        card_instance_id="铁索-1",
        card_key="sgs_trick_tiesuolianhuan",
        target_ids=("乙",),
        payload=payload,
    )


def test_chain_damage_started_valid_contract() -> None:
    event = _chain_event(
        EventType.CHAIN_DAMAGE_STARTED, _chain_started_payload()
    )
    assert event.payload["damage_type"] == "火属性"
    assert event.payload["candidate_order"] == ("甲",)


@pytest.mark.parametrize(
    ("result", "actual", "old", "new"),
    [
        ("damaged", 1, True, False),
        ("skipped_dead", 0, True, True),
        ("skipped_unchained", 0, False, False),
        ("prevented_zero", 0, True, True),
    ],
)
def test_chain_target_resolved_valid_contracts(
    result: str, actual: int, old: bool, new: bool
) -> None:
    event = _chain_event(
        EventType.CHAIN_TARGET_RESOLVED,
        _chain_resolved_payload(
            result=result, actual=actual, old=old, new=new
        ),
    )
    assert event.payload["result"] == result


@pytest.mark.parametrize(
    "stop_reason",
    ["completed", "prevented_zero", "winner", "no_candidates"],
)
def test_chain_damage_finished_valid_contracts(stop_reason: str) -> None:
    event = _chain_event(
        EventType.CHAIN_DAMAGE_FINISHED,
        _chain_finished_payload(stop_reason),
    )
    assert event.payload["stop_reason"] == stop_reason


@pytest.mark.parametrize(
    ("event_type", "factory", "missing"),
    [
        (
            EventType.CHAIN_DAMAGE_STARTED,
            _chain_started_payload,
            "chain_base_damage",
        ),
        (
            EventType.CHAIN_TARGET_RESOLVED,
            _chain_resolved_payload,
            "result",
        ),
        (
            EventType.CHAIN_DAMAGE_FINISHED,
            _chain_finished_payload,
            "stop_reason",
        ),
    ],
)
def test_chain_events_reject_missing_field(
    event_type: EventType,
    factory: object,
    missing: str,
) -> None:
    payload = factory()  # type: ignore[operator]
    del payload[missing]
    with pytest.raises(ValueError, match="字段必须恰好"):
        _chain_event(event_type, payload)


@pytest.mark.parametrize(
    ("event_type", "factory", "override", "match"),
    [
        (
            EventType.CHAIN_DAMAGE_STARTED,
            _chain_started_payload,
            {"chain_base_damage": "abc"},
            "chain_base_damage必须是正整数",
        ),
        (
            EventType.CHAIN_DAMAGE_STARTED,
            _chain_started_payload,
            {"candidate_order": "甲"},
            "不能是单个字符串",
        ),
        (
            EventType.CHAIN_DAMAGE_STARTED,
            _chain_started_payload,
            {"candidate_order": ["甲", "甲"]},
            "不能包含重复元素",
        ),
        (
            EventType.CHAIN_DAMAGE_STARTED,
            _chain_started_payload,
            {"damage_type": "无属性"},
            "只能是火属性或雷属性",
        ),
        (
            EventType.CHAIN_DAMAGE_STARTED,
            _chain_started_payload,
            {"root_damage_event_id": ""},
            "非空字符串",
        ),
        (
            EventType.CHAIN_DAMAGE_STARTED,
            _chain_started_payload,
            {"source_id": 123},
            "source_id必须是非空字符串",
        ),
        (
            EventType.CHAIN_DAMAGE_STARTED,
            _chain_started_payload,
            {"original_target_id": "丙"},
            "必须与target_ids一致",
        ),
        (
            EventType.CHAIN_TARGET_RESOLVED,
            _chain_resolved_payload,
            {"target_index": "x"},
            "target_index必须是整数",
        ),
        (
            EventType.CHAIN_TARGET_RESOLVED,
            _chain_resolved_payload,
            {"chained_old": 1},
            "chained_old必须是布尔值",
        ),
        (
            EventType.CHAIN_TARGET_RESOLVED,
            _chain_resolved_payload,
            {"actual_damage": -1},
            "actual_damage必须大于等于0",
        ),
        (
            EventType.CHAIN_TARGET_RESOLVED,
            _chain_resolved_payload,
            {"chain_base_damage": "abc"},
            "chain_base_damage必须是正整数",
        ),
        (
            EventType.CHAIN_TARGET_RESOLVED,
            _chain_resolved_payload,
            {"result": "stopped_winner"},
            "stopped_winner不是生产实现值",
        ),
        (
            EventType.CHAIN_TARGET_RESOLVED,
            _chain_resolved_payload,
            {"result": "bogus"},
            "result只能是",
        ),
        (
            EventType.CHAIN_TARGET_RESOLVED,
            _chain_resolved_payload,
            {"target_id": "丙"},
            "必须与target_ids一致",
        ),
        (
            EventType.CHAIN_TARGET_RESOLVED,
            lambda: _chain_resolved_payload(),
            {"actual_damage": 0},
            "damaged结果必须满足",
        ),
        (
            EventType.CHAIN_TARGET_RESOLVED,
            lambda: _chain_resolved_payload(
                result="prevented_zero", actual=0, old=True, new=True
            ),
            {"chained_new": False},
            "prevented_zero结果必须满足",
        ),
        (
            EventType.CHAIN_TARGET_RESOLVED,
            lambda: _chain_resolved_payload(
                result="skipped_unchained", actual=0, old=False, new=False
            ),
            {"chained_new": True},
            "跳过结果必须满足",
        ),
        (
            EventType.CHAIN_DAMAGE_FINISHED,
            _chain_finished_payload,
            {"stop_reason": "not-a-real-reason"},
            "stop_reason只能是",
        ),
        (
            EventType.CHAIN_DAMAGE_FINISHED,
            _chain_finished_payload,
            {"processed_targets": "乙"},
            "不能是单个字符串",
        ),
        (
            EventType.CHAIN_DAMAGE_FINISHED,
            _chain_finished_payload,
            {"skipped_targets": ["乙", "乙"]},
            "不能包含重复元素",
        ),
        (
            EventType.CHAIN_DAMAGE_FINISHED,
            _chain_finished_payload,
            {"processed_targets": ["乙"], "skipped_targets": ["乙"]},
            "不能包含同一角色",
        ),
    ],
)
def test_chain_events_reject_invalid_values(
    event_type: EventType,
    factory: object,
    override: dict[str, object],
    match: str,
) -> None:
    payload = factory()  # type: ignore[operator]
    payload.update(override)
    with pytest.raises(ValueError, match=match):
        _chain_event(event_type, payload)


@pytest.mark.parametrize(
    ("event_type", "factory"),
    [
        (EventType.CHAIN_DAMAGE_STARTED, _chain_started_payload),
        (EventType.CHAIN_TARGET_RESOLVED, _chain_resolved_payload),
        (EventType.CHAIN_DAMAGE_FINISHED, _chain_finished_payload),
    ],
)
def test_chain_events_reject_extra_field(
    event_type: EventType, factory: object
) -> None:
    payload = factory()  # type: ignore[operator]
    payload["extra"] = "多余字段"
    with pytest.raises(ValueError, match="字段必须恰好"):
        _chain_event(event_type, payload)


# ----------------------------------------------------------------------
# 装备事件 reason 封闭枚举（CP-04K 审计残项 N1）
# ----------------------------------------------------------------------


def _equipment_event(
    event_type: EventType,
    *,
    payload: dict[str, object],
    owner: str = "p1",
) -> GameEvent:
    return GameEvent(
        event_type=event_type,
        card_instance_id="sgs-mobile-20260725-138",
        card_key="sgs_weapon_qinggangjian",
        equipment_owner=owner,
        target_ids=(owner,),
        payload=payload,
    )


def test_equipment_equipped_reason_enum_legal() -> None:
    event = _equipment_event(
        EventType.EQUIPMENT_EQUIPPED,
        payload={"slot": "weapon", "reason": "equip"},
    )
    assert event.payload["reason"] == "equip"


def test_equipment_removed_reason_enum_legal() -> None:
    event = _equipment_event(
        EventType.EQUIPMENT_REMOVED,
        payload={"slot": "weapon", "reason": "replaced"},
    )
    assert event.payload["reason"] == "replaced"


def test_equipment_replaced_has_no_reason_field() -> None:
    # 生产实现中 equipment_replaced 只有 slot/old_instance_id/new_instance_id；
    # 不为统一形式凭空增加 reason。
    event = _equipment_event(
        EventType.EQUIPMENT_REPLACED,
        payload={
            "slot": "weapon",
            "old_instance_id": "sgs-mobile-20260725-137",
            "new_instance_id": "sgs-mobile-20260725-138",
        },
    )
    assert "reason" not in event.payload
    with pytest.raises(ValueError, match="字段必须恰好"):
        _equipment_event(
            EventType.EQUIPMENT_REPLACED,
            payload={
                "slot": "weapon",
                "old_instance_id": "sgs-mobile-20260725-137",
                "new_instance_id": "sgs-mobile-20260725-138",
                "reason": "replaced",
            },
        )


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        (
            EventType.EQUIPMENT_EQUIPPED,
            {"slot": "weapon", "reason": "replaced"},
        ),
        (
            EventType.EQUIPMENT_EQUIPPED,
            {"slot": "weapon", "reason": ""},
        ),
        (
            EventType.EQUIPMENT_EQUIPPED,
            {"slot": "weapon", "reason": 123},
        ),
        (
            EventType.EQUIPMENT_REMOVED,
            {"slot": "weapon", "reason": "equip"},
        ),
        (
            EventType.EQUIPMENT_REMOVED,
            {"slot": "weapon", "reason": ""},
        ),
        (
            EventType.EQUIPMENT_REMOVED,
            {"slot": "weapon", "reason": ["replaced"]},
        ),
    ],
)
def test_equipment_events_reject_invalid_reason(
    event_type: EventType, payload: dict[str, object]
) -> None:
    with pytest.raises(ValueError, match="reason只能是"):
        _equipment_event(event_type, payload=payload)


def test_equipment_events_reject_unknown_reason() -> None:
    with pytest.raises(ValueError, match="reason只能是"):
        _equipment_event(
            EventType.EQUIPMENT_EQUIPPED,
            payload={"slot": "weapon", "reason": "borrowed_sword_gain"},
        )
    with pytest.raises(ValueError, match="reason只能是"):
        _equipment_event(
            EventType.EQUIPMENT_REMOVED,
            payload={"slot": "weapon", "reason": "destroyed"},
        )


# ---------------------------------------------------------------------
# CP-04K：装备最小事件契约（equipment_equipped / removed / replaced）
# ---------------------------------------------------------------------


def _equipment_event(
    event_type: EventType,
    *,
    instance_id: str = "sgs-mobile-20260725-138",
    card_key: str = "sgs_weapon_qinggangjian",
    equipment_owner: str = "p1",
    target: str | None = None,
    target_ids: tuple[str, ...] | None = None,
    payload: dict[str, object] | None = None,
) -> GameEvent:
    return GameEvent(
        event_type=event_type,
        card_instance_id=instance_id,
        card_key=card_key,
        equipment_owner=equipment_owner,
        target_ids=target_ids or (target or (equipment_owner or "p1"),),
        payload=payload
        or (
            {"slot": "weapon", "reason": "equip"}
            if event_type is EventType.EQUIPMENT_EQUIPPED
            else {"slot": "weapon", "reason": "replaced"}
            if event_type is EventType.EQUIPMENT_REMOVED
            else {
                "slot": "weapon",
                "old_instance_id": "sgs-mobile-20260725-001",
                "new_instance_id": "sgs-mobile-20260725-138",
            }
        ),
    )


def test_equipment_three_events_legal_construction() -> None:
    equipped = _equipment_event(EventType.EQUIPMENT_EQUIPPED)
    assert equipped.equipment_owner == "p1"
    assert equipped.target_ids == ("p1",)
    assert equipped.payload == {"slot": "weapon", "reason": "equip"}
    removed = _equipment_event(EventType.EQUIPMENT_REMOVED)
    assert removed.payload == {"slot": "weapon", "reason": "replaced"}
    replaced = _equipment_event(EventType.EQUIPMENT_REPLACED)
    assert replaced.payload["old_instance_id"] != replaced.payload["new_instance_id"]


@pytest.mark.parametrize(
    ("event_type", "override", "match"),
    [
        (EventType.EQUIPMENT_EQUIPPED, {"equipment_owner": None}, "必须提供equipment_owner"),
        (EventType.EQUIPMENT_REMOVED, {"equipment_owner": None}, "必须提供equipment_owner"),
        (EventType.EQUIPMENT_REPLACED, {"equipment_owner": None}, "必须提供equipment_owner"),
        (EventType.EQUIPMENT_EQUIPPED, {"target_ids": ("p2",)}, "只能以装备拥有者为target"),
        (EventType.EQUIPMENT_REMOVED, {"target_ids": ("p2",)}, "只能以装备拥有者为target"),
        (EventType.EQUIPMENT_REPLACED, {"target_ids": ("p2",)}, "只能以装备拥有者为target"),
        (EventType.EQUIPMENT_EQUIPPED, {"payload": {"reason": "equip"}}, "必须是正式装备栏"),
        (EventType.EQUIPMENT_REMOVED, {"payload": {"slot": "weapon"}}, "字段必须恰好为slot与reason"),
        (EventType.EQUIPMENT_REPLACED, {"payload": {"slot": "weapon"}}, "字段必须恰好为slot"),
        (EventType.EQUIPMENT_EQUIPPED, {"payload": {"slot": "hand", "reason": "equip"}}, "必须是正式装备栏"),
        (EventType.EQUIPMENT_REPLACED, {"payload": {"slot": "weapon", "old_instance_id": "a", "new_instance_id": "b", "extra": 1}}, "字段必须恰好为slot"),
    ],
)
def test_equipment_events_reject_invalid_construction(
    event_type: EventType, override: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        _equipment_event(event_type, **override)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# 判定事件契约（CP-04L）
# ----------------------------------------------------------------------


def _judgment_started_event(
    *,
    trick_id: str = "sgs-mobile-20260725-098",
    target_id: str = "p2",
    entry_index: int = 1,
    payload: dict[str, object] | None = None,
    target_ids: tuple[str, ...] | None = None,
) -> GameEvent:
    return GameEvent(
        event_type=EventType.JUDGMENT_STARTED,
        card_instance_id=trick_id,
        card_key="sgs_delayed_lebusi",
        target_ids=target_ids or (target_id,),
        payload=(
            payload
            if payload is not None
            else {
                "delayed_trick_instance_id": trick_id,
                "target_id": target_id,
                "judgment_zone_entry_index": entry_index,
            }
        ),
    )


def _judgment_result_event(
    *,
    trick_id: str = "sgs-mobile-20260725-098",
    judgment_card_id: str = "sgs-mobile-20260725-023",
    target_id: str = "p2",
    payload: dict[str, object] | None = None,
    target_ids: tuple[str, ...] | None = None,
) -> GameEvent:
    return GameEvent(
        event_type=EventType.JUDGMENT_RESULT,
        card_instance_id=judgment_card_id,
        card_key="sgs_basic_shan",
        target_ids=target_ids or (target_id,),
        payload=(
            payload
            if payload is not None
            else {
                "delayed_trick_instance_id": trick_id,
                "judgment_card_instance_id": judgment_card_id,
                "target_id": target_id,
                "suit": "♦",
                "rank": "8",
                "hit": False,
                "skipped_phase": None,
                "damage_amount": None,
                "damage_type": None,
                "effect_applied": False,
            }
        ),
    )


def _phase_skipped_event(
    *,
    trick_id: str = "sgs-mobile-20260725-098",
    player_id: str = "p2",
    skipped_phase: str = "play",
    payload: dict[str, object] | None = None,
    target_ids: tuple[str, ...] | None = None,
) -> GameEvent:
    return GameEvent(
        event_type=EventType.PHASE_SKIPPED,
        card_instance_id=trick_id,
        card_key="sgs_delayed_lebusi",
        target_ids=target_ids or (player_id,),
        payload=(
            payload
            if payload is not None
            else {
                "player_id": player_id,
                "turn_number": 2,
                "skipped_phase": skipped_phase,
                "reason": "lebusi_judgment_hit",
                "delayed_trick_instance_id": trick_id,
            }
        ),
    )


def _delayed_transferred_event(
    *,
    trick_id: str = "sgs-mobile-20260725-117",
    from_player_id: str = "p1",
    to_player_id: str = "p2",
    payload: dict[str, object] | None = None,
    target_ids: tuple[str, ...] | None = None,
) -> GameEvent:
    return GameEvent(
        event_type=EventType.DELAYED_TRICK_TRANSFERRED,
        card_instance_id=trick_id,
        card_key="sgs_delayed_shandian",
        target_ids=target_ids or (to_player_id,),
        payload=(
            payload
            if payload is not None
            else {
                "from_player_id": from_player_id,
                "to_player_id": to_player_id,
                "judgment_zone_entry_index": 2,
                "reason": "shandian_transfer",
            }
        ),
    )


def test_judgment_started_valid_contract() -> None:
    event = _judgment_started_event()
    assert event.event_type is EventType.JUDGMENT_STARTED
    assert event.target_ids == ("p2",)
    assert event.payload["judgment_zone_entry_index"] == 1


def test_judgment_result_valid_contract() -> None:
    event = _judgment_result_event()
    assert event.event_type is EventType.JUDGMENT_RESULT
    assert event.payload["judgment_card_instance_id"] == event.card_instance_id
    assert event.payload["hit"] is False
    assert event.payload["skipped_phase"] is None
    assert event.payload["damage_amount"] is None


def test_phase_skipped_valid_contract() -> None:
    event = _phase_skipped_event()
    assert event.event_type is EventType.PHASE_SKIPPED
    assert event.payload["player_id"] == event.target_ids[0]
    assert event.payload["skipped_phase"] == "play"
    draw = _phase_skipped_event(skipped_phase="draw")
    assert draw.payload["skipped_phase"] == "draw"


def test_delayed_trick_transferred_valid_contract() -> None:
    event = _delayed_transferred_event()
    assert event.event_type is EventType.DELAYED_TRICK_TRANSFERRED
    assert event.payload["to_player_id"] == event.target_ids[0]
    assert event.payload["reason"] == "shandian_transfer"
    restored = _delayed_transferred_event(
        to_player_id="p1", from_player_id="p1"
    )
    assert restored.payload["reason"] == "shandian_transfer"


@pytest.mark.parametrize(
    ("event_type", "override", "match"),
    [
        (
            EventType.JUDGMENT_STARTED,
            {"payload": {"target_id": "p2", "judgment_zone_entry_index": 1}},
            "字段必须恰好",
        ),
        (
            EventType.JUDGMENT_STARTED,
            {"payload": {"delayed_trick_instance_id": "other", "target_id": "p2", "judgment_zone_entry_index": 1}},
            "必须等于实体牌ID",
        ),
        (
            EventType.JUDGMENT_STARTED,
            {"payload": {"delayed_trick_instance_id": "sgs-mobile-20260725-098", "target_id": "p2", "judgment_zone_entry_index": True}},
            "必须是非负整数",
        ),
        (
            EventType.JUDGMENT_STARTED,
            {"target_ids": ("p2", "p1")},
            "必须且只能指定一名判定角色",
        ),
        (
            EventType.JUDGMENT_STARTED,
            {"payload": {"delayed_trick_instance_id": "sgs-mobile-20260725-098", "target_id": "p1", "judgment_zone_entry_index": 1}},
            "target_id必须等于target_ids",
        ),
        (
            EventType.JUDGMENT_RESULT,
            {"payload": {"delayed_trick_instance_id": "sgs-mobile-20260725-098", "target_id": "p2", "suit": "♦", "rank": "8", "hit": True, "skipped_phase": None, "damage_amount": None, "damage_type": None, "effect_applied": False}},
            "字段集与正式契约不一致",
        ),
        (
            EventType.JUDGMENT_RESULT,
            {"payload": {"delayed_trick_instance_id": "sgs-mobile-20260725-098", "judgment_card_instance_id": "other", "target_id": "p2", "suit": "♦", "rank": "8", "hit": False, "skipped_phase": None, "damage_amount": None, "damage_type": None, "effect_applied": False}},
            "必须等于判定牌实体ID",
        ),
        (
            EventType.JUDGMENT_RESULT,
            {"payload": {"delayed_trick_instance_id": "sgs-mobile-20260725-098", "judgment_card_instance_id": "sgs-mobile-20260725-023", "target_id": "p2", "suit": "♦", "rank": "8", "hit": 1, "skipped_phase": None, "damage_amount": None, "damage_type": None, "effect_applied": False}},
            "hit必须是布尔值",
        ),
        (
            EventType.JUDGMENT_RESULT,
            {"payload": {"delayed_trick_instance_id": "sgs-mobile-20260725-098", "judgment_card_instance_id": "sgs-mobile-20260725-023", "target_id": "p2", "suit": "♦", "rank": "8", "hit": False, "skipped_phase": "end", "damage_amount": None, "damage_type": None, "effect_applied": False}},
            "必须是draw、play或空",
        ),
        (
            EventType.JUDGMENT_RESULT,
            {"payload": {"delayed_trick_instance_id": "sgs-mobile-20260725-098", "judgment_card_instance_id": "sgs-mobile-20260725-023", "target_id": "p2", "suit": "♦", "rank": "8", "hit": False, "skipped_phase": None, "damage_amount": True, "damage_type": None, "effect_applied": False}},
            "必须是非负整数或空",
        ),
        (
            EventType.PHASE_SKIPPED,
            {"payload": {"player_id": "p2", "turn_number": 2, "skipped_phase": "play", "reason": "lebusi_judgment_hit"}},
            "字段集与正式契约不一致",
        ),
        (
            EventType.PHASE_SKIPPED,
            {"payload": {"player_id": "p1", "turn_number": 2, "skipped_phase": "play", "reason": "lebusi_judgment_hit", "delayed_trick_instance_id": "sgs-mobile-20260725-098"}},
            "必须等于target_ids",
        ),
        (
            EventType.PHASE_SKIPPED,
            {"payload": {"player_id": "p2", "turn_number": 0, "skipped_phase": "play", "reason": "lebusi_judgment_hit", "delayed_trick_instance_id": "sgs-mobile-20260725-098"}},
            "必须是正整数",
        ),
        (
            EventType.PHASE_SKIPPED,
            {"payload": {"player_id": "p2", "turn_number": 2, "skipped_phase": "draw_phase", "reason": "lebusi_judgment_hit", "delayed_trick_instance_id": "sgs-mobile-20260725-098"}},
            "必须是draw或play",
        ),
        (
            EventType.PHASE_SKIPPED,
            {"payload": {"player_id": "p2", "turn_number": 2, "skipped_phase": "play", "reason": "", "delayed_trick_instance_id": "sgs-mobile-20260725-098"}},
            "必须是非空字符串",
        ),
        (
            EventType.DELAYED_TRICK_TRANSFERRED,
            {"payload": {"to_player_id": "p2", "judgment_zone_entry_index": 2, "reason": "shandian_transfer"}},
            "字段集与正式契约不一致",
        ),
        (
            EventType.DELAYED_TRICK_TRANSFERRED,
            {"payload": {"from_player_id": "p1", "to_player_id": "p1", "judgment_zone_entry_index": 2, "reason": "shandian_transfer"}},
            "必须等于target_ids",
        ),
        (
            EventType.DELAYED_TRICK_TRANSFERRED,
            {"payload": {"from_player_id": "p1", "to_player_id": "p2", "judgment_zone_entry_index": -1, "reason": "shandian_transfer"}},
            "必须是非负整数",
        ),
        (
            EventType.DELAYED_TRICK_TRANSFERRED,
            {"payload": {"from_player_id": "p1", "to_player_id": "p2", "judgment_zone_entry_index": 2, "reason": ""}},
            "必须是非空字符串",
        ),
    ],
)
def test_judgment_events_reject_invalid_construction(
    event_type: EventType, override: dict[str, object], match: str
) -> None:
    factories = {
        EventType.JUDGMENT_STARTED: _judgment_started_event,
        EventType.JUDGMENT_RESULT: _judgment_result_event,
        EventType.PHASE_SKIPPED: _phase_skipped_event,
        EventType.DELAYED_TRICK_TRANSFERRED: _delayed_transferred_event,
    }
    with pytest.raises(ValueError, match=match):
        factories[event_type](**override)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# 防具事件契约（CP-04M）
# ----------------------------------------------------------------------


def _armor_judgment_started_event(
    *,
    armor_id: str = "sgs-mobile-20260725-045",
    target_id: str = "p2",
    response_to_card_key: str = "sgs_basic_sha",
    window_id: str = "slash:1:sgs-mobile-20260725-140",
    payload: dict[str, object] | None = None,
    target_ids: tuple[str, ...] | None = None,
) -> GameEvent:
    return GameEvent(
        event_type=EventType.ARMOR_JUDGMENT_STARTED,
        card_instance_id=armor_id,
        card_key="sgs_armor_baguazhen",
        target_ids=target_ids or (target_id,),
        payload=(
            payload
            if payload is not None
            else {
                "armor_instance_id": armor_id,
                "armor_key": "sgs_armor_baguazhen",
                "target_id": target_id,
                "response_to_card_key": response_to_card_key,
                "response_window_id": window_id,
            }
        ),
    )


def _armor_judgment_result_event(
    *,
    armor_id: str = "sgs-mobile-20260725-045",
    judgment_card_id: str = "sgs-mobile-20260725-098",
    target_id: str = "p2",
    success: bool = True,
    kind: str | None = "use_dodge",
    payload: dict[str, object] | None = None,
    target_ids: tuple[str, ...] | None = None,
) -> GameEvent:
    resolved_judgment_card_id = judgment_card_id
    if payload is not None and "judgment_card_instance_id" in payload:
        resolved_judgment_card_id = str(payload["judgment_card_instance_id"])
    return GameEvent(
        event_type=EventType.ARMOR_JUDGMENT_RESULT,
        card_instance_id=resolved_judgment_card_id,
        card_key="sgs_delayed_lebusi",
        target_ids=target_ids or (target_id,),
        payload=(
            payload
            if payload is not None
            else {
                "armor_instance_id": armor_id,
                "judgment_card_instance_id": judgment_card_id,
                "judgment_suit": "♥",
                "judgment_color": "红",
                "success": success,
                "virtual_response_kind": kind,
            }
        ),
    )


def _armor_recovered_event(
    *,
    armor_id: str = "sgs-mobile-20260725-043",
    owner_id: str = "p1",
    hp_before: int = 3,
    hp_after: int = 4,
    reason: str = "equip_replaced",
    payload: dict[str, object] | None = None,
    target_ids: tuple[str, ...] | None = None,
) -> GameEvent:
    return GameEvent(
        event_type=EventType.ARMOR_RECOVERED,
        card_instance_id=armor_id,
        card_key="sgs_armor_baiyinshizi",
        target_ids=target_ids or (owner_id,),
        payload=(
            payload
            if payload is not None
            else {
                "armor_instance_id": armor_id,
                "armor_key": "sgs_armor_baiyinshizi",
                "owner_id": owner_id,
                "hp_before": hp_before,
                "hp_after": hp_after,
                "reason": reason,
            }
        ),
    )


def _damage_prevented_event(
    *,
    victim_id: str = "p1",
    card_key: str = "sgs_basic_sha",
    declared_amount: int = 1,
    modifiers: tuple[str, ...] = ("prevented",),
    payload: dict[str, object] | None = None,
    target_ids: tuple[str, ...] | None = None,
) -> GameEvent:
    return GameEvent(
        event_type=EventType.DAMAGE_PREVENTED,
        card_instance_id="sgs-mobile-20260725-140",
        card_key=card_key,
        target_ids=target_ids or (victim_id,),
        payload=(
            payload
            if payload is not None
            else {
                "victim_id": victim_id,
                "card_key": card_key,
                "declared_amount": declared_amount,
                "final_amount": 0,
                "modifiers": list(modifiers),
                "armor_ignored": False,
            }
        ),
    )


def test_armor_judgment_started_valid_contract() -> None:
    event = _armor_judgment_started_event()
    assert event.event_type is EventType.ARMOR_JUDGMENT_STARTED
    assert event.payload["armor_instance_id"] == event.card_instance_id
    assert event.payload["target_id"] == event.target_ids[0]


def test_armor_judgment_result_valid_contract() -> None:
    event = _armor_judgment_result_event()
    assert event.event_type is EventType.ARMOR_JUDGMENT_RESULT
    assert event.payload["judgment_card_instance_id"] == event.card_instance_id
    assert event.payload["judgment_color"] == "红"
    assert event.payload["success"] is True
    failed = _armor_judgment_result_event(
        judgment_card_id="sgs-mobile-20260725-058",
        success=False,
        kind=None,
    )
    assert failed.payload["success"] is False


def test_armor_recovered_valid_contract() -> None:
    event = _armor_recovered_event()
    assert event.event_type is EventType.ARMOR_RECOVERED
    assert event.payload["owner_id"] == event.target_ids[0]
    assert event.payload["hp_after"] == event.payload["hp_before"] + 1


def test_damage_prevented_valid_contract() -> None:
    event = _damage_prevented_event()
    assert event.event_type is EventType.DAMAGE_PREVENTED
    assert event.payload["victim_id"] == event.target_ids[0]
    assert event.payload["final_amount"] == 0
    assert event.payload["declared_amount"] == 1


@pytest.mark.parametrize(
    ("event_type", "override", "match"),
    [
        (
            EventType.ARMOR_JUDGMENT_STARTED,
            {"payload": {"armor_key": "sgs_armor_baguazhen", "target_id": "p2", "response_to_card_key": "sgs_basic_sha", "response_window_id": "w"}},
            "字段必须恰好",
        ),
        (
            EventType.ARMOR_JUDGMENT_STARTED,
            {"payload": {"armor_instance_id": "other", "armor_key": "sgs_armor_baguazhen", "target_id": "p2", "response_to_card_key": "sgs_basic_sha", "response_window_id": "w"}},
            "必须等于实体牌ID",
        ),
        (
            EventType.ARMOR_JUDGMENT_STARTED,
            {"payload": {"armor_instance_id": "sgs-mobile-20260725-045", "armor_key": "sgs_armor_baguazhen", "target_id": "p1", "response_to_card_key": "sgs_basic_sha", "response_window_id": "w"}},
            "必须等于target_ids",
        ),
        (
            EventType.ARMOR_JUDGMENT_STARTED,
            {"payload": {"armor_instance_id": "sgs-mobile-20260725-045", "armor_key": "sgs_armor_baguazhen", "target_id": "p2", "response_to_card_key": "", "response_window_id": "w"}},
            "必须是非空字符串",
        ),
        (
            EventType.ARMOR_JUDGMENT_RESULT,
            {"payload": {"armor_instance_id": "sgs-mobile-20260725-045", "judgment_suit": "♥", "judgment_color": "红", "success": True, "virtual_response_kind": "use_dodge"}},
            "字段必须恰好",
        ),
        (
            EventType.ARMOR_JUDGMENT_RESULT,
            {"payload": {"armor_instance_id": "sgs-mobile-20260725-045", "judgment_card_instance_id": "sgs-mobile-20260725-045", "judgment_suit": "♣", "judgment_color": "黑", "success": False, "virtual_response_kind": None}},
            "判定牌不得与防具本体相同",
        ),
        (
            EventType.ARMOR_JUDGMENT_RESULT,
            {"payload": {"armor_instance_id": "sgs-mobile-20260725-045", "judgment_card_instance_id": "sgs-mobile-20260725-098", "judgment_suit": "♥", "judgment_color": "蓝", "success": True, "virtual_response_kind": "use_dodge"}},
            "只能是红或黑",
        ),
        (
            EventType.ARMOR_JUDGMENT_RESULT,
            {"payload": {"armor_instance_id": "sgs-mobile-20260725-045", "judgment_card_instance_id": "sgs-mobile-20260725-098", "judgment_suit": "♥", "judgment_color": "红", "success": 1, "virtual_response_kind": "use_dodge"}},
            "success必须是布尔值",
        ),
        (
            EventType.ARMOR_JUDGMENT_RESULT,
            {"payload": {"armor_instance_id": "sgs-mobile-20260725-045", "judgment_card_instance_id": "sgs-mobile-20260725-098", "judgment_suit": "♥", "judgment_color": "红", "success": True, "virtual_response_kind": None}},
            "必须是use_dodge或play_jink",
        ),
        (
            EventType.ARMOR_JUDGMENT_RESULT,
            {"payload": {"armor_instance_id": "sgs-mobile-20260725-045", "judgment_card_instance_id": "sgs-mobile-20260725-098", "judgment_suit": "♥", "judgment_color": "红", "success": False, "virtual_response_kind": "use_dodge"}},
            "失败时virtual_response_kind必须为空",
        ),
        (
            EventType.ARMOR_RECOVERED,
            {"payload": {"armor_key": "sgs_armor_baiyinshizi", "owner_id": "p1", "hp_before": 3, "hp_after": 4, "reason": "equip_replaced"}},
            "字段必须恰好",
        ),
        (
            EventType.ARMOR_RECOVERED,
            {"payload": {"armor_instance_id": "sgs-mobile-20260725-043", "armor_key": "sgs_armor_baiyinshizi", "owner_id": "p2", "hp_before": 3, "hp_after": 4, "reason": "equip_replaced"}},
            "必须等于target_ids",
        ),
        (
            EventType.ARMOR_RECOVERED,
            {"payload": {"armor_instance_id": "sgs-mobile-20260725-043", "armor_key": "sgs_armor_baiyinshizi", "owner_id": "p1", "hp_before": True, "hp_after": 4, "reason": "equip_replaced"}},
            "必须是非负整数",
        ),
        (
            EventType.ARMOR_RECOVERED,
            {"payload": {"armor_instance_id": "sgs-mobile-20260725-043", "armor_key": "sgs_armor_baiyinshizi", "owner_id": "p1", "hp_before": 3, "hp_after": 4, "reason": ""}},
            "必须是非空字符串",
        ),
        (
            EventType.DAMAGE_PREVENTED,
            {"payload": {"card_key": "sgs_basic_sha", "declared_amount": 1, "final_amount": 0, "modifiers": ["prevented"], "armor_ignored": False}},
            "字段必须恰好",
        ),
        (
            EventType.DAMAGE_PREVENTED,
            {"payload": {"victim_id": "p2", "card_key": "sgs_basic_sha", "declared_amount": 1, "final_amount": 0, "modifiers": ["prevented"], "armor_ignored": False}},
            "必须等于target_ids",
        ),
        (
            EventType.DAMAGE_PREVENTED,
            {"payload": {"victim_id": "p1", "card_key": "sgs_basic_sha", "declared_amount": 0, "final_amount": 0, "modifiers": ["prevented"], "armor_ignored": False}},
            "必须是正整数",
        ),
        (
            EventType.DAMAGE_PREVENTED,
            {"payload": {"victim_id": "p1", "card_key": "sgs_basic_sha", "declared_amount": 1, "final_amount": 1, "modifiers": ["prevented"], "armor_ignored": False}},
            "必须为0",
        ),
        (
            EventType.DAMAGE_PREVENTED,
            {"payload": {"victim_id": "p1", "card_key": "sgs_basic_sha", "declared_amount": 1, "final_amount": 0, "modifiers": [], "armor_ignored": False}},
            "不能为空",
        ),
        (
            EventType.DAMAGE_PREVENTED,
            {"payload": {"victim_id": "p1", "card_key": "sgs_basic_sha", "declared_amount": 1, "final_amount": 0, "modifiers": ["prevented"], "armor_ignored": 1}},
            "必须是布尔值",
        ),
    ],
)
def test_armor_events_reject_invalid_construction(
    event_type: EventType, override: dict[str, object], match: str
) -> None:
    factories = {
        EventType.ARMOR_JUDGMENT_STARTED: _armor_judgment_started_event,
        EventType.ARMOR_JUDGMENT_RESULT: _armor_judgment_result_event,
        EventType.ARMOR_RECOVERED: _armor_recovered_event,
        EventType.DAMAGE_PREVENTED: _damage_prevented_event,
    }
    with pytest.raises(ValueError, match=match):
        factories[event_type](**override)  # type: ignore[arg-type]
