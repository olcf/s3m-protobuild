from __future__ import annotations

from pathlib import Path

import yaml

from ..errors import BuildError
from ..model import DescriptorOptions, ResolvedPackage, proto_paths
from ..output import move_generated_tree
from ..run import require_commands, run

OPENAPI_METHODS = ("get", "post", "put", "delete", "patch", "head", "options")


def generate_openapi_and_descriptor(
    output_root: Path,
    stage_root: Path,
    packages: list[ResolvedPackage],
    generate_openapi: bool,
    descriptor: DescriptorOptions,
    descriptor_packages: list[ResolvedPackage] | None = None,
    env: dict[str, str] | None = None,
) -> None:
    commands = ["protoc"]
    if generate_openapi:
        commands.append("protoc-gen-oas")
    require_commands(commands, env=env)

    output_root.mkdir(parents=True, exist_ok=True)
    includes = ["-I", str(stage_root)]

    if generate_openapi:
        proto_files = proto_paths(packages)
        openapi_abs = output_root / "openapi.yaml"
        openapi_abs.parent.mkdir(parents=True, exist_ok=True)

        run(
            [
                "protoc",
                *includes,
                f"--oas_out={openapi_abs.parent}",
                "--oas_opt=format=yaml",
                *proto_files,
            ],
            env=env,
        )
        move_generated_tree(
            openapi_abs.parent / "proto", openapi_abs.parent, ("openapi.yaml",)
        )
        _apply_openapi_mutations(openapi_abs, packages)

    if descriptor.output_root:
        selected = descriptor_packages if descriptor_packages is not None else packages
        proto_files = proto_paths(selected)
        descriptor_abs = descriptor.output_root / descriptor.relative_path
        descriptor_abs.parent.mkdir(parents=True, exist_ok=True)

        args = [
            "protoc",
            *includes,
            f"--descriptor_set_out={descriptor_abs}",
        ]
        if descriptor.include_imports:
            args.append("--include_imports")
        if descriptor.include_source_info:
            args.append("--include_source_info")

        args.extend(proto_files)

        run(args, env=env)


def _apply_openapi_mutations(
    openapi_path: Path, packages: list[ResolvedPackage]
) -> None:
    mutation_files = [
        package.source_dir / "openapi-mutations.yaml"
        for package in packages
        if (package.source_dir / "openapi-mutations.yaml").exists()
    ]
    if not mutation_files:
        return
    if not openapi_path.exists():
        raise BuildError(
            f"OpenAPI mutations requested but {openapi_path} was not generated"
        )

    spec = yaml.safe_load(openapi_path.read_text())
    for mutation_file in mutation_files:
        config = yaml.safe_load(mutation_file.read_text()) or {}

        for mutation in config.get("mutations", []):
            kind = mutation.get("type")
            if kind != "add_header_parameter":
                raise BuildError(
                    f"Unsupported OpenAPI mutation type in {mutation_file}: {kind}"
                )
            param = _build_header_parameter(mutation.get("parameter", {}))
            _inject_header_parameter(spec, mutation.get("path_prefix", ""), param)

    openapi_path.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True))


def _build_header_parameter(parameter: dict) -> dict:
    result = {
        "name": parameter["name"],
        "in": "header",
        "required": parameter.get("required", False),
        "schema": parameter.get("schema", {"type": "string"}),
    }
    if "description" in parameter:
        result["description"] = parameter["description"]
    return result


def _inject_header_parameter(spec: dict, path_prefix: str, param: dict) -> None:
    for path, path_item in (spec.get("paths") or {}).items():
        if not path.startswith(path_prefix):
            continue

        for method in OPENAPI_METHODS:
            operation = path_item.get(method)
            if not operation:
                continue
            existing = {item.get("name") for item in operation.get("parameters", [])}
            if param["name"] not in existing:
                operation.setdefault("parameters", []).append(dict(param))
