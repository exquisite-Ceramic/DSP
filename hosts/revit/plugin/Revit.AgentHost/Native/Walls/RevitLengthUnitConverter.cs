using Autodesk.Revit.DB;
using Revit.AgentHost.Core.Contracts;
using Revit.AgentHost.Core.Execution;

namespace Revit.AgentHost.Native.Walls;

public static class RevitLengthUnitConverter
{
    public static double MillimetersToInternal(double millimeters)
    {
        if (!double.IsFinite(millimeters))
        {
            throw new ArgumentOutOfRangeException(nameof(millimeters));
        }

        return UnitUtils.ConvertToInternalUnits(
            millimeters,
            UnitTypeId.Millimeters);
    }

    public static double InternalToMillimeters(double internalLength)
    {
        if (!double.IsFinite(internalLength))
        {
            throw new ArgumentOutOfRangeException(nameof(internalLength));
        }

        return UnitUtils.ConvertFromInternalUnits(
            internalLength,
            UnitTypeId.Millimeters);
    }
}

public sealed class RevitWallThicknessCandidate : IDisposable
{
    public RevitWallThicknessCandidate(
        WallThicknessPlan plan,
        CompoundStructure candidateStructure)
    {
        Plan = plan ?? throw new ArgumentNullException(nameof(plan));
        CandidateStructure = candidateStructure
            ?? throw new ArgumentNullException(nameof(candidateStructure));
    }

    public WallThicknessPlan Plan { get; }

    public CompoundStructure CandidateStructure { get; }

    public void Dispose()
    {
        CandidateStructure.Dispose();
    }
}

public sealed class RevitWallThicknessPlanBuilder
{
    public RevitWallThicknessCandidate Build(
        WallType wallType,
        double requestedMillimeters,
        double toleranceInternal)
    {
        ArgumentNullException.ThrowIfNull(wallType);

        CompoundStructure? structure = wallType.GetCompoundStructure();
        if (structure is null)
        {
            throw new WallThicknessPlanningException(
                WallThicknessPlanner.AmbiguousWallThicknessLayer,
                "The wall type does not provide a CompoundStructure.");
        }

        try
        {
            if (structure.IsVerticallyCompound)
            {
                throw new WallThicknessPlanningException(
                    WallThicknessPlanner.VerticallyCompoundWallUnsupported,
                    "Vertically compound walls are outside the supported MVP.");
            }

            IReadOnlyList<WallLayerSnapshot> snapshots = structure
                .GetLayers()
                .Select(
                    (layer, index) =>
                    {
                        bool isMembrane =
                            layer.Function == MaterialFunctionAssignment.Membrane;
                        return new WallLayerSnapshot(
                            index,
                            layer.Width,
                            isMembrane,
                            CanSetWidth: !isMembrane);
                    })
                .ToArray();

            double requestedTotalInternal =
                RevitLengthUnitConverter.MillimetersToInternal(
                    requestedMillimeters);

            WallThicknessPlan plan = WallThicknessPlanner.Plan(
                requestedTotalInternal,
                snapshots,
                toleranceInternal);

            structure.SetLayerWidth(
                plan.EditableLayerIndex,
                plan.NewEditableLayerWidthInternal);

            double candidateWidth = structure.GetWidth();
            if (!double.IsFinite(candidateWidth)
                || Math.Abs(candidateWidth - plan.RequestedTotalInternal)
                    > toleranceInternal)
            {
                throw new WallThicknessPlanningException(
                    WallThicknessPlanner.InvalidWallThickness,
                    "Candidate CompoundStructure width does not match the requested total within tolerance.");
            }

            return new RevitWallThicknessCandidate(plan, structure);
        }
        catch
        {
            structure.Dispose();
            throw;
        }
    }
}
