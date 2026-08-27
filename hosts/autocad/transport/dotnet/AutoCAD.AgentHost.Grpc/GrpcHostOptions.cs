namespace AutoCAD.AgentHost.Grpc;

/// <summary>Configuration for the local gRPC host.</summary>
public sealed record GrpcHostOptions(
    string Host = "127.0.0.1",
    int Port = 0,
    string? DiscoveryDirectory = null);
