from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import DecisionRecord
from .mortal_adapter import ExternalMortalPackage

ACTION_SPACE = 46
REVIEW_TAU = 0.1
PASS_INDEX = 45
CHI_LOW = 38
CHI_MID = 39
CHI_HIGH = 40
PON = 41
KAN = 42
HORA = 43
RYUKYOKU = 44
RIICHI = 37

TILE_ORDER = [
    "1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
    "1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p",
    "1s", "2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s",
    "E", "S", "W", "N", "P", "F", "C",
    "5mr", "5pr", "5sr",
]
TILE_TO_INDEX = {tile: idx for idx, tile in enumerate(TILE_ORDER)}


@dataclass(slots=True)
class SeatResolution:
    seat: int
    nickname: str | None


def _deaka(tile: str) -> str:
    return {"5mr": "5m", "5pr": "5p", "5sr": "5s"}.get(tile, tile)


def _tile_index(tile: str) -> int:
    if tile not in TILE_TO_INDEX:
        raise ValueError(f"unknown tile string: {tile}")
    return TILE_TO_INDEX[tile]


def _chi_kind(event: dict[str, Any]) -> int:
    pai = _deaka(event["pai"])
    consumed = [_deaka(tile) for tile in event["consumed"]]

    suit = pai[-1]
    num = int(pai[:-1])
    low = sorted([f"{num + 1}{suit}", f"{num + 2}{suit}"])
    mid = sorted([f"{num - 1}{suit}", f"{num + 1}{suit}"])
    high = sorted([f"{num - 2}{suit}", f"{num - 1}{suit}"])
    normalized = sorted(consumed)

    if normalized == low:
        return CHI_LOW
    if normalized == mid:
        return CHI_MID
    if normalized == high:
        return CHI_HIGH
    raise ValueError(f"cannot classify chi event: {event}")


def event_to_action_index(event: dict[str, Any]) -> int | None:
    kind = event["type"]
    if kind == "dahai":
        return _tile_index(event["pai"])
    if kind == "reach":
        return RIICHI
    if kind == "chi":
        return _chi_kind(event)
    if kind == "pon":
        return PON
    if kind in {"ankan", "kakan", "daiminkan"}:
        return KAN
    if kind == "hora":
        return HORA
    if kind == "ryukyoku":
        return RYUKYOKU
    if kind == "none":
        return PASS_INDEX
    return None


def format_action(event: dict[str, Any]) -> str:
    kind = event["type"]
    if kind == "dahai":
        return f"dahai:{event['pai']}"
    if kind == "reach":
        return "reach"
    if kind == "chi":
        return f"chi:{event['pai']}:{','.join(event['consumed'])}"
    if kind == "pon":
        return f"pon:{event['pai']}"
    if kind in {"ankan", "kakan", "daiminkan"}:
        base = event.get("pai") or ",".join(event.get("consumed", []))
        return f"{kind}:{base}"
    if kind == "hora":
        return "hora"
    if kind == "ryukyoku":
        return "ryukyoku"
    if kind == "none":
        return "pass"
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def _extract_meta(response: dict[str, Any]) -> dict[str, Any] | None:
    meta = response.get("meta")
    if not isinstance(meta, dict):
        return None
    if not meta.get("q_values"):
        return None
    return meta


def _softmax(values: list[float], tau: float) -> list[float]:
    if not values:
        return []
    if tau <= 0:
        raise ValueError("tau must be positive")
    scaled = [v / tau for v in values]
    pivot = max(scaled)
    exps = [math.exp(v - pivot) for v in scaled]
    total = sum(exps)
    if total <= 0:
        return [0.0 for _ in values]
    return [v / total for v in exps]


def _decode_q_values(meta: dict[str, Any], tau: float) -> tuple[list[int], dict[int, float], dict[int, float]]:
    compact_q_values = [float(v) for v in meta.get("q_values", [])]
    mask_bits = int(meta.get("mask_bits", 0))
    legal_indices = [idx for idx in range(ACTION_SPACE) if mask_bits & (1 << idx)]
    if len(legal_indices) != len(compact_q_values):
        raise ValueError("mask_bits and q_values length mismatch")

    q_by_index = dict(zip(legal_indices, compact_q_values, strict=True))
    prob_by_index = dict(zip(legal_indices, _softmax(compact_q_values, tau), strict=True))
    return legal_indices, q_by_index, prob_by_index


def _mask_flags(mask_bits: int) -> dict[str, bool]:
    return {
        "can_pon_or_daiminkan": bool((mask_bits >> PON) & 1 or (mask_bits >> KAN) & 1),
        "can_agari": bool((mask_bits >> HORA) & 1),
        "can_ryukyoku": bool((mask_bits >> RYUKYOKU) & 1),
    }


def _events_equal_ignore_aka(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    if expected["type"] != actual["type"]:
        return False

    kind = expected["type"]
    if kind in {"reach", "hora", "ryukyoku", "none"}:
        return True
    if kind in {"dahai", "kakan"}:
        return _deaka(expected["pai"]) == _deaka(actual["pai"])
    if kind in {"chi", "pon", "daiminkan"}:
        lhs = sorted(_deaka(tile) for tile in expected.get("consumed", []))
        rhs = sorted(_deaka(tile) for tile in actual.get("consumed", []))
        return lhs == rhs
    if kind == "ankan":
        lhs = sorted(_deaka(tile) for tile in expected.get("consumed", []))
        rhs = sorted(_deaka(tile) for tile in actual.get("consumed", []))
        return lhs == rhs
    return expected == actual


def _next_actual_action(
    events: list[dict[str, Any]],
    current_index: int,
    seat: int,
    *,
    can_pon_or_daiminkan: bool,
    can_agari: bool,
    can_ryukyoku: bool,
) -> dict[str, Any] | None:
    if current_index + 1 >= len(events):
        return None

    ev = events[current_index + 1]
    kind = ev["type"]

    if kind in {"dora", "reach_accepted"}:
        return _next_actual_action(
            events,
            current_index + 1,
            seat,
            can_pon_or_daiminkan=can_pon_or_daiminkan,
            can_agari=can_agari,
            can_ryukyoku=can_ryukyoku,
        )

    if kind == "tsumo":
        return {"type": "none"}

    if kind == "hora":
        for candidate in events[current_index + 1 : current_index + 4]:
            if candidate["type"] == "hora" and candidate.get("actor") == seat:
                return candidate
        return {"type": "none"} if can_agari else None

    if kind == "ryukyoku":
        return ev if can_ryukyoku else None

    actor = ev.get("actor")
    if actor is not None and actor != seat:
        if can_agari or can_pon_or_daiminkan:
            return {"type": "none"}
        return None

    if event_to_action_index(ev) is not None:
        return ev
    return None


class MortalReviewRunner:
    def __init__(self, model_dir: str | Path, tau: float = REVIEW_TAU):
        self.package = ExternalMortalPackage(model_dir)
        self.tau = tau

    def resolve_seat_from_head(self, head_path: str | Path, account_id: int) -> SeatResolution:
        head = json.loads(Path(head_path).read_text(encoding="utf-8"))
        accounts = head.get("accounts", [])
        used_seats = {
            int(account["seat"])
            for account in accounts
            if account.get("seat") is not None
        }
        remaining_seats = [seat for seat in range(4) if seat not in used_seats]

        for account in accounts:
            if int(account.get("account_id", -1)) == account_id:
                seat_value = account.get("seat")
                if seat_value is None:
                    if len(remaining_seats) == 1:
                        seat_value = remaining_seats[0]
                    else:
                        raise ValueError(f"seat missing for account_id {account_id} in {head_path}")
                return SeatResolution(
                    seat=int(seat_value),
                    nickname=account.get("nickname"),
                )
        raise ValueError(f"account_id {account_id} not found in {head_path}")

    def analyze_mjai_game(self, mjai_path: str | Path, seat: int, game_id: str) -> list[DecisionRecord]:
        events = [
            json.loads(line)
            for line in Path(mjai_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(events) < 2:
            return []

        bot = self.package.build_bot(seat)
        decisions: list[DecisionRecord] = []

        for idx, event in enumerate(events[:-1]):
            response_raw = bot.react(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
            if not response_raw:
                continue

            response = json.loads(response_raw)
            meta = _extract_meta(response)
            if meta is None:
                continue

            predicted_idx = event_to_action_index(response)
            if predicted_idx is None:
                continue

            mask_bits = int(meta.get("mask_bits", 0))
            flags = _mask_flags(mask_bits)
            actual_event = _next_actual_action(
                events,
                idx,
                seat,
                can_pon_or_daiminkan=flags["can_pon_or_daiminkan"],
                can_agari=flags["can_agari"],
                can_ryukyoku=flags["can_ryukyoku"],
            )
            if actual_event is None:
                continue

            actual_idx = event_to_action_index(actual_event)
            if actual_idx is None:
                continue

            legal_indices, q_by_index, prob_by_index = _decode_q_values(meta, self.tau)
            if actual_idx not in q_by_index:
                continue

            ranked = sorted(legal_indices, key=lambda action_idx: q_by_index[action_idx], reverse=True)
            top3 = set(ranked[:3])
            q_values = [q_by_index[action_idx] for action_idx in legal_indices]
            min_q = min(q_values)
            max_q = max(q_values)
            if max_q > min_q:
                normalized_rating_value = (q_by_index[actual_idx] - min_q) / (max_q - min_q)
            else:
                normalized_rating_value = 1.0
            decisions.append(
                DecisionRecord(
                    game_id=game_id,
                    turn_index=len(decisions),
                    actual_action=format_action(actual_event),
                    model_action=format_action(response),
                    model_probability=prob_by_index.get(actual_idx, 0.0),
                    normalized_rating_value=normalized_rating_value,
                    top1_match=_events_equal_ignore_aka(response, actual_event),
                    top3_match=(actual_idx in top3),
                )
            )

        return decisions
