from __future__ import annotations

from pathlib import Path

import pytest

from _helpers import (
    PROTO_MESSAGE_BODY,
    load_source,
    make_source,
    make_two_sources,
)

from s3m_protobuild.errors import BuildError
from s3m_protobuild.packages import (
    resolve_selector,
)
from s3m_protobuild.selectors import parse_selector
from s3m_protobuild.staging import staged_source_view

PUBLIC = "s3m-apis"
INTERNAL = "s3m-internal"
MODULES = frozenset({PUBLIC, INTERNAL})


def test_package_family_selects_version_children(tmp_path: Path) -> None:
    root = make_source(tmp_path / "public", packages=("slurm/v0042", "slurm/v0043"))
    selector = parse_selector("slurm:go", {PUBLIC})

    packages = resolve_selector(selector, [load_source(root)])

    assert [package.logical_dir.as_posix() for package in packages] == [
        "slurm/v0042",
        "slurm/v0043",
    ]


def test_specific_version_selects_only_that_version(tmp_path: Path) -> None:
    root = make_source(tmp_path / "public", packages=("slurm/v0042", "slurm/v0043"))
    selector = parse_selector("slurm/v0043:go", {PUBLIC})

    packages = resolve_selector(selector, [load_source(root)])

    assert [package.logical_dir.as_posix() for package in packages] == ["slurm/v0043"]


def test_ambiguous_unqualified_exact_package_fails(tmp_path: Path) -> None:
    first, second = make_two_sources(tmp_path, ("status/v1alpha",), ("status/v1alpha",))
    selector = parse_selector("status:go", MODULES)

    with pytest.raises(BuildError, match="Ambiguous package selector"):
        resolve_selector(selector, [load_source(first), load_source(second)])


def test_unqualified_family_can_span_modules_when_versions_do_not_overlap(
    tmp_path: Path,
) -> None:
    first, second = make_two_sources(tmp_path, ("slurm/v0044",), ("slurm/v0045",))
    selector = parse_selector("slurm:go", MODULES)

    packages = resolve_selector(selector, [load_source(first), load_source(second)])

    assert [package.logical_dir.as_posix() for package in packages] == [
        "slurm/v0044",
        "slurm/v0045",
    ]


def test_module_qualified_overlap_resolves(tmp_path: Path) -> None:
    first, second = make_two_sources(tmp_path, ("slurm/v0044",), ("slurm/v0045",))
    selector = parse_selector(f"{INTERNAL}/slurm/v0045:go", MODULES)

    packages = resolve_selector(selector, [load_source(first), load_source(second)])

    assert [
        (package.source.name, package.logical_dir.as_posix()) for package in packages
    ] == [(INTERNAL, "slurm/v0045")]


def test_staging_allows_same_family_different_versions(tmp_path: Path) -> None:
    first, second = make_two_sources(tmp_path, ("slurm/v0044",), ("slurm/v0045",))
    sources = [load_source(first), load_source(second)]
    packages = [
        *resolve_selector(parse_selector(f"{PUBLIC}/slurm/v0044:go", MODULES), sources),
        *resolve_selector(
            parse_selector(f"{INTERNAL}/slurm/v0045:go", MODULES), sources
        ),
    ]

    with staged_source_view(sources, packages) as (stage, staged):
        assert (stage / "proto/slurm/v0044/v0044.proto").exists()
        assert (stage / "proto/slurm/v0045/v0045.proto").exists()
        assert [package.staged_dir.name for package in staged] == ["v0044", "v0045"]


def test_staging_rejects_selected_exact_package_from_multiple_modules(
    tmp_path: Path,
) -> None:
    first, second = make_two_sources(tmp_path, ("slurm/v0044",), ("slurm/v0044",))
    sources = [load_source(first), load_source(second)]
    packages = [
        *resolve_selector(parse_selector(f"{PUBLIC}/slurm/v0044:go", MODULES), sources),
        *resolve_selector(
            parse_selector(f"{INTERNAL}/slurm/v0044:go", MODULES), sources
        ),
    ]

    with (
        pytest.raises(BuildError, match="multiple source modules"),
        staged_source_view(sources, packages),
    ):
        pass


def test_staging_rejects_conflicting_third_party_files(tmp_path: Path) -> None:
    first, second = make_two_sources(tmp_path, ("status/v1alpha",), ("slurm/v0042",))
    (first / "third_party/google/api").mkdir(parents=True)
    (second / "third_party/google/api").mkdir(parents=True)
    (first / "third_party/google/api/http.proto").write_text("one\n")
    (second / "third_party/google/api/http.proto").write_text("two\n")

    sources = [load_source(first), load_source(second)]
    packages = resolve_selector(parse_selector(f"{PUBLIC}/status:go", MODULES), sources)

    with (
        pytest.raises(BuildError, match="dependency file collision"),
        staged_source_view(sources, packages),
    ):
        pass


def test_staging_collision_message_names_both_sources(tmp_path: Path) -> None:
    first, second = make_two_sources(tmp_path, ("status/v1alpha",), ("slurm/v0042",))
    (first / "proto/shared/util").mkdir(parents=True)
    (second / "proto/shared/util").mkdir(parents=True)
    (first / "proto/shared/util/types.proto").write_text("one\n")
    (second / "proto/shared/util/types.proto").write_text("two\n")

    sources = [load_source(first), load_source(second)]
    packages = resolve_selector(parse_selector(f"{PUBLIC}/status:go", MODULES), sources)

    with pytest.raises(BuildError) as exc_info:
        with staged_source_view(sources, packages):
            pass

    message = str(exc_info.value)

    assert "shared/util/types.proto" in message
    assert PUBLIC in message
    assert INTERNAL in message


def test_staging_skips_symlinked_proto_files(tmp_path: Path) -> None:
    root = make_source(tmp_path / "source", packages=("status/v1alpha",))
    outside = tmp_path / "secret.proto"
    outside.write_text("secret\n")
    (root / "proto/status/v1alpha/secret.proto").symlink_to(outside)

    sources = [load_source(root)]
    packages = resolve_selector(parse_selector("status:go", {PUBLIC}), sources)

    with staged_source_view(sources, packages) as (stage, _):
        assert not (stage / "proto/status/v1alpha/secret.proto").exists()


def test_staging_injects_sibling_package_directive(tmp_path: Path) -> None:
    root = make_source(tmp_path / "source", packages=("koas/v1alpha",))
    (root / "proto/koas/v1alpha/argo.proto").write_text(PROTO_MESSAGE_BODY)

    sources = [load_source(root)]
    packages = resolve_selector(parse_selector("koas:go", {PUBLIC}), sources)

    with staged_source_view(sources, packages) as (stage, _):
        argo_text = (stage / "proto/koas/v1alpha/argo.proto").read_text()

        assert "package s3m_apis.v1alpha;" in argo_text


def test_staging_fails_when_directory_has_no_package_directive(tmp_path: Path) -> None:
    root = make_source(
        tmp_path / "source",
        name="demo",
        packages=("foo/v1",),
        include_package_directive=False,
    )
    (root / "proto/foo/v1/extra.proto").write_text(PROTO_MESSAGE_BODY)

    sources = [load_source(root)]
    packages = resolve_selector(parse_selector("foo:go", {"demo"}), sources)

    with pytest.raises(BuildError, match="No `package` directive"):
        with staged_source_view(sources, packages):
            pass


def test_staging_logs_one_line_per_directory_for_inherited_package_directives(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_source(tmp_path / "source", packages=("koas/v1alpha",))
    package_dir = root / "proto/koas/v1alpha"
    (package_dir / "argo.proto").write_text(PROTO_MESSAGE_BODY)
    (package_dir / "certs.proto").write_text(PROTO_MESSAGE_BODY)

    sources = [load_source(root)]
    packages = resolve_selector(parse_selector("koas:go", {PUBLIC}), sources)

    with staged_source_view(sources, packages):
        pass

    stderr = capsys.readouterr().err
    inferred_lines = [
        line for line in stderr.splitlines() if "inferred `package " in line
    ]
    assert len(inferred_lines) == 1
    line = inferred_lines[0]

    assert "proto/koas/v1alpha/" in line
    assert "s3m_apis.v1alpha" in line
    assert "for 2 files from sibling" in line
    assert "warning" not in line.lower()
