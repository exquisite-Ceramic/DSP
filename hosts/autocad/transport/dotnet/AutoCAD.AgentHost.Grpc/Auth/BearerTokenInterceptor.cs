using System.Security.Cryptography;
using System.Text;
using Grpc.Core;
using Grpc.Core.Interceptors;

namespace AutoCAD.AgentHost.Grpc.Auth;

/// <summary>Rejects RPCs that do not present this host instance's bearer token.</summary>
public sealed class BearerTokenInterceptor : Interceptor
{
    private const string HeaderName = "authorization";
    private const string BearerPrefix = "Bearer ";
    private readonly byte[] _expectedToken;

    public BearerTokenInterceptor(TransportIdentity identity)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(identity.AuthToken);
        _expectedToken = Encoding.UTF8.GetBytes(identity.AuthToken);
    }

    public override async Task<TResponse> UnaryServerHandler<TRequest, TResponse>(
        TRequest request,
        ServerCallContext context,
        UnaryServerMethod<TRequest, TResponse> continuation)
    {
        Authenticate(context.RequestHeaders);
        return await continuation(request, context);
    }

    private void Authenticate(Metadata headers)
    {
        var authorizationEntries = headers
            .Where(entry => string.Equals(entry.Key, HeaderName, StringComparison.OrdinalIgnoreCase))
            .ToArray();

        if (authorizationEntries.Length != 1)
        {
            throw Unauthenticated();
        }

        var value = authorizationEntries[0].Value;
        if (!value.StartsWith(BearerPrefix, StringComparison.Ordinal))
        {
            throw Unauthenticated();
        }

        var suppliedToken = Encoding.UTF8.GetBytes(value[BearerPrefix.Length..]);
        var valid = suppliedToken.Length == _expectedToken.Length
            && CryptographicOperations.FixedTimeEquals(suppliedToken, _expectedToken);

        if (!valid)
        {
            throw Unauthenticated();
        }
    }

    private static RpcException Unauthenticated() =>
        new(new Status(StatusCode.Unauthenticated, "missing or invalid bearer token"));
}
