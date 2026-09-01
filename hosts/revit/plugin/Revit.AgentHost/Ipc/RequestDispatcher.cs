using Revit.AgentHost.Core.Contracts;

namespace Revit.AgentHost.Ipc;

public interface IRevitRequestQueue
{
    Task<HostResultEnvelope> Enqueue(HostCommandEnvelope command);
}

public interface IExternalEventSignal
{
    void Raise();
}

public sealed class RequestDispatcher
{
    private readonly IRevitRequestQueue queue;
    private readonly IExternalEventSignal signal;

    public RequestDispatcher(IRevitRequestQueue queue, IExternalEventSignal signal)
    {
        this.queue = queue ?? throw new ArgumentNullException(nameof(queue));
        this.signal = signal ?? throw new ArgumentNullException(nameof(signal));
    }

    public async Task<HostResultEnvelope> DispatchAsync(
        HostCommandEnvelope command,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(command);

        Task<HostResultEnvelope> pending = queue.Enqueue(command);
        signal.Raise();
        return await pending.WaitAsync(cancellationToken).ConfigureAwait(false);
    }
}
