using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace HostContracts;

/// <summary>Contract version for negotiation (spec §23.1: major.minor).</summary>
public static class ContractVersion
{
    public const int Major = 1;
    public const int Minor = 0;
    public const string Current = "1.0";
}

/// <summary>
/// Shared JSON options for the contract wire format: snake_case property
/// names (explicit attributes), enums as strings, nulls omitted, unknown
/// fields ignored (spec §23.1).
/// </summary>
public static class ContractJson
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Converters = { new JsonStringEnumConverter() },
    };
}

public enum ResponseStatus
{
    OK,
    PENDING,
    ERROR,
}

public enum AsyncOperationType
{
    INTERACTION_SESSION,
    RECONSTRUCTION_JOB,
    EXECUTION_JOB,
    OTHER,
}

/// <summary>Deadline rules (AR-024): absolute UTC timestamps; child &lt;= parent.</summary>
public static class DeadlineRules
{
    public static bool IsValidUtc(string value) =>
        DateTimeOffset.TryParse(value, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out var dto)
        && dto.Offset == TimeSpan.Zero;

    public static bool IsWithinParent(string? child, string? parent)
    {
        if (child is null || parent is null)
        {
            return true;
        }

        if (!IsValidUtc(child) || !IsValidUtc(parent))
        {
            return false;
        }

        var childOffset = DateTimeOffset.Parse(child, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind);
        var parentOffset = DateTimeOffset.Parse(parent, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind);
        return childOffset <= parentOffset;
    }
}

/// <summary>Typed handle for PENDING work (spec A.8, §26.1 rule 6).</summary>
public sealed class AsyncOperationRef
{
    [JsonPropertyName("type")]
    public AsyncOperationType Type { get; set; } = AsyncOperationType.OTHER;

    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    public IReadOnlyList<string> Validate()
    {
        var errors = new List<string>();
        if (string.IsNullOrWhiteSpace(Id))
        {
            errors.Add("async ref id is required");
        }

        return errors;
    }
}

/// <summary>
/// Unified request envelope (spec A.8 / §26.1). <c>request_id</c> is unique
/// per transport attempt; <c>idempotency_key</c> stays stable across retries
/// of one logical side effect (AR-023).
/// </summary>
public sealed class RequestEnvelope
{
    private static readonly JsonElement EmptyObject = JsonDocument.Parse("{}").RootElement.Clone();

    [JsonPropertyName("request_id")]
    public string RequestId { get; set; } = Guid.NewGuid().ToString("D");

    [JsonPropertyName("task_id")]
    public string? TaskId { get; set; }

    [JsonPropertyName("project_id")]
    public string? ProjectId { get; set; }

    [JsonPropertyName("actor_context")]
    public JsonElement? ActorContext { get; set; }

    [JsonPropertyName("correlation_ids")]
    public List<string>? CorrelationIds { get; set; }

    [JsonPropertyName("deadline_at")]
    public string? DeadlineAt { get; set; }

    [JsonPropertyName("idempotency_key")]
    public string? IdempotencyKey { get; set; }

    [JsonPropertyName("payload")]
    public JsonElement Payload { get; set; } = EmptyObject;

    public IReadOnlyList<string> Validate()
    {
        var errors = new List<string>();
        if (string.IsNullOrWhiteSpace(RequestId))
        {
            errors.Add("request_id is required");
        }

        if (DeadlineAt is not null && !DeadlineRules.IsValidUtc(DeadlineAt))
        {
            errors.Add($"deadline_at must be absolute UTC: {DeadlineAt}");
        }

        return errors;
    }
}

/// <summary>
/// Unified response envelope (spec A.8 / §26.1). <c>status=PENDING</c> MUST
/// carry an <see cref="OperationRef"/>; <c>status=ERROR</c> MUST carry an
/// <see cref="Error"/>.
/// </summary>
public sealed class ResponseEnvelope
{
    [JsonPropertyName("request_id")]
    public string RequestId { get; set; } = string.Empty;

    [JsonPropertyName("status")]
    public ResponseStatus Status { get; set; } = ResponseStatus.OK;

    [JsonPropertyName("correlation_ids")]
    public List<string>? CorrelationIds { get; set; }

    [JsonPropertyName("snapshot_ref")]
    public string? SnapshotRef { get; set; }

    [JsonPropertyName("operation_ref")]
    public AsyncOperationRef? OperationRef { get; set; }

    [JsonPropertyName("result")]
    public JsonElement? Result { get; set; }

    [JsonPropertyName("error")]
    public ErrorShape? Error { get; set; }

    public IReadOnlyList<string> Validate()
    {
        var errors = new List<string>();
        if (string.IsNullOrWhiteSpace(RequestId))
        {
            errors.Add("request_id is required");
        }

        if (Status == ResponseStatus.PENDING && OperationRef is null)
        {
            errors.Add("status=PENDING requires operation_ref (AsyncOperationRef)");
        }

        if (Status == ResponseStatus.ERROR && Error is null)
        {
            errors.Add("status=ERROR requires error (ErrorShape)");
        }

        if (Error is not null && Status != ResponseStatus.ERROR)
        {
            errors.Add("error is only allowed when status=ERROR");
        }

        return errors;
    }
}
