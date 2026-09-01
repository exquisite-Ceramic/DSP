using Autodesk.Revit.DB;
using Revit.AgentHost.Core.Contracts;

namespace Revit.AgentHost.Native.Walls;

public sealed class RevitWallIsolationProbe
{
    private readonly RevitWallTargetResolver targetResolver;

    public RevitWallIsolationProbe(RevitWallTargetResolver? targetResolver = null)
    {
        this.targetResolver = targetResolver ?? new RevitWallTargetResolver();
    }

    public WallIsolationEvidence Collect(Document document, HostCommandEnvelope command)
    {
        ArgumentNullException.ThrowIfNull(document);
        ArgumentNullException.ThrowIfNull(command);

        RevitWallTargetResolution resolution = targetResolver.Resolve(document, command);
        if (!resolution.TargetResolved || resolution.Wall is null)
        {
            return EmptyEvidence(resolution);
        }

        Wall wall = resolution.Wall;
        WallType wallType = wall.WallType;
        bool isBasicWall = wallType.Kind == WallKind.Basic;

        IReadOnlyList<string> sameTypeWallUniqueIds = new FilteredElementCollector(document)
            .OfClass(typeof(Wall))
            .Cast<Wall>()
            .Where(candidate => candidate.GetTypeId().Equals(wall.GetTypeId()))
            .Select(candidate => candidate.UniqueId)
            .OrderBy(uniqueId => uniqueId, StringComparer.Ordinal)
            .ToArray();

        bool associativityProven = true;
        IReadOnlyList<string> insertUniqueIds;
        IReadOnlyList<string> joinEnd0UniqueIds;
        IReadOnlyList<string> joinEnd1UniqueIds;
        IReadOnlyList<string> unsupportedDependencyUniqueIds;

        try
        {
            insertUniqueIds = UniqueIds(
                document,
                wall.FindInserts(
                    addRectOpenings: true,
                    includeShadows: true,
                    includeEmbeddedWalls: true,
                    includeSharedEmbeddedInserts: true));
        }
        catch
        {
            insertUniqueIds = Array.Empty<string>();
            associativityProven = false;
        }

        LocationCurve? locationCurve = wall.Location as LocationCurve;
        if (locationCurve is null)
        {
            joinEnd0UniqueIds = Array.Empty<string>();
            joinEnd1UniqueIds = Array.Empty<string>();
            associativityProven = false;
        }
        else
        {
            try
            {
                joinEnd0UniqueIds = JoinedUniqueIds(locationCurve.get_ElementsAtJoin(0), wall);
                joinEnd1UniqueIds = JoinedUniqueIds(locationCurve.get_ElementsAtJoin(1), wall);
            }
            catch
            {
                joinEnd0UniqueIds = Array.Empty<string>();
                joinEnd1UniqueIds = Array.Empty<string>();
                associativityProven = false;
            }
        }

        try
        {
            unsupportedDependencyUniqueIds = SupportedDependencyUniqueIds(document, wall);
        }
        catch
        {
            unsupportedDependencyUniqueIds = Array.Empty<string>();
            associativityProven = false;
        }

        return new WallIsolationEvidence(
            resolution.ApprovedTargetCount,
            resolution.TargetResolved,
            resolution.NativeKindMatches,
            resolution.DocumentMatches,
            isBasicWall,
            wall.UniqueId,
            wallType.UniqueId,
            sameTypeWallUniqueIds,
            insertUniqueIds,
            joinEnd0UniqueIds,
            joinEnd1UniqueIds,
            unsupportedDependencyUniqueIds,
            associativityProven);
    }

    private static WallIsolationEvidence EmptyEvidence(RevitWallTargetResolution resolution)
    {
        return new WallIsolationEvidence(
            resolution.ApprovedTargetCount,
            resolution.TargetResolved,
            resolution.NativeKindMatches,
            resolution.DocumentMatches,
            IsBasicWall: false,
            WallUniqueId: null,
            WallTypeUniqueId: null,
            SameTypeWallUniqueIds: Array.Empty<string>(),
            InsertUniqueIds: Array.Empty<string>(),
            JoinEnd0UniqueIds: Array.Empty<string>(),
            JoinEnd1UniqueIds: Array.Empty<string>(),
            UnsupportedDependencyUniqueIds: Array.Empty<string>(),
            AssociativityProven: false);
    }

    private static IReadOnlyList<string> UniqueIds(Document document, IEnumerable<ElementId> ids)
    {
        return ids
            .Select(document.GetElement)
            .Where(element => element is not null)
            .Select(element => element!.UniqueId)
            .OrderBy(uniqueId => uniqueId, StringComparer.Ordinal)
            .ToArray();
    }

    private static IReadOnlyList<string> JoinedUniqueIds(ElementArray joined, Wall target)
    {
        var uniqueIds = new SortedSet<string>(StringComparer.Ordinal);
        foreach (Element element in joined)
        {
            if (!element.Id.Equals(target.Id))
            {
                uniqueIds.Add(element.UniqueId);
            }
        }

        return uniqueIds.ToArray();
    }

    private static IReadOnlyList<string> SupportedDependencyUniqueIds(Document document, Wall target)
    {
        var uniqueIds = new SortedSet<string>(StringComparer.Ordinal);

        foreach (AttachmentLocation attachmentLocation in new[]
                 {
                     AttachmentLocation.Base,
                     AttachmentLocation.Top,
                 })
        {
            foreach (ElementId attachmentId in target.GetAttachmentIds(attachmentLocation))
            {
                Element? attachment = document.GetElement(attachmentId);
                if (attachment is not null && !attachment.Id.Equals(target.Id))
                {
                    uniqueIds.Add(attachment.UniqueId);
                }
            }
        }

        ElementId hostWallId = target.GetHostWallId();
        if (!hostWallId.Equals(ElementId.InvalidElementId))
        {
            Element? hostWall = document.GetElement(hostWallId);
            if (hostWall is not null && !hostWall.Id.Equals(target.Id))
            {
                uniqueIds.Add(hostWall.UniqueId);
            }
        }

        foreach (Wall candidate in new FilteredElementCollector(document)
                     .OfClass(typeof(Wall))
                     .Cast<Wall>())
        {
            if (candidate.Id.Equals(target.Id))
            {
                continue;
            }

            ElementId candidateHostWallId = candidate.GetHostWallId();
            if (!candidateHostWallId.Equals(ElementId.InvalidElementId)
                && candidateHostWallId.Equals(target.Id))
            {
                uniqueIds.Add(candidate.UniqueId);
            }
        }

        return uniqueIds.ToArray();
    }
}
