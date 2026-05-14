from __future__ import annotations

import pytest

from s3m_protobuild.errors import BuildError
from s3m_protobuild.selectors import dedupe_selectors, parse_selector


def test_parse_unqualified_selector() -> None:
    selector = parse_selector("status:go", {"s3m-apis"})

    assert selector.source_name is None
    assert selector.package_text == "status"
    assert selector.target == "go"


def test_parse_source_qualified_selector() -> None:
    selector = parse_selector(
        "s3m-apis-internal/koas/v1alpha:pyb", {"s3m-apis-internal"}
    )

    assert selector.source_name == "s3m-apis-internal"
    assert selector.package_text == "koas/v1alpha"
    assert selector.target == "pyb"


@pytest.mark.parametrize(
    "raw", ["status", "status:", ":go", "status:java", "../status:go", "a/b/c:go"]
)
def test_rejects_bad_selectors(raw: str) -> None:
    with pytest.raises(BuildError):
        parse_selector(raw, {"s3m-apis"})


def test_duplicate_selectors_are_harmless() -> None:
    selectors = [
        parse_selector("status:go", {"s3m-apis"}),
        parse_selector("status:go", {"s3m-apis"}),
    ]

    assert len(dedupe_selectors(selectors)) == 1
