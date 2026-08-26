using HostContracts;

namespace AutoCAD.AgentHost.ChangeCapture;

/// <summary>
/// Builds contract <see cref="HostDelta"/> instances from raw AutoCAD change
/// events. Only committed state is read back, so deltas never expose
/// mid-transaction state (spec §8).
/// </summary>
public sealed class HostDeltaBuilder
{
    public IReadOnlyList<HostDelta> Build(object sender, EventArgs args, string operation)
    {
        // Native.AutoCADEntityApi.DescribeChange(sender, args) returns
        // (handle, className, layer, before, after) or nothing when the
        // change is not entity-related.
        var change = Native.AutoCADEntityApi.DescribeChange(sender, args, operation);
        if (change is null)
        {
            return Array.Empty<HostDelta>();
        }

        var delta = new HostDelta
        {
            EntityRef = change.Value.EntityRef,
            Revision = (int)Native.AcNative.ActiveDocumentRevision(),
            Operation = operation,
            Before = change.Value.Before,
            After = change.Value.After,
        };

        return new[] { delta };
    }
}
