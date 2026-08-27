using System.Security.AccessControl;
using System.Security.Principal;
using System.Text.Json;
using Xunit;

namespace AutoCAD.AgentHost.Grpc.Tests;

public class DiscoveryPublisherTests
{
    [Fact]
    public void DefaultDirectory_IsUnderLocalAppData()
    {
        var expected = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "EnterpriseDesignAgent",
            "hosts");

        Assert.Equal(
            Path.GetFullPath(expected),
            Path.GetFullPath(global::AutoCAD.AgentHost.Grpc.Discovery.DiscoveryPublisher.DefaultDirectory));
    }

    [Fact]
    public async Task Publish_WritesRequiredJsonAtomically_AndLeaseRemovesIt()
    {
        var directory = NewTempDirectory();
        var record = SampleRecord();
        var publisher = new global::AutoCAD.AgentHost.Grpc.Discovery.DiscoveryPublisher(directory);

        await using (var lease = await publisher.PublishAsync(record))
        {
            Assert.True(File.Exists(lease.Path));
            Assert.Empty(Directory.EnumerateFiles(directory, "*.tmp"));

            using var document = JsonDocument.Parse(await File.ReadAllTextAsync(lease.Path));
            var root = document.RootElement;
            var propertyNames = root.EnumerateObject().Select(p => p.Name).ToHashSet(StringComparer.Ordinal);
            Assert.Equal(
                new HashSet<string>(StringComparer.Ordinal)
                {
                    "instance_id",
                    "pid",
                    "host",
                    "port",
                    "transport",
                    "contract_version",
                    "auth_token",
                },
                propertyNames);
            Assert.Equal(record.InstanceId, root.GetProperty("instance_id").GetString());
            Assert.Equal(record.Pid, root.GetProperty("pid").GetInt32());
            Assert.Equal("127.0.0.1", root.GetProperty("host").GetString());
            Assert.Equal(record.Port, root.GetProperty("port").GetInt32());
            Assert.Equal("grpc-h2c", root.GetProperty("transport").GetString());
            Assert.Equal("1.0", root.GetProperty("contract_version").GetString());
            Assert.Equal(record.AuthToken, root.GetProperty("auth_token").GetString());
        }

        Assert.False(File.Exists(Path.Combine(directory, $"{record.InstanceId}.json")));
        Directory.Delete(directory, recursive: true);
    }

    [Fact]
    public async Task Publish_ProtectsDirectoryFromEveryoneWriteAccess()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        var directory = NewTempDirectory();
        var publisher = new global::AutoCAD.AgentHost.Grpc.Discovery.DiscoveryPublisher(directory);
        await using var lease = await publisher.PublishAsync(SampleRecord());

        var security = new DirectoryInfo(directory).GetAccessControl(AccessControlSections.Access);
        var rules = security.GetAccessRules(
            includeExplicit: true,
            includeInherited: true,
            targetType: typeof(SecurityIdentifier))
            .Cast<FileSystemAccessRule>()
            .ToList();

        var currentUser = WindowsIdentity.GetCurrent().User
            ?? throw new InvalidOperationException("current Windows user has no SID");
        var everyone = new SecurityIdentifier(WellKnownSidType.WorldSid, null);

        Assert.Contains(rules, rule =>
            Equals(rule.IdentityReference, currentUser)
            && rule.AccessControlType == AccessControlType.Allow
            && rule.FileSystemRights.HasFlag(FileSystemRights.FullControl));
        Assert.DoesNotContain(rules, rule =>
            Equals(rule.IdentityReference, everyone)
            && rule.AccessControlType == AccessControlType.Allow
            && (rule.FileSystemRights & (FileSystemRights.Write | FileSystemRights.Modify | FileSystemRights.FullControl)) != 0);

        await lease.DisposeAsync();
        Directory.Delete(directory, recursive: true);
    }

    [Fact]
    public async Task OldLease_DoesNotDeleteReplacedRecord()
    {
        var directory = NewTempDirectory();
        var record = SampleRecord();
        var publisher = new global::AutoCAD.AgentHost.Grpc.Discovery.DiscoveryPublisher(directory);
        var lease = await publisher.PublishAsync(record);

        var replacement = "{\"instance_id\":\"replacement\"}";
        await File.WriteAllTextAsync(lease.Path, replacement);
        await lease.DisposeAsync();

        Assert.True(File.Exists(lease.Path));
        Assert.Equal(replacement, await File.ReadAllTextAsync(lease.Path));

        File.Delete(lease.Path);
        Directory.Delete(directory, recursive: true);
    }

    private static global::AutoCAD.AgentHost.Grpc.Discovery.HostDiscoveryRecord SampleRecord() =>
        new(
            InstanceId: Guid.NewGuid().ToString("D"),
            Pid: Environment.ProcessId,
            Host: "127.0.0.1",
            Port: 53182,
            Transport: "grpc-h2c",
            ContractVersion: "1.0",
            AuthToken: "test-token");

    private static string NewTempDirectory()
    {
        var path = Path.Combine(Path.GetTempPath(), "dsp-grpc-discovery-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
    }
}
