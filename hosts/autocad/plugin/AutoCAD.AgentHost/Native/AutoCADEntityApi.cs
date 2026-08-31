using System.Globalization;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using HostContracts;

namespace AutoCAD.AgentHost.Native;

public sealed record NativeBoundsSnapshot(
    double MinX,
    double MinY,
    double MinZ,
    double MaxX,
    double MaxY,
    double MaxZ);

public sealed record OffsetNativeResult(
    HostEntityRef Source,
    HostEntityRef Created,
    NativeBoundsSnapshot SourceBoundsBefore,
    NativeBoundsSnapshot SourceBoundsAfter,
    string SourceLayer,
    string CreatedLayer);

public sealed class OffsetNativeException : InvalidOperationException
{
    public OffsetNativeException(string errorCode, string message)
        : base(message)
    {
        ErrorCode = errorCode;
    }

    public string ErrorCode { get; }
}

/// <summary>Entity-level wrappers: selection, position reads, translation.</summary>
public static class AutoCADEntityApi
{
    public static IReadOnlyList<HostEntityRef> GetSelectedEntityRefs()
    {
        var doc = Application.DocumentManager.MdiActiveDocument;
        if (doc is null)
        {
            return Array.Empty<HostEntityRef>();
        }

        var selection = doc.Editor.SelectImplied();
        if (selection.Status != PromptStatus.OK)
        {
            return Array.Empty<HostEntityRef>();
        }

        var refs = new List<HostEntityRef>();
        using var transaction = doc.Database.TransactionManager.StartTransaction();
        foreach (var id in selection.Value.GetObjectIds())
        {
            if (id.IsErased || id.IsEffectivelyErased)
            {
                continue;
            }

            var entity = transaction.GetObject(id, OpenMode.ForRead) as Entity;
            if (entity is null)
            {
                continue;
            }

            refs.Add(new HostEntityRef
            {
                DocumentId = doc.Name,
                NativeId = entity.Handle.ToString(),
                NativeType = entity.GetType().Name,
            });
        }

        transaction.Commit();
        return refs;
    }

    public static Entity? GetEntityByHandle(string handle)
    {
        var doc = Application.DocumentManager.MdiActiveDocument;
        if (doc is null || !TryResolveObjectId(doc.Database, handle, out var id))
        {
            return null;
        }

        using var transaction = doc.Database.TransactionManager.StartTransaction();
        var entity = id.IsValid && !id.IsErased
            ? transaction.GetObject(id, OpenMode.ForRead) as Entity
            : null;
        transaction.Commit();
        return entity;
    }

    public static Dictionary<string, System.Text.Json.JsonElement> ReadPositions(IEnumerable<string> handles)
    {
        var doc = Application.DocumentManager.MdiActiveDocument!;
        var result = new Dictionary<string, System.Text.Json.JsonElement>();

        using var transaction = doc.Database.TransactionManager.StartTransaction();
        foreach (var handle in handles)
        {
            if (!TryResolveObjectId(doc.Database, handle, out var id)
                || !id.IsValid
                || id.IsErased)
            {
                continue;
            }

            var entity = transaction.GetObject(id, OpenMode.ForRead) as Entity;
            if (entity is null)
            {
                continue;
            }

            double x;
            double y;
            double z;
            if (entity is DBPoint point)
            {
                x = point.Position.X;
                y = point.Position.Y;
                z = point.Position.Z;
            }
            else
            {
                var extents = entity.GeometricExtents;
                var min = extents.MinPoint;
                var max = extents.MaxPoint;
                x = (min.X + max.X) / 2.0;
                y = (min.Y + max.Y) / 2.0;
                z = (min.Z + max.Z) / 2.0;
            }

            result[handle] = System.Text.Json.JsonSerializer.SerializeToElement(new { x, y, z });
        }

        transaction.Commit();
        return result;
    }

    public static void Translate(IEnumerable<string> handles, double dx, double dy, double dz)
    {
        var doc = Application.DocumentManager.MdiActiveDocument
            ?? throw new InvalidOperationException("no active document.");
        Translate(doc.Database, handles, dx, dy, dz);
        AutoCADDocumentApi.BumpRevision(doc.Name);
    }

    public static void Translate(Database database, IEnumerable<string> handles, double dx, double dy, double dz)
    {
        foreach (var handle in handles)
        {
            if (!TryResolveObjectId(database, handle, out var id))
            {
                continue;
            }

            using var transaction = database.TransactionManager.StartTransaction();
            if (!id.IsValid || id.IsErased)
            {
                transaction.Commit();
                continue;
            }

            var entity = transaction.GetObject(id, OpenMode.ForWrite) as Entity;
            if (entity is null)
            {
                transaction.Commit();
                continue;
            }

            entity.TransformBy(Matrix3d.Displacement(new Vector3d(dx, dy, dz)));
            transaction.Commit();
        }
    }

    public static (Dictionary<string, double> Before, Dictionary<string, double> After) SetConstantWidths(
        IEnumerable<string> handles,
        double targetWidth)
    {
        if (!double.IsFinite(targetWidth) || targetWidth <= 0.0)
        {
            throw new ArgumentOutOfRangeException(nameof(targetWidth), "target width must be finite and positive");
        }

        var doc = Application.DocumentManager.MdiActiveDocument
            ?? throw new InvalidOperationException("no active document.");
        if (doc.Database.Insunits != UnitsValue.Millimeters)
        {
            throw new InvalidOperationException("set_wall_thickness.v1 requires an AutoCAD document in millimetres");
        }

        var targets = handles
            .Where(handle => !string.IsNullOrWhiteSpace(handle))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        if (targets.Length == 0)
        {
            throw new ArgumentException("at least one target handle is required", nameof(handles));
        }

        var before = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
        var after = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
        using var transaction = doc.Database.TransactionManager.StartTransaction();

        foreach (var handle in targets)
        {
            if (!TryResolveObjectId(doc.Database, handle, out var id)
                || !id.IsValid
                || id.IsNull
                || id.IsErased
                || id.IsEffectivelyErased)
            {
                throw new InvalidOperationException($"unable to resolve writable AutoCAD entity handle: {handle}");
            }

            var polyline = transaction.GetObject(id, OpenMode.ForWrite) as Polyline
                ?? throw new InvalidOperationException($"wall thickness target must be an AutoCAD Polyline: {handle}");

            before[handle] = polyline.ConstantWidth;
            polyline.ConstantWidth = targetWidth;
            after[handle] = polyline.ConstantWidth;

            if (Math.Abs(after[handle] - targetWidth) > 1e-6)
            {
                throw new InvalidOperationException(
                    $"native ConstantWidth postcondition failed for {handle}: expected {targetWidth}, got {after[handle]}");
            }
        }

        transaction.Commit();
        AutoCADDocumentApi.BumpRevision(doc.Name);
        return (before, after);
    }

    public static OffsetNativeResult OffsetPolyline(
        string handle,
        double distanceMm,
        double sideX,
        double sideY,
        double sideZ) =>
        OffsetPolyline(handle, distanceMm, new Point3d(sideX, sideY, sideZ));

    public static OffsetNativeResult OffsetPolyline(string handle, double distanceMm, Point3d sidePoint)
    {
        if (string.IsNullOrWhiteSpace(handle))
        {
            throw new ArgumentException("offset target handle is required", nameof(handle));
        }

        if (!double.IsFinite(distanceMm) || distanceMm <= 0.0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(distanceMm),
                "offset distance must be finite and positive");
        }

        if (!double.IsFinite(sidePoint.X)
            || !double.IsFinite(sidePoint.Y)
            || !double.IsFinite(sidePoint.Z))
        {
            throw new ArgumentException("offset side point must contain finite coordinates", nameof(sidePoint));
        }

        var doc = Application.DocumentManager.MdiActiveDocument
            ?? throw new InvalidOperationException("no active document.");
        if (doc.Database.Insunits != UnitsValue.Millimeters)
        {
            throw new InvalidOperationException("offset.v1 requires an AutoCAD document in millimetres");
        }

        if (!TryResolveObjectId(doc.Database, handle, out var id)
            || !id.IsValid
            || id.IsNull
            || id.IsErased
            || id.IsEffectivelyErased)
        {
            throw new OffsetNativeException(
                "OFFSET_TARGET_NOT_FOUND",
                $"unable to resolve AutoCAD offset target handle: {handle}");
        }

        DBObjectCollection? positiveObjects = null;
        DBObjectCollection? negativeObjects = null;
        Polyline? selected = null;
        var selectedOwnedByTransaction = false;

        try
        {
            using var transaction = doc.Database.TransactionManager.StartTransaction();
            var source = transaction.GetObject(id, OpenMode.ForRead) as Polyline
                ?? throw new OffsetNativeException(
                    "OFFSET_TARGET_UNSUPPORTED",
                    $"offset.v1 target must be an AutoCAD Polyline: {handle}");

            var sourceBoundsBefore = SnapshotBounds(source.GeometricExtents);
            var sourceLayer = source.Layer;

            positiveObjects = source.GetOffsetCurves(distanceMm);
            negativeObjects = source.GetOffsetCurves(-distanceMm);
            var positive = RequireSinglePolyline(positiveObjects, "+distance");
            var negative = RequireSinglePolyline(negativeObjects, "-distance");

            var positiveDistance = DistanceToSidePoint(positive, sidePoint);
            var negativeDistance = DistanceToSidePoint(negative, sidePoint);
            if (Math.Abs(positiveDistance - negativeDistance) <= 1e-6)
            {
                throw new OffsetNativeException(
                    "OFFSET_SIDE_AMBIGUOUS",
                    "offset side point is equidistant from the positive and negative offset candidates");
            }

            selected = positiveDistance < negativeDistance ? positive : negative;
            selected.Layer = sourceLayer;

            var owner = transaction.GetObject(source.OwnerId, OpenMode.ForWrite) as BlockTableRecord
                ?? throw new OffsetNativeException(
                    "OFFSET_OWNER_UNSUPPORTED",
                    $"unable to resolve owner BlockTableRecord for offset target: {handle}");
            owner.AppendEntity(selected);
            transaction.AddNewlyCreatedDBObject(selected, true);
            selectedOwnedByTransaction = true;

            var sourceBoundsAfter = SnapshotBounds(source.GeometricExtents);
            if (!BoundsEqual(sourceBoundsBefore, sourceBoundsAfter))
            {
                throw new OffsetNativeException(
                    "OFFSET_SOURCE_CHANGED",
                    $"offset.v1 mutated source geometry for handle: {handle}");
            }

            if (!string.Equals(selected.Layer, sourceLayer, StringComparison.Ordinal))
            {
                throw new OffsetNativeException(
                    "OFFSET_CREATED_LAYER_MISMATCH",
                    $"offset.v1 created entity on unexpected layer: {selected.Layer}");
            }

            var sourceRef = new HostEntityRef
            {
                DocumentId = doc.Name,
                NativeId = source.Handle.ToString(),
                NativeType = source.GetType().Name,
            };
            var createdRef = new HostEntityRef
            {
                DocumentId = doc.Name,
                NativeId = selected.Handle.ToString(),
                NativeType = selected.GetType().Name,
            };

            transaction.Commit();
            AutoCADDocumentApi.BumpRevision(doc.Name);

            return new OffsetNativeResult(
                sourceRef,
                createdRef,
                sourceBoundsBefore,
                sourceBoundsAfter,
                sourceLayer,
                selected.Layer);
        }
        finally
        {
            DisposeTransientOffsetObjects(positiveObjects, selected, selectedOwnedByTransaction);
            DisposeTransientOffsetObjects(negativeObjects, selected, selectedOwnedByTransaction);
        }
    }

    private static Polyline RequireSinglePolyline(DBObjectCollection objects, string candidateLabel)
    {
        if (objects.Count != 1 || objects[0] is not Polyline polyline)
        {
            throw new OffsetNativeException(
                "OFFSET_RESULT_UNSUPPORTED",
                $"offset {candidateLabel} must produce exactly one AutoCAD Polyline");
        }

        return polyline;
    }

    private static double DistanceToSidePoint(Polyline candidate, Point3d sidePoint) =>
        candidate.GetClosestPointTo(sidePoint, false).DistanceTo(sidePoint);

    private static NativeBoundsSnapshot SnapshotBounds(Extents3d extents) =>
        new(
            extents.MinPoint.X,
            extents.MinPoint.Y,
            extents.MinPoint.Z,
            extents.MaxPoint.X,
            extents.MaxPoint.Y,
            extents.MaxPoint.Z);

    private static bool BoundsEqual(NativeBoundsSnapshot left, NativeBoundsSnapshot right) =>
        Math.Abs(left.MinX - right.MinX) <= 1e-6
        && Math.Abs(left.MinY - right.MinY) <= 1e-6
        && Math.Abs(left.MinZ - right.MinZ) <= 1e-6
        && Math.Abs(left.MaxX - right.MaxX) <= 1e-6
        && Math.Abs(left.MaxY - right.MaxY) <= 1e-6
        && Math.Abs(left.MaxZ - right.MaxZ) <= 1e-6;

    private static void DisposeTransientOffsetObjects(
        DBObjectCollection? objects,
        Polyline? selected,
        bool selectedOwnedByTransaction)
    {
        if (objects is null)
        {
            return;
        }

        for (var index = 0; index < objects.Count; index++)
        {
            var dbObject = objects[index];
            if (selectedOwnedByTransaction && ReferenceEquals(dbObject, selected))
            {
                continue;
            }

            dbObject.Dispose();
        }
    }

    internal static bool TryResolveObjectId(Database database, string nativeId, out ObjectId objectId)
    {
        objectId = ObjectId.Null;
        if (!long.TryParse(
                nativeId,
                NumberStyles.HexNumber,
                CultureInfo.InvariantCulture,
                out var raw))
        {
            return false;
        }

        try
        {
            objectId = database.GetObjectId(false, new Handle(raw), 0);
            return objectId.IsValid && !objectId.IsNull;
        }
        catch
        {
            objectId = ObjectId.Null;
            return false;
        }
    }

    public static (HostEntityRef EntityRef, System.Text.Json.JsonElement? Before, System.Text.Json.JsonElement? After)? DescribeChange(
        object? sender, EventArgs args, string operation)
    {
        if (sender is not DBObject dbObject)
        {
            return null;
        }

        var entityRef = new HostEntityRef
        {
            DocumentId = AcNative.ActiveDocumentId(),
            NativeId = dbObject.Handle.ToString(),
            NativeType = dbObject.GetType().Name,
        };

        return (entityRef, null, null);
    }
}