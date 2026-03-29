from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import ModuleType

import torch


@contextmanager
def pushd(path: Path):
    old_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


@dataclass(slots=True)
class ModelPackageProbe:
    model_dir: Path
    model_py: bool
    bot_py: bool
    weight_file: bool
    load_model_available: bool


class ExternalMortalPackage:
    def __init__(self, model_dir: str | Path):
        self.model_dir = Path(model_dir).resolve()

    def probe(self) -> ModelPackageProbe:
        module = self._import_model_module()
        return ModelPackageProbe(
            model_dir=self.model_dir,
            model_py=(self.model_dir / "model.py").exists(),
            bot_py=(self.model_dir / "bot.py").exists(),
            weight_file=(self.model_dir / "mortal.pth").exists(),
            load_model_available=hasattr(module, "load_model"),
        )

    def build_bot(self, seat: int = 0):
        module = self._import_model_module()
        with pushd(self.model_dir):
            with self._patched_torch_load():
                return module.load_model(seat)

    def _import_model_module(self):
        model_dir_str = str(self.model_dir)
        if model_dir_str not in sys.path:
            sys.path.insert(0, model_dir_str)
        if "model" in sys.modules:
            del sys.modules["model"]
        return import_module("model")

    @contextmanager
    def _patched_torch_load(self):
        original_load = torch.load

        def compat_load(*args, **kwargs):
            # Older Mortal checkpoints were saved assuming the pre-2.6 default.
            # When the caller does not specify, force the legacy behavior.
            kwargs.setdefault("weights_only", False)
            return original_load(*args, **kwargs)

        torch.load = compat_load
        try:
            yield
        finally:
            torch.load = original_load
