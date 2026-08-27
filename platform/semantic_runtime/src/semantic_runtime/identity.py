"""Stable host-local to semantic identity mappings."""

from __future__ import annotations

from dataclasses import dataclass


class IdentityConflictError(ValueError):
    """Raised when an existing semantic/native identity would be rebound."""


@dataclass(frozen=True, slots=True)
class IdentityBinding:
    semantic_id: str
    document_id: str
    native_id: str
    ifc_global_id: str | None = None

    def __post_init__(self) -> None:
        semantic_id = self.semantic_id.strip()
        document_id = self.document_id.strip()
        native_id = self.native_id.strip()
        if not semantic_id or not document_id or not native_id:
            raise ValueError("semantic_id, document_id, and native_id are required")
        ifc_global_id = self.ifc_global_id.strip() if self.ifc_global_id is not None else None
        if ifc_global_id == "":
            ifc_global_id = None
        object.__setattr__(self, "semantic_id", semantic_id)
        object.__setattr__(self, "document_id", document_id)
        object.__setattr__(self, "native_id", native_id)
        object.__setattr__(self, "ifc_global_id", ifc_global_id)


class IdentityRegistry:
    """In-memory MVP identity registry with fail-closed rebinding."""

    def __init__(self) -> None:
        self._by_semantic: dict[str, IdentityBinding] = {}
        self._by_native: dict[tuple[str, str], IdentityBinding] = {}

    def bind(self, binding: IdentityBinding) -> IdentityBinding:
        native_key = (binding.document_id, binding.native_id)
        semantic_existing = self._by_semantic.get(binding.semantic_id)
        native_existing = self._by_native.get(native_key)

        if semantic_existing is not None and semantic_existing != binding:
            raise IdentityConflictError(
                f"semantic identity {binding.semantic_id!r} is already bound"
            )
        if native_existing is not None and native_existing != binding:
            raise IdentityConflictError(
                f"native identity {native_key!r} is already bound"
            )

        self._by_semantic[binding.semantic_id] = binding
        self._by_native[native_key] = binding
        return binding

    def by_semantic(self, semantic_id: str) -> IdentityBinding | None:
        return self._by_semantic.get(semantic_id)

    def by_native(self, document_id: str, native_id: str) -> IdentityBinding | None:
        return self._by_native.get((document_id, native_id))
