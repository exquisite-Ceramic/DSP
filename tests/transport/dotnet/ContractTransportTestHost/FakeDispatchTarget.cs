using System.Text.Json;
using System.Text.Json.Serialization;
using AutoCAD.AgentHost.Grpc;

namespace ContractTransportTestHost;

public sealed class FakeDispatchTarget : IContractDispatchTarget
{
    private readonly string _mode;
    private readonly CounterFile _counter;

    public FakeDispatchTarget(string mode, CounterFile counter)
    {
        if (mode is not ("normal" or "block"))
        {
            throw new ArgumentException("mode must be normal or block", nameof(mode));
        }

        _mode = mode;
        _counter = counter;
    }

    public async ValueTask<byte[]> DispatchAsync(
        byte[] contractJson,
        CancellationToken cancellationToken)
    {
        await _counter.IncrementAsync(CancellationToken.None);

        if (_mode == "block")
        {
            try
            {
                await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
            }
            catch (OperationCanceledException)
            {
                await _counter.SetStatusAsync("cancelled", CancellationToken.None);
                throw;
            }
        }

        try
        {
            using var document = JsonDocument.Parse(contractJson);
            if (document.RootElement.ValueKind != JsonValueKind.Object
                || !document.RootElement.TryGetProperty("request_id", out var requestIdElement)
                || requestIdElement.ValueKind != JsonValueKind.String
                || string.IsNullOrWhiteSpace(requestIdElement.GetString()))
            {
                return ErrorEnvelope("unknown", "INVALID_CONTRACT", "request_id is required");
            }

            var requestId = requestIdElement.GetString()!;
            return JsonSerializer.SerializeToUtf8Bytes(new
            {
                request_id = requestId,
                status = "OK",
                result = new
                {
                    command_id = "test-command",
                    status = "OK",
                },
            });
        }
        catch (JsonException)
        {
            return ErrorEnvelope("unknown", "INVALID_CONTRACT", "malformed DSP contract JSON");
        }
    }

    private static byte[] ErrorEnvelope(string requestId, string errorCode, string message) =>
        JsonSerializer.SerializeToUtf8Bytes(new
        {
            request_id = requestId,
            status = "ERROR",
            error = new
            {
                error_code = errorCode,
                category = "PROTOCOL",
                message,
                retryable = "NEVER",
            },
        });
}

public sealed class CounterFile
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    private readonly string _path;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private int _count;
    private string? _status;

    public CounterFile(string path)
    {
        _path = Path.GetFullPath(path);
    }

    public async Task InitializeAsync(CancellationToken cancellationToken = default)
    {
        var directory = Path.GetDirectoryName(_path)
            ?? throw new InvalidOperationException("counter file must have a parent directory");
        Directory.CreateDirectory(directory);
        await WriteSnapshotAsync(cancellationToken);
    }

    public async Task IncrementAsync(CancellationToken cancellationToken = default)
    {
        await _gate.WaitAsync(cancellationToken);
        try
        {
            checked
            {
                _count++;
            }
            await WriteSnapshotAsync(cancellationToken);
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task SetStatusAsync(string status, CancellationToken cancellationToken = default)
    {
        await _gate.WaitAsync(cancellationToken);
        try
        {
            _status = status;
            await WriteSnapshotAsync(cancellationToken);
        }
        finally
        {
            _gate.Release();
        }
    }

    private async Task WriteSnapshotAsync(CancellationToken cancellationToken)
    {
        var directory = Path.GetDirectoryName(_path)!;
        var tempPath = Path.Combine(
            directory,
            $"{Path.GetFileName(_path)}.{Guid.NewGuid():N}.tmp");
        var bytes = JsonSerializer.SerializeToUtf8Bytes(
            new CounterSnapshot(_count, _status),
            JsonOptions);

        try
        {
            await File.WriteAllBytesAsync(tempPath, bytes, cancellationToken);
            for (var attempt = 0; ; attempt++)
            {
                try
                {
                    File.Move(tempPath, _path, overwrite: true);
                    return;
                }
                catch (IOException) when (attempt < 20)
                {
                    await Task.Delay(TimeSpan.FromMilliseconds(10), cancellationToken);
                }
            }
        }
        finally
        {
            try
            {
                if (File.Exists(tempPath))
                {
                    File.Delete(tempPath);
                }
            }
            catch (IOException)
            {
                // Best-effort cleanup for a test-only status file.
            }
        }
    }

    private sealed record CounterSnapshot(
        [property: JsonPropertyName("count")] int Count,
        [property: JsonPropertyName("status")] string? Status);
}
