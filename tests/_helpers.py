from __future__ import annotations

from pathlib import Path

from s3m_protobuild.config import ModuleConfig
from s3m_protobuild.model import Source

PROTO_MESSAGE_BODY = 'syntax = "proto3";\n\nmessage A { string n = 1; }\n'


def make_source(
    root: Path,
    name: str = "s3m-apis",
    packages: tuple[str, ...] = ("status/v1alpha",),
    *,
    include_package_directive: bool = True,
) -> Path:
    """Create a minimal source repo at `root` with a MODULE file and proto/ tree.

    `packages` is a tuple of slash-separated paths under `proto/`; the leaf
    segment becomes the proto filename. Pass `packages=()` to skip proto
    creation entirely.
    """
    root.mkdir(parents=True)
    (root / "MODULE").write_text(
        "\n".join(
            [
                f"MODULE={name}",
                "VERSION=1.2.3",
                f"GO_PACKAGE=example.com/{name}",
                "",
            ]
        )
    )

    for package in packages:
        package_dir = root / "proto" / package
        package_dir.mkdir(parents=True)
        proto_name = package_dir.name
        body = ['syntax = "proto3";']
        if include_package_directive:
            body.append(f"package {name.replace('-', '_')}.{proto_name};")
        body.append("")
        (package_dir / f"{proto_name}.proto").write_text("\n".join(body))
    return root


def make_two_sources(
    tmp_path: Path,
    first_packages: tuple[str, ...],
    second_packages: tuple[str, ...],
    *,
    first_name: str = "s3m-apis",
    second_name: str = "s3m-internal",
    first_dir: str = "first",
    second_dir: str = "second",
) -> tuple[Path, Path]:
    first = make_source(
        tmp_path / first_dir, name=first_name, packages=first_packages
    )
    second = make_source(
        tmp_path / second_dir, name=second_name, packages=second_packages
    )
    return first, second


def make_module_config(
    name: str = "s3m-apis",
    go_package: str = "example.com/s3m-apis",
    *,
    version: str = "1.2.3",
    py_package: str | None = None,
    pyb_package: str | None = None,
    flatten_namespaces: tuple[str, ...] = (),
) -> ModuleConfig:
    return ModuleConfig(
        name=name,
        version=version,
        go_package=go_package,
        py_package=py_package,
        pyb_package=pyb_package,
        flatten_namespaces=flatten_namespaces,
    )


def write_generated_file(output_root: Path, relative: str, content: str) -> Path:
    path = output_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def seed_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(text)


def load_source(root: Path, name: str | None = None) -> Source:
    config = ModuleConfig.load(root)
    return Source(name=name or config.name, root=root, config=config)
