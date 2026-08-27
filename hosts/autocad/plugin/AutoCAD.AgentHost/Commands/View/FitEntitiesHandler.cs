using System.Text.Json;
using HostContracts;

namespace AutoCAD.AgentHost.Commands.View;

/// <summary>View command: zooms to drawing extents or the supplied handles.</summary>
public sealed class FitEntitiesHandler : HostCommandHandler
{
    public override string CommandType => "view.fit_entities";

    public override HostCommandResult Execute(HostCommand command)
    {
        var handles = Array.Empty<string>();
        if (command.Arguments is JsonElement arguments
            && arguments.ValueKind == JsonValueKind.Object
            && arguments.TryGetProperty("handles", out var handleElement))
        {
            handles = handleElement.Deserialize<string[]>() ?? Array.Empty<string>();
        }

        Native.AutoCADViewApi.ZoomExtents(handles);
        return new HostCommandResult
        {
            Payload = JsonDocument.Parse("{}").RootElement.Clone(),
        };
    }
}
