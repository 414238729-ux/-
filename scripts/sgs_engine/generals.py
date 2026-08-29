# -*- coding: utf-8 -*-
"""Authoritative General definitions and frozen General Registry.

This module provides the formal General infrastructure for SGS engine:
- GeneralDefinition: Immutable, validated general metadata (key, name, version,
  gender, max_hp, starting_hp, complete skill list, profile_identity).
- AuthoritativeGeneralRegistry: Immutable, frozen registry mapping general_key
  to GeneralDefinition with deterministic registry_identity.
- Automatic assembly of complete skill sets and CharacterMetadata into
  production sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .actions import UnsupportedRuleError
from .model import CharacterGender, CharacterMetadata
from .replay import canonical_json, sha256_value

GENERAL_SCHEMA_V1 = "authoritative-general-v1"
_GENERAL_DEFINITION_FIELDS = frozenset(
    {
        "general_key",
        "name",
        "version",
        "gender",
        "max_hp",
        "starting_hp",
        "skill_ids",
        "description",
        "schema_version",
        "profile_identity",
    }
)


def _require_nonempty_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")
    return value.strip()


def _require_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label}必须是正整数")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class GeneralDefinition:
    """Immutable authoritative general definition with canonical profile identity."""

    general_key: str
    name: str
    version: str
    gender: CharacterGender
    max_hp: int
    starting_hp: int
    skill_ids: tuple[str, ...]
    description: str = ""
    schema_version: str = GENERAL_SCHEMA_V1
    profile_identity: str = field(default="")

    def __post_init__(self) -> None:
        object.__setattr__(self, "general_key", _require_nonempty_str(self.general_key, "武将键"))
        object.__setattr__(self, "name", _require_nonempty_str(self.name, "武将名称"))
        object.__setattr__(self, "version", _require_nonempty_str(self.version, "武将版本"))
        if not isinstance(self.gender, CharacterGender):
            raise TypeError("武将gender必须是CharacterGender枚举")
        max_hp = _require_positive_int(self.max_hp, "体力上限")
        starting_hp = _require_positive_int(self.starting_hp, "初始体力")
        if starting_hp > max_hp:
            raise ValueError("初始体力不能高于体力上限")
        object.__setattr__(self, "max_hp", max_hp)
        object.__setattr__(self, "starting_hp", starting_hp)
        if isinstance(self.skill_ids, str) or not isinstance(self.skill_ids, (tuple, list, Sequence)):
            raise TypeError("skill_ids必须是技能ID序列")
        skills = tuple(_require_nonempty_str(s, "技能ID") for s in self.skill_ids)
        if not skills:
            raise ValueError("武将必须至少拥有一个技能")
        if len(skills) != len(set(skills)):
            raise ValueError("武将技能列表不能包含重复ID")
        object.__setattr__(self, "skill_ids", skills)

        canonical = self.to_canonical_payload()
        canonical_identity = sha256_value(canonical)
        if self.profile_identity:
            if self.profile_identity != canonical_identity:
                raise ValueError(
                    f"武将 {self.general_key} 传入的 profile_identity 与规范语义哈希不一致 "
                    f"(传入={self.profile_identity}, 计算={canonical_identity})"
                )
        else:
            object.__setattr__(self, "profile_identity", canonical_identity)

    def to_canonical_payload(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "gender": self.gender.value,
            "general_key": self.general_key,
            "max_hp": self.max_hp,
            "name": self.name,
            "schema_version": self.schema_version,
            "skill_ids": list(self.skill_ids),
            "starting_hp": self.starting_hp,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "gender": self.gender.value,
            "general_key": self.general_key,
            "max_hp": self.max_hp,
            "name": self.name,
            "profile_identity": self.profile_identity,
            "schema_version": self.schema_version,
            "skill_ids": list(self.skill_ids),
            "starting_hp": self.starting_hp,
            "version": self.version,
        }

    def canonical_profile_identity(self) -> str:
        """Recompute identity from the live semantic payload.

        This deliberately does not trust the cached ``profile_identity`` field;
        replay preflight uses it to detect malicious ``object.__setattr__``
        mutation of a frozen definition.
        """

        try:
            payload = self.to_canonical_payload()
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(
                f"武将 {getattr(self, 'general_key', '<unknown>')!r} live semantic payload 非法"
            ) from exc
        return sha256_value(payload)

    def assert_canonical_integrity(self) -> None:
        expected = self.canonical_profile_identity()
        if type(self.profile_identity) is not str or self.profile_identity != expected:
            raise ValueError(
                f"武将 {self.general_key!r} live canonical payload 与缓存 profile_identity 不一致"
            )
        # Strict reconstruction validates live field types as well as values.
        GeneralDefinition.from_dict(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GeneralDefinition:
        if type(data) is not dict:
            raise TypeError("武将数据必须是字典映射")
        actual_fields = frozenset(data)
        if actual_fields != _GENERAL_DEFINITION_FIELDS:
            missing = sorted(_GENERAL_DEFINITION_FIELDS - actual_fields)
            extra = sorted(actual_fields - _GENERAL_DEFINITION_FIELDS)
            raise ValueError(
                f"武将数据字段必须精确匹配 schema；missing={missing}, extra={extra}"
            )
        for key in (
            "general_key",
            "name",
            "version",
            "description",
            "schema_version",
            "profile_identity",
        ):
            if type(data[key]) is not str:
                raise TypeError(f"武将字段 {key} 必须是精确字符串")
        raw_gender = data["gender"]
        if type(raw_gender) is not str:
            raise TypeError("武将gender必须是字符串")
        try:
            gender = CharacterGender(raw_gender)
        except ValueError as exc:
            raise ValueError(f"未知性别 {raw_gender!r}") from exc
        raw_skills = data["skill_ids"]
        if type(raw_skills) is not list:
            raise TypeError("skill_ids必须是精确 JSON array")
        if any(type(item) is not str for item in raw_skills):
            raise TypeError("skill_ids中的每一项必须是精确字符串")
        for key in ("max_hp", "starting_hp"):
            if type(data[key]) is not int:
                raise TypeError(f"武将字段 {key} 必须是整数且拒绝 bool-as-int")
        return cls(
            general_key=data["general_key"],
            name=data["name"],
            version=data["version"],
            gender=gender,
            max_hp=data["max_hp"],
            starting_hp=data["starting_hp"],
            skill_ids=tuple(raw_skills),
            description=data["description"],
            schema_version=data["schema_version"],
            profile_identity=data["profile_identity"],
        )

    def to_character_metadata(self) -> CharacterMetadata:
        return CharacterMetadata(
            character_key=self.general_key,
            intrinsic_gender=self.gender,
            effective_gender=self.gender,
        )


class AuthoritativeGeneralRegistry:
    """Immutable, frozen registry of GeneralDefinitions."""

    def __init__(self, generals: Iterable[GeneralDefinition] | None = None) -> None:
        self._generals: dict[str, GeneralDefinition] = {}
        self._frozen: bool = False
        self._registry_identity: str = ""

        if generals is not None:
            for g in generals:
                self.register(g)

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    @property
    def registry_identity(self) -> str:
        if not self._frozen:
            raise ValueError("武将注册表尚未冻结，无法读取registry_identity")
        self.assert_canonical_integrity()
        return self._registry_identity

    def canonical_registry_identity(self) -> str:
        if not self._frozen:
            raise ValueError("武将注册表尚未冻结，无法重算registry_identity")
        for key, general in self._generals.items():
            if key != general.general_key:
                raise ValueError("武将注册表键与 live GeneralDefinition.general_key 不一致")
            general.assert_canonical_integrity()
        return sha256_value(
            {
                "schema_version": GENERAL_SCHEMA_V1,
                "generals": {
                    key: self._generals[key].to_dict()
                    for key in sorted(self._generals)
                },
            }
        )

    def assert_canonical_integrity(self) -> None:
        live_identity = self.canonical_registry_identity()
        if live_identity != self._registry_identity:
            raise ValueError("武将注册表 live canonical payload 与缓存 registry_identity 不一致")

    def register(self, general: GeneralDefinition) -> None:
        if self._frozen:
            raise ValueError("武将注册表已冻结，禁止注册新武将")
        if not isinstance(general, GeneralDefinition):
            raise TypeError("注册对象必须是GeneralDefinition实例")
        # Validate canonical profile identity matches
        expected_identity = sha256_value(general.to_canonical_payload())
        if general.profile_identity != expected_identity:
            raise ValueError(f"武将 {general.general_key} profile_identity 被篡改")
        if general.general_key in self._generals:
            raise ValueError(f"武将键 {general.general_key!r} 已存在于注册表中")
        self._generals[general.general_key] = general

    def get_general(self, general_key: str) -> GeneralDefinition:
        if general_key not in self._generals:
            raise UnsupportedRuleError(f"武将注册表未包含武将键 {general_key!r}")
        general = self._generals[general_key]
        if general.general_key != general_key:
            raise ValueError("武将注册表键与 live GeneralDefinition.general_key 不一致")
        general.assert_canonical_integrity()
        return general

    def has_general(self, general_key: str) -> bool:
        return general_key in self._generals

    def freeze(self) -> "AuthoritativeGeneralRegistry":
        if not self._frozen:
            payload = {
                "schema_version": GENERAL_SCHEMA_V1,
                "generals": {
                    k: self._generals[k].to_dict()
                    for k in sorted(self._generals.keys())
                },
            }
            self._registry_identity = sha256_value(payload)
            self._frozen = True
        return self


def create_authoritative_general_batch_v1_registry() -> AuthoritativeGeneralRegistry:
    """Creates the frozen authoritative General Registry for Batch V1."""
    shamoke = GeneralDefinition(
        general_key="shamoke",
        name="沙摩柯",
        version="1.0.0",
        gender=CharacterGender.MALE,
        max_hp=4,
        starting_hp=4,
        skill_ids=("sgs_skill_jili",),
        description="蜀势力武将沙摩柯，拥有技能【蒺藜】。",
    )
    registry = AuthoritativeGeneralRegistry([shamoke])
    return registry.freeze()


def create_general_registry(
    generals: Iterable[GeneralDefinition] | None = None,
) -> AuthoritativeGeneralRegistry:
    """Create and freeze an AuthoritativeGeneralRegistry with provided generals."""
    return AuthoritativeGeneralRegistry(generals).freeze()
