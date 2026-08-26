using System.Text.Json;
using HostContracts;
using Xunit;

namespace HostContracts.Tests;

public class HostDeltaTests
{
    private static T RoundTrip<T>(T value) =>
        JsonSerializer.Deserialize<T>(JsonSerializer.Serialize(value, ContractJson.Options), ContractJson.Options)!;

    [Fact]
    public void RoundTrips_Structure()
    {
        var original = new HostDelta
        {
            RevisionBefore = 100,
            RevisionAfter = 101,
            Modified = { new HostEntityRef { DocumentId = "drawing-001", NativeId = "2AF" } },
        };

        var restored = RoundTrip(original);

        Assert.Equal(100, restored.RevisionBefore);
        Assert.Equal(101, restored.RevisionAfter);
        Assert.Equal("2AF", Assert.Single(restored.Modified).NativeId);
        Assert.Empty(restored.Added);
        Assert.Empty(restored.Erased);
        Assert.Empty(original.Validate());
    }

    [Fact]
    public void RevisionAfter_MustBeGreaterOrEqual_RevisionBefore()
    {
        Assert.Empty(new HostDelta { RevisionBefore = 100, RevisionAfter = 101 }.Validate());
        Assert.Empty(new HostDelta { RevisionBefore = 100, RevisionAfter = 100 }.Validate());
        Assert.NotEmpty(new HostDelta { RevisionBefore = 101, RevisionAfter = 100 }.Validate());
    }

    [Fact]
    public void SameEntity_NotAllowed_InAddedAndErased()
    {
        var conflict = new HostDelta
        {
            RevisionBefore = 100,
            RevisionAfter = 101,
            Added = { new HostEntityRef { DocumentId = "drawing-001", NativeId = "2AF" } },
            Erased = { new HostEntityRef { DocumentId = "drawing-001", NativeId = "2AF" } },
        };
        Assert.NotEmpty(conflict.Validate());

        var ok = new HostDelta
        {
            RevisionBefore = 100,
            RevisionAfter = 101,
            Added = { new HostEntityRef { DocumentId = "drawing-001", NativeId = "3B1" } },
            Erased = { new HostEntityRef { DocumentId = "drawing-001", NativeId = "2AF" } },
        };
        Assert.Empty(ok.Validate());
    }

    [Fact]
    public void UnknownField_IsIgnored()
    {
        const string json = """{"revision_before":100,"revision_after":101,"future_kind":"x"}""";
        var delta = JsonSerializer.Deserialize<HostDelta>(json, ContractJson.Options)!;
        Assert.Equal(100, delta.RevisionBefore);
        Assert.Equal(101, delta.RevisionAfter);
        var reserialized = JsonSerializer.Serialize(delta, ContractJson.Options);
        Assert.DoesNotContain("future_kind", reserialized);
    }
}
