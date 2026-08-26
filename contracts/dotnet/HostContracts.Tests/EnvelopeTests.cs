using System.Text.Json;
using HostContracts;
using Xunit;

namespace HostContracts.Tests;

public class EnvelopeTests
{
    private static string Json<T>(T value) => JsonSerializer.Serialize(value, ContractJson.Options);

    private static T RoundTrip<T>(T value) =>
        JsonSerializer.Deserialize<T>(Json(value), ContractJson.Options)!;

    [Fact] // TC-C01
    public void RequestEnvelope_RoundTrips_AllFields()
    {
        var original = new RequestEnvelope
        {
            RequestId = "req-001",
            TaskId = "task-001",
            ProjectId = "project-001",
            ActorContext = JsonDocument.Parse("""{"user":"alice","role":"designer"}""").RootElement.Clone(),
            CorrelationIds = new List<string> { "corr-1", "corr-2" },
            DeadlineAt = "2026-08-26T14:00:00Z",
            IdempotencyKey = "move-abc",
            Payload = JsonDocument.Parse("""{"command_id":"cmd-001","mode":"EXECUTE"}""").RootElement.Clone(),
        };

        var restored = RoundTrip(original);

        Assert.Equal(original.RequestId, restored.RequestId);
        Assert.Equal(original.TaskId, restored.TaskId);
        Assert.Equal(original.ProjectId, restored.ProjectId);
        Assert.Equal(original.CorrelationIds, restored.CorrelationIds);
        Assert.Equal(original.DeadlineAt, restored.DeadlineAt);
        Assert.Equal(original.IdempotencyKey, restored.IdempotencyKey);
        Assert.Equal("alice", restored.ActorContext?.GetProperty("user").GetString());
        Assert.Equal("EXECUTE", restored.Payload.GetProperty("mode").GetString());
        Assert.Empty(original.Validate());
    }

    [Fact]
    public void RequestEnvelope_MissingRequestId_IsInvalid()
    {
        var envelope = new RequestEnvelope { RequestId = "" };
        Assert.Contains(envelope.Validate(), e => e.Contains("request_id"));
    }

    [Fact]
    public void DeadlineAt_RoundTrips_UtcPrecision()
    {
        const string deadline = "2026-08-26T14:00:00Z";
        var restored = RoundTrip(new RequestEnvelope { DeadlineAt = deadline });
        Assert.Equal(deadline, restored.DeadlineAt);
        Assert.Empty(restored.Validate());
    }

    [Fact]
    public void DeadlineAt_NonUtc_IsInvalid()
    {
        var envelope = new RequestEnvelope { DeadlineAt = "2026-08-26T14:00:00+02:00" };
        Assert.NotEmpty(envelope.Validate());

        var naive = new RequestEnvelope { DeadlineAt = "2026-08-26T14:00:00" };
        Assert.NotEmpty(naive.Validate());
    }

    [Fact] // TC-C05
    public void RequestId_MayChange_WhileIdempotencyKey_StaysStable()
    {
        var attempt1 = new RequestEnvelope { RequestId = "req-001", IdempotencyKey = "move-abc" };
        var attempt2 = new RequestEnvelope { RequestId = "req-002", IdempotencyKey = "move-abc" };

        Assert.Empty(attempt1.Validate());
        Assert.Empty(attempt2.Validate());
        Assert.NotEqual(attempt1.RequestId, attempt2.RequestId);
        Assert.Equal(attempt1.IdempotencyKey, attempt2.IdempotencyKey);
    }

    [Fact] // AR-024 helper
    public void ChildDeadline_MustNotExceed_ParentDeadline()
    {
        Assert.True(DeadlineRules.IsWithinParent("2026-08-26T14:00:00Z", "2026-08-26T15:00:00Z"));
        Assert.False(DeadlineRules.IsWithinParent("2026-08-26T16:00:00Z", "2026-08-26T15:00:00Z"));
        Assert.True(DeadlineRules.IsWithinParent(null, "2026-08-26T15:00:00Z"));
        Assert.True(DeadlineRules.IsWithinParent("2026-08-26T14:00:00Z", null));
    }

    [Fact]
    public void ResponseEnvelope_Pending_RequiresOperationRef()
    {
        var pending = new ResponseEnvelope { RequestId = "req-1", Status = ResponseStatus.PENDING };
        Assert.Contains(pending.Validate(), e => e.Contains("operation_ref"));

        var pendingWithRef = new ResponseEnvelope
        {
            RequestId = "req-1",
            Status = ResponseStatus.PENDING,
            OperationRef = new AsyncOperationRef { Type = AsyncOperationType.EXECUTION_JOB, Id = "job-9" },
        };
        Assert.Empty(pendingWithRef.Validate());

        var ok = new ResponseEnvelope { RequestId = "req-1", Status = ResponseStatus.OK };
        Assert.Empty(ok.Validate());
    }

    [Fact]
    public void ResponseEnvelope_Error_RequiresErrorShape()
    {
        var error = new ResponseEnvelope { RequestId = "req-1", Status = ResponseStatus.ERROR };
        Assert.NotEmpty(error.Validate());
    }

    [Fact]
    public void AsyncOperationRef_RoundTrips()
    {
        var original = new AsyncOperationRef { Type = AsyncOperationType.EXECUTION_JOB, Id = "job-9" };
        var restored = RoundTrip(original);
        Assert.Equal(original.Type, restored.Type);
        Assert.Equal(original.Id, restored.Id);
        Assert.Empty(original.Validate());
    }
}
