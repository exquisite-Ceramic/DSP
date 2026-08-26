using AutoCAD.AgentHost.ChangeCapture;
using AutoCAD.AgentHost.Commands;
using AutoCAD.AgentHost.Execution;
using AutoCAD.AgentHost.Ipc;

namespace AutoCAD.AgentHost.Bootstrap;

/// <summary>
/// Owns the plugin lifecycle: starts the pipe server, wires the command
/// dispatcher and the change-capture pipeline, and tears everything down
/// on <see cref="Stop"/>.
/// </summary>
public sealed class PluginLifecycle
{
    private NamedPipeServer? _server;
    private ChangeSensor? _sensor;

    public void Start()
    {
        var dispatcher = new RequestDispatcher(
            new HostCommandHandlerRegistry(),
            new IdempotencyStore(),
            new RevisionGuard());

        _server = new NamedPipeServer(dispatcher);
        _server.Start();

        _sensor = new ChangeSensor(new HostDeltaBuilder(), new EventQueue());
        _sensor.Attach();
    }

    public void Stop()
    {
        _sensor?.Detach();
        _sensor = null;
        _server?.Stop();
        _server = null;
    }
}
