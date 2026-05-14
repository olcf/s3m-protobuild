from __future__ import annotations

from pathlib import Path

from .errors import BuildError
from .metadata import write_build_info
from .model import (
    Artifact,
    DescriptorOptions,
    ResolvedPackage,
    Source,
)
from .output import (
    copy_resources,
    include_sources,
    prepare_output_root,
    reduce_package_directory,
)
from .packages import merge_packages
from .planning import (
    PlannedBuild,
    descriptor_options,
    metadata_artifacts,
    plan_artifacts,
    validate_single_output_artifacts,
)
from .python_package import ensure_python_packaging, write_version_module
from .run import env_with_local_tools, env_with_writable_go_cache, log, log_indent
from .selectors import dedupe_selectors, parse_selector
from .sources import SourceRequest, resolved_sources
from .staging import staged_source_view
from .targets.go import generate_go, require_go_tools
from .targets.py_betterproto import generate_betterproto
from .targets.py_grpcio import generate_grpcio
from .targets.openapi_descriptor import generate_openapi_and_descriptor


def build(
    source_requests: list[SourceRequest],
    selector_texts: list[str],
    output_dir: Path,
    go_mod_replace: dict[str, Path] | None = None,
    descriptor_out: Path | None = None,
    descriptor_imports: bool = False,
    descriptor_source_info: bool = False,
    include_source: bool = False,
    unsafe_overwrite: bool = False,
    venv: Path | None = None,
    go_dir: Path | None = None,
) -> None:
    if not selector_texts:
        raise BuildError("At least one explicit selector is required.")

    go_mod_replace = go_mod_replace or {}
    output_dir = output_dir.resolve()

    with resolved_sources(source_requests) as sources:
        source_names = {source.name for source in sources}
        selectors = dedupe_selectors(
            [parse_selector(raw, source_names) for raw in selector_texts]
        )

        plan = plan_artifacts(selectors, sources, output_dir)
        validate_single_output_artifacts(plan.artifacts)

        descriptor_opts = descriptor_options(
            descriptor_out,
            descriptor_imports,
            descriptor_source_info,
            output_dir,
            plan.descriptor_packages,
        )

        prepare_output_root(
            output_dir,
            [source.root for source in sources],
            unsafe_overwrite=unsafe_overwrite,
        )

        all_packages = merge_packages(
            [
                *(
                    package
                    for artifact in plan.artifacts
                    for package in artifact.packages
                ),
                *plan.specs_packages,
                *plan.descriptor_packages,
            ]
        )

        tool_env = env_with_writable_go_cache(
            env_with_local_tools(venv=venv, go_dir=go_dir)
        )

        total_artifacts = len(plan.artifacts)
        if plan.specs_packages:
            total_artifacts += 1
        if descriptor_out:
            total_artifacts += 1
        log(f"Building {total_artifacts} artifact(s) from {len(sources)} source(s)")

        with staged_source_view(sources, all_packages) as (stage_root, staged_packages):
            staged_index = {package.identity: package for package in staged_packages}

            _build_planned_artifacts(
                plan.artifacts,
                staged_index,
                stage_root,
                sources,
                go_mod_replace,
                tool_env,
                include_source,
            )
            _build_specs_and_descriptor(
                plan,
                descriptor_opts,
                staged_index,
                output_dir,
                stage_root,
                tool_env,
            )

        write_build_info(
            output_dir,
            sources,
            [selector.raw for selector in selectors],
            metadata_artifacts(plan, descriptor_opts, output_dir),
            tool_env=tool_env,
        )
        log("Build complete")


def _build_artifact(
    artifact: Artifact,
    stage_root: Path,
    packages: list[ResolvedPackage],
    all_sources: list[Source],
    go_mod_replace: dict[str, Path],
    tool_env: dict[str, str] | None,
) -> None:
    target = artifact.key.target
    config = artifact.source.config
    if target == "go":
        tool_env = require_go_tools(all_sources, env=tool_env)
        copy_resources(artifact.source, artifact.output_root, "go")
        generate_go(
            artifact.output_root,
            config,
            stage_root,
            packages,
            all_sources,
            go_mod_replace,
            env=tool_env,
        )

        return
    if target == "py":
        generate_grpcio(
            artifact.output_root,
            config,
            stage_root,
            packages,
            all_sources,
            env=tool_env,
        )

        dist_name = config.py_dist_name
        module_name = config.py_module_name
        runtime_deps: tuple[str, ...] = (
            "protobuf",
            "grpcio",
            "googleapis-common-protos",
        )
    elif target == "pyb":
        generate_betterproto(
            artifact.output_root, config, stage_root, packages, env=tool_env
        )

        dist_name = config.pyb_dist_name
        module_name = config.pyb_module_name
        runtime_deps = ("betterproto",)
    else:
        raise BuildError(f"Unsupported target: {target}")

    copy_resources(artifact.source, artifact.output_root, target)
    ensure_python_packaging(artifact.output_root, dist_name, module_name, runtime_deps)
    write_version_module(artifact.output_root, module_name, config.version)


def _build_planned_artifacts(
    artifacts: list[Artifact],
    staged_index: dict[tuple[str, Path], ResolvedPackage],
    stage_root: Path,
    sources: list[Source],
    go_mod_replace: dict[str, Path],
    tool_env: dict[str, str] | None,
    include_source: bool,
) -> None:
    for artifact in artifacts:
        staged = [staged_index[package.identity] for package in artifact.packages]
        log(f"Building {artifact.key.text()} into {artifact.output_root}", 1)

        with log_indent():
            _build_artifact(
                artifact, stage_root, staged, sources, go_mod_replace, tool_env
            )
            if include_source:
                include_sources(artifact.output_root, staged)
            reduce_package_directory(artifact.output_root)


def _build_specs_and_descriptor(
    plan: PlannedBuild,
    descriptor_opts: DescriptorOptions,
    staged_index: dict[tuple[str, Path], ResolvedPackage],
    output_dir: Path,
    stage_root: Path,
    tool_env: dict[str, str] | None,
) -> None:
    if not plan.specs_packages and not descriptor_opts.output_root:
        return

    specs_staged = [
        staged_index[package.identity]
        for package in merge_packages(plan.specs_packages)
    ]
    descriptor_staged = (
        [
            staged_index[package.identity]
            for package in merge_packages(plan.descriptor_packages)
        ]
        if descriptor_opts.output_root
        else []
    )

    generate_openapi_and_descriptor(
        output_dir,
        stage_root,
        specs_staged,
        bool(plan.specs_packages),
        descriptor_opts,
        descriptor_packages=descriptor_staged,
        env=tool_env,
    )
