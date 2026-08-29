from __future__ import annotations

from collections.abc import Mapping

from .errors import EnterpriseCatalogBuildError
from .hashing import hash_machine_payload
from .model import EnterpriseMappingCatalog, EnterpriseMappingRule, MatchType
from .source import EXPECTED_METADATA, validate_root_metadata


ASSURANCE_VALUES = {
    "NATIVE_ASSERTED",
    "STANDARD_MAPPED",
    "RULE_DERIVED",
    "HEURISTIC",
    "UNKNOWN",
}


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EnterpriseCatalogBuildError(f"{field} must be non-empty")
    return value.strip()


def _rule(raw: object) -> EnterpriseMappingRule:
    if not isinstance(raw, Mapping):
        raise EnterpriseCatalogBuildError("rule must be a mapping")
    mapping_id = _text(raw.get("mapping_id"), "mapping_id")
    source_scheme = _text(raw.get("source_scheme"), "source_scheme")
    target_term_id = _text(raw.get("target_term_id"), "target_term_id")
    if ":" not in target_term_id:
        raise EnterpriseCatalogBuildError("target_term_id must use namespace:local form")
    namespace, local = target_term_id.split(":", 1)
    if not namespace or not local:
        raise EnterpriseCatalogBuildError("target_term_id must use namespace:local form")
    assurance = _text(raw.get("assurance"), "assurance")
    if assurance not in ASSURANCE_VALUES:
        raise EnterpriseCatalogBuildError("assurance is invalid")

    match = raw.get("match")
    if not isinstance(match, Mapping):
        raise EnterpriseCatalogBuildError("match must be a mapping")
    raw_type = _text(match.get("type"), "match type")
    try:
        match_type = MatchType(raw_type)
    except ValueError as exc:
        raise EnterpriseCatalogBuildError(f"unsupported match type: {raw_type}") from exc
    pattern = _text(match.get("pattern"), "pattern")
    case_sensitive = match.get("case_sensitive")
    if not isinstance(case_sensitive, bool):
        raise EnterpriseCatalogBuildError("case_sensitive must be boolean")

    return EnterpriseMappingRule(
        mapping_id=mapping_id,
        source_scheme=source_scheme,
        match_type=match_type,
        pattern=pattern,
        case_sensitive=case_sensitive,
        target_term_id=target_term_id,
        assurance=assurance,
    )


def _fold(value: str, case_sensitive: bool) -> str:
    return value if case_sensitive else value.casefold()


def _patterns_overlap(a: EnterpriseMappingRule, b: EnterpriseMappingRule) -> bool:
    if a.source_scheme != b.source_scheme:
        return False
    # If either side is case-insensitive, existence of a common source code is
    # determined in the folded language. When both are case-sensitive, use exact casing.
    case_sensitive = a.case_sensitive and b.case_sensitive
    ap = _fold(a.pattern, case_sensitive)
    bp = _fold(b.pattern, case_sensitive)

    if a.match_type is MatchType.EXACT and b.match_type is MatchType.EXACT:
        return ap == bp
    if a.match_type is MatchType.EXACT and b.match_type is MatchType.PREFIX:
        return ap.startswith(bp)
    if a.match_type is MatchType.PREFIX and b.match_type is MatchType.EXACT:
        return bp.startswith(ap)
    return ap.startswith(bp) or bp.startswith(ap)


def _assert_deterministic(rules: tuple[EnterpriseMappingRule, ...]) -> None:
    for index, first in enumerate(rules):
        for second in rules[index + 1 :]:
            if not _patterns_overlap(first, second):
                continue
            first_semantics = (first.target_term_id, first.assurance)
            second_semantics = (second.target_term_id, second.assurance)
            if first_semantics != second_semantics:
                raise EnterpriseCatalogBuildError(
                    "overlapping rules produce different semantics: "
                    f"{first.mapping_id}, {second.mapping_id}"
                )


def build_catalog(payload: Mapping[str, object]) -> EnterpriseMappingCatalog:
    validate_root_metadata(payload)
    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list):
        raise EnterpriseCatalogBuildError("rules must be an array")

    parsed = tuple(sorted((_rule(item) for item in raw_rules), key=lambda item: item.mapping_id))
    seen: set[str] = set()
    for item in parsed:
        if item.mapping_id in seen:
            raise EnterpriseCatalogBuildError(f"duplicate mapping_id: {item.mapping_id}")
        seen.add(item.mapping_id)
    _assert_deterministic(parsed)

    metadata = dict(EXPECTED_METADATA)
    machine_payload = {
        "metadata": metadata,
        "rules": [item.machine_payload() for item in parsed],
    }
    return EnterpriseMappingCatalog(
        metadata=metadata,
        rules=parsed,
        content_hash=hash_machine_payload(machine_payload),
    )
