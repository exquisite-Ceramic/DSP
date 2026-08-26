using System.Text.Json;

namespace AutoCAD.AgentHost.Verification;

/// <summary>
/// Read-only entity state access used by verifiers. Never mutates the drawing.
/// </summary>
public static class EntityReader
{
    /// <summary>Reads position payloads (handle → x/y/z) for the given handles.</summary>
    public static Dictionary<string, JsonElement> ReadPositions(IEnumerable<string> handles)
    {
        return Native.AutoCADEntityApi.ReadPositions(handles);
    }
}
