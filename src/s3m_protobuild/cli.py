from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .build import build
from .clean import clean
from .diag import env_diag
from .errors import BuildError
from .sources import parse_source_arg
from .toolchain import setup_local_tools


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        _run_command(args)
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="s3m-protobuild",
        description="Standalone S3M protobuf artifact builder",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser("build", help="Build selected artifacts")
    build_parser.add_argument(
        "selectors", nargs="+", help="[module/]package[/version]:target"
    )
    build_parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="PATH or git+<scheme>://...[@REF] (pip-style URL; @REF optional)",
    )
    build_parser.add_argument(
        "--out",
        dest="output_dir",
        type=Path,
        required=True,
        help="Output root",
    )

    build_parser.add_argument(
        "--go-mod-replace",
        action="append",
        default=[],
        help=(
            "Add a `replace` directive to the generated go.mod "
            "(`GO_MODULE=PATH`). PATH is written verbatim; Go resolves "
            "it relative to generated go.mod in --out."
        ),
    )

    build_parser.add_argument(
        "--descriptor-out",
        type=Path,
        default=None,
        help="Build a descriptor set at PATH inside --out (off if omitted)",
    )
    build_parser.add_argument(
        "--descriptor-imports",
        action="store_true",
        help="Include transitive imports in descriptor set",
    )
    build_parser.add_argument(
        "--descriptor-source-info",
        action="store_true",
        help="Include source info in descriptor set",
    )

    build_parser.add_argument(
        "--include-source",
        action="store_true",
        help="Copy selected proto/service sources into output",
    )
    build_parser.add_argument(
        "--unsafe-overwrite",
        action="store_true",
        help="Allow destructively replacing a non-empty unmanaged --out root",
    )

    build_parser.add_argument(
        "--venv", type=Path, help="Use a Python virtualenv for Python generators"
    )
    build_parser.add_argument(
        "--go",
        dest="go_dir",
        type=Path,
        help="Use local Go tool directory",
    )

    clean_parser = sub.add_parser("clean", help="Clean a managed output root")
    clean_parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Managed output root",
    )

    setup_parser = sub.add_parser("setup", help="Install local-only build dependencies")
    setup_parser.add_argument(
        "targets",
        nargs="+",
        choices=["python", "go"],
        help="Which generator toolchains to install (one or both)",
    )
    setup_parser.add_argument("--venv", type=Path, help="Local Python virtualenv")
    setup_parser.add_argument(
        "--go", dest="go_dir", type=Path, help="Local Go tool directory"
    )

    env_parser = sub.add_parser("env", help="Print dependency diagnostics")
    env_parser.add_argument(
        "--venv", type=Path, help="Check with a local Python virtualenv on PATH"
    )
    env_parser.add_argument(
        "--go",
        dest="go_dir",
        type=Path,
        help="Check with local Go tool directory",
    )

    return parser


def _run_command(args: argparse.Namespace) -> None:
    if args.command == "build":
        build(
            source_requests=[parse_source_arg(raw) for raw in args.source],
            selector_texts=args.selectors,
            output_dir=args.output_dir,
            go_mod_replace=dict(
                _parse_go_mod_replace(raw) for raw in args.go_mod_replace
            ),
            descriptor_out=args.descriptor_out,
            descriptor_imports=args.descriptor_imports,
            descriptor_source_info=args.descriptor_source_info,
            include_source=args.include_source,
            unsafe_overwrite=args.unsafe_overwrite,
            venv=args.venv,
            go_dir=args.go_dir,
        )
    elif args.command == "clean":
        clean(args.out)
    elif args.command == "setup":
        targets = set(args.targets)
        setup_local_tools(
            args.venv,
            args.go_dir,
            python="python" in targets,
            go="go" in targets,
        )
    elif args.command == "env":
        print(env_diag(venv=args.venv, go_dir=args.go_dir))


def _parse_go_mod_replace(raw: str) -> tuple[str, Path]:
    module, sep, path = raw.partition("=")
    module = module.strip()
    path = path.strip()

    if not sep or not module or not path:
        raise BuildError(f"--go-mod-replace must be GO_MODULE=PATH: {raw}")
    return module, Path(path)


if __name__ == "__main__":
    raise SystemExit(main())
