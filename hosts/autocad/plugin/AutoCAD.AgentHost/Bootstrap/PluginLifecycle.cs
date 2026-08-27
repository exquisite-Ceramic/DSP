using System.Diagnostics;
using System.Security.Cryptography;
using AutoCAD.AgentHost.ChangeCapture;
using AutoCAD.AgentHost.Commands;
using AutoCAD.AgentHost.Execution;
using AutoCAD.AgentHost.Grpc;
using AutoCAD.AgentHost.Grpc.Discovery;
using AutoCAD.AgentHost.Ipc;
using HostContracts;

namespace AutoCAD.AgentHost.Bootstrap;

/// <summary>
/// Owns the plugin lifecycle. During the migration window Named Pipe remains
/// available while an authenticated loopback gRPC endpoint is published for
/// explicit opt-in clients.
/// </summary>
public sealed class PluginLifecycle
{
    private NamedPipeServer? _pipeServer;
    private ChangeSensor? _sensor;
    private DiscoveryLease? _discoveryLease;
    private GrpcHostHandle? _grpcHost;

    public void Start()
    {
        var dispatcher = new RequestDispatcher(
            new HostCommandHandlerRegistry(),
            new IdempotencyStore(),
            new RevisionGuard());

        // Named Pipe remains the migration default and must not depend on gRPC
        // startup succeeding.
        _pipeServer = new NamedPipeServer(dispatcher);
        _pipeServer.Start();

        try
        {
            StartGrpcAsync(dispatcher).GetAwaiter().GetResult();
        }
        catch (Exception exception)
        {
            Trace.TraceError(
                "AutoCAD gRPC transport failed to start; Named Pipe remains available. {0}",
                exception);
        }

        _sensor = new ChangeSensor(new HostDeltaBuilder(), new EventQueue());
        _sensor.Attach();
    }

    public void Stop()
    {
        _sensor?.Detach();
        _sensor = null;

        DisposeDiscoveryLease();
        DisposeGrpcHost();

        _pipeServer?.Stop();
        _pipeServer = null;
    }

    private async Task StartGrpcAsync(RequestDispatcher dispatcher)
    {
        var instanceId = Guid.NewGuid().ToString("D");
        var authToken = CreateAuthToken();
        var identity = new TransportIdentity(
            instanceId,
            authToken,
            ContractVersion.Current);

        GrpcHostHandle? host = null;
        DiscoveryLease? lease = null;

        try
        {
            host = await GrpcHostServer.StartAsync(
                new GrpcRequestDispatcherTarget(dispatcher),
                identity,
                new GrpcHostOptions(Host: "127.0.0.1", Port: 0));

            // Publication happens only after Kestrel has returned the actual
            // dynamic port, so clients cannot discover an unbound endpoint.
            lease = await new DiscoveryPublisher().PublishAsync(new HostDiscoveryRecord(
                instanceId,
                Environment.ProcessId,
                "127.0.0.1",
                host.Port,
                "grpc-h2c",
                ContractVersion.Current,
                authToken));

            _grpcHost = host;
            _discoveryLease = lease;
            host = null;
            lease = null;
        }
        finally
        {
            if (lease is not null)
            {
                await lease.DisposeAsync();
            }

            if (host is not null)
            {
                await host.DisposeAsync();
            }
        }
    }

    private static string CreateAuthToken()
    {
        var bytes = RandomNumberGenerator.GetBytes(32);
        return Convert.ToBase64String(bytes)
            .TrimEnd('=')
            .Replace('+', '-')
            .Replace('/', '_');
    }

    private void DisposeDiscoveryLease()
    {
        var lease = _discoveryLease;
        _discoveryLease = null;
        if (lease is null)
        {
            return;
        }

        try
        {
            lease.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }
        catch (Exception exception)
        {
            Trace.TraceError("Failed to remove AutoCAD gRPC discovery record. {0}", exception);
        }
    }

    private void DisposeGrpcHost()
    {
        var host = _grpcHost;
        _grpcHost = null;
        if (host is null)
        {
            return;
        }

        try
        {
            host.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }
        catch (Exception exception)
        {
            Trace.TraceError("Failed to stop AutoCAD gRPC transport. {0}", exception);
        }
    }
}
