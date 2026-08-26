using System.Text.Json;
using HostContracts;

namespace AutoCAD.AgentHost.Commands.Model;

/// <summary>
/// Write command: translates entities by (dx, dy[, dz]).
/// Executes inside a transaction + document lock, verifies afterwards,
/// and records the idempotency key through the dispatcher (ADR-003).
/// </summary>
public sealed class MoveHandler : HostCommandHandler
{
    public override string CommandType => "model.move";

    public override HostCommandResult Execute(HostCommand command)
    {
        var handles = command.Params.TryGetProperty("handles", out var h)
            ? h.Deserialize<string[]>() ?? Array.Empty<string>()
            : Array.Empty<string>();
        var dx = command.Params.TryGetProperty("dx", out var dxEl) ? dxEl.GetDouble() : 0.0;
        var dy = command.Params.TryGetProperty("dy", out var dyEl) ? dyEl.GetDouble() : 0.0;
        var dz = command.Params.TryGetProperty("dz", out var dzEl) ? dzEl.GetDouble() : 0.0;

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
                Ok = false,
                Error = new HostError
                {
                    Code = "verification_failed",
                    Message = verification.Message,
                    Details = JsonSerializer.SerializeToElement(verification.Details),
                    Retryable = true,
                },
            };
        }

        var payload = JsonSerializer.SerializeToElement(new
        {
            moved = handles.Length,
            positions = after,
        });

        return new HostCommandResult
        {
            Ok = true,
            Payload = payload,
            Verification = JsonSerializer.SerializeToElement(verification.ToDto()),
        };
    }
}
