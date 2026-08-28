using System.Collections.ObjectModel;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace DesignFactContracts;

[JsonConverter(typeof(JsonStringEnumConverter))]
public enum FactKind
{
    PROPERTY,
    CLASSIFICATION,
    PLACEMENT,
    BOUNDS,
    GEOMETRY,
    RELATIONSHIP,
    IDENTITY,
}

[JsonConverter(typeof(JsonStringEnumConverter))]
public enum ValueType
{
    NULL,
    STRING,
    INTEGER,
    NUMBER,
    BOOLEAN,
    OBJECT,
    ARRAY,
}

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed class NormalizedDesignFact
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        WriteIndented = false,
    };

    [JsonConstructor]
    public NormalizedDesignFact(
        string factId,
        string producer,
        DesignFactHostRef hostRef,
        long sourceRevision,
        NativeSubjectRef subjectNativeRef,
        FactKind factKind,
        string? predicate,
        JsonElement value,
        ValueType valueType,
        string? unit,
        string? geometryRef,
        string? sourceScheme,
        string? sourceCode,
        IReadOnlyList<string>? provenance)
    {
        FactId = ContractValidation.NonBlank(factId, nameof(factId));
        Producer = ContractValidation.NonBlank(producer, nameof(producer));
        HostRef = hostRef ?? throw new ArgumentNullException(nameof(hostRef));
        if (sourceRevision < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(sourceRevision), "source_revision must be non-negative");
        }
        SourceRevision = sourceRevision;
        SubjectNativeRef = subjectNativeRef ?? throw new ArgumentNullException(nameof(subjectNativeRef));
        if (!string.Equals(HostRef.DocumentId, SubjectNativeRef.DocumentId, StringComparison.Ordinal))
        {
            throw new ArgumentException("host_ref and subject_native_ref document_id must match");
        }

        FactKind = factKind;
        Predicate = ContractValidation.OptionalNonBlank(predicate, nameof(predicate));
        Value = value.Clone();
        ValueType = valueType;
        ContractValidation.ValidateValue(Value, ValueType);
        Unit = ContractValidation.OptionalNonBlank(unit, nameof(unit));
        GeometryRef = ContractValidation.OptionalNonBlank(geometryRef, nameof(geometryRef));
        SourceScheme = ContractValidation.OptionalNonBlank(sourceScheme, nameof(sourceScheme));
        SourceCode = ContractValidation.OptionalNonBlank(sourceCode, nameof(sourceCode));
        if ((SourceScheme is null) != (SourceCode is null))
        {
            throw new ArgumentException("source_scheme and source_code must be both present or both absent");
        }

        Provenance = new ReadOnlyCollection<string>(
            (provenance ?? Array.Empty<string>())
                .Select(item => ContractValidation.NonBlank(item, "provenance item"))
                .ToArray());
    }

    [JsonPropertyName("fact_id")]
    public string FactId { get; }

    [JsonPropertyName("producer")]
    public string Producer { get; }

    [JsonPropertyName("host_ref")]
    public DesignFactHostRef HostRef { get; }

    [JsonPropertyName("source_revision")]
    public long SourceRevision { get; }

    [JsonPropertyName("subject_native_ref")]
    public NativeSubjectRef SubjectNativeRef { get; }

    [JsonPropertyName("fact_kind")]
    public FactKind FactKind { get; }

    [JsonPropertyName("predicate")]
    public string? Predicate { get; }

    [JsonPropertyName("value")]
    public JsonElement Value { get; }

    [JsonPropertyName("value_type")]
    public ValueType ValueType { get; }

    [JsonPropertyName("unit")]
    public string? Unit { get; }

    [JsonPropertyName("geometry_ref")]
    public string? GeometryRef { get; }

    [JsonPropertyName("source_scheme")]
    public string? SourceScheme { get; }

    [JsonPropertyName("source_code")]
    public string? SourceCode { get; }

    [JsonPropertyName("provenance")]
    public IReadOnlyList<string> Provenance { get; }

    public static NormalizedDesignFact FromJson(string json)
    {
        using var document = JsonDocument.Parse(json);
        ContractValidation.ValidateFactWireShape(document.RootElement);
        return JsonSerializer.Deserialize<NormalizedDesignFact>(json, SerializerOptions)
            ?? throw new JsonException("NormalizedDesignFact payload deserialized to null");
    }

    public string ToJson() => JsonSerializer.Serialize(this, SerializerOptions);
}

internal static class ContractValidation
{
    private static readonly HashSet<string> FactFields = new(StringComparer.Ordinal)
    {
        "fact_id", "producer", "host_ref", "source_revision", "subject_native_ref",
        "fact_kind", "predicate", "value", "value_type", "unit", "geometry_ref",
        "source_scheme", "source_code", "provenance",
    };

    internal static string NonBlank(string? value, string fieldName)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException($"{fieldName} must be a non-empty string", fieldName);
        }
        return value;
    }

    internal static string? OptionalNonBlank(string? value, string fieldName)
    {
        return value is null ? null : NonBlank(value, fieldName);
    }

    internal static void ValidateFactWireShape(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            throw new JsonException("NormalizedDesignFact must be a JSON object");
        }

        var present = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in root.EnumerateObject())
        {
            if (!FactFields.Contains(property.Name))
            {
                throw new JsonException($"Unknown NormalizedDesignFact field: {property.Name}");
            }
            present.Add(property.Name);
        }

        var missing = FactFields.Where(field => !present.Contains(field)).ToArray();
        if (missing.Length > 0)
        {
            throw new JsonException($"Missing NormalizedDesignFact fields: {string.Join(", ", missing)}");
        }

        ValidateStringEnum<FactKind>(root.GetProperty("fact_kind"), "fact_kind");
        ValidateStringEnum<ValueType>(root.GetProperty("value_type"), "value_type");
    }

    internal static void ValidateValue(JsonElement value, ValueType valueType)
    {
        var valid = valueType switch
        {
            ValueType.NULL => value.ValueKind == JsonValueKind.Null,
            ValueType.STRING => value.ValueKind == JsonValueKind.String,
            ValueType.INTEGER => value.ValueKind == JsonValueKind.Number && IsInteger(value),
            ValueType.NUMBER => value.ValueKind == JsonValueKind.Number,
            ValueType.BOOLEAN => value.ValueKind is JsonValueKind.True or JsonValueKind.False,
            ValueType.OBJECT => value.ValueKind == JsonValueKind.Object,
            ValueType.ARRAY => value.ValueKind == JsonValueKind.Array,
            _ => false,
        };

        if (!valid)
        {
            throw new ArgumentException($"value is incompatible with value_type {valueType}");
        }
    }

    private static void ValidateStringEnum<TEnum>(JsonElement value, string fieldName)
        where TEnum : struct, Enum
    {
        if (value.ValueKind != JsonValueKind.String)
        {
            throw new JsonException($"{fieldName} must be a string enum value");
        }

        var text = value.GetString();
        if (text is null || !Enum.GetNames<TEnum>().Contains(text, StringComparer.Ordinal))
        {
            throw new JsonException($"invalid {fieldName}: {text}");
        }
    }

    private static bool IsInteger(JsonElement value)
    {
        if (value.TryGetInt64(out _))
        {
            return true;
        }
        return value.TryGetDecimal(out var number) && decimal.Truncate(number) == number;
    }
}
