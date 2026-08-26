namespace AutoCAD.AgentHost.Identity;

/// <summary>
/// Stable identity of a drawing plus its monotonically increasing revision.
/// Revision is bumped after every committed transaction that mutates entities
/// (see Native/AutoCADDocumentApi) and is the value compared by RevisionGuard.
/// </summary>
public sealed class DrawingIdentity
{
    public string DocumentId { get; init; } = string.Empty;

    public string DocumentName { get; init; } = string.Empty;

    public long Revision { get; internal set; }

    public override string ToString() => $"{DocumentName} ({DocumentId}) rev {Revision}";
}
