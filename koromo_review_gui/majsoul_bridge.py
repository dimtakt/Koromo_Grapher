from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .runtime_paths import gui_root, node_executable_path, repo_root
from .subprocess_utils import hidden_subprocess_kwargs


@dataclass(slots=True)
class FetchResult:
    uuid: str
    output_dir: Path
    head_path: Path
    record_data_path: Path
    has_data_url: bool
    client_version_string: str


class MajsoulNodeBridge:
    def __init__(
        self,
        script_path: str | Path | None = None,
        default_url_base: str = "https://mahjongsoul.game.yo-star.com/",
    ):
        self.script_path = Path(script_path) if script_path else self._default_script_path()
        self.default_url_base = default_url_base

    @staticmethod
    def _default_script_path() -> Path:
        bundled = gui_root() / "bundled" / "fetch_majsoul_record.bundle.js"
        if bundled.exists():
            return bundled
        return gui_root() / "fetch_majsoul_record.js"

    def fetch_game_record(
        self,
        access_token: str,
        oauth_type: str | int,
        uuid: str,
        output_dir: str | Path,
        url_base: str | None = None,
    ) -> FetchResult:
        cmd = [
            str(node_executable_path()),
            str(self.script_path),
            access_token,
            str(oauth_type),
            uuid,
            str(Path(output_dir)),
            url_base or self.default_url_base,
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            cwd=str(repo_root()),
            **hidden_subprocess_kwargs(),
        )
        if proc.returncode != 0:
            message = (proc.stderr or proc.stdout).strip()
            raise RuntimeError(f"Majsoul 패보 다운로드 실패: {message}")

        payload = json.loads(proc.stdout.strip())
        return FetchResult(
            uuid=payload["uuid"],
            output_dir=Path(payload["outputDir"]),
            head_path=Path(payload["headPath"]),
            record_data_path=Path(payload["recordDataPath"]),
            has_data_url=bool(payload["hasDataUrl"]),
            client_version_string=payload["clientVersionString"],
        )
