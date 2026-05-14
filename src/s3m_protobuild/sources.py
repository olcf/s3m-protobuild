from __future__ import annotations

import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generator
from urllib.parse import urlparse, urlunparse

from .config import ModuleConfig
from .errors import BuildError
from .model import Source
from .run import require_commands, run

REMOTE_PREFIX = "git+"


@dataclass(frozen=True)
class SourceRequest:
    location: str


def parse_source_arg(raw: str) -> SourceRequest:
    if "=" in raw:
        raise BuildError(
            "--source takes a path or git+URL, not name=path; "
            "qualify selectors with the source MODULE value when needed"
        )
    location = raw.strip()
    if not location:
        raise BuildError("Source location is empty")
    return SourceRequest(location=location)


@contextmanager
def resolved_sources(
    requests: list[SourceRequest],
) -> Generator[list[Source], None, None]:
    if not requests:
        requests = [SourceRequest(location=".")]

    with tempfile.TemporaryDirectory(prefix="s3m-protobuild-sources-") as tmp:
        tmp_root = Path(tmp)
        sources: list[Source] = []
        names: set[str] = set()

        for index, request in enumerate(requests):
            source = _resolve_one(request, tmp_root / f"src-{index}")
            if source.name in names:
                raise BuildError(f"Duplicate source MODULE: {source.name}")
            names.add(source.name)
            sources.append(source)
        yield sources


def _resolve_one(request: SourceRequest, clone_dest: Path) -> Source:
    if request.location.startswith(REMOTE_PREFIX):
        root = clone_remote(request.location, clone_dest)
    else:
        root = Path(request.location).expanduser().resolve()

    validate_source_root(root)
    config = ModuleConfig.load(root)
    return Source(name=config.name, root=root, config=config)


def validate_source_root(root: Path) -> None:
    if not root.exists():
        raise BuildError(f"Source root does not exist: {root}")
    if not (root / "MODULE").exists():
        raise BuildError(f"Source root has no MODULE file: {root}")
    if not (root / "proto").is_dir():
        raise BuildError(f"Source root has no proto/ directory: {root}")


def split_remote_ref(location: str) -> tuple[str, str | None]:
    spec = location.removeprefix(REMOTE_PREFIX)
    if not spec:
        raise BuildError(f"Remote source is missing a URL: {location}")
    if "://" not in spec:
        raise BuildError(
            f"Remote source must use a git+<scheme>://... URL (e.g. "
            f"git+https://host/path or git+ssh://user@host/path): {location}"
        )

    parsed = urlparse(spec)
    if "@" not in parsed.path:
        return spec, None

    path_part, ref = parsed.path.split("@", 1)
    if not ref:
        raise BuildError(f"Remote source must look like git+URL@REF: {location}")

    url = urlunparse(parsed._replace(path=path_part))
    return url, ref


def clone_remote(location: str, dest: Path) -> Path:
    require_commands(("git",))
    url, ref = split_remote_ref(location)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if ref:
        try:
            run(["git", "clone", "--depth", "1", "--branch", ref, url, str(dest)])
            return dest
        except BuildError:
            pass

    run(["git", "clone", url, str(dest)])

    if ref:
        run(["git", "checkout", ref], cwd=dest)
    return dest
