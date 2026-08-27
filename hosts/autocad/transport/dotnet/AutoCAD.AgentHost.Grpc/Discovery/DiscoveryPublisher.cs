using System.Security.AccessControl;
using System.Security.Principal;
using System.Text.Json;

namespace AutoCAD.AgentHost.Grpc.Discovery;

/// <summary>Atomically publishes one current-user-only discovery record.</summary>
public sealed class DiscoveryPublisher
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = false,
    };

    private readonly string _directory;

    public DiscoveryPublisher(string? discoveryDirectory = null)
    {
        _directory = Path.GetFullPath(discoveryDirectory ?? DefaultDirectory);
    }

    public static string DefaultDirectory => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "EnterpriseDesignAgent",
        "hosts");

    public async Task<DiscoveryLease> PublishAsync(
        HostDiscoveryRecord record,
        CancellationToken cancellationToken = default)
    {
        Validate(record);
        Directory.CreateDirectory(_directory);
        ProtectDirectory(_directory);

        var finalPath = Path.Combine(_directory, $"{record.InstanceId}.json");
        var tempPath = Path.Combine(_directory, $"{record.InstanceId}.{Guid.NewGuid():N}.tmp");
        var payload = JsonSerializer.SerializeToUtf8Bytes(record, JsonOptions);

        try
        {
            await File.WriteAllBytesAsync(tempPath, payload, cancellationToken);
            ProtectFile(tempPath);
            File.Move(tempPath, finalPath, overwrite: true);
            ProtectFile(finalPath);
            return new DiscoveryLease(finalPath, payload);
        }
        finally
        {
            TryDelete(tempPath);
        }
    }

    private static void Validate(HostDiscoveryRecord record)
    {
        ArgumentNullException.ThrowIfNull(record);
        ArgumentException.ThrowIfNullOrWhiteSpace(record.InstanceId);
        if (!string.Equals(Path.GetFileName(record.InstanceId), record.InstanceId, StringComparison.Ordinal)
            || record.InstanceId is "." or ".."
            || record.InstanceId.Contains(Path.DirectorySeparatorChar)
            || record.InstanceId.Contains(Path.AltDirectorySeparatorChar))
        {
            throw new ArgumentException("instance_id must be a safe file name", nameof(record));
        }

        if (record.Pid <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(record), "pid must be positive");
        }

        if (!string.Equals(record.Host, "127.0.0.1", StringComparison.Ordinal))
        {
            throw new ArgumentException("host must be IPv4 loopback 127.0.0.1", nameof(record));
        }

        if (record.Port is <= 0 or > 65535)
        {
            throw new ArgumentOutOfRangeException(nameof(record), "port must be in the range 1..65535");
        }

        if (!string.Equals(record.Transport, "grpc-h2c", StringComparison.Ordinal))
        {
            throw new ArgumentException("transport must be grpc-h2c", nameof(record));
        }

        ArgumentException.ThrowIfNullOrWhiteSpace(record.ContractVersion);
        ArgumentException.ThrowIfNullOrWhiteSpace(record.AuthToken);
    }

    private static void ProtectDirectory(string path)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        var sid = WindowsIdentity.GetCurrent().User
            ?? throw new InvalidOperationException("current Windows user has no SID");
        var security = new DirectorySecurity();
        security.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
        security.SetOwner(sid);
        security.AddAccessRule(new FileSystemAccessRule(
            sid,
            FileSystemRights.FullControl,
            InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
            PropagationFlags.None,
            AccessControlType.Allow));
        new DirectoryInfo(path).SetAccessControl(security);
    }

    private static void ProtectFile(string path)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        var sid = WindowsIdentity.GetCurrent().User
            ?? throw new InvalidOperationException("current Windows user has no SID");
        var security = new FileSecurity();
        security.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
        security.SetOwner(sid);
        security.AddAccessRule(new FileSystemAccessRule(
            sid,
            FileSystemRights.FullControl,
            AccessControlType.Allow));
        new FileInfo(path).SetAccessControl(security);
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException)
        {
            // Best-effort cleanup of a failed temporary publication.
        }
        catch (UnauthorizedAccessException)
        {
            // Best-effort cleanup of a failed temporary publication.
        }
    }
}

/// <summary>Deletes the discovery record only while it is still the record originally published.</summary>
public sealed class DiscoveryLease : IAsyncDisposable
{
    private readonly byte[] _publishedBytes;
    private int _disposed;

    internal DiscoveryLease(string path, byte[] publishedBytes)
    {
        Path = path;
        _publishedBytes = publishedBytes.ToArray();
    }

    public string Path { get; }

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }

        try
        {
            if (!File.Exists(Path))
            {
                return;
            }

            var currentBytes = await File.ReadAllBytesAsync(Path);
            if (currentBytes.AsSpan().SequenceEqual(_publishedBytes))
            {
                File.Delete(Path);
            }
        }
        catch (FileNotFoundException)
        {
            // Another owner already removed or replaced the record.
        }
        catch (DirectoryNotFoundException)
        {
            // The discovery directory was already removed.
        }
    }
}
