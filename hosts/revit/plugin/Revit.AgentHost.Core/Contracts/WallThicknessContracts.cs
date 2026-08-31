using System.Text.Json.Serialization;

namespace Revit.AgentHost.Core.Contracts;

public sealed record WallThicknessMeasurement(
    [property: JsonPropertyName("value")] double Value,
    [property: JsonPropertyName("unit")] string Unit);

public sealed record WallThicknessArguments(
    [property: JsonPropertyName("thickness")] WallThicknessMeasurement Thickness);
