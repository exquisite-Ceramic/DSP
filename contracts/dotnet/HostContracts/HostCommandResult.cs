using System.Text.Json;
using System.Text.Json.Serialization;

namespace HostContracts;

public enum ResultStatus
{
    OK,
    PENDING,
    ERROR,
}

/// <summary>Outcome of a host command. <c>status=ERROR</c> MUST carry an <see cref="Error"/>.</summary>
public sealed class HostCommandResult
{
    [JsonPropertyName("command_id")]
    public string CommandId { get; set; } = string.Empty;

    [JsonPropertyName("status")]
    public ResultStatus Status { get; set; } = ResultStatus.OK;

    [JsonPropertyName("payload")]
    public JsonElement? Payload { get; set; }

    [JsonPropertyName("error")]
    public ErrorShape? Error { get; set; }

    [JsonPropertyName("revision_after")]
    public int? RevisionAfter { get; set; }

    [JsonPropertyName("verification")]
    public JsonElement? Verification { get; set; }

    [JsonPropertyName("replayed")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)]
    public bool Replayed { get; set; }

    [JsonIgnore]
    public bool Ok => Status == ResultStatus.OK;

    public IReadOnlyList<string> Validate()
    {
        var errors = new List<string>();
        if (string.IsNullOrWhiteSpace(CommandId))
        {
            errors.Add("command_id is required");
        }

        if (Status == ResultStatus.ERROR && Error is null)
        {
            errors.Add("status=ERROR requires error (ErrorShape)");
        }

        if (Error is not null && Status != ResultStatus.ERROR)
        {
            errors.Add("error is only allowed when status=ERROR");
        }

        return errors;
    }
}
