using HostContracts;

namespace AutoCAD.AgentHost.Execution;

/// <summary>
/// Rejects stale writes: a write command carrying an expected revision that
/// does not match the document's current revision fails with
/// <c>revision_conflict</c> (spec §7).
/// </summary>
public sealed class RevisionGuard
{
    public HostError? Validate(string documentId, HostCommand command)
    {
        if (command.Revision is null)
        {
            return null; // read command or caller opted out
        }

        var current = Native.AcNative.ActiveDocumentRevision();
        if (command.Revision.Value == current)
        {
            return null;
        }

        return new HostError
        {
            Code = "revision_conflict",
            Message = $"expected revision {command.Revision.Value}, current is {current}.",
            Retryable = true,
        };
    }
}
