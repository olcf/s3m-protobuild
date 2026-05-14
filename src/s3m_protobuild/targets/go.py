from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable

from ..config import ModuleConfig
from ..errors import BuildError
from ..model import ResolvedPackage, Source, proto_paths
from ..output import move_generated_tree
from ..run import log, require_commands, run

GO_COMMANDS = (
    "protoc",
    "go",
    "protoc-go-inject-tag",
    "protoc-gen-go",
    "protoc-gen-go-grpc",
    "protoc-gen-grpc-gateway",
)

# Pseudo-version go writes in synthetic `require` lines so `go mod tidy`
# accepts a `replace` directive whose target is a local path.
_REPLACE_PSEUDO_VERSION = "v0.0.0-00010101000000-000000000000"
_DEFAULT_GO_VERSION = "1.22"


def require_go_tools(
    all_sources: list[Source],
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = _without_source_go_bins(
        (source.root for source in all_sources), base_env=env
    )
    require_commands(GO_COMMANDS, env=env)
    return env


def _without_source_go_bins(
    source_roots: Iterable[Path],
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    # Strip `<source>/.go/bin` entries from PATH so a source repo's own
    # checked-in tools can't shadow s3m-protobuild's pinned versions.
    env = (base_env or os.environ).copy()
    blocked = {(root / ".go" / "bin").resolve() for root in source_roots}
    kept: list[str] = []

    for part in env.get("PATH", "").split(os.pathsep):
        if not part:
            continue
        try:
            if Path(part).resolve() in blocked:
                continue
        except OSError:
            pass
        kept.append(part)

    env["PATH"] = os.pathsep.join(kept)
    return env


def generate_go(
    output_root: Path,
    config: ModuleConfig,
    stage_root: Path,
    packages: list[ResolvedPackage],
    all_sources: list[Source],
    go_mod_replace: dict[str, Path],
    env: dict[str, str] | None = None,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    proto_files = proto_paths(packages)
    if not proto_files:
        return

    includes = ["-I", str(stage_root)]
    run(
        [
            "protoc",
            *includes,
            f"--go_out={output_root}",
            "--go_opt=paths=source_relative",
            f"--go-grpc_out={output_root}",
            "--go-grpc_opt=paths=source_relative",
            *proto_files,
        ],
        env=env,
    )

    # grpc-gateway is invoked per package because grpc_api_configuration is
    # single-valued; one protoc invocation can only point at one service.yaml.
    for package in packages:
        service_yaml = (
            package.staged_dir / "service.yaml" if package.staged_dir else None
        )
        if not service_yaml or not service_yaml.exists():
            continue
        package_proto_files = [str(path) for path in package.logical_proto_files]
        run(
            [
                "protoc",
                *includes,
                f"--grpc-gateway_out={output_root}",
                "--grpc-gateway_opt=logtostderr=true",
                "--grpc-gateway_opt=paths=source_relative",
                f"--grpc-gateway_opt=grpc_api_configuration={service_yaml}",
                *package_proto_files,
            ],
            env=env,
        )

    for package in packages:
        pattern = output_root / "proto" / package.logical_dir / "*.pb.go"
        run(["protoc-go-inject-tag", f"-input={pattern}"], env=env)

    move_generated_tree(
        output_root / "proto", output_root, ("*.pb.go", "*.pb.gw.go")
    )

    _write_go_mod(
        output_root,
        config,
        go_mod_replace=go_mod_replace,
        all_sources=all_sources,
        env=env,
    )


def _parse_go_version(text: str) -> str:
    match = re.search(r"go(\d+\.\d+)", text)
    if not match:
        return _DEFAULT_GO_VERSION
    return match.group(1)


def _write_go_mod(
    output_root: Path,
    config: ModuleConfig,
    go_mod_replace: dict[str, Path],
    all_sources: list[Source],
    env: dict[str, str],
) -> None:
    go_version = _parse_go_version(run(["go", "version"], env=env))
    replaces = _usable_replaces(config, go_mod_replace)
    (output_root / "go.mod").write_text(_render_go_mod(config, go_version, replaces))

    try:
        run(["go", "mod", "tidy"], cwd=output_root, env=env)
    except BuildError as exc:
        hint = _go_mod_replace_hint(
            exc.output, config, all_sources, go_mod_replace
        )
        if hint:
            raise BuildError(f"{exc}\n\n{hint}", output=exc.output) from exc
        raise

    _warn_unused_replaces(output_root, replaces, env=env)


def _usable_replaces(
    config: ModuleConfig, go_mod_replace: dict[str, Path]
) -> dict[str, Path]:
    replaces: dict[str, Path] = {}
    for module, path in sorted(go_mod_replace.items()):
        if module == config.go_package:
            log(
                f"warning: ignoring --go-mod-replace for {config.go_package}; "
                "replace cannot point a module at itself"
            )
            continue
        replaces[module] = path

    return replaces


def _render_go_mod(
    config: ModuleConfig, go_version: str, replaces: dict[str, Path]
) -> str:
    lines = [f"module {config.go_package}", "", f"go {go_version}", ""]
    if replaces:
        lines.append("require (")
        for module in replaces:
            lines.append(f"\t{module} {_REPLACE_PSEUDO_VERSION}")

        lines += [")", "", "replace ("]
        for module, path in replaces.items():
            lines.append(f"\t{module} => {path.as_posix()}")
        lines += [")", ""]

    return "\n".join(lines)


def _warn_unused_replaces(
    output_root: Path,
    replaces: dict[str, Path],
    env: dict[str, str],
) -> None:
    if not replaces:
        return

    parsed = json.loads(run(["go", "mod", "edit", "-json"], cwd=output_root, env=env))
    required = {entry["Path"] for entry in parsed.get("Require") or []}

    for module in replaces:
        if module in required:
            continue
        log(
            f"warning: --go-mod-replace {module}=... was passed but no selected "
            f"package imports {module}. The replace directive will be written "
            f"but is unused."
        )


def _go_mod_replace_hint(
    output: str | None,
    config: ModuleConfig,
    all_sources: list[Source],
    go_mod_replace: dict[str, Path],
) -> str | None:
    if not output:
        return None

    sibling_packages = {
        source.config.go_package: source
        for source in all_sources
        if source.config.go_package and source.config.go_package != config.go_package
    }
    if not sibling_packages:
        return None

    suggestions = [
        f"  --go-mod-replace {go_package}=../{source.name}"
        for go_package, source in sibling_packages.items()
        if go_package not in go_mod_replace and go_package in output
    ]
    if not suggestions:
        return None

    return (
        "Hint: the generated module imports another --source's Go package. "
        "Re-run with the corresponding --go-mod-replace flag(s):\n"
        + "\n".join(suggestions)
        + "\n(Adjust the path on the right of '=' to wherever the sibling artifact lives "
        "relative to this artifact's --out root.)"
    )
