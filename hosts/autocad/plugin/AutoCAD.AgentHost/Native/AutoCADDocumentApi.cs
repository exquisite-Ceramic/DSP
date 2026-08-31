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

    private static Database? _attachedDatabase;
    private static ObjectEventHandler? _objectModifiedHandler;
    private static ObjectErasedEventHandler? _objectErasedHandler;
    private static ObjectEventHandler? _objectAppendedHandler;
    private static DocumentCollectionEventHandler? _documentActivatedHandler;

    public static Document GetActiveDocument() =>
        Application.DocumentManager.MdiActiveDocument
        ?? throw new InvalidOperationException("no active document.");

    public static bool IsActiveDocumentMillimeters() =>
        GetActiveDocument().Database.Insunits == UnitsValue.Millimeters;

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
        DetachChangeHandlers();

        _objectModifiedHandler = (sender, args) => objectChanged(sender, args);
        _objectErasedHandler = (sender, args) => objectErased(sender, args);
        _objectAppendedHandler = (sender, args) => objectAdded(sender, args);
        _documentActivatedHandler = (sender, args) =>
            BindChangeHandlersToDatabase(args.Document.Database);

        Application.DocumentManager.DocumentActivated += _documentActivatedHandler;
        BindChangeHandlersToDatabase(GetActiveDocument().Database);
    }

    private static void BindChangeHandlersToDatabase(Database db)
    {
        if (ReferenceEquals(_attachedDatabase, db))
        {
            return;
        }

        DetachDatabaseChangeHandlers();
        _attachedDatabase = db;

        if (_objectModifiedHandler is not null)
        {
            db.ObjectModified += _objectModifiedHandler;
        }

        if (_objectErasedHandler is not null)
        {
            db.ObjectErased += _objectErasedHandler;
        }

        if (_objectAppendedHandler is not null)
        {
            db.ObjectAppended += _objectAppendedHandler;
        }
    }

    private static void DetachDatabaseChangeHandlers()
    {
        var db = _attachedDatabase;
        if (db is null)
        {
            return;
        }

        if (_objectModifiedHandler is not null)
        {
            db.ObjectModified -= _objectModifiedHandler;
        }

        if (_objectErasedHandler is not null)
        {
            db.ObjectErased -= _objectErasedHandler;
        }

        if (_objectAppendedHandler is not null)
        {
            db.ObjectAppended -= _objectAppendedHandler;
        }

        _attachedDatabase = null;
    }

    public static void DetachChangeHandlers()
    {
        if (_documentActivatedHandler is not null)
        {
            Application.DocumentManager.DocumentActivated -= _documentActivatedHandler;
            _documentActivatedHandler = null;
        }

        DetachDatabaseChangeHandlers();
        _objectModifiedHandler = null;
        _objectErasedHandler = null;
        _objectAppendedHandler = null;
    }
}
