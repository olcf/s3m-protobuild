from __future__ import annotations

from pathlib import Path

import pytest

from _helpers import make_module_config

from s3m_protobuild import metadata
from s3m_protobuild.model import Artifact, ArtifactKey, Source


def fake_run(args: list[str], cwd: Path | None = None, **kwargs) -> str:
    _ = cwd, kwargs
    if args == ["protoc", "--version"]:
        return "libprotoc 31.1\n"
    if args == ["go", "version"]:
        return "go version go1.23.4 darwin/arm64\n"
    if args == ["go", "list", "-m", "all"]:
        return "example.com/s3m-apis v1.2.3\ngoogle.golang.org/protobuf v1.36.11\n"
    raise AssertionError(f"unexpected command: {args}")


def _build_info(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, targets: list[str]
) -> str:
    monkeypatch.setattr(metadata, "run", fake_run)
    source = Source(name="s3m-apis", root=tmp_path, config=make_module_config())
    artifacts = [
        Artifact(ArtifactKey("combined", target), source=source, output_root=tmp_path)
        for target in targets
    ]
    path = metadata.write_build_info(
        tmp_path, sources=[], selectors=[], artifacts=artifacts, tool_env={}
    )
    return path.read_text()


def test_descriptor_target_logs_protoc_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = _build_info(tmp_path, monkeypatch, ["descriptor"])
    assert "tooling.protoc.version: libprotoc 31.1" in info


def test_go_and_descriptor_log_protoc_version_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = _build_info(tmp_path, monkeypatch, ["go", "descriptor"])
    assert info.count("tooling.protoc.version:") == 1
    assert "tooling.go.version: " in info


def test_go_only_does_not_log_protoc_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = _build_info(tmp_path, monkeypatch, ["go"])
    assert "tooling.protoc.version" not in info
