using System.Text.Json;
using HostContracts;

namespace AutoCAD.AgentHost.Commands.Context;

/// <summary>Read-only: returns the current selection as contract EntityRefs.</summary>
public sealed class CurrentSelectionHandler : HostCommandHandler
{
    public override string CommandType => "context.current_selection";

    public override HostCommandResult Execute(HostCommand command)
    {
        using var _ = Execution.DocumentLockManager.Acquire(Native.AcNative.ActiveDocumentId());

        var refs = Native.AutoCADEntityApi.GetSelectedEntityRefs();
        var payload = JsonSerializer.SerializeToElement(new
        {
            entityRefs = refs,
            revision = Native.AcNative.ActiveDocumentRevision(),
        });

        return new HostCommandResult { Payload = payload };
    }
}
