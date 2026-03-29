from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .runtime_paths import reviewer_root as default_reviewer_root
from .subprocess_utils import hidden_subprocess_kwargs


@dataclass(slots=True)
class MjaiConversionResult:
    input_path: Path
    mjai_path: Path


class TenhouToMjaiBridge:
    def __init__(self, reviewer_root: str | Path | None = None):
        root = Path(reviewer_root) if reviewer_root else default_reviewer_root()
        self.reviewer_root = root.resolve()
        self.exe_path = self.reviewer_root / "target" / "release" / "mjai-reviewer.exe"

    def convert(self, tenhou_json_path: str | Path, mjai_path: str | Path | None = None) -> MjaiConversionResult:
        input_path = Path(tenhou_json_path).resolve()
        output_path = Path(mjai_path).resolve() if mjai_path else input_path.with_suffix(".mjai.jsonl")

        if not self.exe_path.exists():
            raise FileNotFoundError(f"mjai-reviewer executable not found: {self.exe_path}")

        command = [
            str(self.exe_path),
            "-i",
            str(input_path),
            "--no-review",
            "--mjai-out",
            str(output_path),
        ]
        subprocess.run(
            command,
            cwd=self.reviewer_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            **hidden_subprocess_kwargs(),
        )

        return MjaiConversionResult(
            input_path=input_path,
            mjai_path=output_path,
        )
