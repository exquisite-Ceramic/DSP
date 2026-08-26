using System.Text.Json.Serialization;

namespace HostContracts;

/// <summary>Health / state heartbeat exchanged in both directions.</summary>
public sealed class HostStatus
{
    [JsonPropertyName("state")]
    public string State { get; set; } = "starting"; // starting | ready | busy | error | stopped

    [JsonPropertyName("documentId")]
    public string? DocumentId { get; set; }

    [JsonPropertyName("documentName")]
    public string? DocumentName { get; set; }

    [JsonPropertyName("revision")]
    public int Revision { get; set; }

    [JsonPropertyName("uptimeMs")]
    public long UptimeMs { get; set; }

    [JsonPropertyName("detail")]
    public string? Detail { get; set; }
}
