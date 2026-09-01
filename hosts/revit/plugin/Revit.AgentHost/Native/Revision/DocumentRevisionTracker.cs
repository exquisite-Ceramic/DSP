using System.Collections.Concurrent;
using System.Runtime.CompilerServices;
using Autodesk.Revit.DB;

namespace Revit.AgentHost.Native.Revision;

public sealed class DocumentRevisionTracker
{
    private sealed record DocumentKeyHolder(string Value);

    private readonly ConcurrentDictionary<string, long> revisions =
        new(StringComparer.Ordinal);
    private readonly ConditionalWeakTable<Document, DocumentKeyHolder> documentKeys = new();

    public string GetDocumentKey(Document document)
    {
        ArgumentNullException.ThrowIfNull(document);
        DocumentKeyHolder holder = documentKeys.GetValue(
            document,
            static _ => new DocumentKeyHolder(Guid.NewGuid().ToString("N")));
        revisions.TryAdd(holder.Value, 0L);
        return holder.Value;
    }

    public long Get(string documentKey)
    {
        ValidateDocumentKey(documentKey);
        return revisions.TryGetValue(documentKey, out long revision) ? revision : 0L;
    }

    public long OnDocumentChanged(string documentKey)
    {
        ValidateDocumentKey(documentKey);
        return revisions.AddOrUpdate(
            documentKey,
            1L,
            static (_, current) => checked(current + 1L));
    }

    private static void ValidateDocumentKey(string documentKey)
    {
        if (string.IsNullOrWhiteSpace(documentKey))
        {
            throw new ArgumentException("Document key is required.", nameof(documentKey));
        }
    }
}
