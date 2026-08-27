"""Transport-only protobuf surface tests."""

from autocad_sidecar.ipc.generated import host_transport_v1_pb2 as pb


def test_transport_proto_is_transport_only():
    req = pb.DispatchRequest(contract_json=b'{"request_id":"r1","payload":{}}')
    assert req.contract_json.startswith(b"{")

    message_names = set(pb.DESCRIPTOR.message_types_by_name)
    assert message_names == {
        "PingRequest",
        "PingResponse",
        "DispatchRequest",
        "DispatchResponse",
    }
    assert "HostCommand" not in message_names
    assert "HostDelta" not in message_names
