using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using HostContracts;

namespace AutoCAD.AgentHost.Native;

/// <summary>Entity-level wrappers: selection, position reads, translation.</summary>
public static class AutoCADEntityApi
{
    public static IReadOnlyList<HostEntityRef> GetSelectedEntityRefs()
    {
        var doc = Application.DocumentManager.MdiActiveDocument;
        var selection = doc?.Editor.SelectImplied();
        if (selection is null || selection.Value.Status != PromptStatus.OK)
        {
            return Array.Empty<HostEntityRef>();
        }

        var refs = new List<HostEntityRef>();
        using var transaction = doc!.Database.TransactionManager.StartTransaction();
        foreach (var id in selection.Value.Value.GetObjectIds())
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
                Handle = entity.Handle.ToString(),
                ClassName = entity.GetType().Name,
                Layer = entity.Layer,
                DocumentId = doc.Name,
            });
        }

        transaction.Commit();
        return refs;
    }

    /// <summary>Resolves a handle to its entity, or null when missing/erased.</summary>
    public static Entity? GetEntityByHandle(string handle)
    {
        var doc = Application.DocumentManager.MdiActiveDocument;
        if (doc is null || !Handle.TryParse(handle, out var parsed))
        {
            return null;
        }

        using var transaction = doc.Database.TransactionManager.StartTransaction();
        var id = transaction.GetObjectId(true, parsed);
        var entity = id.IsValid && !id.IsErased
            ? transaction.GetObject(id, OpenMode.ForRead) as Entity
            : null;
        transaction.Commit();
        return entity;
    }

    /// <summary>Reads position payloads (handle → {x,y,z}) without mutation.</summary>
    public static Dictionary<string, System.Text.Json.JsonElement> ReadPositions(IEnumerable<string> handles)
    {
        var doc = Application.DocumentManager.MdiActiveDocument!;
        var result = new Dictionary<string, System.Text.Json.JsonElement>();

        using var transaction = doc.Database.TransactionManager.StartTransaction();
        foreach (var handle in handles)
        {
            if (!Handle.TryParse(handle, out var parsed))
            {
                continue;
            }

            var id = transaction.GetObjectId(true, parsed);
            if (!id.IsValid || id.IsErased)
            {
                continue;
            }

            var entity = transaction.GetObject(id, OpenMode.ForRead) as Entity;
            if (entity is null)
            {
                continue;
            }

            var (x, y, z) = entity is DBPoint point
                ? (point.Position.X, point.Position.Y, point.Position.Z)
                : (0.0, 0.0, 0.0);

            result[handle] = System.Text.Json.JsonSerializer.SerializeToElement(new { x, y, z });
        }

        transaction.Commit();
        return result;
    }

    /// <summary>Translates entities by (dx, dy, dz) inside the caller's transaction.</summary>
    public static void Translate(Database database, IEnumerable<string> handles, double dx, double dy, double dz)
    {
        foreach (var handle in handles)
        {
            if (!Handle.TryParse(handle, out var parsed))
            {
                continue;
            }

            using var transaction = database.TransactionManager.StartTransaction();
            var id = transaction.GetObjectId(true, parsed);
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

            var vector = new Vector3d(dx, dy, dz);
            entity.TransformBy(Matrix3d.Displacement(vector));
            transaction.Commit();
        }

        AutoCADDocumentApi.BumpRevision(database.Filename);
    }

    /// <summary>Describes a change event; null when not entity-related.</summary>
    public static (HostEntityRef EntityRef, System.Text.Json.JsonElement? Before, System.Text.Json.JsonElement? After)? DescribeChange(
        object sender, EventArgs args, string operation)
    {
        if (sender is not DBObject dbObject)
        {
            return null;
        }

        var entityRef = new HostEntityRef
        {
            Handle = dbObject.Handle.ToString(),
            ClassName = dbObject.GetType().Name,
        };

        // Reading full before/after snapshots is deferred to a later milestone;
        // the handle + operation already enables coarse tracking (spec §8).
        return (entityRef, null, null);
    }
}
