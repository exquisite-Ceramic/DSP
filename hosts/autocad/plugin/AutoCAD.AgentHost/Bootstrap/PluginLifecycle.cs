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
    private CancellationTokenSource? _grpcStartupCts;
    private Task? _grpcStartupTask;

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

        // AutoCAD calls Initialize on its UI thread. Never synchronously wait on
        // Kestrel startup from that thread: async continuations can otherwise
        // deadlock the host synchronization context during NETLOAD.
        _grpcStartupCts = new CancellationTokenSource();
        var cancellationToken = _grpcStartupCts.Token;
        _grpcStartupTask = Task.Run(
            () => RunGrpcLifetimeAsync(dispatcher, cancellationToken),
            CancellationToken.None);

        _sensor = new ChangeSensor(new HostDeltaBuilder(), new EventQueue());
        _sensor.Attach();
    }

    public void Stop()
    {
        _sensor?.Detach();
        _sensor = null;

        var grpcCts = _grpcStartupCts;
        var grpcTask = _grpcStartupTask;
        _grpcStartupCts = null;
        _grpcStartupTask = null;

        _grpcStartupCts?.Cancel();
        grpcCts?.Cancel();
        if (grpcCts is not null)
        {
            if (grpcTask is null)
            {
                grpcCts.Dispose();
            }
            else
            {
                _ = grpcTask.ContinueWith(
                    _ => grpcCts.Dispose(),
                    CancellationToken.None,
                    TaskContinuationOptions.ExecuteSynchronously,
                    TaskScheduler.Default);
            }
        }

        _pipeServer?.Stop();
        _pipeServer = null;
    }

    private async Task RunGrpcLifetimeAsync(
        RequestDispatcher dispatcher,
        CancellationToken cancellationToken)
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
                    new GrpcHostOptions(Host: "127.0.0.1", Port: 0),
                    cancellationToken)
                .ConfigureAwait(false);

            // Publication happens only after Kestrel has returned the actual
            // dynamic port, so clients cannot discover an unbound endpoint.
            lease = await new DiscoveryPublisher().PublishAsync(
                    new HostDiscoveryRecord(
                        instanceId,
                        Environment.ProcessId,
                        "127.0.0.1",
                        host.Port,
                        "grpc-h2c",
                        ContractVersion.Current,
                        authToken),
                    cancellationToken)
                .ConfigureAwait(false);

            await Task.Delay(Timeout.Infinite, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // Normal plugin shutdown.
        }
        catch (Exception exception)
        {
            Trace.TraceError(
                "AutoCAD gRPC transport failed to start; Named Pipe remains available. {0}",
                exception);
        }
        finally
        {
            if (lease is not null)
            {
                try
                {
                    await lease.DisposeAsync().ConfigureAwait(false);
                }
                catch (Exception exception)
                {
                    Trace.TraceError("Failed to remove AutoCAD gRPC discovery record. {0}", exception);
                }
            }

            if (host is not null)
            {
                try
                {
                    await host.DisposeAsync().ConfigureAwait(false);
                }
                catch (Exception exception)
                {
                    Trace.TraceError("Failed to stop AutoCAD gRPC transport. {0}", exception);
                }
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
}
