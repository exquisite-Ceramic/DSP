from pathlib import Path


def _lifecycle_source() -> str:
    return Path(
        "hosts/autocad/plugin/AutoCAD.AgentHost/Bootstrap/PluginLifecycle.cs"
    ).read_text(encoding="utf-8")


def test_plugin_lifecycle_keeps_pipe_and_adds_grpc_during_migration():
    lifecycle = _lifecycle_source()
    assert "NamedPipeServer" in lifecycle
    assert "GrpcHostServer" in lifecycle
    assert "DiscoveryPublisher" in lifecycle


def test_plugin_lifecycle_does_not_block_autocad_thread_on_grpc_startup():
    lifecycle = _lifecycle_source()
    assert "StartGrpcAsync(dispatcher).GetAwaiter().GetResult()" not in lifecycle
    assert "_grpcStartupTask = Task.Run(" in lifecycle
    assert "_grpcStartupCts" in lifecycle
    assert "_grpcStartupCts?.Cancel();" in lifecycle


def test_plugin_project_references_transport_project():
    project = Path(
        "hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj"
    ).read_text(encoding="utf-8")
    assert "AutoCAD.AgentHost.Grpc.csproj" in project
