using System.Text.Json;

namespace AutoCAD.AgentHost.Verification;

public sealed class WallThicknessVerificationReport
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

public static class WallThicknessVerifier
{
    public static WallThicknessVerificationReport Verify(
        IReadOnlyDictionary<string, double> after,
        double expectedWidth)
    {
        var mismatches = new List<string>();
        foreach (var (handle, actualWidth) in after)
        {
            if (Math.Abs(actualWidth - expectedWidth) > 1e-6)
            {
                mismatches.Add($"{handle}: expected {expectedWidth} mm, got {actualWidth} mm");
            }
        }

        if (mismatches.Count == 0)
        {
            return new WallThicknessVerificationReport
            {
                Ok = true,
                Message = "all wall thickness targets verified",
            };
        }

        return new WallThicknessVerificationReport
        {
            Ok = false,
            Message = string.Join("; ", mismatches),
            Details = { ["mismatches"] = mismatches },
        };
    }
}
