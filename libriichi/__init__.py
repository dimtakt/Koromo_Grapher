from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path


def _candidate_paths() -> list[Path]:
    root = Path(__file__).resolve().parent.parent
    return [
        root / "target" / "release" / "riichi.dll",
        root / "target" / "release" / "deps" / "riichi.dll",
        root / "target" / "debug" / "riichi.dll",
        root / "target" / "debug" / "deps" / "riichi.dll",
    ]


def _load_extension() -> None:
    for path in _candidate_paths():
        if not path.exists():
            continue
        loader = importlib.machinery.ExtensionFileLoader(__name__, str(path))
        spec = importlib.util.spec_from_file_location(__name__, path, loader=loader)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[__name__] = module
        spec.loader.exec_module(module)
        globals().update(module.__dict__)
        return
    raise ImportError(
        "could not find built libriichi extension; expected target/release/riichi.dll"
    )


_load_extension()
