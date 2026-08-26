using System.Text.Json;
using HostContracts;
using Xunit;

namespace HostContracts.Tests;

/// <summary>
/// Forward compatibility (spec §23.1) and golden vectors (TC-C06 / TC-C08).
/// The golden JSON in contracts/test_vectors is shared with the Python suite:
/// both languages MUST read it identically.
/// </summary>
public class CompatibilityTests
{
    private static readonly string Vectors = Path.Combine(AppContext.BaseDirectory, "test_vectors");

    private static string ReadVector(string relPath) =>
        File.ReadAllText(Path.Combine(Vectors, relPath));

    [Fact] // TC-C06
    public void UnknownField_IsIgnored()
    {
        const string json = """{"request_id":"req-1","task_id":"task-1","future_field":"hello"}""";
        var env = JsonSerializer.Deserialize<RequestEnvelope>(json, ContractJson.Options)!;
        Assert.Equal("req-1", env.RequestId);
        Assert.Equal("task-1", env.TaskId);

        var reserialized = JsonSerializer.Serialize(env, ContractJson.Options);
        Assert.DoesNotContain("future_field", reserialized);
    }

    [Fact]
    public void UnknownField_NestedInCommand_IsIgnored()
    {
        const string json = """
            {"command_id":"c","document_id":"d","mode":"READ","operation":"context.current_document","future_nested":{"a":1}}
            """;
        var cmd = JsonSerializer.Deserialize<HostCommand>(json, ContractJson.Options)!;
        Assert.Equal("c", cmd.CommandId);

        var reserialized = JsonSerializer.Serialize(cmd, ContractJson.Options);
        Assert.DoesNotContain("future_nested", reserialized);
    }

    [Fact]
    public void ContractVersion_Vector_Matches_AssemblyConstant()
    {
        using var doc = JsonDocument.Parse(ReadVector("contract-version.json"));
        var root = doc.RootElement;
        Assert.Equal(ContractVersion.Major, root.GetProperty("major").GetInt32());
        Assert.Equal(ContractVersion.Minor, root.GetProperty("minor").GetInt32());
    }

    [Fact] // TC-C08 golden — the same assertions as the Python suite.
    public void Golden_MoveJson_IsReadable_IdenticallyToPython()
    {
        var env = JsonSerializer.Deserialize<RequestEnvelope>(ReadVector(Path.Combine("request", "move.json")), ContractJson.Options)!;
        Assert.Empty(env.Validate());

        Assert.Equal("req-001", env.RequestId);
        Assert.Equal("task-001", env.TaskId);
        Assert.Equal("project-001", env.ProjectId);
        Assert.Equal("2026-08-26T15:00:00Z", env.DeadlineAt);
        Assert.Equal("move-task-001-unit-001", env.IdempotencyKey);

        var cmd = JsonSerializer.Deserialize<HostCommand>(env.Payload.GetRawText(), ContractJson.Options)!;
        Assert.Equal("cmd-001", cmd.CommandId);
        Assert.Equal("drawing-001", cmd.DocumentId);
        Assert.Equal(HostCommandMode.EXECUTE, cmd.Mode);
        Assert.Equal("move.v1", cmd.Operation);

        var ref0 = Assert.Single(cmd.TargetNativeRefs);
        Assert.Equal("drawing-001", ref0.DocumentId);
        Assert.Equal("2AF", ref0.NativeId);

        Assert.Equal(500, cmd.Arguments!.Value.GetProperty("displacement").GetProperty("x").GetInt32());
        Assert.Equal(0, cmd.Arguments!.Value.GetProperty("displacement").GetProperty("y").GetInt32());
        Assert.Equal(0, cmd.Arguments!.Value.GetProperty("displacement").GetProperty("z").GetInt32());

        // Round-trip stability: deserialize -> serialize -> deserialize stays identical.
        var json = JsonSerializer.Serialize(env, ContractJson.Options);
        var again = JsonSerializer.Deserialize<RequestEnvelope>(json, ContractJson.Options)!;
        Assert.Equal("req-001", again.RequestId);
        Assert.Equal(HostCommandMode.EXECUTE,
            JsonSerializer.Deserialize<HostCommand>(again.Payload.GetRawText(), ContractJson.Options)!.Mode);
    }

    [Fact]
    public void Golden_RequestVectors_AreReadable()
    {
        var selection = JsonSerializer.Deserialize<RequestEnvelope>(
            ReadVector(Path.Combine("request", "current_selection.json")), ContractJson.Options)!;
        Assert.Equal(HostCommandMode.READ,
            JsonSerializer.Deserialize<HostCommand>(selection.Payload.GetRawText(), ContractJson.Options)!.Mode);

        var verify = JsonSerializer.Deserialize<RequestEnvelope>(
            ReadVector(Path.Combine("request", "verify_move.json")), ContractJson.Options)!;
        var verifyCmd = JsonSerializer.Deserialize<HostCommand>(verify.Payload.GetRawText(), ContractJson.Options)!;
        Assert.Equal(HostCommandMode.VERIFY, verifyCmd.Mode);
        Assert.Equal("verify.move.v1", verifyCmd.Operation);
    }

    [Fact]
    public void Golden_DeltaVectors_AreReadable()
    {
        var modified = JsonSerializer.Deserialize<HostDelta>(
            ReadVector(Path.Combine("delta", "entity_modified.json")), ContractJson.Options)!;
        Assert.Equal(100, modified.RevisionBefore);
        Assert.Equal(101, modified.RevisionAfter);
        Assert.Equal("2AF", Assert.Single(modified.Modified).NativeId);
        Assert.Empty(modified.Validate());

        var created = JsonSerializer.Deserialize<HostDelta>(
            ReadVector(Path.Combine("delta", "entity_created.json")), ContractJson.Options)!;
        var added = Assert.Single(created.Added);
        Assert.Equal("3B1", added.NativeId);
        Assert.Equal("LINE", added.NativeType);
    }

    [Fact]
    public void Golden_ErrorResponseVectors_AreReadable()
    {
        var conflict = JsonSerializer.Deserialize<ResponseEnvelope>(
            ReadVector(Path.Combine("response", "revision_conflict.json")), ContractJson.Options)!;
        Assert.Equal(ResponseStatus.ERROR, conflict.Status);
        Assert.NotNull(conflict.Error);
        Assert.Equal("REVISION_CONFLICT", conflict.Error!.ErrorCode);
        Assert.Equal(ErrorCategory.CONSISTENCY, conflict.Error.Category);
        Assert.Equal(RetryPolicy.AFTER_RECONSTRUCT, conflict.Error.Retryable);
        Assert.Equal(100, conflict.Error.Details!.Value[0].GetProperty("expected_revision").GetInt32());
        Assert.Equal(101, conflict.Error.Details!.Value[0].GetProperty("actual_revision").GetInt32());
        Assert.Empty(conflict.Validate());

        var failed = JsonSerializer.Deserialize<ResponseEnvelope>(
            ReadVector(Path.Combine("response", "host_command_failed.json")), ContractJson.Options)!;
        Assert.Equal("HOST_COMMAND_FAILED", failed.Error!.ErrorCode);
        Assert.Equal(RetryPolicy.IMMEDIATE, failed.Error.Retryable);

        var ok = JsonSerializer.Deserialize<ResponseEnvelope>(
            ReadVector(Path.Combine("response", "move_ok.json")), ContractJson.Options)!;
        Assert.Equal(ResponseStatus.OK, ok.Status);
        Assert.Null(ok.Error);
        var result = JsonSerializer.Deserialize<HostCommandResult>(ok.Result!.Value.GetRawText(), ContractJson.Options)!;
        Assert.Equal(101, result.RevisionAfter);
        Assert.True(result.Ok);
    }
}
