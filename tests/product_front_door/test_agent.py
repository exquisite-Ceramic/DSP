"""Task 4：SubprocessAgentInterpreter 的窄 JSON 边界契约测试。"""

from __future__ import annotations

import json
import sys

import pytest

import design_product_front_door as front_door


def _interpreter_type():
    """延迟取得 subprocess interpreter，使尚未实现时形成明确 TDD RED。"""

    interpreter_type = getattr(front_door, "SubprocessAgentInterpreter", None)
    assert interpreter_type is not None, "SubprocessAgentInterpreter 尚未实现"
    return interpreter_type


def _command_for_payload(payload: object, *, inspect_input: bool = True) -> list[str]:
    """构造最小真实子进程；可校验 stdin 只含 correlation + utterance。"""

    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    statements = ["import json,sys", "data=json.load(sys.stdin)"]
    if inspect_input:
        statements.append(
            "assert set(data)=={'client_submission_ref','utterance'}, data"
        )
        statements.append("assert data['client_submission_ref']=='agent-001'")
        statements.append("assert data['utterance']=='把墙改成 300mm。'")
    statements.append(f"print({encoded!r})")
    return [sys.executable, "-c", ";".join(statements)]


def test_subprocess_interpreter_sends_only_correlation_and_utterance_and_decodes_proposal() -> None:
    """真实 subprocess stdin 不携带业务 identity；合法 proposal 被还原为窄 dataclass。"""

    interpreter_type = _interpreter_type()
    interpreter = interpreter_type(
        command=_command_for_payload(
            {
                "kind": "PROPOSAL",
                "candidate_key": "primary-revit",
                "thickness": {"value": 300, "unit": "mm"},
            }
        )
    )

    result = interpreter.interpret(
        client_submission_ref="agent-001",
        utterance="把墙改成 300mm。",
    )

    assert isinstance(result, front_door.AgentProposal)
    assert result.candidate_key == "primary-revit"
    assert result.thickness_value == 300.0
    assert result.thickness_unit == "mm"


def test_subprocess_interpreter_decodes_clarification_without_business_identity() -> None:
    """合法 clarification 只返回用户问题，不增加 candidate/task/session 字段。"""

    interpreter_type = _interpreter_type()
    interpreter = interpreter_type(
        command=_command_for_payload(
            {
                "kind": "CLARIFICATION_REQUIRED",
                "question": "请确认要修改 primary-revit 吗？",
            }
        )
    )

    result = interpreter.interpret(
        client_submission_ref="agent-001",
        utterance="把墙改成 300mm。",
    )

    assert isinstance(result, front_door.AgentClarificationRequired)
    assert result.question == "请确认要修改 primary-revit 吗？"


@pytest.mark.parametrize(
    "forbidden_field",
    [
        "project_id",
        "host_kind",
        "task_id",
        "session_ref",
        "pause_id",
        "resume",
        "approval",
    ],
)
def test_subprocess_interpreter_rejects_forbidden_authority_fields(
    forbidden_field: str,
) -> None:
    """模型输出不得携带 controller/server authority 字段，即使其余 proposal 合法。"""

    interpreter_type = _interpreter_type()
    payload = {
        "kind": "PROPOSAL",
        "candidate_key": "primary-revit",
        "thickness": {"value": 300, "unit": "mm"},
        forbidden_field: "forbidden",
    }
    interpreter = interpreter_type(command=_command_for_payload(payload))

    with pytest.raises(ValueError, match="FRONT_DOOR_AGENT_OUTPUT_INVALID"):
        interpreter.interpret(
            client_submission_ref="agent-001",
            utterance="把墙改成 300mm。",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "kind": "PROPOSAL",
            "candidate_key": "primary-revit",
            "thickness": {"value": 300, "unit": "mm", "unknown": True},
        },
        {
            "kind": "PROPOSAL",
            "candidate_key": "primary-revit",
            "thickness": {"value": True, "unit": "mm"},
        },
        {
            "kind": "PROPOSAL",
            "candidate_key": "primary-revit",
            "thickness": {"value": 300, "unit": "cm"},
        },
        {
            "kind": "CLARIFICATION_REQUIRED",
            "question": " ",
        },
        {
            "kind": "UNKNOWN",
            "candidate_key": "primary-revit",
        },
    ],
)
def test_subprocess_interpreter_rejects_malformed_or_expanded_outputs(payload: object) -> None:
    """未知 kind、空问题、非法 thickness 或扩张字段一律 fail closed。"""

    interpreter_type = _interpreter_type()
    interpreter = interpreter_type(command=_command_for_payload(payload))

    with pytest.raises(ValueError, match="FRONT_DOOR_AGENT_OUTPUT_INVALID"):
        interpreter.interpret(
            client_submission_ref="agent-001",
            utterance="把墙改成 300mm。",
        )


def test_subprocess_interpreter_requires_stdout_to_be_one_json_document() -> None:
    """stdout 不能在合法 JSON 前后夹带第二段模型文本或解释。"""

    interpreter_type = _interpreter_type()
    payload = json.dumps(
        {
            "kind": "PROPOSAL",
            "candidate_key": "primary-revit",
            "thickness": {"value": 300, "unit": "mm"},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    code = ";".join(
        [
            "import json,sys",
            "json.load(sys.stdin)",
            f"print({payload!r})",
            "print('extra model text')",
        ]
    )
    interpreter = interpreter_type(command=[sys.executable, "-c", code])

    with pytest.raises(ValueError, match="FRONT_DOOR_AGENT_OUTPUT_INVALID"):
        interpreter.interpret(
            client_submission_ref="agent-001",
            utterance="把墙改成 300mm。",
        )


def test_subprocess_interpreter_maps_nonzero_process_exit_to_stable_error() -> None:
    """模型子进程失败不能被误报为 clarification/proposal。"""

    interpreter_type = _interpreter_type()
    interpreter = interpreter_type(
        command=[sys.executable, "-c", "import sys;sys.exit(7)"]
    )

    with pytest.raises(ValueError, match="FRONT_DOOR_AGENT_PROCESS_FAILED"):
        interpreter.interpret(
            client_submission_ref="agent-001",
            utterance="把墙改成 300mm。",
        )
