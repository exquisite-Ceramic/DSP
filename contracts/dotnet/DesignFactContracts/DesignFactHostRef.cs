using System.Text.Json.Serialization;

namespace DesignFactContracts;

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed class DesignFactHostRef
{
    [JsonConstructor]
    public DesignFactHostRef(string hostType, string hostInstanceId, string documentId)
    {
        HostType = ContractValidation.NonBlank(hostType, nameof(hostType));
        HostInstanceId = ContractValidation.NonBlank(hostInstanceId, nameof(hostInstanceId));
        DocumentId = ContractValidation.NonBlank(documentId, nameof(documentId));
    }

    [JsonPropertyName("host_type")]
    public string HostType { get; }

    [JsonPropertyName("host_instance_id")]
    public string HostInstanceId { get; }

    [JsonPropertyName("document_id")]
    public string DocumentId { get; }
}
