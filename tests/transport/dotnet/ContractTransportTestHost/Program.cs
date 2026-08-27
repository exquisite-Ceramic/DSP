using System.Text.Json;
using AutoCAD.AgentHost.Grpc;
using AutoCAD.AgentHost.Grpc.Discovery;

namespace ContractTransportTestHost;

internal static class Program
{
    private const string ContractVersion = "1.0";

    public static async Task<int> Main(string[] args)
    {
        try
        {
            var options = HostOptions.Parse(args);
            Environment.SetEnvironmentVariable("Logging__LogLevel__Default", "Warning");

            var counter = new CounterFile(options.CounterFile);
            await counter.InitializeAsync();
            var target = new FakeDispatchTarget(options.Mode, counter);
            var identity = new TransportIdentity(
                options.InstanceId,
                options.Token,
                ContractVersion);

            await using var host = await GrpcHostServer.StartAsync(
                target,
                identity,
                new GrpcHostOptions(Host: "127.0.0.1", Port: 0));

            var publisher = new DiscoveryPublisher(options.DiscoveryDirectory);
            await using var lease = await publisher.PublishAsync(new HostDiscoveryRecord(
                options.InstanceId,
                Environment.ProcessId,
                "127.0.0.1",
                host.Port,
                "grpc-h2c",
                ContractVersion,
                options.Token));

            Console.Out.WriteLine(JsonSerializer.Serialize(new
            {
                instance_id = options.InstanceId,
                port = host.Port,
                pid = Environment.ProcessId,
            }));
            Console.Out.Flush();

            // The Python fixture owns stdin and sends one line to request a
            // graceful shutdown. This keeps dotnet-run child processes from
            // surviving a test teardown on Windows.
            await Console.In.ReadLineAsync();
            return 0;
        }
        catch (Exception exception)
        {
            await Console.Error.WriteLineAsync(exception.ToString());
            return 1;
        }
    }

    private sealed record HostOptions(
        string InstanceId,
        string Token,
        string DiscoveryDirectory,
        string Mode,
        string CounterFile)
    {
        public static HostOptions Parse(string[] args)
        {
            var values = new Dictionary<string, string>(StringComparer.Ordinal);
            for (var index = 0; index < args.Length; index += 2)
            {
                if (index + 1 >= args.Length || !args[index].StartsWith("--", StringComparison.Ordinal))
                {
                    throw new ArgumentException("arguments must be supplied as --name value pairs");
                }
                values[args[index][2..]] = args[index + 1];
            }

            static string Required(IReadOnlyDictionary<string, string> source, string name)
            {
                if (!source.TryGetValue(name, out var value) || string.IsNullOrWhiteSpace(value))
                {
                    throw new ArgumentException($"--{name} is required");
                }
                return value;
            }

            var mode = Required(values, "mode");
            if (mode is not ("normal" or "block"))
            {
                throw new ArgumentException("--mode must be normal or block");
            }

            return new HostOptions(
                Required(values, "instance-id"),
                Required(values, "token"),
                Required(values, "discovery-dir"),
                mode,
                Required(values, "counter-file"));
        }
    }
}
