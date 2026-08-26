using HostContracts;

namespace AutoCAD.AgentHost.Ipc;

/// <summary>
/// Turns a raw envelope JSON frame into a dispatched command and back into
/// a result envelope. Write commands are serialized through
/// DocumentLockManager inside the handlers (see Execution/*).
/// </summary>
public sealed class RequestDispatcher
{
    private readonly HostCommandHandlerRegistry _registry;
    private readonly IdempotencyStore _idempotency;
    private readonly RevisionGuard _revisionGuard;

    public RequestDispatcher(HostCommandHandlerRegistry registry, IdempotencyStore idempotency, RevisionGuard revisionGuard)
    {
        _registry = registry;
        _idempotency = idempotency;
        _revisionGuard = revisionGuard;
    }

    public byte[] Dispatch(byte[] frame)
    {
        try
        {
            var envelope = ContractSerializer.Deserialize<Envelope>(frame);
            var command = ContractSerializer.PayloadAs<HostCommand>(envelope);
            var result = Execute(command);
            var response = ContractSerializer.Wrap("result", envelope, result);
            return ContractSerializer.Serialize(response);
        }
        catch (Exception ex)
        {
            var error = new HostError { Code = "internal_error", Message = ex.Message, Retryable = false };
            var response = ContractSerializer.Wrap("error", null, error);
            return ContractSerializer.Serialize(response);
        }
    }

    private HostCommandResult Execute(HostCommand command)
    {
        var documentId = Native.AcNative.ActiveDocumentId();

        // Idempotency (ADR-003): replay returns the cached result without re-executing.
        if (!string.IsNullOrEmpty(command.IdempotencyKey))
        {
            var cached = _idempotency.TryGet(documentId, command.IdempotencyKey);
            if (cached is not null)
            {
                cached.Replayed = true;
                return cached;
            }
        }

        // Revision guard (spec §7): reject stale writes.
        var guardError = _revisionGuard.Validate(documentId, command);
        if (guardError is not null)
        {
            return new HostCommandResult
            {
                CommandId = command.CommandId,
                Ok = false,
                Error = guardError,
            };
        }

        var handler = _registry.Resolve(command.CommandType);
        var result = handler.Execute(command);
        result.CommandId = command.CommandId;
        result.Revision = Native.AcNative.ActiveDocumentRevision();

        if (!string.IsNullOrEmpty(command.IdempotencyKey))
        {
            _idempotency.Store(documentId, command.IdempotencyKey, result);
        }

        return result;
    }
}
