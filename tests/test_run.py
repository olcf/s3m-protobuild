from __future__ import annotations

import os
from pathlib import Path

import pytest

from s3m_protobuild import run as run_module
from s3m_protobuild.errors import BuildError


def test_require_commands_hints_about_local_dirs_in_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".go" / "bin").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(BuildError) as exc:
        run_module.require_commands(["protoc-gen-go"], env={"PATH": "/usr/bin"})

    msg = str(exc.value)

    assert "Missing required command(s): protoc-gen-go" in msg
    assert "Hint: .venv and .go exist in this directory." in msg
    assert "Did you mean to pass --venv .venv --go .go?" in msg
    assert "`build`" not in msg


def test_require_commands_skips_hint_when_dir_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    path = f"{venv_bin}{os.pathsep}/usr/bin"

    with pytest.raises(BuildError) as exc:
        run_module.require_commands(["protoc-gen-go"], env={"PATH": path})

    msg = str(exc.value)

    assert "Hint:" not in msg


def test_require_commands_no_hint_without_local_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(BuildError) as exc:
        run_module.require_commands(["protoc-gen-go"], env={"PATH": "/usr/bin"})

    assert "Hint:" not in str(exc.value)


def test_require_python_modules_hints_about_single_local_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_module, "python_executable", lambda env=None: "python3")

    def fake_run(*args, **kwargs):
        return run_module.subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="",
            stderr="ModuleNotFoundError",
        )

    monkeypatch.setattr(run_module.subprocess, "run", fake_run)

    with pytest.raises(BuildError) as exc:
        run_module.require_python_modules(["yaml"], env={"PATH": "/usr/bin"})

    msg = str(exc.value)

    assert "Missing required Python module(s): yaml" in msg
    assert "Hint: .venv exists in this directory." in msg
    assert "Did you mean to pass --venv .venv?" in msg
    assert "`build`" not in msg


def test_env_with_local_tools_strict_raises_on_missing_dirs(tmp_path: Path) -> None:
    with pytest.raises(BuildError, match="Virtual environment bin directory not found"):
        run_module.env_with_local_tools(venv=tmp_path / ".venv")
    with pytest.raises(BuildError, match="Local Go tool bin directory not found"):
        run_module.env_with_local_tools(go_dir=tmp_path / ".go")


def test_env_with_local_tools_non_strict_skips_missing_dirs(tmp_path: Path) -> None:
    env = run_module.env_with_local_tools(
        venv=tmp_path / ".venv", go_dir=tmp_path / ".go", strict=False
    )

    assert env is not None
    assert str(tmp_path / ".venv" / "bin") not in env.get("PATH", "")
    assert str(tmp_path / ".go" / "bin") not in env.get("PATH", "")


def test_env_with_local_tools_non_strict_uses_existing_dirs(tmp_path: Path) -> None:
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    env = run_module.env_with_local_tools(
        venv=tmp_path / ".venv", go_dir=tmp_path / ".go", strict=False
    )

    assert env is not None
    assert str(venv_bin) in env["PATH"]
    assert str(tmp_path / ".go" / "bin") not in env["PATH"]


def test_env_with_writable_go_cache_appends_modcacherw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOFLAGS", "-mod=readonly")

    env = run_module.env_with_writable_go_cache()

    assert env["GOFLAGS"] == "-mod=readonly -modcacherw"


def test_env_with_writable_go_cache_does_not_duplicate_flag() -> None:
    env = run_module.env_with_writable_go_cache(
        {"GOFLAGS": "-mod=readonly -modcacherw"}
    )

    assert env["GOFLAGS"] == "-mod=readonly -modcacherw"


def test_env_with_local_tools_uses_local_go_workspace(tmp_path: Path) -> None:
    go_dir = tmp_path / ".go"
    (go_dir / "bin").mkdir(parents=True)

    env = run_module.env_with_local_tools(go_dir=go_dir)

    assert env is not None
    resolved = go_dir.resolve()

    assert env["PATH"].startswith(str(resolved / "bin") + os.pathsep)
    assert env["GOPATH"] == str(resolved)
    assert env["GOMODCACHE"] == str(resolved / "pkg" / "mod")
    assert env["GOCACHE"] == str(resolved / "cache")
    assert "-modcacherw" in env["GOFLAGS"]
