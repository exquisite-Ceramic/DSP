using System.Text.Json;
using HostContracts;

namespace AutoCAD.AgentHost.Native
{
    public static class AcNative
    {
        public static string ActiveDocumentId() => "drawing-001";
        public static string ActiveDocumentName() => "drawing.dwg";
        public static long ActiveDocumentRevision() => 100;
    }

    public static class AutoCADEntityApi
    {
        public static IReadOnlyList<HostEntityRef> GetSelectedEntityRefs() => Array.Empty<HostEntityRef>();
        public static Dictionary<string, JsonElement> ReadPositions(IEnumerable<string> handles) => new();
        public static void Translate(IEnumerable<string> handles, double dx, double dy, double dz) { }
        public static object? GetEntityByHandle(string handle) => new object();
        public static (HostEntityRef EntityRef, JsonElement? Before, JsonElement? After)? DescribeChange(
            object sender,
            EventArgs args,
            string operation) => null;
    }

    public static class AutoCADViewApi
    {
        public static void ZoomExtents(IEnumerable<string> handles) { }
    }
}

namespace AutoCAD.AgentHost.Execution
{
    public static class DocumentLockManager
    {
        public static IDisposable Acquire(string documentId) => new NoopDisposable();

        private sealed class NoopDisposable : IDisposable
        {
            public void Dispose() { }
        }
    }
}

namespace AutoCAD.AgentHost.Verification
{
    public sealed class MoveVerificationReport
    {
        public bool Ok { get; init; } = true;
        public string Message { get; init; } = string.Empty;
        public Dictionary<string, object> Details { get; init; } = new();
        public JsonElement ToDto() => JsonSerializer.SerializeToElement(new { ok = Ok });
    }

    public static class MoveVerifier
    {
        public static MoveVerificationReport Verify(
            Dictionary<string, JsonElement> before,
            Dictionary<string, JsonElement> after,
            double dx,
            double dy,
            double dz) => new();
    }
}
