using System.Text.Json;
using HostContracts;
using Xunit;

namespace HostContracts.Tests;

public class SerializationTests
{
    private static readonly object[] AllDtos =
    {
        new RequestEnvelope
        {
            RequestId = "req-001",
            TaskId = "task-001",
            IdempotencyKey = "k-1",
            Payload = JsonDocument.Parse("""{"command_id":"cmd-001"}""").RootElement.Clone(),
        },
        new HostCommand
        {
            CommandId = "cmd-001",
            DocumentId = "drawing-001",
            Mode = HostCommandMode.EXECUTE,
            Operation = "move.v1",
            TargetNativeRefs = { new HostEntityRef { DocumentId = "drawing-001", NativeId = "2AF" } },
            Arguments = JsonDocument.Parse("""{"displacement":{"x":500,"y":0,"z":0}}""").RootElement.Clone(),
            IdempotencyKey = "k-1",
        },
        new HostCommandResult { CommandId = "cmd-001", Status = ResultStatus.OK, RevisionAfter = 101 },
        new HostCommandResult
        {
            CommandId = "cmd-002",
            Status = ResultStatus.ERROR,
            Error = new ErrorShape { ErrorCode = "REVISION_CONFLICT", Category = ErrorCategory.CONSISTENCY },
        },
        new HostDelta
        {
            RevisionBefore = 100,
            RevisionAfter = 101,
            Modified = { new HostEntityRef { DocumentId = "drawing-001", NativeId = "2AF" } },
        },
        new ErrorShape { ErrorCode = "REVISION_CONFLICT", Category = ErrorCategory.CONSISTENCY, Retryable = RetryPolicy.AFTER_RECONSTRUCT },
    };

    public static IEnumerable<object[]> Dtos => AllDtos.Select(d => new[] { d });

    [Theory]
    [MemberData(nameof(Dtos))]
    public void AllDtos_RoundTrip_ThroughJson(object value)
    {
        var json = JsonSerializer.Serialize(value, ContractJson.Options);
        var restored = JsonSerializer.Deserialize(json, value.GetType(), ContractJson.Options);
        Assert.NotNull(restored);
        Assert.Equal(json, JsonSerializer.Serialize(restored, ContractJson.Options));
    }

    [Fact]
    public void EnvelopeCommandChain_SerializesAndDeserializes()
    {
        var command = new HostCommand
        {
            CommandId = "cmd-001",
            DocumentId = "drawing-001",
            Mode = HostCommandMode.READ,
            Operation = "context.current_selection",
        };
        var envelope = new RequestEnvelope
        {
            RequestId = "req-001",
            IdempotencyKey = null, // READ: no idempotency needed
            Payload = JsonSerializer.SerializeToElement(command, ContractJson.Options),
        };

        var json = JsonSerializer.Serialize(envelope, ContractJson.Options);
        var restoredEnvelope = JsonSerializer.Deserialize<RequestEnvelope>(json, ContractJson.Options)!;
        var restoredCommand = JsonSerializer.Deserialize<HostCommand>(restoredEnvelope.Payload.GetRawText(), ContractJson.Options)!;

        Assert.Equal("req-001", restoredEnvelope.RequestId);
        Assert.Equal(HostCommandMode.READ, restoredCommand.Mode);
        Assert.Equal("context.current_selection", restoredCommand.Operation);
    }

    [Fact]
    public void OptionalFields_AreOmitted_WhenUnset()
    {
        var cmd = new HostCommand { CommandId = "c", Mode = HostCommandMode.READ, Operation = "context.current_document" };
        var json = JsonSerializer.Serialize(cmd, ContractJson.Options);
        Assert.DoesNotContain("idempotency_key", json);
        Assert.DoesNotContain("deadline_at", json);
        Assert.DoesNotContain("arguments", json);
        Assert.DoesNotContain("preconditions", json);
    }

    [Fact]
    public void Error_RoundTrips_InsideResult()
    {
        var result = new HostCommandResult
        {
            CommandId = "c",
            Status = ResultStatus.ERROR,
            Error = new ErrorShape
            {
                ErrorCode = "REVISION_CONFLICT",
                Category = ErrorCategory.CONSISTENCY,
                Retryable = RetryPolicy.AFTER_RECONSTRUCT,
            },
        };
        var restored = JsonSerializer.Deserialize<HostCommandResult>(
            JsonSerializer.Serialize(result, ContractJson.Options), ContractJson.Options)!;
        Assert.False(restored.Ok);
        Assert.Equal("REVISION_CONFLICT", restored.Error!.ErrorCode);
    }
}
