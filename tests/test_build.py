from __future__ import annotations

# pylint: disable=unused-argument

import os
from pathlib import Path

import pytest

from _helpers import make_source, make_two_sources, write_generated_file

from s3m_protobuild import build as build_module
from s3m_protobuild.build import build
from s3m_protobuild.errors import BuildError
from s3m_protobuild.model import DescriptorOptions, ResolvedPackage
from s3m_protobuild.sources import SourceRequest


def make_fake_go(
    relative: str = "status/v1alpha/v1alpha.pb.go",
    content: str = "package v1alpha\n",
    observer=None,
):
    def fake_generate_go(
        output_root: Path,
        config,
        stage_root: Path,
        packages: list[ResolvedPackage],
        all_sources,
        go_mod_replace,
        env=None,
    ) -> None:
        if observer is not None:
            observer(
                output_root=output_root,
                stage_root=stage_root,
                packages=packages,
                all_sources=all_sources,
                go_mod_replace=go_mod_replace,
            )

        write_generated_file(output_root, relative, content)

    return fake_generate_go


def make_fake_grpcio(relative_under_config: str = "status/v1alpha/v1alpha_pb2.py"):
    def fake_generate_grpcio(
        output_root: Path,
        config,
        stage_root: Path,
        packages: list[ResolvedPackage],
        all_sources,
        env=None,
    ) -> None:
        write_generated_file(
            output_root, f"{config.name}/{relative_under_config}", "# generated\n"
        )

    return fake_generate_grpcio


def make_fake_betterproto(relative_under_config: str = "koas/v1alpha/__init__.py"):
    def fake_generate_betterproto(
        output_root: Path,
        config,
        stage_root: Path,
        packages: list[ResolvedPackage],
        env=None,
    ) -> None:
        write_generated_file(
            output_root, f"{config.name}/{relative_under_config}", "# generated\n"
        )

    return fake_generate_betterproto


def write_go_helper(source: Path) -> None:
    helper = source / "res/go/pkg/s3mutil/conn.go"
    helper.parent.mkdir(parents=True)
    helper.write_text("package s3mutil\n")


def test_oas_and_descriptor_share_output_root_with_one_specs_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_source(tmp_path / "source", packages=("status/v1alpha",))
    output_dir = tmp_path / "dist"
    calls: list[tuple[Path, Path, list[str], bool, DescriptorOptions]] = []

    def fake_generate_openapi_and_descriptor(
        output_root: Path,
        stage_root: Path,
        packages: list[ResolvedPackage],
        generate_openapi: bool,
        descriptor: DescriptorOptions,
        descriptor_packages: list[ResolvedPackage] | None = None,
        env=None,
    ) -> None:
        assert generate_openapi
        calls.append(
            (
                output_root,
                stage_root,
                [package.logical_dir.as_posix() for package in packages],
                generate_openapi,
                descriptor,
            )
        )

        openapi = output_root / "openapi.yaml"
        descriptor_path = descriptor.output_root / descriptor.relative_path
        openapi.parent.mkdir(parents=True, exist_ok=True)
        descriptor_path.parent.mkdir(parents=True, exist_ok=True)

        openapi.write_text("openapi: 3.0.0\n")
        descriptor_path.write_bytes(b"descriptor")

    monkeypatch.setattr(
        build_module,
        "generate_openapi_and_descriptor",
        fake_generate_openapi_and_descriptor,
    )

    build(
        source_requests=[SourceRequest(str(source))],
        selector_texts=["status:oas"],
        output_dir=output_dir,
        descriptor_out=Path("descriptors/status.bin"),
    )

    assert len(calls) == 1

    output_root, stage_root, packages, generate_openapi, descriptor = calls[0]
    assert output_root == output_dir.resolve()
    assert stage_root.name.startswith("s3m-protobuild-")
    assert packages == ["status/v1alpha"]
    assert generate_openapi is True
    assert descriptor.output_root == output_dir.resolve()
    assert descriptor.relative_path == Path("descriptors/status.bin")

    assert (output_dir / "openapi.yaml").exists()
    assert (output_dir / "descriptors/status.bin").exists()


def test_oas_uses_only_oas_selected_packages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_go_preflight: None,
) -> None:
    source = make_source(
        tmp_path / "source", packages=("status/v1alpha", "slurm/v0042")
    )
    observed: dict[str, list[str]] = {}

    def fake_generate_openapi_and_descriptor(
        output_root: Path,
        stage_root: Path,
        packages: list[ResolvedPackage],
        generate_openapi: bool,
        descriptor: DescriptorOptions,
        descriptor_packages: list[ResolvedPackage] | None = None,
        env=None,
    ) -> None:
        observed["openapi"] = [package.logical_dir.as_posix() for package in packages]
        openapi = output_root / "openapi.yaml"
        openapi.write_text("openapi: 3.0.0\n")

    monkeypatch.setattr(
        build_module,
        "generate_go",
        make_fake_go(relative="slurm/v0042/v0042.pb.go", content="package v0042\n"),
    )
    monkeypatch.setattr(
        build_module,
        "generate_openapi_and_descriptor",
        fake_generate_openapi_and_descriptor,
    )

    build(
        source_requests=[SourceRequest(str(source))],
        selector_texts=["status:oas", "slurm/v0042:go"],
        output_dir=tmp_path / "dist",
    )

    assert observed == {"openapi": ["status/v1alpha"]}


def test_descriptor_path_must_stay_inside_specs_root(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source", packages=("status/v1alpha",))

    with pytest.raises(BuildError, match="descriptor path"):
        build(
            source_requests=[SourceRequest(str(source))],
            selector_texts=["status:go"],
            output_dir=tmp_path / "dist",
            descriptor_out=Path("../desc.bin"),
        )


def test_multi_source_build_stages_all_sources_without_inferred_replaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_go_preflight: None,
) -> None:
    public, internal = make_two_sources(
        tmp_path,
        ("common/v1alpha",),
        ("koas/v1alpha",),
        first_dir="public",
        second_dir="internal",
    )
    (internal / "proto/koas/v1alpha/v1alpha.proto").write_text(
        "\n".join(
            [
                'syntax = "proto3";',
                "package s3m_internal.koas.v1alpha;",
                'import "proto/common/v1alpha/v1alpha.proto";',
                "",
            ]
        )
    )

    observed: dict[str, object] = {}

    def observer(*, output_root, stage_root, packages, all_sources, go_mod_replace):
        observed["packages"] = [package.logical_dir.as_posix() for package in packages]
        observed["sources"] = [source.name for source in all_sources]
        observed["has_public_dependency"] = (
            stage_root / "proto/common/v1alpha/v1alpha.proto"
        ).exists()
        observed["has_internal_target"] = (
            stage_root / "proto/koas/v1alpha/v1alpha.proto"
        ).exists()
        observed["go_mod_replace"] = go_mod_replace

    monkeypatch.setattr(
        build_module,
        "generate_go",
        make_fake_go(
            "koas/v1alpha/v1alpha.pb.go", "package v1alpha\n", observer=observer
        ),
    )

    build(
        source_requests=[SourceRequest(str(public)), SourceRequest(str(internal))],
        selector_texts=["s3m-internal/koas/v1alpha:go"],
        output_dir=tmp_path / "dist",
    )

    assert observed == {
        "packages": ["koas/v1alpha"],
        "sources": ["s3m-apis", "s3m-internal"],
        "has_public_dependency": True,
        "has_internal_target": True,
        "go_mod_replace": {},
    }

    assert (tmp_path / "dist/koas/v1alpha/v1alpha.pb.go").exists()


def test_explicit_go_mod_replaces_are_passed_to_go_generator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_go_preflight: None,
) -> None:
    public, internal = make_two_sources(
        tmp_path,
        ("common/v1alpha",),
        ("koas/v1alpha",),
        first_dir="public",
        second_dir="internal",
    )
    observed: dict[str, Path] = {}

    def observer(*, go_mod_replace, **_):
        observed.update(go_mod_replace)

    monkeypatch.setattr(
        build_module,
        "generate_go",
        make_fake_go(
            "koas/v1alpha/v1alpha.pb.go", "package v1alpha\n", observer=observer
        ),
    )

    build(
        source_requests=[SourceRequest(str(public)), SourceRequest(str(internal))],
        selector_texts=["s3m-internal/koas/v1alpha:go"],
        output_dir=tmp_path / "dist",
        go_mod_replace={"example.com/s3m-apis": tmp_path / "local/s3m-apis-go"},
    )

    assert observed == {"example.com/s3m-apis": tmp_path / "local/s3m-apis-go"}


def test_generated_package_artifacts_from_multiple_modules_need_separate_outputs(
    tmp_path: Path,
    stub_go_preflight: None,
) -> None:
    public, internal = make_two_sources(
        tmp_path,
        ("common/v1alpha",),
        ("koas/v1alpha",),
        first_dir="public",
        second_dir="internal",
    )

    with pytest.raises(BuildError, match="only one source module"):
        build(
            source_requests=[SourceRequest(str(public)), SourceRequest(str(internal))],
            selector_texts=[
                "s3m-internal/koas/v1alpha:go",
                "s3m-apis/common/v1alpha:go",
            ],
            output_dir=tmp_path / "dist",
        )


def test_go_resources_are_copied_before_go_mod_tidy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_go_preflight: None,
) -> None:
    source = make_source(tmp_path / "source", packages=("status/v1alpha",))
    write_go_helper(source)
    observed: dict[str, bool] = {}

    def observer(*, output_root, **_):
        observed["helper_present"] = (output_root / "pkg/s3mutil/conn.go").exists()

    monkeypatch.setattr(build_module, "generate_go", make_fake_go(observer=observer))

    build(
        source_requests=[SourceRequest(str(source))],
        selector_texts=["status/v1alpha:go"],
        output_dir=tmp_path / "dist",
    )

    assert observed == {"helper_present": True}


def test_build_adds_writable_go_cache_flag_without_local_go(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_go_preflight: None,
) -> None:
    source = make_source(tmp_path / "source", packages=("status/v1alpha",))
    seen_env: dict[str, str] = {}

    def fake_generate_go(
        output_root: Path,
        config,
        stage_root: Path,
        packages: list[ResolvedPackage],
        all_sources,
        go_mod_replace,
        env=None,
    ) -> None:
        assert env is not None
        seen_env.update(env)
        write_generated_file(
            output_root, "status/v1alpha/v1alpha.pb.go", "package v1alpha\n"
        )

    monkeypatch.setenv("GOFLAGS", "-mod=readonly")
    monkeypatch.setattr(build_module, "generate_go", fake_generate_go)

    build(
        source_requests=[SourceRequest(str(source))],
        selector_texts=["status/v1alpha:go"],
        output_dir=tmp_path / "dist",
    )

    assert seen_env["GOFLAGS"] == "-mod=readonly -modcacherw"


def test_build_uses_local_go_workspace_when_go_dir_is_passed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_go_preflight: None,
) -> None:
    source = make_source(tmp_path / "source", packages=("status/v1alpha",))
    go_dir = tmp_path / ".go"
    (go_dir / "bin").mkdir(parents=True)
    seen_env: dict[str, str] = {}

    def fake_generate_go(
        output_root: Path,
        config,
        stage_root: Path,
        packages: list[ResolvedPackage],
        all_sources,
        go_mod_replace,
        env=None,
    ) -> None:
        assert env is not None
        seen_env.update(env)
        write_generated_file(
            output_root, "status/v1alpha/v1alpha.pb.go", "package v1alpha\n"
        )

    monkeypatch.setattr(build_module, "generate_go", fake_generate_go)

    build(
        source_requests=[SourceRequest(str(source))],
        selector_texts=["status/v1alpha:go"],
        output_dir=tmp_path / "dist",
        go_dir=go_dir,
    )

    resolved = go_dir.resolve()

    assert seen_env["PATH"].startswith(str(resolved / "bin") + os.pathsep)
    assert seen_env["GOPATH"] == str(resolved)
    assert seen_env["GOMODCACHE"] == str(resolved / "pkg" / "mod")
    assert seen_env["GOCACHE"] == str(resolved / "cache")
    assert "-modcacherw" in seen_env["GOFLAGS"]


def test_go_tool_preflight_happens_before_resource_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_source(tmp_path / "source", packages=("status/v1alpha",))
    write_go_helper(source)
    out = tmp_path / "dist"

    def fake_require_go_tools(all_sources, env=None):
        raise BuildError("missing go tools")

    monkeypatch.setattr(build_module, "require_go_tools", fake_require_go_tools)

    with pytest.raises(BuildError, match="missing go tools"):
        build(
            source_requests=[SourceRequest(str(source))],
            selector_texts=["status/v1alpha:go"],
            output_dir=out,
        )

    assert not (out / "pkg/s3mutil/conn.go").exists()
    assert not any(out.iterdir())


def test_user_provided_setup_py_is_preserved_and_version_module_is_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_source(tmp_path / "source", packages=("status/v1alpha",))
    user_setup = (
        "from setuptools import setup\n"
        "from s3m_apis_grpcio._version import version\n"
        "\n"
        "setup(\n"
        '    name="s3m-apis-grpcio",\n'
        "    version=version,\n"
        '    install_requires=["protobuf"],\n'
        ")\n"
    )
    resource = source / "res/py/setup.py"
    resource.parent.mkdir(parents=True)
    resource.write_text(user_setup)

    out = tmp_path / "dist"

    monkeypatch.setattr(build_module, "generate_grpcio", make_fake_grpcio())

    build(
        source_requests=[SourceRequest(str(source))],
        selector_texts=["status/v1alpha:py"],
        output_dir=out,
    )

    assert (out / "setup.py").read_text() == user_setup

    assert (out / "s3m_apis_grpcio/_version.py").read_text() == 'version = "1.2.3"\n'

    build_info = (out / "build.info").read_text()

    assert "source.git.commit: " in build_info
    assert "Commit Hash: " not in build_info


def test_python_packaging_is_created_when_resources_are_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_source(
        tmp_path / "source", name="s3minternal", packages=("koas/v1alpha",)
    )
    out = tmp_path / "dist"

    monkeypatch.setattr(
        build_module, "generate_grpcio", make_fake_grpcio("koas/v1alpha/v1alpha_pb2.py")
    )

    build(
        source_requests=[SourceRequest(str(source))],
        selector_texts=["koas/v1alpha:py"],
        output_dir=out,
    )

    setup_text = (out / "setup.py").read_text()

    assert 'name="s3minternal-grpcio"' in setup_text
    assert "from s3minternal_grpcio._version import version" in setup_text

    assert (
        out / "MANIFEST.in"
    ).read_text() == "recursive-include s3minternal_grpcio *\n"
    assert (out / "s3minternal_grpcio/_version.py").read_text() == 'version = "1.2.3"\n'


def test_betterproto_packaging_is_created_when_resources_are_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_source(
        tmp_path / "source", name="s3minternal", packages=("koas/v1alpha",)
    )
    out = tmp_path / "dist"

    monkeypatch.setattr(build_module, "generate_betterproto", make_fake_betterproto())

    build(
        source_requests=[SourceRequest(str(source))],
        selector_texts=["koas/v1alpha:pyb"],
        output_dir=out,
    )

    assert 'name="s3minternal-betterproto"' in (out / "setup.py").read_text()
    assert (out / "MANIFEST.in").exists()


def test_py_and_pyb_targets_need_separate_outputs(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source", packages=("koas/v1alpha",))

    with pytest.raises(BuildError, match="py and pyb"):
        build(
            source_requests=[SourceRequest(str(source))],
            selector_texts=["koas/v1alpha:py", "koas/v1alpha:pyb"],
            output_dir=tmp_path / "dist",
        )
