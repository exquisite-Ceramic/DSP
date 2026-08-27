namespace AutoCAD.AgentHost.Grpc;

/// <summary>
/// Transport-neutral boundary for dispatching one existing DSP contract JSON document.
/// Implementations must not expose native Autodesk types across this interface.
/// </summary>
public interface IContractDispatchTarget
{
    ValueTask<byte[]> DispatchAsync(byte[] contractJson, CancellationToken cancellationToken);
}
