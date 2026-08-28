# -*- coding: utf-8 -*-
"""Authoritative skill registry for the SGS rules core.

Provides immutable, auditable registration of SkillDefinition and SkillHandler instances.
Rejects duplicate skill IDs, duplicate profile identities, unknown fields, and post-freeze mutations.
An empty frozen registry (EMPTY_SKILL_REGISTRY) is provided for no-skill modes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from .actions import UnsupportedRuleError
from .skills import SkillDefinition, SkillHandler


class SkillRegistryError(ValueError):
    """Raised when skill registration or lookup fails."""


class AuthoritativeSkillRegistry:
    """Immutable authoritative registry mapping skill_id to SkillDefinition and SkillHandler."""

    def __init__(self, handlers: Iterable[SkillHandler] = ()) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._handlers: dict[str, SkillHandler] = {}
        self._profiles: dict[str, str] = {}  # profile_identity -> skill_id
        self._frozen: bool = False
        self._identity: str = ""

        for handler in handlers:
            self.register(handler)

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    @property
    def registry_identity(self) -> str:
        if not self._frozen:
            raise SkillRegistryError("注册表未冻结，无法获取 registry_identity")
        return self._identity

    @property
    def skill_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._skills))

    @property
    def skills(self) -> Mapping[str, SkillDefinition]:
        return MappingProxyType(self._skills)

    @property
    def handlers(self) -> Mapping[str, SkillHandler]:
        return MappingProxyType(self._handlers)

    def register(self, handler: SkillHandler) -> None:
        """Register a skill handler before freezing."""
        if self._frozen:
            raise SkillRegistryError("注册表已冻结，禁止新增或修改技能注册")
        if not isinstance(handler, SkillHandler):
            raise TypeError("注册目标必须是 SkillHandler 实例")
        definition = handler.definition
        if not isinstance(definition, SkillDefinition):
            raise TypeError("handler.definition 必须是 SkillDefinition")

        skill_id = definition.skill_id
        if skill_id in self._skills:
            raise SkillRegistryError(f"重复注册技能ID：{skill_id}")
        profile_id = definition.profile_identity
        if profile_id in self._profiles:
            existing_skill = self._profiles[profile_id]
            raise SkillRegistryError(
                f"技能 {skill_id} 的 profile_identity 与已有技能 {existing_skill} 重复：{profile_id}"
            )

        self._skills[skill_id] = definition
        self._handlers[skill_id] = handler
        self._profiles[profile_id] = skill_id

    def freeze(self) -> AuthoritativeSkillRegistry:
        """Freeze this registry and compute deterministic registry_identity."""
        if self._frozen:
            return self

        # Compute deterministic SHA-256 over all sorted canonical skill definitions
        entries: list[dict[str, object]] = [
            self._skills[sid].to_canonical_dict(include_identity=True)
            for sid in sorted(self._skills)
        ]
        encoded = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self._identity = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        self._frozen = True
        return self

    def has_skill(self, skill_id: str) -> bool:
        return skill_id in self._skills

    def get_skill(self, skill_id: str) -> SkillDefinition:
        """Return SkillDefinition or raise UnsupportedRuleError if unknown."""
        if skill_id not in self._skills:
            raise UnsupportedRuleError(f"未注册或不受支持的技能：{skill_id!r}")
        return self._skills[skill_id]

    def get_handler(self, skill_id: str) -> SkillHandler:
        """Return SkillHandler or raise UnsupportedRuleError if unknown."""
        if skill_id not in self._handlers:
            raise UnsupportedRuleError(f"未注册或不受支持的技能处理器：{skill_id!r}")
        return self._handlers[skill_id]


def create_skill_registry(handlers: Sequence[SkillHandler] = ()) -> AuthoritativeSkillRegistry:
    """Create and freeze a new AuthoritativeSkillRegistry with given handlers."""
    registry = AuthoritativeSkillRegistry(handlers)
    return registry.freeze()


EMPTY_SKILL_REGISTRY: AuthoritativeSkillRegistry = create_skill_registry(())
