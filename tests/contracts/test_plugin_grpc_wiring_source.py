from pathlib import Path


def test_plugin_lifecycle_keeps_pipe_and_adds_grpc_during_migration():
    lifecycle = Path(
        "hosts/autocad/plugin/AutoCAD.AgentHost/Bootstrap/PluginLifecycle.cs"
    ).read_text(encoding="utf-8")
    assert "NamedPipeServer" in lifecycle
    assert "GrpcHostServer" in lifecycle
    assert "DiscoveryPublisher" in lifecycle


def test_plugin_project_references_transport_project():
    project = Path(
        "hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj"
    ).read_text(encoding="utf-8")
    assert "AutoCAD.AgentHost.Grpc.csproj" in project
