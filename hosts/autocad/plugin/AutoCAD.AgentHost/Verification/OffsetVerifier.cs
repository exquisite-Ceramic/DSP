using System.Text.Json;
using AutoCAD.AgentHost.Native;

namespace AutoCAD.AgentHost.Verification;

public sealed class OffsetVerificationReport
{
    public bool Ok { get; init; }

    public string Message { get; init; } = string.Empty;

    public Dictionary<string, object> Details { get; init; } = new();

    public JsonElement ToDto() => JsonSerializer.SerializeToElement(new
    {
        ok = Ok,
        message = Message,
        details = Details,
    });
}

public static class OffsetVerifier
{
    public static OffsetVerificationReport Verify(OffsetNativeResult result)
    {
        var mismatches = new List<string>();

        if (string.Equals(
                result.Source.NativeId,
                result.Created.NativeId,
                StringComparison.OrdinalIgnoreCase))
        {
            mismatches.Add("created entity ref must differ from source entity ref");
        }

        if (!BoundsEqual(result.SourceBoundsBefore, result.SourceBoundsAfter))
        {
            mismatches.Add("source bounds changed during offset creation");
        }

        if (!string.Equals(result.SourceLayer, result.CreatedLayer, StringComparison.Ordinal))
        {
            mismatches.Add(
                $"created layer mismatch: expected {result.SourceLayer}, got {result.CreatedLayer}");
        }

        if (mismatches.Count == 0)
        {
            return new OffsetVerificationReport
            {
                Ok = true,
                Message = "offset creation verified",
            };
        }

        return new OffsetVerificationReport
        {
            Ok = false,
            Message = string.Join("; ", mismatches),
            Details = { ["mismatches"] = mismatches },
        };
    }

    private static bool BoundsEqual(NativeBoundsSnapshot left, NativeBoundsSnapshot right) =>
        Math.Abs(left.MinX - right.MinX) <= 1e-6
        && Math.Abs(left.MinY - right.MinY) <= 1e-6
        && Math.Abs(left.MinZ - right.MinZ) <= 1e-6
        && Math.Abs(left.MaxX - right.MaxX) <= 1e-6
        && Math.Abs(left.MaxY - right.MaxY) <= 1e-6
        && Math.Abs(left.MaxZ - right.MaxZ) <= 1e-6;
}