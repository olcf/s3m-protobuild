from __future__ import annotations

from pathlib import Path

import pytest

from s3m_protobuild import diag, toolchain
from s3m_protobuild.errors import BuildError


def test_python_setup_requires_venv() -> None:
    with pytest.raises(BuildError, match=r"`setup python` requires --venv"):
        toolchain.setup_local_tools(None, None, python=True, go=False)


def test_go_setup_requires_go_dir() -> None:
    with pytest.raises(BuildError, match=r"`setup go` requires --go"):
        toolchain.setup_local_tools(None, None, python=False, go=True)


def test_python_setup_installs_pinned_deps_in_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venv = tmp_path / ".venv"
    bin_dir = venv / "bin"
    bin_dir.mkdir(parents=True)
    (venv / "pyvenv.cfg").touch()
    python_bin = bin_dir / "python"
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_: object) -> None:
        calls.append(args)

    monkeypatch.setattr(toolchain.sys, "platform", "linux")
    monkeypatch.setattr(toolchain, "run", fake_run)

    toolchain.setup_local_tools(venv, None, python=True, go=False)

    expected = [str(python_bin), *"-m pip install".split()]
    expected.extend(["--disable-pip-version-check", *toolchain.PYTHON_BUILD_DEPS])

    assert calls == [expected]


def test_python_setup_refuses_directory_that_is_not_a_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bogus = tmp_path / "not-a-venv"
    bogus.mkdir()
    monkeypatch.setattr(toolchain, "run", lambda *a, **k: None)

    with pytest.raises(BuildError) as exc:
        toolchain.setup_local_tools(bogus, None, python=True, go=False)

    msg = str(exc.value)

    assert str(bogus) in msg
    assert "not a Python virtualenv" in msg
    assert "pyvenv.cfg" in msg


def test_go_setup_installs_pinned_tools_under_go_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    go_dir = tmp_path / ".go"
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(args: list[str], *, env: dict[str, str], **_: object) -> None:
        calls.append((args, env))

    monkeypatch.setattr(toolchain, "run", fake_run)
    monkeypatch.setattr(
        toolchain.shutil,
        "which",
        lambda command, path=None: "/usr/bin/" + command,
    )

    toolchain.setup_local_tools(None, go_dir, python=False, go=True)

    assert [args for args, _ in calls] == [
        ["go", "install", tool] for tool in toolchain.GO_BUILD_TOOLS
    ]
    assert any("protoc-gen-oas@" in tool for tool in toolchain.GO_BUILD_TOOLS)

    for _, env in calls:
        assert env["GOBIN"] == str((go_dir / "bin").resolve())
        assert env["GOPATH"] == str(go_dir.resolve())
        assert env["GOMODCACHE"] == str((go_dir / "pkg" / "mod").resolve())
        assert env["GOCACHE"] == str((go_dir / "cache").resolve())
        assert "-modcacherw" in env["GOFLAGS"]


def test_env_checks_protoc_gen_oas(monkeypatch: pytest.MonkeyPatch) -> None:
    checked: list[str] = []

    def fake_which(command: str, path: str | None = None) -> str | None:
        checked.append(command)
        assert path == "local"

    monkeypatch.setattr(
        diag,
        "env_with_local_tools",
        lambda venv=None, go_dir=None, strict=True: {"PATH": "local"},
    )
    monkeypatch.setattr(toolchain.shutil, "which", fake_which)
    monkeypatch.setattr(diag, "_python_module_present", lambda *a, **k: False)

    result = diag.env_diag(Path(".venv"), Path(".go"))

    assert "protoc-gen-oas" in checked
    assert "protoc-gen-oas: missing" in result
    assert "s3m-protobuild setup go --go .go" in result


def test_env_prints_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {
        "protoc": "libprotoc 25.1",
        "go": "go version go1.22.0 darwin/arm64",
        "protoc-gen-go": "protoc-gen-go v1.36.11",
        "protoc-gen-go-grpc": "protoc-gen-go-grpc 1.6.1",
        "protoc-gen-grpc-gateway": "Version v2.29.0, commit abc",
        "protoc-go-inject-tag": "protoc-go-inject-tag v1.4.0",
        "protoc-gen-oas": "protoc-gen-oas 0.14.0",
        "protoc-gen-python_betterproto": "",
    }

    expected_args = {
        name: ("version",) if name == "go" else ("--version",) for name in versions
    }
    seen: list[tuple[str, tuple[str, ...]]] = []

    monkeypatch.setattr(
        diag,
        "env_with_local_tools",
        lambda venv=None, go_dir=None, strict=True: {"PATH": "local"},
    )
    monkeypatch.setattr(
        toolchain.shutil, "which", lambda command, path=None: f"/usr/bin/{command}"
    )

    def fake_run(args, **kwargs):
        # Module-import probes use `python -c "import X"`; return rc=0.
        if len(args) >= 3 and args[1] == "-c" and args[2].startswith("import "):
            return diag.subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        binary = Path(args[0]).name
        seen.append((binary, tuple(args[1:])))
        assert kwargs["stdin"] is diag.subprocess.DEVNULL
        return diag.subprocess.CompletedProcess(
            args, 0, stdout=versions[binary] + "\n", stderr=""
        )

    monkeypatch.setattr(diag.subprocess, "run", fake_run)

    result = diag.env_diag()

    for name, version in versions.items():
        assert (name, expected_args[name]) in seen
        expected_line = f"{name}: {version or 'ok'}"
        assert expected_line in result

    for module in toolchain.PYTHON_BUILD_MODULES:
        assert f"{module} (Python module): ok" in result


def test_go_setup_fails_clearly_when_go_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(toolchain, "run", lambda *a, **k: None)
    monkeypatch.setattr(toolchain.shutil, "which", lambda command, path=None: None)

    with pytest.raises(BuildError) as exc:
        toolchain.setup_local_tools(None, tmp_path / ".go", python=False, go=True)

    msg = str(exc.value)

    assert "`go` is required but not on PATH" in msg
    # Hint must include both the package-manager and manual-download options.
    assert "go.dev/dl" in msg


def test_install_hints_include_url_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(toolchain.sys, "platform", "linux")
    monkeypatch.setattr(
        toolchain.platform,
        "freedesktop_os_release",
        lambda: {"ID": "ubuntu", "ID_LIKE": "debian"},
    )

    protoc_hint = toolchain.system_install_guidance("protoc")
    go_hint = toolchain.system_install_guidance("go")

    assert "apt-get install protobuf-compiler" in protoc_hint
    assert "github.com/protocolbuffers/protobuf/releases" in protoc_hint
    assert "apt-get install golang-go" in go_hint
    assert "go.dev/dl" in go_hint


def test_install_hints_fallback_includes_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(toolchain.sys, "platform", "freebsd")

    protoc_hint = toolchain.system_install_guidance("protoc")
    go_hint = toolchain.system_install_guidance("go")

    assert "github.com/protocolbuffers/protobuf/releases" in protoc_hint
    assert "go.dev/dl" in go_hint


def test_post_setup_warns_about_missing_protoc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    go_dir = tmp_path / ".go"
    monkeypatch.setattr(toolchain, "run", lambda *a, **k: None)
    monkeypatch.setattr(
        toolchain.shutil,
        "which",
        lambda command, path=None: (
            None if command == "protoc" else f"/usr/bin/{command}"
        ),
    )

    toolchain.setup_local_tools(None, go_dir, python=False, go=True)

    stderr = capsys.readouterr().err
    assert "`protoc` is not on PATH" in stderr
    assert f"--go {go_dir}" in stderr


def test_post_setup_silent_when_protoc_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").touch()
    monkeypatch.setattr(toolchain.sys, "platform", "linux")
    monkeypatch.setattr(toolchain, "run", lambda *a, **k: None)
    monkeypatch.setattr(
        toolchain.shutil, "which", lambda command, path=None: "/usr/bin/protoc"
    )

    toolchain.setup_local_tools(venv, None, python=True, go=False)

    stderr = capsys.readouterr().err
    assert "`protoc` is not on PATH" not in stderr
    assert f"--venv {venv}" in stderr


def test_env_hints_when_cwd_has_local_dirs_but_flags_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".go" / "bin").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(toolchain.shutil, "which", lambda command, path=None: None)
    monkeypatch.setattr(diag, "_python_module_present", lambda *a, **k: True)

    result = diag.env_diag()

    assert ".venv and .go exist in this directory" in result
    assert "--venv .venv --go .go" in result


def test_env_skips_cwd_hint_when_flags_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".go" / "bin").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(toolchain.shutil, "which", lambda command, path=None: None)
    monkeypatch.setattr(diag, "_python_module_present", lambda *a, **k: True)

    result = diag.env_diag(venv=tmp_path / ".venv", go_dir=tmp_path / ".go")

    assert "exist in this directory" not in result


def test_env_reports_missing_python_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        diag,
        "env_with_local_tools",
        lambda venv=None, go_dir=None, strict=True: {"PATH": "local"},
    )
    monkeypatch.setattr(
        toolchain.shutil, "which", lambda command, path=None: f"/bin/{command}"
    )
    monkeypatch.setattr(
        diag.subprocess,
        "run",
        lambda *a, **k: diag.subprocess.CompletedProcess(
            a[0], 0, stdout="x\n", stderr=""
        ),
    )
    monkeypatch.setattr(
        diag,
        "_python_module_present",
        lambda python, module, env: module != "grpc_tools.protoc",
    )

    result = diag.env_diag()

    assert "grpc_tools.protoc (Python module): missing" in result
    assert "betterproto (Python module): ok" in result
    assert "yaml (Python module): ok" in result


def test_env_warns_when_setup_dirs_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(toolchain.shutil, "which", lambda command, path=None: None)
    monkeypatch.setattr(diag, "_python_module_present", lambda *a, **k: True)

    result = diag.env_diag(tmp_path / ".venv", tmp_path / ".go")

    venv_bin = tmp_path / ".venv" / "bin"
    go_bin = tmp_path / ".go" / "bin"

    assert f"{venv_bin} not found" in result
    assert f"setup python --venv {tmp_path / '.venv'}" in result
    assert f"{go_bin} not found" in result
    assert f"setup go --go {tmp_path / '.go'}" in result
    assert "protoc: missing" in result


def test_env_consolidates_missing_tools_into_to_fix_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diag,
        "env_with_local_tools",
        lambda venv=None, go_dir=None, strict=True: {"PATH": "local"},
    )
    # protoc/go on PATH; all plugins missing.
    monkeypatch.setattr(
        toolchain.shutil,
        "which",
        lambda command, path=None: (
            f"/bin/{command}" if command in {"protoc", "go"} else None
        ),
    )

    def fake_run(args, **_):
        return diag.subprocess.CompletedProcess(args, 0, stdout="1.0\n", stderr="")

    monkeypatch.setattr(diag.subprocess, "run", fake_run)
    monkeypatch.setattr(diag, "_python_module_present", lambda *a, **k: False)

    result = diag.env_diag()

    # Per-line listing has no inline hint anymore.
    def line_for(name: str) -> list[str]:
        return [line for line in result.splitlines() if line == f"{name}: missing"]

    assert line_for("protoc-gen-go"), result
    assert line_for("protoc-gen-go-grpc"), result

    # One consolidated "To fix:" block at the bottom, with per-hint groupings.
    assert "\nTo fix:\n" in "\n" + result + "\n"
    fix_section = result.split("To fix:\n", 1)[1]
    assert "Run `s3m-protobuild setup go --go .go`." in fix_section
    assert (
        "installs: protoc-gen-go, protoc-gen-go-grpc, "
        "protoc-gen-grpc-gateway, protoc-go-inject-tag, protoc-gen-oas"
    ) in fix_section
    assert "Run `s3m-protobuild setup python --venv .venv`." in fix_section
    assert (
        "installs: betterproto[compiler], grpcio-tools, PyYAML"
    ) in fix_section
    assert "grpc_tools.protoc" not in fix_section
    assert "black" not in fix_section
    assert "yaml" not in fix_section
    # The hint should appear exactly once per unique fix.
    assert fix_section.count("Run `s3m-protobuild setup go --go .go`.") == 1
    assert fix_section.count("Run `s3m-protobuild setup python --venv .venv`.") == 1


def test_env_marks_unresponsive_binary_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        diag,
        "env_with_local_tools",
        lambda venv=None, go_dir=None, strict=True: {"PATH": "local"},
    )
    monkeypatch.setattr(toolchain.shutil, "which", lambda command, path=None: "/bin/x")
    monkeypatch.setattr(diag, "_python_module_present", lambda *a, **k: True)

    def fake_run(args, **_):
        raise diag.subprocess.TimeoutExpired(cmd=args, timeout=5)

    monkeypatch.setattr(diag.subprocess, "run", fake_run)

    result = diag.env_diag()

    assert "protoc: ok" in result
    assert "missing" not in result
