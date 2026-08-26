using System.Text.Json;
using HostContracts;
using Xunit;

namespace HostContracts.Tests;

public class ContractVersionWireTests
{
    [Fact]
    public void RequestEnvelope_WritesContractVersion()
    {
        var json = JsonSerializer.Serialize(new RequestEnvelope { RequestId = "req-1" }, ContractJson.Options);
        Assert.Contains("\"contract_version\":\"1.0\"", json);
    }

    [Fact]
    public void RequestEnvelope_RejectsMissingContractVersionOnWire()
    {
        Assert.Throws<JsonException>(() => JsonSerializer.Deserialize<RequestEnvelope>(
            """{"request_id":"req-1","payload":{}}""", ContractJson.Options));
    }

    [Fact]
    public void RequestEnvelope_RejectsUnsupportedContractVersion()
    {
        var env = new RequestEnvelope { RequestId = "req-1", ContractVersion = "2.0" };
        Assert.Contains(env.Validate(), e => e.Contains("contract_version"));
    }

    [Fact]
    public void ResponseEnvelope_RejectsMissingContractVersionOnWire()
    {
        Assert.Throws<JsonException>(() => JsonSerializer.Deserialize<ResponseEnvelope>(
            """{"request_id":"req-1","status":"OK"}""", ContractJson.Options));
    }

    [Fact]
    public void ResponseEnvelope_RejectsUnsupportedContractVersion()
    {
        var env = new ResponseEnvelope { RequestId = "req-1", ContractVersion = "2.0" };
        Assert.Contains(env.Validate(), e => e.Contains("contract_version"));
    }
}
