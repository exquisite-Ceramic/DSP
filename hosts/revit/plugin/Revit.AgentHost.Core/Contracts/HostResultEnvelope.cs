using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace Revit.AgentHost.Core.Contracts;

public sealed record HostResultEnvelope(
    [property: JsonPropertyName("command_id")] string CommandId,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("payload"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] JsonObject? Payload,
    [property: JsonPropertyName("error"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] JsonObject? Error,
    [property: JsonPropertyName("revision_after"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? RevisionAfter,
    [property: JsonPropertyName("verification"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] JsonObject? Verification,
    [property: JsonPropertyName("replayed")] bool Replayed);
