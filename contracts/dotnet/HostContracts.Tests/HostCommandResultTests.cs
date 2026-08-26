using System.Text.Json;
using HostContracts;
using Xunit;

namespace HostContracts.Tests;

public class HostCommandResultTests
{
    private static T RoundTrip<T>(T value) =>
        JsonSerializer.Deserialize<T>(JsonSerializer.Serialize(value, ContractJson.Options), ContractJson.Options)!;

    [Fact]
    public void OkResult_RoundTrips()
    {
        var original = new HostCommandResult
        {
            CommandId = "cmd-001",
            Status = ResultStatus.OK,
            Payload = JsonDocument.Parse("""{"moved":1}""").RootElement.Clone(),
            RevisionAfter = 101,
            Verification = JsonDocument.Parse("""{"ok":true,"checked":1}""").RootElement.Clone(),
        };

        var restored = RoundTrip(original);

        Assert.Equal(original.CommandId, restored.CommandId);
        Assert.Equal(original.Status, restored.Status);
        Assert.Equal(101, restored.RevisionAfter);
        Assert.Equal(1, restored.Payload!.Value.GetProperty("moved").GetInt32());
        Assert.True(restored.Ok);
        Assert.Empty(original.Validate());
    }

    [Fact]
    public void ErrorResult_RoundTrips()
    {
        var original = new HostCommandResult
        {
            CommandId = "cmd-002",
            Status = ResultStatus.ERROR,
            Error = new ErrorShape
            {
                ErrorCode = "REVISION_CONFLICT",
                Category = ErrorCategory.CONSISTENCY,
                Retryable = RetryPolicy.AFTER_RECONSTRUCT,
            },
        };

        var restored = RoundTrip(original);

        Assert.Equal(ResultStatus.ERROR, restored.Status);
        Assert.NotNull(restored.Error);
        Assert.Equal("REVISION_CONFLICT", restored.Error!.ErrorCode);
        Assert.False(restored.Ok);
        Assert.Empty(original.Validate());
    }

    [Fact]
    public void ErrorStatus_WithoutError_IsInvalid()
    {
        var result = new HostCommandResult { CommandId = "c", Status = ResultStatus.ERROR };
        Assert.NotEmpty(result.Validate());
    }

    [Fact]
    public void Error_WithoutErrorStatus_IsInvalid()
    {
        var result = new HostCommandResult
        {
            CommandId = "c",
            Status = ResultStatus.OK,
            Error = new ErrorShape { ErrorCode = "X" },
        };
        Assert.NotEmpty(result.Validate());
    }

    [Fact]
    public void Replayed_IsOmitted_WhenFalse()
    {
        var result = new HostCommandResult { CommandId = "c", Status = ResultStatus.OK };
        var json = JsonSerializer.Serialize(result, ContractJson.Options);
        Assert.DoesNotContain("replayed", json);

        result.Replayed = true;
        json = JsonSerializer.Serialize(result, ContractJson.Options);
        Assert.Contains("\"replayed\":true", json);
    }
}
