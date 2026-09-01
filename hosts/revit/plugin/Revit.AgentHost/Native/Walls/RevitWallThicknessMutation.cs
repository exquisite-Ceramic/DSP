using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using Autodesk.Revit.DB;
using Revit.AgentHost.Core.Contracts;
using Revit.AgentHost.Core.Execution;
using Revit.AgentHost.Native.ExternalEvents;

namespace Revit.AgentHost.Native.Walls;

public sealed class RevitWallThicknessMutation : IRevitRequestExecutor
{
    public const string CommitStateUnknown = "REVIT_COMMIT_STATE_UNKNOWN";
    public const string CommittedEffectUnnormalizable = "COMMITTED_EFFECT_UNNORMALIZABLE";

    private readonly IdempotencyStore idempotencyStore;
    private readonly RevitWallTargetResolver targetResolver;
    private readonly RevitWallIsolationProbe isolationProbe;
    private readonly RevitWallThicknessPlanBuilder planBuilder;
    private readonly RevitWallSnapshotReader snapshotReader;

    public RevitWallThicknessMutation(
        IdempotencyStore? idempotencyStore = null,
        RevitWallTargetResolver? targetResolver = null,
        RevitWallIsolationProbe? isolationProbe = null,
        RevitWallThicknessPlanBuilder? planBuilder = null,
        RevitWallSnapshotReader? snapshotReader = null)
    {
        this.idempotencyStore = idempotencyStore ?? new IdempotencyStore();
        this.targetResolver = targetResolver ?? new RevitWallTargetResolver();
        this.isolationProbe = isolationProbe ?? new RevitWallIsolationProbe(this.targetResolver);
        this.planBuilder = planBuilder ?? new RevitWallThicknessPlanBuilder();
        this.snapshotReader = snapshotReader
            ?? new RevitWallSnapshotReader(this.targetResolver, this.isolationProbe);
    }

    public HostResultEnvelope Execute(
        Document document,
        HostCommandEnvelope command,
        long revisionBefore,
        Func<long> readCurrentRevision)
    {
        ArgumentNullException.ThrowIfNull(document);
        ArgumentNullException.ThrowIfNull(command);
        ArgumentNullException.ThrowIfNull(readCurrentRevision);

        try
        {
            ValidateCommandShape(command);
            string idempotencyKey = command.IdempotencyKey!;
            string fingerprint = CommandFingerprint.Compute(command);

            if (idempotencyStore.TryGet(
                    idempotencyKey,
                    fingerprint,
                    out HostResultEnvelope stored))
            {
                return stored with { Replayed = true };
            }

            long expectedRevision = ReadExpectedRevision(command);
            RevisionGate.RequireExpected(revisionBefore, expectedRevision);

            WallIsolationEvidence preflight = isolationProbe.Collect(document, command);
            WallIsolationDecision decision = WallIsolationDecision.Evaluate(preflight);
            if (!decision.IsEligible)
            {
                return BeforeCommitError(
                    command.CommandId,
                    decision.Code ?? WallIsolationDecision.WallAssociativityUnproven,
                    revisionBefore,
                    null);
            }

            RevitWallTargetResolution resolution = targetResolver.Resolve(document, command);
            if (!resolution.TargetResolved || resolution.Wall is null)
            {
                return BeforeCommitError(
                    command.CommandId,
                    WallIsolationDecision.TargetResolutionFailed,
                    revisionBefore,
                    null);
            }

            Wall wall = resolution.Wall;
            WallThicknessArguments arguments = ReadArguments(command);
            double toleranceInternal =
                RevitLengthUnitConverter.MillimetersToInternal(0.000001);

            using RevitWallThicknessCandidate candidate = planBuilder.Build(
                wall.WallType,
                arguments.Thickness.Value,
                toleranceInternal);

            RevitWallSnapshot before = snapshotReader.Read(document, command);

            HostResultEnvelope? transactionFailure = ApplyOneTransaction(
                document,
                wall,
                candidate,
                command.CommandId,
                revisionBefore);
            if (transactionFailure is not null)
            {
                return transactionFailure;
            }

            long revisionAfter = readCurrentRevision();
            if (revisionAfter <= revisionBefore)
            {
                return KnownCommittedError(
                    command.CommandId,
                    revisionAfter,
                    "DocumentChanged did not advance the document revision after the committed transaction.");
            }

            RevitWallSnapshot after;
            WallIsolationEvidence postIsolation;
            try
            {
                after = snapshotReader.Read(document, command);
                postIsolation = isolationProbe.Collect(document, command);
            }
            catch (Exception exception)
            {
                return KnownCommittedError(
                    command.CommandId,
                    revisionAfter,
                    exception.Message);
            }

            WallIsolationDecision postDecision = WallIsolationDecision.Evaluate(postIsolation);
            bool identityInvariantProven =
                string.Equals(before.WallUniqueId, after.WallUniqueId, StringComparison.Ordinal)
                && string.Equals(before.WallTypeUniqueId, after.WallTypeUniqueId, StringComparison.Ordinal);
            bool locationInvariantProven =
                string.Equals(before.LocationSignature, after.LocationSignature, StringComparison.Ordinal);
            bool relationshipInvariantProven =
                postDecision.IsEligible
                && string.Equals(
                    before.RelationshipSignature,
                    after.RelationshipSignature,
                    StringComparison.Ordinal);

            WallThicknessEvidence evidence;
            try
            {
                evidence = WallThicknessEvidence.Create(
                    before.WallUniqueId,
                    before.WallTypeUniqueId,
                    candidate.Plan.EditableLayerIndex,
                    before.WidthInternal,
                    candidate.Plan.RequestedTotalInternal,
                    after.WidthInternal,
                    toleranceInternal,
                    revisionBefore,
                    revisionAfter,
                    identityInvariantProven,
                    locationInvariantProven,
                    relationshipInvariantProven,
                    transactionAttemptCount: 1,
                    documentChangeObserved: true);
            }
            catch (Exception exception)
            {
                return KnownCommittedError(
                    command.CommandId,
                    revisionAfter,
                    exception.Message);
            }

            HostResultEnvelope success = BuildSuccess(
                command,
                arguments,
                before,
                after,
                evidence);
            idempotencyStore.Store(idempotencyKey, fingerprint, success);
            return success;
        }
        catch (IdempotencyConflictException exception)
        {
            return BeforeCommitError(
                command.CommandId,
                exception.Code,
                revisionBefore,
                exception.Message);
        }
        catch (RevisionConflictException exception)
        {
            return BeforeCommitError(
                command.CommandId,
                exception.Code,
                revisionBefore,
                exception.Message);
        }
        catch (WallThicknessPlanningException exception)
        {
            return BeforeCommitError(
                command.CommandId,
                exception.Code,
                revisionBefore,
                exception.Message);
        }
        catch (PrecommitValidationException exception)
        {
            return BeforeCommitError(
                command.CommandId,
                exception.Code,
                revisionBefore,
                exception.Message);
        }
        catch (Exception exception)
        {
            return BeforeCommitError(
                command.CommandId,
                "REVIT_PRECOMMIT_VALIDATION_FAILED",
                revisionBefore,
                exception.Message);
        }
    }

    private static HostResultEnvelope? ApplyOneTransaction(
        Document document,
        Wall wall,
        RevitWallThicknessCandidate candidate,
        string commandId,
        long revisionBefore)
    {
        using Transaction transaction = new Transaction(document, "DSP Set Wall Thickness");
        TransactionStatus startStatus = transaction.Start();
        if (startStatus != TransactionStatus.Started)
        {
            return BeforeCommitError(
                commandId,
                "REVIT_TRANSACTION_NOT_STARTED",
                revisionBefore,
                startStatus.ToString());
        }

        try
        {
            wall.WallType.SetCompoundStructure(candidate.CandidateStructure);
        }
        catch (Exception exception)
        {
            TryRollBack(transaction);
            return BeforeCommitError(
                commandId,
                "REVIT_MUTATION_APPLY_FAILED",
                revisionBefore,
                exception.Message);
        }

        TransactionStatus commitStatus;
        try
        {
            commitStatus = transaction.Commit();
        }
        catch (Exception exception)
        {
            return CommitUnknownError(commandId, revisionBefore, exception.Message);
        }

        if (commitStatus == TransactionStatus.Committed)
        {
            return null;
        }

        if (commitStatus == TransactionStatus.RolledBack)
        {
            return BeforeCommitError(
                commandId,
                "REVIT_TRANSACTION_ROLLED_BACK",
                revisionBefore,
                null);
        }

        return CommitUnknownError(
            commandId,
            revisionBefore,
            $"Unexpected Revit transaction status: {commitStatus}.");
    }

    private static void ValidateCommandShape(HostCommandEnvelope command)
    {
        if (!string.Equals(command.Mode, "EXECUTE", StringComparison.Ordinal)
            || !string.Equals(command.Operation, "set_wall_thickness", StringComparison.Ordinal))
        {
            throw new PrecommitValidationException(
                "REVIT_UNSUPPORTED_COMMAND",
                "Only EXECUTE set_wall_thickness is configured.");
        }

        if (string.IsNullOrWhiteSpace(command.IdempotencyKey))
        {
            throw new PrecommitValidationException(
                "IDEMPOTENCY_KEY_REQUIRED",
                "EXECUTE requires a non-empty idempotency key.");
        }
    }

    private static long ReadExpectedRevision(HostCommandEnvelope command)
    {
        if (command.Preconditions.Count != 1
            || !command.Preconditions[0].TryGetPropertyValue("revision", out JsonNode? revisionNode)
            || revisionNode is null
            || !long.TryParse(
                revisionNode.ToString(),
                NumberStyles.Integer,
                CultureInfo.InvariantCulture,
                out long revision)
            || revision < 0)
        {
            throw new PrecommitValidationException(
                "REVISION_PRECONDITION_REQUIRED",
                "Exactly one non-negative revision precondition is required.");
        }

        return revision;
    }

    private static WallThicknessArguments ReadArguments(HostCommandEnvelope command)
    {
        WallThicknessArguments? arguments =
            command.Arguments.Deserialize<WallThicknessArguments>();

        if (arguments is null
            || arguments.Thickness is null
            || !string.Equals(arguments.Thickness.Unit, "mm", StringComparison.Ordinal)
            || !double.IsFinite(arguments.Thickness.Value)
            || arguments.Thickness.Value <= 0.0)
        {
            throw new PrecommitValidationException(
                WallThicknessPlanner.InvalidWallThickness,
                "Thickness must be a finite positive millimetre value.");
        }

        return arguments;
    }

    private static HostResultEnvelope BuildSuccess(
        HostCommandEnvelope command,
        WallThicknessArguments arguments,
        RevitWallSnapshot before,
        RevitWallSnapshot after,
        WallThicknessEvidence evidence)
    {
        var payload = new JsonObject
        {
            ["wall_unique_id"] = evidence.WallUniqueId,
            ["wall_type_unique_id"] = evidence.WallTypeUniqueId,
            ["editable_layer_index"] = evidence.EditableLayerIndex,
            ["width_before_internal"] = evidence.WidthBeforeInternal,
            ["width_after_internal"] = evidence.WidthAfterInternal,
            ["width_after_mm"] = after.WidthMillimeters,
            ["requested_width_mm"] = arguments.Thickness.Value,
            ["transaction_attempt_count"] = evidence.TransactionAttemptCount,
        };

        var verification = new JsonObject
        {
            ["identity_invariant_proven"] = evidence.IdentityInvariantProven,
            ["location_invariant_proven"] = evidence.LocationInvariantProven,
            ["relationship_invariant_proven"] = evidence.RelationshipInvariantProven,
            ["document_change_observed"] = evidence.DocumentChangeObserved,
            ["revision_before"] = evidence.RevisionBefore,
            ["revision_after"] = evidence.RevisionAfter,
            ["location_signature_before"] = before.LocationSignature,
            ["location_signature_after"] = after.LocationSignature,
            ["relationship_signature_before"] = before.RelationshipSignature,
            ["relationship_signature_after"] = after.RelationshipSignature,
        };

        return new HostResultEnvelope(
            command.CommandId,
            "OK",
            payload,
            null,
            checked((int)evidence.RevisionAfter),
            verification,
            false);
    }

    private static HostResultEnvelope BeforeCommitError(
        string commandId,
        string code,
        long revision,
        string? message)
    {
        return Error(commandId, code, revision, message, commitState: "BEFORE_COMMIT");
    }

    private static HostResultEnvelope CommitUnknownError(
        string commandId,
        long revision,
        string? message)
    {
        return Error(
            commandId,
            CommitStateUnknown,
            revision,
            message,
            commitState: "COMMIT_STATE_UNKNOWN");
    }

    private static HostResultEnvelope KnownCommittedError(
        string commandId,
        long revision,
        string? message)
    {
        return Error(
            commandId,
            CommittedEffectUnnormalizable,
            revision,
            message,
            commitState: "KNOWN_COMMITTED");
    }

    private static HostResultEnvelope Error(
        string commandId,
        string code,
        long revision,
        string? message,
        string commitState)
    {
        var error = new JsonObject
        {
            ["code"] = code,
            ["commit_state"] = commitState,
        };
        if (!string.IsNullOrWhiteSpace(message))
        {
            error["message"] = message;
        }

        return new HostResultEnvelope(
            commandId,
            "ERROR",
            null,
            error,
            checked((int)revision),
            null,
            false);
    }

    private static void TryRollBack(Transaction transaction)
    {
        try
        {
            if (transaction.GetStatus() == TransactionStatus.Started)
            {
                transaction.RollBack();
            }
        }
        catch
        {
            // The mutation did not reach Commit(); preserve the original before-commit failure.
        }
    }

    private sealed class PrecommitValidationException : InvalidOperationException
    {
        public PrecommitValidationException(string code, string message)
            : base(message)
        {
            Code = code;
        }

        public string Code { get; }
    }
}
