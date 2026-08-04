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
