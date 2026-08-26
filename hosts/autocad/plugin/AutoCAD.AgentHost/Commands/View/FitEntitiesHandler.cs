using HostContracts;

namespace AutoCAD.AgentHost.Commands.View;

/// <summary>View command: zooms to drawing extents (fit). No model mutation.</summary>
public sealed class FitEntitiesHandler : HostCommandHandler
{
    public override string CommandType => "view.fit";

    public override HostCommandResult Execute(HostCommand command)
    {
        // Optional: zoom to the given handles instead of whole drawing.
        var handles = command.Params.TryGetProperty("handles", out var h)
            ? h.Deserialize<string[]>() ?? Array.Empty<string>()
            : Array.Empty<string>();

        Native.AutoCADViewApi.ZoomExtents(handles);

        return new HostCommandResult { Ok = true, Payload = System.Text.Json.JsonDocument.Parse("{}").RootElement.Clone() };
    }
}
