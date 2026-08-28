using System.Text.Json.Nodes;
using DesignFactContracts;
using Xunit;

namespace DesignFactContracts.Tests;

public sealed class WireShapeTests
{
    private static string VectorPath(string name) =>
        Path.Combine(AppContext.BaseDirectory, "test_vectors", "normalized_design_fact", name);

    [Fact]
    public void ProvenanceNullIsRejected()
    {
        var fact = JsonNode.Parse(File.ReadAllText(VectorPath("valid_property.json")))!.AsObject();
        fact["provenance"] = null;

        Assert.ThrowsAny<Exception>(() => NormalizedDesignFact.FromJson(fact.ToJsonString()));
    }
}
