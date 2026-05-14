from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import ModuleConfig

TARGETS = frozenset({"go", "py", "pyb", "oas"})


@dataclass(frozen=True)
class Source:
    name: str
    root: Path
    config: ModuleConfig


@dataclass(frozen=True)
class Selector:
    raw: str
    source_name: str | None
    package_path: Path
    target: str

    @property
    def package_text(self) -> str:
        return self.package_path.as_posix()


@dataclass(frozen=True)
class ResolvedPackage:
    source: Source
    selector: str
    logical_dir: Path
    source_dir: Path
    staged_dir: Path | None = None

    @property
    def identity(self) -> tuple[str, Path]:
        return (self.source.name, self.logical_dir)

    @property
    def logical_proto_files(self) -> list[Path]:
        base = self.staged_dir or self.source_dir
        return sorted(base.glob("*.proto"))


@dataclass(frozen=True)
class ArtifactKey:
    source_name: str
    target: str

    def text(self) -> str:
        return f"{self.source_name}:{self.target}"


@dataclass(frozen=True)
class DescriptorOptions:
    relative_path: Path | None = None
    output_root: Path | None = None
    include_imports: bool = False
    include_source_info: bool = False


@dataclass
class Artifact:
    key: ArtifactKey
    source: Source
    output_root: Path
    packages: list[ResolvedPackage] = field(default_factory=list)


def proto_paths(packages: list[ResolvedPackage]) -> list[str]:
    return [str(path) for package in packages for path in package.logical_proto_files]
