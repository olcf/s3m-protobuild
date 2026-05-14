from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import BuildError
from .model import (
    Artifact,
    ArtifactKey,
    DescriptorOptions,
    ResolvedPackage,
    Selector,
    Source,
)
from .packages import merge_packages, resolve_selector


@dataclass(frozen=True)
class PlannedBuild:
    artifacts: list[Artifact]
    specs_packages: list[ResolvedPackage]
    descriptor_packages: list[ResolvedPackage]


def plan_artifacts(
    selectors: list[Selector], sources: list[Source], output_dir: Path
) -> PlannedBuild:
    artifacts_by_key: dict[ArtifactKey, Artifact] = {}
    specs_packages: list[ResolvedPackage] = []
    descriptor_packages: list[ResolvedPackage] = []

    for selector in selectors:
        packages = merge_packages(resolve_selector(selector, sources))
        descriptor_packages.extend(packages)

        if selector.target == "oas":
            specs_packages.extend(packages)
            continue

        package_sources = {package.source.name for package in packages}
        if len(package_sources) > 1:
            names = ", ".join(sorted(package_sources))
            raise BuildError(
                f"Selector {selector.raw!r} expands across multiple source "
                f"modules for target {selector.target}: {names}. "
                "Use module-qualified selectors and separate --out roots."
            )

        source = packages[0].source
        key = ArtifactKey(source.name, selector.target)

        artifact = artifacts_by_key.setdefault(
            key, Artifact(key=key, source=source, output_root=output_dir)
        )
        artifact.packages = merge_packages([*artifact.packages, *packages])

    return PlannedBuild(
        artifacts=_ordered_artifacts(list(artifacts_by_key.values()), sources),
        specs_packages=specs_packages,
        descriptor_packages=descriptor_packages,
    )


def validate_single_output_artifacts(artifacts: list[Artifact]) -> None:
    targets = {artifact.key.target for artifact in artifacts}
    if {"py", "pyb"} <= targets:
        raise BuildError("Targets py and pyb require separate --out roots.")

    source_names = {artifact.source.name for artifact in artifacts}
    if len(source_names) > 1:
        names = ", ".join(sorted(source_names))
        raise BuildError(
            "One --out root can contain generated packages from only one source "
            f"module; selected modules: {names}"
        )


def descriptor_options(
    descriptor_out: Path | None,
    include_imports: bool,
    include_source_info: bool,
    output_dir: Path,
    descriptor_packages: list[ResolvedPackage],
) -> DescriptorOptions:
    if descriptor_out is None:
        return DescriptorOptions(
            output_root=None,
            include_imports=include_imports,
            include_source_info=include_source_info,
        )

    if not descriptor_packages:
        raise BuildError(
            "Descriptor output was requested, but no selectors resolved packages."
        )

    if descriptor_out.is_absolute() or ".." in descriptor_out.parts:
        raise BuildError(
            f"descriptor path must stay inside the output root: {descriptor_out}"
        )

    return DescriptorOptions(
        output_root=output_dir,
        relative_path=descriptor_out,
        include_imports=include_imports,
        include_source_info=include_source_info,
    )


def metadata_artifacts(
    plan: PlannedBuild, descriptor_opts: DescriptorOptions, output_dir: Path
) -> list[Artifact]:
    artifacts = [*plan.artifacts]

    if plan.specs_packages:
        artifacts.append(
            Artifact(
                ArtifactKey("combined", "oas"),
                source=plan.specs_packages[0].source,
                output_root=output_dir,
                packages=plan.specs_packages,
            )
        )

    if descriptor_opts.output_root:
        artifacts.append(
            Artifact(
                ArtifactKey("combined", "descriptor"),
                source=plan.descriptor_packages[0].source,
                output_root=descriptor_opts.output_root,
                packages=plan.descriptor_packages,
            )
        )
    return artifacts


def _ordered_artifacts(
    artifacts: list[Artifact], sources: list[Source]
) -> list[Artifact]:
    source_order = {source.name: index for index, source in enumerate(sources)}
    target_order = {"go": 0, "py": 1, "pyb": 2}

    return sorted(
        artifacts,
        key=lambda artifact: (
            source_order[artifact.source.name],
            target_order[artifact.key.target],
        ),
    )
