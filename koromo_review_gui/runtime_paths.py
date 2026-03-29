from __future__ import annotations

import sys
from pathlib import Path


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _has_repo_markers(base: Path) -> bool:
    if getattr(sys, "frozen", False):
        return (base / "_external").exists() and (base / "mortal").exists()
    return (base / "_external").exists() and (base / "mortal").exists() and (base / "koromo_review_gui").exists()


def repo_root() -> Path:
    base = app_base_dir()
    if _has_repo_markers(base):
        return base

    for parent in [base.parent, base.parent.parent, base.parent.parent.parent]:
        if parent and _has_repo_markers(parent):
            return parent

    return base


def external_dir() -> Path:
    return repo_root() / "_external"


def reviewer_root() -> Path:
    return external_dir() / "mjai-reviewer"


def mahjong_soul_api_root() -> Path:
    return external_dir() / "mahjong_soul_api"


def amae_koromo_scripts_root() -> Path:
    return external_dir() / "amae-koromo-scripts"


def mortal_root() -> Path:
    return repo_root() / "mortal"


def gui_root() -> Path:
    return repo_root() / "koromo_review_gui"


def local_review_runner_path() -> Path:
    if is_frozen():
        runner_dir = app_base_dir() / "run_local_mortal_review" / "run_local_mortal_review.exe"
        if runner_dir.exists():
            return runner_dir
        return app_base_dir() / "run_local_mortal_review.exe"
    return gui_root() / "run_local_mortal_review.cmd"


def node_executable_path() -> Path | str:
    bundled = repo_root() / "node.exe"
    if bundled.exists():
        return bundled
    return "node"
