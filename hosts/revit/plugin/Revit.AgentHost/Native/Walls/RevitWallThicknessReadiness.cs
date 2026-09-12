using System.Text.Json;
using System.Text.Json.Nodes;
using Autodesk.Revit.DB;
using Revit.AgentHost.Core.Contracts;
using Revit.AgentHost.Core.Execution;
using Revit.AgentHost.Native.ExternalEvents;

namespace Revit.AgentHost.Native.Walls;

public sealed class RevitWallThicknessReadiness : IRevitRequestExecutor
{
    private readonly RevitWallTargetResolver targetResolver;
    private readonly RevitWallIsolationProbe isolationProbe;
    private readonly RevitWallThicknessPlanBuilder planBuilder;
    private readonly RevitWallSnapshotReader snapshotReader;

    public RevitWallThicknessReadiness(
        RevitWallTargetResolver? targetResolver = null,
        RevitWallIsolationProbe? isolationProbe = null,
        RevitWallThicknessPlanBuilder? planBuilder = null,
        RevitWallSnapshotReader? snapshotReader = null)
    {
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
            WallThicknessArguments arguments = ReadArguments(command);

            WallIsolationEvidence isolation = isolationProbe.Collect(document, command);
            WallIsolationDecision decision = WallIsolationDecision.Evaluate(isolation);
            if (!decision.IsEligible)
            {
                return Error(
                    command.CommandId,
                    decision.Code ?? WallIsolationDecision.WallAssociativityUnproven,
                    revisionBefore,
                    null);
            }

            RevitWallTargetResolution resolution = targetResolver.Resolve(document, command);
            if (!resolution.TargetResolved || resolution.Wall is null)
            {
                return Error(
                    command.CommandId,
                    WallIsolationDecision.TargetResolutionFailed,
                    revisionBefore,
                    null);
            }

            Wall wall = resolution.Wall;
            if (!string.Equals(
                    wall.UniqueId,
                    command.TargetNativeRefs[0].NativeId,
                    StringComparison.Ordinal))
            {
                return Error(
                    command.CommandId,
                    WallIsolationDecision.TargetResolutionFailed,
                    revisionBefore,
                    "解析后的 Revit UniqueId 与授权 native target 不一致。");
            }

            double toleranceInternal =
                RevitLengthUnitConverter.MillimetersToInternal(0.000001);
            using RevitWallThicknessCandidate candidate = planBuilder.Build(
                wall.WallType,
                arguments.Thickness.Value,
                toleranceInternal);

            RevitWallSnapshot snapshot = snapshotReader.Read(document, command);
            long revisionAfter = readCurrentRevision();
            if (revisionAfter != revisionBefore)
            {
                return Error(
                    command.CommandId,
                    "REVIT_READINESS_REVISION_CHANGED",
                    revisionAfter,
                    "只读 readiness 期间文档 revision 已变化。");
            }

            return Success(
                command,
                wall,
                snapshot,
                arguments,
                revisionAfter);
        }
        catch (WallThicknessPlanningException exception)
        {
            return Error(command.CommandId, exception.Code, revisionBefore, exception.Message);
        }
        catch (ReadinessValidationException exception)
        {
            return Error(command.CommandId, exception.Code, revisionBefore, exception.Message);
        }
        catch (Exception exception)
        {
            return Error(
                command.CommandId,
                "REVIT_READINESS_FAILED",
                revisionBefore,
                exception.Message);
        }
    }

    private static void ValidateCommandShape(HostCommandEnvelope command)
    {
        if (!string.Equals(command.Mode, "READ", StringComparison.Ordinal)
            || !string.Equals(
                command.Operation,
                "check_wall_thickness_readiness",
                StringComparison.Ordinal))
        {
            throw new ReadinessValidationException(
                "REVIT_READINESS_UNSUPPORTED_COMMAND",
                "只支持 READ/check_wall_thickness_readiness。");
        }

        if (!string.IsNullOrWhiteSpace(command.IdempotencyKey))
        {
            throw new ReadinessValidationException(
                "REVIT_READINESS_IDEMPOTENCY_FORBIDDEN",
                "只读 readiness 不接受 idempotency_key。");
        }

        if (command.Preconditions.Count != 0)
        {
            throw new ReadinessValidationException(
                "REVIT_READINESS_PRECONDITION_FORBIDDEN",
                "只读 readiness 不接受 mutation precondition。");
        }
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
            throw new ReadinessValidationException(
                WallThicknessPlanner.InvalidWallThickness,
                "墙厚必须是有限、正值且单位为 mm。");
        }

        return arguments;
    }

    private static HostResultEnvelope Success(
        HostCommandEnvelope command,
        Wall wall,
        RevitWallSnapshot snapshot,
        WallThicknessArguments arguments,
        long revision)
    {
        var payload = new JsonObject
        {
            ["document_id"] = command.DocumentId,
            ["wall_unique_id"] = wall.UniqueId,
            ["wall_type_unique_id"] = snapshot.WallTypeUniqueId,
            ["current_width"] = new JsonObject
            {
                ["value"] = snapshot.WidthMillimeters,
                ["unit"] = "mm",
            },
            ["requested_width"] = new JsonObject
            {
                ["value"] = arguments.Thickness.Value,
                ["unit"] = "mm",
            },
            ["isolation_ready"] = true,
            ["plan_ready"] = true,
        };

        return new HostResultEnvelope(
            command.CommandId,
            "OK",
            payload,
            null,
            checked((int)revision),
            null,
            false);
    }

    private static HostResultEnvelope Error(
        string commandId,
        string code,
        long revision,
        string? message)
    {
        var error = new JsonObject
        {
            ["code"] = code,
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

    private sealed class ReadinessValidationException : InvalidOperationException
    {
        public ReadinessValidationException(string code, string message)
            : base(message)
        {
            Code = code;
        }

        public string Code { get; }
    }
}
