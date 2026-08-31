from __future__ import annotations

import os

import pytest

from autocad_live_host import live_autocad_host_adapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from design_fact_contracts import FactKind

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AGENT_HOST_TEST") != "1",
        reason="requires live AutoCAD host (AGENT_HOST_TEST=1)",
    ),
]


@pytest.mark.asyncio
async def test_live_lwpolyline_constant_width_is_normalized_as_mm_property() -> None:
    host = live_autocad_host_adapter()

    try:
        dispatcher = CommandDispatcher(host)
        selection = await dispatcher.current_selection()
        assert selection.ok, selection.error

        refs = (selection.payload or {}).get("entityRefs", [])
        assert refs, "select the Step34 LWPOLYLINE fixture in AutoCAD"
        assert any(
            str(ref.get("native_type", "")).upper() in {"POLYLINE", "LWPOLYLINE"}
            for ref in refs
        ), "selected entity must include the Step34 LWPOLYLINE fixture"

        handles = [str(ref["native_id"]) for ref in refs]
        batch = await dispatcher.extract_design_facts(handles)
    finally:
        await host.close()

    width_facts = [
        fact
        for fact in batch.facts
        if fact.fact_kind is FactKind.PROPERTY and fact.predicate == "constant_width"
    ]
    assert len(width_facts) == 1, (
        "expected one ConstantWidth property fact from the selected AutoCAD LWPOLYLINE"
    )

    width_fact = width_facts[0]
    assert width_fact.value == 200.0
    assert width_fact.unit == "mm"
    assert width_fact.source_scheme == "autocad.property"
    assert width_fact.source_code == "LWPOLYLINE.ConstantWidth"
