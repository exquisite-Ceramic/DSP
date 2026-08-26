using System.Text.Json;
using HostContracts;
using Xunit;

namespace HostContracts.Tests;

public class HostCommandTests
{
    private static T RoundTrip<T>(T value) =>
        JsonSerializer.Deserialize<T>(JsonSerializer.Serialize(value, ContractJson.Options), ContractJson.Options)!;

    private static HostCommand MoveCommand() => new()
    {
        CommandId = "cmd-001",
        DocumentId = "drawing-001",
        Mode = HostCommandMode.EXECUTE,
        Operation = "move.v1",
        TargetNativeRefs = { new HostEntityRef { DocumentId = "drawing-001", NativeId = "2AF" } },
        Arguments = JsonDocument.Parse("""{"displacement":{"x":500,"y":0,"z":0}}""").RootElement.Clone(),
        Preconditions = JsonDocument.Parse("""[{"type":"revision","expected":100}]""").RootElement.Clone(),
        IdempotencyKey = "move-task-001-unit-001",
        DeadlineAt = "2026-08-26T15:00:00Z",
    };

    [Fact] // TC-C02
    public void MoveCommand_RoundTrips_AllFields()
    {
        var original = MoveCommand();
        var restored = RoundTrip(original);

        Assert.Equal(original.CommandId, restored.CommandId);
        Assert.Equal(original.DocumentId, restored.DocumentId);
        Assert.Equal(original.Mode, restored.Mode);
        Assert.Equal(original.Operation, restored.Operation);
        Assert.Equal(original.IdempotencyKey, restored.IdempotencyKey);
        Assert.Equal(original.DeadlineAt, restored.DeadlineAt);

        var ref0 = Assert.Single(restored.TargetNativeRefs);
        Assert.Equal("drawing-001", ref0.DocumentId);
        Assert.Equal("2AF", ref0.NativeId);

        Assert.Equal(500, restored.Arguments!.Value.GetProperty("displacement").GetProperty("x").GetInt32());
        Assert.Equal(100, restored.Preconditions!.Value[0].GetProperty("expected").GetInt32());

        Assert.Empty(original.Validate());
    }

    [Fact] // TC-C03
    public void Execute_WithoutIdempotencyKey_IsInvalid()
    {
        var cmd = new HostCommand { CommandId = "c1", Mode = HostCommandMode.EXECUTE, Operation = "move.v1" };
        Assert.Contains(cmd.Validate(), e => e.Contains("idempotency_key"));
    }

    [Fact] // TC-C04
    public void Read_WithoutIdempotencyKey_IsValid()
    {
        var cmd = new HostCommand { CommandId = "c2", Mode = HostCommandMode.READ, Operation = "context.current_selection" };
        Assert.Empty(cmd.Validate());
    }

    [Fact]
    public void View_WithoutIdempotencyKey_IsValid()
    {
        var cmd = new HostCommand { CommandId = "c3", Mode = HostCommandMode.VIEW, Operation = "view.fit_entities" };
        Assert.Empty(cmd.Validate());
    }

    [Fact]
    public void Verify_WithoutIdempotencyKey_IsValid()
    {
        var cmd = new HostCommand { CommandId = "c4", Mode = HostCommandMode.VERIFY, Operation = "verify.move.v1" };
        Assert.Empty(cmd.Validate());
    }

    [Fact]
    public void Execute_WithIdempotencyKey_IsValid()
    {
        var cmd = new HostCommand { CommandId = "c5", Mode = HostCommandMode.EXECUTE, Operation = "move.v1", IdempotencyKey = "k-1" };
        Assert.Empty(cmd.Validate());
    }

    [Fact]
    public void Mode_SerializesAsEnumString_NotInteger()
    {
        var cmd = new HostCommand { CommandId = "c", Mode = HostCommandMode.EXECUTE, Operation = "move.v1" };
        var json = JsonSerializer.Serialize(cmd, ContractJson.Options);
        Assert.Contains("\"mode\":\"EXECUTE\"", json);
        Assert.DoesNotContain("\"mode\":2", json);
    }
}
