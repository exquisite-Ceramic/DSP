using Dsp.Host.Transport.V1;
using Google.Protobuf;
using Grpc.Core;

namespace AutoCAD.AgentHost.Grpc.Services;

/// <summary>Thin RPC adapter over the existing DSP contract JSON dispatch boundary.</summary>
internal sealed class AutoCadHostService : AutoCadHost.AutoCadHostBase
{
    private readonly IContractDispatchTarget _target;
    private readonly TransportIdentity _identity;

    public AutoCadHostService(IContractDispatchTarget target, TransportIdentity identity)
    {
        _target = target;
        _identity = identity;
    }

    public override Task<PingResponse> Ping(PingRequest request, ServerCallContext context)
    {
        context.CancellationToken.ThrowIfCancellationRequested();

        if (!string.IsNullOrEmpty(request.InstanceId)
            && !string.Equals(request.InstanceId, _identity.InstanceId, StringComparison.Ordinal))
        {
            throw new RpcException(new Status(
                StatusCode.FailedPrecondition,
                "requested instance_id does not match this host instance"));
        }

        return Task.FromResult(new PingResponse
        {
            InstanceId = _identity.InstanceId,
            ContractVersion = _identity.ContractVersion,
        });
    }

    public override async Task<DispatchResponse> Dispatch(DispatchRequest request, ServerCallContext context)
    {
        if (request.ContractJson.IsEmpty)
        {
            throw new RpcException(new Status(StatusCode.InvalidArgument, "contract_json is required"));
        }

        context.CancellationToken.ThrowIfCancellationRequested();
        var result = await _target.DispatchAsync(
            request.ContractJson.ToByteArray(),
            context.CancellationToken);

        return new DispatchResponse
        {
            ContractJson = ByteString.CopyFrom(result),
        };
    }
}
