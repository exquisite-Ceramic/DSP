using System.Text.Json;
using HostContracts;

namespace AutoCAD.AgentHost.Commands.Interaction;

/// <summary>
/// Non-mutating Host Canvas interaction: prompt the designer for one point and
/// return only a provider-neutral numeric coordinate vector.
/// </summary>
public sealed class PickPointHandler : HostCommandHandler
{
    public override string CommandType => "interaction.pick_point";

    public override HostCommandResult Execute(HostCommand command)
    {
        string? prompt = null;
        if (command.Arguments is JsonElement arguments
            && arguments.ValueKind == JsonValueKind.Object
            && arguments.TryGetProperty("prompt", out var promptElement)
            && promptElement.ValueKind == JsonValueKind.String)
        {
            prompt = promptElement.GetString();
        }

        using var _ = Execution.DocumentLockManager.Acquire(Native.AcNative.ActiveDocumentId());
        var picked = Native.AutoCADInteractionApi.PickPoint(prompt);
        if (picked.Cancelled)
        {
            return new HostCommandResult
            {
                CommandId = command.CommandId,
                Status = ResultStatus.ERROR,
                Error = new ErrorShape
                {
                    ErrorCode = "INTERACTION_CANCELLED",
                    Category = ErrorCategory.EXECUTION,
                    Message = "The Host point interaction was cancelled.",
                    Retryable = RetryPolicy.NEVER,
                },
            };
        }

        var payload = JsonSerializer.SerializeToElement(new
        {
            point = new[] { picked.X, picked.Y, picked.Z },
        });

        return new HostCommandResult
        {
            CommandId = command.CommandId,
            Payload = payload,
        };
    }
}
