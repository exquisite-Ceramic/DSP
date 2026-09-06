using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Events;
using Autodesk.Revit.UI;
using Revit.AgentHost.Ipc;
using Revit.AgentHost.Native.ExternalEvents;
using Revit.AgentHost.Native.Revision;
using Revit.AgentHost.Native.Walls;

namespace Revit.AgentHost.Native;

public sealed class PluginEntry : IExternalApplication
{
    private DocumentRevisionTracker? revisions;
    private ExternalEvent? externalEvent;
    private NamedPipeServer? pipeServer;

    public Result OnStartup(UIControlledApplication application)
    {
        revisions = new DocumentRevisionTracker();
        var queue = new RevitRequestQueue();
        var executor = new RevitRequestExecutorRouter(
            new RevitWallThicknessReadiness(),
            new RevitWallThicknessMutation());
        var handler = new RevitExternalEventHandler(queue, revisions, executor);

        externalEvent = ExternalEvent.Create(handler);
        var dispatcher = new RequestDispatcher(
            queue,
            new ExternalEventSignal(externalEvent));
        pipeServer = new NamedPipeServer(dispatcher);

        application.ControlledApplication.DocumentChanged += OnDocumentChanged;
        application.ControlledApplication.DocumentClosing += OnDocumentClosing;
        pipeServer.Start();
        return Result.Succeeded;
    }

    public Result OnShutdown(UIControlledApplication application)
    {
        application.ControlledApplication.DocumentChanged -= OnDocumentChanged;
        application.ControlledApplication.DocumentClosing -= OnDocumentClosing;
        pipeServer?.Dispose();
        pipeServer = null;
        externalEvent?.Dispose();
        externalEvent = null;
        revisions = null;
        return Result.Succeeded;
    }

    private void OnDocumentChanged(object? sender, DocumentChangedEventArgs args)
    {
        if (revisions is null)
        {
            return;
        }

        revisions.OnDocumentChanged(args.GetDocument());
    }

    private void OnDocumentClosing(object? sender, DocumentClosingEventArgs args)
    {
        if (revisions is null)
        {
            return;
        }

        revisions.OnDocumentClosing(args.Document);
    }

    private sealed class ExternalEventSignal : IExternalEventSignal
    {
        private readonly ExternalEvent externalEvent;

        public ExternalEventSignal(ExternalEvent externalEvent)
        {
            this.externalEvent = externalEvent;
        }

        public void Raise()
        {
            externalEvent.Raise();
        }
    }
}
