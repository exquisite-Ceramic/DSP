using System.Text.Json;
using HostContracts;

namespace AutoCAD.AgentHost.Execution;

/// <summary>
/// Rejects stale writes using the current HostCommand preconditions array.
/// A revision precondition is {"type":"revision","expected":N}.
/// </summary>
public sealed class RevisionGuard
{
    public ErrorShape? Validate(string documentId, HostCommand command)
    {
        if (command.Preconditions is not JsonElement preconditions
            || preconditions.ValueKind != JsonValueKind.Array)
        {
            return null;
        }

        foreach (var precondition in preconditions.EnumerateArray())
        {
            if (precondition.ValueKind != JsonValueKind.Object
                || !precondition.TryGetProperty("type", out var type)
                || type.GetString() != "revision"
                || !precondition.TryGetProperty("expected", out var expectedElement)
                || !expectedElement.TryGetInt64(out var expected))
            {
                continue;
            }

            var current = Native.AcNative.ActiveDocumentRevision();
            if (expected == current)
            {
                return null;
            }

            return new ErrorShape
            {
                ErrorCode = "REVISION_CONFLICT",
                Category = ErrorCategory.CONSISTENCY,
                Message = $"expected revision {expected}, current is {current}.",
                Retryable = RetryPolicy.AFTER_RECONSTRUCT,
                Details = JsonSerializer.SerializeToElement(
                    new[] { new { expected_revision = expected, actual_revision = current } },
                    ContractJson.Options),
            };
        }

        return null;
    }
}
