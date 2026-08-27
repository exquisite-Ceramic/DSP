using System.Globalization;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using HostContracts;

namespace AutoCAD.AgentHost.Native;

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
