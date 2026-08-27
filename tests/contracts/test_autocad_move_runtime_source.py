from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTITY = (
    ROOT
    / "hosts"
    / "autocad"
    / "plugin"
    / "AutoCAD.AgentHost"
    / "Native"
    / "AutoCADEntityApi.cs"
).read_text(encoding="utf-8")


def test_move_verification_reads_a_real_position_for_general_entities():
    assert "entity.GeometricExtents" in ENTITY
    assert "extents.MinPoint" in ENTITY
    assert "extents.MaxPoint" in ENTITY


def test_move_revision_bumps_the_active_document_identity():
    assert "AutoCADDocumentApi.BumpRevision(database.Filename)" not in ENTITY
    assert "AutoCADDocumentApi.BumpRevision(doc.Name)" in ENTITY
