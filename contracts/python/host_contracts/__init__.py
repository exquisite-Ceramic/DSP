"""HostContract Python mirror implementation (v1.0, snake_case wire format).

Single source of truth: ``contracts/schemas/*.json`` (spec v0.6 / §23.1).
Keep in sync with ``contracts/dotnet/HostContracts``.
"""

from host_contracts.command import HostCommand
from host_contracts.delta import HostDelta
from host_contracts.entity_ref import HostEntityRef
from host_contracts.envelope import (
    CONTRACT_MAJOR,
    CONTRACT_MINOR,
    CONTRACT_VERSION,
    AsyncOperationRef,
    RequestEnvelope,
    ResponseEnvelope,
    deadline_within,
    is_valid_utc,
)
from host_contracts.error import ErrorShape
from host_contracts.result import HostCommandResult
from host_contracts.status import HostStatus

__all__ = [
    "CONTRACT_MAJOR",
    "CONTRACT_MINOR",
    "CONTRACT_VERSION",
    "RequestEnvelope",
    "ResponseEnvelope",
    "AsyncOperationRef",
    "HostEntityRef",
    "HostCommand",
    "HostCommandResult",
    "HostDelta",
    "ErrorShape",
    "HostStatus",
    "deadline_within",
    "is_valid_utc",
]
