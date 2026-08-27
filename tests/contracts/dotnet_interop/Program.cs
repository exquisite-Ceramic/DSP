using System.Text.Json;
using HostContracts;

if (args.Length != 1)
{
    Console.Error.WriteLine("usage: ContractInterop <consume-request|emit-request>");
    return 2;
}

try
{
    return args[0] switch
    {
        "consume-request" => ConsumeRequest(),
        "emit-request" => EmitRequest(),
        _ => UnknownMode(args[0]),
    };
}
catch (Exception ex)
{
    Console.Error.WriteLine(ex.ToString());
    return 1;
}

static int ConsumeRequest()
{
    var json = Console.In.ReadToEnd();
    var envelope = JsonSerializer.Deserialize<RequestEnvelope>(json, ContractJson.Options)
        ?? throw new InvalidOperationException("request envelope deserialized to null");
    EnsureValid(envelope.Validate(), "request envelope");

    var command = JsonSerializer.Deserialize<HostCommand>(
        envelope.Payload.GetRawText(), ContractJson.Options)
        ?? throw new InvalidOperationException("host command deserialized to null");
    EnsureValid(command.Validate(), "host command");

    var nativeId = command.TargetNativeRefs.Single().NativeId;
    var displacementX = command.Arguments!.Value
        .GetProperty("displacement")
        .GetProperty("x")
        .GetInt32();

    var summary = new
    {
        request_id = envelope.RequestId,
        task_id = envelope.TaskId,
        command_id = command.CommandId,
        document_id = command.DocumentId,
        mode = command.Mode.ToString(),
        operation = command.Operation,
        native_id = nativeId,
        displacement_x = displacementX,
        idempotency_key = command.IdempotencyKey,
    };

    Console.WriteLine(JsonSerializer.Serialize(summary, ContractJson.Options));
    return 0;
}

static int EmitRequest()
{
    var command = new HostCommand
    {
        CommandId = "cmd-cs-001",
        DocumentId = "drawing-001",
        Mode = HostCommandMode.EXECUTE,
        Operation = "move.v1",
        TargetNativeRefs =
        {
            new HostEntityRef { DocumentId = "drawing-001", NativeId = "2AF" },
        },
        Arguments = JsonDocument.Parse(
            """{"displacement":{"x":500,"y":0,"z":0}}""").RootElement.Clone(),
        IdempotencyKey = "interop-cs-py-001",
        DeadlineAt = "2026-08-27T01:00:00Z",
    };
    EnsureValid(command.Validate(), "host command");

    var envelope = new RequestEnvelope
    {
        RequestId = "req-cs-001",
        TaskId = "task-interop-002",
        ProjectId = "project-001",
        IdempotencyKey = "interop-cs-py-001",
        Payload = JsonSerializer.SerializeToElement(command, ContractJson.Options),
    };
    EnsureValid(envelope.Validate(), "request envelope");

    Console.WriteLine(JsonSerializer.Serialize(envelope, ContractJson.Options));
    return 0;
}

static int UnknownMode(string mode)
{
    Console.Error.WriteLine($"unknown mode: {mode}");
    return 2;
}

static void EnsureValid(IReadOnlyList<string> errors, string label)
{
    if (errors.Count > 0)
    {
        throw new InvalidOperationException($"invalid {label}: {string.Join("; ", errors)}");
    }
}
