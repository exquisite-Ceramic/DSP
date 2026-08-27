using Microsoft.AspNetCore.Builder;

namespace AutoCAD.AgentHost.Grpc;

/// <summary>Owns one running loopback gRPC host and its resolved endpoint.</summary>
public sealed class GrpcHostHandle : IAsyncDisposable
{
    private readonly WebApplication _application;
    private int _disposed;

    internal GrpcHostHandle(WebApplication application, Uri address)
    {
        _application = application;
        Address = address;
    }

    public Uri Address { get; }

    public int Port => Address.Port;

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }

        await _application.StopAsync();
        await _application.DisposeAsync();
    }
}
