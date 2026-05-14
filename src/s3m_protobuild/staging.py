from __future__ import annotations

import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from .errors import BuildError
from .model import ResolvedPackage, Source
from .output import iter_files
from .run import log

_PACKAGE_LINE_RE = re.compile(
    r"^\s*package\s+([A-Za-z_][A-Za-z0-9_.]*)\s*;", re.MULTILINE
)
_SYNTAX_LINE_RE = re.compile(r"^\s*syntax\s*=\s*\"[^\"]+\"\s*;.*$", re.MULTILINE)


@contextmanager
def staged_source_view(
    sources: list[Source],
    packages: list[ResolvedPackage],
) -> Generator[tuple[Path, list[ResolvedPackage]], None, None]:
    with tempfile.TemporaryDirectory(prefix="s3m-protobuild-") as tmp:
        stage_root = Path(tmp)
        stage_proto = stage_root / "proto"
        stage_proto.mkdir(parents=True)

        selected_owners = _selected_package_owners(packages)
        staged_owners: dict[Path, str] = {}

        for source in sources:
            _copy_tree_contents(source.root / "third_party", stage_root)
            _copy_proto_tree(
                source.root / "proto",
                stage_proto,
                source.name,
                selected_owners,
                staged_owners,
            )

        _inject_missing_packages(stage_proto, staged_owners)

        staged = [
            ResolvedPackage(
                source=package.source,
                selector=package.selector,
                logical_dir=package.logical_dir,
                source_dir=package.source_dir,
                staged_dir=stage_proto / package.logical_dir,
            )
            for package in packages
        ]
        yield stage_root, staged


def _copy_tree_contents(source: Path, dest_root: Path) -> None:
    for item in iter_files(source):
        dest = dest_root / item.relative_to(source)
        if dest.exists():
            if dest.read_bytes() != item.read_bytes():
                raise BuildError(
                    f"Staged dependency file collision at "
                    f"{dest.relative_to(dest_root.parent)}"
                )
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)


def _copy_proto_tree(
    source: Path,
    dest: Path,
    source_name: str,
    selected_owners: dict[Path, str],
    staged_owners: dict[Path, str],
) -> None:
    for item in iter_files(source):
        rel = item.relative_to(source)
        owner = _selected_owner(rel, selected_owners)
        if owner and owner != source_name:
            continue

        target = dest / rel
        if target.exists():
            previous = staged_owners.get(rel, "<unknown>")
            raise BuildError(
                f"Staged proto file collision at proto/{rel.as_posix()}: "
                f"already staged from {previous!r}, also present in {source_name!r}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        staged_owners[rel] = source_name


def _selected_package_owners(packages: list[ResolvedPackage]) -> dict[Path, str]:
    owners: dict[Path, str] = {}
    for package in packages:
        previous = owners.setdefault(package.logical_dir, package.source.name)
        if previous != package.source.name:
            raise BuildError(
                f"Selected package {package.logical_dir.as_posix()} exists in "
                f"multiple source modules: {previous}, {package.source.name}. "
                "Use separate output roots."
            )
    return owners


def _selected_owner(rel: Path, selected_owners: dict[Path, str]) -> str | None:
    for package_dir, owner in selected_owners.items():
        if rel.is_relative_to(package_dir):
            return owner
    return None


def _inject_missing_packages(
    stage_proto: Path,
    staged_owners: dict[Path, str],
) -> None:
    # Mutates staged copies under stage_proto only; original source trees are untouched.
    proto_files = sorted(stage_proto.rglob("*.proto"))
    package_by_dir: dict[Path, tuple[str, Path]] = {}
    needs_injection_by_dir: dict[Path, list[Path]] = {}

    for proto_path in proto_files:
        text = proto_path.read_text()
        existing = _read_existing_package(text)
        rel_to_stage = proto_path.relative_to(stage_proto)
        if existing is not None:
            previous = package_by_dir.get(proto_path.parent)
            if previous is not None and previous[0] != existing:
                raise BuildError(
                    f"Conflicting `package` directives in "
                    f"proto/{rel_to_stage.parent.as_posix()}: "
                    f"{previous[0]!r} vs {existing!r}"
                )
            if previous is None:
                package_by_dir[proto_path.parent] = (existing, proto_path)
            continue

        needs_injection_by_dir.setdefault(proto_path.parent, []).append(proto_path)

    if not needs_injection_by_dir:
        return

    failures: list[str] = []
    for dir_path, paths in needs_injection_by_dir.items():
        chosen = package_by_dir.get(dir_path)
        if chosen is None:
            for proto_path in paths:
                rel = proto_path.relative_to(stage_proto)
                owner = staged_owners.get(rel)
                failures.append(
                    f"proto/{rel.as_posix()} (owner: {owner or '<unknown>'})"
                )
            continue

        package, source_proto = chosen
        rel_dir = dir_path.relative_to(stage_proto)
        count = len(paths)
        log(
            f"proto/{rel_dir.as_posix()}/: inferred `package {package};` "
            f"for {count} file{'s' if count != 1 else ''} from sibling "
            f"{source_proto.name}"
        )

        for proto_path in paths:
            _inject_package_directive(proto_path, package)

    if failures:
        joined = "\n  ".join(failures)
        raise BuildError(
            "No `package` directive found in any proto file under these directories; "
            "at least one file per directory must declare a package:\n  " + joined
        )


def _read_existing_package(text: str) -> str | None:
    match = _PACKAGE_LINE_RE.search(text)
    return match.group(1) if match else None


def _inject_package_directive(proto_path: Path, package: str) -> None:
    text = proto_path.read_text()
    directive = f"package {package};\n"
    match = _SYNTAX_LINE_RE.search(text)
    if match is None:
        proto_path.write_text(directive + text)
        return
    end = match.end()
    after = text[end:].lstrip("\n")
    proto_path.write_text(f"{text[:end]}\n\n{directive}{after}")
