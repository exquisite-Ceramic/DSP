using System.Text;
using System.Text.Json;
using HostContracts;

namespace AutoCAD.AgentHost.Ipc;

/// <summary>
/// JSON (de)serialization of the current HostContracts wire DTOs.
/// No Autodesk types ever cross this boundary (ADR-001).
/// </summary>
public static class ContractSerializer
{
    public static T Deserialize<T>(byte[] frame) =>
        JsonSerializer.Deserialize<T>(frame, ContractJson.Options)
        ?? throw new InvalidDataException($"cannot deserialize {typeof(T).Name}.");

    public static RequestEnvelope DeserializeRequest(byte[] frame) =>
        Deserialize<RequestEnvelope>(frame);

    public static byte[] Serialize(object value) =>
        Encoding.UTF8.GetBytes(JsonSerializer.Serialize(value, ContractJson.Options));

    public static T PayloadAs<T>(RequestEnvelope envelope) =>
        envelope.Payload.Deserialize<T>(ContractJson.Options)
        ?? throw new InvalidDataException($"cannot deserialize payload as {typeof(T).Name}.");

    public static ResponseEnvelope WrapResult(RequestEnvelope request, HostCommandResult result)
    {
        if (result.Status == ResultStatus.ERROR)
        {
            return new ResponseEnvelope
            {
                RequestId = request.RequestId,
                Status = ResponseStatus.ERROR,
                CorrelationIds = request.CorrelationIds,
                Error = result.Error ?? new ErrorShape
                {
                    ErrorCode = "HOST_COMMAND_FAILED",
                    Category = ErrorCategory.EXECUTION,
                    Message = "host command returned ERROR without an ErrorShape",
                    Retryable = RetryPolicy.NEVER,
                },
            };
        }

        return new ResponseEnvelope
        {
            RequestId = request.RequestId,
            Status = ResponseStatus.OK,
            CorrelationIds = request.CorrelationIds,
            Result = JsonSerializer.SerializeToElement(result, ContractJson.Options),
        };
    }

    public static ResponseEnvelope WrapError(RequestEnvelope? request, ErrorShape error) =>
        new()
        {
            RequestId = request?.RequestId ?? string.Empty,
            Status = ResponseStatus.ERROR,
            CorrelationIds = request?.CorrelationIds,
            Error = error,
        };
}
