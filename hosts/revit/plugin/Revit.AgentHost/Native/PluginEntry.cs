using System.Text.Json.Nodes;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Events;
using Autodesk.Revit.UI;
using Revit.AgentHost.Core.Contracts;
using Revit.AgentHost.Ipc;
using Revit.AgentHost.Native.ExternalEvents;
using Revit.AgentHost.Native.Revision;

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
        var executor = new FailClosedRequestExecutor();
        var handler = new RevitExternalEventHandler(queue, revisions, executor);

        externalEvent = ExternalEvent.Create(handler);
        var dispatcher = new RequestDispatcher(
            queue,
            new ExternalEventSignal(externalEvent));
        pipeServer = new NamedPipeServer(dispatcher);

        application.ControlledApplication.DocumentChanged += OnDocumentChanged;
        pipeServer.Start();
        return Result.Succeeded;
    }

    public Result OnShutdown(UIControlledApplication application)
    {
        application.ControlledApplication.DocumentChanged -= OnDocumentChanged;
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

        Document document = args.GetDocument();
        string documentKey = revisions.GetDocumentKey(document);
        revisions.OnDocumentChanged(documentKey);
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

    private sealed class FailClosedRequestExecutor : IRevitRequestExecutor
    {
        public HostResultEnvelope Execute(
            Document document,
            HostCommandEnvelope command,
            long revisionBefore)
        {
            ArgumentNullException.ThrowIfNull(document);
            ArgumentNullException.ThrowIfNull(command);

            return new HostResultEnvelope(
                command.CommandId,
                "ERROR",
                null,
                new JsonObject
                {
                    ["code"] = "REVIT_NATIVE_COMMAND_NOT_CONFIGURED",
                },
                checked((int)revisionBefore),
                null,
                false);
        }
    }
}
