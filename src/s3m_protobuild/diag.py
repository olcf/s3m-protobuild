from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .run import env_with_local_tools, local_tools_hint, python_executable
from .toolchain import PYTHON_BUILD_MODULES, system_install_guidance

GO_SETUP_HINT = "Run `s3m-protobuild setup go --go .go`."
PYTHON_SETUP_HINT = "Run `s3m-protobuild setup python --venv .venv`."

_VERSION_ARGS: dict[str, tuple[str, ...]] = {
    "go": ("version",),
}


def env_diag(venv: Path | None = None, go_dir: Path | None = None) -> str:
    env = env_with_local_tools(venv=venv, go_dir=go_dir, strict=False) or dict(
        os.environ
    )
    lines: list[str] = []
    hint = local_tools_hint(env)
    if hint:
        lines.append(hint)
    lines.extend(_missing_local_dir_messages(venv=venv, go_dir=go_dir))
    missing_by_hint: dict[str, list[str]] = {}

    _append_command_diagnostics(lines, missing_by_hint, env)
    _append_python_module_diagnostics(lines, missing_by_hint, env)
    if missing_by_hint:
        _append_fix_block(lines, missing_by_hint)
    return "\n".join(lines)


def _missing_local_dir_messages(
    venv: Path | None,
    go_dir: Path | None,
) -> list[str]:
    messages: list[str] = []

    if venv:
        bin_dir = venv / ("Scripts" if sys.platform == "win32" else "bin")
        if not bin_dir.exists():
            messages.append(
                f"{bin_dir} not found. Run `s3m-protobuild setup python --venv {venv}`."
            )

    if go_dir:
        go_bin = go_dir / "bin"
        if not go_bin.exists():
            messages.append(
                f"{go_bin} not found. Run `s3m-protobuild setup go --go {go_dir}`."
            )
    return messages


def _append_command_diagnostics(
    lines: list[str],
    missing_by_hint: dict[str, list[str]],
    env: dict[str, str],
) -> None:
    checks = [
        ("protoc", system_install_guidance("protoc"), "protoc"),
        ("go", system_install_guidance("go"), "go"),
        ("protoc-gen-go", GO_SETUP_HINT, "protoc-gen-go"),
        ("protoc-gen-go-grpc", GO_SETUP_HINT, "protoc-gen-go-grpc"),
        ("protoc-gen-grpc-gateway", GO_SETUP_HINT, "protoc-gen-grpc-gateway"),
        ("protoc-go-inject-tag", GO_SETUP_HINT, "protoc-go-inject-tag"),
        ("protoc-gen-oas", GO_SETUP_HINT, "protoc-gen-oas"),
        (
            "protoc-gen-python_betterproto",
            PYTHON_SETUP_HINT,
            PYTHON_BUILD_MODULES["betterproto"],
        ),
    ]

    for command, guidance, install_name in checks:
        version = _command_version(command, env)
        if version is None:
            lines.append(f"{command}: missing")
            _append_missing_name(missing_by_hint, guidance, install_name)
            continue
        lines.append(f"{command}: {version or 'ok'}")


def _append_python_module_diagnostics(
    lines: list[str],
    missing_by_hint: dict[str, list[str]],
    env: dict[str, str],
) -> None:
    checks = [
        (module, f"{module} (Python module)", install_name)
        for module, install_name in PYTHON_BUILD_MODULES.items()
    ]
    python = python_executable(env)

    for module, label, install_name in checks:
        if _python_module_present(python, module, env):
            lines.append(f"{label}: ok")
            continue
        lines.append(f"{label}: missing")
        _append_missing_name(missing_by_hint, PYTHON_SETUP_HINT, install_name)


def _append_fix_block(
    lines: list[str],
    missing_by_hint: dict[str, list[str]],
) -> None:
    lines.extend(("", "To fix:"))
    for hint, names in missing_by_hint.items():
        for hint_line in hint.splitlines():
            lines.append(f"  {hint_line}")
        lines.append(f"    installs: {', '.join(names)}")


def _append_missing_name(
    missing_by_hint: dict[str, list[str]],
    hint: str,
    name: str,
) -> None:
    names = missing_by_hint.setdefault(hint, [])
    if name not in names:
        names.append(name)


def _command_version(command: str, env: dict[str, str]) -> str | None:
    binary = shutil.which(command, path=env.get("PATH"))
    if not binary:
        return None

    args = _VERSION_ARGS.get(command, ("--version",))

    try:
        result = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""

    if result.returncode != 0:
        return ""

    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if line and line.isprintable():
            return line
    return ""


def _python_module_present(python: str, module: str, env: dict[str, str]) -> bool:
    try:
        result = subprocess.run(
            [python, "-c", f"import {module}"],
            capture_output=True,
            text=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False

    return result.returncode == 0


