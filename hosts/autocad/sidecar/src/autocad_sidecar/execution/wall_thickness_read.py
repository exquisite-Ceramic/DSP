"""AutoCAD 墙厚产品 vertical 的独立 normalized-fact READ wrapper。"""

from __future__ import annotations

import asyncio

from design_fact_contracts import FactKind, NormalizedDesignFactBatch


def _run(awaitable):
    """在同步 verification 边界执行 async fact extraction。"""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError(
        "AutoCAD wall-thickness synchronous READ cannot run inside an active event loop"
    )


def _fail(code: str, message: str) -> None:
    """用稳定错误码拒绝不可参与 verification 的 Host evidence。"""

    raise ValueError(f"{code}: {message}")


def _text(value: object, *, code: str, field_name: str) -> str:
    """规范化 READ request identity。"""

    if not isinstance(value, str) or not value.strip():
        _fail(code, f"{field_name} must be a non-blank string")
    return value.strip()


def _revision(value: object) -> int:
    """只接受真实非负 committed revision。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(
            "AUTOCAD_WALL_READ_EXPECTED_REVISION_INVALID",
            "expected_revision must be a non-negative integer",
        )
    return value


class AutoCadWallThicknessFactReadPort:
    """读取 exact AutoCAD wall facts，并绑定 committed runtime/document/revision。"""

    def __init__(self, dispatcher) -> None:
        extractor = getattr(dispatcher, "extract_design_facts", None)
        if not callable(extractor):
            raise TypeError("dispatcher must provide extract_design_facts")
        self._dispatcher = dispatcher

    def read(
        self,
        *,
        host_instance_id: str,
        document_id: str,
        native_id: str,
        expected_revision: int,
    ) -> NormalizedDesignFactBatch:
        """发起一次独立 normalized-fact READ；不接受 mutation response 作为替代。"""

        host = _text(
            host_instance_id,
            code="AUTOCAD_WALL_READ_REQUEST_INVALID",
            field_name="host_instance_id",
        )
        document = _text(
            document_id,
            code="AUTOCAD_WALL_READ_REQUEST_INVALID",
            field_name="document_id",
        )
        native = _text(
            native_id,
            code="AUTOCAD_WALL_READ_REQUEST_INVALID",
            field_name="native_id",
        )
        revision = _revision(expected_revision)
        try:
            batch = _run(self._dispatcher.extract_design_facts([native]))
        except (ConnectionError, OSError, RuntimeError, TypeError, ValueError) as exc:
            _fail("AUTOCAD_WALL_READ_FAILED", f"fact extraction failed: {exc}")
        if not isinstance(batch, NormalizedDesignFactBatch):
            _fail(
                "AUTOCAD_WALL_READ_FAILED",
                "fact extraction did not return NormalizedDesignFactBatch",
            )
        if not batch.facts:
            _fail("AUTOCAD_WALL_READ_FAILED", "fact batch is empty")

        if any(fact.source_revision != revision for fact in batch.facts):
            _fail(
                "AUTOCAD_WALL_READ_REVISION_MISMATCH",
                "fact source revision does not match committed revision",
            )
        if any(fact.host_ref.host_type != "autocad" for fact in batch.facts):
            _fail(
                "AUTOCAD_WALL_READ_HOST_MISMATCH",
                "fact host type is not AutoCAD",
            )
        if any(fact.host_ref.host_instance_id != host for fact in batch.facts):
            _fail(
                "AUTOCAD_WALL_READ_HOST_MISMATCH",
                "fact Host instance does not match requested runtime",
            )
        if any(
            fact.host_ref.document_id != document
            or fact.subject_native_ref.document_id != document
            for fact in batch.facts
        ):
            _fail(
                "AUTOCAD_WALL_READ_DOCUMENT_MISMATCH",
                "fact document does not match requested document",
            )
        if any(fact.subject_native_ref.native_id != native for fact in batch.facts):
            _fail(
                "AUTOCAD_WALL_READ_TARGET_MISMATCH",
                "fact target does not match requested native id",
            )
        if any(
            fact.subject_native_ref.native_kind != "LWPOLYLINE"
            for fact in batch.facts
        ):
            _fail(
                "AUTOCAD_WALL_READ_TARGET_MISMATCH",
                "fact target is not the expected AutoCAD LWPOLYLINE",
            )
        width_facts = tuple(
            fact
            for fact in batch.facts
            if fact.fact_kind is FactKind.PROPERTY
            and fact.predicate == "constant_width"
        )
        if len(width_facts) != 1 or width_facts[0].unit != "mm":
            _fail(
                "AUTOCAD_WALL_READ_FAILED",
                "exact constant_width mm evidence is unavailable",
            )
        return batch


__all__ = ["AutoCadWallThicknessFactReadPort"]
