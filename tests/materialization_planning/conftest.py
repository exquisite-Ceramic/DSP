import pytest

from tests.materialization_planning._support import build_case


@pytest.fixture
def phase_i_case():
    return build_case()
