import pytest

from autocad_sidecar.ipc.transport import PipeTransport
from autocad_sidecar.ipc.transport_selector import build_transport


def test_selector_builds_pipe_transport():
    transport = build_transport("pipe", pipe_name="EnterpriseDesignAgent.test")
    assert isinstance(transport, PipeTransport)


def test_selector_requires_instance_id_for_grpc():
    with pytest.raises(ValueError, match="instance_id"):
        build_transport("grpc")


def test_selector_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unsupported transport"):
        build_transport("udp")
