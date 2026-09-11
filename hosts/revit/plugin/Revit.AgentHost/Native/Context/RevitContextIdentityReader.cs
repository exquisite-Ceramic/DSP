using System.Text.Json.Nodes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Revit.AgentHost.Core.Contracts;

namespace Revit.AgentHost.Native.Context;

/// <summary>
/// 只读返回当前 Revit 文档身份、当前 runtime identity 与当前选择集的 persistent UniqueId。
/// </summary>
public sealed class RevitContextIdentityReader
{
    public const string Operation = "context.current_selection";

    private static readonly string HostInstanceId = $"revit-{Guid.NewGuid():N}";

    public HostResultEnvelope Execute(
        UIDocument uiDocument,
        HostCommandEnvelope command,
        long revision)
    {
        ArgumentNullException.ThrowIfNull(uiDocument);
        ArgumentNullException.ThrowIfNull(command);

        if (!string.Equals(command.Mode, "READ", StringComparison.Ordinal)
            || !string.Equals(command.Operation, Operation, StringComparison.Ordinal))
        {
            return Error(command.CommandId, "REVIT_CONTEXT_UNSUPPORTED", revision);
        }

        Document document = uiDocument.Document;
        string documentId = string.IsNullOrWhiteSpace(document.PathName)
            ? document.Title
            : document.PathName;

        var selectedElements = new JsonArray();
        foreach (ElementId elementId in uiDocument.Selection.GetElementIds())
        {
            Element? element = document.GetElement(elementId);
            if (element is null || string.IsNullOrWhiteSpace(element.UniqueId))
            {
                continue;
            }

            selectedElements.Add(new JsonObject
            {
                ["unique_id"] = element.UniqueId,
                ["native_kind"] = element.GetType().Name,
            });
        }

        var payload = new JsonObject
        {
            ["document_id"] = documentId,
            ["document_title"] = document.Title,
            ["host_instance_id"] = HostInstanceId,
            ["selected_elements"] = selectedElements,
        };

        return new HostResultEnvelope(
            command.CommandId,
            "OK",
            payload,
            null,
            checked((int)revision),
            null,
            false);
    }

    private static HostResultEnvelope Error(string commandId, string code, long revision)
    {
        return new HostResultEnvelope(
            commandId,
            "ERROR",
            null,
            new JsonObject { ["code"] = code },
            checked((int)revision),
            null,
            false);
    }
}
