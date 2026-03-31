from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


def _round_label(kyoku_index: int, honba: int) -> str:
    winds = ["\ub3d9", "\ub0a8", "\uc11c", "\ubd81"]
    wind = winds[(kyoku_index // 4) % len(winds)]
    kyoku_num = (kyoku_index % 4) + 1
    base = f"{wind}{kyoku_num}\uad6d"
    if honba:
        return f"{base} {honba}\ubcf8\uc7a5"
    return base


def _tile_token(token: object | None) -> str:
    if token is None:
        return "-"
    text = str(token).strip()
    return text or "-"


def _call_source_label(actor: int | None, last_actor: object | None) -> str:
    relative = _relative_target(actor, last_actor)
    return {
        1: "\u2190\uc0c1\uac00",
        2: "\u2191\ub300\uba74",
        3: "\u2192\ud558\uac00",
    }.get(relative, "")


def _seat_label(kyoku_index: int, actor: int | None) -> str:
    if actor is None:
        return ""
    seat_winds = ["\ub3d9\uac00", "\ub0a8\uac00", "\uc11c\uac00", "\ubd81\uac00"]
    dealer = kyoku_index % 4
    return seat_winds[(actor - dealer) % 4]


def _format_action(action: dict | None) -> str:
    if not action:
        return "-"

    kind = str(action.get("type", "unknown"))
    pai = _tile_token(action.get("pai"))

    if kind == "dahai":
        suffix = " (쯔모기리)" if action.get("tsumogiri") else ""
        return f"\ud0c0\ud328 {pai}{suffix}"
    if kind == "chi":
        consumed = ", ".join(_tile_token(tile) for tile in (action.get("consumed") or []))
        return f"\uce58 {pai} [{consumed}]"
    if kind == "pon":
        consumed = ", ".join(_tile_token(tile) for tile in (action.get("consumed") or []))
        return f"\ud401 {pai} [{consumed}]"
    if kind == "daiminkan":
        consumed = ", ".join(_tile_token(tile) for tile in (action.get("consumed") or []))
        return f"\ub300\uba85\uae61 {pai} [{consumed}]"
    if kind == "ankan":
        consumed = ", ".join(_tile_token(tile) for tile in (action.get("consumed") or []))
        return f"\uae61 [{consumed}]"
    if kind == "kakan":
        consumed = ", ".join(_tile_token(tile) for tile in (action.get("consumed") or []))
        return f"\uae61 {pai} [{consumed}]"
    if kind == "reach":
        return "\ub9ac\uce58"
    if kind == "hora":
        return "\ud654\ub8cc"
    if kind == "ryukyoku":
        return "\uc720\uad6d"
    if kind == "none":
        return "\ud328\uc2a4"
    if action.get("target") is not None:
        return f"{kind} actor={action.get('actor')} target={action.get('target')}"
    if pai != "-":
        return f"{kind} {pai}"
    return kind


def _format_player_index(value: object | None, focus_actor: int | None) -> str:
    if value is None:
        return "-"
    text = str(value)
    if focus_actor is not None and text == str(focus_actor):
        return f"<b>{text}</b>"
    return text


def _format_deltas(deltas: list[object], focus_actor: int | None) -> str:
    if not deltas:
        return "[]"
    parts: list[str] = []
    for index, delta in enumerate(deltas):
        text = str(delta)
        if focus_actor is not None and index == focus_actor:
            text = f"<b>{text}</b>"
        parts.append(text)
    return "[" + ", ".join(parts) + "]"


def _format_scores(scores: list[object], focus_actor: int | None) -> str:
    if not scores:
        return "-"
    parts: list[str] = []
    for index, score in enumerate(scores):
        text = str(score)
        if focus_actor is not None and index == focus_actor:
            text = f"<b>{text}</b>"
        parts.append(text)
    return ", ".join(parts)


def _format_end_status(items: list[dict], focus_actor: int | None = None) -> str:
    parts: list[str] = []
    for item in items or []:
        kind = str(item.get("type", "unknown"))
        actor = item.get("actor")
        target = item.get("target")
        deltas = item.get("deltas") or []
        actor_text = _format_player_index(actor, focus_actor)
        target_text = _format_player_index(target, focus_actor)
        deltas_text = _format_deltas(deltas, focus_actor)
        if kind == "hora":
            parts.append(f"\ud654\ub8cc actor={actor_text} target={target_text} \uc810\uc218\ubcc0\ub3d9 {deltas_text}")
        elif kind == "ryukyoku":
            parts.append(f"\uc720\uad6d \uc810\uc218\ubcc0\ub3d9 {deltas_text}")
        else:
            parts.append(f"{kind} actor={actor_text} target={target_text} \uc810\uc218\ubcc0\ub3d9 {deltas_text}")
    return "<br>".join(parts) if parts else "-"


@dataclass(slots=True)
class ReviewCandidate:
    action_text: str
    probability: float
    q_value: float
    is_actual: bool


@dataclass(slots=True)
class ReviewFuuroGroup:
    label: str
    tiles: list[str] = field(default_factory=list)
    called_tile_index: int | None = None
    stacked_tile: str | None = None
    stacked_on_index: int | None = None


@dataclass(slots=True)
class ReviewEntryDetail:
    log_entry_index: int
    round_label: str
    actor: int | None
    last_actor: int | None
    actual_action_kind: str
    junme: int
    tile: str
    tiles_left: int
    shanten: int | None
    actual_action_text: str
    expected_action_text: str
    best_action_text: str
    actual_probability: float
    actual_q_value: float
    is_equal: bool
    flags: list[str] = field(default_factory=list)
    tehai_tiles: list[str] = field(default_factory=list)
    fuuro_groups: list[ReviewFuuroGroup] = field(default_factory=list)
    display_tehai_tiles: list[str] = field(default_factory=list)
    display_fuuro_groups: list[ReviewFuuroGroup] = field(default_factory=list)
    incoming_call_tile: str = "-"
    incoming_call_source: str = ""
    highlight_last_tile: bool = True
    candidates: list[ReviewCandidate] = field(default_factory=list)


@dataclass(slots=True)
class ReviewKyokuDetail:
    log_index: int
    round_label: str
    seat_label: str
    player_index: int | None
    score_text: str
    end_summary: str
    entries: list[ReviewEntryDetail] = field(default_factory=list)


@dataclass(slots=True)
class ReviewGameDetail:
    engine: str
    version: str
    rating: float
    total_reviewed: int
    total_matches: int
    temperature: float | None
    kyokus: list[ReviewKyokuDetail] = field(default_factory=list)


def _fuuro_label(kind: str) -> str:
    return {
        "chi": "\uce58",
        "pon": "\ud401",
        "daiminkan": "\ub300\uba85\uae61",
        "ankan": "\uae61",
        "kakan": "\uae61",
    }.get(kind, "\ud6c4\ub85c")


def _relative_target(actor: int | None, target: object | None) -> int | None:
    if actor is None or target is None:
        return None
    try:
        return (int(actor) - int(target)) % 4
    except (TypeError, ValueError):
        return None


def _build_fuuro_group(actor: int | None, group: dict) -> ReviewFuuroGroup:
    kind = str(group.get("type", "")).lower()
    consumed = [_tile_token(tile) for tile in (group.get("consumed") or [])]
    called_tile = _tile_token(group.get("taken") if group.get("taken") is not None else group.get("pai"))
    relative = _relative_target(actor, group.get("target"))

    tiles = list(consumed)
    called_tile_index: int | None = None

    if kind == "chi":
        tiles = [called_tile, *consumed]
        called_tile_index = 0
    elif kind == "pon":
        called_tile_index = {1: 0, 2: 1, 3: 2}.get(relative, len(consumed))
        tiles = list(consumed)
        tiles.insert(min(called_tile_index, len(tiles)), called_tile)
    elif kind == "daiminkan":
        called_tile_index = {1: 0, 2: 1, 3: 3}.get(relative, len(consumed))
        tiles = list(consumed)
        tiles.insert(min(called_tile_index, len(tiles)), called_tile)
    elif kind == "kakan":
        previous_relative = _relative_target(actor, group.get("previous_pon_target"))
        previous_called_tile = _tile_token(
            group.get("previous_pon_pai") if group.get("previous_pon_pai") is not None else group.get("pai")
        )
        called_tile_index = {1: 0, 2: 1, 3: 2}.get(previous_relative, len(consumed))
        tiles = list(consumed)
        tiles.insert(min(called_tile_index, len(tiles)), previous_called_tile)
        return ReviewFuuroGroup(
            label=_fuuro_label(kind),
            tiles=tiles,
            called_tile_index=called_tile_index,
            stacked_tile=called_tile,
            stacked_on_index=called_tile_index,
        )
    elif kind == "ankan":
        tiles = list(consumed)
        called_tile_index = None
    else:
        tiles = list(consumed)
        if called_tile != "-":
            tiles.append(called_tile)
            called_tile_index = len(tiles) - 1

    return ReviewFuuroGroup(
        label=_fuuro_label(kind),
        tiles=tiles,
        called_tile_index=called_tile_index,
    )


def parse_review_detail(path: str | Path) -> ReviewGameDetail:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    review = payload.get("review") or {}
    kyokus: list[ReviewKyokuDetail] = []

    for log_index, kyoku in enumerate(review.get("kyokus") or []):
        kyoku_index = int(kyoku.get("kyoku", 0))
        round_label = _round_label(kyoku_index, int(kyoku.get("honba", 0)))
        entries: list[ReviewEntryDetail] = []

        raw_entries = kyoku.get("entries") or []
        for entry_index, entry in enumerate(raw_entries):
            details = entry.get("details") or []
            actual_index = entry.get("actual_index")
            if actual_index is None or not details or int(actual_index) >= len(details):
                continue

            actual_index = int(actual_index)
            actual_detail = details[actual_index]

            actual_action = entry.get("actual") or {}
            expected_action = entry.get("expected") or {}
            actor = None
            if actual_action.get("actor") is not None:
                actor = int(actual_action.get("actor"))
            elif entry.get("last_actor") is not None:
                actor = int(entry.get("last_actor"))
            if actor is None:
                for detail in details:
                    detail_action = detail.get("action") or {}
                    if detail_action.get("actor") is not None:
                        actor = int(detail_action.get("actor"))
                        break

            flags: list[str] = []
            if entry.get("at_self_chi_pon"):
                flags.append("\uc790\uae30 \uce58/\ud401 \ubd84\uae30")
            if entry.get("at_self_riichi"):
                flags.append("\uc790\uae30 \ub9ac\uce58 \ubd84\uae30")
            if entry.get("at_opponent_kakan"):
                flags.append("\uc0c1\ub300 \uac00\uae61 \ubd84\uae30")
            if entry.get("at_furiten"):
                flags.append("\ud6c4\ub9ac\ud150")

            actual_kind = str(actual_action.get("type", "")).lower()
            representative_call_action = None
            for detail in details:
                detail_action = detail.get("action") or {}
                detail_kind = str(detail_action.get("type", "")).lower()
                if detail_kind in {"chi", "pon", "daiminkan"}:
                    representative_call_action = detail_action
                    break

            is_pass_call_decision = False
            if actual_kind == "none" and representative_call_action is not None:
                rep_actor = representative_call_action.get("actor")
                rep_target = representative_call_action.get("target")
                if rep_actor is not None:
                    actor = int(rep_actor)
                if actor is not None and rep_target is not None and int(rep_target) != actor:
                    is_pass_call_decision = True

            incoming_call_source_actor = None
            show_incoming_call = False
            if actual_kind in {"chi", "pon", "daiminkan"}:
                incoming_call_source_actor = actual_action.get("target", entry.get("last_actor"))
                show_incoming_call = True
            elif actual_kind == "hora":
                incoming_call_source_actor = actual_action.get("target")
                show_incoming_call = True
            elif is_pass_call_decision:
                incoming_call_source_actor = representative_call_action.get("target")
                show_incoming_call = True

            has_external_source = (
                actor is not None
                and incoming_call_source_actor is not None
                and int(incoming_call_source_actor) != actor
            )
            show_incoming_call = show_incoming_call and has_external_source

            candidates = [
                ReviewCandidate(
                    action_text=_format_action(detail.get("action")),
                    probability=float(detail.get("prob", 0.0)),
                    q_value=float(detail.get("q_value", 0.0)),
                    is_actual=index == actual_index,
                )
                for index, detail in enumerate(details)
            ]

            state = entry.get("state") or {}
            fuuro_groups: list[ReviewFuuroGroup] = []
            for group in state.get("fuuros") or []:
                fuuro_groups.append(_build_fuuro_group(actor, group))

            display_tehai_tiles = [_tile_token(tile) for tile in (state.get("tehai") or [])]
            display_fuuro_groups = list(fuuro_groups)

            entries.append(
                ReviewEntryDetail(
                    log_entry_index=entry_index,
                    round_label=round_label,
                    actor=actor,
                    last_actor=int(entry["last_actor"]) if entry.get("last_actor") is not None else None,
                    actual_action_kind=actual_kind,
                    junme=int(entry.get("junme", 0)),
                    tile=_tile_token(entry.get("tile")),
                    tiles_left=int(entry.get("tiles_left", 0)),
                    shanten=int(entry["shanten"]) if entry.get("shanten") is not None else None,
                    actual_action_text=_format_action(actual_action),
                    expected_action_text=_format_action(expected_action),
                    best_action_text=_format_action((details[0] or {}).get("action")),
                    actual_probability=float(actual_detail.get("prob", 0.0)),
                    actual_q_value=float(actual_detail.get("q_value", 0.0)),
                    is_equal=bool(entry.get("is_equal", False)),
                    flags=flags,
                    tehai_tiles=[_tile_token(tile) for tile in (state.get("tehai") or [])],
                    fuuro_groups=fuuro_groups,
                    display_tehai_tiles=display_tehai_tiles,
                    display_fuuro_groups=display_fuuro_groups,
                    incoming_call_tile=_tile_token(entry.get("tile")) if show_incoming_call else "-",
                    incoming_call_source=_call_source_label(actor, incoming_call_source_actor) if show_incoming_call else "",
                    highlight_last_tile=(actual_kind in {"dahai", "kakan", "ankan"} and not bool(entry.get("at_self_chi_pon"))),
                    candidates=candidates,
                )
            )

        player_index = next((entry.actor for entry in entries if entry.actor is not None), None)
        score_text = _format_scores(kyoku.get("relative_scores") or [], player_index)
        kyokus.append(
            ReviewKyokuDetail(
                log_index=log_index,
                round_label=round_label,
                seat_label=_seat_label(kyoku_index, player_index),
                player_index=player_index,
                score_text=score_text,
                end_summary=_format_end_status(kyoku.get("end_status") or [], focus_actor=player_index),
                entries=entries,
            )
        )

    return ReviewGameDetail(
        engine=str(payload.get("engine", "-")),
        version=str(payload.get("version", "-")),
        rating=float(review.get("rating", 0.0)) * 100.0,
        total_reviewed=int(review.get("total_reviewed", 0)),
        total_matches=int(review.get("total_matches", 0)),
        temperature=float(review["temperature"]) if review.get("temperature") is not None else None,
        kyokus=kyokus,
    )
