using Dsp.Host.Transport.V1;
using Google.Protobuf;
using Grpc.Core;
using Grpc.Net.Client;
using Xunit;

namespace AutoCAD.AgentHost.Grpc.Tests;

public class GrpcHostServerTests
{
    private const string ServiceName = "dsp.host.transport.v1.AutoCadHost";

    private static readonly global::AutoCAD.AgentHost.Grpc.TransportIdentity Identity =
        new("instance-test-001", "test-token-001", "1.0");

    private static readonly Method<PingRequest, PingResponse> PingMethod = new(
        MethodType.Unary,
        ServiceName,
        "Ping",
        Marshallers.Create<PingRequest>(value => value.ToByteArray(), data => PingRequest.Parser.ParseFrom(data)),
        Marshallers.Create<PingResponse>(value => value.ToByteArray(), data => PingResponse.Parser.ParseFrom(data)));

    private static readonly Method<DispatchRequest, DispatchResponse> DispatchMethod = new(
        MethodType.Unary,
        ServiceName,
        "Dispatch",
        Marshallers.Create<DispatchRequest>(value => value.ToByteArray(), data => DispatchRequest.Parser.ParseFrom(data)),
        Marshallers.Create<DispatchResponse>(value => value.ToByteArray(), data => DispatchResponse.Parser.ParseFrom(data)));

    [Fact]
    public async Task Ping_ReturnsIdentity_WithCorrectToken()
    {
        var target = new FakeDispatchTarget();
        await using var host = await global::AutoCAD.AgentHost.Grpc.GrpcHostServer.StartAsync(
            target,
            Identity,
            new global::AutoCAD.AgentHost.Grpc.GrpcHostOptions());
        using var channel = CreateChannel(host);

        var response = await Ping(
            channel,
            new PingRequest { InstanceId = Identity.InstanceId },
            AuthHeaders(Identity.AuthToken)).ResponseAsync;

        Assert.Equal(Identity.InstanceId, response.InstanceId);
        Assert.Equal(Identity.ContractVersion, response.ContractVersion);
    }

    [Fact]
    public async Task Ping_WithWrongInstance_IsFailedPrecondition()
    {
        var target = new FakeDispatchTarget();
        await using var host = await global::AutoCAD.AgentHost.Grpc.GrpcHostServer.StartAsync(
            target,
            Identity,
            new global::AutoCAD.AgentHost.Grpc.GrpcHostOptions());
        using var channel = CreateChannel(host);

        var error = await Assert.ThrowsAsync<RpcException>(async () =>
            await Ping(
                channel,
                new PingRequest { InstanceId = "other-instance" },
                AuthHeaders(Identity.AuthToken)).ResponseAsync);

        Assert.Equal(StatusCode.FailedPrecondition, error.StatusCode);
    }

    [Fact]
    public async Task MissingToken_IsUnauthenticated_AndDoesNotDispatch()
    {
        var target = new FakeDispatchTarget();
        await using var host = await global::AutoCAD.AgentHost.Grpc.GrpcHostServer.StartAsync(
            target,
            Identity,
            new global::AutoCAD.AgentHost.Grpc.GrpcHostOptions());
        using var channel = CreateChannel(host);

        var error = await Assert.ThrowsAsync<RpcException>(async () =>
            await Dispatch(
                channel,
                new DispatchRequest { ContractJson = ByteString.CopyFromUtf8("{}") }).ResponseAsync);

        Assert.Equal(StatusCode.Unauthenticated, error.StatusCode);
        Assert.Equal(0, target.InvocationCount);
    }

    [Fact]
    public async Task WrongToken_IsUnauthenticated_AndDoesNotDispatch()
    {
        var target = new FakeDispatchTarget();
        await using var host = await global::AutoCAD.AgentHost.Grpc.GrpcHostServer.StartAsync(
            target,
            Identity,
            new global::AutoCAD.AgentHost.Grpc.GrpcHostOptions());
        using var channel = CreateChannel(host);

        var error = await Assert.ThrowsAsync<RpcException>(async () =>
            await Dispatch(
                channel,
                new DispatchRequest { ContractJson = ByteString.CopyFromUtf8("{}") },
                AuthHeaders("wrong-token")).ResponseAsync);

        Assert.Equal(StatusCode.Unauthenticated, error.StatusCode);
        Assert.Equal(0, target.InvocationCount);
    }

    [Fact]
    public async Task EmptyContractJson_IsInvalidArgument()
    {
        var target = new FakeDispatchTarget();
        await using var host = await global::AutoCAD.AgentHost.Grpc.GrpcHostServer.StartAsync(
            target,
            Identity,
            new global::AutoCAD.AgentHost.Grpc.GrpcHostOptions());
        using var channel = CreateChannel(host);

        var error = await Assert.ThrowsAsync<RpcException>(async () =>
            await Dispatch(
                channel,
                new DispatchRequest(),
                AuthHeaders(Identity.AuthToken)).ResponseAsync);

        Assert.Equal(StatusCode.InvalidArgument, error.StatusCode);
        Assert.Equal(0, target.InvocationCount);
    }

    [Fact]
    public async Task Dispatch_PreservesBytesExactly()
    {
        var requestBytes = System.Text.Encoding.UTF8.GetBytes("{\"request_id\":\"r-1\",\"payload\":{\"x\":500}}");
        var responseBytes = System.Text.Encoding.UTF8.GetBytes("{\"request_id\":\"r-1\",\"status\":\"OK\"}");
        var target = new FakeDispatchTarget { ResponseBytes = responseBytes };
        await using var host = await global::AutoCAD.AgentHost.Grpc.GrpcHostServer.StartAsync(
            target,
            Identity,
            new global::AutoCAD.AgentHost.Grpc.GrpcHostOptions());
        using var channel = CreateChannel(host);

        var response = await Dispatch(
            channel,
            new DispatchRequest { ContractJson = ByteString.CopyFrom(requestBytes) },
            AuthHeaders(Identity.AuthToken)).ResponseAsync;

        Assert.Equal(requestBytes, target.LastRequestBytes);
        Assert.Equal(responseBytes, response.ContractJson.ToByteArray());
        Assert.Equal(1, target.InvocationCount);
    }

    [Fact]
    public async Task Cancellation_ReachesDispatchTarget()
    {
        var target = new FakeDispatchTarget { BlockUntilCancelled = true };
        await using var host = await global::AutoCAD.AgentHost.Grpc.GrpcHostServer.StartAsync(
            target,
            Identity,
            new global::AutoCAD.AgentHost.Grpc.GrpcHostOptions());
        using var channel = CreateChannel(host);
        using var cts = new CancellationTokenSource();

        var call = Dispatch(
            channel,
            new DispatchRequest { ContractJson = ByteString.CopyFromUtf8("{\"request_id\":\"r-cancel\"}") },
            AuthHeaders(Identity.AuthToken),
            cts.Token);

        await target.Entered.Task.WaitAsync(TimeSpan.FromSeconds(10));
        cts.Cancel();

        var error = await Assert.ThrowsAsync<RpcException>(async () => await call.ResponseAsync);
        Assert.Equal(StatusCode.Cancelled, error.StatusCode);
        await target.CancellationObserved.Task.WaitAsync(TimeSpan.FromSeconds(10));
    }

    [Fact]
    public async Task Host_BindsIpv4Loopback_OnDynamicPort()
    {
        var target = new FakeDispatchTarget();
        await using var host = await global::AutoCAD.AgentHost.Grpc.GrpcHostServer.StartAsync(
            target,
            Identity,
            new global::AutoCAD.AgentHost.Grpc.GrpcHostOptions(Host: "127.0.0.1", Port: 0));

        Assert.True(host.Port is > 0 and <= 65535);
        Assert.Equal("127.0.0.1", host.Address.Host);
        Assert.Equal(host.Port, host.Address.Port);
        Assert.Equal("http", host.Address.Scheme);
    }

    private static GrpcChannel CreateChannel(global::AutoCAD.AgentHost.Grpc.GrpcHostHandle host) =>
        GrpcChannel.ForAddress(host.Address);

    private static AsyncUnaryCall<PingResponse> Ping(
        GrpcChannel channel,
        PingRequest request,
        Metadata? headers = null,
        CancellationToken cancellationToken = default) =>
        channel.CreateCallInvoker().AsyncUnaryCall(
            PingMethod,
            string.Empty,
            new CallOptions(headers: headers, cancellationToken: cancellationToken),
            request);

    private static AsyncUnaryCall<DispatchResponse> Dispatch(
        GrpcChannel channel,
        DispatchRequest request,
        Metadata? headers = null,
        CancellationToken cancellationToken = default) =>
        channel.CreateCallInvoker().AsyncUnaryCall(
            DispatchMethod,
            string.Empty,
            new CallOptions(headers: headers, cancellationToken: cancellationToken),
            request);

    private static Metadata AuthHeaders(string token) =>
        new() { { "authorization", $"Bearer {token}" } };

    private sealed class FakeDispatchTarget : global::AutoCAD.AgentHost.Grpc.IContractDispatchTarget
    {
        private int _invocationCount;

        public int InvocationCount => Volatile.Read(ref _invocationCount);
        public byte[]? LastRequestBytes { get; private set; }
        public byte[] ResponseBytes { get; init; } = System.Text.Encoding.UTF8.GetBytes("{}");
        public bool BlockUntilCancelled { get; init; }
        public TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource CancellationObserved { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public async ValueTask<byte[]> DispatchAsync(byte[] contractJson, CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref _invocationCount);
            LastRequestBytes = contractJson.ToArray();
            Entered.TrySetResult();

            if (BlockUntilCancelled)
            {
                try
                {
                    await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
                }
                catch (OperationCanceledException)
                {
                    CancellationObserved.TrySetResult();
                    throw;
                }
            }

            return ResponseBytes;
        }
    }
}
