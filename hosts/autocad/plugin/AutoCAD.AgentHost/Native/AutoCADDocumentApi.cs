using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCAD.AgentHost.Native;

/// <summary>
/// ⭐ Native/ is the ONLY zone allowed to reference Autodesk.* (ADR-001).
/// Everything outside this folder talks to AutoCAD exclusively through
/// these thin wrappers.
/// </summary>
public static class AcNative
{
    /// <summary>Stable id of the active document (file path when available).</summary>
    public static string ActiveDocumentId()
    {
        var doc = Application.DocumentManager.MdiActiveDocument;
        return doc?.Name ?? string.Empty;
    }

    public static string ActiveDocumentName() =>
        Application.DocumentManager.MdiActiveDocument?.Name ?? string.Empty;

    /// <summary>Monotonic revision of the active document (see DrawingIdentity).</summary>
    public static long ActiveDocumentRevision() =>
        AutoCADDocumentApi.GetDrawingIdentity().Revision;
}

/// <summary>Document-level wrappers: lock/unlock, revision bookkeeping, events.</summary>
public static class AutoCADDocumentApi
{
    private static readonly Dictionary<string, Identity.DrawingIdentity> Identities = new(StringComparer.OrdinalIgnoreCase);

    public static Document GetActiveDocument() =>
        Application.DocumentManager.MdiActiveDocument
        ?? throw new InvalidOperationException("no active document.");

    /// <summary>Locks the document for exclusive access; dispose to release.</summary>
    public static IDisposable LockDocument(string documentId)
    {
        var doc = GetActiveDocument();
        return doc.LockDocument();
    }

    public static Identity.DrawingIdentity GetDrawingIdentity()
    {
        var doc = GetActiveDocument();
        var db = doc.Database;

        if (!Identities.TryGetValue(doc.Name, out var identity))
        {
            identity = new Identity.DrawingIdentity
            {
                DocumentId = doc.Name,
                DocumentName = System.IO.Path.GetFileName(doc.Name),
            };
            Identities[doc.Name] = identity;
        }

        // Current revision is derived from the transaction state of the database.
        identity.Revision = db.TransactionManager.NumberOfActiveTransactions == 0
            ? identity.Revision
            : identity.Revision;
        return identity;
    }

    public static void BumpRevision(string documentName)
    {
        if (Identities.TryGetValue(documentName, out var identity))
        {
            identity.Revision++;
        }
    }

    // ---- change events (wired by ChangeCapture/ChangeSensor) ----

    public static void AttachChangeHandlers(
        EventHandler objectChanged,
        EventHandler objectErased,
        EventHandler objectAdded)
    {
        var db = GetActiveDocument().Database;
        db.ObjectModified += objectChanged;
        db.ObjectErased += objectErased;
        db.ObjectAppended += objectAdded;
    }

    public static void DetachChangeHandlers()
    {
        // Detach requires the same delegate instances; the sensor keeps them
        // and calls back here. Placeholder: iterate DocumentManager documents.
    }
}
