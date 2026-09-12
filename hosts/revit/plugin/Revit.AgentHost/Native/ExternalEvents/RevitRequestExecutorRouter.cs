using System.Text.Json.Nodes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Revit.AgentHost.Core.Contracts;
using Revit.AgentHost.Native.Context;
using Revit.AgentHost.Native.Walls;

namespace Revit.AgentHost.Native.ExternalEvents;

public sealed class RevitRequestExecutorRouter : IRevitUiRequestExecutor
{
    private readonly RevitContextIdentityReader contextIdentityReader;
    private readonly RevitWallThicknessReadiness readiness;
    private readonly RevitWallThicknessMutation mutation;

    public RevitRequestExecutorRouter(
        RevitWallThicknessReadiness readiness,
        RevitWallThicknessMutation mutation,
        RevitContextIdentityReader? contextIdentityReader = null)
    {
        this.readiness = readiness ?? throw new ArgumentNullException(nameof(readiness));
        this.mutation = mutation ?? throw new ArgumentNullException(nameof(mutation));
        this.contextIdentityReader = contextIdentityReader ?? new RevitContextIdentityReader();
    }

    public HostResultEnvelope Execute(
        UIDocument uiDocument,
        HostCommandEnvelope command,
        long revisionBefore,
        Func<long> readCurrentRevision)
    {
        ArgumentNullException.ThrowIfNull(uiDocument);
        ArgumentNullException.ThrowIfNull(command);
        ArgumentNullException.ThrowIfNull(readCurrentRevision);

        if (string.Equals(command.Mode, "READ", StringComparison.Ordinal)
            && string.Equals(
                command.Operation,
                RevitContextIdentityReader.Operation,
                StringComparison.Ordinal))
        {
            return contextIdentityReader.Execute(uiDocument, command, revisionBefore);
        }

        Document document = uiDocument.Document;
        if (string.Equals(command.Mode, "READ", StringComparison.Ordinal)
            && string.Equals(
                command.Operation,
                "check_wall_thickness_readiness",
                StringComparison.Ordinal))
        {
            return readiness.Execute(
                document,
                command,
                revisionBefore,
                readCurrentRevision);
        }

        if (string.Equals(command.Mode, "EXECUTE", StringComparison.Ordinal)
            && string.Equals(
                command.Operation,
                "set_wall_thickness",
                StringComparison.Ordinal))
        {
            return mutation.Execute(
                document,
                command,
                revisionBefore,
                readCurrentRevision);
        }

        return Unsupported(command.CommandId, revisionBefore);
    }

    private static HostResultEnvelope Unsupported(string commandId, long revision)
    {
        var error = new JsonObject
        {
            ["code"] = "REVIT_REQUEST_UNSUPPORTED",
        };
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
