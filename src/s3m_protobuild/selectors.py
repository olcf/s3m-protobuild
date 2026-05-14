from __future__ import annotations

from pathlib import Path

from .errors import BuildError
from .model import TARGETS, Selector


def parse_selector(raw: str, source_names: set[str]) -> Selector:
    if raw.count(":") != 1:
        raise BuildError(
            f"Selector must have exactly one ':' separating package and target: {raw}"
        )
    left, target = raw.split(":", 1)
    left = left.strip().strip("/")
    target = target.strip()
    if not left:
        raise BuildError(f"Selector is missing a package path: {raw}")
    if target not in TARGETS:
        raise BuildError(
            f"Unknown target {target!r} in selector {raw!r}; expected one of {sorted(TARGETS)}"
        )

    source_name: str | None = None
    package_text = left
    parts = left.split("/")
    if len(parts) >= 2 and parts[0] in source_names:
        source_name = parts[0]
        package_text = "/".join(parts[1:])

    package_path = Path(package_text)
    if package_path.is_absolute() or ".." in package_path.parts:
        raise BuildError(f"Invalid package path in selector: {raw}")
    if len(package_path.parts) > 2:
        raise BuildError(
            f"Package selectors support package or package/version paths: {raw}"
        )
    return Selector(
        raw=raw, source_name=source_name, package_path=package_path, target=target
    )


def dedupe_selectors(selectors: list[Selector]) -> list[Selector]:
    seen: set[tuple[str | None, str, str]] = set()
    result: list[Selector] = []

    for selector in selectors:
        key = (selector.source_name, selector.package_text, selector.target)
        if key in seen:
            continue
        seen.add(key)
        result.append(selector)
    return result
