using Autodesk.Revit.DB;
using Revit.AgentHost.Core.Contracts;

namespace Revit.AgentHost.Native.Walls;

public sealed record RevitWallTargetResolution(
    int ApprovedTargetCount,
    bool NativeKindMatches,
    bool DocumentMatches,
    Wall? Wall)
{
    public bool TargetResolved => Wall is not null;
}

public sealed class RevitWallTargetResolver
{
    public RevitWallTargetResolution Resolve(Document document, HostCommandEnvelope command)
    {
        ArgumentNullException.ThrowIfNull(document);
        ArgumentNullException.ThrowIfNull(command);

        int approvedTargetCount = command.TargetNativeRefs.Count;
        if (approvedTargetCount != 1)
        {
            return new RevitWallTargetResolution(
                approvedTargetCount,
                NativeKindMatches: false,
                DocumentMatches: false,
                Wall: null);
        }

        HostNativeRef nativeRef = command.TargetNativeRefs[0];
        bool nativeKindMatches = string.Equals(
            nativeRef.NativeType,
            "Wall",
            StringComparison.Ordinal);
        bool documentMatches = string.Equals(
            nativeRef.DocumentId,
            command.DocumentId,
            StringComparison.Ordinal);

        if (!nativeKindMatches || !documentMatches || string.IsNullOrWhiteSpace(nativeRef.NativeId))
        {
            return new RevitWallTargetResolution(
                approvedTargetCount,
                nativeKindMatches,
                documentMatches,
                Wall: null);
        }

        Wall? wall = document.GetElement(nativeRef.NativeId) as Wall;
        return new RevitWallTargetResolution(
            approvedTargetCount,
            nativeKindMatches,
            documentMatches,
            wall);
    }
}
