from __future__ import annotations

import pytest

from s3m_protobuild import build as build_module


@pytest.fixture
def stub_go_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        build_module, "require_go_tools", lambda all_sources, env=None: env or {}
    )
