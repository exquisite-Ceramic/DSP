from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
NATIVE_ROOT = REPO_ROOT / "hosts/revit/plugin/Revit.AgentHost/Native"
CONTEXT_READER = NATIVE_ROOT / "Context/RevitContextIdentityReader.cs"
RUNTIME_IDENTITY = NATIVE_ROOT / "Context/RevitRuntimeIdentity.cs"
SNAPSHOT_READ = NATIVE_ROOT / "Walls/RevitWallThicknessSnapshotRead.cs"
SNAPSHOT_READER = NATIVE_ROOT / "Walls/RevitWallSnapshotReader.cs"
ROUTER = NATIVE_ROOT / "ExternalEvents/RevitRequestExecutorRouter.cs"
PLUGIN = NATIVE_ROOT / "PluginEntry.cs"


def test_revit_host_identity_has_one_shared_process_lifetime_owner() -> None:
    """context READ 与 post-commit READ 必须引用同一个 process-lifetime Host identity。"""

    assert RUNTIME_IDENTITY.is_file()
    runtime_text = RUNTIME_IDENTITY.read_text(encoding="utf-8")
    context_text = CONTEXT_READER.read_text(encoding="utf-8")

    assert 'public static class RevitRuntimeIdentity' in runtime_text
    assert 'public static string HostInstanceId' in runtime_text
    assert 'revit-{Guid.NewGuid():N}' in runtime_text
    assert 'RevitRuntimeIdentity.HostInstanceId' in context_text
    assert 'private static readonly string HostInstanceId' not in context_text
    assert 'Guid.NewGuid()' not in context_text


def test_wall_snapshot_read_is_dedicated_read_only_handler_reusing_existing_reader() -> None:
    """新能力只能封装独立 READ evidence，不能复制 mutation 或墙体读取算法。"""

    assert SNAPSHOT_READER.is_file()
    assert SNAPSHOT_READ.is_file()
    text = SNAPSHOT_READ.read_text(encoding="utf-8")

    for required in (
        'public const string Operation = "read_wall_thickness_snapshot"',
        'string.Equals(command.Mode, "READ", StringComparison.Ordinal)',
        'snapshotReader.Read(document, command)',
        'RevitRuntimeIdentity.HostInstanceId',
        '"native_kind"',
        '"Wall"',
        '"builtin_category"',
        '"OST_Walls"',
        '"wall_thickness_mm"',
        '"revision_before"',
        '"revision_after"',
        '"REVIT_SNAPSHOT_REVISION_CHANGED"',
    ):
        assert required in text

    for forbidden in (
        'new Transaction(',
        '.Commit()',
        'SetCompoundStructure',
        'GetCompoundStructure()',
        'GetWidth()',
    ):
        assert forbidden not in text


def test_wall_snapshot_read_rejects_mutation_shape_and_requires_exactly_one_target() -> None:
    """专用 READ contract 必须保持 empty arguments/preconditions/no-idempotency/one target。"""

    assert SNAPSHOT_READ.is_file()
    text = SNAPSHOT_READ.read_text(encoding="utf-8")

    for required in (
        'command.TargetNativeRefs.Count != 1',
        'command.Arguments.Count != 0',
        'command.Preconditions.Count != 0',
        '!string.IsNullOrWhiteSpace(command.IdempotencyKey)',
    ):
        assert required in text


def test_router_and_plugin_wire_snapshot_read_without_renaming_existing_routes() -> None:
    """新增 READ route 不能改变既有 readiness / mutation public operation。"""

    router_text = ROUTER.read_text(encoding="utf-8")
    plugin_text = PLUGIN.read_text(encoding="utf-8")

    assert 'RevitWallThicknessSnapshotRead snapshotRead' in router_text
    assert 'RevitWallThicknessSnapshotRead.Operation' in router_text
    assert 'snapshotRead.Execute(' in router_text
    assert '"check_wall_thickness_readiness"' in router_text
    assert '"set_wall_thickness"' in router_text

    assert 'new RevitWallThicknessSnapshotRead()' in plugin_text
    assert 'new RevitWallThicknessReadiness()' in plugin_text
    assert 'new RevitWallThicknessMutation()' in plugin_text
