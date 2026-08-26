from host_contracts.envelope import CONTRACT_VERSION, RequestEnvelope, ResponseEnvelope


def test_request_envelope_writes_contract_version():
    env = RequestEnvelope(request_id="req-1")
    assert env.to_dict()["contract_version"] == CONTRACT_VERSION


def test_request_envelope_rejects_missing_or_unsupported_contract_version():
    missing = RequestEnvelope.from_dict({"request_id": "req-1", "payload": {}})
    unsupported = RequestEnvelope.from_dict({"contract_version": "2.0", "request_id": "req-1", "payload": {}})
    assert any("contract_version" in error for error in missing.validate())
    assert any("contract_version" in error for error in unsupported.validate())


def test_response_envelope_writes_and_validates_contract_version():
    env = ResponseEnvelope(request_id="req-1")
    assert env.to_dict()["contract_version"] == CONTRACT_VERSION
    missing = ResponseEnvelope.from_dict({"request_id": "req-1", "status": "OK"})
    assert any("contract_version" in error for error in missing.validate())
