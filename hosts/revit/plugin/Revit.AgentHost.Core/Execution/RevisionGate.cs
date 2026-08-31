namespace Revit.AgentHost.Core.Execution;

public sealed class RevisionConflictException : InvalidOperationException
{
    public const string StableCode = "REVISION_CONFLICT";

    public RevisionConflictException(long currentRevision, long expectedRevision)
        : base($"Current document revision {currentRevision} does not match expected revision {expectedRevision}.")
    {
        CurrentRevision = currentRevision;
        ExpectedRevision = expectedRevision;
    }

    public string Code => StableCode;

    public long CurrentRevision { get; }

    public long ExpectedRevision { get; }
}

public static class RevisionGate
{
    public static void RequireExpected(long currentRevision, long expectedRevision)
    {
        if (currentRevision < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(currentRevision));
        }

        if (expectedRevision < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(expectedRevision));
        }

        if (currentRevision != expectedRevision)
        {
            throw new RevisionConflictException(currentRevision, expectedRevision);
        }
    }
}
