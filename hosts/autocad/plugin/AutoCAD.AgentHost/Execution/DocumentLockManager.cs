namespace AutoCAD.AgentHost.Execution;

/// <summary>
/// Acquires and releases the AutoCAD document lock so that command work
/// runs on the document thread (AutoCAD document access is not thread-safe).
/// </summary>
public static class DocumentLockManager
{
    public static IDisposable Acquire(string documentId)
    {
        // Native.AutoCADDocumentApi.LockDocument(documentId) returns a disposable
        // that releases on dispose.
        return Native.AutoCADDocumentApi.LockDocument(documentId);
    }
}
