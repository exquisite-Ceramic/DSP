using System.Text.Json;
using System.Text.Json.Nodes;
using DesignFactContracts;
using Xunit;

namespace DesignFactContracts.Tests;

public sealed class NormalizedDesignFactTests
{
    private static string VectorPath(string name) =>
        Path.Combine(AppContext.BaseDirectory, "test_vectors", "normalized_design_fact", name);

    private static string ReadVector(string name) => File.ReadAllText(VectorPath(name));

    [Theory]
    [InlineData("valid_property.json")]
    [InlineData("valid_classification.json")]
    [InlineData("valid_object.json")]
    public void ValidVectorsDeserializeAndRoundTripWithSnakeCase(string name)
    {
        var fact = NormalizedDesignFact.FromJson(ReadVector(name));
        var json = fact.ToJson();
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;

        Assert.True(root.TryGetProperty("fact_id", out _));
        Assert.True(root.TryGetProperty("host_ref", out _));
        Assert.True(root.TryGetProperty("subject_native_ref", out _));
        Assert.True(root.TryGetProperty("value_type", out _));
        Assert.False(root.TryGetProperty("FactId", out _));
    }

    [Fact]
    public void EmptyBatchRoundTrips()
    {
        var batch = NormalizedDesignFactBatch.FromJson(ReadVector("valid_empty_batch.json"));
        Assert.Empty(batch.Facts);
        using var document = JsonDocument.Parse(batch.ToJson());
        Assert.Equal(0, document.RootElement.GetProperty("facts").GetArrayLength());
    }

    [Fact]
    public void BatchRejectsFactWithMissingRequiredNullableWireField()
    {
        var fact = JsonNode.Parse(ReadVector("valid_property.json"))!.AsObject();
        Assert.True(fact.Remove("unit"));
        var payload = new JsonObject
        {
            ["facts"] = new JsonArray(fact),
        }.ToJsonString();

        Assert.ThrowsAny<Exception>(() => NormalizedDesignFactBatch.FromJson(payload));
    }

    [Theory]
    [InlineData("invalid_source_pair.json")]
    [InlineData("invalid_document_mismatch.json")]
    [InlineData("invalid_value_type.json")]
    public void InvalidVectorsAreRejected(string name)
    {
        Assert.ThrowsAny<Exception>(() => NormalizedDesignFact.FromJson(ReadVector(name)));
    }

    [Fact]
    public void ContractAssemblyHasNoHostSdkOrSemanticProviderDependency()
    {
        var references = typeof(NormalizedDesignFact).Assembly.GetReferencedAssemblies()
            .Select(reference => reference.Name ?? string.Empty)
            .ToArray();

        Assert.DoesNotContain(references, name => name.Contains("Autodesk", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(references, name => name.Contains("HostContracts", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(references, name => name.Contains("Semantic", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(references, name => name.Contains("Ifc", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(references, name => name.Contains("Metro", StringComparison.OrdinalIgnoreCase));
    }
}
