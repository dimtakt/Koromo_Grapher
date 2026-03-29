from __future__ import annotations

import json
from pathlib import Path

from .metrics import summarize_decisions
from .models import AggregateStats, DecisionRecord


def _round_label(kyoku_index: int, honba: int) -> str:
    winds = ["동", "남", "서", "북"]
    wind = winds[(kyoku_index // 4) % len(winds)]
    kyoku_num = (kyoku_index % 4) + 1
    base = f"{wind}{kyoku_num}국"
    if honba:
        return f"{base} {honba}본장"
    return base


def _normalized_rating(entry: dict) -> float:
    details = entry.get("details") or []
    actual_index = entry.get("actual_index")
    if actual_index is None or not details or actual_index >= len(details):
        return 0.0

    q_values = [float(detail["q_value"]) for detail in details]
    actual_q = q_values[int(actual_index)]
    q_min = min(q_values)
    q_max = max(q_values)
    if q_max == q_min:
        return 1.0
    return (actual_q - q_min) / (q_max - q_min)


def parse_reviewer_json(path: str | Path, game_id: str) -> list[DecisionRecord]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows: list[DecisionRecord] = []

    turn_index = 0
    for kyoku in payload["review"]["kyokus"]:
        round_label = _round_label(int(kyoku.get("kyoku", 0)), int(kyoku.get("honba", 0)))
        for entry in kyoku["entries"]:
            details = entry.get("details") or []
            actual_index = entry.get("actual_index")
            if actual_index is None or actual_index >= len(details):
                continue

            actual_detail = details[int(actual_index)]
            junme = int(entry.get("junme", 0))
            rows.append(
                DecisionRecord(
                    game_id=game_id,
                    turn_index=turn_index,
                    round_label=round_label,
                    junme=junme,
                    actual_action=json.dumps(entry.get("actual"), ensure_ascii=False, separators=(",", ":")),
                    model_action=json.dumps(details[0].get("action"), ensure_ascii=False, separators=(",", ":")),
                    model_probability=float(actual_detail.get("prob", 0.0)),
                    normalized_rating_value=_normalized_rating(entry),
                    top1_match=bool(entry.get("is_equal", False)),
                    top3_match=int(actual_index) < min(3, len(details)),
                )
            )
            turn_index += 1

    return rows


def summarize_reviewer_json(path: str | Path, game_id: str) -> AggregateStats:
    return summarize_decisions(parse_reviewer_json(path, game_id))
