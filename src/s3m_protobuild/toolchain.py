from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

from .errors import BuildError
from .run import env_with_local_tools, log, run

PYTHON_BUILD_DEPS = (
    "grpcio-tools==1.80.0",
    "betterproto[compiler]==2.0.0b7",
    "PyYAML==6.0.3",
)

# Importable module names corresponding to PYTHON_BUILD_DEPS, so `env` can verify
# the installed packages are actually usable from chosen Python toolchain. Each
# value is the install spec to suggest when the module is missing (unversioned,
# since these go into `s3m-protobuild setup python` guidance).
PYTHON_BUILD_MODULES = {
    "grpc_tools.protoc": "grpcio-tools",
    "betterproto": "betterproto[compiler]",
    "black": "betterproto[compiler]",
    "yaml": "PyYAML",
}

GO_BUILD_TOOLS = (
    "google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.11",
    "google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.6.1",
    "github.com/grpc-ecosystem/grpc-gateway/v2/protoc-gen-grpc-gateway@v2.29.0",
    "github.com/favadi/protoc-go-inject-tag@v1.4.0",
    "github.com/ogen-go/protoc-gen-oas/cmd/protoc-gen-oas@v0.14.0",
)


def setup_local_tools(
    venv: Path | None, go_dir: Path | None, python: bool, go: bool
) -> None:
    missing: list[str] = []
    if python and not venv:
        missing.append("`setup python` requires --venv.")
    if go and not go_dir:
        missing.append("`setup go` requires --go.")
    if missing:
        raise BuildError(
            " ".join(missing)
            + " (This tool does not support mutating system toolchain state.)"
        )

    if python:
        if not venv.exists():
            run([sys.executable, "-m", "venv", str(venv)])
        elif not (venv / "pyvenv.cfg").exists():
            raise BuildError(
                f"`{venv}` exists but is not a Python virtualenv "
                "(no pyvenv.cfg found).\n"
                "  Pass --venv at a fresh path, or remove this directory first."
            )

        if sys.platform == "win32":
            python_bin = venv / "Scripts" / "python.exe"
        else:
            python_bin = venv / "bin" / "python"

        run(
            [
                str(python_bin),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                *PYTHON_BUILD_DEPS,
            ]
        )

    if go:
        if not shutil.which("go"):
            raise BuildError(
                "`go` is required but not on PATH.\n" + system_install_guidance("go")
            )

        go_dir.mkdir(parents=True, exist_ok=True)

        bin_dir, pkg_dir, cache_dir = (
            (go_dir / name).resolve() for name in ("bin", "pkg", "cache")
        )
        for directory in (bin_dir, pkg_dir, cache_dir):
            directory.mkdir(parents=True, exist_ok=True)
        env = env_with_local_tools(go_dir=go_dir)
        assert env is not None
        env["GOBIN"] = str(bin_dir)

        for tool in GO_BUILD_TOOLS:
            run(["go", "install", tool], env=env)

    _post_setup_notes(
        venv=venv if python else None,
        go_dir=go_dir if go else None,
    )


def _post_setup_notes(venv: Path | None, go_dir: Path | None) -> None:
    flags: list[str] = []
    if venv:
        flags.append(f"--venv {venv}")
    if go_dir:
        flags.append(f"--go {go_dir}")

    if flags:
        log(
            "Pass "
            + " ".join(flags)
            + " to `s3m-protobuild env` and `s3m-protobuild build` to use these tools."
        )

    if not shutil.which("protoc"):
        log("Warning: `protoc` is not on PATH. It is required to build.")
        for hint in system_install_guidance("protoc").splitlines():
            log(f"  {hint}")


_PROTOC_URL = "https://github.com/protocolbuffers/protobuf/releases"
_GO_URL = "https://go.dev/dl/"

_INSTALL_HINTS: dict[str, dict[str, str]] = {
    "protoc": {
        "darwin": (
            f"Install with Homebrew: `brew install protobuf`\n"
            f"Or download a release manually: {_PROTOC_URL}"
        ),
        "debian": (
            f"Install with apt: `sudo apt-get install protobuf-compiler`\n"
            f"Or download a release manually: {_PROTOC_URL}"
        ),
        "rhel": (
            f"Install with dnf: `sudo dnf install protobuf-compiler`\n"
            f"Or download a release manually: {_PROTOC_URL}"
        ),
        "fallback": (
            f"Install protoc via your OS package manager.\n"
            f"Or download a release manually: {_PROTOC_URL}"
        ),
    },
    "go": {
        "darwin": (
            f"Install with Homebrew: `brew install go`\n"
            f"Or download a release manually: {_GO_URL}"
        ),
        "debian": (
            f"Install with apt: `sudo apt-get install golang-go`\n"
            f"Or download a release manually: {_GO_URL}"
        ),
        "rhel": (
            f"Install with dnf: `sudo dnf install golang`\n"
            f"Or download a release manually: {_GO_URL}"
        ),
        "fallback": (
            f"Install Go via your OS package manager.\n"
            f"Or download a release manually: {_GO_URL}"
        ),
    },
}


def system_install_guidance(command: str) -> str:
    table = _INSTALL_HINTS[command]
    return table.get(_platform_family(), table["fallback"])


def _platform_family() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return _linux_distro_family()
    return "fallback"


def _linux_distro_family() -> str:
    try:
        fields = platform.freedesktop_os_release()
    except OSError:
        return "fallback"

    id_like = f"{fields.get('ID', '')} {fields.get('ID_LIKE', '')}".lower()
    if any(token in id_like for token in ("debian", "ubuntu")):
        return "debian"
    if any(
        token in id_like for token in ("rhel", "fedora", "centos", "rocky", "almalinux")
    ):
        return "rhel"
    return "fallback"
