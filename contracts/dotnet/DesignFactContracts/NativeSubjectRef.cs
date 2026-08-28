using System.Text.Json.Serialization;

namespace DesignFactContracts;

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed class NativeSubjectRef
{
    [JsonConstructor]
    public NativeSubjectRef(string documentId, string nativeId, string? nativeKind = null)
    {
        DocumentId = ContractValidation.NonBlank(documentId, nameof(documentId));
        NativeId = ContractValidation.NonBlank(nativeId, nameof(nativeId));
        NativeKind = ContractValidation.OptionalNonBlank(nativeKind, nameof(nativeKind));
    }

    [JsonPropertyName("document_id")]
    public string DocumentId { get; }

    [JsonPropertyName("native_id")]
    public string NativeId { get; }

    [JsonPropertyName("native_kind")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? NativeKind { get; }
}
