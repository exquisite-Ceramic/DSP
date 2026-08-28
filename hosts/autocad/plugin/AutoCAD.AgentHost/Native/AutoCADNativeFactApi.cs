using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCAD.AgentHost.Native;

/// <summary>
/// Read-only AutoCAD-native entity snapshot extraction for Step 19.
/// This Host-local DTO intentionally carries no canonical semantic meaning.
/// </summary>
public static class AutoCADNativeFactApi
{
    private static readonly string HostInstanceId = $"autocad-{Guid.NewGuid():N}";

    public static object Extract(IReadOnlyList<string> handles)
    {
        ArgumentNullException.ThrowIfNull(handles);

        var doc = AutoCADDocumentApi.GetActiveDocument();
        var documentId = doc.Name;
        var revision = AcNative.ActiveDocumentRevision();

        var normalizedHandles = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var handle in handles)
        {
            if (string.IsNullOrWhiteSpace(handle))
            {
                throw new ArgumentException("handle must be a non-empty string", nameof(handles));
            }

            if (seen.Add(handle))
            {
                normalizedHandles.Add(handle);
            }
        }

        var entities = new List<Dictionary<string, object?>>();
        using var transaction = doc.Database.TransactionManager.StartTransaction();

        foreach (var handle in normalizedHandles)
        {
            if (!AutoCADEntityApi.TryResolveObjectId(doc.Database, handle, out var objectId)
                || !objectId.IsValid
                || objectId.IsNull
                || objectId.IsErased
                || objectId.IsEffectivelyErased)
            {
                throw new InvalidOperationException($"unable to resolve readable AutoCAD entity handle: {handle}");
            }

            var entity = transaction.GetObject(objectId, OpenMode.ForRead) as Entity
                ?? throw new InvalidOperationException($"unable to open AutoCAD entity for read: {handle}");

            var nativeKind = entity.GetRXClass().DxfName;
            if (string.IsNullOrWhiteSpace(nativeKind))
            {
                throw new InvalidOperationException($"AutoCAD entity has no native kind: {handle}");
            }

            if (string.IsNullOrWhiteSpace(entity.Layer))
            {
                throw new InvalidOperationException($"AutoCAD entity has no layer: {handle}");
            }

            var snapshot = new Dictionary<string, object?>
            {
                ["nativeId"] = entity.Handle.ToString(),
                ["nativeKind"] = nativeKind,
                ["layer"] = entity.Layer,
            };

            try
            {
                var extents = entity.GeometricExtents;
                snapshot["bounds"] = new
                {
                    min = new
                    {
                        x = extents.MinPoint.X,
                        y = extents.MinPoint.Y,
                        z = extents.MinPoint.Z,
                    },
                    max = new
                    {
                        x = extents.MaxPoint.X,
                        y = extents.MaxPoint.Y,
                        z = extents.MaxPoint.Z,
                    },
                };
            }
            catch
            {
                // Some valid AutoCAD entities do not expose geometric extents.
                // Identity and native classification evidence remain usable.
            }

            entities.Add(snapshot);
        }

        transaction.Commit();
        return new
        {
            hostInstanceId = HostInstanceId,
            documentId,
            revision,
            entities,
        };
    }
}
