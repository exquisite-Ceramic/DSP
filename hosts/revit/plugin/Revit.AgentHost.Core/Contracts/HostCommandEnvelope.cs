using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace Revit.AgentHost.Core.Contracts;

public sealed record HostNativeRef(
    [property: JsonPropertyName("document_id")] string DocumentId,
    [property: JsonPropertyName("native_id")] string NativeId,
    [property: JsonPropertyName("native_type")] string NativeType);

public sealed record HostCommandEnvelope(
    [property: JsonPropertyName("command_id")] string CommandId,
    [property: JsonPropertyName("document_id")] string DocumentId,
    [property: JsonPropertyName("mode")] string Mode,
    [property: JsonPropertyName("operation")] string Operation,
    [property: JsonPropertyName("target_native_refs")] IReadOnlyList<HostNativeRef> TargetNativeRefs,
    [property: JsonPropertyName("arguments")] JsonObject Arguments,
    [property: JsonPropertyName("preconditions")] IReadOnlyList<JsonObject> Preconditions,
    [property: JsonPropertyName("idempotency_key")] string? IdempotencyKey,
    [property: JsonPropertyName("deadline_at")] string? DeadlineAt);
