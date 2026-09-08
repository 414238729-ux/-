# -*- coding: utf-8 -*-
"""G-local private C6 recorder and exact production/timed composition.

Private serializers are used only by PrivateIncrementalC6RecorderV1. No live
token is serialized. Full replay uses the unchanged controller-neutral C6
production V1 verifier; bounded replay has a separate, non-promotable scope.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping

from . import c8_timed_8p_full_game_contract_v1 as contract
from . import c8_timed_8p_full_game_replay_v1 as replay
from . import production_replay as c6
from . import formal_duel
from .mode_identity import FormalEightPlayerIdentitySession, FormalEightPlayerIdentityConfiguration
from .production_batch import BatchActionIdController
from .events import EventType
from .model import DRAW_PILE, ZoneRef


class C8G3CompositionMismatch(replay.C8G1ReplaySemanticError):
    pass


C8_G3_BOUNDED_SCHEMA = "sgs-c8-g-bounded-production-timed-replay-test-v2"
C8_G3_BOUNDED_SCOPE = "BOUNDED_VERIFIER_TEST_ONLY"
C8_G3_FULL_GAME_STATUS = "IMPLEMENTED_PROVISIONAL_NOT_EXECUTED_ON_FULL_GAME"
R2_TEST_ONLY_SCHEMA = "R2_TARGETED_TEST_ONLY_PRODUCTION_INTEGRATION_V1"
R2_TEST_ONLY_ENVELOPE_TYPE = "R2TestOnlyEvidenceEnvelopeV1"
R2_TEST_ONLY_RESULT_TYPE = "R2TestOnlyCompositionResultV1"
R2_TEST_ONLY_SCOPE = "TARGETED_PRODUCTION_INTEGRATION_ONLY"
R2_TEST_ONLY_TASK = "C8_G3_TEST_ONLY_R2_EVIDENCE_LANE_IMPLEMENTATION_V1"
R2_TEST_ONLY_FACTORY_ID = "ExplicitTestOnlyFixtureFactoryV1"
R2_TEST_ONLY_FACTORY_SCHEMA = "R2TestOnlyFixtureFactoryDescriptorV1"
R2_TEST_ONLY_SETUP_SCHEMA = "R2TestOnlyFixtureSetupV1"
R2_TEST_ONLY_PRIVATE_SCHEMA = "R2TestOnlyTrustedPrivateArtifactV1"
R2_TEST_ONLY_PUBLIC_SCHEMA = "R2TestOnlyPublicProjectionV1"
R2_TEST_ONLY_RESULT_TOKEN = object()
R2_TEST_ONLY_BOUNDARIES = (
    "NOT_NATURAL_PRODUCTION_COVERAGE",
    "NOT_FULL_GAME_EVIDENCE",
)
R2_TEST_ONLY_RECIPE = "MOVE_DRAW_TOP_TO_LORD_HAND_ONCE"
R2_TEST_ONLY_FACTORY_DESCRIPTOR = {
    "schema": R2_TEST_ONLY_FACTORY_SCHEMA,
    "version": 1,
    "factory_id": R2_TEST_ONLY_FACTORY_ID,
    "constructor": "create_canonical_c6_no_skill_session_v1",
    "recipe": R2_TEST_ONLY_RECIPE,
    "scope": R2_TEST_ONLY_SCOPE,
    "trusted_descriptor": True,
}
E_AUDIT_REFERENCE_V1 = {'scope': 'C8_RESPONSE_WINDOW_OPTIONAL_ACTIVATION_E_TARGETED_INDEPENDENT_AUDIT_PASSED', 'report_path': 'C:\\Users\\ASUS\\.codex\\visualizations\\2026\\09\\07\\01a07bee-e98c-7183-adc3-ca0dc46a45b5\\e-audit-r1\\FINAL_GROK_REPORT.md', 'report_sha256': 'ed8417ab05e04d3ba69df3a2d7cda23cf43fc5e28229308c8628f82221371f6a', 'adapter_contract_identity': '17fd08db5270dfa2b7ccbbdc973ce61643d296a3b94158c8fc8a15a7f5138a8c', 'audited_e_source_sha256': '50147fd7abbbff86459f38fa0ab19e0571599b0e9f66efd007bbec466f64c647', 'audited_e_test_sha256': 'fe4514d92ff94707f1639b0b428e821362aa2ede79ba0d06fcae22a2a0e84012', 'audited_e_development_identity': '71e2e6b16d6c12cd1724f08f1a400c78f91a41af8026c944680b8e8fa1dd586e', "superseded_binding": {
    "scope": "STEP1362_SLASH_RESPONSE_E_TARGETED_INDEPENDENT_AUDIT_PASSED",
    "report_path": "C:\\Users\\ASUS\\.codex\\visualizations\\2026\\09\\06\\01a0751d-b33e-7a21-9b32-5c137cb143b5\\c8-step1362-mapping-rebind-v1\\grok-e-targeted-audit\\STEP1362_SLASH_RESPONSE_E_TARGETED_INDEPENDENT_AUDIT_REPORT.md",
    "report_sha256": "82a8f271271f37ee5ff696ed5d8364df72336d9f6fe435b3b9b6c6f7aa665e6c",
    "adapter_contract_identity": contract.C8_G1_E_CONTRACT_IDENTITY,
    "audited_e_source_sha256": "86db1cde329c328f84a50accf72cded10eb50f676bb04e8c9f9da6f0e42ae5ba",
    "audited_e_test_sha256": "ce3117d3547d9552933e397dfb9d685576b1f1507fbc8fc51b79eee80d809369",
    "audited_e_development_identity": "9821c844b014e63e7b5c2889bf03ae319f8c6acf334bb66d2d9c0afe67bb2c8b",
    "historical_audit": {
        "adapter_contract_identity": contract.C8_G1_E_CONTRACT_IDENTITY,
        "audited_e_development_identity": "51991dfc073a723c9fd62568c1836359900360cdfec2577c06c6b2e2f27986e7",
        "audited_e_source_sha256": "1b56952e34941d96c13b8f0d70e1cafc9f4b7db3c13d9461a3f8e122b63737ad",
        "audited_e_test_sha256": "266a012990f47168306c8f7a5095711261a060686733aeea872abd73f7868f8a",
        "historical_audit": {
            "adapter_contract_identity": contract.C8_G1_E_CONTRACT_IDENTITY,
            "report_sha256": "7ba22ad980695e9818c0f3d36b0ef3efb1b7d165215b7dc33fce1feb1eccdd26",
            "scope": "C8_E_INDEPENDENT_TARGETED_AUDIT_PASSED",
            "validity": "VALID_FOR_OLD_E_IDENTITY_ONLY"
        },
        "report_path": "C:\\Users\\ASUS\\.codex\\visualizations\\2026\\09\\05\\01a07352-caf8-7f13-8730-3e77154127a3\\c8-w592-g1-f-e-rebind-v1\\basetemp\\grok-e-audit-01\\E_W592_MAPPING_TARGETED_INDEPENDENT_AUDIT_REPORT.md",
        "report_sha256": "baf797cd958d2c1dd03810637e7d5268f8759f6de0287ecd0e5d35400f2ad1ac",
        "scope": "E_W592_MAPPING_TARGETED_INDEPENDENT_AUDIT_PASSED",
        "validity": "VALID_FOR_OLD_E_IDENTITY_ONLY"
    }
}}

PRIVATE_SCHEMA = "sgs-c8-g-private-incremental-c6-record-v1"
_SHARED_HASHES = {'scripts/sgs_engine/production_replay.py': '42f12af9dec319ceca695cbc006779371b59b5381d0bc6ded4d574485ec0e390', 'scripts/sgs_engine/production_batch.py': 'ed90625615c01e185ab03948c466b3779867d5f78187bb557660e08b6e5f089b', 'scripts/sgs_engine/mode_identity.py': '8ba10885af4d8d84e5433b533c8c0a2448cc3b8b51a3c418aa618f86f0aa555d', 'scripts/sgs_engine/actions.py': '7157cd4cae3e48d8c5109e821b37c1becc48d191d2fb5efa04e8541867cd1ff2', 'scripts/sgs_engine/model.py': '986d6a7f028cb27309d6a657d5c5fb8fa24cf508865bb98a30948b238e405480', 'scripts/sgs_engine/engine.py': '32d9c614b772b905a37c4ee8e46c509615599f8f98337fb9ccc0185523538445', 'scripts/sgs_engine/rng.py': '66257cc2d44c66a2749fbe3029a590e892447e90a422cace063a0e7f974b39a5', 'scripts/sgs_engine/authoritative_no_skill_full_game.py': '1cbab5fb0772e827a9d1387061e9637e011e961945c81b43eb2a70addcd15a96'}
_SHARED_HASHES["scripts/sgs_engine/events.py"] = "d3ec00f2b74e1363fe985334d0b4377d7f73813ead8b0aaec65cfb76bad49e90"
_G3_PATHS = ("scripts/sgs_engine/c8_timed_8p_full_game_production_replay_v1.py",
             "tests/test_c8_timed_8p_full_game_production_replay_v1.py")


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sha_file(path: Path) -> str:
    from . import c8_timed_replay_version_compatibility_v1 as compatibility
    producer_digest = compatibility.execution_source_digest_v1(path)
    if producer_digest is not None:
        return producer_digest
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_c8_g3_development_snapshot_v1(repo_root: Path | str | None = None) -> dict[str, object]:
    from . import c8_timed_replay_version_compatibility_v1 as compatibility
    from . import c8_timed_8p_full_game_runner_v1 as runner
    root = _root() if repo_root is None else Path(repo_root).resolve()
    if not _SHARED_HASHES:
        raise C8G3CompositionMismatch("G3 dependency guard未冻结")
    dependencies = {name: _sha_file(root/name) for name in _SHARED_HASHES}
    replay.exact_equal_v3(dependencies, _SHARED_HASHES, "G3 private serializer/shared dependency bytes")
    prior = runner.current_c8_g2_development_snapshot_v1(root)
    material = {"schema": "sgs-c8-g3-development-identity-v2", "prior": prior,
                "shared_source_sha256": dependencies,
                "source_test_sha256": {p: _sha_file(root/p) for p in _G3_PATHS},
                "descriptor": "EXACT_C6_V1_PLUS_FRESH_GROUPED_TIMED_FLAT_SEQUENCE_PUBLIC_INDUCTION_V2",
                "supersedes_current_identity": "246c686bdb51afb788fbbfc8c475b76f6ba4074c31e784dc1b288786d7de1beb",
                "execution_order_profile": "HASH_SEED_0_BEFORE_START_EXACT_BUILD_EXECUTABLE_SLOT_ORDER",
                "audited_e_prerequisite": E_AUDIT_REFERENCE_V1}
    identity = contract.identity_v1(material)
    return {**material, "development_identity": identity,
            "current_c8_implementation_identity": contract.identity_v1({
                "schema": "sgs-c8-g3-current-implementation-v2", "g2": prior["current_c8_implementation_identity"],
                "g3": identity}),
            "global_source_identity": compatibility.execution_global_identity_v1() or formal_duel.implementation_identity()}


def _hash(value: object) -> str:
    return contract.identity_v1(value)


def _equal(a: object, b: object, label: str) -> None:
    replay.exact_equal_v3(a, b, label)


def _detached(value: object) -> object:
    return json.loads(contract.canonical_json_bytes_v1(value))


def _factory_descriptor_v1() -> dict[str, object]:
    return _detached(R2_TEST_ONLY_FACTORY_DESCRIPTOR)  # type: ignore[return-value]


class ExplicitTestOnlyFixtureFactoryV1:
    """The only trusted factory accepted by the R2 test-only dispatch seam.

    It starts from the canonical C6 constructor and applies one immutable
    ``GameState.move_card`` setup before any recorder, B, E, G1 choice, or
    accepted step exists.  The private moved-card ID stays in the trusted
    envelope and is never supplied to the driver.
    """

    __slots__ = ("_last_setup",)

    def __init__(self) -> None:
        self._last_setup: dict[str, object] | None = None

    @staticmethod
    def descriptor_v1() -> dict[str, object]:
        return _factory_descriptor_v1()

    def create_bundle(self, *, seed: int, run_label: str) -> Any:
        from . import c8_timed_8p_full_game_runner_v1 as runner
        from . import c8_c6_production_adapter_v1 as production_adapter
        if type(seed) is not int or isinstance(seed, bool) or seed != 0:
            raise C8G3CompositionMismatch("R2 factory仅允许canonical seed0")
        session = production_adapter.create_canonical_c6_no_skill_session_v1(seed)
        setup = self.prepare_session_v1(session, seed=seed)
        self._last_setup = setup
        bundle = runner._assemble_bundle_v3(session, seed=seed, run_label=run_label)
        if type(bundle).__name__ != "CanonicalSessionBundleV1":
            raise C8G3CompositionMismatch("R2 factory必须返回exact canonical bundle")
        return bundle

    def setup_evidence_v1(self) -> dict[str, object]:
        if self._last_setup is None:
            raise C8G3CompositionMismatch("R2 factory setup evidence尚未由constructor产生")
        return _detached(self._last_setup)  # type: ignore[return-value]

    def prepare_session_v1(self, session: FormalEightPlayerIdentitySession, *, seed: int) -> dict[str, object]:
        if type(session) is not FormalEightPlayerIdentitySession:
            raise C8G3CompositionMismatch("R2 factory只接受exact canonical C6 session")
        if type(seed) is not int or isinstance(seed, bool) or seed != 0:
            raise C8G3CompositionMismatch("R2 factory仅允许canonical seed0")
        if session.step_count != 0 or session.is_finished or session.phase.value != "prepare":
            raise C8G3CompositionMismatch("R2 setup必须发生在step0 prepare")
        if session.analysis_only is not False or session.skill_runtime is not None:
            raise C8G3CompositionMismatch("R2 setup不允许analysis/skill runtime")
        actor = session.lord_player_id
        zone = ZoneRef.hand(actor)
        before = session.state
        if len(before.card_ids_in(zone)) != 4:
            raise C8G3CompositionMismatch("R2 setup要求lord初始手牌恰为4")
        draw_ids = before.card_ids_in(DRAW_PILE)
        if not draw_ids:
            raise C8G3CompositionMismatch("R2 setup要求draw pile存在top card")
        if session.formal_result_eligible is not True:
            raise C8G3CompositionMismatch("canonical constructor在fixture前必须formal eligible")
        moved = draw_ids[0]
        before_identity = c6._game_state_hash(session)
        # This is the single trusted fixture mutation.  The state remains
        # immutable; no private snapshot, anchor, RNG, or step counter is edited.
        session._state = before.move_card(moved, zone)
        session.state.assert_card_conservation()
        if session.step_count != 0 or len(session.state.card_ids_in(zone)) != 5:
            raise C8G3CompositionMismatch("R2 setup未形成4到5手牌转换")
        if session.state.players_by_id[actor].hp != 5:
            raise C8G3CompositionMismatch("R2 setup改变了非目标初始HP")
        if session.formal_result_eligible is not False:
            raise C8G3CompositionMismatch("R2 setup必须真实导致formal_result_eligible=false")
        setup = {
            "schema": R2_TEST_ONLY_SETUP_SCHEMA,
            "version": 1,
            "factory_id": R2_TEST_ONLY_FACTORY_ID,
            "scope": R2_TEST_ONLY_SCOPE,
            "fixture_applied": True,
            "recipe": R2_TEST_ONLY_RECIPE,
            "seed": seed,
            "actor_id": actor,
            "initial_step_count": 0,
            "initial_hand_before": 4,
            "initial_hand_after": 5,
            "required_discard_count": 2,
            "formal_result_eligible": False,
            "before_state_identity": before_identity,
            "after_state_identity": c6._game_state_hash(session),
            "private": {"moved_card_instance_id": moved},
        }
        setup["setup_commitment"] = _hash({k: v for k, v in setup.items() if k != "setup_commitment"})
        return _detached(setup)  # type: ignore[return-value]


def _validate_fixture_setup_v1(value: object, *, seed: int) -> dict[str, object]:
    d = replay._object(value,
        "schema version factory_id scope fixture_applied recipe seed actor_id initial_step_count initial_hand_before initial_hand_after required_discard_count formal_result_eligible before_state_identity after_state_identity private setup_commitment",
        "R2 fixture setup")
    expected = {
        "schema": R2_TEST_ONLY_SETUP_SCHEMA, "version": 1,
        "factory_id": R2_TEST_ONLY_FACTORY_ID, "scope": R2_TEST_ONLY_SCOPE,
        "fixture_applied": True, "recipe": R2_TEST_ONLY_RECIPE, "seed": seed,
        "initial_step_count": 0, "initial_hand_before": 4,
        "initial_hand_after": 5, "required_discard_count": 2,
        "formal_result_eligible": False,
    }
    for key, expected_value in expected.items():
        _equal(d[key], expected_value, "R2 fixture setup "+key)
    for key in ("actor_id", "before_state_identity", "after_state_identity"):
        replay._text(d[key], "R2 fixture setup "+key)
    private = replay._exact_keys(d["private"], frozenset({"moved_card_instance_id"}), "R2 fixture private setup")
    replay._text(private["moved_card_instance_id"], "R2 moved card instance")
    _equal(d["setup_commitment"], _hash({k: v for k, v in d.items() if k != "setup_commitment"}), "R2 fixture setup commitment")
    return d


class PrivateIncrementalC6RecorderV1:
    """Read-only observer of exact C6 material, with no authority to choose/submit.

    Only this recorder uses _context()/the C6 context serializer and the initial
    RNG serializer. The observation is detached data; it never enters G1/C input.
    """

    def __init__(self, session: FormalEightPlayerIdentitySession, *, seed: int, max_steps: int,
                 test_only: bool = False) -> None:
        if type(session) is not FormalEightPlayerIdentitySession or session.analysis_only is not False or session.skill_runtime is not None:
            raise C8G3CompositionMismatch("private recorder只允许exact canonical C6")
        if type(test_only) is not bool:
            raise C8G3CompositionMismatch("private recorder test-only flag必须是bool")
        if session.step_count != 0 or session.is_finished:
            raise C8G3CompositionMismatch("private recorder必须从canonical step_count=0开始")
        self.session = session
        self.seed = seed
        self.max_steps = max_steps
        self.test_only = test_only
        self.pending = None
        self.decisions = []
        self.counters = []
        self.successful_rescues = []
        self.initial = self._header()
        self.private = {"schema": c6.AUTHORITATIVE_PRIVATE_SCHEMA,
                        "session_id": session.session_id, "session_secret_hex": session.session_secret_hex}
        self._diagnostic_sample_v1((), self.initial["initial_event_count"], self.initial["initial_rng_call_count"])

    def _diagnostic_sample_v1(self, delta_events: tuple, event_count: int, rng_count: int) -> None:
        """Reuse the recorder's accepted event boundary; only aggregate allowlisted facts escape."""
        s = self.session
        players = s.state.players_by_id
        alive_hp = [p.hp for p in players.values() if p.alive]
        effects = {"damage_events": 0, "damage_amount": 0, "dying_events": 0, "death_events": 0,
                   "hp_recover_events": 0, "hp_recover_amount": 0, "successful_rescues": 0}
        for event in delta_events:
            if event.event_type is EventType.DAMAGE:
                effects["damage_events"] += 1
                effects["damage_amount"] += event.amount
            elif event.event_type is EventType.DYING:
                effects["dying_events"] += 1
            elif event.event_type is EventType.DEATH:
                effects["death_events"] += 1
            elif event.event_type is EventType.HP_RECOVER:
                effects["hp_recover_events"] += 1
                effects["hp_recover_amount"] += event.payload["amount"]
        effects["successful_rescues"] = sum(e["inner_decision_index"] == s.step_count-1 for e in self.successful_rescues[-8:])
        public = {"accepted_step_count": s.step_count, "state_revision": s.state.revision,
            "event_count": event_count, "rng_count": rng_count, "alive_count": len(alive_hp),
            "alive_hp_sum": sum(alive_hp), "alive_hp_min": min(alive_hp) if alive_hp else None,
            "alive_hp_max": max(alive_hp) if alive_hp else None,
            "dying_count": sum(p.alive and p.hp <= 0 for p in players.values()), "effects_delta": effects}
        private = {"per_player_hp": {pid: p.hp for pid, p in players.items()},
            "execution_identity": self.decisions[-1]["execution_after_sha256"] if self.decisions else self.initial["initial_execution_hash"],
            "state_identity": self.decisions[-1]["state_after_sha256"] if self.decisions else self.initial["initial_game_state_hash"]}
        self._diagnostic_bytes = contract.canonical_json_bytes_v1({"public": public, "private": private})

    def diagnostic_boundary_v1(self) -> bytes:
        """Detached immutable reporting data; the sink receives no session/driver references."""
        return self._diagnostic_bytes

    @staticmethod
    def cold_session(private_record: Mapping[str, object]) -> FormalEightPlayerIdentitySession:
        from .c8_timed_8p_full_game_runner_v1 import validate_execution_order_profile_v1
        validate_execution_order_profile_v1()
        header = private_record["header"]
        private = private_record["authoritative_private"]
        config = header["initial_configuration"]["formal_eight_player_identity_configuration"]
        trusted = FormalEightPlayerIdentityConfiguration.from_canonical_profile_value(config)
        return FormalEightPlayerIdentitySession(seed=header["seed"], configuration=trusted,
                   analysis_only=False, session_id=private["session_id"],
                   session_secret=bytes.fromhex(private["session_secret_hex"]))

    def _header(self) -> dict[str, object]:
        s = self.session
        rules = c6._ruleset_value(s)
        deck = c6._deck_definition(s.formal_registry.records)
        configuration = {"formal_eight_player_identity_configuration": s.formal_configuration.to_dict(),
                         "physical_player_ids": list(s.physical_player_ids),
                         "identities": {key: role.value for key, role in s.identities_by_player.items()},
                         "numbered_player_order": list(s.numbered_player_order), "lord_player_id": s.lord_player_id,
                         "analysis_only": False, "max_steps": self.max_steps}
        return {"schema_version": c6.REEXECUTION_SCHEMA, "engine_version": c6.ENGINE_VERSION,
                # The outer lane flag does not change the canonical native C6 header.
                "mode_id": s.mode_id, "test_only": False, "formal_result": s.formal_result_eligible,
                "production_basic_cards_batch": True, "ruleset_version": rules["ruleset_version"],
                "ruleset_hash": rules["ruleset_hash"], "registry_fingerprint": rules["registry_fingerprint"],
                "initial_configuration": configuration, "deck_definition": deck, "deck_hash": c6.sha256_value(deck),
                "seed": self.seed, "initial_rng_state": s._rng.export_initial_state(),
                "initial_rng_state_sha256": s._rng.initial_state_sha256,
                "initial_rng_call_count": len(s.rng_calls), "initial_event_count": len(s.events),
                "initial_execution_hash": c6._execution_hash(s), "initial_game_state_hash": c6._game_state_hash(s),
                "fixture_applied": False}

    def before(self) -> None:
        s = self.session
        if self.pending is not None or s.is_finished or s.step_count != len(self.decisions):
            raise C8G3CompositionMismatch("private recorder pending/index错误")
        context = c6._context_value(s._context())
        legal = [c6._action_value(action) for action in s.legal_actions()]
        self.pending = {"index": len(self.decisions), "context": context, "context_sha256": c6.sha256_value(context),
                        "legal_actions": legal, "legal_action_set_sha256": c6.sha256_value(legal),
                        "state_before_sha256": c6._game_state_hash(s), "execution_before_sha256": c6._execution_hash(s),
                        "event_start": len(s.events), "rng_start": len(s.rng_calls)}
        self.pending_revision = s.state.revision
        self.pending_rescue_hp = ({pid: player.hp for pid, player in s.state.players_by_id.items()}
                                 if context["phase"] == "dying_rescue" else {})

    def compare_initial(self, recorded: Mapping[str, object]) -> None:
        """Check canonical initialization and its independent event/RNG offsets before any action."""
        _equal(self.initial, recorded["header"], "fresh canonical initial header")
        _equal(c6._event_values(self.session), recorded["events"][:self.initial["initial_event_count"]], "initial event stream")
        _equal(c6._rng_values(self.session), recorded["random_consumptions"][:self.initial["initial_rng_call_count"]], "initial RNG stream")

    def after(self, signed_action_id: str) -> tuple[dict[str, object], dict[str, int]]:
        s = self.session
        if self.pending is None or s.step_count != len(self.decisions)+1:
            raise C8G3CompositionMismatch("recorder无法逐个取证accepted step，禁止折叠callback")
        chosen = [a for a in self.pending["legal_actions"] if a["action_id"] == signed_action_id]
        if len(chosen) != 1:
            raise C8G3CompositionMismatch("committed signed action不在fresh完整合法集")
        accepted_events = s.events
        accepted_rng_count = len(s.rng_calls)
        decision = {**self.pending, "chosen_action_id": signed_action_id, "chosen_action": chosen[0],
                    "state_after_sha256": c6._game_state_hash(s), "execution_after_sha256": c6._execution_hash(s),
                    "rng_end": accepted_rng_count, "event_end": len(accepted_events)}
        counters = {"pre_revision": self.pending_revision, "post_revision": s.state.revision,
                    "pre_step_count": s.step_count-1, "post_step_count": s.step_count}
        self.decisions.append(decision)
        self.counters.append(counters)
        # Successful rescue is a separate actual HP transition, never inferred from a child timer.
        for target in chosen[0]["target_ids"]:
            before_hp = self.pending_rescue_hp.get(target)
            after_player = s.state.players_by_id[target]
            if before_hp is not None and before_hp <= 0 and after_player.hp >= 1 and after_player.alive:
                evidence = {"schema": "sgs-c8-g-successful-rescue-v1", "inner_decision_index": decision["index"],
                            "inner_decision_identity": _hash(decision), "target_id": target,
                            "pre_hp": before_hp, "post_hp": after_player.hp}
                self.successful_rescues.append({**evidence, "evidence_identity": _hash(evidence)})
        self._diagnostic_sample_v1(accepted_events[self.pending["event_start"]:], len(accepted_events), accepted_rng_count)
        self.pending = None
        return decision, counters

    def finish(self) -> dict[str, object]:
        if self.pending is not None:
            raise C8G3CompositionMismatch("recorder pending step禁止封装成功")
        s = self.session
        events = c6._event_values(s)
        rng = c6._rng_values(s)
        chain = list(c6._build_event_hash_chain(events))
        outcome = None
        inner = None
        if s.is_finished:
            s.assert_finished_state_invariants()
            # Use the public execution export for terminal fields; never inspect/mutate _runtime.
            snapshot = s.execution_snapshot
            runtime = snapshot["runtime"]
            reason = runtime["game_over_reason"] or s.outcome_policy.finish_reason
            outcome = {"winner_id": s.winner_id, "finish_reason": reason, "step_count": s.step_count,
                       "turn_count": runtime["turn_number"], "decision_count": len(self.decisions),
                       "random_consumption_count": len(rng), "event_count": len(events),
                       "event_chain_tip": chain[-1], "final_execution_hash": c6._execution_hash(s),
                       "final_game_state_hash": c6._game_state_hash(s)}
            inner = c6.ProductionReexecutionReplay(header=self.initial, decisions=tuple(self.decisions),
                       random_consumptions=tuple(rng), events=tuple(events), event_hash_chain=tuple(chain),
                       outcome=outcome, authoritative_private=self.private, player_visible=False).to_dict()
        material = {"schema": PRIVATE_SCHEMA, "header": self.initial, "authoritative_private": self.private,
                    "decisions": self.decisions, "counters": self.counters, "random_consumptions": rng,
                    "events": events, "event_hash_chain": chain, "outcome": outcome, "inner_full_game_record": inner}
        material["successful_rescue_evidence"] = self.successful_rescues
        # Detach all values so future recorder activity cannot alter an already issued artifact.
        return json.loads(contract.canonical_json_bytes_v1({**material, "record_identity": _hash(material)}))


def _validate_private_record_common(value: object, *, full_game: bool, seed: int,
                                    max_steps: int, expected_formal_result: bool) -> dict[str, object]:
    d = replay._object(value, "schema header authoritative_private decisions counters random_consumptions events event_hash_chain outcome inner_full_game_record successful_rescue_evidence record_identity", "private C6 record")
    if d["schema"] != PRIVATE_SCHEMA:
        raise C8G3CompositionMismatch("private incremental schema mismatch")
    _equal(d["record_identity"], _hash({k:v for k,v in d.items() if k != "record_identity"}), "private record hash")
    h = replay._exact_keys(d["header"], frozenset(c6._HEADER_FIELDS), "C6 header")
    for key in ("seed", "initial_rng_call_count", "initial_event_count"):
        replay._integer(h[key], "C6 header "+key)
    for key, expected in (("schema_version", c6.REEXECUTION_SCHEMA), ("engine_version", c6.ENGINE_VERSION),
                          ("mode_id", contract.C8_G1_BASE_MODE_ID), ("fixture_applied", False),
                          ("test_only", False), ("formal_result", expected_formal_result),
                          ("production_basic_cards_batch", True), ("seed", seed)):
        _equal(h[key], expected, "C6 header "+key)
    config = replay._object(h["initial_configuration"], "formal_eight_player_identity_configuration physical_player_ids identities numbered_player_order lord_player_id analysis_only max_steps", "C6 canonical configuration")
    _equal(config["formal_eight_player_identity_configuration"], FormalEightPlayerIdentityConfiguration.formal_profile().to_dict(), "C6 trusted profile")
    _equal(config["analysis_only"], False, "C6 analysis_only")
    _equal(config["max_steps"], max_steps, "C6 step guard")
    private = replay._object(d["authoritative_private"], "schema session_id session_secret_hex", "private signing material")
    _equal(private["schema"], c6.AUTHORITATIVE_PRIVATE_SCHEMA, "private signing schema")
    replay._text(private["session_id"], "session id")
    secret = replay._text(private["session_secret_hex"], "private secret")
    if len(secret) != 64 or any(ch not in "0123456789abcdef" for ch in secret):
        raise C8G3CompositionMismatch("private secret不是canonical 32-byte hex")
    decisions = replay._exact_list(d["decisions"], "private decisions")
    counters = replay._exact_list(d["counters"], "private counters")
    if not decisions or len(decisions) != len(counters) or len(decisions) > max_steps:
        raise C8G3CompositionMismatch("private decisions/counters count mismatch")
    for i, decision in enumerate(decisions):
        replay._exact_keys(decision, frozenset(c6._DECISION_FIELDS), "C6 decision")
        _equal(decision["index"], i, "C6 ordered index")
        context = replay._object(decision["context"], "mode phase actor_id turn_player_id response_window_id expected_revision metadata", "C6 context")
        replay._integer(context["expected_revision"], "context revision")
        for action in [*replay._exact_list(decision["legal_actions"], "C6 legal tuple"), decision["chosen_action"]]:
            replay._object(action, "action_id action_type actor_id card_instance_id virtual_card target_ids skill_id payload", "C6 action")
        for key in ("event_start", "event_end", "rng_start", "rng_end"):
            replay._integer(decision[key], key)
        c = replay._object(counters[i], "pre_revision post_revision pre_step_count post_step_count", "actual counters")
        for key in c:
            replay._integer(c[key], key)
        _equal(c["pre_step_count"], i, "pre step count")
        _equal(c["post_step_count"], i+1, "post step count")
        _equal(decision["context_sha256"], c6.sha256_value(decision["context"]), "C6 context commitment")
        _equal(decision["legal_action_set_sha256"], c6.sha256_value(decision["legal_actions"]), "C6 ordered legal commitment")
        _equal(decision["context"]["expected_revision"], c["pre_revision"], "C6 actual revision")
        if c["post_revision"] < c["pre_revision"]:
            raise C8G3CompositionMismatch("C6 committed revision倒退")
    _equal(d["event_hash_chain"], list(c6._build_event_hash_chain(d["events"])), "C6 event chain")
    for event in replay._exact_list(d["events"], "C6 events"):
        fields = "card_instance_id card_key card_user damage_source equipment_owner event_type kill_credit material_card_instance_ids payload sequence skill_owner target_ids"
        if event.get("event_type") == "damage":
            # C6's DamageEvent extends the GameEvent wire record with these exact fields.
            fields += " target_id amount damage_type"
            replay._integer(event.get("amount"), "damage amount", minimum=1)
            replay._text(event.get("damage_type"), "damage type")
            _equal(event.get("target_ids"), [event.get("target_id")], "damage target binding")
        replay._object(event, fields, "C6 event")
        replay._integer(event["sequence"], "event sequence")
    for call in replay._exact_list(d["random_consumptions"], "C6 RNG calls"):
        replay._object(call, "arguments index method result", "C6 RNG call")
        replay._integer(call["index"], "RNG call index")
    for rescue in replay._exact_list(d["successful_rescue_evidence"], "successful rescue evidence"):
        replay._object(rescue, "schema inner_decision_index inner_decision_identity target_id pre_hp post_hp evidence_identity", "successful rescue")
        _equal(rescue["schema"], "sgs-c8-g-successful-rescue-v1", "rescue schema")
        index = replay._integer(rescue["inner_decision_index"], "rescue decision index")
        if index >= len(decisions) or type(rescue["pre_hp"]) is not int or rescue["pre_hp"] > 0:
            raise C8G3CompositionMismatch("successful rescue起点不合法")
        replay._integer(rescue["post_hp"], "rescue post HP", minimum=1)
        replay._text(rescue["target_id"], "rescue target")
        _equal(rescue["inner_decision_identity"], _hash(decisions[index]), "rescue action binding")
        _equal(rescue["evidence_identity"], _hash({k:v for k,v in rescue.items() if k != "evidence_identity"}), "rescue commitment")
    if full_game:
        inner = c6.ProductionReexecutionReplay.from_dict(d["inner_full_game_record"])
        for key in ("header", "authoritative_private", "decisions", "random_consumptions", "events", "event_hash_chain", "outcome"):
            _equal(inner.to_dict()[key], d[key], "full inner exact binding "+key)
    elif d["outcome"] is not None or d["inner_full_game_record"] is not None:
        raise C8G3CompositionMismatch("bounded prefix不得制造terminal/旧full verifier PASS")
    return d


def _validate_private_record(value: object, *, full_game: bool, seed: int, max_steps: int) -> dict[str, object]:
    """Formal-only private record wrapper."""
    return _validate_private_record_common(value, full_game=full_game, seed=seed,
                                           max_steps=max_steps, expected_formal_result=True)


def _validate_test_only_private_record(value: object, *, full_game: bool, seed: int,
                                       max_steps: int) -> dict[str, object]:
    """Private record validator for the R2 lane; it never grants formal eligibility."""
    if full_game is not False:
        raise C8G3CompositionMismatch("test-only private record不得进入full-game scope")
    return _validate_private_record_common(value, full_game=False, seed=seed,
                                           max_steps=max_steps, expected_formal_result=False)


def _validate_timed_private(timed: Mapping[str, object]) -> None:
    from . import c8_timed_8p_full_game_runner_v1 as runner
    from . import c8_timed_session_runtime_v1 as bmod
    from . import c8_timeout_controller_integration_v1 as cmod
    from . import c8_virtual_time_contract_v1 as amod
    steps = runner.flat_step_records_v4(timed)
    progress_steps = {}
    for i, raw in enumerate(timed["private_timed_transcript"]):
        p = replay._object(raw, "runtime_events controller_events security_before security_after controller_result e_legal_snapshot e_issuance due", "private timed material")
        decision = steps[i]["decision"]
        binding = decision["binding"]
        events = [bmod.RuntimeEventV1.from_dict(v) for v in replay._exact_list(p["runtime_events"], "runtime events")]
        controllers = [cmod.ControllerEventV1.from_public_dict_v1(v) for v in replay._exact_list(p["controller_events"], "controller events")]
        for label, values in (("runtime", events), ("controller", controllers)):
            bounds = binding[label+"_event_range"]
            _equal(bounds["end"]-bounds["start"], len(values), label+"event range")
        forwards = [v for v in events if v.inner_transition_identity is not None]
        continued = decision["completion"]["kind"] == "ON_TIME_OBLIGATION_CONTINUED"
        closes = [v for v in events if v.event_kind.value in {"WINDOW_CLOSED_BY_ACTION", "WINDOW_CLOSED_BY_TIMEOUT", "MULTI_STEP_CONTINUED"}]
        if len(forwards) != 1 or len(closes) != 1:
            raise C8G3CompositionMismatch("B forward与CONTINUE/CLOSE不唯一")
        _equal(closes[0].event_kind.value, "MULTI_STEP_CONTINUED" if continued else "WINDOW_CLOSED_BY_ACTION" if decision["kind"] == replay.ON_TIME_KIND else "WINDOW_CLOSED_BY_TIMEOUT", "B actual disposition kind")
        if events.index(forwards[0]) >= events.index(closes[0]):
            raise C8G3CompositionMismatch("B disposition必须在真实forward之后")
        _equal(closes[0].event_identity, binding["window_disposition_ref"], "actual B disposition event")
        for label in ("security_before", "security_after"):
            audit = _security_audit_from_dict(p[label])
            _equal(audit["guard_active"], False, "outside callback guard")
            _equal(audit["authorizing_capability_exposed"], False, "no exported capability")
        if decision["kind"] == replay.ON_TIME_KIND:
            if any(p[key] is not None for key in ("controller_result", "e_legal_snapshot", "e_issuance", "due")) or controllers:
                raise C8G3CompositionMismatch("on-time private material不得伪造timeout authority")
            _equal(decision["normal_forward"]["inner_transition_identity"], forwards[0].inner_transition_identity, "normal B transition")
            _equal(decision["normal_forward"]["runtime_forward_event_identity"], forwards[0].event_identity, "normal B forward event")
            if continued:
                _equal(closes[0].logical_step_identity, decision["completion"]["logical_step_identity"], "B continued logical step")
                ids = progress_steps.setdefault(binding["window_id"], [])
                ids.append(closes[0].logical_step_identity)
                window = timed["window_records"][binding["global_window_index"]-1]["opened_window"]
                progress = bmod.LogicalObligationProgressV1.build(window_id=window["window_id"],
                    window_binding_identity=window["window_binding_identity"], obligation_identity=window["obligation_identity"],
                    next_step_index=len(ids), step_identities=tuple(ids))
                _equal(progress.progress_identity, decision["completion"]["progress_identity"], "fresh B continuation progress identity")
                if closes[0].execution_receipt_identity is not None:
                    raise C8G3CompositionMismatch("on-time continuation不允许timeout receipt")
            else:
                _equal(decision["completion"]["closed_window_identity"], closes[0].window_state_identity, "normal B closed window")
            continue
        result = cmod.TimeoutControllerResultV1.from_public_dict_v1(p["controller_result"])
        due = bmod.TimeoutDueCommitmentV1.from_dict(p["due"])
        if len(result.selected_actions) != 1 or len(result.receipt_identities) != 1:
            raise C8G3CompositionMismatch("current E必须唯一实际timeout receipt")
        selected = result.selected_actions[0]
        link = decision["b_timeout_receipt_link"]
        for v in (selected.receipt_identity, result.receipt_identities[0], forwards[0].execution_receipt_identity, closes[0].execution_receipt_identity):
            _equal(link["receipt_identity"], v, "actual C/B receipt attribution")
        _equal(link["c_result_identity"], result.result_identity, "actual C result")
        _equal(link["c_selected_action_identity"], _hash(selected.to_public_dict_v1()), "actual C selected action")
        _equal(link["timeout_due_identity"], due.commitment_identity, "actual B due")
        _equal(link["runtime_forward_event_identity"], forwards[0].event_identity, "actual B timeout forward")
        _equal(link["signed_action_id_commitment"], _hash({"production_signed_action_id": selected.signed_action_id}), "actual C signed action")
        if not any(v.receipt_identity == selected.receipt_identity for v in controllers):
            raise C8G3CompositionMismatch("C event trace缺实际B receipt lineage")
        snapshot_data = dict(replay._exact_keys(p["e_legal_snapshot"], frozenset(cmod.AdapterPublicLegalActionsSnapshotV1.__dataclass_fields__), "E legal snapshot"))
        snapshot_data["public_legal_set"] = amod.PublicLegalSetProjectionV1.from_dict(snapshot_data["public_legal_set"])
        snapshot = cmod.AdapterPublicLegalActionsSnapshotV1(**snapshot_data)
        legal = decision["fresh_public_legal_set_and_canonical_order"]
        _equal(legal["snapshot_identity"], snapshot.snapshot_identity, "actual E legal snapshot")
        _equal(legal["canonical_order_identity"], snapshot.canonical_public_ordering_identity, "actual E canonical ordering")
        issuance_fields = set(cmod.SignedActionIssuanceEvidenceV1.__dataclass_fields__) - {"external_capability"}
        issuance = replay._exact_keys(p["e_issuance"], frozenset(issuance_fields | {"serialized_live_authority"}), "non-authorizing E issuance body")
        _equal(issuance["serialized_live_authority"], False, "no serialized E authority")
        _equal(issuance["obligation_completed"], True, "current E close-only profile")
        _equal(issuance["issuance_identity"], _hash({k:v for k,v in issuance.items() if k not in {"issuance_identity", "serialized_live_authority"}}), "actual E issuance identity")
        e = decision["e_fresh_confirmation_and_issuance_evidence"]
        _equal(selected.issuance_evidence_identity, issuance["issuance_identity"], "C/E issuance link")
        for key, actual in (("issuance_identity", issuance["issuance_identity"]), ("candidate_identity", issuance["candidate_identity"]),
                            ("public_ordinal", issuance["public_ordinal"]), ("legal_set_identity", issuance["legal_set_identity"]),
                            ("canonical_order_identity", issuance["canonical_public_ordering_identity"]),
                            ("timeout_due_identity", issuance["timeout_due_commitment_identity"]),
                            ("ledger_before_identity", issuance["issuance_security_ledger_before_identity"]),
                            ("ledger_after_identity", issuance["issuance_security_ledger_after_identity"])):
            _equal(e[key], actual, "E public/internal "+key)
        _equal(issuance["signed_action_id"], selected.signed_action_id, "E/C exact signed action")
        _equal(issuance["signed_action_id_commitment"], cmod.signed_action_id_commitment_v1(selected.signed_action_id), "E original commitment domain")
        security = decision["security_operation_evidence"]
        for tag in ("before", "after"):
            _equal(security[tag+"_identity"], _hash(p["security_"+tag]), "security operation transcript")
            _equal(security[tag+"_epoch"], p["security_"+tag]["operation_attempt_epoch"], "security exact epoch")


def _security_audit_from_dict(value: object) -> dict[str, object]:
    from . import c8_timed_session_runtime_v1 as bmod
    audit = replay._object(value, "schema contract_version runtime_contract_identity runtime_instance_identity operation_attempt_epoch operation_attempt_chain_tip guard_active next_guard_generation authorizing_capability_exposed audit_identity", "security audit")
    _equal(audit["contract_version"], 1, "security audit version")
    _equal(audit["authorizing_capability_exposed"], False, "no exported capability")
    bmod.ControllerCallbackSecurityAuditV1(**{k:v for k,v in audit.items() if k != "authorizing_capability_exposed"})
    return audit


def _validate_r2_call_trace_v1(value: object) -> list[dict[str, object]]:
    calls = replay._exact_list(value, "R2 B/E/C6 call trace")
    expected: list[dict[str, object]] = []
    for count in (4, 5, 6):
        methods = ("B_NORMAL_FORWARD", "E_APPLY_SIGNED_ACTION_ID", "C6_STEP")
        for index, method in enumerate(methods):
            expected.append({"event": "call", "method": method,
                "stack": list(methods[:index+1]), "pre_step_count": count})
    for index, item in enumerate(calls):
        d = replay._exact_keys(item, frozenset({"event", "method", "stack", "pre_step_count"}),
                               f"R2 call trace[{index}]")
        _equal(d, expected[index] if index < len(expected) else None,
               f"R2 exact B/E/C6 call trace[{index}]")
    _equal(calls, expected, "R2 exact B/E/C6 call trace")
    return calls


def _validate_r2_timed_semantics_v1(timed: Mapping[str, object], setup: Mapping[str, object],
                                    call_trace: object) -> list[dict[str, object]]:
    """Targeted R2 semantics, after the detached G2 structural parser."""
    from . import c8_timed_8p_full_game_runner_v1 as runner
    _equal(timed["full_game"], False, "R2 timed full_game")
    _equal(timed["promotion"], False, "R2 timed promotion")
    _equal(timed["test_only"], True, "R2 timed test_only")
    _equal(timed["private_production_record"]["header"]["formal_result"], False,
           "R2 native C6 formal eligibility")
    _equal(timed["private_production_record"]["header"]["test_only"], False,
           "R2 native C6 test_only frozen false")
    _equal(setup["after_state_identity"], timed["private_production_record"]["header"]["initial_game_state_hash"],
           "R2 fixture-to-recorder initial state")
    windows = replay._exact_list(timed["window_records"], "R2 windows")
    steps = runner.flat_step_records_v4(timed)
    _equal(len(windows), 6, "R2 exact bounded windows")
    _equal(len(steps), 8, "R2 exact accepted steps")
    discard_windows = [w for w in windows if w["context"]["phase"] == "discard"]
    _equal(len(discard_windows), 1, "R2 single discard window")
    window = discard_windows[0]
    _equal(window["sequence"], 5, "R2 discard window sequence")
    window_steps = window["steps"]
    _equal(len(window_steps), 3, "R2 discard step count")
    private = timed["private_production_record"]
    inner = private["decisions"][4:7]
    operations = [item["chosen_action"]["payload"]["operation"] for item in inner]
    _equal(operations, ["select_discard_card", "select_discard_card", "discard_phase_submit"],
           "R2 exact SELECT SELECT COMMIT")
    if inner[0]["chosen_action"]["card_instance_id"] == inner[1]["chosen_action"]["card_instance_id"]:
        raise C8G3CompositionMismatch("R2两次SELECT不得选择同一private card")
    _equal([sum(action["payload"].get("operation") == "unselect_discard_card"
                 for action in item["legal_actions"]) for item in inner], [0, 1, 2],
           "R2 reversal counts")
    _equal([len(item["legal_actions"]) for item in inner], [7, 7, 8], "R2 eligible set sizes")
    if any(action["payload"].get("excess_count") != 2 for action in inner[0]["legal_actions"]):
        raise C8G3CompositionMismatch("R2 discard excess count不是2")
    bindings = [item["decision"]["binding"] for item in window_steps]
    _equal([b["production_action_ref"]["executed_public_ordinal"] for b in bindings], [0, 0, 7],
           "R2 ordinal progression")
    for local, step in enumerate(window_steps):
        liveness = step["decision"]["liveness"]
        if liveness is None:
            raise C8G3CompositionMismatch("R2 discard step缺少public liveness")
        before, after = liveness["before"], liveness["after"]
        _equal(before["candidate_count"], 7, "R2 candidate count")
        _equal(before["certified_selected_progress_count"], local, "R2 q before")
        _equal(after["certified_selected_progress_count"], min(local+1, 2), "R2 q after")
        _equal(after["stage"], "DONE" if local == 2 else "SELECTING", "R2 liveness stage")
        _equal(step["completion"]["disposition"], "CLOSED_BY_ACTION" if local == 2 else "CONTINUED",
               "R2 continuation disposition")
        _equal(bindings[local]["pre_step_count"], 4+local, "R2 pre step count")
        _equal(bindings[local]["post_step_count"], 5+local, "R2 post step count")
    _equal(window_steps[1]["decision"]["liveness"]["after"]["certified_required_count"], 2,
           "R2 required discard count")
    commit_options = [index for index, action in enumerate(inner[2]["legal_actions"])
                      if action["payload"].get("operation") == "discard_phase_submit"]
    _equal(commit_options, [7], "R2 unique COMMIT ordinal")
    _equal(window_steps[-1]["post_state"]["phase"], "end", "R2 committed phase")
    events = private["events"][inner[-1]["event_start"]:inner[-1]["event_end"]]
    _equal(sum(event["event_type"] == "card_discarded" for event in events), 2, "R2 discarded card count")
    for b in bindings[1:]:
        if b["window_authority_ref_identity"] != bindings[0]["window_authority_ref_identity"]:
            raise C8G3CompositionMismatch("R2 continuation ref漂移")
    _equal(len({b["window_authority_ref_identity"] for b in bindings}), 1, "R2 same opening ref")
    _equal(len({b["opening_production_context_identity"] for b in bindings}), 1, "R2 same opening context")
    _equal(len({b["deadline_at"] for b in bindings}), 1, "R2 same deadline")
    _equal(len({b["decision_tick"] for b in bindings}), 1, "R2 same decision tick")
    _equal(len({b["actor_id"] for b in bindings}), 1, "R2 same actor")
    _equal(len({b["production_context_identity"] for b in bindings}), 3, "R2 fresh context identities")
    _equal(bindings[0]["deadline_at"], 497, "R2 exact deadline")
    _equal(bindings[0]["decision_tick"], 496, "R2 exact tick")
    for step in window_steps[1:]:
        if {operation["name"] for operation in step["operations"]}.intersection(
                {"OPEN", "REFRESH", "ADVANCE", "DUE", "RESOLVE"}):
            raise C8G3CompositionMismatch("R2 continuation重新OPEN/REFRESH/ADVANCE/timeout")
    _equal(len({step["decision"]["liveness"]["before"]["logical_obligation_identity"]
                for step in window_steps}), 1, "R2 obligation identity")
    runtime_events = [event for raw in timed["private_timed_transcript"] for event in raw["runtime_events"]]
    _equal(sum(event["event_kind"] == "WINDOW_OPENED" for event in runtime_events), 6, "R2 B open count")
    _equal(sum(event["event_kind"] == "MULTI_STEP_CONTINUED" for event in runtime_events), 2, "R2 B continuation count")
    _equal([w["sequence"] for w in windows if w["steps"][0]["decision"]["kind"] == replay.TIMEOUT_KIND], [4],
           "R2 timeout schedule")
    for raw in timed["private_timed_transcript"][4:7]:
        if any(raw[key] is not None for key in ("e_legal_snapshot", "e_issuance", "due", "controller_result")):
            raise C8G3CompositionMismatch("R2 on-time continuation携带timeout authority")
        _equal(raw["controller_events"], [], "R2 on-time continuation controller events")
    successor = windows[5]
    _equal(successor["relation"], contract.WindowRelationEvidenceV3.independent_decision_v3().to_dict(),
           "R2 END independent successor relation")
    _equal(successor["steps"][0]["decision"]["driver_decision"]["actual_timeout"], False,
           "R2 successor independent decision")
    calls = _validate_r2_call_trace_v1(call_trace)
    return calls


def _r2_public_setup_v1(setup: Mapping[str, object]) -> dict[str, object]:
    return {key: _detached(value) for key, value in setup.items() if key != "private"}


def _r2_public_projection_v1(timed: Mapping[str, object], setup: Mapping[str, object],
                             call_trace: object, sequence: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema": R2_TEST_ONLY_PUBLIC_SCHEMA,
        "version": 1,
        "scope": R2_TEST_ONLY_SCOPE,
        "trace_scope": R2_TEST_ONLY_SCOPE,
        "test_only": True,
        "formal_result_eligible": False,
        "formal_result": False,
        "natural": False,
        "full_game": False,
        "promotion": False,
        "baseline": False,
        "matrix": False,
        "terminal_expected": False,
        "fixture_setup": _r2_public_setup_v1(setup),
        "timed_artifact": _detached(timed["public_projection"]),
        "call_trace": _detached(call_trace),
        "ordered_production_sequence": _detached(sequence),
        "ordered_production_sequence_identity": replay.ordered_production_sequence_identity_v1(sequence),
    }


def build_test_only_evidence_envelope_v1(timed: object, setup: object, call_trace: object,
                                         *, repo_root: Path | str | None = None) -> dict[str, object]:
    """Build the isolated R2 envelope; this is not a formal/full-game artifact."""
    from . import c8_timed_8p_full_game_runner_v1 as runner
    parsed_timed = runner.test_only_timed_artifact_from_dict_v1(timed, repo_root=repo_root)
    parsed_setup = _validate_fixture_setup_v1(setup, seed=parsed_timed["seed"])
    sequence = replay.ordered_production_sequence_v1(
        [step["decision"] for step in runner.flat_step_records_v4(parsed_timed)])
    _validate_r2_timed_semantics_v1(parsed_timed, parsed_setup, call_trace)
    private = {
        "schema": R2_TEST_ONLY_PRIVATE_SCHEMA,
        "fixture_setup": parsed_setup,
        "timed_artifact": parsed_timed,
    }
    public = _r2_public_projection_v1(parsed_timed, parsed_setup, call_trace, sequence)
    envelope = {
        "schema": R2_TEST_ONLY_SCHEMA,
        "version": 1,
        "envelope_type": R2_TEST_ONLY_ENVELOPE_TYPE,
        "task": R2_TEST_ONLY_TASK,
        "scope": R2_TEST_ONLY_SCOPE,
        "trace_scope": R2_TEST_ONLY_SCOPE,
        "boundaries": list(R2_TEST_ONLY_BOUNDARIES),
        "test_only": True,
        "formal_result_eligible": False,
        "formal_result": False,
        "natural": False,
        "full_game": False,
        "promotion": False,
        "baseline": False,
        "matrix": False,
        "terminal_expected": False,
        "production_authority": "FRESH_TEST_ONLY_COMPOSITION_ONLY",
        "factory": _factory_descriptor_v1(),
        "trusted_private_artifact": private,
        "public_projection": public,
        "call_trace": _detached(call_trace),
        "ordered_production_sequence": sequence,
        "ordered_production_sequence_identity": replay.ordered_production_sequence_identity_v1(sequence),
    }
    envelope["artifact_identity"] = _hash(envelope)
    return _detached(envelope)  # type: ignore[return-value]


_R2_ENVELOPE_FIELDS = frozenset({
    "schema", "version", "envelope_type", "task", "scope", "trace_scope", "boundaries",
    "test_only", "formal_result_eligible", "formal_result", "natural", "full_game", "promotion",
    "baseline", "matrix", "terminal_expected", "production_authority", "factory",
    "trusted_private_artifact", "public_projection", "call_trace", "ordered_production_sequence",
    "ordered_production_sequence_identity", "artifact_identity",
})


def r2_test_only_evidence_from_dict_v1(value: object, *, repo_root: Path | str | None = None) -> dict[str, object]:
    """Detached R2 parser.  It never rehydrates a live session or receipt owner."""
    from . import c8_timed_8p_full_game_runner_v1 as runner
    d = replay._strict_json(value) if type(value) in {str, bytes} else replay._exact_dict(value, "R2 envelope")
    replay._validate_json_tree(d, "R2 envelope")
    replay._reject_forbidden_keys(d, replay._SERIALIZED_LIVE_KEYS, "R2 envelope")
    d = replay._exact_keys(d, _R2_ENVELOPE_FIELDS, "R2 envelope root")
    expected = {
        "schema": R2_TEST_ONLY_SCHEMA, "version": 1, "envelope_type": R2_TEST_ONLY_ENVELOPE_TYPE,
        "task": R2_TEST_ONLY_TASK, "scope": R2_TEST_ONLY_SCOPE, "trace_scope": R2_TEST_ONLY_SCOPE,
        "boundaries": list(R2_TEST_ONLY_BOUNDARIES), "test_only": True,
        "formal_result_eligible": False, "formal_result": False, "natural": False,
        "full_game": False, "promotion": False, "baseline": False, "matrix": False,
        "terminal_expected": False, "production_authority": "FRESH_TEST_ONLY_COMPOSITION_ONLY",
    }
    for key, expected_value in expected.items():
        _equal(d[key], expected_value, "R2 envelope "+key)
    _equal(d["factory"], _factory_descriptor_v1(), "R2 trusted factory descriptor")
    private = replay._exact_keys(d["trusted_private_artifact"],
        frozenset({"schema", "fixture_setup", "timed_artifact"}), "R2 trusted private artifact")
    _equal(private["schema"], R2_TEST_ONLY_PRIVATE_SCHEMA, "R2 private artifact schema")
    setup = _validate_fixture_setup_v1(private["fixture_setup"], seed=0)
    timed = runner.test_only_timed_artifact_from_dict_v1(private["timed_artifact"], repo_root=repo_root)
    sequence = replay.ordered_production_sequence_v1(
        [step["decision"] for step in runner.flat_step_records_v4(timed)])
    _equal(d["ordered_production_sequence"], sequence, "R2 envelope ordered sequence")
    _equal(d["ordered_production_sequence_identity"], replay.ordered_production_sequence_identity_v1(sequence),
           "R2 envelope sequence identity")
    _validate_r2_timed_semantics_v1(timed, setup, d["call_trace"])
    replay._reject_forbidden_keys(d["public_projection"], replay._PUBLIC_FORBIDDEN_KEYS,
                                  "R2 public projection")
    _equal(d["public_projection"], _r2_public_projection_v1(timed, setup, d["call_trace"], sequence),
           "R2 public allowlist")
    _equal(d["artifact_identity"], _hash({key: item for key, item in d.items() if key != "artifact_identity"}),
           "R2 envelope hash")
    return d


def _full_material_bindings_v3(timed: Mapping[str, object]) -> dict[str, object]:
    from .c8_timed_8p_full_game_runner_v1 import flat_step_records_v4
    private = timed["private_production_record"]
    return {
        "initial_production_material": {"schema": replay.C8_G1_INITIAL_SCHEMA, "contract_version": contract.C8_G1_CONTRACT_VERSION,
            "canonical_origin_step_count": 0, "header_identity": _hash(private["header"])},
        "inner_production_replay": {"schema": replay.C8_G1_INNER_BINDING_SCHEMA, "contract_version": contract.C8_G1_CONTRACT_VERSION,
            "c6_replay_schema": c6.REEXECUTION_SCHEMA, "inner_replay_identity": private["inner_full_game_record"]["record_sha256"],
            "decision_identities": [_hash(v) for v in private["decisions"]]},
        "authoritative_private": {"schema": replay.C8_G1_PRIVATE_SCHEMA, "contract_version": contract.C8_G1_CONTRACT_VERSION,
            "private_record_identity": private["record_identity"]},
        "production_steps": [{"schema": replay.C8_G1_STEP_SCHEMA, "contract_version": contract.C8_G1_CONTRACT_VERSION,
            "decision_evidence_identity": w["decision"]["evidence_identity"], "binding": w["decision"]["binding"],
            "completion": w["completion"]} for w in flat_step_records_v4(timed)],
        "outer_timed_windows": [{"schema": replay.C8_G1_WINDOW_SCHEMA, "contract_version": contract.C8_G1_CONTRACT_VERSION,
            "record_identity": w["record_identity"], "relation": w["relation"]} for w in timed["window_records"]],
        "public_projection": {"schema": replay.C8_G1_PUBLIC_PROJECTION_SCHEMA, "contract_version": contract.C8_G1_CONTRACT_VERSION,
            "timed_public_projection": timed["public_projection"]},
    }


def build_composition_artifact_v1(timed: object, *, repo_root: Path | str | None = None) -> dict[str, object]:
    from . import c8_timed_replay_version_compatibility_v1 as compatibility
    compatibility.reject_recording_v1()
    from . import c8_timed_8p_full_game_runner_v1 as runner
    raw = replay._exact_dict(timed, "typed timed artifact")
    full_game = replay._boolean(raw["full_game"], "full_game")
    d = runner.timed_artifact_from_dict_v3(raw, full_game=full_game, repo_root=repo_root)
    sequence = replay.ordered_production_sequence_v1([w["decision"] for w in runner.flat_step_records_v4(d)])
    material = {"schema": contract.C8_G1_REPLAY_SCHEMA if full_game else C8_G3_BOUNDED_SCHEMA,
                "contract_version": contract.C8_G1_CONTRACT_VERSION if full_game else 2,
                "scope": "FULL_GAME_REAL_PRODUCTION_TRACE" if full_game else C8_G3_BOUNDED_SCOPE,
                "full_game": full_game, "promotion": False,
                "cell_id": contract.canonical_cell_id_v1(d["seed"]) if full_game else "C8G3-BOUNDED-TEST-000",
                "g3_binding": current_c8_g3_development_snapshot_v1(repo_root),
                "timed_artifact": d, "ordered_production_sequence": sequence,
                "ordered_production_sequence_identity": replay.ordered_production_sequence_identity_v1(sequence)}
    if full_game:
        material.update(_full_material_bindings_v3(d))
    material["artifact_identity"] = _hash(material)
    return preflight_composition_v1(material, full_game=full_game, repo_root=repo_root)


def preflight_composition_v1(value: object, *, full_game: bool,
                            repo_root: Path | str | None = None) -> dict[str, object]:
    from . import c8_timed_8p_full_game_runner_v1 as runner
    d = replay._strict_json(value) if type(value) in {str, bytes} else replay._exact_dict(value, "composition")
    replay._validate_json_tree(d, "composition")
    replay._reject_forbidden_keys(d, replay._SERIALIZED_LIVE_KEYS, "composition")
    fields = "schema contract_version scope full_game promotion cell_id g3_binding timed_artifact ordered_production_sequence ordered_production_sequence_identity artifact_identity"
    if full_game:
        fields += " initial_production_material inner_production_replay authoritative_private production_steps outer_timed_windows public_projection"
    d = replay._object(d, fields, "composition root")
    for key, expected in (("schema", contract.C8_G1_REPLAY_SCHEMA if full_game else C8_G3_BOUNDED_SCHEMA),
                          ("contract_version", contract.C8_G1_CONTRACT_VERSION if full_game else 2), ("full_game", full_game), ("promotion", False),
                          ("scope", "FULL_GAME_REAL_PRODUCTION_TRACE" if full_game else C8_G3_BOUNDED_SCOPE)):
        _equal(d[key], expected, "current composition "+key)
    _equal(d["g3_binding"], current_c8_g3_development_snapshot_v1(repo_root), "G3 current source/profile/serializer identity")
    timed = runner.timed_artifact_from_dict_v3(d["timed_artifact"], full_game=full_game, repo_root=repo_root)
    if timed["test_only"] is not False:
        raise C8G3CompositionMismatch("TEST_ONLY factory不得进入production composition verifier")
    _equal(d["cell_id"], contract.canonical_cell_id_v1(timed["seed"]) if full_game else "C8G3-BOUNDED-TEST-000", "cell id")
    sequence = replay.ordered_production_sequence_v1([w["decision"] for w in runner.flat_step_records_v4(timed)])
    _equal(d["ordered_production_sequence"], sequence, "ordered production sequence")
    _equal(d["ordered_production_sequence_identity"], replay.ordered_production_sequence_identity_v1(sequence), "ordered production sequence hash")
    _validate_timed_private(timed)
    if full_game:
        for key, expected in _full_material_bindings_v3(timed).items():
            _equal(d[key], expected, "G1 full-game v3 binding "+key)
    _equal(d["artifact_identity"], _hash({k:v for k,v in d.items() if k != "artifact_identity"}), "composition artifact identity")
    return d


def finalize_test_only_timed_artifact_v1(value: object, *, fixture_factory: object,
                                         repo_root: Path | str | None = None) -> dict[str, object]:
    """Explicit runner dispatch target for a test-only timed artifact.

    The gate is intentionally independent from ``preflight_composition_v1``:
    it requires the exact factory type, then reconstructs the canonical C6
    session and reapplies the frozen setup before comparing the private header.
    """
    from . import c8_timed_8p_full_game_runner_v1 as runner
    if type(fixture_factory) is not ExplicitTestOnlyFixtureFactoryV1:
        raise C8G3CompositionMismatch("R2 finalizer需要exact trusted fixture factory")
    timed = runner.test_only_timed_artifact_from_dict_v1(value, repo_root=repo_root)
    private = timed["private_production_record"]
    session = PrivateIncrementalC6RecorderV1.cold_session(private)
    setup = fixture_factory.prepare_session_v1(session, seed=timed["seed"])
    recorder = PrivateIncrementalC6RecorderV1(
        session, seed=timed["seed"], max_steps=timed["construction"]["max_steps"], test_only=True
    )
    recorder.compare_initial(private)
    _equal(private["header"]["test_only"], False, "R2 finalizer native C6 test_only frozen false")
    _equal(private["header"]["formal_result"], False, "R2 finalizer formal eligibility")
    _equal(setup["after_state_identity"], private["header"]["initial_game_state_hash"],
           "R2 finalizer fixture state")
    return timed


def _fresh_inner(d: Mapping[str, object]) -> dict[str, object]:
    from . import c8_timed_8p_full_game_runner_v1 as runner
    from . import c8_c6_production_adapter_v1 as production
    timed = d["timed_artifact"]
    private = timed["private_production_record"]
    runner.validate_execution_order_profile_v1(timed["construction"]["execution_order_profile"])
    _validate_private_record(private, full_game=d["full_game"], seed=timed["seed"], max_steps=timed["construction"]["max_steps"])
    if d["full_game"]:
        # Full-game authority remains the original unmodified production V1 verifier.
        c6.reexecute_production_replay(c6.ProductionReexecutionReplay.from_dict(private["inner_full_game_record"]))
    session = PrivateIncrementalC6RecorderV1.cold_session(private)
    recorder = PrivateIncrementalC6RecorderV1(session, seed=timed["seed"], max_steps=timed["construction"]["max_steps"])
    recorder.compare_initial(private)
    public_adapter = production.C8C6ProductionAdapterV1(session)
    actual_families = []
    # The incremental path additionally records actual revision/step domains absent from C6 V1.
    for i, stored in enumerate(private["decisions"]):
        recorder.before()
        for key, fresh in recorder.pending.items():
            _equal(stored[key], fresh, "fresh inner pre-step "+key)
        chosen = next((a for a in session.legal_actions() if a.action_id == stored["chosen_action_id"]), None)
        if chosen is None:
            raise C8G3CompositionMismatch("fresh inner action不在完整legal tuple")
        actual_families.append(runner._family_for_public_action(chosen, public_adapter.observe_production_decision_context_v1()))
        executed = session.step(BatchActionIdController(chosen.action_id))
        _equal(executed.action_id, chosen.action_id, "fresh inner executed action")
        actual, counters = recorder.after(executed.action_id)
        _equal(actual, stored, "fresh inner decision material")
        _equal(counters, private["counters"][i], "fresh inner actual revision/steps")
    fresh = recorder.finish()
    _equal(fresh, private, "fresh inner complete state/event/RNG record")
    _equal(session.is_finished, d["full_game"], "fresh inner terminal")
    actual_sequence = []
    for i, actual in enumerate(fresh["decisions"]):
        ordinal = next(j for j, action in enumerate(actual["legal_actions"]) if action["action_id"] == actual["chosen_action_id"])
        actual_sequence.append({"cell_execution_identity": timed["cell_execution_identity"],
            "inner_decision_index": i, "step_index": i+1, **fresh["counters"][i],
            "production_action_ref": {"inner_decision_index": i, "executed_public_ordinal": ordinal,
                "executed_public_action_family": actual_families[i],
                "signed_action_id_commitment": _hash({"production_signed_action_id": actual["chosen_action_id"]}),
                "ordered_legal_action_commitment": actual["legal_action_set_sha256"]},
            "pre_execution_identity": actual["execution_before_sha256"], "post_execution_identity": actual["execution_after_sha256"],
            "pre_state_identity": actual["state_before_sha256"], "post_state_identity": actual["state_after_sha256"],
            **{key: actual[key] for key in ("event_start", "event_end", "rng_start", "rng_end")}, "inner_decision_identity": _hash(actual)})
    return {"status": "MATCH", "path": "FULL_C6_V1_AND_INCREMENTAL" if d["full_game"] else "G_LOCAL_PREFIX_ONLY",
            "private_record_identity": fresh["record_identity"], "ordered_sequence": actual_sequence,
            "full_game": d["full_game"]}


def _fresh_timed(d: Mapping[str, object], *, diagnostic_sink: object | None = None) -> dict[str, object]:
    from . import c8_timed_8p_full_game_runner_v1 as runner
    stored = d["timed_artifact"]
    config = stored["construction"]
    runner.validate_execution_order_profile_v1(config["execution_order_profile"])
    session = PrivateIncrementalC6RecorderV1.cold_session(stored["private_production_record"])
    bundle = runner._assemble_bundle_v3(session, seed=stored["seed"], run_label=config["run_label"])
    actual = runner._execute_timed_v3(repo_root=_root(), bundle=bundle, seed=stored["seed"], max_steps=config["max_steps"],
                                    max_windows=config["max_windows"], run_label=config["run_label"], full_game=d["full_game"],
                                    expected_initial_record=stored["private_production_record"], diagnostic_sink=diagnostic_sink)
    # Includes every raw B/C/E commitment and rejected operation; no semantic normalization.
    _equal(actual, stored, "fresh timed complete operation/evidence transcript")
    sequence = replay.ordered_production_sequence_v1([w["decision"] for w in runner.flat_step_records_v4(actual)])
    return {"status": "MATCH", "path": "FRESH_A_B_C_E_TIMED", "private_record_identity": actual["private_production_record"]["record_identity"],
            "ordered_sequence": sequence, "full_game": d["full_game"]}


def _fresh_test_only_inner(d: Mapping[str, object]) -> dict[str, object]:
    """Fresh R2 inner replay after the exact factory has rebuilt the fixture."""
    from . import c8_timed_8p_full_game_production_replay_v1 as lane
    from . import c8_timed_8p_full_game_runner_v1 as runner
    from . import c8_c6_production_adapter_v1 as production
    private_artifact = d["trusted_private_artifact"]
    timed = private_artifact["timed_artifact"]
    setup = private_artifact["fixture_setup"]
    private = timed["private_production_record"]
    runner.validate_execution_order_profile_v1(timed["construction"]["execution_order_profile"])
    _validate_test_only_private_record(private, full_game=False, seed=timed["seed"],
                                       max_steps=timed["construction"]["max_steps"])
    factory = lane.ExplicitTestOnlyFixtureFactoryV1()
    session = PrivateIncrementalC6RecorderV1.cold_session(private)
    fresh_setup = factory.prepare_session_v1(session, seed=timed["seed"])
    _equal(fresh_setup, setup, "R2 fresh inner factory setup")
    recorder = PrivateIncrementalC6RecorderV1(
        session, seed=timed["seed"], max_steps=timed["construction"]["max_steps"], test_only=True
    )
    recorder.compare_initial(private)
    public_adapter = production.C8C6ProductionAdapterV1(session)
    actual_families = []
    for index, stored in enumerate(private["decisions"]):
        recorder.before()
        for key, fresh in recorder.pending.items():
            _equal(stored[key], fresh, "R2 fresh inner pre-step "+key)
        chosen = next((action for action in session.legal_actions()
                       if action.action_id == stored["chosen_action_id"]), None)
        if chosen is None:
            raise C8G3CompositionMismatch("R2 fresh inner signed action不在fresh legal set")
        actual_families.append(
            runner._family_for_public_action(
                chosen, public_adapter.observe_production_decision_context_v1()
            )
        )
        executed = session.step(BatchActionIdController(chosen.action_id))
        _equal(executed.action_id, chosen.action_id, "R2 fresh inner executed signed action")
        actual, counters = recorder.after(executed.action_id)
        _equal(actual, stored, "R2 fresh inner decision material")
        _equal(counters, private["counters"][index], "R2 fresh inner counters")
    fresh = recorder.finish()
    _equal(fresh, private, "R2 fresh inner complete private record")
    if session.is_finished:
        raise C8G3CompositionMismatch("R2 fresh inner不得到达terminal")
    sequence = []
    for index, actual in enumerate(fresh["decisions"]):
        ordinal = next(j for j, action in enumerate(actual["legal_actions"])
                        if action["action_id"] == actual["chosen_action_id"])
        sequence.append({
            "cell_execution_identity": timed["cell_execution_identity"],
            "inner_decision_index": index, "step_index": index+1,
            **fresh["counters"][index],
            "production_action_ref": {
                "inner_decision_index": index,
                "executed_public_ordinal": ordinal,
                "executed_public_action_family": actual_families[index],
                "signed_action_id_commitment": _hash({"production_signed_action_id": actual["chosen_action_id"]}),
                "ordered_legal_action_commitment": actual["legal_action_set_sha256"],
            },
            "pre_execution_identity": actual["execution_before_sha256"],
            "post_execution_identity": actual["execution_after_sha256"],
            "pre_state_identity": actual["state_before_sha256"],
            "post_state_identity": actual["state_after_sha256"],
            **{key: actual[key] for key in ("event_start", "event_end", "rng_start", "rng_end")},
            "inner_decision_identity": _hash(actual),
        })
    return {"status": "MATCH", "path": "R2_FRESH_C6_PREFIX_ONLY",
            "private_record_identity": fresh["record_identity"],
            "ordered_sequence": sequence, "full_game": False}


def _fresh_test_only_timed(d: Mapping[str, object]) -> dict[str, object]:
    """Fresh R2 B/E/C6 timed run through the explicit test-only dispatch."""
    from . import c8_timed_8p_full_game_production_replay_v1 as lane
    from . import c8_timed_8p_full_game_runner_v1 as runner
    private_artifact = d["trusted_private_artifact"]
    stored = private_artifact["timed_artifact"]
    setup = private_artifact["fixture_setup"]
    private = stored["private_production_record"]
    config = stored["construction"]
    runner.validate_execution_order_profile_v1(config["execution_order_profile"])
    factory = lane.ExplicitTestOnlyFixtureFactoryV1()
    session = PrivateIncrementalC6RecorderV1.cold_session(private)
    fresh_setup = factory.prepare_session_v1(session, seed=stored["seed"])
    _equal(fresh_setup, setup, "R2 fresh timed factory setup")
    bundle = runner._assemble_bundle_v3(session, seed=stored["seed"], run_label=config["run_label"])
    actual = runner._execute_timed_v3(
        repo_root=_root(), bundle=bundle, seed=stored["seed"],
        max_steps=config["max_steps"], max_windows=config["max_windows"],
        run_label=config["run_label"], full_game=False, test_only=True,
        test_only_factory=factory, expected_initial_record=private,
    )
    _equal(actual, stored, "R2 fresh timed complete production transcript")
    sequence = replay.ordered_production_sequence_v1(
        [step["decision"] for step in runner.flat_step_records_v4(actual)])
    return {"status": "MATCH", "path": "R2_FRESH_A_B_E_C6_TIMED",
            "private_record_identity": actual["private_production_record"]["record_identity"],
            "ordered_sequence": sequence, "full_game": False}


def _r2_fresh_workers(d: Mapping[str, object], *, repo_root: Path | str | None = None) -> tuple[dict[str, object], dict[str, object]]:
    """Run the R2 inner and timed checks in fresh worker processes."""
    root = _root() if repo_root is None else Path(repo_root).resolve()
    infrastructure_deadline = time.monotonic()+45
    with tempfile.TemporaryDirectory(prefix="c8-r2-g3-") as temporary:
        directory = Path(temporary).resolve()
        if directory == root or root in directory.parents:
            raise C8G3CompositionMismatch("R2 fresh temp必须在repo外")
        source = directory/"r2-private-input.json"
        source.write_bytes(contract.canonical_json_bytes_v1(d))
        outputs: list[dict[str, object]] = []
        for mode in ("r2-inner", "r2-timed"):
            target = directory/(mode+"-result.json")
            remaining = infrastructure_deadline-time.monotonic()
            if remaining <= 0:
                raise C8G3CompositionMismatch("R2 fresh worker infrastructure timeout")
            command = [sys.executable, "-B", "-m", __name__, "--worker", mode,
                       "--input", str(source), "--output", str(target)]
            completed = subprocess.run(
                command, cwd=root, capture_output=True,
                timeout=min(20, max(1, remaining)),
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"},
            )
            if completed.returncode != 0 or not target.exists():
                raise C8G3CompositionMismatch("R2 fresh "+mode+" worker失败")
            report = replay._strict_json(target.read_bytes())
            if report.get("status") != "MATCH":
                raise C8G3CompositionMismatch("R2 fresh "+mode+"结果不匹配")
            outputs.append(report)
    if len(outputs) != 2:
        raise C8G3CompositionMismatch("R2 fresh worker数量不完整")
    return outputs[0], outputs[1]


def _fresh_unresolved(d: Mapping[str, object]) -> dict[str, object]:
    """Separate public-only C/B/E no-step probe, bound to a naturally recorded production context.

    The probe constructs a new independent timer. It neither reopens an archived
    parent nor modifies the actual timed transcript. Its identity is separate.
    """
    from . import c8_timed_8p_full_game_runner_v1 as runner
    timed = d["timed_artifact"]
    steps = runner.flat_step_records_v4(timed)
    runner.validate_execution_order_profile_v1(timed["construction"]["execution_order_profile"])
    target = next((i for i, w in enumerate(steps)
                   if w["context"]["applicability"] == "PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED"), None)
    if target is None:
        return {"status": "MATCH", "scope": "ISOLATED_PUBLIC_NO_STEP_PROBE", "observed": False}
    private = timed["private_production_record"]
    session = PrivateIncrementalC6RecorderV1.cold_session(private)
    recorder = PrivateIncrementalC6RecorderV1(session, seed=timed["seed"], max_steps=timed["construction"]["max_steps"])
    recorder.compare_initial(private)
    for i in range(target):
        recorder.before()
        stored = private["decisions"][i]
        for key, fresh in recorder.pending.items():
            _equal(stored[key], fresh, "isolated probe production prefix")
        action = session.step(BatchActionIdController(stored["chosen_action_id"]))
        actual, counters = recorder.after(action.action_id)
        _equal(actual, stored, "isolated probe actual prefix step")
        _equal(counters, private["counters"][i], "isolated probe actual counters")
    recorder.before()
    for key, fresh in recorder.pending.items():
        _equal(private["decisions"][target][key], fresh, "isolated probe actual production context")
    bundle = runner._assemble_bundle_v3(session, seed=timed["seed"], run_label="g3-isolated-unresolved")
    context, ref, opened = bundle.orchestrator.observe_and_open_or_refresh_v1()
    if context.applicability.value != "PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED" or opened is not True:
        raise C8G3CompositionMismatch("记录中的unresolved context未自然再生")
    active = bundle.runtime.state.virtual_time_state.window_stack.active_window
    runner._advance_virtual_time(bundle, active.deadline_at)
    before = (session.step_count, session.state.revision, session.execution_hash, len(session.events), len(session.rng_calls))
    result = bundle.controller.resolve_timeout_v1(ref, timeout_due_commitment=bundle.runtime.current_timeout_due_commitment_v1(ref))
    after = (session.step_count, session.state.revision, session.execution_hash, len(session.events), len(session.rng_calls))
    _equal(before, after, "isolated public unresolved must not step/change production")
    if (result.result_kind != "TIMEOUT_UNRESOLVED" or result.selected_actions or result.receipt_identities
            or result.step_count != 1 or len(result.legal_set_identities) != 1
            or bundle.adapter.public_issuance_evidence_v1()):
        raise C8G3CompositionMismatch("unresolved probe必须拒绝selection/issuance/receipt")
    material = {"status": "MATCH", "scope": "ISOLATED_PUBLIC_NO_STEP_PROBE", "observed": True,
        "originating_decision_evidence_identity": steps[target]["decision"]["evidence_identity"],
        "same_production_context_commitment": private["decisions"][target]["context_sha256"],
        "independent_probe_context_identity": context.context_identity, "result_identity": result.result_identity,
        "resolver_legal_set_checks": result.step_count, "production_steps_added": 0}
    return {**material, "proof_identity": _hash(material)}


def _cold_workers(d: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    # The original objects/owner registries never cross the process boundary.
    # Infrastructure deadline only; game time remains the recorded deterministic virtual clock.
    infrastructure_deadline = time.monotonic()+50
    with tempfile.TemporaryDirectory(prefix="c8-g3-cold-") as temporary:
        directory = Path(temporary).resolve()
        if directory == _root() or _root() in directory.parents:
            raise C8G3CompositionMismatch("cold worker temp必须在repo外")
        source = directory/"private-input.json"
        source.write_bytes(contract.canonical_json_bytes_v1(d))
        outputs = []
        modes = ["inner", "timed"]
        if d["full_game"] and any(w["context"]["applicability"] == "PRIVATE_ORDINAL_TIMEOUT_UNRESOLVED" for w in d["timed_artifact"]["window_records"]):
            modes.append("unresolved")
        for mode in modes:
            target = directory/(mode+"-result.json")
            command = [sys.executable, "-B", "-m", "scripts.sgs_engine.c8_timed_8p_full_game_production_replay_v1",
                       "--worker", mode, "--input", str(source), "--output", str(target)]
            remaining = infrastructure_deadline-time.monotonic()
            if remaining <= 0:
                raise C8G3CompositionMismatch("C8_G3_COMPOSITION_MISMATCH: cold worker infrastructure timeout")
            completed = subprocess.run(command, cwd=_root(), capture_output=True, timeout=min(25, remaining),
                                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"})
            if completed.returncode or not target.exists():
                raise C8G3CompositionMismatch("C8_G3_COMPOSITION_MISMATCH: fresh "+mode+" worker")
            report = replay._strict_json(target.read_bytes())
            if report.get("status") != "MATCH":
                raise C8G3CompositionMismatch("C8_G3_COMPOSITION_MISMATCH: "+mode)
            outputs.append(report)
    inner, timed = outputs[:2]
    timed["unresolved_no_step_proof"] = outputs[2] if len(outputs) == 3 else None
    _equal(inner["ordered_sequence"], timed["ordered_sequence"], "inner/timed exact ordered actions")
    _equal(inner["ordered_sequence"], d["ordered_production_sequence"], "recorded/fresh ordered actions")
    _equal(inner["private_record_identity"], timed["private_record_identity"], "inner/timed state/event/RNG")
    return inner, timed


_BOUNDED_RESULT_TOKEN = object()


@dataclass(frozen=True, slots=True)
class BoundedCompositionResultV1:
    artifact_identity: str
    ordered_production_sequence_identity: str
    accepted_steps: int
    windows: int
    _authority: object = None

    def __post_init__(self) -> None:
        if self._authority is not _BOUNDED_RESULT_TOKEN:
            raise C8G3CompositionMismatch("bounded result只能由fresh固定入口签发")

    def to_report_dict(self) -> dict[str, object]:
        return {"schema": "sgs-c8-g-bounded-composition-result-v1", "scope": C8_G3_BOUNDED_SCOPE,
                "status": "MATCH", "full_game": False, "promotion": False,
                "old_c6_full_game_verifier": "NOT_CALLED_FOR_PREFIX", "full_game_replay": "NOT_PROVEN",
                "artifact_identity": self.artifact_identity, "ordered_production_sequence_identity": self.ordered_production_sequence_identity,
                "accepted_steps": self.accepted_steps, "windows": self.windows,
                "authority": "REPORT_ONLY_NOT_REHYDRATABLE"}


def verify_bounded_composition_v1(value: object) -> BoundedCompositionResultV1:
    d = preflight_composition_v1(value, full_game=False)
    _cold_workers(d)
    return BoundedCompositionResultV1(d["artifact_identity"], d["ordered_production_sequence_identity"],
                                     d["timed_artifact"]["completed_production_steps"], d["timed_artifact"]["completed_windows"], _BOUNDED_RESULT_TOKEN)


@dataclass(frozen=True, slots=True)
class R2TestOnlyCompositionResultV1:
    """Non-promotable result token for the isolated targeted R2 lane."""

    artifact_identity: str
    ordered_production_sequence_identity: str
    accepted_steps: int
    windows: int
    inner_worker: Mapping[str, object]
    timed_worker: Mapping[str, object]
    _authority: object = None

    def __post_init__(self) -> None:
        if self._authority is not R2_TEST_ONLY_RESULT_TOKEN:
            raise C8G3CompositionMismatch("R2结果只能由fresh test-only composition入口签发")
        if self.accepted_steps != 8 or self.windows != 6:
            raise C8G3CompositionMismatch("R2结果边界不是冻结的8 steps/6 windows")

    def to_report_dict(self) -> dict[str, object]:
        return {
            "schema": R2_TEST_ONLY_RESULT_TYPE,
            "scope": R2_TEST_ONLY_SCOPE,
            "trace_scope": R2_TEST_ONLY_SCOPE,
            "status": "MATCH",
            "test_only": True,
            "formal_result_eligible": False,
            "formal_result": False,
            "natural": False,
            "full_game": False,
            "promotion": False,
            "baseline": False,
            "matrix": False,
            "accepted_steps": self.accepted_steps,
            "windows": self.windows,
            "artifact_identity": self.artifact_identity,
            "ordered_production_sequence_identity": self.ordered_production_sequence_identity,
            "inner_timed_stored_sequence": "EXACT_MATCH_NO_SORT_NO_COLLAPSE",
            "inner_worker": dict(self.inner_worker),
            "timed_worker": dict(self.timed_worker),
            "formal_full_game_entry": "REJECTED_BEFORE_FORMAL_VERIFIER",
            "promotion_token": "NOT_ISSUED",
            "authority": "TARGETED_INTEGRATION_ONLY_NOT_FULL_GAME_PROOF",
        }


def verify_test_only_composition_v1(value: object, *, repo_root: Path | str | None = None) -> R2TestOnlyCompositionResultV1:
    """Freshly compose R2 inner/timed/stored ordered actions in two workers."""
    d = r2_test_only_evidence_from_dict_v1(value, repo_root=repo_root)
    inner, timed = _r2_fresh_workers(d, repo_root=repo_root)
    sequence = d["ordered_production_sequence"]
    _equal(inner["ordered_sequence"], sequence, "R2 inner/frozen ordered sequence")
    _equal(timed["ordered_sequence"], sequence, "R2 timed/frozen ordered sequence")
    _equal(inner["ordered_sequence_identity"], d["ordered_production_sequence_identity"],
           "R2 inner sequence identity")
    _equal(timed["ordered_sequence_identity"], d["ordered_production_sequence_identity"],
           "R2 timed sequence identity")
    _equal(inner["private_record_identity"], timed["private_record_identity"],
           "R2 inner/timed private state identity")
    timed_artifact = d["trusted_private_artifact"]["timed_artifact"]
    return R2TestOnlyCompositionResultV1(
        d["artifact_identity"], d["ordered_production_sequence_identity"],
        timed_artifact["completed_production_steps"], timed_artifact["completed_windows"],
        inner, timed, R2_TEST_ONLY_RESULT_TOKEN,
    )


def _derive_full_game_witnesses(d: Mapping[str, object], unresolved: object) -> tuple[contract.RequiredEventWitnessV1, ...]:
    """Called only after two fresh workers match. Stored observed/verified flags are never inputs."""
    timed = d["timed_artifact"]
    observed = {name: [] for name in contract.REQUIRED_EVENT_OBLIGATION_IDS_V1}
    for i, window in enumerate(timed["window_records"]):
        for step in window["steps"]:
            decision = step["decision"]
            observed["FG-TIMER-02" if decision["kind"] == replay.TIMEOUT_KIND else "FG-TIMER-01"].append(decision["evidence_identity"])
        w = window["steps"][-1]
        observed["FG-TIMER-03"].append(window["record_identity"])
        phase_boundary = w["pre_state"]["phase"] != w["post_state"]["phase"]
        actor_boundary = (w["pre_state"]["turn_number"], w["pre_state"]["current_actor_id"]) != (w["post_state"]["turn_number"], w["post_state"]["current_actor_id"])
        if phase_boundary and i+1 < len(timed["window_records"]):
            observed["FG-TIMER-04"].append(w["completion"]["completion_identity"])
        if actor_boundary and i+1 < len(timed["window_records"]):
            observed["FG-TIMER-05"].append(w["completion"]["completion_identity"])
        if phase_boundary or actor_boundary:
            observed["FG-TIMER-06"].append(_hash(w["operations"][-1]))
        relation = window["relation"]
        if relation["causal_relation_kind"] == "POST_COMMIT_CAUSAL_CHILD":
            kind = window["steps"][0]["decision"]["binding"]["production_window_kind"]
            if kind == "OPTIONAL_RESPONSE":
                observed["FG-TIMER-07"].append(window["record_identity"])
            if kind == "RESCUE_RESPONSE":
                observed["FG-TIMER-08"].append(window["record_identity"])
    if unresolved is not None and unresolved["observed"] is True:
        observed["FG-TIMER-09"].append(unresolved["proof_identity"])
    observed["FG-TIMER-10"].append(_hash(timed["private_production_record"]["outcome"]))
    observed["FG-TIMER-12"].append(d["ordered_production_sequence_identity"])
    result = []
    for missing in contract.canonical_missing_witnesses_v1():
        identities = tuple(sorted(set(observed[missing.obligation_id])))
        if identities:
            result.append(contract.RequiredEventWitnessV1(missing.obligation_id, missing.level, missing.applicability,
                contract.WitnessStatusV1.OBSERVED, identities, "FULL_GAME_REAL_PRODUCTION_TRACE"))
        else:
            result.append(missing)
    return tuple(result)


def verify_full_game_composition_v1(value: object) -> contract.FullGameResultV1:
    from . import c8_timed_replay_version_compatibility_v1 as compatibility
    compatibility.reject_recording_v1()
    d = preflight_composition_v1(value, full_game=True)
    _, fresh_timed = _cold_workers(d)
    timed = d["timed_artifact"]
    witnesses = _derive_full_game_witnesses(d, fresh_timed["unresolved_no_step_proof"])
    observed = {w.obligation_id for w in witnesses if w.status is contract.WitnessStatusV1.OBSERVED}
    facts = {"PRODUCTION_REACHABLE", "NATURAL_FULL_GAME", "CANONICAL_C6_MODE_PROVEN", "FORMAL_DRIVER_POLICY_PROVEN",
             "TIMER_AUTHORITY_PROVEN", "PUBLIC_ADAPTER_AUTHORITY_PROVEN", "CONTROLLER_AUTHORITY_PROVEN",
             "MULTIWINDOW_CONTINUITY_PROVEN", "NATURAL_TERMINAL_PROVEN", "TERMINAL_WINDOWS_CLEAN_PROVEN",
             "INNER_PRODUCTION_REPLAY_PROVEN", "OUTER_TIMER_REPLAY_PROVEN", "FULL_GAME_REPLAY_STRICT_VERIFIED",
             "IDENTITY_PROFILE_DRIVER_BINDING_PROVEN"}
    for obligation, fact in (("FG-TIMER-01", "ON_TIME_TRACE_PROVEN"), ("FG-TIMER-02", "TIMEOUT_TRACE_PROVEN"),
                             ("FG-TIMER-03", "SAME_CONTEXT_NO_REFRESH_PROVEN"), ("FG-TIMER-04", "PHASE_CLEANUP_PROVEN"),
                             ("FG-TIMER-05", "TURN_ACTOR_CLEANUP_PROVEN"), ("FG-TIMER-06", "STALE_EVIDENCE_REJECTION_PROVEN"),
                             ("FG-TIMER-09", "UNRESOLVED_CONTEXT_POLICY_PROVEN")):
        if obligation in observed:
            facts.add(fact)
    return contract._fresh_full_game_result_v1(cell_id=d["cell_id"], seed=timed["seed"], mode_id=contract.C8_G1_BASE_MODE_ID,
        registry_identity=timed["registry"]["registry_identity"], current_implementation_identity=d["g3_binding"]["current_c8_implementation_identity"],
        contract_identity=contract.C8_G1_CONTRACT_IDENTITY, timer_profile_id=contract.C8_G1_TIMER_PROFILE_ID,
        driver_policy_identity=contract.C8_G1_DRIVER_POLICY_IDENTITY, replay_schema=contract.C8_G1_REPLAY_SCHEMA,
        replay_scope=contract.C8_G1_SCOPE_MARKER, production_adapter_id=contract.C8_G1_E_ADAPTER_ID,
        production_adapter_contract_identity=contract.C8_G1_E_CONTRACT_IDENTITY,
        controller_contract_identity=contract.C8_G1_C_CONTROLLER_CONTRACT_IDENTITY,
        artifact_scope=contract.CandidateScopeV1.FORMAL_QUALITY_CANDIDATE, run_status=contract.CellRunStatusV1.COMPLETE,
        artifact_complete=True, full_game=True, formal_matrix_cell=True, natural_terminal=True, safety_cap_hit=False,
        strict_replay_verified=True, replay_identity=d["artifact_identity"], artifact_identity=d["artifact_identity"],
        verified_fact_ids=frozenset(facts), required_event_witnesses=witnesses,
        successful_rescue_evidence_identities=tuple(v["evidence_identity"] for v in timed["private_production_record"]["successful_rescue_evidence"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G3 fixed isolated private replay worker")
    parser.add_argument("--worker", choices=("inner", "timed", "unresolved", "r2-inner", "r2-timed"), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = replay._strict_json(args.input.read_bytes())
    try:
        if args.worker in {"r2-inner", "r2-timed"}:
            d = r2_test_only_evidence_from_dict_v1(raw, repo_root=_root())
            fresh = _fresh_test_only_inner if args.worker == "r2-inner" else _fresh_test_only_timed
            result = fresh(d)
            report = {"status": "MATCH", "worker": args.worker,
                "scope": R2_TEST_ONLY_SCOPE, "trace_scope": R2_TEST_ONLY_SCOPE,
                "test_only": True, "formal_result_eligible": False,
                "full_game": False, "promotion": False,
                "artifact_identity": d["artifact_identity"],
                "ordered_sequence": result["ordered_sequence"],
                "ordered_sequence_identity": replay.ordered_production_sequence_identity_v1(result["ordered_sequence"]),
                "private_record_identity": result["private_record_identity"],
                "accepted_steps": 8, "windows": 6}
            args.output.write_bytes(contract.canonical_json_bytes_v1(report))
            return 0
        full_game = replay._boolean(raw.get("full_game"), "full_game")
        d = preflight_composition_v1(raw, full_game=full_game)
        result = {"inner": _fresh_inner, "timed": _fresh_timed, "unresolved": _fresh_unresolved}[args.worker](d)
    except Exception as exc:
        # Values of private actions, secrets, events and RNG are never printed.
        result = {"status": "C8_G3_COMPOSITION_MISMATCH", "stage": args.worker, "error_type": type(exc).__name__}
        args.output.write_bytes(contract.canonical_json_bytes_v1(result))
        return 1
    args.output.write_bytes(contract.canonical_json_bytes_v1(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
