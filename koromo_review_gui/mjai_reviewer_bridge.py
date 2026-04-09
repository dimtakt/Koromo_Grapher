from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .runtime_paths import gui_root, local_review_runner_path, mortal_root, reviewer_root as default_reviewer_root
from .subprocess_utils import hidden_subprocess_kwargs


@dataclass(slots=True)
class MjaiReviewerRunResult:
    input_path: Path
    output_path: Path
    rating: float
    total_reviewed: int
    total_matches: int
    review_json: dict


class MjaiReviewerBridge:
    def __init__(
        self,
        reviewer_root: str | Path | None = None,
        mortal_exe: str | Path | None = None,
        mortal_cfg: str | Path | None = None,
    ):
        root = Path(reviewer_root) if reviewer_root else default_reviewer_root()
        self.reviewer_root = root.resolve()
        self.reviewer_exe = self.reviewer_root / "target" / "release" / "mjai-reviewer.exe"
        self.mortal_exe = Path(mortal_exe) if mortal_exe else local_review_runner_path()
        self.mortal_cfg = Path(mortal_cfg) if mortal_cfg else gui_root() / "local_mortal_review_config.toml"

    def review_tenhou_game(
        self,
        tenhou_json_path: str | Path,
        player_id: int,
        output_path: str | Path | None = None,
        state_file: str | Path | None = None,
        ignore_tonpuu_for_mortal: bool = False,
    ) -> MjaiReviewerRunResult:
        input_path = Path(tenhou_json_path).resolve()
        out_path = Path(output_path).resolve() if output_path else input_path.with_suffix(".review.json")
        cfg_path = self._prepare_config(out_path, state_file)

        command = [
            str(self.reviewer_exe),
            "-e",
            "mortal",
            "-i",
            str(input_path),
            "-a",
            str(player_id),
            "--json",
            "--show-rating",
            "--no-open",
            "--mortal-exe",
            str(self.mortal_exe.resolve()),
            "--mortal-cfg",
            str(cfg_path.resolve()),
            "-o",
            str(out_path),
        ]
        env = dict(os.environ)
        env["MORTAL_CFG_PATH"] = str(cfg_path.resolve())
        if ignore_tonpuu_for_mortal:
            env["MORTAL_ALLOW_TONPUU"] = "1"
        proc = subprocess.run(
            command,
            cwd=self.reviewer_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            **hidden_subprocess_kwargs(),
        )
        if proc.returncode != 0:
            message = (proc.stderr or proc.stdout).strip()
            raise RuntimeError(f"mjai-reviewer failed:\n{message}")

        review_json = json.loads(out_path.read_text(encoding="utf-8"))
        review = review_json["review"]
        return MjaiReviewerRunResult(
            input_path=input_path,
            output_path=out_path,
            rating=float(review["rating"]) * 100.0,
            total_reviewed=int(review["total_reviewed"]),
            total_matches=int(review["total_matches"]),
            review_json=review_json,
        )

    def _prepare_config(self, output_path: Path, state_file: str | Path | None) -> Path:
        if not state_file:
            return self.mortal_cfg

        state_path = Path(state_file).resolve()
        grp_state = mortal_root() / "grp_bootstrap.pt"
        config_text = (
            "[control]\n"
            f"state_file = '{state_path.as_posix()}'\n\n"
            "[grp]\n"
            f"state_file = '{grp_state.resolve().as_posix()}'\n\n"
            "[grp.network]\n"
            "hidden_size = 64\n"
            "num_layers = 2\n"
        )
        cfg_path = output_path.with_suffix(".review.toml")
        cfg_path.write_text(config_text, encoding="utf-8")
        return cfg_path
