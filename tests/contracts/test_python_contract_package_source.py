from pathlib import Path
import tomllib


def test_host_contracts_has_editable_package_metadata():
    project_file = Path("contracts/python/pyproject.toml")
    assert project_file.exists(), "contracts/python must be an installable Python project"

    project = tomllib.loads(project_file.read_text(encoding="utf-8"))
    assert project["project"]["name"] == "host-contracts"
    assert project["project"]["version"] == "0.1.0"
    assert project["build-system"]["build-backend"] == "setuptools.build_meta"


def test_grpc_conformance_installs_local_python_packages():
    workflow = Path(".github/workflows/grpc-transport-conformance.yml").read_text(
        encoding="utf-8"
    )
    assert "pip install -e contracts/python" in workflow
    assert "pip install -e hosts/autocad/sidecar" in workflow
