using System.IO.Pipes;
using AutoCAD.AgentHost.Ipc;

namespace AutoCAD.AgentHost.Ipc;

/// <summary>
/// Named-pipe server inside the AutoCAD process (ADR-002).
/// Frame format: 4-byte little-endian length prefix + UTF-8 JSON envelope.
/// </summary>
public sealed class NamedPipeServer
{
    public const int MaxFrameBytes = 1024 * 1024; // 1 MiB

    private readonly RequestDispatcher _dispatcher;
    private readonly CancellationTokenSource _cts = new();
    private Task? _acceptLoop;

    public NamedPipeServer(RequestDispatcher dispatcher) => _dispatcher = dispatcher;

    public string PipeName { get; private set; } = $"EnterpriseDesignAgent.{Environment.MachineName}-{Environment.ProcessId}";

    public void Start()
    {
        _acceptLoop = Task.Run(() => AcceptLoopAsync(_cts.Token));
    }

    public void Stop()
    {
        _cts.Cancel();
        _acceptLoop?.Wait(TimeSpan.FromSeconds(2));
        _cts.Dispose();
    }

    private async Task AcceptLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                var pipe = new NamedPipeServerStream(
                    PipeName,
                    PipeDirection.InOut,
                    maxNumberOfServerInstances: 1,
                    PipeTransmissionMode.Byte,
                    PipeOptions.Asynchronous);

                await pipe.WaitForConnectionAsync(ct);
                await HandleClientAsync(pipe, ct);
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (Exception ex)
            {
                // Log and continue accepting.
                System.Diagnostics.Debug.WriteLine($"[AgentHost] accept failed: {ex.Message}");
                await Task.Delay(250, ct);
            }
        }
    }

    private async Task HandleClientAsync(NamedPipeServerStream pipe, CancellationToken ct)
    {
        try
        {
            while (!ct.IsCancellationRequested && pipe.IsConnected)
            {
                var frame = await ReadFrameAsync(pipe, ct);
                if (frame is null)
                {
                    break; // client closed
                }

                var response = _dispatcher.Dispatch(frame);
                await WriteFrameAsync(pipe, response, ct);
            }
        }
        finally
        {
            pipe.Dispose();
        }
    }

    private static async Task<byte[]?> ReadFrameAsync(NamedPipeServerStream pipe, CancellationToken ct)
    {
        var header = new byte[4];
        int read = await pipe.ReadAsync(header.AsMemory(0, 4), ct);
        if (read == 0)
        {
            return null;
        }

        while (read < 4)
        {
            int n = await pipe.ReadAsync(header.AsMemory(read, 4 - read), ct);
            if (n == 0)
            {
                return null;
            }

            read += n;
        }

        int length = BitConverter.ToInt32(header, 0);
        if (length <= 0 || length > MaxFrameBytes)
        {
            throw new InvalidDataException($"invalid frame length: {length}");
        }

        var body = new byte[length];
        read = 0;
        while (read < length)
        {
            int n = await pipe.ReadAsync(body.AsMemory(read, length - read), ct);
            if (n == 0)
            {
                return null;
            }

            read += n;
        }

        return body;
    }

    private static async Task WriteFrameAsync(NamedPipeServerStream pipe, byte[] body, CancellationToken ct)
    {
        var header = BitConverter.GetBytes(body.Length);
        await pipe.WriteAsync(header.AsMemory(), ct);
        await pipe.WriteAsync(body.AsMemory(), ct);
        await pipe.FlushAsync(ct);
    }
}
