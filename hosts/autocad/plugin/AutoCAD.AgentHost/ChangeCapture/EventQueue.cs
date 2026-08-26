using System.Collections.Concurrent;
using HostContracts;

namespace AutoCAD.AgentHost.ChangeCapture;

/// <summary>
/// Bounded queue of pending deltas to push to the sidecar. The push loop is
/// started by PluginLifecycle; if the pipe is down, deltas accumulate up to
/// <see cref="MaxQueued"/> and are then dropped (with a counter) rather than
/// blocking document commits.
/// </summary>
public sealed class EventQueue
{
    public const int MaxQueued = 4096;

    private readonly ConcurrentQueue<HostDelta> _queue = new();
    private readonly object _sync = new();
    private int _dropped;

    public void Enqueue(HostDelta delta)
    {
        lock (_sync)
        {
            if (_queue.Count >= MaxQueued)
            {
                _dropped++;
                return;
            }

            _queue.Enqueue(delta);
        }
    }

    public IReadOnlyList<HostDelta> Drain()
    {
        var batch = new List<HostDelta>();
        lock (_sync)
        {
            while (_queue.TryDequeue(out var delta))
            {
                batch.Add(delta);
            }
        }

        return batch;
    }

    public (int Queued, int Dropped) Stats()
    {
        lock (_sync)
        {
            return (_queue.Count, _dropped);
        }
    }
}
