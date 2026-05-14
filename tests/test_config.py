from __future__ import annotations

from pathlib import Path

import pytest

from s3m_protobuild.config import ModuleConfig
from s3m_protobuild.errors import BuildError


def write_module_file(root: Path, **values: str) -> None:
    data = {
        "MODULE": "s3m-apis",
        "VERSION": "1.2.3",
        "GO_PACKAGE": "example.com/s3m-apis",
        **values,
    }
    root.mkdir(parents=True, exist_ok=True)

    (root / "MODULE").write_text(
        "".join(f"{key}={value}\n" for key, value in data.items())
    )


@pytest.mark.parametrize("key", ["MODULE", "PY_PACKAGE", "PYB_PACKAGE"])
def test_module_package_names_must_not_be_paths(tmp_path: Path, key: str) -> None:
    write_module_file(tmp_path, **{key: "../outside"})

    with pytest.raises(BuildError, match=key):
        ModuleConfig.load(tmp_path)


@pytest.mark.parametrize(
    "key, value",
    [
        ("MODULE", "S3M-Apis"),
        ("MODULE", "s3m_apis"),
        ("MODULE", "s3m..apis"),
        ("PY_PACKAGE", "s3m-apis-grpcio"),
        ("PYB_PACKAGE", "s3m-apis-betterproto"),
    ],
)
def test_module_package_names_must_match_expected_formats(
    tmp_path: Path, key: str, value: str
) -> None:
    write_module_file(tmp_path, **{key: value})

    with pytest.raises(BuildError, match=key):
        ModuleConfig.load(tmp_path)


@pytest.mark.parametrize(
    "module, py_dist, py_module, pyb_dist, pyb_module",
    [
        (
            "s3m-apis",
            "s3m-apis-grpcio",
            "s3m_apis_grpcio",
            "s3m-apis-betterproto",
            "s3m_apis_betterproto",
        ),
        (
            "s3m-apis-internal",
            "s3m-apis-internal-grpcio",
            "s3m_apis_internal_grpcio",
            "s3m-apis-internal-betterproto",
            "s3m_apis_internal_betterproto",
        ),
    ],
)
def test_python_dist_and_module_names_default_from_module(
    tmp_path: Path,
    module: str,
    py_dist: str,
    py_module: str,
    pyb_dist: str,
    pyb_module: str,
) -> None:
    write_module_file(tmp_path, MODULE=module)

    config = ModuleConfig.load(tmp_path)

    assert config.py_dist_name == py_dist
    assert config.py_module_name == py_module
    assert config.pyb_dist_name == pyb_dist
    assert config.pyb_module_name == pyb_module


def test_python_package_overrides_take_effect(tmp_path: Path) -> None:
    write_module_file(
        tmp_path,
        PY_PACKAGE="my_grpc_pkg",
        PYB_PACKAGE="my_bp_pkg",
    )

    config = ModuleConfig.load(tmp_path)

    assert config.py_dist_name == "my-grpc-pkg"
    assert config.py_module_name == "my_grpc_pkg"
    assert config.pyb_dist_name == "my-bp-pkg"
    assert config.pyb_module_name == "my_bp_pkg"
