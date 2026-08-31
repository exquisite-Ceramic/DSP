using System.Text.Json;
using HostContracts;

namespace AutoCAD.AgentHost.Commands.Model;

/// <summary>
/// Step36 Host mutation: create exactly one native Polyline by offsetting one
/// source Polyline toward a caller-supplied side point.
/// </summary>
public sealed class OffsetHandler : HostCommandHandler
{
    public override string CommandType => "offset.v1";

    public override HostCommandResult Execute(HostCommand command)
    {
        if (command.TargetNativeRefs.Count != 1
            || string.IsNullOrWhiteSpace(command.TargetNativeRefs[0].NativeId))
        {
            return InvalidArgument("offset.v1 requires exactly one target native ref");
        }

        if (command.Arguments is not JsonElement arguments
            || arguments.ValueKind != JsonValueKind.Object
            || !TryReadMillimetreDistance(arguments, out var distanceMm)
            || !TryReadSidePoint(arguments, out var sideX, out var sideY, out var sideZ))
        {
            return InvalidArgument(
                "offset.v1 requires positive finite arguments.distance in 'mm' and finite arguments.sidePoint coordinates in 'mm'");
        }

        using var _ = Execution.DocumentLockManager.Acquire(Native.AcNative.ActiveDocumentId());

        if (!Native.AutoCADDocumentApi.IsActiveDocumentMillimeters())
        {
            return new HostCommandResult
            {
                Status = ResultStatus.ERROR,
                Error = new ErrorShape
                {
                    ErrorCode = "UNSUPPORTED_DOCUMENT_UNITS",
                    Category = ErrorCategory.EXECUTION,
                    Message = "offset.v1 requires an AutoCAD document in millimetres",
                    Retryable = RetryPolicy.NEVER,
                },
            };
        }

        Native.OffsetNativeResult nativeResult;
        try
        {
            nativeResult = Native.AutoCADEntityApi.OffsetPolyline(
                command.TargetNativeRefs[0].NativeId,
                distanceMm,
                sideX,
                sideY,
                sideZ);
        }
        catch (Native.OffsetNativeException ex)
        {
            return new HostCommandResult
            {
                Status = ResultStatus.ERROR,
                Error = new ErrorShape
                {
                    ErrorCode = ex.ErrorCode,
                    Category = ErrorCategory.EXECUTION,
                    Message = ex.Message,
                    Retryable = RetryPolicy.NEVER,
                },
            };
        }

        var verification = Verification.OffsetVerifier.Verify(nativeResult);
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
                    Details = JsonSerializer.SerializeToElement(
                        verification.Details,
                        ContractJson.Options),
                    Retryable = RetryPolicy.IMMEDIATE,
                },
                Verification = verification.ToDto(),
            };
        }

        return new HostCommandResult
        {
            Payload = JsonSerializer.SerializeToElement(
                new
                {
                    createdEntityRef = nativeResult.Created,
                },
                ContractJson.Options),
            Verification = verification.ToDto(),
        };
    }

    private static HostCommandResult InvalidArgument(string message) =>
        new()
        {
            Status = ResultStatus.ERROR,
            Error = new ErrorShape
            {
                ErrorCode = "INVALID_ARGUMENT",
                Category = ErrorCategory.EXECUTION,
                Message = message,
                Retryable = RetryPolicy.NEVER,
            },
        };

    private static bool TryReadMillimetreDistance(JsonElement arguments, out double distanceMm)
    {
        distanceMm = 0.0;
        return arguments.TryGetProperty("distance", out var distance)
            && distance.ValueKind == JsonValueKind.Object
            && distance.TryGetProperty("value", out var valueElement)
            && valueElement.ValueKind == JsonValueKind.Number
            && valueElement.TryGetDouble(out distanceMm)
            && double.IsFinite(distanceMm)
            && distanceMm > 0.0
            && distance.TryGetProperty("unit", out var unitElement)
            && unitElement.ValueKind == JsonValueKind.String
            && string.Equals(unitElement.GetString(), "mm", StringComparison.Ordinal);
    }

    private static bool TryReadSidePoint(
        JsonElement arguments,
        out double x,
        out double y,
        out double z)
    {
        x = 0.0;
        y = 0.0;
        z = 0.0;
        return arguments.TryGetProperty("sidePoint", out var sidePoint)
            && sidePoint.ValueKind == JsonValueKind.Object
            && sidePoint.TryGetProperty("x", out var xElement)
            && xElement.ValueKind == JsonValueKind.Number
            && xElement.TryGetDouble(out x)
            && double.IsFinite(x)
            && sidePoint.TryGetProperty("y", out var yElement)
            && yElement.ValueKind == JsonValueKind.Number
            && yElement.TryGetDouble(out y)
            && double.IsFinite(y)
            && sidePoint.TryGetProperty("z", out var zElement)
            && zElement.ValueKind == JsonValueKind.Number
            && zElement.TryGetDouble(out z)
            && double.IsFinite(z)
            && sidePoint.TryGetProperty("unit", out var unitElement)
            && unitElement.ValueKind == JsonValueKind.String
            && string.Equals(unitElement.GetString(), "mm", StringComparison.Ordinal);
    }
}