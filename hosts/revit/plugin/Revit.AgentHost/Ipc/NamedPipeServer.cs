using System.IO.Pipes;
using System.Text.Json;
using Revit.AgentHost.Core.Contracts;

namespace Revit.AgentHost.Ipc;

public sealed class NamedPipeServer : IDisposable
{
    public const int MaxFrameBytes = 1024 * 1024;

    private readonly RequestDispatcher dispatcher;
    private readonly CancellationTokenSource cancellation = new();
    private Task? acceptLoop;

    public NamedPipeServer(RequestDispatcher dispatcher, string? pipeName = null)
    {
        this.dispatcher = dispatcher ?? throw new ArgumentNullException(nameof(dispatcher));
        PipeName = string.IsNullOrWhiteSpace(pipeName)
            ? $"EnterpriseDesignAgent.Revit.{Environment.MachineName}-{Environment.ProcessId}"
            : pipeName;
    }

    public string PipeName { get; }

    public void Start()
    {
        if (acceptLoop is not null)
        {
            throw new InvalidOperationException("Named pipe server is already started.");
        }

        acceptLoop = Task.Run(() => AcceptLoopAsync(cancellation.Token));
    }

    public void Stop()
    {
        cancellation.Cancel();
        acceptLoop?.Wait(TimeSpan.FromSeconds(2));
    }

    public void Dispose()
    {
        Stop();
        cancellation.Dispose();
    }

    private async Task AcceptLoopAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                await using var pipe = new NamedPipeServerStream(
                    PipeName,
                    PipeDirection.InOut,
                    1,
                    PipeTransmissionMode.Byte,
                    PipeOptions.Asynchronous);

                await pipe.WaitForConnectionAsync(cancellationToken).ConfigureAwait(false);
                await HandleClientAsync(pipe, cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                break;
            }
        }
    }

    private async Task HandleClientAsync(
        NamedPipeServerStream pipe,
        CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested && pipe.IsConnected)
        {
            byte[]? body = await ReadFrameAsync(pipe, cancellationToken).ConfigureAwait(false);
            if (body is null)
            {
                return;
            }

            HostCommandEnvelope command = JsonSerializer.Deserialize<HostCommandEnvelope>(body)
                ?? throw new InvalidDataException("HostCommand payload must be a JSON object.");
            HostResultEnvelope result = await dispatcher
                .DispatchAsync(command, cancellationToken)
                .ConfigureAwait(false);
            byte[] response = JsonSerializer.SerializeToUtf8Bytes(result);
            await WriteFrameAsync(pipe, response, cancellationToken).ConfigureAwait(false);
        }
    }

    private static async Task<byte[]?> ReadFrameAsync(
        NamedPipeServerStream pipe,
        CancellationToken cancellationToken)
    {
        byte[] header = new byte[4];
        int headerBytes = await ReadExactAsync(pipe, header, cancellationToken).ConfigureAwait(false);
        if (headerBytes == 0)
        {
            return null;
        }

        if (headerBytes != header.Length)
        {
            throw new EndOfStreamException("Named pipe closed during frame header.");
        }

        int length = BitConverter.ToInt32(header, 0);
        if (length <= 0 || length > MaxFrameBytes)
        {
            throw new InvalidDataException($"invalid frame length: {length}");
        }

        byte[] body = new byte[length];
        int bodyBytes = await ReadExactAsync(pipe, body, cancellationToken).ConfigureAwait(false);
        if (bodyBytes != length)
        {
            throw new EndOfStreamException("Named pipe closed during frame body.");
        }

        return body;
    }

    private static async Task<int> ReadExactAsync(
        NamedPipeServerStream pipe,
        byte[] buffer,
        CancellationToken cancellationToken)
    {
        int total = 0;
        while (total < buffer.Length)
        {
            int read = await pipe
                .ReadAsync(buffer.AsMemory(total, buffer.Length - total), cancellationToken)
                .ConfigureAwait(false);
            if (read == 0)
            {
                break;
            }

            total += read;
        }

        return total;
    }

    private static async Task WriteFrameAsync(
        NamedPipeServerStream pipe,
        byte[] body,
        CancellationToken cancellationToken)
    {
        if (body.Length <= 0 || body.Length > MaxFrameBytes)
        {
            throw new InvalidDataException($"invalid response frame length: {body.Length}");
        }

        byte[] header = BitConverter.GetBytes(body.Length);
        await pipe.WriteAsync(header.AsMemory(), cancellationToken).ConfigureAwait(false);
        await pipe.WriteAsync(body.AsMemory(), cancellationToken).ConfigureAwait(false);
        await pipe.FlushAsync(cancellationToken).ConfigureAwait(false);
    }
}
