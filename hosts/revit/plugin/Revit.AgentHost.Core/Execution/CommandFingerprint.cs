using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Revit.AgentHost.Core.Contracts;

namespace Revit.AgentHost.Core.Execution;

public static class CommandFingerprint
{
    public static string Compute(HostCommandEnvelope command)
    {
        ArgumentNullException.ThrowIfNull(command);

        JsonObject semanticBody = new()
        {
            ["document_id"] = command.DocumentId,
            ["mode"] = command.Mode,
            ["operation"] = command.Operation,
            ["target_native_refs"] = JsonSerializer.SerializeToNode(command.TargetNativeRefs),
            ["arguments"] = command.Arguments.DeepClone(),
            ["preconditions"] = JsonSerializer.SerializeToNode(command.Preconditions),
        };

        string canonical = Canonicalize(semanticBody);
        byte[] digest = SHA256.HashData(Encoding.UTF8.GetBytes(canonical));
        return Convert.ToHexString(digest).ToLowerInvariant();
    }

    private static string Canonicalize(JsonNode node)
    {
        using MemoryStream stream = new();
        using (Utf8JsonWriter writer = new(stream))
        {
            WriteCanonical(writer, node);
        }

        return Encoding.UTF8.GetString(stream.ToArray());
    }

    private static void WriteCanonical(Utf8JsonWriter writer, JsonNode? node)
    {
        if (node is null)
        {
            writer.WriteNullValue();
            return;
        }

        if (node is JsonObject obj)
        {
            writer.WriteStartObject();
            foreach ((string key, JsonNode? value) in obj.OrderBy(pair => pair.Key, StringComparer.Ordinal))
            {
                writer.WritePropertyName(key);
                WriteCanonical(writer, value);
            }
            writer.WriteEndObject();
            return;
        }

        if (node is JsonArray array)
        {
            writer.WriteStartArray();
            foreach (JsonNode? item in array)
            {
                WriteCanonical(writer, item);
            }
            writer.WriteEndArray();
            return;
        }

        node.WriteTo(writer);
    }
}
