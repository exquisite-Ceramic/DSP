using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCAD.AgentHost.Native;

/// <summary>View-level wrappers: zoom / fit operations.</summary>
public static class AutoCADViewApi
{
    /// <summary>Zooms to the drawing extents (or to the given handles).</summary>
    public static void ZoomExtents(IReadOnlyCollection<string> handles)
    {
        var doc = Application.DocumentManager.MdiActiveDocument;
        if (doc is null)
        {
            return;
        }

        using var transaction = doc.Database.TransactionManager.StartTransaction();

        Extents3d extents;
        if (handles.Count == 0)
        {
            extents = doc.Database.Extents;
        }
        else
        {
            extents = new Extents3d();
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

                if (transaction.GetObject(id, OpenMode.ForRead) is Entity entity)
                {
                    extents.AddExtents(entity.GeometricExtents);
                }
            }
        }

        if (extents.IsNull)
        {
            transaction.Commit();
            return;
        }

        // Keep a small margin around the fit.
        var width = extents.MaxPoint.X - extents.MinPoint.X;
        var height = extents.MaxPoint.Y - extents.MinPoint.Y;
        var margin = Math.Max(width, height) * 0.05;
        extents.AddExtents(new Extents3d(
            extents.MinPoint + new Vector3d(-margin, -margin, 0),
            extents.MaxPoint + new Vector3d(margin, margin, 0)));

        using (doc.LockDocument())
        {
            doc.Editor.Zoom(extents);
        }

        transaction.Commit();
    }
}
