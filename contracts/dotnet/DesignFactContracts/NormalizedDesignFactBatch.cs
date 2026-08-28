using System.Collections.ObjectModel;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace DesignFactContracts;

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed class NormalizedDesignFactBatch
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        WriteIndented = false,
    };

    [JsonConstructor]
    public NormalizedDesignFactBatch(IReadOnlyList<NormalizedDesignFact>? facts)
    {
        Facts = new ReadOnlyCollection<NormalizedDesignFact>((facts ?? Array.Empty<NormalizedDesignFact>()).ToArray());
    }

    [JsonPropertyName("facts")]
    public IReadOnlyList<NormalizedDesignFact> Facts { get; }

    public static NormalizedDesignFactBatch FromJson(string json)
    {
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object)
        {
            throw new JsonException("NormalizedDesignFactBatch must be a JSON object");
        }
        var properties = root.EnumerateObject().Select(property => property.Name).ToArray();
        if (properties.Length != 1 || properties[0] != "facts")
        {
            throw new JsonException("NormalizedDesignFactBatch must contain only the facts field");
        }

        var factsElement = root.GetProperty("facts");
        if (factsElement.ValueKind != JsonValueKind.Array)
        {
            throw new JsonException("facts must be a JSON array");
        }

        var facts = factsElement
            .EnumerateArray()
            .Select(item => NormalizedDesignFact.FromJson(item.GetRawText()))
            .ToArray();
        return new NormalizedDesignFactBatch(facts);
    }

    public string ToJson() => JsonSerializer.Serialize(this, SerializerOptions);
}
