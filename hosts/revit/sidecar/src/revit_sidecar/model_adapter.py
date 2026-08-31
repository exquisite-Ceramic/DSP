from __future__ import annotations

import math

from host_contracts.command import HostCommand
from host_contracts.entity_ref import HostEntityRef


class RevitHostAdapter:
    @staticmethod
    def build_set_wall_thickness_command(
        *,
        command_id: str,
        document_id: str,
        wall_unique_id: str,
        expected_revision: int,
        thickness_mm: float,
        idempotency_key: str,
    ) -> HostCommand:
        if not math.isfinite(thickness_mm) or thickness_mm <= 0:
            raise ValueError("thickness_mm must be finite and positive")

        return HostCommand(
            command_id=command_id,
            document_id=document_id,
            mode="EXECUTE",
            operation="set_wall_thickness",
            target_native_refs=[
                HostEntityRef(
                    document_id=document_id,
                    native_id=wall_unique_id,
                    native_type="Wall",
                )
            ],
            arguments={"thickness": {"value": thickness_mm, "unit": "mm"}},
            preconditions=[{"revision": expected_revision}],
            idempotency_key=idempotency_key,
        )
