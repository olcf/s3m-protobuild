from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import BuildError


@dataclass(frozen=True)
class ModuleConfig:
    name: str
    version: str
    go_package: str
    py_package: str | None
    pyb_package: str | None
    flatten_namespaces: tuple[str, ...]

    @property
    def py_dist_name(self) -> str:
        if self.py_package:
            return self.py_package.replace("_", "-")
        return f"{self.name}-grpcio"

    @property
    def py_module_name(self) -> str:
        return self.py_package or self.py_dist_name.replace("-", "_")

    @property
    def pyb_dist_name(self) -> str:
        if self.pyb_package:
            return self.pyb_package.replace("_", "-")
        return f"{self.name}-betterproto"

    @property
    def pyb_module_name(self) -> str:
        return self.pyb_package or self.pyb_dist_name.replace("-", "_")

    @classmethod
    def load(cls, root: Path) -> "ModuleConfig":
        module_file = root / "MODULE"
        if not module_file.exists():
            raise BuildError(f"No MODULE file found at {module_file}")

        raw: dict[str, str] = {}
        for raw_line in module_file.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            raw[key.strip()] = value.strip()

        required = ("MODULE", "VERSION", "GO_PACKAGE")
        missing = [key for key in required if not raw.get(key)]
        if missing:
            raise BuildError(f"MODULE is missing required key(s): {', '.join(missing)}")

        version = raw["VERSION"]
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:rc\d+)?", version):
            raise BuildError(
                f"MODULE VERSION must match x.y.z or x.y.zrcN: {module_file}"
            )

        name = _kebab_name(raw["MODULE"])
        py_package = _optional_python_package_name(
            raw.get("PY_PACKAGE"), "PY_PACKAGE"
        )
        pyb_package = _optional_python_package_name(
            raw.get("PYB_PACKAGE"), "PYB_PACKAGE"
        )
        flatten = tuple(
            item.strip()
            for item in raw.get("FLATTEN_NAMESPACES", "").split(",")
            if item.strip()
        )

        return cls(
            name=name,
            version=version,
            go_package=raw["GO_PACKAGE"],
            py_package=py_package,
            pyb_package=pyb_package,
            flatten_namespaces=flatten,
        )


def _optional_python_package_name(value: str | None, key: str) -> str | None:
    if not value:
        return None
    if not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise BuildError(
            f"MODULE {key} must be a valid Python import package name "
            f"(lowercase letters, digits, underscores, starting with a letter): "
            f"{value!r}"
        )
    return value


def _kebab_name(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", value):
        raise BuildError(
            f"MODULE must be a lowercase kebab-case name "
            f"(letters, digits, single dashes): {value!r}"
        )
    return value
