using System.Text;
using System.Text.Json;
using HostContracts;

namespace AutoCAD.AgentHost.Ipc;

/// <summary>
/// JSON (de)serialization of contract types. Pure contract types only —
/// no Autodesk types ever cross this boundary (ADR-001).
/// </summary>
public static class ContractSerializer
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public static T Deserialize<T>(byte[] frame) =>
        JsonSerializer.Deserialize<T>(frame, Options)
        ?? throw new InvalidDataException($"cannot deserialize {typeof(T).Name}.");

    public static byte[] Serialize(object value) =>
        Encoding.UTF8.GetBytes(JsonSerializer.Serialize(value, Options));

    public static T PayloadAs<T>(Envelope envelope) =>
        envelope.Payload.Deserialize<T>(Options)
        ?? throw new InvalidDataException($"cannot deserialize payload as {typeof(T).Name}.");

    /// <summary>Build a response envelope echoing the request's correlation id.</summary>
    public static Envelope Wrap(string messageType, Envelope? request, object payload)
    {
        var envelope = new Envelope
        {
            MessageType = messageType,
            CorrelationId = request?.MessageId,
        };
        envelope.Payload = JsonSerializer.SerializeToElement(payload, Options);
        return envelope;
    }
}
