"""ExecutionUnit: groups slices and carries the result of applying them."""

from __future__ import annotations

from dataclasses import dataclass, field

from changeset.execution_slice import ExecutionSlice


@dataclass(slots=True)
class ExecutionUnit:
    """One command-shaped unit compiled from a change set: the slices plus
    the outcome of applying them to the host."""

    change_set_id: str
    slices: list[ExecutionSlice] = field(default_factory=list)
    ok: bool = False
    applied_revision: int | None = None
    error_code: str | None = None
    error_message: str | None = None

    def add_slice(self, slice_: ExecutionSlice) -> None:
        self.slices.append(slice_)
