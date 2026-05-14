from __future__ import annotations

import re
from pathlib import Path

from ..config import ModuleConfig
from ..model import ResolvedPackage, Source, proto_paths
from ..output import move_generated_tree, write_package_inits
from ..run import python_executable, require_commands, require_python_modules, run

_FROM_PROTO_RE = re.compile(r"^(from )proto(?:\.([A-Za-z0-9_\.]+))?( import .*)$")
_IMPORT_PROTO_RE = re.compile(r"^(import )proto\.([A-Za-z0-9_\.]+)(.*)$")


def generate_grpcio(
    output_root: Path,
    config: ModuleConfig,
    stage_root: Path,
    packages: list[ResolvedPackage],
    all_sources: list[Source],
    env: dict[str, str] | None = None,
) -> None:
    require_commands(("python3",), env=env)
    require_python_modules(("grpc_tools.protoc",), env=env)

    package_name = config.py_module_name
    package_root = output_root / package_name
    package_root.mkdir(parents=True, exist_ok=True)
    proto_files = proto_paths(packages)

    run(
        [
            python_executable(env),
            "-m",
            "grpc_tools.protoc",
            "-I",
            str(stage_root),
            f"--grpc_python_out={package_root}",
            f"--python_out={package_root}",
            *proto_files,
        ],
        env=env,
    )

    move_generated_tree(package_root / "proto", package_root, ("*.py",))
    write_package_inits(package_root, packages)
    _rewrite_proto_imports(
        package_root, _python_package_owners(all_sources), package_name
    )


def _python_package_owners(sources: list[Source]) -> dict[tuple[str, ...], str]:
    owners: dict[tuple[str, ...], str] = {}
    for source in sources:
        package_name = source.config.py_module_name
        proto_root = source.root / "proto"
        for proto_file in proto_root.rglob("*.proto"):
            owners[proto_file.parent.relative_to(proto_root).parts] = package_name
    return owners


def _owner_for_module(
    module: str | None, owners: dict[tuple[str, ...], str], fallback: str
) -> str:
    if not module:
        return fallback
    parts = tuple(part for part in module.split(".") if part)
    for size in range(len(parts), 0, -1):
        owner = owners.get(parts[:size])
        if owner:
            return owner
    return fallback


def _rewrite_proto_imports(
    package_root: Path, owners: dict[tuple[str, ...], str], fallback: str
) -> None:
    def rewrite_from(match: re.Match[str]) -> str:
        prefix, submodule, suffix = match.group(1), match.group(2), match.group(3)
        owner = _owner_for_module(submodule, owners, fallback)
        tail = f".{submodule}" if submodule else ""
        return f"{prefix}{owner}{tail}{suffix}"

    def rewrite_import(match: re.Match[str]) -> str:
        prefix, submodule, suffix = match.group(1), match.group(2), match.group(3)
        owner = _owner_for_module(submodule, owners, fallback)
        return f"{prefix}{owner}.{submodule}{suffix}"

    for py_file in sorted(package_root.rglob("*.py")):
        original = py_file.read_text()

        lines = []
        for line in original.splitlines(keepends=True):
            rewritten = _FROM_PROTO_RE.sub(rewrite_from, line)
            rewritten = _IMPORT_PROTO_RE.sub(rewrite_import, rewritten)
            lines.append(rewritten)
        new_text = "".join(lines)

        if new_text != original:
            py_file.write_text(new_text)
