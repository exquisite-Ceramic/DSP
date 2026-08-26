using System.Text.Json;
using System.Text.Json.Serialization;

namespace HostContracts;

/// <summary>Error categories (spec §19.2).</summary>
public enum ErrorCategory
{
    PROTOCOL,
    POLICY,
    SEMANTIC,
    EXECUTION,
    CONSISTENCY,
}

/// <summary>Retry policy enum (spec §19.2) — NOT a bool.</summary>
public enum RetryPolicy
{
    IMMEDIATE,
    AFTER_RECONSTRUCT,
    AFTER_APPROVAL,
    NEVER,
}

/// <summary>
/// Structured error object (spec §19.2). <c>error_code</c> is the stable
/// machine-readable code — program decisions MUST key on it, never on
/// <see cref="Message"/>.
/// </summary>
public sealed class ErrorShape
{
    [JsonPropertyName("error_code")]
    public string ErrorCode { get; set; } = string.Empty;

    [JsonPropertyName("category")]
    public ErrorCategory Category { get; set; } = ErrorCategory.EXECUTION;

    [JsonPropertyName("message")]
    public string Message { get; set; } = string.Empty;

    [JsonPropertyName("correlation_ids")]
    public List<string>? CorrelationIds { get; set; }

    [JsonPropertyName("retryable")]
    public RetryPolicy Retryable { get; set; } = RetryPolicy.NEVER;

    [JsonPropertyName("details")]
    public JsonElement? Details { get; set; }

    public IReadOnlyList<string> Validate()
    {
        var errors = new List<string>();
        if (string.IsNullOrWhiteSpace(ErrorCode))
        {
            errors.Add("error_code is required");
        }

        return errors;
    }
}
