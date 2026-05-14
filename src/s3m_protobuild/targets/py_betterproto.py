from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..config import ModuleConfig
from ..errors import BuildError
from ..model import ResolvedPackage, proto_paths
from ..output import remove_empty_dirs, write_package_inits
from ..run import require_commands, require_python_modules, run

_FROM_RELATIVE_RE = re.compile(
    r"^(?P<indent>\s*)from (?P<dots>\.+)(?P<rest>[\w.]*) import\b"
)


def generate_betterproto(
    output_root: Path,
    config: ModuleConfig,
    stage_root: Path,
    packages: list[ResolvedPackage],
    env: dict[str, str] | None = None,
) -> None:
    require_commands(("protoc", "protoc-gen-python_betterproto"), env=env)
    require_python_modules(("betterproto",), env=env)
    package_name = config.pyb_module_name
    package_root = output_root / package_name
    package_root.mkdir(parents=True, exist_ok=True)
    proto_files = proto_paths(packages)

    run(
        [
            "protoc",
            "-I",
            str(stage_root),
            f"--python_betterproto_out={package_root}",
            *proto_files,
        ],
        env=env,
    )

    _flatten_namespaces(package_root, config.flatten_namespaces)
    write_package_inits(package_root, packages)


def _flatten_namespaces(package_root: Path, namespaces: tuple[str, ...]) -> None:
    namespace_roots = [package_root.joinpath(*ns.split(".")) for ns in namespaces]

    moves: dict[Path, Path] = {}
    for namespace_root in namespace_roots:
        if not namespace_root.exists():
            continue
        for source in sorted(namespace_root.rglob("*")):
            if not source.is_file():
                continue
            old_rel = source.relative_to(package_root)
            new_rel = source.relative_to(namespace_root)
            moves[old_rel] = new_rel

    for old_rel, new_rel in moves.items():
        src = package_root / old_rel
        dest = package_root / new_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.resolve() != src.resolve():
            _resolve_flatten_collision(src, dest)
            continue
        shutil.move(str(src), str(dest))

    for old_rel, new_rel in moves.items():
        moved = package_root / new_rel
        if moved.suffix != ".py" or not moved.exists():
            continue
        _rewrite_relative_imports(moved, old_rel, new_rel, moves)

    for namespace_root in namespace_roots:
        shutil.rmtree(namespace_root, ignore_errors=True)

    remove_empty_dirs(package_root)


def _resolve_flatten_collision(src: Path, dest: Path) -> None:
    if src.name != "__init__.py" or dest.name != "__init__.py":
        raise BuildError(
            f"Namespace flatten would overwrite {dest} with {src}. "
            "Both files exist at the same relative path inside and outside the "
            "flattened namespace. A .proto file is likely missing or duplicating "
            "its `package` directive."
        )
    src_text = src.read_text()
    dest_text = dest.read_text()

    if not src_text.strip():
        src.unlink()
        return
    if not dest_text.strip():
        dest.unlink()
        shutil.move(str(src), str(dest))
        return
    if src_text == dest_text:
        src.unlink()
        return
    raise BuildError(
        f"Namespace flatten cannot merge non-empty {dest}; both files have content. "
        "This usually means a .proto file is missing a `package` directive."
    )


def _rewrite_relative_imports(
    file_path: Path,
    old_rel: Path,
    new_rel: Path,
    moves: dict[Path, Path],
) -> None:
    old_pkg_parts = list(old_rel.parent.parts)
    new_pkg_parts = list(new_rel.parent.parts)
    if old_pkg_parts == new_pkg_parts:
        return

    def fix_line(line: str) -> str:
        match = _FROM_RELATIVE_RE.match(line)
        if not match:
            return line
        n_dots = len(match.group("dots"))
        ups = n_dots - 1
        if ups > len(old_pkg_parts):
            return line
        target_pkg_parts = old_pkg_parts[: len(old_pkg_parts) - ups]
        rest = match.group("rest")
        if rest:
            target_pkg_parts.extend(rest.split("."))
        target_old_init = Path(*target_pkg_parts, "__init__.py")
        target_new_init = moves.get(target_old_init, target_old_init)
        target_new_pkg_parts = list(target_new_init.parent.parts)

        common = 0
        while (
            common < len(new_pkg_parts)
            and common < len(target_new_pkg_parts)
            and new_pkg_parts[common] == target_new_pkg_parts[common]
        ):
            common += 1
        new_ups = len(new_pkg_parts) - common
        new_dots = "." * (new_ups + 1)
        new_rest = ".".join(target_new_pkg_parts[common:])
        return (
            f"{match.group('indent')}from {new_dots}{new_rest} import"
            + line[match.end() :]
        )

    text = file_path.read_text()
    new_text = "\n".join(fix_line(line) for line in text.split("\n"))

    if new_text != text:
        file_path.write_text(new_text)
