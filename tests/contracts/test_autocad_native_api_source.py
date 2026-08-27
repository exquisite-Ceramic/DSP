from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "hosts" / "autocad" / "plugin" / "AutoCAD.AgentHost"
ENTITY = (PLUGIN / "Native" / "AutoCADEntityApi.cs").read_text(encoding="utf-8")
VIEW = (PLUGIN / "Native" / "AutoCADViewApi.cs").read_text(encoding="utf-8")
DOCUMENT = (PLUGIN / "Native" / "AutoCADDocumentApi.cs").read_text(encoding="utf-8")
MOVE = (PLUGIN / "Commands" / "Model" / "MoveHandler.cs").read_text(encoding="utf-8")


def test_select_implied_uses_prompt_selection_result_shape():
    assert "selection.Value.Status" not in ENTITY
    assert "selection.Value.Value.GetObjectIds()" not in ENTITY
    assert "selection.Status" in ENTITY
    assert "selection.Value.GetObjectIds()" in ENTITY


def test_handles_resolve_through_database_get_object_id():
    assert "Handle.TryParse" not in ENTITY
    assert "transaction.GetObjectId" not in ENTITY
    assert "Handle.TryParse" not in VIEW
    assert "transaction.GetObjectId" not in VIEW
    assert "database.GetObjectId(false, new Handle(raw), 0)" in ENTITY


def test_view_fit_uses_current_view_api():
    assert "doc.Database.Extents" not in VIEW
    assert "extents.IsNull" not in VIEW
    assert ".Editor.Zoom(" not in VIEW
    assert "using Autodesk.AutoCAD.Geometry;" in VIEW
    assert ".Extmin" in VIEW
    assert ".Extmax" in VIEW
    assert "GetCurrentView()" in VIEW
    assert "SetCurrentView(" in VIEW


def test_change_handlers_adapt_autocad_delegate_types_and_detach():
    assert "ObjectEventHandler" in DOCUMENT
    assert "ObjectErasedEventHandler" in DOCUMENT
    assert "ObjectModified -=" in DOCUMENT
    assert "ObjectErased -=" in DOCUMENT
    assert "ObjectAppended -=" in DOCUMENT


def test_move_does_not_wrap_native_translate_in_second_transaction():
    assert "TransactionRunner.Run" not in MOVE
    assert "Native.AutoCADEntityApi.Translate(" in MOVE
