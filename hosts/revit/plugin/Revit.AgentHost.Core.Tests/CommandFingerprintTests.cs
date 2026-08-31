using System.Text.Json;
using System.Text.Json.Nodes;
using Revit.AgentHost.Core.Contracts;
using Revit.AgentHost.Core.Execution;
using Xunit;

namespace Revit.AgentHost.Core.Tests;

public sealed class CommandFingerprintTests
{
    [Fact]
    public void Host_command_serializes_shared_schema_field_names_exactly()
    {
        HostCommandEnvelope command = BuildCommand();

        string json = JsonSerializer.Serialize(command);
        using JsonDocument document = JsonDocument.Parse(json);
        JsonElement root = document.RootElement;

        Assert.Equal("CMD-REVIT-001", root.GetProperty("command_id").GetString());
        Assert.Equal("DOC-REVIT-001", root.GetProperty("document_id").GetString());
        Assert.Equal("EXECUTE", root.GetProperty("mode").GetString());
        Assert.Equal("set_wall_thickness", root.GetProperty("operation").GetString());
        Assert.Equal("IDEMP-REVIT-001", root.GetProperty("idempotency_key").GetString());
        Assert.Equal(JsonValueKind.Null, root.GetProperty("deadline_at").ValueKind);

        JsonElement target = root.GetProperty("target_native_refs")[0];
        Assert.Equal("DOC-REVIT-001", target.GetProperty("document_id").GetString());
        Assert.Equal("wall-unique-id", target.GetProperty("native_id").GetString());
        Assert.Equal("Wall", target.GetProperty("native_type").GetString());
        Assert.Equal(300.0, root.GetProperty("arguments").GetProperty("thickness").GetProperty("value").GetDouble());
        Assert.Equal("mm", root.GetProperty("arguments").GetProperty("thickness").GetProperty("unit").GetString());
        Assert.Equal(10, root.GetProperty("preconditions")[0].GetProperty("revision").GetInt32());
    }

    [Fact]
    public void Fingerprint_is_insensitive_to_json_object_key_order()
    {
        HostCommandEnvelope left = BuildCommand(argumentsJson: "{\"thickness\":{\"value\":300.0,\"unit\":\"mm\"}}");
        HostCommandEnvelope right = BuildCommand(argumentsJson: "{\"thickness\":{\"unit\":\"mm\",\"value\":300.0}}");

        Assert.Equal(CommandFingerprint.Compute(left), CommandFingerprint.Compute(right));
    }

    [Fact]
    public void Fingerprint_changes_for_every_effective_mutation_authority_input()
    {
        string baseline = CommandFingerprint.Compute(BuildCommand());

        Assert.NotEqual(baseline, CommandFingerprint.Compute(BuildCommand(nativeId: "other-wall-unique-id")));
        Assert.NotEqual(baseline, CommandFingerprint.Compute(BuildCommand(thicknessMm: 301.0)));
        Assert.NotEqual(baseline, CommandFingerprint.Compute(BuildCommand(documentId: "DOC-REVIT-002")));
        Assert.NotEqual(baseline, CommandFingerprint.Compute(BuildCommand(revision: 11)));
        Assert.NotEqual(baseline, CommandFingerprint.Compute(BuildCommand(operation: "other_operation")));
        Assert.NotEqual(baseline, CommandFingerprint.Compute(BuildCommand(mode: "VERIFY")));
    }

    private static HostCommandEnvelope BuildCommand(
        string documentId = "DOC-REVIT-001",
        string nativeId = "wall-unique-id",
        double thicknessMm = 300.0,
        int revision = 10,
        string operation = "set_wall_thickness",
        string mode = "EXECUTE",
        string? argumentsJson = null)
    {
        JsonObject arguments = argumentsJson is not null
            ? JsonNode.Parse(argumentsJson)!.AsObject()
            : JsonSerializer.SerializeToNode(
                new WallThicknessArguments(new WallThicknessMeasurement(thicknessMm, "mm")))!.AsObject();
        JsonObject precondition = JsonNode.Parse($"{{\"revision\":{revision}}}")!.AsObject();

        return new HostCommandEnvelope(
            CommandId: "CMD-REVIT-001",
            DocumentId: documentId,
            Mode: mode,
            Operation: operation,
            TargetNativeRefs: new[] { new HostNativeRef(documentId, nativeId, "Wall") },
            Arguments: arguments,
            Preconditions: new[] { precondition },
            IdempotencyKey: "IDEMP-REVIT-001",
            DeadlineAt: null);
    }
}
