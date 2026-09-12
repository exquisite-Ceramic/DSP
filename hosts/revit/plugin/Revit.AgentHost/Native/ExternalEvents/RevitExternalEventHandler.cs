using System.Text.Json.Nodes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Revit.AgentHost.Core.Contracts;
using Revit.AgentHost.Native.Revision;

namespace Revit.AgentHost.Native.ExternalEvents;

public interface IRevitRequestExecutor
{
    HostResultEnvelope Execute(
        Document document,
        HostCommandEnvelope command,
        long revisionBefore,
        Func<long> readCurrentRevision);
}

public interface IRevitUiRequestExecutor
{
    HostResultEnvelope Execute(
        UIDocument uiDocument,
        HostCommandEnvelope command,
        long revisionBefore,
        Func<long> readCurrentRevision);
}

public sealed class RevitExternalEventHandler : IExternalEventHandler
{
    private readonly RevitRequestQueue queue;
    private readonly DocumentRevisionTracker revisions;
    private readonly IRevitUiRequestExecutor executor;

    public RevitExternalEventHandler(
        RevitRequestQueue queue,
        DocumentRevisionTracker revisions,
        IRevitUiRequestExecutor executor)
    {
        this.queue = queue ?? throw new ArgumentNullException(nameof(queue));
        this.revisions = revisions ?? throw new ArgumentNullException(nameof(revisions));
        this.executor = executor ?? throw new ArgumentNullException(nameof(executor));
    }

    public void Execute(UIApplication app)
    {
        ArgumentNullException.ThrowIfNull(app);

        while (queue.TryDequeue(out RevitQueuedRequest request))
        {
            HostResultEnvelope result = ExecuteOne(app, request.Command);
            request.Complete(result);
        }
    }

    public string GetName() => "DSP Revit AgentHost request dispatcher";

    private HostResultEnvelope ExecuteOne(
        UIApplication app,
        HostCommandEnvelope command)
    {
        UIDocument? uiDocument = app.ActiveUIDocument;
        if (uiDocument is null)
        {
            return Error(command.CommandId, "REVIT_ACTIVE_DOCUMENT_UNAVAILABLE", 0L, null);
        }

        long revisionBefore = revisions.Get(uiDocument.Document);

        try
        {
            return executor.Execute(
                uiDocument,
                command,
                revisionBefore,
                () => revisions.Get(uiDocument.Document));
        }
        catch (Exception exception)
        {
            return Error(
                command.CommandId,
                "REVIT_REQUEST_EXECUTION_FAILED",
                revisions.Get(uiDocument.Document),
                exception.Message);
        }
    }

    private static HostResultEnvelope Error(
        string commandId,
        string code,
        long revision,
        string? message)
    {
        var error = new JsonObject
        {
            ["code"] = code,
        };
        if (!string.IsNullOrWhiteSpace(message))
        {
            error["message"] = message;
        }

        return new HostResultEnvelope(
            commandId,
            "ERROR",
            null,
            error,
            checked((int)revision),
            null,
            false);
    }
}
