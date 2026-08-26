using System.Text.Json;
using HostContracts;
using Xunit;

namespace HostContracts.Tests;

public class HostEntityRefTests
{
    private static T RoundTrip<T>(T value) =>
        JsonSerializer.Deserialize<T>(JsonSerializer.Serialize(value, ContractJson.Options), ContractJson.Options)!;

    [Fact]
    public void RoundTrips_AllFields()
    {
        var original = new HostEntityRef
        {
            DocumentId = "drawing-001",
            NativeId = "2AF",
            NativeType = "LINE",
        };

        var restored = RoundTrip(original);

        Assert.Equal(original.DocumentId, restored.DocumentId);
        Assert.Equal(original.NativeId, restored.NativeId);
        Assert.Equal(original.NativeType, restored.NativeType);
        Assert.Empty(original.Validate());
    }

    [Fact]
    public void NativeType_IsOptional_AndOmittedWhenNull()
    {
        var ref_ = new HostEntityRef { DocumentId = "drawing-001", NativeId = "2AF" };
        var json = JsonSerializer.Serialize(ref_, ContractJson.Options);
        Assert.DoesNotContain("native_type", json);

        var restored = JsonSerializer.Deserialize<HostEntityRef>(json, ContractJson.Options)!;
        Assert.Null(restored.NativeType);
    }

    [Fact]
    public void MissingFields_AreInvalid()
    {
        Assert.NotEmpty(new HostEntityRef { DocumentId = "", NativeId = "2AF" }.Validate());
        Assert.NotEmpty(new HostEntityRef { DocumentId = "drawing-001", NativeId = "" }.Validate());
        Assert.Empty(new HostEntityRef { DocumentId = "drawing-001", NativeId = "2AF" }.Validate());
    }

    [Fact]
    public void UnknownField_IsIgnored()
    {
        const string json = """{"document_id":"drawing-001","native_id":"2AF","object_id":"0x1a2b"}""";
        var ref_ = JsonSerializer.Deserialize<HostEntityRef>(json, ContractJson.Options)!;
        Assert.Equal("drawing-001", ref_.DocumentId);
        Assert.Equal("2AF", ref_.NativeId);

        var reserialized = JsonSerializer.Serialize(ref_, ContractJson.Options);
        Assert.DoesNotContain("object_id", reserialized);
    }
}
