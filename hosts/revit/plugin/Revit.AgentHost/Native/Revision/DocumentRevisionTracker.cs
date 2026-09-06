using System.Collections.Concurrent;
using Autodesk.Revit.DB;

namespace Revit.AgentHost.Native.Revision;

public sealed class DocumentRevisionTracker
{
    private readonly ConcurrentDictionary<Document, long> revisions = new();

    public long Get(Document document)
    {
        ArgumentNullException.ThrowIfNull(document);
        return revisions.GetOrAdd(document, 0L);
    }

    public long OnDocumentChanged(Document document)
    {
        ArgumentNullException.ThrowIfNull(document);
        return revisions.AddOrUpdate(
            document,
            1L,
            static (_, current) => checked(current + 1L));
    }

    public void OnDocumentClosing(Document document)
    {
        ArgumentNullException.ThrowIfNull(document);
        revisions.TryRemove(document, out _);
    }
}
