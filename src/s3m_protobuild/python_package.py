from __future__ import annotations

from pathlib import Path


def ensure_python_packaging(
    output_root: Path,
    dist_name: str,
    module_name: str,
    install_requires: tuple[str, ...],
) -> list[Path]:
    written: list[Path] = []

    setup_py = output_root / "setup.py"
    if not setup_py.exists():
        setup_py.write_text(_render_setup_py(dist_name, module_name, install_requires))
        written.append(setup_py)

    manifest = output_root / "MANIFEST.in"
    if not manifest.exists():
        manifest.write_text(f"recursive-include {module_name} *\n")
        written.append(manifest)

    return written


def write_version_module(output_root: Path, module_name: str, version: str) -> Path:
    package_dir = output_root / module_name
    package_dir.mkdir(parents=True, exist_ok=True)
    version_file = package_dir / "_version.py"
    version_file.write_text(f'version = "{version}"\n')
    return version_file


def _render_setup_py(
    dist_name: str, module_name: str, install_requires: tuple[str, ...]
) -> str:
    deps = "".join(f'        "{dep}",\n' for dep in install_requires)

    return (
        "from setuptools import find_packages, setup\n"
        "\n"
        f"from {module_name}._version import version\n"
        "\n"
        "setup(\n"
        f'    name="{dist_name}",\n'
        "    version=version,\n"
        "    packages=find_packages(),\n"
        "    include_package_data=True,\n"
        "    install_requires=[\n"
        f"{deps}"
        "    ],\n"
        ")\n"
    )
