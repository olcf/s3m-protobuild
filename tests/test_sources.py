from __future__ import annotations

import pytest

from s3m_protobuild.errors import BuildError
from s3m_protobuild.sources import split_remote_ref


@pytest.mark.parametrize(
    "raw, url, ref",
    [
        (
            "git+https://github.com/olcf/s3m-apis.git",
            "https://github.com/olcf/s3m-apis.git",
            None,
        ),
        (
            "git+https://github.com/olcf/s3m-apis.git@main",
            "https://github.com/olcf/s3m-apis.git",
            "main",
        ),
        (
            "git+ssh://git@github.com/olcf/s3m-apis.git",
            "ssh://git@github.com/olcf/s3m-apis.git",
            None,
        ),
        (
            "git+ssh://git@github.com/olcf/s3m-apis.git@v1.2",
            "ssh://git@github.com/olcf/s3m-apis.git",
            "v1.2",
        ),
        (
            "git+https://github.com/olcf/s3m-apis.git@release/1.2",
            "https://github.com/olcf/s3m-apis.git",
            "release/1.2",
        ),
        (
            "git+ssh://git@github.com/olcf/s3m-apis.git@feature/foo",
            "ssh://git@github.com/olcf/s3m-apis.git",
            "feature/foo",
        ),
    ],
)
def test_split_remote_ref(raw: str, url: str, ref: str | None) -> None:
    assert split_remote_ref(raw) == (url, ref)


def test_scp_style_ssh_rejected() -> None:
    with pytest.raises(BuildError, match=r"git\+<scheme>://"):
        split_remote_ref("git+git@github.com:olcf/s3m-apis.git")


def test_empty_after_prefix_rejected() -> None:
    with pytest.raises(BuildError, match="missing a URL"):
        split_remote_ref("git+")
