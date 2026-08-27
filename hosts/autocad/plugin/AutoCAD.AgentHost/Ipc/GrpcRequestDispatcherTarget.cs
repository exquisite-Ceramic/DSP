using AutoCAD.AgentHost.Grpc;

namespace AutoCAD.AgentHost.Ipc;

/// <summary>
/// Adapts the existing synchronous DSP request dispatcher to the transport-only
/// gRPC boundary without changing the HostContract JSON wire format.
/// </summary>
public sealed class GrpcRequestDispatcherTarget : IContractDispatchTarget
{
    private readonly RequestDispatcher _dispatcher;

    public GrpcRequestDispatcherTarget(RequestDispatcher dispatcher)
    {
        _dispatcher = dispatcher ?? throw new ArgumentNullException(nameof(dispatcher));
    }

    public ValueTask<byte[]> DispatchAsync(
        byte[] contractJson,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return ValueTask.FromResult(_dispatcher.Dispatch(contractJson));
    }
}
