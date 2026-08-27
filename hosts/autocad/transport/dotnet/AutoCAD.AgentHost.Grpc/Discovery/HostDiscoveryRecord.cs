using System.Text.Json.Serialization;

namespace AutoCAD.AgentHost.Grpc.Discovery;

/// <summary>Current-user discovery record for one local AutoCAD gRPC endpoint.</summary>
public sealed record HostDiscoveryRecord(
    [property: JsonPropertyName("instance_id")] string InstanceId,
    [property: JsonPropertyName("pid")] int Pid,
    [property: JsonPropertyName("host")] string Host,
    [property: JsonPropertyName("port")] int Port,
    [property: JsonPropertyName("transport")] string Transport,
    [property: JsonPropertyName("contract_version")] string ContractVersion,
    [property: JsonPropertyName("auth_token")] string AuthToken);
