using System.Text.Json;
using HostContracts;
using Xunit;

namespace HostContracts.Tests;

public class HostErrorTests
{
    private static T RoundTrip<T>(T value) =>
        JsonSerializer.Deserialize<T>(JsonSerializer.Serialize(value, ContractJson.Options), ContractJson.Options)!;

    [Fact]
    public void ErrorShape_RoundTrips_AllFields()
    {
        var original = new ErrorShape
        {
            ErrorCode = "REVISION_CONFLICT",
            Category = ErrorCategory.CONSISTENCY,
            Message = "Document has changed since the planning snapshot",
            CorrelationIds = new List<string> { "task-001", "cmd-002" },
            Retryable = RetryPolicy.AFTER_RECONSTRUCT,
            Details = JsonDocument.Parse("""[{"expected_revision":100,"actual_revision":101}]""").RootElement.Clone(),
        };

        var restored = RoundTrip(original);

        Assert.Equal(original.ErrorCode, restored.ErrorCode);
        Assert.Equal(original.Category, restored.Category);
        Assert.Equal(original.Message, restored.Message);
        Assert.Equal(original.CorrelationIds, restored.CorrelationIds);
        Assert.Equal(original.Retryable, restored.Retryable);
        Assert.Equal(original.Details!.Value.GetRawText(), restored.Details!.Value.GetRawText());
        Assert.Empty(original.Validate());
    }

    [Fact]
    public void ErrorCode_IsStable_WhileMessage_MayChange()
    {
        var a = new ErrorShape { ErrorCode = "REVISION_CONFLICT", Message = "old wording" };
        var b = new ErrorShape { ErrorCode = "REVISION_CONFLICT", Message = "new wording" };

        // Program decisions MUST key on error_code, never on message.
        Assert.Equal(a.ErrorCode, b.ErrorCode);
        Assert.NotEqual(a.Message, b.Message);
        Assert.Equal("REVISION_CONFLICT", a.ErrorCode);
    }

    [Fact]
    public void Category_AndRetryable_SerializeAsStrings()
    {
        var error = new ErrorShape
        {
            ErrorCode = "X",
            Category = ErrorCategory.CONSISTENCY,
            Retryable = RetryPolicy.IMMEDIATE,
        };
        var json = JsonSerializer.Serialize(error, ContractJson.Options);
        Assert.Contains("\"category\":\"CONSISTENCY\"", json);
        Assert.Contains("\"retryable\":\"IMMEDIATE\"", json);
    }

    [Fact]
    public void MissingErrorCode_IsInvalid()
    {
        Assert.NotEmpty(new ErrorShape { ErrorCode = "" }.Validate());
    }

    [Fact]
    public void UnknownField_IsIgnored()
    {
        const string json = """{"error_code":"X","message":"m","native_stack":"not part of contract"}""";
        var error = JsonSerializer.Deserialize<ErrorShape>(json, ContractJson.Options)!;
        Assert.Equal("X", error.ErrorCode);
        var reserialized = JsonSerializer.Serialize(error, ContractJson.Options);
        Assert.DoesNotContain("native_stack", reserialized);
    }
}
