"""Product Runtime 测试共享 fixture。"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def product_task_postgres_dsn() -> str:
    """仅 PostgreSQL 用例需要 DSN；缺失时不影响 deterministic ProductTask tests。"""

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn
