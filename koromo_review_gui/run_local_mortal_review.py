from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch

if __package__ in (None, ""):
    REPO_ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(REPO_ROOT))
    from koromo_review_gui.runtime_paths import mortal_root, repo_root
else:
    from koromo_review_gui.runtime_paths import mortal_root, repo_root

REPO_ROOT = repo_root()
MORTAL_ROOT = mortal_root()
sys.path.insert(0, str(MORTAL_ROOT))
sys.path.insert(0, str(REPO_ROOT))
os.environ["MORTAL_CFG"] = os.environ.get("MORTAL_CFG_PATH", str(REPO_ROOT / "koromo_review_gui" / "local_mortal_review_config.toml"))

import prelude  # noqa: F401
from common import filtered_trimmed_lines
from config import config
from engine import MortalEngine
from libriichi.dataset import Grp
from libriichi.mjai import Bot
from model import Brain, DQN, GRP


def compat_torch_load(path: str | Path):
    return torch.load(path, weights_only=False, map_location=torch.device("cpu"))


def resolve_config_path() -> str:
    cfg_path = os.environ.get("MORTAL_CFG_PATH")
    if cfg_path:
        return cfg_path
    return str(REPO_ROOT / "koromo_review_gui" / "local_mortal_review_config.toml")


def main():
    try:
        player_id = int(sys.argv[-1])
        assert player_id in range(4)
    except Exception:
        print("Usage: python run_local_mortal_review.py <ID>", file=sys.stderr)
        sys.exit(1)

    review_mode = os.environ.get("MORTAL_REVIEW_MODE", "0") == "1"
    force_device = os.environ.get("MORTAL_DEVICE", "").strip().lower()
    if force_device in {"cuda", "gpu"} and torch.cuda.is_available():
        device = torch.device("cuda")
    elif force_device == "cpu":
        device = torch.device("cpu")
    else:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    state = compat_torch_load(config["control"]["state_file"])
    cfg = state["config"]
    version = cfg["control"].get("version", 1)
    num_blocks = cfg["resnet"]["num_blocks"]
    conv_channels = cfg["resnet"]["conv_channels"]
    if "tag" in state:
        tag = state["tag"]
    elif "timestamp" in state:
        time = datetime.fromtimestamp(state["timestamp"], tz=timezone.utc).strftime("%y%m%d%H")
        tag = f"mortal{version}-b{num_blocks}c{conv_channels}-t{time}"
    else:
        state_name = Path(config["control"]["state_file"]).stem
        tag = f"mortal{version}-b{num_blocks}c{conv_channels}-{state_name}"

    mortal = Brain(version=version, num_blocks=num_blocks, conv_channels=conv_channels).to(device).eval()
    dqn = DQN(version=version).to(device).eval()
    mortal.load_state_dict(state["mortal"])
    dqn.load_state_dict(state["current_dqn"])

    engine = MortalEngine(
        mortal,
        dqn,
        version=version,
        is_oracle=False,
        device=device,
        enable_amp=(device.type == "cuda"),
        enable_quick_eval=not review_mode,
        enable_rule_based_agari_guard=True,
        name="mortal",
    )
    bot = Bot(engine, player_id)

    logs: list[str] = []
    for line in filtered_trimmed_lines(sys.stdin):
        if review_mode:
            logs.append(line)

        reaction = bot.react(line)
        if reaction:
            print(reaction, flush=True)
        elif review_mode:
            print('{"type":"none","meta":{"mask_bits":0}}', flush=True)

    if review_mode:
        grp = GRP(**config["grp"]["network"]).to(device)
        grp_state = compat_torch_load(config["grp"]["state_file"])
        grp.load_state_dict(grp_state["model"])

        ins = Grp.load_log("\n".join(logs))
        feature = ins.take_feature()
        seq = [torch.as_tensor(feature[: idx + 1], device=device) for idx in range(len(feature))]

        with torch.inference_mode():
            logits = grp(seq)
        matrix = grp.calc_matrix(logits)
        extra_data = {
            "model_tag": tag,
            "phi_matrix": matrix.tolist(),
        }
        print(json.dumps(extra_data), flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
