using HostContracts;

namespace AutoCAD.AgentHost.ChangeCapture;

/// <summary>Builds current HostDelta DTOs from committed AutoCAD change events.</summary>
public sealed class HostDeltaBuilder
{
    public IReadOnlyList<HostDelta> Build(object? sender, EventArgs args, string operation)
    {
        var change = Native.AutoCADEntityApi.DescribeChange(sender, args, operation);
        if (change is null)
        {
            return Array.Empty<HostDelta>();
        }

        var revisionAfter = (int)Native.AcNative.ActiveDocumentRevision();
        var delta = new HostDelta
        {
            RevisionBefore = Math.Max(0, revisionAfter - 1),
            RevisionAfter = revisionAfter,
        };

        switch (operation)
        {
            case "created":
                delta.Added.Add(change.Value.EntityRef);
                break;
            case "deleted":
                delta.Erased.Add(change.Value.EntityRef);
                break;
            default:
                delta.Modified.Add(change.Value.EntityRef);
                break;
        }

        return new[] { delta };
    }
}
