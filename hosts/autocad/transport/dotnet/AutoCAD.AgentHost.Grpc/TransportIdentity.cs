namespace AutoCAD.AgentHost.Grpc;

/// <summary>Identity and authentication material for one AutoCAD transport instance.</summary>
public sealed record TransportIdentity(
    string InstanceId,
    string AuthToken,
    string ContractVersion);
