using System.Net;
using AutoCAD.AgentHost.Grpc.Auth;
using AutoCAD.AgentHost.Grpc.Services;
using Grpc.Core.Interceptors;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.AspNetCore.Server.Kestrel.Core;
using Microsoft.Extensions.DependencyInjection;

namespace AutoCAD.AgentHost.Grpc;

/// <summary>Starts one authenticated HTTP/2 gRPC server on IPv4 loopback.</summary>
public static class GrpcHostServer
{
    public static async Task<GrpcHostHandle> StartAsync(
        IContractDispatchTarget target,
        TransportIdentity identity,
        GrpcHostOptions options,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(target);
        ArgumentNullException.ThrowIfNull(identity);
        ArgumentNullException.ThrowIfNull(options);

        if (!string.Equals(options.Host, "127.0.0.1", StringComparison.Ordinal))
        {
            throw new ArgumentException("gRPC host must bind exactly to IPv4 loopback 127.0.0.1", nameof(options));
        }

        if (options.Port is < 0 or > 65535)
        {
            throw new ArgumentOutOfRangeException(nameof(options), "port must be in the range 0..65535");
        }

        var builder = WebApplication.CreateSlimBuilder();
        builder.WebHost.ConfigureKestrel(kestrel =>
        {
            kestrel.Listen(IPAddress.Loopback, options.Port, listen =>
            {
                listen.Protocols = HttpProtocols.Http2;
            });
        });

        builder.Services.AddSingleton(target);
        builder.Services.AddSingleton(identity);
        builder.Services.AddSingleton<BearerTokenInterceptor>();
        builder.Services.AddGrpc(grpc => grpc.Interceptors.Add<BearerTokenInterceptor>());

        var app = builder.Build();
        app.MapGrpcService<AutoCadHostService>();

        try
        {
            await app.StartAsync(cancellationToken);
            var server = app.Services.GetRequiredService<IServer>();
            var addresses = server.Features.Get<IServerAddressesFeature>()?.Addresses
                ?? throw new InvalidOperationException("Kestrel did not publish a bound address");
            var address = addresses
                .Select(value => Uri.TryCreate(value, UriKind.Absolute, out var parsed) ? parsed : null)
                .SingleOrDefault(uri => uri is not null && uri.Host == "127.0.0.1")
                ?? throw new InvalidOperationException("Kestrel did not bind the expected IPv4 loopback endpoint");

            if (address.Port is <= 0 or > 65535)
            {
                throw new InvalidOperationException($"Kestrel reported invalid dynamic port {address.Port}");
            }

            return new GrpcHostHandle(app, address);
        }
        catch
        {
            await app.DisposeAsync();
            throw;
        }
    }
}
