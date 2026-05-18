from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterator

from .errors import BuildError
from .model import ResolvedPackage, Source

BUILD_INFO_NAME = "build.info"


def iter_files(root: Path) -> Iterator[Path]:
    """Yield regular files under `root` in sorted order, skipping symlinks."""
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        yield path


def validate_output_root(
    output_root: Path,
    source_roots: list[Path],
    unsafe_overwrite: bool = False,
) -> None:
    output_root = output_root.resolve()
    dangerous_names = {
        ".git",
        ".venv",
        "venv",
        ".go",
        "go",
        "proto",
        "src",
        "internal",
        "s3m-protobuild",
        "s3m_protobuild",
    }
    if output_root.name in dangerous_names:
        raise BuildError(f"Refusing dangerous output root: {output_root}")

    for raw_source_root in source_roots:
        source_root = raw_source_root.resolve()
        if output_root == source_root:
            raise BuildError(f"Output root cannot be a source root: {output_root}")
        if output_root.is_relative_to(source_root):
            raise BuildError(
                f"Output root cannot be inside a source root: {output_root}"
            )

    if not output_root.exists():
        return
    if not output_root.is_dir():
        raise BuildError(f"Output root exists and is not a directory: {output_root}")

    if not any(output_root.iterdir()):
        return

    if (output_root / BUILD_INFO_NAME).exists():
        return
    if unsafe_overwrite:
        return
    raise BuildError(
        f"Refusing non-empty unmanaged output root: {output_root}. "
        "Pass --unsafe-overwrite to replace it."
    )


def prepare_output_root(
    output_root: Path, source_roots: list[Path], unsafe_overwrite: bool = False
) -> None:
    validate_output_root(output_root, source_roots, unsafe_overwrite=unsafe_overwrite)

    if output_root.exists() and any(output_root.iterdir()):
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)


def move_generated_tree(
    source_dir: Path, target_dir: Path, patterns: tuple[str, ...]
) -> list[Path]:
    moved: list[Path] = []
    if not source_dir.exists():
        return moved

    for pattern in patterns:
        for source in sorted(source_dir.rglob(pattern)):
            if not source.is_file():
                continue
            rel = source.relative_to(source_dir)
            dest = target_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest.unlink()
            shutil.move(source, dest)
            moved.append(dest)

    remove_empty_dirs(source_dir, include_root=True)

    return moved


def remove_empty_dirs(root: Path, include_root: bool = False) -> None:
    if not root.exists():
        return

    for dirpath, _, _ in os.walk(root, topdown=False):
        current = Path(dirpath)
        if current == root and not include_root:
            continue
        try:
            if not any(current.iterdir()):
                current.rmdir()
        except OSError:
            pass


def reduce_package_directory(root: Path) -> None:
    if not root.exists():
        return
    # Bottom-up so a parent sees its just-collapsed children as absent and can collapse too.

    for dirpath, _, _ in os.walk(root, topdown=False):
        directory = Path(dirpath)
        if directory == root:
            continue
        init_file = directory / "__init__.py"
        if not init_file.exists() or init_file.stat().st_size != 0:
            continue
        if any(child != init_file for child in directory.iterdir()):
            continue
        init_file.unlink()
        try:
            directory.rmdir()
        except OSError:
            pass

    remove_empty_dirs(root)


def write_package_inits(package_root: Path, packages: list[ResolvedPackage]) -> None:
    (package_root / "__init__.py").touch(exist_ok=True)

    for package in packages:
        current = package_root
        for part in package.logical_dir.parts:
            current = current / part
            current.mkdir(parents=True, exist_ok=True)
            (current / "__init__.py").touch(exist_ok=True)


def copy_resources(source: Source, output_root: Path, target: str) -> list[Path]:
    written: list[Path] = []
    resource_root = source.root / "res" / target

    for src in iter_files(resource_root):
        rel = src.relative_to(resource_root)
        dest = output_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        written.append(dest)

    return written


def copy_licenses(source: Source, output_root: Path) -> list[Path]:
    written: list[Path] = []
    for src in sorted(source.root.glob("LICENSE*")):
        if not src.is_file():
            continue
        dest = output_root / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        written.append(dest)
    return written


def include_sources(output_root: Path, packages: list[ResolvedPackage]) -> list[Path]:
    written: list[Path] = []

    for package in packages:
        proto_root = package.source.root / "proto"
        for src in iter_files(package.source_dir):
            if src.suffix != ".proto" and src.name != "service.yaml":
                continue
            rel = src.relative_to(proto_root)
            dest = output_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            written.append(dest)

    return written
