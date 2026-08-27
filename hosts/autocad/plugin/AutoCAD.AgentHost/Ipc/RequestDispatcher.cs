using AutoCAD.AgentHost.Commands;
using AutoCAD.AgentHost.Execution;
using HostContracts;

namespace AutoCAD.AgentHost.Ipc;

/// <summary>
/// Turns a RequestEnvelope frame into a dispatched HostCommand and returns a
/// ResponseEnvelope. Write commands are serialized through document locks in
/// the handlers.
/// </summary>
public sealed class RequestDispatcher
{
    private readonly HostCommandHandlerRegistry _registry;
    private readonly IdempotencyStore _idempotency;
    private readonly RevisionGuard _revisionGuard;

    public RequestDispatcher(
        HostCommandHandlerRegistry registry,
        IdempotencyStore idempotency,
        RevisionGuard revisionGuard)
    {
        _registry = registry;
        _idempotency = idempotency;
        _revisionGuard = revisionGuard;
    }

    public byte[] Dispatch(byte[] frame)
    {
        RequestEnvelope? request = null;
        try
        {
            request = ContractSerializer.DeserializeRequest(frame);
            var command = ContractSerializer.PayloadAs<HostCommand>(request);
            var result = Execute(command);
            return ContractSerializer.Serialize(ContractSerializer.WrapResult(request, result));
        }
        catch (Exception ex)
        {
            var error = new ErrorShape
            {
                ErrorCode = "INTERNAL_ERROR",
                Category = ErrorCategory.EXECUTION,
                Message = ex.Message,
                Retryable = RetryPolicy.NEVER,
            };
            return ContractSerializer.Serialize(ContractSerializer.WrapError(request, error));
        }
    }

    private HostCommandResult Execute(HostCommand command)
    {
        var documentId = Native.AcNative.ActiveDocumentId();

        if (!string.IsNullOrEmpty(command.IdempotencyKey))
        {
            var cached = _idempotency.TryGet(documentId, command.IdempotencyKey);
            if (cached is not null)
            {
                cached.Replayed = true;
                return cached;
            }
        }

        var guardError = _revisionGuard.Validate(documentId, command);
        if (guardError is not null)
        {
            return new HostCommandResult
            {
                CommandId = command.CommandId,
                Status = ResultStatus.ERROR,
                Error = guardError,
            };
        }

        var handler = _registry.Resolve(command.Operation);
        var result = handler.Execute(command);
        result.CommandId = command.CommandId;
        result.RevisionAfter = (int)Native.AcNative.ActiveDocumentRevision();

        if (!string.IsNullOrEmpty(command.IdempotencyKey))
        {
            _idempotency.Store(documentId, command.IdempotencyKey, result);
        }

        return result;
    }
}
