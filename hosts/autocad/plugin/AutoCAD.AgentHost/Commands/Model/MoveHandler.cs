using System.Text.Json;
using HostContracts;

namespace AutoCAD.AgentHost.Commands.Model;

/// <summary>
/// Write command: translates entities by a displacement, verifies afterwards,
/// and returns a current HostCommandResult.
/// </summary>
public sealed class MoveHandler : HostCommandHandler
{
    public override string CommandType => "move.v1";

    public override HostCommandResult Execute(HostCommand command)
    {
        var handles = command.TargetNativeRefs
            .Select(reference => reference.NativeId)
            .Where(nativeId => !string.IsNullOrWhiteSpace(nativeId))
            .ToArray();
        var dx = 0.0;
        var dy = 0.0;
        var dz = 0.0;

        if (command.Arguments is JsonElement arguments
            && arguments.ValueKind == JsonValueKind.Object)
        {
            if (handles.Length == 0 && arguments.TryGetProperty("handles", out var handleElement))
            {
                handles = handleElement.Deserialize<string[]>() ?? Array.Empty<string>();
            }

            if (arguments.TryGetProperty("displacement", out var displacement)
                && displacement.ValueKind == JsonValueKind.Object)
            {
                dx = displacement.TryGetProperty("x", out var x) ? x.GetDouble() : 0.0;
                dy = displacement.TryGetProperty("y", out var y) ? y.GetDouble() : 0.0;
                dz = displacement.TryGetProperty("z", out var z) ? z.GetDouble() : 0.0;
            }
            else
            {
                dx = arguments.TryGetProperty("dx", out var x) ? x.GetDouble() : 0.0;
                dy = arguments.TryGetProperty("dy", out var y) ? y.GetDouble() : 0.0;
                dz = arguments.TryGetProperty("dz", out var z) ? z.GetDouble() : 0.0;
            }
        }

        using var _ = Execution.DocumentLockManager.Acquire(Native.AcNative.ActiveDocumentId());

        var before = Native.AutoCADEntityApi.ReadPositions(handles);
        Execution.TransactionRunner.Run(db =>
        {
            Native.AutoCADEntityApi.Translate(db, handles, dx, dy, dz);
        });
        var after = Native.AutoCADEntityApi.ReadPositions(handles);

        var verification = Verification.MoveVerifier.Verify(before, after, dx, dy, dz);
        if (!verification.Ok)
        {
            return new HostCommandResult
            {
                Status = ResultStatus.ERROR,
                Error = new ErrorShape
                {
                    ErrorCode = "VERIFICATION_FAILED",
                    Category = ErrorCategory.EXECUTION,
                    Message = verification.Message,
                    Details = JsonSerializer.SerializeToElement(verification.Details, ContractJson.Options),
                    Retryable = RetryPolicy.IMMEDIATE,
                },
                Verification = verification.ToDto(),
            };
        }

        var payload = JsonSerializer.SerializeToElement(new
        {
            moved = handles.Length,
            positions = after,
        });

        return new HostCommandResult
        {
            Payload = payload,
            Verification = verification.ToDto(),
        };
    }
}
