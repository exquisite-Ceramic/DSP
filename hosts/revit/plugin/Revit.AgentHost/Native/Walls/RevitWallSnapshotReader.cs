using System.Globalization;
using Autodesk.Revit.DB;
using Revit.AgentHost.Core.Contracts;

namespace Revit.AgentHost.Native.Walls;

public sealed record RevitWallSnapshot(
    string WallUniqueId,
    string WallTypeUniqueId,
    double WidthInternal,
    double WidthMillimeters,
    string LocationSignature,
    string RelationshipSignature);

public sealed class RevitWallSnapshotReader
{
    private readonly RevitWallTargetResolver targetResolver;
    private readonly RevitWallIsolationProbe isolationProbe;

    public RevitWallSnapshotReader(
        RevitWallTargetResolver? targetResolver = null,
        RevitWallIsolationProbe? isolationProbe = null)
    {
        this.targetResolver = targetResolver ?? new RevitWallTargetResolver();
        this.isolationProbe = isolationProbe ?? new RevitWallIsolationProbe(this.targetResolver);
    }

    public RevitWallSnapshot Read(Document document, HostCommandEnvelope command)
    {
        ArgumentNullException.ThrowIfNull(document);
        ArgumentNullException.ThrowIfNull(command);

        RevitWallTargetResolution resolution = targetResolver.Resolve(document, command);
        if (!resolution.TargetResolved || resolution.Wall is null)
        {
            throw new InvalidOperationException("TARGET_RESOLUTION_FAILED");
        }

        Wall wall = resolution.Wall;
        WallType wallType = wall.WallType;

        double widthInternal;
        CompoundStructure? structure = wallType.GetCompoundStructure();
        if (structure is null)
        {
            throw new InvalidOperationException("WALL_COMPOUND_STRUCTURE_UNAVAILABLE");
        }

        using (structure)
        {
            widthInternal = structure.GetWidth();
        }

        if (!double.IsFinite(widthInternal) || widthInternal <= 0.0)
        {
            throw new InvalidOperationException("WALL_WIDTH_READ_INVALID");
        }

        LocationCurve? locationCurve = wall.Location as LocationCurve;
        if (locationCurve is null)
        {
            throw new InvalidOperationException("WALL_LOCATION_UNAVAILABLE");
        }

        Curve curve = locationCurve.Curve;
        XYZ start = curve.GetEndPoint(0);
        XYZ end = curve.GetEndPoint(1);

        WallIsolationEvidence isolation = isolationProbe.Collect(document, command);

        return new RevitWallSnapshot(
            wall.UniqueId,
            wallType.UniqueId,
            widthInternal,
            RevitLengthUnitConverter.InternalToMillimeters(widthInternal),
            LocationSignature(curve, start, end),
            RelationshipSignature(isolation));
    }

    private static string LocationSignature(Curve curve, XYZ start, XYZ end)
    {
        return string.Join(
            "|",
            curve.GetType().FullName ?? curve.GetType().Name,
            Coordinate(start.X),
            Coordinate(start.Y),
            Coordinate(start.Z),
            Coordinate(end.X),
            Coordinate(end.Y),
            Coordinate(end.Z));
    }

    private static string RelationshipSignature(WallIsolationEvidence evidence)
    {
        return string.Join(
            ";",
            $"same-type={Join(evidence.SameTypeWallUniqueIds)}",
            $"inserts={Join(evidence.InsertUniqueIds)}",
            $"join-0={Join(evidence.JoinEnd0UniqueIds)}",
            $"join-1={Join(evidence.JoinEnd1UniqueIds)}",
            $"unsupported={Join(evidence.UnsupportedDependencyUniqueIds)}",
            $"associativity={evidence.AssociativityProven}");
    }

    private static string Join(IReadOnlyList<string> values)
    {
        return string.Join(",", values.OrderBy(value => value, StringComparer.Ordinal));
    }

    private static string Coordinate(double value)
    {
        return value.ToString("R", CultureInfo.InvariantCulture);
    }
}
