from __future__ import annotations

from pathlib import Path

from .errors import BuildError
from .model import ResolvedPackage, Selector, Source


def resolve_selector(
    selector: Selector, sources: list[Source]
) -> list[ResolvedPackage]:
    candidates = sources
    if selector.source_name:
        candidates = [
            source for source in sources if source.name == selector.source_name
        ]

    resolved_by_source: list[tuple[Source, list[Path]]] = []
    for source in candidates:
        package_root = source.root / "proto" / selector.package_path
        dirs = _resolve_package_dirs(selector.package_path, package_root)
        if dirs:
            resolved_by_source.append((source, dirs))

    if not resolved_by_source:
        source_hint = (
            f" in source {selector.source_name}" if selector.source_name else ""
        )
        raise BuildError(f"Package not found{source_hint}: {selector.package_text}")
    if not selector.source_name:
        _check_unqualified_ambiguity(selector, resolved_by_source)

    return [
        ResolvedPackage(
            source=source,
            selector=selector.raw,
            logical_dir=path.relative_to(source.root / "proto"),
            source_dir=path,
        )
        for source, dirs in resolved_by_source
        for path in dirs
    ]


def _resolve_package_dirs(requested: Path, package_root: Path) -> list[Path]:
    # parse_selector caps `requested` at 1 or 2 parts:
    # 1 part is a package family (expand v* children if any),
    # 2 parts is a pinned version directory.
    if not package_root.is_dir():
        return []

    if len(requested.parts) == 1:
        version_dirs = sorted(path for path in package_root.glob("v*") if path.is_dir())
        dirs = version_dirs or [package_root]
    else:
        dirs = [package_root]
    return [path for path in dirs if any(path.glob("*.proto"))]


def _check_unqualified_ambiguity(
    selector: Selector, resolved_by_source: list[tuple[Source, list[Path]]]
) -> None:
    owners: dict[Path, str] = {}

    for source, dirs in resolved_by_source:
        for path in dirs:
            logical = path.relative_to(source.root / "proto")
            previous = owners.setdefault(logical, source.name)
            if previous != source.name:
                raise BuildError(
                    f"Ambiguous package selector {selector.raw!r}; "
                    f"{logical.as_posix()} exists in multiple source modules: "
                    f"{previous}, {source.name}. Use a module-qualified selector."
                )


def merge_packages(packages: list[ResolvedPackage]) -> list[ResolvedPackage]:
    by_identity: dict[tuple[str, Path], ResolvedPackage] = {}
    for package in packages:
        by_identity.setdefault(package.identity, package)
    return list(by_identity.values())
