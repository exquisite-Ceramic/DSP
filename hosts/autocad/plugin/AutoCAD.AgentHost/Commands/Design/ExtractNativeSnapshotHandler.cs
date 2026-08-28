using System.Text.Json;
using HostContracts;

namespace AutoCAD.AgentHost.Commands.Design;

/// <summary>Read-only Host command that returns AutoCAD-local native entity snapshots.</summary>
public sealed class ExtractNativeSnapshotHandler : HostCommandHandler
{
    public override string CommandType => "design.extract_native_snapshot";

    public override HostCommandResult Execute(HostCommand command)
    {
        if (command.Mode != HostCommandMode.READ)
        {
            throw new InvalidOperationException("design.extract_native_snapshot requires READ mode");
        }

        if (command.Arguments is not JsonElement arguments
            || arguments.ValueKind != JsonValueKind.Object
            || !arguments.TryGetProperty("handles", out var handleElement)
            || handleElement.ValueKind != JsonValueKind.Array)
        {
            throw new ArgumentException("arguments.handles must be an array");
        }

        var handles = new List<string>();
        foreach (var item in handleElement.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.String)
            {
                throw new ArgumentException("arguments.handles must contain only strings");
            }

            var handle = item.GetString();
            if (string.IsNullOrWhiteSpace(handle))
            {
                throw new ArgumentException("arguments.handles must contain non-empty strings");
            }

            handles.Add(handle);
        }

        using var _ = Execution.DocumentLockManager.Acquire(Native.AcNative.ActiveDocumentId());
        var snapshot = Native.AutoCADNativeFactApi.Extract(handles);
        var payload = JsonSerializer.SerializeToElement(snapshot);

        return new HostCommandResult { Payload = payload };
    }
}
