from __future__ import annotations

import contextlib
import contextvars
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Generator, Iterable

from .errors import BuildError

_log_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "s3m_protobuild_log_depth", default=0
)


def log(message: str, level: int = 0) -> None:
    indent = "  " * (_log_depth.get() + level)
    print(f"{indent}{message}", file=sys.stderr)


@contextlib.contextmanager
def log_indent() -> Generator[None, None, None]:
    token = _log_depth.set(_log_depth.get() + 1)
    try:
        yield
    finally:
        _log_depth.reset(token)


def quote(value: object) -> str:
    return shlex.quote(str(value))


def run(
    args: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> str:
    display = " ".join(quote(arg) for arg in args)
    where = f" (cwd={cwd})" if cwd else ""
    log(f"Running: {display}{where}", 1)
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        raise BuildError(f"Unable to run command: {display}: {exc}") from exc

    if completed.stdout:
        for line in completed.stdout.splitlines():
            log(f"| {line}", 2)

    if check and completed.returncode != 0:
        raise BuildError(
            f"Command failed with exit code {completed.returncode}: {display}",
            output=completed.stdout,
        )

    return completed.stdout


def require_commands(
    commands: Iterable[str], env: dict[str, str] | None = None
) -> None:
    path = env.get("PATH") if env else None
    missing = [cmd for cmd in commands if not shutil.which(cmd, path=path)]
    if missing:
        message = (
            "Missing required command(s): "
            + ", ".join(missing)
            + ". Run `s3m-protobuild env` for install guidance."
        )
        hint = local_tools_hint(env)
        if hint:
            message += "\n" + hint

        raise BuildError(message)


def require_python_modules(
    modules: Iterable[str], env: dict[str, str] | None = None
) -> None:
    python = python_executable(env)
    missing: list[str] = []
    for module in modules:
        try:
            completed = subprocess.run(
                [python, "-c", f"import {module}"],
                check=False,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError:
            missing.append(module)
            continue
        if completed.returncode != 0:
            missing.append(module)

    if missing:
        message = (
            "Missing required Python module(s): "
            + ", ".join(missing)
            + ". Run `s3m-protobuild setup python --venv .venv`"
            " or install them in your selected environment."
        )
        hint = local_tools_hint(env)
        if hint:
            message += "\n" + hint

        raise BuildError(message)


def local_tools_hint(env: dict[str, str] | None) -> str | None:
    """Detect ./.venv or ./.go in cwd that weren't put on PATH via --venv/--go."""
    path = env.get("PATH", "") if env else ""
    cwd = Path.cwd()
    hints: list[tuple[str, str]] = []

    venv_bin = cwd / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
    if venv_bin.exists() and str(venv_bin) not in path:
        hints.append((".venv", "--venv .venv"))

    go_bin = cwd / ".go" / "bin"
    if go_bin.exists() and str(go_bin) not in path:
        hints.append((".go", "--go .go"))

    if not hints:
        return None

    dirs = " and ".join(name for name, _ in hints)
    flags = " ".join(flag for _, flag in hints)
    verb = "exist" if len(hints) > 1 else "exists"
    return (
        f"Hint: {dirs} {verb} in this directory. "
        f"Did you mean to pass {flags}?"
    )


def python_executable(env: dict[str, str] | None = None) -> str:
    path = env.get("PATH") if env else None
    python = shutil.which("python3", path=path) or shutil.which("python", path=path)
    return python or "python3"


def env_with_writable_go_cache(env: dict[str, str] | None = None) -> dict[str, str]:
    result = (env or os.environ).copy()
    goflags = result.get("GOFLAGS", "")
    try:
        has_flag = "-modcacherw" in shlex.split(goflags)
    except ValueError:
        has_flag = "-modcacherw" in goflags.split()
    if not has_flag:
        result["GOFLAGS"] = (goflags + " -modcacherw").strip()
    return result


def env_with_local_tools(
    venv: Path | None = None,
    go_dir: Path | None = None,
    strict: bool = True,
) -> dict[str, str] | None:
    if not venv and not go_dir:
        return None

    env = os.environ.copy()

    if venv:
        bin_dir = venv / ("Scripts" if sys.platform == "win32" else "bin")
        if bin_dir.exists():
            env["VIRTUAL_ENV"] = str(venv)
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        elif strict:
            raise BuildError(f"Virtual environment bin directory not found: {bin_dir}")

    if go_dir:
        resolved_go_dir = go_dir.resolve()
        go_bin = resolved_go_dir / "bin"
        if go_bin.exists():
            env["PATH"] = f"{go_bin}{os.pathsep}{env.get('PATH', '')}"
            env["GOPATH"] = str(resolved_go_dir)
            env["GOMODCACHE"] = str(resolved_go_dir / "pkg" / "mod")
            env["GOCACHE"] = str(resolved_go_dir / "cache")

            env = env_with_writable_go_cache(env)
        elif strict:
            raise BuildError(f"Local Go tool bin directory not found: {go_bin}")

    return env
