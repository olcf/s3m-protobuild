from __future__ import annotations

# pylint: disable=protected-access

from pathlib import Path
from typing import Callable

import pytest

from _helpers import make_module_config

from s3m_protobuild.errors import BuildError
from s3m_protobuild.model import Source
from s3m_protobuild.targets import go


def make_fake_go_run(
    *,
    edit_json: str = '{"Require": []}',
    record: list[tuple[list[str], Path | None]] | None = None,
    tidy_error: BuildError | None = None,
) -> Callable[..., str]:
    """Mock for `s3m_protobuild.targets.go.run`: stubs `go version`, `go mod tidy`,
    and `go mod edit -json`. Optionally records calls and raises from `tidy`.
    """

    def fake_run(
        args: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> str:
        _ = env, check
        if record is not None:
            record.append((args, cwd))

        if args == ["go", "version"]:
            return "go version go1.23.4 darwin/arm64\n"
        if args == ["go", "mod", "tidy"]:
            if tidy_error is not None:
                raise tidy_error
            return ""
        if args == ["go", "mod", "edit", "-json"]:
            return edit_json
        raise AssertionError(f"unexpected command: {args}")

    return fake_run


def test_go_mod_writes_replace_paths_verbatim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "out/go"
    output.mkdir(parents=True)
    calls: list[tuple[list[str], Path | None]] = []
    edit_json = (
        '{"Require": ['
        '{"Path": "example.com/external", "Version": "v0.0.0"},'
        '{"Path": "example.com/public", "Version": "v0.0.0"}'
        "]}"
    )

    monkeypatch.setattr(
        go, "run", make_fake_go_run(edit_json=edit_json, record=calls)
    )

    go._write_go_mod(
        output,
        make_module_config(name="internal", go_package="example.com/internal"),
        go_mod_replace={
            "example.com/internal": Path("."),
            "example.com/public": Path("../public-go"),
            "example.com/external": Path("../../deps/external-go"),
        },
        all_sources=[],
        env={"PATH": "test"},
    )

    expected = "\n".join(
        [
            "module example.com/internal",
            "",
            "go 1.23",
            "",
            "require (",
            "\texample.com/external v0.0.0-00010101000000-000000000000",
            "\texample.com/public v0.0.0-00010101000000-000000000000",
            ")",
            "",
            "replace (",
            "\texample.com/external => ../../deps/external-go",
            "\texample.com/public => ../public-go",
            ")",
            "",
        ]
    )

    assert (output / "go.mod").read_text() == expected
    assert calls == [
        (["go", "version"], None),
        (["go", "mod", "tidy"], output),
        (["go", "mod", "edit", "-json"], output),
    ]


def test_unused_go_mod_replace_emits_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "out/go"
    output.mkdir(parents=True)

    monkeypatch.setattr(go, "run", make_fake_go_run())

    go._write_go_mod(
        output,
        make_module_config(name="internal", go_package="example.com/internal"),
        go_mod_replace={"example.com/public": Path("../public-go")},
        all_sources=[],
        env={"PATH": "test"},
    )

    stderr = capsys.readouterr().err

    assert "warning: --go-mod-replace example.com/public" in stderr
    assert "no selected package imports example.com/public" in stderr


def test_go_mod_tidy_failure_suggests_sibling_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "out/go"
    output.mkdir(parents=True)

    tidy_stderr = (
        "go: example.com/internal/foo imports\n"
        "\texample.com/public/bar: module example.com/public@latest found "
        "but does not contain package example.com/public/bar\n"
    )
    monkeypatch.setattr(
        go,
        "run",
        make_fake_go_run(tidy_error=BuildError("Command failed", output=tidy_stderr)),
    )

    public_source = Source(
        name="s3m-public",
        root=tmp_path / "src/public",
        config=make_module_config(name="s3m-public", go_package="example.com/public"),
    )

    with pytest.raises(BuildError) as exc_info:
        go._write_go_mod(
            output,
            make_module_config(name="s3m-internal", go_package="example.com/internal"),
            go_mod_replace={},
            all_sources=[public_source],
            env={"PATH": "test"},
        )

    message = str(exc_info.value)

    assert "--go-mod-replace example.com/public=../s3m-public" in message
    assert exc_info.value.output == tidy_stderr
