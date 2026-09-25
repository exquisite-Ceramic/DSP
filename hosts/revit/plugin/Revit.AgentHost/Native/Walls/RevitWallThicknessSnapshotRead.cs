using System.Text.Json.Nodes;
using Autodesk.Revit.DB;
using Revit.AgentHost.Core.Contracts;
using Revit.AgentHost.Native.Context;
using Revit.AgentHost.Native.ExternalEvents;

namespace Revit.AgentHost.Native.Walls;

/// <summary>
/// 为 Step33 mandatory verification 提供独立、只读的墙厚快照。
/// 该 handler 只负责 command/evidence correlation，不复制 RevitWallSnapshotReader 的模型读取算法。
/// </summary>
public sealed class RevitWallThicknessSnapshotRead : IRevitRequestExecutor
{
    public const string Operation = "read_wall_thickness_snapshot";

    private readonly RevitWallSnapshotReader snapshotReader;

    public RevitWallThicknessSnapshotRead(RevitWallSnapshotReader? snapshotReader = null)
    {
        this.snapshotReader = snapshotReader ?? new RevitWallSnapshotReader();
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
            ValidateCommandShape(document, command);
            RevitWallSnapshot snapshot = snapshotReader.Read(document, command);
            long revisionAfter = readCurrentRevision();
            if (revisionAfter != revisionBefore)
            {
                return Error(
                    command.CommandId,
                    "REVIT_SNAPSHOT_REVISION_CHANGED",
                    revisionAfter,
                    "独立墙厚 READ 期间文档 revision 已变化，证据不能归属本次 commit。");
            }

            return Success(document, command, snapshot, revisionBefore, revisionAfter);
        }
        catch (SnapshotReadValidationException exception)
        {
            return Error(command.CommandId, exception.Code, revisionBefore, exception.Message);
        }
        catch (Exception exception)
        {
            return Error(
                command.CommandId,
                "REVIT_SNAPSHOT_READ_FAILED",
                revisionBefore,
                exception.Message);
        }
    }

    private static void ValidateCommandShape(Document document, HostCommandEnvelope command)
    {
        if (!string.Equals(command.Mode, "READ", StringComparison.Ordinal)
            || !string.Equals(command.Operation, Operation, StringComparison.Ordinal))
        {
            throw new SnapshotReadValidationException(
                "REVIT_SNAPSHOT_READ_UNSUPPORTED_COMMAND",
                "只支持 READ/read_wall_thickness_snapshot。");
        }

        if (command.TargetNativeRefs.Count != 1)
        {
            throw new SnapshotReadValidationException(
                "REVIT_SNAPSHOT_TARGET_INVALID",
                "独立墙厚 READ 必须且只能包含一个 Wall UniqueId target。");
        }

        if (command.Arguments.Count != 0)
        {
            throw new SnapshotReadValidationException(
                "REVIT_SNAPSHOT_ARGUMENTS_FORBIDDEN",
                "独立墙厚 READ 不接受 mutation arguments。");
        }

        if (command.Preconditions.Count != 0)
        {
            throw new SnapshotReadValidationException(
                "REVIT_SNAPSHOT_PRECONDITION_FORBIDDEN",
                "独立墙厚 READ 不接受 mutation preconditions。");
        }

        if (!string.IsNullOrWhiteSpace(command.IdempotencyKey))
        {
            throw new SnapshotReadValidationException(
                "REVIT_SNAPSHOT_IDEMPOTENCY_FORBIDDEN",
                "独立墙厚 READ 不接受 idempotency_key。");
        }

        string actualDocumentId = RevitContextIdentityReader.ReadDocumentId(document);
        HostNativeRef target = command.TargetNativeRefs[0];
        if (!string.Equals(command.DocumentId, actualDocumentId, StringComparison.Ordinal)
            || !string.Equals(target.DocumentId, actualDocumentId, StringComparison.Ordinal)
            || !string.Equals(target.NativeType, "Wall", StringComparison.Ordinal)
            || string.IsNullOrWhiteSpace(target.NativeId))
        {
            throw new SnapshotReadValidationException(
                "REVIT_SNAPSHOT_TARGET_INVALID",
                "独立墙厚 READ 的 document/native target 与当前 Revit 文档不一致。");
        }
    }

    private static HostResultEnvelope Success(
        Document document,
        HostCommandEnvelope command,
        RevitWallSnapshot snapshot,
        long revisionBefore,
        long revisionAfter)
    {
        var payload = new JsonObject
        {
            ["document_id"] = RevitContextIdentityReader.ReadDocumentId(document),
            ["host_instance_id"] = RevitRuntimeIdentity.HostInstanceId,
            ["wall_unique_id"] = snapshot.WallUniqueId,
            ["wall_type_unique_id"] = snapshot.WallTypeUniqueId,
            ["native_kind"] = "Wall",
            ["builtin_category"] = "OST_Walls",
            ["wall_thickness_mm"] = snapshot.WidthMillimeters,
            ["location_signature"] = snapshot.LocationSignature,
            ["relationship_signature"] = snapshot.RelationshipSignature,
            ["revision_before"] = revisionBefore,
            ["revision_after"] = revisionAfter,
        };

        return new HostResultEnvelope(
            command.CommandId,
            "OK",
            payload,
            null,
            checked((int)revisionAfter),
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

    private sealed class SnapshotReadValidationException : InvalidOperationException
    {
        public SnapshotReadValidationException(string code, string message)
            : base(message)
        {
            Code = code;
        }

        public string Code { get; }
    }
}
