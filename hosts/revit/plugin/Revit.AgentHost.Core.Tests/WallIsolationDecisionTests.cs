using Revit.AgentHost.Core.Contracts;
using Revit.AgentHost.Core.Execution;
using Xunit;

namespace Revit.AgentHost.Core.Tests;

public sealed class WallIsolationDecisionTests
{
    [Theory]
    [InlineData(0)]
    [InlineData(2)]
    public void Target_count_outside_single_target_mvp_is_rejected(int approvedTargetCount)
    {
        WallIsolationDecision decision = WallIsolationDecision.Evaluate(
            EligibleEvidence() with { ApprovedTargetCount = approvedTargetCount });

        Assert.False(decision.IsEligible);
        Assert.Equal("TARGET_COUNT_OUTSIDE_MVP", decision.Code);
    }

    [Fact]
    public void Missing_target_is_rejected_as_resolution_failure()
    {
        WallIsolationDecision decision = WallIsolationDecision.Evaluate(
            EligibleEvidence() with { TargetResolved = false });

        Assert.False(decision.IsEligible);
        Assert.Equal("TARGET_RESOLUTION_FAILED", decision.Code);
    }

    [Fact]
    public void Wrong_native_kind_is_rejected_as_resolution_failure()
    {
        WallIsolationDecision decision = WallIsolationDecision.Evaluate(
            EligibleEvidence() with { NativeKindMatches = false });

        Assert.False(decision.IsEligible);
        Assert.Equal("TARGET_RESOLUTION_FAILED", decision.Code);
    }

    [Fact]
    public void Wrong_document_is_rejected_as_resolution_failure()
    {
        WallIsolationDecision decision = WallIsolationDecision.Evaluate(
            EligibleEvidence() with { DocumentMatches = false });

        Assert.False(decision.IsEligible);
        Assert.Equal("TARGET_RESOLUTION_FAILED", decision.Code);
    }

    [Fact]
    public void Non_basic_wall_is_rejected()
    {
        WallIsolationDecision decision = WallIsolationDecision.Evaluate(
            EligibleEvidence() with { IsBasicWall = false });

        Assert.False(decision.IsEligible);
        Assert.Equal("UNSUPPORTED_WALL_KIND", decision.Code);
    }

    [Fact]
    public void Shared_wall_type_is_rejected()
    {
        WallIsolationDecision decision = WallIsolationDecision.Evaluate(
            EligibleEvidence() with
            {
                SameTypeWallUniqueIds = new[] { "wall-001", "wall-002" },
            });

        Assert.False(decision.IsEligible);
        Assert.Equal("SHARED_WALL_TYPE_OUTSIDE_SCOPE", decision.Code);
    }

    [Fact]
    public void Insert_or_opening_is_rejected()
    {
        WallIsolationDecision decision = WallIsolationDecision.Evaluate(
            EligibleEvidence() with { InsertUniqueIds = new[] { "door-001" } });

        Assert.False(decision.IsEligible);
        Assert.Equal("WALL_INSERTS_OUTSIDE_MVP", decision.Code);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    public void Actual_join_participant_is_rejected(int end)
    {
        WallIsolationEvidence evidence = end == 0
            ? EligibleEvidence() with { JoinEnd0UniqueIds = new[] { "wall-joined" } }
            : EligibleEvidence() with { JoinEnd1UniqueIds = new[] { "wall-joined" } };

        WallIsolationDecision decision = WallIsolationDecision.Evaluate(evidence);

        Assert.False(decision.IsEligible);
        Assert.Equal("WALL_JOIN_OUTSIDE_MVP", decision.Code);
    }

    [Fact]
    public void Unproven_supported_dependency_is_rejected()
    {
        WallIsolationDecision decision = WallIsolationDecision.Evaluate(
            EligibleEvidence() with
            {
                UnsupportedDependencyUniqueIds = new[] { "dependent-001" },
            });

        Assert.False(decision.IsEligible);
        Assert.Equal("WALL_ASSOCIATIVITY_UNPROVEN", decision.Code);
    }

    [Fact]
    public void Exclusive_isolated_basic_wall_is_eligible()
    {
        WallIsolationDecision decision = WallIsolationDecision.Evaluate(EligibleEvidence());

        Assert.True(decision.IsEligible);
        Assert.Null(decision.Code);
    }

    private static WallIsolationEvidence EligibleEvidence()
    {
        return new WallIsolationEvidence(
            ApprovedTargetCount: 1,
            TargetResolved: true,
            NativeKindMatches: true,
            DocumentMatches: true,
            IsBasicWall: true,
            WallUniqueId: "wall-001",
            WallTypeUniqueId: "wall-type-001",
            SameTypeWallUniqueIds: new[] { "wall-001" },
            InsertUniqueIds: Array.Empty<string>(),
            JoinEnd0UniqueIds: Array.Empty<string>(),
            JoinEnd1UniqueIds: Array.Empty<string>(),
            UnsupportedDependencyUniqueIds: Array.Empty<string>());
    }
}
