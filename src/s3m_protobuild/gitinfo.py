from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitInfo:
    commit: str
    commit_time: str
    dirty: bool
    untracked: bool


def collect_git_info(root: Path) -> GitInfo:
    commit = _git(root, "rev-parse", "HEAD") or "unknown"
    commit_time = _git(root, "show", "-s", "--format=%ci", "HEAD") or "unknown"
    dirty = False
    untracked = False
    for line in (_git(root, "status", "--porcelain") or "").splitlines():
        if line.startswith("??"):
            untracked = True
        else:
            dirty = True

    return GitInfo(
        commit=commit, commit_time=commit_time, dirty=dirty, untracked=untracked
    )


def _git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None

    if completed.returncode != 0:
        return None

    return completed.stdout.strip()
