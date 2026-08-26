namespace AutoCAD.AgentHost.ChangeCapture;

/// <summary>
/// Subscribes to document change events and forwards them to the delta
/// pipeline. Attach on plugin start, detach on stop.
/// </summary>
public sealed class ChangeSensor
{
    private readonly HostDeltaBuilder _builder;
    private readonly EventQueue _queue;
    private bool _attached;

    public ChangeSensor(HostDeltaBuilder builder, EventQueue queue)
    {
        _builder = builder;
        _queue = queue;
    }

    public void Attach()
    {
        if (_attached)
        {
            return;
        }

        // Native.AutoCADDocumentApi exposes the underlying Document/Database
        // events; handlers run on the document thread and must not block.
        Native.AutoCADDocumentApi.AttachChangeHandlers(OnObjectChanged, OnObjectErased, OnObjectAdded);
        _attached = true;
    }

    public void Detach()
    {
        if (!_attached)
        {
            return;
        }

        Native.AutoCADDocumentApi.DetachChangeHandlers();
        _attached = false;
    }

    private void OnObjectChanged(object sender, EventArgs args)
    {
        // Collect per-transaction; the builder collapses events into deltas.
        foreach (var delta in _builder.Build(sender, args, operation: "modified"))
        {
            _queue.Enqueue(delta);
        }
    }

    private void OnObjectAdded(object sender, EventArgs args)
    {
        foreach (var delta in _builder.Build(sender, args, operation: "created"))
        {
            _queue.Enqueue(delta);
        }
    }

    private void OnObjectErased(object sender, EventArgs args)
    {
        foreach (var delta in _builder.Build(sender, args, operation: "deleted"))
        {
            _queue.Enqueue(delta);
        }
    }
}
