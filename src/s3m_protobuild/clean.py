from __future__ import annotations

import shutil
from pathlib import Path

from .errors import BuildError
from .output import BUILD_INFO_NAME


def clean(output_root: Path) -> None:
    output_root = output_root.resolve()
    if not output_root.exists():
        return
    if not (output_root / BUILD_INFO_NAME).exists():
        raise BuildError(f"Refusing to clean unmarked output directory: {output_root}")

    shutil.rmtree(output_root)
