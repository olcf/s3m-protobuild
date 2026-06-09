from __future__ import annotations

import datetime
import shutil
from datetime import timezone
from pathlib import Path
from typing import TextIO

from . import __version__
from .errors import BuildError
from .gitinfo import collect_git_info
from .model import Artifact, Source
from .output import BUILD_INFO_NAME
from .run import run

_TOOLING_TARGETS = frozenset({"go", "py", "pyb", "oas", "descriptor"})


def write_build_info(
    output_root: Path,
    sources: list[Source],
    selectors: list[str],
    artifacts: list[Artifact],
    tool_env: dict[str, str] | None = None,
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / BUILD_INFO_NAME

    with path.open("w") as handle:
        _write_build_section(handle, selectors, artifacts)
        for source in sources:
            _write_source_section(handle, source)
        _write_tooling_section(handle, artifacts, tool_env=tool_env)

    return path


def _write_build_section(
    handle: TextIO, selectors: list[str], artifacts: list[Artifact]
) -> None:
    _write_header(handle, "build")
    handle.write(
        f"build.time: {datetime.datetime.now(timezone.utc).isoformat()}\n"
        f"build.s3m_protobuild.version: {__version__}\n"
    )

    for index, selector in enumerate(selectors):
        handle.write(f"build.selector.{index}: {selector}\n")

    for index, artifact in enumerate(artifacts):
        handle.write(f"build.artifact.{index}.key: {artifact.key.text()}\n")

    handle.write("\n")


def _write_source_section(handle: TextIO, source: Source) -> None:
    info = collect_git_info(source.root)
    _write_header(handle, f"source: {source.name}")
    handle.write(
        f"source.module.version: {source.config.version}\n"
        f"source.module.go_package: {source.config.go_package}\n"
        f"source.git.commit: {info.commit}\n"
        f"source.git.commit_time: {info.commit_time}\n"
        f"source.git.dirty: {_bool_field(info.dirty)}\n"
        f"source.git.untracked: {_bool_field(info.untracked)}\n"
        "\n"
    )


def _write_tooling_section(
    handle: TextIO,
    artifacts: list[Artifact],
    tool_env: dict[str, str] | None,
) -> None:
    targets = {artifact.key.target for artifact in artifacts}
    if not targets & _TOOLING_TARGETS:
        return
    _write_header(handle, "tooling")

    if targets & {"oas", "descriptor"}:
        _write_protoc_version(handle, tool_env=tool_env)

    if "oas" in targets:
        _write_oas_tool_versions(handle, tool_env=tool_env)

    if targets & {"py", "pyb"}:
        _write_python_tool_versions(handle, tool_env=tool_env)

    if "go" in targets:
        go_module_cwd = next(
            (artifact.output_root for artifact in artifacts if artifact.key.target == "go"),
            None,
        )
        _write_go_tool_versions(handle, tool_env=tool_env, go_module_cwd=go_module_cwd)

    handle.write("\n")


def _bool_field(value: bool) -> str:
    return "true" if value else "false"


def _capture(
    handle: TextIO,
    key: str,
    args: list[str],
    env: dict[str, str] | None,
    **kwargs,
) -> str:
    try:
        return run(args, env=env, **kwargs)
    except BuildError:
        handle.write(f"{key}.error: {' '.join(args)} failed\n")
        return ""


def _write_python_tool_versions(handle: TextIO, tool_env: dict[str, str] | None) -> None:
    freeze = _capture(
        handle, "tooling.python.pip_freeze", ["python3", "-m", "pip", "freeze"], tool_env
    )

    for line in _nonempty_lines(freeze):
        if line.startswith(("#", "-")):
            continue
        name, sep, version = line.partition("==")
        if sep and version:
            handle.write(f"tooling.python.pkg.{name}: {version}\n")


def _write_go_tool_versions(
    handle: TextIO, tool_env: dict[str, str] | None, go_module_cwd: Path | None
) -> None:
    version = _capture(handle, "tooling.go.version", ["go", "version"], tool_env).strip()
    if version:
        handle.write(f"tooling.go.version: {version}\n")

    modules = _capture(
        handle,
        "tooling.go.modules",
        ["go", "list", "-m", "all"],
        tool_env,
        cwd=go_module_cwd,
    )
    for line in _nonempty_lines(modules):
        module, sep, mod_version = line.partition(" ")
        if sep and mod_version:
            handle.write(f"tooling.go.module.{module}: {mod_version}\n")


def _write_protoc_version(handle: TextIO, tool_env: dict[str, str] | None) -> None:
    protoc_version = _capture(
        handle, "tooling.protoc.version", ["protoc", "--version"], tool_env
    ).strip()
    if protoc_version:
        handle.write(f"tooling.protoc.version: {protoc_version}\n")


def _write_oas_tool_versions(handle: TextIO, tool_env: dict[str, str] | None) -> None:
    oas_bin = shutil.which("protoc-gen-oas", path=(tool_env or {}).get("PATH"))
    if not oas_bin:
        handle.write(
            "tooling.protoc_gen_oas.version.error: protoc-gen-oas not found on PATH\n"
        )
        return

    info = _capture(
        handle,
        "tooling.protoc_gen_oas.version",
        ["go", "version", "-m", oas_bin],
        tool_env,
    )
    # `go version -m` emits `\tmod\t<path>\t<version>\t<h1:...>` for each dep;
    # the first such line is the binary's own module.
    for line in info.splitlines():
        parts = line.split("\t")
        if len(parts) >= 4 and parts[1] == "mod":
            handle.write(f"tooling.protoc_gen_oas.version: {parts[3]}\n")
            return
    if info:
        handle.write("tooling.protoc_gen_oas.version.error: mod line not found\n")


def _write_header(handle: TextIO, name: str) -> None:
    handle.write(f"--- {name} ---\n")


def _nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]
