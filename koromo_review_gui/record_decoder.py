from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .runtime_paths import gui_root, node_executable_path
from .subprocess_utils import hidden_subprocess_kwargs


@dataclass(slots=True)
class DecodedRecordResult:
    record_data_path: Path
    decoded_json_path: Path


class MajsoulRecordDecoder:
    def __init__(self, script_path: str | Path | None = None):
        self.script_path = Path(script_path) if script_path else self._default_script_path()

    @staticmethod
    def _default_script_path() -> Path:
        bundled = gui_root() / "bundled" / "decode_majsoul_record.bundle.js"
        if bundled.exists():
            return bundled
        return gui_root() / "decode_majsoul_record.js"

    def decode(self, record_data_path: str | Path, decoded_json_path: str | Path | None = None) -> DecodedRecordResult:
        record_data_path = Path(record_data_path)
        decoded_json_path = Path(decoded_json_path) if decoded_json_path else record_data_path.with_suffix(".decoded.json")

        proc = subprocess.run(
            [str(node_executable_path()), str(self.script_path), str(record_data_path), str(decoded_json_path)],
            capture_output=True,
            text=True,
            check=False,
            **hidden_subprocess_kwargs(),
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "패보 디코드 실패\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}"
            )

        return DecodedRecordResult(
            record_data_path=record_data_path,
            decoded_json_path=decoded_json_path,
        )
