namespace Revit.AgentHost.Core.Contracts;

public sealed record WallLayerSnapshot(
    int LayerIndex,
    double WidthInternal,
    bool IsMembrane,
    bool CanSetWidth);
