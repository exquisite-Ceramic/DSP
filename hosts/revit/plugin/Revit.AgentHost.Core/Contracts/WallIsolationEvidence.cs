namespace Revit.AgentHost.Core.Contracts;

public sealed record WallIsolationEvidence(
    int ApprovedTargetCount,
    bool TargetResolved,
    bool NativeKindMatches,
    bool DocumentMatches,
    bool IsBasicWall,
    string? WallUniqueId,
    string? WallTypeUniqueId,
    IReadOnlyList<string> SameTypeWallUniqueIds,
    IReadOnlyList<string> InsertUniqueIds,
    IReadOnlyList<string> JoinEnd0UniqueIds,
    IReadOnlyList<string> JoinEnd1UniqueIds,
    IReadOnlyList<string> UnsupportedDependencyUniqueIds,
    bool AssociativityProven = true);
