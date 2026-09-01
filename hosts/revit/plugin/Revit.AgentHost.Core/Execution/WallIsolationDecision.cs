using Revit.AgentHost.Core.Contracts;

namespace Revit.AgentHost.Core.Execution;

public sealed record WallIsolationDecision(bool IsEligible, string? Code)
{
    public const string TargetCountOutsideMvp = "TARGET_COUNT_OUTSIDE_MVP";
    public const string TargetResolutionFailed = "TARGET_RESOLUTION_FAILED";
    public const string UnsupportedWallKind = "UNSUPPORTED_WALL_KIND";
    public const string SharedWallTypeOutsideScope = "SHARED_WALL_TYPE_OUTSIDE_SCOPE";
    public const string WallInsertsOutsideMvp = "WALL_INSERTS_OUTSIDE_MVP";
    public const string WallJoinOutsideMvp = "WALL_JOIN_OUTSIDE_MVP";
    public const string WallAssociativityUnproven = "WALL_ASSOCIATIVITY_UNPROVEN";

    public static WallIsolationDecision Evaluate(WallIsolationEvidence evidence)
    {
        ArgumentNullException.ThrowIfNull(evidence);

        if (evidence.ApprovedTargetCount != 1)
        {
            return Reject(TargetCountOutsideMvp);
        }

        if (!evidence.TargetResolved
            || !evidence.NativeKindMatches
            || !evidence.DocumentMatches
            || string.IsNullOrWhiteSpace(evidence.WallUniqueId)
            || string.IsNullOrWhiteSpace(evidence.WallTypeUniqueId))
        {
            return Reject(TargetResolutionFailed);
        }

        if (!evidence.IsBasicWall)
        {
            return Reject(UnsupportedWallKind);
        }

        if (evidence.SameTypeWallUniqueIds.Count != 1
            || !string.Equals(
                evidence.SameTypeWallUniqueIds[0],
                evidence.WallUniqueId,
                StringComparison.Ordinal))
        {
            return Reject(SharedWallTypeOutsideScope);
        }

        if (evidence.InsertUniqueIds.Count != 0)
        {
            return Reject(WallInsertsOutsideMvp);
        }

        if (evidence.JoinEnd0UniqueIds.Count != 0 || evidence.JoinEnd1UniqueIds.Count != 0)
        {
            return Reject(WallJoinOutsideMvp);
        }

        if (!evidence.AssociativityProven || evidence.UnsupportedDependencyUniqueIds.Count != 0)
        {
            return Reject(WallAssociativityUnproven);
        }

        return new WallIsolationDecision(true, null);
    }

    private static WallIsolationDecision Reject(string code)
    {
        return new WallIsolationDecision(false, code);
    }
}
