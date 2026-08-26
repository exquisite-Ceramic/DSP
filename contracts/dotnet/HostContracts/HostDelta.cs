using System.Text.Json.Serialization;

namespace HostContracts;

/// <summary>
/// Lightweight change stream (spec §12.3 / §26.8): revisions bracket the
/// change; entity refs are grouped by change kind.
/// </summary>
public sealed class HostDelta
{
    [JsonPropertyName("revision_before")]
    public int RevisionBefore { get; set; }

    [JsonPropertyName("revision_after")]
    public int RevisionAfter { get; set; }

    [JsonPropertyName("added")]
    public List<HostEntityRef> Added { get; set; } = new();

    [JsonPropertyName("modified")]
    public List<HostEntityRef> Modified { get; set; } = new();

    [JsonPropertyName("erased")]
    public List<HostEntityRef> Erased { get; set; } = new();

    public IReadOnlyList<string> Validate()
    {
        var errors = new List<string>();
        if (RevisionAfter < RevisionBefore)
        {
            errors.Add("revision_after must be >= revision_before");
        }

        var addedKeys = Added.Select(r => (r.DocumentId, r.NativeId)).ToHashSet();
        var erasedKeys = Erased.Select(r => (r.DocumentId, r.NativeId)).ToHashSet();
        var overlap = addedKeys.Intersect(erasedKeys).OrderBy(k => k.NativeId).ToList();
        if (overlap.Count > 0)
        {
            errors.Add($"entity in both added and erased: {string.Join(", ", overlap.Select(k => $"{k.DocumentId}/{k.NativeId}"))}");
        }

        return errors;
    }
}
