using System.Text.Json;
using HostContracts;

namespace AutoCAD.AgentHost.Commands.Model;

/// <summary>
/// Step34 Host mutation for the enterprise wall convention:
/// AutoCAD Polyline.ConstantWidth in millimetre drawings.
/// </summary>
public sealed class SetWallThicknessHandler : HostCommandHandler
{
    public override string CommandType => "set_wall_thickness.v1";

    public override HostCommandResult Execute(HostCommand command)
    {
        var handles = command.TargetNativeRefs
            .Select(reference => reference.NativeId)
            .Where(nativeId => !string.IsNullOrWhiteSpace(nativeId))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        if (handles.Length == 0)
        {
            throw new ArgumentException("set_wall_thickness.v1 requires at least one target native ref");
        }

        if (command.Arguments is not JsonElement arguments
            || arguments.ValueKind != JsonValueKind.Object
            || !arguments.TryGetProperty("thickness", out var thickness)
            || thickness.ValueKind != JsonValueKind.Object
            || !thickness.TryGetProperty("value", out var valueElement)
            || valueElement.ValueKind != JsonValueKind.Number
            || !valueElement.TryGetDouble(out var targetWidth)
            || !double.IsFinite(targetWidth)
            || targetWidth <= 0.0
            || !thickness.TryGetProperty("unit", out var unitElement)
            || unitElement.ValueKind != JsonValueKind.String
            || !string.Equals(unitElement.GetString(), "mm", StringComparison.Ordinal))
        {
            throw new ArgumentException(
                "arguments.thickness must be a positive finite measurement with unit 'mm'");
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
                    Message = "set_wall_thickness.v1 requires an AutoCAD document in millimetres",
                    Retryable = RetryPolicy.NEVER,
                },
            };
        }

        var (before, after) = Native.AutoCADEntityApi.SetConstantWidths(handles, targetWidth);
        var verification = Verification.WallThicknessVerifier.Verify(after, targetWidth);
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
            Payload = JsonSerializer.SerializeToElement(new
            {
                updated = handles.Length,
                beforeWidths = before,
                widths = after,
                unit = "mm",
            }),
            Verification = verification.ToDto(),
        };
    }
}
