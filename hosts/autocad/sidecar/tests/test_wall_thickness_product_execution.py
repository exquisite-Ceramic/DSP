"""Task 12 RED：AutoCAD 墙厚 production Host I/O wrappers。"""

from __future__ import annotations

from importlib import import_module

import pytest
from autocad_sidecar.adapter.design_fact_adapter import DesignFactAdapter
from design_fact_contracts import FactKind
from host_contracts import HostCommandResult


def _api():
    mutation = import_module("autocad_sidecar.execution.wall_thickness")
    read = import_module("autocad_sidecar.execution.wall_thickness_read")
    mutation_type = getattr(mutation, "AutoCadWallThicknessMutationPort", None)
    read_type = getattr(read, "AutoCadWallThicknessFactReadPort", None)
    assert mutation_type is not None, "AutoCadWallThicknessMutationPort 尚未实现"
    assert read_type is not None, "AutoCadWallThicknessFactReadPort 尚未实现"
    return mutation_type, read_type


class _Dispatcher:
    """只实现 production public dispatcher API；测试禁止走 Phase I helper。"""

    def __init__(self) -> None:
        self.mutations = []
        self.reads = []
        self.mutation_result = HostCommandResult(
            command_id="CMD-AUTOCAD-1",
            status="OK",
            payload={
                "updated": 1,
                "beforeWidths": {"A31": 200.0},
                "widths": {"A31": 300.0},
                "unit": "mm",
            },
            revision_after=12,
        )
        self.read_batch = DesignFactAdapter().normalize_snapshot(
            {
                "hostInstanceId": "AUTOCAD-01",
                "documentId": "DOC-AUTOCAD",
                "revision": 12,
                "entities": [
                    {
                        "nativeId": "A31",
                        "nativeKind": "LWPOLYLINE",
                        "layer": "A-WALL",
                        "properties": {
                            "constantWidth": {"value": 300.0, "unit": "mm"}
                        },
                    }
                ],
            }
        )

    async def set_wall_thickness(
        self,
        handles,
        thickness_mm,
        *,
        idempotency_key=None,
        revision=None,
    ):
        self.mutations.append(
            (tuple(handles), thickness_mm, idempotency_key, revision)
        )
        return self.mutation_result

    async def extract_design_facts(self, handles):
        self.reads.append(tuple(handles))
        return self.read_batch


def test_mutation_wrapper_uses_exact_public_dispatcher_revision_and_idempotency() -> None:
    """production mutation wrapper 只能透传 exact target、revision 与 durable idempotency key。"""

    mutation_type, _ = _api()
    dispatcher = _Dispatcher()
    port = mutation_type(dispatcher)

    result = port.execute(
        native_id="A31",
        thickness_mm=300.0,
        idempotency_key="IDEMPOTENCY-1",
        expected_revision=11,
    )

    assert result is dispatcher.mutation_result
    assert dispatcher.mutations == [(("A31",), 300.0, "IDEMPOTENCY-1", 11)]


def test_independent_read_requires_exact_runtime_document_target_and_revision() -> None:
    """独立 READ 只能接受 exact committed revision 的 normalized AutoCAD facts。"""

    _, read_type = _api()
    dispatcher = _Dispatcher()
    port = read_type(dispatcher)

    batch = port.read(
        host_instance_id="AUTOCAD-01",
        document_id="DOC-AUTOCAD",
        native_id="A31",
        expected_revision=12,
    )

    assert dispatcher.reads == [("A31",)]
    width = next(
        fact
        for fact in batch.facts
        if fact.fact_kind is FactKind.PROPERTY
        and fact.predicate == "constant_width"
    )
    assert width.value == 300.0
    assert width.unit == "mm"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("revision", 13, "AUTOCAD_WALL_READ_REVISION_MISMATCH"),
        ("document", "DOC-OTHER", "AUTOCAD_WALL_READ_DOCUMENT_MISMATCH"),
        ("host", "AUTOCAD-OTHER", "AUTOCAD_WALL_READ_HOST_MISMATCH"),
        ("target", "OTHER", "AUTOCAD_WALL_READ_TARGET_MISMATCH"),
    ),
)
def test_independent_read_rejects_correlated_identity_or_revision_drift(
    field: str,
    value,
    code: str,
) -> None:
    """新 READ 的采集元数据可变化，但稳定 identity/revision 不得变化。"""

    _, read_type = _api()
    dispatcher = _Dispatcher()
    payload = {
        "hostInstanceId": "AUTOCAD-01",
        "documentId": "DOC-AUTOCAD",
        "revision": 12,
        "entities": [
            {
                "nativeId": "A31",
                "nativeKind": "LWPOLYLINE",
                "layer": "A-WALL",
                "properties": {
                    "constantWidth": {"value": 300.0, "unit": "mm"}
                },
            }
        ],
    }
    if field == "revision":
        payload["revision"] = value
    elif field == "document":
        payload["documentId"] = value
    elif field == "host":
        payload["hostInstanceId"] = value
    else:
        payload["entities"][0]["nativeId"] = value
    dispatcher.read_batch = DesignFactAdapter().normalize_snapshot(payload)
    port = read_type(dispatcher)

    with pytest.raises(ValueError, match=code):
        port.read(
            host_instance_id="AUTOCAD-01",
            document_id="DOC-AUTOCAD",
            native_id="A31",
            expected_revision=12,
        )


def test_mutation_transport_exception_is_not_retried_by_wrapper() -> None:
    """dispatcher 已跨过 EXECUTE transport 边界时，wrapper 不得自行重复发送。"""

    mutation_type, _ = _api()

    class _LostDispatcher(_Dispatcher):
        async def set_wall_thickness(self, *args, **kwargs):
            self.mutations.append((args, kwargs))
            raise ConnectionError("response lost")

    dispatcher = _LostDispatcher()
    port = mutation_type(dispatcher)
    with pytest.raises(ConnectionError):
        port.execute(
            native_id="A31",
            thickness_mm=300.0,
            idempotency_key="IDEMPOTENCY-LOST",
            expected_revision=11,
        )
    assert len(dispatcher.mutations) == 1
