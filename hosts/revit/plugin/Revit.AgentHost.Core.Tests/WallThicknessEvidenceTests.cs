using System.Text.Json.Nodes;
using Revit.AgentHost.Core.Contracts;
using Revit.AgentHost.Core.Execution;
using Xunit;

namespace Revit.AgentHost.Core.Tests;

public sealed class WallThicknessEvidenceTests
{
    [Fact]
    public void Valid_success_evidence_is_created()
    {
        WallThicknessEvidence evidence = CreateValidEvidence();

        Assert.Equal("wall-unique-id", evidence.WallUniqueId);
        Assert.Equal("wall-type-unique-id", evidence.WallTypeUniqueId);
        Assert.Equal(1, evidence.TransactionAttemptCount);
        Assert.Equal(11, evidence.RevisionAfter);
    }

    [Theory]
    [InlineData("", "wall-type-unique-id")]
    [InlineData("wall-unique-id", "")]
    public void Empty_native_identity_is_rejected(string wallUniqueId, string wallTypeUniqueId)
    {
        Assert.Throws<ArgumentException>(() => CreateValidEvidence(
            wallUniqueId: wallUniqueId,
            wallTypeUniqueId: wallTypeUniqueId));
    }

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(0.0)]
    [InlineData(-1.0)]
    public void Nonfinite_or_nonpositive_post_width_is_rejected(double widthAfter)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => CreateValidEvidence(widthAfterInternal: widthAfter));
    }

    [Fact]
    public void Post_width_must_match_requested_width_within_tolerance()
    {
        Assert.Throws<InvalidOperationException>(() => CreateValidEvidence(
            requestedWidthInternal: 100.0,
            widthAfterInternal: 100.5,
            toleranceInternal: 0.1));
    }

    [Theory]
    [InlineData(10, 10)]
    [InlineData(10, 9)]
    public void Revision_after_must_advance(long revisionBefore, long revisionAfter)
    {
        Assert.Throws<InvalidOperationException>(() => CreateValidEvidence(
            revisionBefore: revisionBefore,
            revisionAfter: revisionAfter));
    }

    [Theory]
    [InlineData(false, true, true)]
    [InlineData(true, false, true)]
    [InlineData(true, true, false)]
    public void All_target_invariants_must_be_proven(
        bool identityInvariantProven,
        bool locationInvariantProven,
        bool relationshipInvariantProven)
    {
        Assert.Throws<InvalidOperationException>(() => CreateValidEvidence(
            identityInvariantProven: identityInvariantProven,
            locationInvariantProven: locationInvariantProven,
            relationshipInvariantProven: relationshipInvariantProven));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(2)]
    public void Successful_evidence_requires_exactly_one_transaction_attempt(int transactionAttemptCount)
    {
        Assert.Throws<InvalidOperationException>(() => CreateValidEvidence(
            transactionAttemptCount: transactionAttemptCount));
    }

    [Fact]
    public void Idempotent_replay_returns_stored_success_without_constructing_second_mutation_request()
    {
        IdempotencyStore store = new();
        int mutationRequests = 0;
        const string key = "IDEMP-REVIT-001";
        const string fingerprint = "fingerprint-a";

        HostResultEnvelope Execute()
        {
            if (store.TryGet(key, fingerprint, out HostResultEnvelope stored))
            {
                return stored with { Replayed = true };
            }

            mutationRequests += 1;
            WallThicknessEvidence evidence = CreateValidEvidence();
            HostResultEnvelope result = new(
                CommandId: "CMD-REVIT-001",
                Status: "OK",
                Payload: new JsonObject
                {
                    ["wall_unique_id"] = evidence.WallUniqueId,
                },
                Error: null,
                RevisionAfter: checked((int)evidence.RevisionAfter),
                Verification: null,
                Replayed: false);
            store.Store(key, fingerprint, result);
            return result;
        }

        HostResultEnvelope first = Execute();
        HostResultEnvelope replay = Execute();

        Assert.False(first.Replayed);
        Assert.True(replay.Replayed);
        Assert.Equal(1, mutationRequests);
        Assert.Equal(first.CommandId, replay.CommandId);
        Assert.Equal(first.RevisionAfter, replay.RevisionAfter);
    }

    private static WallThicknessEvidence CreateValidEvidence(
        string wallUniqueId = "wall-unique-id",
        string wallTypeUniqueId = "wall-type-unique-id",
        double requestedWidthInternal = 100.0,
        double widthAfterInternal = 100.0,
        double toleranceInternal = 0.001,
        long revisionBefore = 10,
        long revisionAfter = 11,
        bool identityInvariantProven = true,
        bool locationInvariantProven = true,
        bool relationshipInvariantProven = true,
        int transactionAttemptCount = 1)
    {
        return WallThicknessEvidence.Create(
            wallUniqueId,
            wallTypeUniqueId,
            editableLayerIndex: 1,
            widthBeforeInternal: 80.0,
            requestedWidthInternal,
            widthAfterInternal,
            toleranceInternal,
            revisionBefore,
            revisionAfter,
            identityInvariantProven,
            locationInvariantProven,
            relationshipInvariantProven,
            transactionAttemptCount,
            documentChangeObserved: true);
    }
}
