namespace Revit.AgentHost.Core.Contracts;

public sealed class WallThicknessEvidence
{
    private WallThicknessEvidence(
        string wallUniqueId,
        string wallTypeUniqueId,
        int editableLayerIndex,
        double widthBeforeInternal,
        double requestedWidthInternal,
        double widthAfterInternal,
        double toleranceInternal,
        long revisionBefore,
        long revisionAfter,
        bool identityInvariantProven,
        bool locationInvariantProven,
        bool relationshipInvariantProven,
        int transactionAttemptCount,
        bool documentChangeObserved)
    {
        WallUniqueId = wallUniqueId;
        WallTypeUniqueId = wallTypeUniqueId;
        EditableLayerIndex = editableLayerIndex;
        WidthBeforeInternal = widthBeforeInternal;
        RequestedWidthInternal = requestedWidthInternal;
        WidthAfterInternal = widthAfterInternal;
        ToleranceInternal = toleranceInternal;
        RevisionBefore = revisionBefore;
        RevisionAfter = revisionAfter;
        IdentityInvariantProven = identityInvariantProven;
        LocationInvariantProven = locationInvariantProven;
        RelationshipInvariantProven = relationshipInvariantProven;
        TransactionAttemptCount = transactionAttemptCount;
        DocumentChangeObserved = documentChangeObserved;
    }

    public string WallUniqueId { get; }
    public string WallTypeUniqueId { get; }
    public int EditableLayerIndex { get; }
    public double WidthBeforeInternal { get; }
    public double RequestedWidthInternal { get; }
    public double WidthAfterInternal { get; }
    public double ToleranceInternal { get; }
    public long RevisionBefore { get; }
    public long RevisionAfter { get; }
    public bool IdentityInvariantProven { get; }
    public bool LocationInvariantProven { get; }
    public bool RelationshipInvariantProven { get; }
    public int TransactionAttemptCount { get; }
    public bool DocumentChangeObserved { get; }

    public static WallThicknessEvidence Create(
        string wallUniqueId,
        string wallTypeUniqueId,
        int editableLayerIndex,
        double widthBeforeInternal,
        double requestedWidthInternal,
        double widthAfterInternal,
        double toleranceInternal,
        long revisionBefore,
        long revisionAfter,
        bool identityInvariantProven,
        bool locationInvariantProven,
        bool relationshipInvariantProven,
        int transactionAttemptCount,
        bool documentChangeObserved)
    {
        if (string.IsNullOrWhiteSpace(wallUniqueId))
        {
            throw new ArgumentException("Wall UniqueId is required.", nameof(wallUniqueId));
        }

        if (string.IsNullOrWhiteSpace(wallTypeUniqueId))
        {
            throw new ArgumentException("WallType UniqueId is required.", nameof(wallTypeUniqueId));
        }

        if (editableLayerIndex < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(editableLayerIndex));
        }

        RequireFinitePositive(widthBeforeInternal, nameof(widthBeforeInternal));
        RequireFinitePositive(requestedWidthInternal, nameof(requestedWidthInternal));
        RequireFinitePositive(widthAfterInternal, nameof(widthAfterInternal));

        if (!double.IsFinite(toleranceInternal) || toleranceInternal < 0.0)
        {
            throw new ArgumentOutOfRangeException(nameof(toleranceInternal));
        }

        if (Math.Abs(widthAfterInternal - requestedWidthInternal) > toleranceInternal)
        {
            throw new InvalidOperationException(
                "Post-read wall width does not match the requested width within tolerance.");
        }

        if (revisionBefore < 0 || revisionAfter < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(revisionBefore));
        }

        if (revisionAfter <= revisionBefore)
        {
            throw new InvalidOperationException(
                "Successful evidence requires revision_after to advance beyond revision_before.");
        }

        if (!identityInvariantProven || !locationInvariantProven || !relationshipInvariantProven)
        {
            throw new InvalidOperationException(
                "Successful evidence requires identity, location, and relationship invariants to be proven.");
        }

        if (transactionAttemptCount != 1)
        {
            throw new InvalidOperationException(
                "Successful evidence requires exactly one transaction attempt.");
        }

        if (!documentChangeObserved)
        {
            throw new InvalidOperationException(
                "Successful evidence requires DocumentChanged attribution.");
        }

        return new WallThicknessEvidence(
            wallUniqueId,
            wallTypeUniqueId,
            editableLayerIndex,
            widthBeforeInternal,
            requestedWidthInternal,
            widthAfterInternal,
            toleranceInternal,
            revisionBefore,
            revisionAfter,
            identityInvariantProven,
            locationInvariantProven,
            relationshipInvariantProven,
            transactionAttemptCount,
            documentChangeObserved);
    }

    private static void RequireFinitePositive(double value, string parameterName)
    {
        if (!double.IsFinite(value) || value <= 0.0)
        {
            throw new ArgumentOutOfRangeException(parameterName);
        }
    }
}
