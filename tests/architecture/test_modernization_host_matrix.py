from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs" / "superpowers" / "modernization" / "host-compatibility-matrix.md"
AUTOCAD_PROJECT = ROOT / "hosts" / "autocad" / "plugin" / "AutoCAD.AgentHost" / "AutoCAD.AgentHost.csproj"
REVIT_PROJECT = ROOT / "hosts" / "revit" / "plugin" / "Revit.AgentHost" / "Revit.AgentHost.csproj"

COLUMNS = (
    "Host surface",
    "Product / version",
    "Vendor runtime",
    "SDK / API assembly source",
    "DSP TFM",
    "Build SDK",
    "Offline / Core evidence",
    "Native build evidence",
    "Real Host acceptance evidence",
    "Support status",
)


def _support_rows() -> list[dict[str, str]]:
    lines = MATRIX.read_text(encoding="utf-8").splitlines()
    header = "| " + " | ".join(COLUMNS) + " |"
    header_index = lines.index(header)

    rows: list[dict[str, str]] = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        values = [value.strip() for value in line.strip().strip("|").split("|")]
        assert len(values) == len(COLUMNS), f"unexpected host-matrix column count: {line}"
        rows.append(dict(zip(COLUMNS, values, strict=True)))
    return rows


def test_supported_host_rows_are_complete_and_real_host_backed() -> None:
    rows = _support_rows()
    supported = {row["Product / version"]: row for row in rows if row["Support status"] == "SUPPORTED"}

    assert "AutoCAD 2025" in supported
    assert "Revit 2027" in supported

    required_fields = (
        "Host surface",
        "Product / version",
        "Vendor runtime",
        "SDK / API assembly source",
        "DSP TFM",
        "Build SDK",
        "Offline / Core evidence",
        "Native build evidence",
        "Real Host acceptance evidence",
        "Support status",
    )
    for product, row in supported.items():
        for field in required_fields:
            value = row[field]
            assert value, f"{product} missing {field}"
            assert value.upper() != "N/A", f"{product} cannot use N/A for {field}"
        assert row["Real Host acceptance evidence"].upper() != "NOT VERIFIED"


def test_native_projects_keep_host_owned_build_boundaries() -> None:
    autocad = AUTOCAD_PROJECT.read_text(encoding="utf-8")
    assert "<TargetFramework>net8.0-windows</TargetFramework>" in autocad
    assert "$(AUTOCAD_ACAD_DIR)" in autocad
    for assembly in ("AcCoreMgd.dll", "AcDbMgd.dll", "AcMgd.dll"):
        assert assembly in autocad

    revit = REVIT_PROJECT.read_text(encoding="utf-8")
    assert "<TargetFramework>$(DspRevitTargetFramework)</TargetFramework>" in revit
    assert "DspRevitVersion must be supplied" in revit
    assert "DspRevitTargetFramework must be supplied" in revit
    assert "DspRevitApiDir must be supplied" in revit
    assert "$(DspRevitApiDir)\\RevitAPI.dll" in revit
    assert "$(DspRevitApiDir)\\RevitAPIUI.dll" in revit
