using Revit.AgentHost.Core.Execution;
using Xunit;

namespace Revit.AgentHost.Core.Tests;

public sealed class RevisionGateTests
{
    [Theory]
    [InlineData(0L)]
    [InlineData(1L)]
    [InlineData(42L)]
    public void Equal_revision_passes(long revision)
    {
        RevisionGate.RequireExpected(revision, revision);
    }

    [Fact]
    public void Mismatched_revision_fails_with_stable_code()
    {
        RevisionConflictException error = Assert.Throws<RevisionConflictException>(
            () => RevisionGate.RequireExpected(currentRevision: 11, expectedRevision: 10));

        Assert.Equal("REVISION_CONFLICT", error.Code);
        Assert.Equal(11, error.CurrentRevision);
        Assert.Equal(10, error.ExpectedRevision);
    }

    [Fact]
    public void Negative_current_revision_is_invalid()
    {
        Assert.Throws<ArgumentOutOfRangeException>(
            () => RevisionGate.RequireExpected(currentRevision: -1, expectedRevision: 0));
    }

    [Fact]
    public void Negative_expected_revision_is_invalid()
    {
        Assert.Throws<ArgumentOutOfRangeException>(
            () => RevisionGate.RequireExpected(currentRevision: 0, expectedRevision: -1));
    }
}
