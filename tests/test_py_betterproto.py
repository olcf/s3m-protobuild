from __future__ import annotations

from pathlib import Path

import pytest

from _helpers import seed_tree

from s3m_protobuild.errors import BuildError
from s3m_protobuild.targets.py_betterproto import _flatten_namespaces


def test_flatten_recomputes_relative_dots_for_moved_files(tmp_path: Path) -> None:
    package_root = tmp_path / "s3minternal"

    seed_tree(
        package_root,
        {
            "__init__.py": "class KeyValuePair: pass\n",
            "olcf/__init__.py": "",
            "olcf/s3minternal/__init__.py": "",
            "olcf/s3minternal/streamingadmin/__init__.py": (
                "from .... import KeyValuePair as ___KeyValuePair__\n"
                "x = ___KeyValuePair__\n"
            ),
        },
    )

    _flatten_namespaces(package_root, ("olcf.s3minternal",))

    assert (package_root / "__init__.py").read_text() == "class KeyValuePair: pass\n"
    streamingadmin = (package_root / "streamingadmin" / "__init__.py").read_text()

    assert "from .. import KeyValuePair as ___KeyValuePair__" in streamingadmin


def test_flatten_preserves_top_level_when_intermediate_init_is_empty(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "s3minternal"

    seed_tree(
        package_root,
        {
            "__init__.py": "TOP_LEVEL = 1\n",
            "olcf/__init__.py": "",
            "olcf/s3minternal/__init__.py": "",
        },
    )

    _flatten_namespaces(package_root, ("olcf.s3minternal",))

    assert (package_root / "__init__.py").read_text() == "TOP_LEVEL = 1\n"


def test_flatten_fails_clearly_on_non_empty_init_collision(tmp_path: Path) -> None:
    package_root = tmp_path / "s3minternal"

    seed_tree(
        package_root,
        {
            "__init__.py": "TOP_LEVEL = 1\n",
            "olcf/__init__.py": "",
            "olcf/s3minternal/__init__.py": "OTHER = 2\n",
        },
    )

    with pytest.raises(BuildError, match="missing a `package` directive"):
        _flatten_namespaces(package_root, ("olcf.s3minternal",))


def test_flatten_preserves_dots_when_file_and_target_share_flatten_domain(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "s3m_apis_betterproto"

    seed_tree(
        package_root,
        {
            "olcf/__init__.py": "",
            "olcf/s3m/__init__.py": "",
            "olcf/s3m/common/__init__.py": "",
            "olcf/s3m/common/v1alpha/__init__.py": "class HeaderParam: pass\n",
            "olcf/s3m/streaming/__init__.py": "",
            "olcf/s3m/streaming/v1alpha/__init__.py": (
                "from ...common.v1alpha import HeaderParam\n"
            ),
        },
    )

    _flatten_namespaces(package_root, ("olcf.s3m",))

    moved = (package_root / "streaming" / "v1alpha" / "__init__.py").read_text()

    assert "from ...common.v1alpha import HeaderParam" in moved


def test_flatten_recomputes_dots_for_cross_domain_references(tmp_path: Path) -> None:
    package_root = tmp_path / "s3minternal"

    seed_tree(
        package_root,
        {
            "olcf/__init__.py": "",
            "olcf/s3m/__init__.py": "",
            "olcf/s3m/common/__init__.py": "",
            "olcf/s3m/common/v1alpha/__init__.py": "class HeaderParam: pass\n",
            "olcf/s3minternal/__init__.py": "",
            "olcf/s3minternal/streamingadmin/__init__.py": (
                "from ...s3m.common.v1alpha import HeaderParam\n"
            ),
        },
    )

    _flatten_namespaces(package_root, ("olcf.s3m", "olcf.s3minternal"))

    moved = (package_root / "streamingadmin" / "__init__.py").read_text()

    assert "from ..common.v1alpha import HeaderParam" in moved
