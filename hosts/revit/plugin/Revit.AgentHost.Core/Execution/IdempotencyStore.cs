using Revit.AgentHost.Core.Contracts;

namespace Revit.AgentHost.Core.Execution;

public sealed record IdempotencyEntry(string Fingerprint, HostResultEnvelope Result);

public sealed class IdempotencyConflictException : InvalidOperationException
{
    public const string StableCode = "IDEMPOTENCY_KEY_CONFLICT";

    public IdempotencyConflictException(string key)
        : base($"Idempotency key '{key}' is already bound to a different command fingerprint.")
    {
    }

    public string Code => StableCode;
}

public sealed class IdempotencyStore
{
    private readonly Dictionary<string, IdempotencyEntry> entries = new(StringComparer.Ordinal);

    public bool TryGet(string key, string fingerprint, out HostResultEnvelope result)
    {
        if (!entries.TryGetValue(key, out IdempotencyEntry? entry))
        {
            result = null!;
            return false;
        }

        EnsureFingerprintMatches(key, fingerprint, entry.Fingerprint);
        result = entry.Result;
        return true;
    }

    public void Store(string key, string fingerprint, HostResultEnvelope result)
    {
        ArgumentNullException.ThrowIfNull(result);

        if (entries.TryGetValue(key, out IdempotencyEntry? existing))
        {
            EnsureFingerprintMatches(key, fingerprint, existing.Fingerprint);
            return;
        }

        entries.Add(key, new IdempotencyEntry(fingerprint, result));
    }

    private static void EnsureFingerprintMatches(string key, string requested, string stored)
    {
        if (!string.Equals(requested, stored, StringComparison.Ordinal))
        {
            throw new IdempotencyConflictException(key);
        }
    }
}
