"""Task 7：冻结 ExecutionGrant 所需的显式 workflow lineage seam。

真实 Gateway V2 发 grant 必须同时验证 approval、execution plan 与 provider binding。
这些 StableRef 已经存在于 workflow state，因此必须由 graph/service 显式透传；禁止为了
维持旧单参数 seam 而在 CanonicalWorkflowOwnerPorts 中新增反向索引或私有 lineage map。
"""

from __future__ import annotations

import inspect

from design_orchestrator.default_workflow_services import (
    DefaultWorkflowServices,
    ExternalOwnerPorts,
)
from design_orchestrator.workflow_services import WorkflowServices


def _parameter_names(owner: object, method_name: str) -> tuple[str, ...]:
    """读取公开方法参数名，忽略 annotation 文本等非行为契约细节。"""

    method = getattr(owner, method_name)
    return tuple(inspect.signature(method).parameters)


def test_task7_execution_grant_seam_carries_all_authoritative_refs() -> None:
    """Grant seam 必须显式携带 Gateway V2 校验所需的三条 authoritative lineage。"""

    expected = (
        "self",
        "execution_plan_ref",
        "approval_ref",
        "provider_binding_ref",
    )

    assert _parameter_names(WorkflowServices, "issue_execution_grant") == expected
    assert _parameter_names(ExternalOwnerPorts, "issue_execution_grant") == expected
    assert _parameter_names(DefaultWorkflowServices, "issue_execution_grant") == expected
