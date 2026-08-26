using System.Collections.Concurrent;
using HostContracts;

namespace AutoCAD.AgentHost.Execution;

/// <summary>
/// In-memory idempotency cache (ADR-003). Keyed by (documentId, idempotencyKey);
/// replays return the cached result with <c>Replayed = true</c>.
/// Buckets are dropped when a document closes.
/// </summary>
public sealed class IdempotencyStore
{
    private const int MaxEntriesPerDocument = 1024;

    private readonly ConcurrentDictionary<string, ConcurrentDictionary<string, HostCommandResult>> _store = new();

    public HostCommandResult? TryGet(string documentId, string idempotencyKey)
    {
        return _store.TryGetValue(documentId, out var bucket)
            && bucket.TryGetValue(idempotencyKey, out var result)
                ? result
                : null;
    }

    public void Store(string documentId, string idempotencyKey, HostCommandResult result)
    {
        var bucket = _store.GetOrAdd(documentId, _ => new ConcurrentDictionary<string, HostCommandResult>());

        if (bucket.Count >= MaxEntriesPerDocument)
        {
            bucket.Clear(); // simple LRU stand-in: reset the bucket
        }

        bucket[idempotencyKey] = result;
    }

    public void DropDocument(string documentId) => _store.TryRemove(documentId, out _);
}
