using System.Text.Json;
using HostContracts;

namespace AutoCAD.AgentHost.Commands.Context;

/// <summary>Read-only: returns identity of the active document.</summary>
public sealed class CurrentDocumentHandler : HostCommandHandler
{
    public override string CommandType => "context.current_document";

    public override HostCommandResult Execute(HostCommand command)
    {
        var payload = JsonSerializer.SerializeToElement(new
        {
            documentId = Native.AcNative.ActiveDocumentId(),
            documentName = Native.AcNative.ActiveDocumentName(),
            revision = Native.AcNative.ActiveDocumentRevision(),
        });

        return new HostCommandResult { Ok = true, Payload = payload };
    }
}
