from __future__ import annotations

from pathlib import Path

from _helpers import load_source, make_source

from s3m_protobuild.targets.py_grpcio import (
    _python_package_owners,
    _rewrite_proto_imports,
)


def test_grpcio_rewrite_uses_import_owner_package(tmp_path: Path) -> None:
    public = make_source(
        tmp_path / "public", name="s3m-apis", packages=("common/v1alpha",)
    )
    internal = make_source(
        tmp_path / "internal", name="s3m-apis-internal", packages=("koas/v1alpha",)
    )
    package_root = tmp_path / "out" / "s3m_apis_internal_grpcio"
    package_root.mkdir(parents=True)
    generated = package_root / "sample_pb2.py"
    generated.write_text(
        "\n".join(
            [
                (
                    "from proto.common.v1alpha import headers_pb2 "
                    "as proto_dot_common_dot_v1alpha_dot_headers__pb2"
                ),
                (
                    "from proto.koas.v1alpha import common_pb2 "
                    "as proto_dot_koas_dot_v1alpha_dot_common__pb2"
                ),
                "import proto.common.v1alpha.headers_pb2 as headers__pb2",
                "",
            ]
        )
    )

    owners = _python_package_owners(
        [load_source(public, "s3m-apis"), load_source(internal, "s3m-apis-internal")]
    )

    _rewrite_proto_imports(package_root, owners, "s3m_apis_internal_grpcio")

    assert generated.read_text().splitlines() == [
        (
            "from s3m_apis_grpcio.common.v1alpha import headers_pb2 "
            "as proto_dot_common_dot_v1alpha_dot_headers__pb2"
        ),
        (
            "from s3m_apis_internal_grpcio.koas.v1alpha import common_pb2 "
            "as proto_dot_koas_dot_v1alpha_dot_common__pb2"
        ),
        "import s3m_apis_grpcio.common.v1alpha.headers_pb2 as headers__pb2",
    ]
