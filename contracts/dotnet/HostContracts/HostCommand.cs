using System.Text.Json;
using System.Text.Json.Serialization;

namespace HostContracts;

/// <summary>Command modes (spec A.4). First phase: READ / VIEW / EXECUTE / VERIFY.</summary>
public enum HostCommandMode
{
    READ,
    VIEW,
    EXECUTE,
    VERIFY,
    PREVIEW,
    ROLLBACK,
    INTERACTION,
}

/// <summary>
/// Host command (spec A.4). Mutating modes (EXECUTE, ROLLBACK) MUST carry
/// an <see cref="IdempotencyKey"/> (spec §15.2).
/// </summary>
public sealed class HostCommand
{
    [JsonPropertyName("command_id")]
    public string CommandId { get; set; } = string.Empty;

    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    [JsonPropertyName("mode")]
    public HostCommandMode Mode { get; set; } = HostCommandMode.READ;

    [JsonPropertyName("operation")]
    public string Operation { get; set; } = string.Empty;

    [JsonPropertyName("target_native_refs")]
    public List<HostEntityRef> TargetNativeRefs { get; set; } = new();

    [JsonPropertyName("arguments")]
    public JsonElement? Arguments { get; set; }

    [JsonPropertyName("preconditions")]
    public JsonElement? Preconditions { get; set; }

    [JsonPropertyName("idempotency_key")]
    public string? IdempotencyKey { get; set; }

    [JsonPropertyName("deadline_at")]
    public string? DeadlineAt { get; set; }

    public IReadOnlyList<string> Validate()
    {
        var errors = new List<string>();
        if (string.IsNullOrWhiteSpace(CommandId))
        {
            errors.Add("command_id is required");
        }

        if (string.IsNullOrWhiteSpace(Operation))
        {
            errors.Add("operation is required");
        }

        if (Mode is HostCommandMode.EXECUTE or HostCommandMode.ROLLBACK
            && string.IsNullOrWhiteSpace(IdempotencyKey))
        {
            errors.Add($"mode {Mode} requires idempotency_key");
        }

        if (DeadlineAt is not null && !DeadlineRules.IsValidUtc(DeadlineAt))
        {
            errors.Add($"deadline_at must be absolute UTC: {DeadlineAt}");
        }

        return errors;
    }
}
