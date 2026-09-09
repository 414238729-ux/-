"""第一轮真实故障的生产语义回归；局面设置是显式 fixture，提交仍走签名链。"""
from dataclasses import replace
import pytest

from scripts.sgs_engine.actions import ActionType, InvalidActionError, UnsupportedRuleError
from scripts.sgs_engine.model import DRAW_PILE, DISCARD_PILE, PROCESSING_ZONE, ZoneRef
from scripts.sgs_engine.production_batch import BatchActionIdController, ProductionBatchError, ProductionPhase
from scripts.sgs_engine.playable_config import GameConfig
from scripts.sgs_engine.playable_runtime import GameService, RuntimeProtocolError
from test_post_c8_information import fixture, submit


def take(core, operation, **matches):
    action = next(a for a in core.legal_actions() if a.payload.get("operation") == operation
                  and all(getattr(a, k) == v for k,v in matches.items()))
    assert action.action_id and action in core.legal_actions()
    core.step(BatchActionIdController(action.action_id))
    core.state.assert_card_conservation()
    core.assert_resolution_invariants()
    return action


def equip_fixture(core, pid, key, slot="weapon"):
    cid=next(c.instance_id for c in core.state.cards if c.card_key == key)
    core._state=core.state.move_card(cid, ZoneRef.equipment(pid,slot))
    core._reconcile_qianchong_for_all(core.state)
    return cid


def zhangba_pause():
    service,sid,session=fixture({"p1":["sgs_basic_jiu","sgs_delayed_bingliang",
        "sgs_basic_shan","sgs_basic_tao"]}, mode="duel", generals=("shamoke","soldier"))
    core=session.game.core
    equip_fixture(core,"p1","sgs_weapon_zhangbashemao")
    take(core,"use_wine_buff"); take(core,"use_bingliang")
    chosen=take(core,"use_slash")
    assert chosen.virtual_card is not None
    assert core.skill_pending.skill_id == "sgs_skill_jili"
    return core, chosen.virtual_card.material_card_instance_ids


@pytest.mark.parametrize("activate", [True,False])
def test_virtual_materials_owned_during_jili_pause_and_finished_once(activate):
    core,materials=zhangba_pause()
    assert core._pending_card_continuation.material_ids == materials
    assert all(core.state.location_of(cid)==PROCESSING_ZONE for cid in materials)
    take(core,"activate_skill" if activate else "pass_skill")
    assert core.runtime.pending_slash.material_ids == materials
    take(core,"pass_slash_response")
    assert all(core.state.location_of(cid)==DISCARD_PILE for cid in materials)
    assert core.runtime.pending_slash is None


def test_virtual_material_tamper_and_unowned_processing_still_fail_closed():
    core,materials=zhangba_pause()
    broken=core.state.move_card(materials[0], DISCARD_PILE)
    core._state=broken
    with pytest.raises(ProductionBatchError,match="虚拟材料悬空"):
        core.assert_resolution_invariants()
    core._state=broken.move_card(materials[0],PROCESSING_ZONE)
    stranger=next(cid for cid in core.state.card_ids_in(DRAW_PILE))
    core._state=core.state.move_card(stranger,PROCESSING_ZONE)
    with pytest.raises(ProductionBatchError,match="挂起根"):
        core.assert_resolution_invariants()


def test_hanbing_second_choice_refreshes_after_mingzhe_and_rejects_old_choice():
    s,sid,session=fixture({"p1":["sgs_basic_sha"],"p2":["sgs_basic_tao","sgs_basic_jiu"]},
        mode="2v2",generals=("soldier","wangyuanji"))
    core=session.game.core
    equip_fixture(core,"p1","sgs_weapon_hanbingjian")
    equip_fixture(core,"p2","sgs_mount_offensive", "attack_horse")
    equip_fixture(core,"p2","sgs_weapon_fangtianhuaji")
    take(core,"use_slash", target_ids=("p2",)); take(core,"pass_slash_response")
    take(core,"weapon_prevent_damage")
    old=next(a for a in core.legal_actions() if a.card_instance_id and
        core.state.location_of(a.card_instance_id)==ZoneRef.equipment("p2","weapon"))
    core.step(BatchActionIdController(old.action_id))
    assert core.skill_pending.skill_id == "sgs_skill_mingzhe"
    old_digest=core.runtime.pending_hanbing_discard.snapshot_digest
    take(core,"activate_skill")
    assert core.runtime.pending_hanbing_discard.step == 2
    assert core.runtime.pending_hanbing_discard.snapshot_digest != old_digest
    assert core.legal_actions()
    with pytest.raises(ProductionBatchError,match="不在当前真实合法动作集合"):
        core.step(BatchActionIdController(old.action_id))
    take(core,"hanbing_discard_card")
    assert core.phase != ProductionPhase.HANBING_DISCARD


@pytest.mark.parametrize("kind", ["response", "rescue"])
@pytest.mark.parametrize("draw_spent_card", [False,True])
def test_spent_response_and_rescue_follow_only_authoritative_reshuffle(kind,draw_spent_card):
    general="shamoke" if kind=="response" else "wangyuanji"
    response="sgs_basic_shan" if kind=="response" else "sgs_basic_tao"
    s,sid,session=fixture({"p1":["sgs_basic_sha"],"p2":[response]},mode="duel",
                        generals=("soldier",general))
    core=session.game.core
    if kind=="rescue":
        equip_fixture(core,"p2","sgs_weapon_fangtianhuaji")
        core._state=replace(core.state,players=tuple(replace(p,hp=1) if p.player_id=="p2" else p for p in core.state.players))
    # 空牌堆测试：选择只重洗刚打出的牌，或真实多张弃牌堆；不伪造实体。
    destination=ZoneRef.hand("p1") if draw_spent_card else DISCARD_PILE
    core._state=core.state.move_cards({cid:destination for cid in core.state.card_ids_in(DRAW_PILE)})
    take(core,"use_slash",target_ids=("p2",))
    if kind=="rescue":take(core,"pass_slash_response")
    # 救援顺序以生产 current_actor 为准，直到本人有桃的窗口。
    while kind=="rescue" and core.current_actor_id != "p2":take(core,"pass_rescue")
    take(core,"play_dodge" if kind=="response" else "rescue_with_peach")
    continuation=core._pending_card_continuation
    assert continuation.required_card_zone == DISCARD_PILE
    spent=continuation.card_instance_id
    take(core,"activate_skill")
    assert core._pending_card_continuation is None
    assert continuation.continuation_id in core.consumed_card_continuation_identities
    assert core.state.location_of(spent) in (DRAW_PILE,ZoneRef.hand("p2"))
    if draw_spent_card:assert core.state.location_of(spent)==ZoneRef.hand("p2")
    assert any(e.payload.get("reason")=="reshuffle" and e.card_instance_id==spent for e in core.events)
    with pytest.raises(InvalidActionError,match="duplicate"):
        core._resume_pending_card_continuation(core.state,continuation.continuation_id)


def test_spent_card_illegal_move_without_authority_is_not_rebound():
    s,sid,session=fixture({"p1":["sgs_basic_sha"],"p2":["sgs_basic_shan"]},
                        mode="duel",generals=("soldier","shamoke"))
    core=session.game.core; take(core,"use_slash"); take(core,"play_dodge")
    pending=core._pending_card_continuation
    core._state=core.state.move_card(pending.card_instance_id,ZoneRef.hand("p1"))
    # 状态 revision 不作为绕过牌区检查的理由。
    core._pending_card_continuation=replace(pending,expected_revision=core.state.revision)
    with pytest.raises(UnsupportedRuleError,match="预期牌区"):
        core._resume_pending_card_continuation(core.state,pending.continuation_id)


@pytest.mark.parametrize("seed", [0,1,2,3])
def test_c7_zuilun_legal_set_and_apply_have_same_phase(seed):
    s=GameService(); sid=s.create_game(GameConfig(mode="identity8_heir",seed=seed,
        control="AI_VS_AI",ai_seed=10,mulligan=True,max_steps=360))
    for _ in range(8):
        if s.get_result(sid)["status"]!="IN_PROGRESS":break
        s.advance_until_human_or_terminal(sid,max_steps=64,time_slice_ms=10000)
    session=s._sessions[sid]
    assert s.get_result(sid)["status"] in ("WIN","DRAW","ABORTED")
    assert any(e.payload.get("skill_id")=="sgs_skill_zuilun" for e in session.game.core.events)
    assert session.accepted > 96


@pytest.mark.parametrize("path", ["loyalist", "ambitionist"])
def test_playable_c7_conversion_uses_shared_engine_hook_at_turn_boundary(path):
    s,sid,session=fixture({},mode="identity8_heir",generals=("soldier",))
    core=session.game.core; variant=core.mode_policy._variant
    spy=next(p for p,role in variant.role_current.items() if role=="spy")
    variant.spy_path_chooser_id=spy; variant.spy_path_choice=path
    variant.spy_path_locked=True; variant.spy_path_pending=True
    core._runtime=replace(core.runtime,phase=ProductionPhase.END)
    take(core,"end_turn")
    assert variant.role_current[spy]==path and not variant.spy_path_pending
    events=[e for e in core.events if e.event_type.value=="identity_revealed"]
    assert any(e.payload.get("identity")==path for e in events)


def test_frozen_verifier_rejects_current_development_bytes_and_pin_is_separate():
    from pathlib import Path
    from scripts.current_post_c8_implementation_pin import FROZEN_C8_IDENTITY, POST_C8_CURRENT_IMPLEMENTATION_IDENTITY
    from scripts.sgs_engine.formal_duel import implementation_identity
    from scripts.sgs_engine import c8_bounded_timed_8p_trace_v1 as frozen
    assert implementation_identity()==POST_C8_CURRENT_IMPLEMENTATION_IDENTITY
    assert POST_C8_CURRENT_IMPLEMENTATION_IDENTITY != FROZEN_C8_IDENTITY
    with pytest.raises(frozen.C8FTraceError,match="AUDITED_HASH_DRIFT"):
        frozen.audited_dependency_snapshot_v1(Path(__file__).resolve().parents[1])
