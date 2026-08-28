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
        if (root.GetProperty("facts").ValueKind != JsonValueKind.Array)
        {
            throw new JsonException("facts must be a JSON array");
        }

        return JsonSerializer.Deserialize<NormalizedDesignFactBatch>(json, SerializerOptions)
            ?? throw new JsonException("NormalizedDesignFactBatch payload deserialized to null");
    }

    public string ToJson() => JsonSerializer.Serialize(this, SerializerOptions);
}
