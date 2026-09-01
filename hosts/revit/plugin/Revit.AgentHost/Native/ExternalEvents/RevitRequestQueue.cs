using System.Collections.Concurrent;
using Revit.AgentHost.Core.Contracts;
using Revit.AgentHost.Ipc;

namespace Revit.AgentHost.Native.ExternalEvents;

public sealed class RevitQueuedRequest
{
    private readonly TaskCompletionSource<HostResultEnvelope> completion =
        new(TaskCreationOptions.RunContinuationsAsynchronously);
    private int completed;

    public RevitQueuedRequest(HostCommandEnvelope command)
    {
        Command = command ?? throw new ArgumentNullException(nameof(command));
    }

    public HostCommandEnvelope Command { get; }

    public Task<HostResultEnvelope> Completion => completion.Task;

    public void Complete(HostResultEnvelope result)
    {
        ArgumentNullException.ThrowIfNull(result);
        if (Interlocked.Exchange(ref completed, 1) != 0)
        {
            throw new InvalidOperationException(
                $"Revit request '{Command.CommandId}' was completed more than once.");
        }

        completion.SetResult(result);
    }
}

public sealed class RevitRequestQueue : IRevitRequestQueue
{
    private readonly ConcurrentQueue<RevitQueuedRequest> pending = new();

    public Task<HostResultEnvelope> Enqueue(HostCommandEnvelope command)
    {
        var request = new RevitQueuedRequest(command);
        pending.Enqueue(request);
        return request.Completion;
    }

    public bool TryDequeue(out RevitQueuedRequest request)
    {
        return pending.TryDequeue(out request!);
    }
}
