using Revit.AgentHost.Core.Contracts;

namespace Revit.AgentHost.Core.Execution;

public sealed record WallThicknessPlan(
    int EditableLayerIndex,
    double RequestedTotalInternal,
    double NewEditableLayerWidthInternal);

public sealed class WallThicknessPlanningException : InvalidOperationException
{
    public WallThicknessPlanningException(string code, string message)
        : base(message)
    {
        Code = code;
    }

    public string Code { get; }
}

public static class WallThicknessPlanner
{
    public const string VerticallyCompoundWallUnsupported = "VERTICALLY_COMPOUND_WALL_UNSUPPORTED";
    public const string AmbiguousWallThicknessLayer = "AMBIGUOUS_WALL_THICKNESS_LAYER";
    public const string InvalidWallThickness = "INVALID_WALL_THICKNESS";

    public static WallThicknessPlan Plan(
        double requestedTotalInternal,
        IReadOnlyList<WallLayerSnapshot> layers,
        double tolerance)
    {
        ArgumentNullException.ThrowIfNull(layers);

        if (!double.IsFinite(requestedTotalInternal)
            || requestedTotalInternal <= 0.0
            || !double.IsFinite(tolerance)
            || tolerance < 0.0)
        {
            throw Invalid("Requested total and tolerance must be finite, with a positive total and non-negative tolerance.");
        }

        foreach (WallLayerSnapshot layer in layers)
        {
            if (layer.LayerIndex < 0
                || !double.IsFinite(layer.WidthInternal)
                || layer.WidthInternal < 0.0)
            {
                throw Invalid("Layer widths must be finite and non-negative, with non-negative native indices.");
            }
        }

        WallLayerSnapshot[] editableLayers = layers
            .Where(layer => !layer.IsMembrane && layer.CanSetWidth)
            .ToArray();

        if (editableLayers.Length != 1)
        {
            throw new WallThicknessPlanningException(
                AmbiguousWallThicknessLayer,
                "Exactly one editable non-membrane wall layer is required.");
        }

        WallLayerSnapshot editable = editableLayers[0];
        double fixedSum = 0.0;
        foreach (WallLayerSnapshot layer in layers)
        {
            if (layer.LayerIndex == editable.LayerIndex)
            {
                continue;
            }

            fixedSum += layer.WidthInternal;
            if (!double.IsFinite(fixedSum))
            {
                throw Invalid("The fixed wall-layer width sum is not finite.");
            }
        }

        if (requestedTotalInternal <= fixedSum)
        {
            throw Invalid("Requested wall thickness must exceed the fixed wall-layer width sum.");
        }

        double newEditableWidth = requestedTotalInternal - fixedSum;
        if (!double.IsFinite(newEditableWidth) || newEditableWidth <= 0.0)
        {
            throw Invalid("Calculated editable wall-layer width must be finite and positive.");
        }

        double reconstructedTotal = fixedSum + newEditableWidth;
        if (!double.IsFinite(reconstructedTotal)
            || Math.Abs(reconstructedTotal - requestedTotalInternal) > tolerance)
        {
            throw Invalid("Planned wall-layer widths do not reconstruct the requested total within tolerance.");
        }

        return new WallThicknessPlan(
            editable.LayerIndex,
            requestedTotalInternal,
            newEditableWidth);
    }

    private static WallThicknessPlanningException Invalid(string message)
    {
        return new WallThicknessPlanningException(InvalidWallThickness, message);
    }
}
