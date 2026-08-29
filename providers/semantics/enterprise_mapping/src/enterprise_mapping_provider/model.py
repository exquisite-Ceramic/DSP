from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class MatchType(str, Enum):
    EXACT = "EXACT"
    PREFIX = "PREFIX"


@dataclass(frozen=True, slots=True)
class EnterpriseMappingRule:
    mapping_id: str
    source_scheme: str
    match_type: MatchType
    pattern: str
    case_sensitive: bool
    target_term_id: str
    assurance: str

    def machine_payload(self) -> dict[str, object]:
        return {
            "mapping_id": self.mapping_id,
            "source_scheme": self.source_scheme,
            "match_type": self.match_type.value,
            "pattern": self.pattern,
            "case_sensitive": self.case_sensitive,
            "target_term_id": self.target_term_id,
            "assurance": self.assurance,
        }


@dataclass(frozen=True, slots=True)
class EnterpriseMappingCatalog:
    metadata: Mapping[str, str]
    rules: tuple[EnterpriseMappingRule, ...]
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        object.__setattr__(self, "rules", tuple(self.rules))
