using System.Text.Json.Nodes;
using Revit.AgentHost.Core.Contracts;
using Revit.AgentHost.Core.Execution;
using Xunit;

namespace Revit.AgentHost.Core.Tests;

public sealed class IdempotencyStoreTests
{
    [Fact]
    public void First_key_and_fingerprint_are_absent()
    {
        IdempotencyStore store = new();

        bool found = store.TryGet("IDEMP-REVIT-001", "fingerprint-a", out HostResultEnvelope result);

        Assert.False(found);
        Assert.Null(result);
    }

    [Fact]
    public void Same_key_and_fingerprint_replay_returns_exact_stored_result()
    {
        IdempotencyStore store = new();
        HostResultEnvelope expected = SuccessResult();
        store.Store("IDEMP-REVIT-001", "fingerprint-a", expected);

        bool found = store.TryGet("IDEMP-REVIT-001", "fingerprint-a", out HostResultEnvelope actual);

        Assert.True(found);
        Assert.Same(expected, actual);
    }

    [Fact]
    public void Same_key_with_different_fingerprint_fails_closed_with_stable_code()
    {
        IdempotencyStore store = new();
        store.Store("IDEMP-REVIT-001", "fingerprint-a", SuccessResult());

        IdempotencyConflictException error = Assert.Throws<IdempotencyConflictException>(
            () => store.TryGet("IDEMP-REVIT-001", "fingerprint-b", out _));

        Assert.Equal("IDEMPOTENCY_KEY_CONFLICT", error.Code);
    }

    [Fact]
    public void Replay_does_not_invoke_execution_delegate_a_second_time()
    {
        IdempotencyStore store = new();
        int executions = 0;

        HostResultEnvelope ExecuteOnce()
        {
            const string key = "IDEMP-REVIT-001";
            const string fingerprint = "fingerprint-a";
            if (store.TryGet(key, fingerprint, out HostResultEnvelope replayed))
            {
                return replayed;
            }

            executions += 1;
            HostResultEnvelope result = SuccessResult();
            store.Store(key, fingerprint, result);
            return result;
        }

        HostResultEnvelope first = ExecuteOnce();
        HostResultEnvelope second = ExecuteOnce();

        Assert.Same(first, second);
        Assert.Equal(1, executions);
    }

    private static HostResultEnvelope SuccessResult()
    {
        return new HostResultEnvelope(
            CommandId: "CMD-REVIT-001",
            Status: "OK",
            Payload: JsonNode.Parse("{\"native_id\":\"wall-unique-id\"}")!.AsObject(),
            Error: null,
            RevisionAfter: 11,
            Verification: null,
            Replayed: false);
    }
}
