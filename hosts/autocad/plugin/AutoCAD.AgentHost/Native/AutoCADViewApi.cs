using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

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

        var database = doc.Database;
        using var transaction = database.TransactionManager.StartTransaction();

        Point3d minPoint;
        Point3d maxPoint;

        if (handles.Count == 0)
        {
            minPoint = database.Extmin;
            maxPoint = database.Extmax;
        }
        else
        {
            Extents3d extents = default;
            var hasExtents = false;

            foreach (var handle in handles)
            {
                if (!AutoCADEntityApi.TryResolveObjectId(database, handle, out var id)
                    || !id.IsValid
                    || id.IsErased)
                {
                    continue;
                }

                if (transaction.GetObject(id, OpenMode.ForRead) is not Entity entity)
                {
                    continue;
                }

                if (!hasExtents)
                {
                    extents = entity.GeometricExtents;
                    hasExtents = true;
                }
                else
                {
                    extents.AddExtents(entity.GeometricExtents);
                }
            }

            if (!hasExtents)
            {
                transaction.Commit();
                return;
            }

            minPoint = extents.MinPoint;
            maxPoint = extents.MaxPoint;
        }

        transaction.Commit();

        var width = Math.Max(maxPoint.X - minPoint.X, 1e-6);
        var height = Math.Max(maxPoint.Y - minPoint.Y, 1e-6);
        const double marginScale = 1.10;

        using var view = doc.Editor.GetCurrentView();
        view.CenterPoint = new Point2d(
            (minPoint.X + maxPoint.X) / 2.0,
            (minPoint.Y + maxPoint.Y) / 2.0);
        view.Width = width * marginScale;
        view.Height = height * marginScale;

        using (doc.LockDocument())
        {
            doc.Editor.SetCurrentView(view);
        }
    }
}
