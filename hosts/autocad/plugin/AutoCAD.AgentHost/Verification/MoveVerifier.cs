using System.Text.Json;

namespace AutoCAD.AgentHost.Verification;

/// <summary>
/// Verifies that a translate command moved every target by exactly the
/// requested delta (spec §9). Returns a structured report attached to the
/// command result.
/// </summary>
public sealed class MoveVerificationReport
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

public static class MoveVerifier
{
    public static MoveVerificationReport Verify(
        Dictionary<string, JsonElement> before,
        Dictionary<string, JsonElement> after,
        double dx, double dy, double dz)
    {
        var mismatches = new List<string>();

        foreach (var (handle, beforeEl) in before)
        {
            if (!after.TryGetValue(handle, out var afterEl))
            {
                mismatches.Add($"{handle}: missing after move");
                continue;
            }

            var (bx, by, bz) = ReadPosition(beforeEl);
            var (ax, ay, az) = ReadPosition(afterEl);
            const double tolerance = 1e-6;

            if (Math.Abs(ax - (bx + dx)) > tolerance ||
                Math.Abs(ay - (by + dy)) > tolerance ||
                Math.Abs(az - (bz + dz)) > tolerance)
            {
                mismatches.Add($"{handle}: expected ({bx + dx}, {by + dy}, {bz + dz}), got ({ax}, {ay}, {az})");
            }
        }

        if (mismatches.Count == 0)
        {
            return new MoveVerificationReport { Ok = true, Message = "all entities verified" };
        }

        return new MoveVerificationReport
        {
            Ok = false,
            Message = string.Join("; ", mismatches),
            Details = { ["mismatches"] = mismatches },
        };
    }

    private static (double X, double Y, double Z) ReadPosition(JsonElement element)
    {
        var x = element.TryGetProperty("x", out var xe) ? xe.GetDouble() : 0.0;
        var y = element.TryGetProperty("y", out var ye) ? ye.GetDouble() : 0.0;
        var z = element.TryGetProperty("z", out var ze) ? ze.GetDouble() : 0.0;
        return (x, y, z);
    }
}
