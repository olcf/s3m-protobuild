from __future__ import annotations

from pathlib import Path

import pytest

from _helpers import make_source

from s3m_protobuild.clean import clean
from s3m_protobuild.errors import BuildError
from s3m_protobuild.output import (
    prepare_output_root,
    reduce_package_directory,
    validate_output_root,
)


def test_refuses_source_root_output(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source")

    with pytest.raises(BuildError, match="source root"):
        validate_output_root(source, [source])


def test_refuses_proto_child_output(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source")

    with pytest.raises(BuildError, match="inside a source root"):
        validate_output_root(source / "proto" / "out", [source])


def test_refuses_any_output_inside_source_root(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source")

    with pytest.raises(BuildError, match="inside a source root"):
        validate_output_root(source / "generated-out", [source])


def test_refuses_non_empty_unmanaged_output(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source")
    out = tmp_path / "out"
    out.mkdir()

    (out / "user.txt").write_text("keep")

    with pytest.raises(BuildError, match="unmanaged"):
        validate_output_root(out, [source])


def test_empty_existing_output_does_not_need_marker(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source")
    out = tmp_path / "out"
    out.mkdir()

    validate_output_root(out, [source])
    prepare_output_root(out, [source])

    assert out.exists()


def test_managed_output_can_be_prepared(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source")
    out = tmp_path / "out"
    out.mkdir()

    (out / "build.info").write_text("build info\n")
    (out / "old.txt").write_text("old")

    prepare_output_root(out, [source])

    assert out.exists()
    assert not (out / "old.txt").exists()


def test_clean_removes_managed_output_root(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()

    (out / "build.info").write_text("build info\n")
    (out / "generated.py").write_text("generated\n")
    (out / "pkg").mkdir()
    (out / "pkg/__init__.py").write_text("")

    clean(out)

    assert not out.exists()


def test_clean_refuses_unmarked_output_root(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()

    (out / "scratch.txt").write_text("keep me\n")

    with pytest.raises(BuildError, match="unmarked"):
        clean(out)

    assert (out / "scratch.txt").exists()


def test_reduce_package_directory_collapses_nested_empty_chain(tmp_path: Path) -> None:
    root = tmp_path / "pkg"
    (root / "a" / "b" / "c").mkdir(parents=True)
    (root / "a" / "__init__.py").write_text("")
    (root / "a" / "b" / "__init__.py").write_text("")
    (root / "a" / "b" / "c" / "__init__.py").write_text("")

    reduce_package_directory(root)

    assert not (root / "a").exists()


def test_reduce_package_directory_keeps_ancestors_of_real_content(tmp_path: Path) -> None:
    root = tmp_path / "pkg"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "__init__.py").write_text("")
    (root / "a" / "b" / "__init__.py").write_text("")
    (root / "a" / "b" / "real.py").write_text("x = 1\n")

    reduce_package_directory(root)

    assert (root / "a" / "__init__.py").exists()
    assert (root / "a" / "b" / "__init__.py").exists()
    assert (root / "a" / "b" / "real.py").exists()


def test_reduce_package_directory_keeps_non_empty_init(tmp_path: Path) -> None:
    root = tmp_path / "pkg"
    (root / "a").mkdir(parents=True)
    (root / "a" / "__init__.py").write_text("from . import x\n")

    reduce_package_directory(root)

    assert (root / "a" / "__init__.py").exists()
