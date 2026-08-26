using System.Text.Json.Serialization;

namespace HostContracts;

/// <summary>
/// Host-local entity reference (spec §12.2): DocumentId + NativeId.
/// ObjectId and other Autodesk native types MUST NOT cross the contract
/// boundary (AR-001) — enforced by NativeTypeLeakTests.
/// </summary>
public sealed class HostEntityRef
{
    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    [JsonPropertyName("native_id")]
    public string NativeId { get; set; } = string.Empty;

    [JsonPropertyName("native_type")]
    public string? NativeType { get; set; }

    public IReadOnlyList<string> Validate()
    {
        var errors = new List<string>();
        if (string.IsNullOrWhiteSpace(DocumentId))
        {
            errors.Add("document_id is required");
        }

        if (string.IsNullOrWhiteSpace(NativeId))
        {
            errors.Add("native_id is required");
        }

        return errors;
    }
}
