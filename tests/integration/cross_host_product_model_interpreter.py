"""Task 16 受控现场的真实 Anthropic SDK 模型解释子进程。

只接收 correlation/utterance，输出 production AgentInterpreter 的窄 JSON；
实际 provider 响应和 usage 另存到本次 case 的独占证据文件。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anthropic


def run_model(payload: object, environment: dict[str, str]) -> dict:
    """通过已安装 SDK 发起唯一一次真实 provider 请求，缺证据立即停止。"""

    if not isinstance(payload, dict) or set(payload) != {"client_submission_ref", "utterance"}:
        raise ValueError("MODEL_INPUT_INVALID")
    if not all(isinstance(payload[key], str) and payload[key].strip() for key in payload):
        raise ValueError("MODEL_INPUT_INVALID")
    required = (
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "DSP_MODEL_CANDIDATE_KEY",
        "DSP_MODEL_EVIDENCE_FILE",
    )
    if any(not environment.get(key, "").strip() for key in required):
        raise ValueError("MODEL_ENV_INVALID")
    forbidden = {
        key
        for key in environment
        if key.startswith("DSP_")
        and key not in {"DSP_MODEL_CANDIDATE_KEY", "DSP_MODEL_EVIDENCE_FILE"}
    }
    if forbidden:
        raise ValueError("MODEL_AUTHORITY_ENV_INVALID")
    candidate = environment["DSP_MODEL_CANDIDATE_KEY"]
    model = environment["ANTHROPIC_MODEL"]
    client = anthropic.Anthropic(
        auth_token=environment["ANTHROPIC_AUTH_TOKEN"],
        base_url=environment["ANTHROPIC_BASE_URL"],
        max_retries=0,
        timeout=25,
    )
    response = client.messages.create(
        model=model,
        max_tokens=300,
        thinking={"type": "disabled"},
        system=(
            "Interpret the user's wall thickness request for one configured cross-host wall pair. "
            "Only propose the candidate key and requested thickness. "
            "The configured candidate key is "
            + json.dumps(candidate)
            + '. Return exactly one JSON object: {"kind":"PROPOSAL","candidate_key":"...",'
            '"thickness":{"value":number,"unit":"mm"}} or '
            '{"kind":"CLARIFICATION_REQUIRED","question":"..."}. '
            "Convert units to mm. Do not invent missing intent. You have no tools or authority "
            "to approve or execute."
        ),
        messages=[{"role": "user", "content": payload["utterance"]}],
    )
    raw_response = response.model_dump()
    content = raw_response.get("content", [])
    output = json.loads("".join(block["text"] for block in content if block["type"] == "text"))
    record = {
        "client_submission_ref": payload["client_submission_ref"],
        "model_name": model,
        "invocation_id": response.id,
        "request_id": getattr(response, "_request_id", None),
        "response_model": response.model,
        "proposal": output,
        "raw_response": raw_response,
        "usage": response.usage.model_dump(),
    }
    serialized = json.dumps(record, ensure_ascii=False, allow_nan=False)
    if environment["ANTHROPIC_AUTH_TOKEN"] in serialized:
        raise ValueError("MODEL_SECRET_IN_EVIDENCE")
    evidence = Path(environment["DSP_MODEL_EVIDENCE_FILE"])
    with evidence.open("x", encoding="utf-8") as stream:
        stream.write(serialized)
        stream.flush()
        os.fsync(stream.fileno())
    return output


def main() -> None:
    """异常仅输出固定码，绝不回显 provider 的错误正文或环境。"""

    try:
        payload = json.load(sys.stdin)
        output = run_model(payload, dict(os.environ))
        print(json.dumps(output, ensure_ascii=False, allow_nan=False))
    except Exception:
        raise SystemExit("MODEL_CALL_FAILED: inspect controlled case evidence") from None


if __name__ == "__main__":
    main()
