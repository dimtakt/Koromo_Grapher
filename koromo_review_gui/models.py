from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass(slots=True)
class PlayerQuery:
    koromo_url: str
    recent_games: Optional[int] = None
    player_id: Optional[int] = None
    mode_id: Optional[int] = None
    majsoul_access_token: Optional[str] = None
    cn_login_email: Optional[str] = None
    cn_login_password: Optional[str] = None


@dataclass(slots=True)
class GameRecord:
    game_id: str
    uuid: Optional[str] = None
    mode_id: Optional[int] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    player_name: Optional[str] = None
    player_score: Optional[int] = None
    player_grading_score: Optional[int] = None
    placement: Optional[int] = None
    source_url: Optional[str] = None


@dataclass(slots=True)
class DecisionRecord:
    game_id: str
    turn_index: int
    round_label: str
    junme: int
    actual_action: str
    model_action: str
    model_probability: float
    normalized_rating_value: float
    top1_match: bool
    top3_match: bool


@dataclass(slots=True)
class DecisionPreview:
    turn_index: int
    round_label: str
    junme: int
    actual_action: str
    model_action: str
    model_probability: float
    normalized_rating_value: float
    top1_match: bool
    top3_match: bool


@dataclass(slots=True)
class GameAnalysis:
    game_id: str
    decision_count: int
    rating: float
    top1_agreement: float
    top3_agreement: float
    bad_move_rate_5: float
    bad_move_rate_10: float
    bad_move_count_5: int = 0
    bad_move_count_10: int = 0
    started_at: Optional[datetime] = None
    notes: str = ""
    worst_decisions: list[DecisionPreview] = field(default_factory=list)


@dataclass(slots=True)
class AggregateStats:
    total_games: int = 0
    total_decisions: int = 0
    rating: float = 0.0
    top1_agreement: float = 0.0
    top3_agreement: float = 0.0
    bad_move_rate_5: float = 0.0
    bad_move_rate_10: float = 0.0
    games: list[GameAnalysis] = field(default_factory=list)


@dataclass(slots=True)
class EngineAnalysisResult:
    engine_name: str
    model_dir: str
    stats: AggregateStats


@dataclass(slots=True)
class AnalysisSession:
    saved_at: str
    query: dict[str, Any]
    reports: list[EngineAnalysisResult]


def game_analysis_to_dict(row: GameAnalysis) -> dict[str, Any]:
    payload = asdict(row)
    payload["started_at"] = row.started_at.isoformat() if row.started_at else None
    return payload


def aggregate_stats_to_dict(stats: AggregateStats) -> dict[str, Any]:
    return {
        "total_games": stats.total_games,
        "total_decisions": stats.total_decisions,
        "rating": stats.rating,
        "top1_agreement": stats.top1_agreement,
        "top3_agreement": stats.top3_agreement,
        "bad_move_rate_5": stats.bad_move_rate_5,
        "bad_move_rate_10": stats.bad_move_rate_10,
        "games": [game_analysis_to_dict(game) for game in stats.games],
    }


def aggregate_stats_from_dict(payload: dict[str, Any]) -> AggregateStats:
    games = []
    for row in payload.get("games", []):
        started_at = row.get("started_at")
        games.append(
            GameAnalysis(
                game_id=row["game_id"],
                decision_count=int(row["decision_count"]),
                rating=float(row["rating"]),
                top1_agreement=float(row["top1_agreement"]),
                top3_agreement=float(row["top3_agreement"]),
                bad_move_rate_5=float(row["bad_move_rate_5"]),
                bad_move_rate_10=float(row["bad_move_rate_10"]),
                bad_move_count_5=int(row.get("bad_move_count_5", 0)),
                bad_move_count_10=int(row.get("bad_move_count_10", 0)),
                started_at=datetime.fromisoformat(started_at) if started_at else None,
                notes=row.get("notes", ""),
                worst_decisions=[
                    DecisionPreview(
                        turn_index=int(item["turn_index"]),
                        round_label=str(item.get("round_label", "")),
                        junme=int(item.get("junme", 0)),
                        actual_action=str(item["actual_action"]),
                        model_action=str(item["model_action"]),
                        model_probability=float(item["model_probability"]),
                        normalized_rating_value=float(item["normalized_rating_value"]),
                        top1_match=bool(item["top1_match"]),
                        top3_match=bool(item["top3_match"]),
                    )
                    for item in row.get("worst_decisions", [])
                ],
            )
        )

    return AggregateStats(
        total_games=int(payload.get("total_games", 0)),
        total_decisions=int(payload.get("total_decisions", 0)),
        rating=float(payload.get("rating", 0.0)),
        top1_agreement=float(payload.get("top1_agreement", 0.0)),
        top3_agreement=float(payload.get("top3_agreement", 0.0)),
        bad_move_rate_5=float(payload.get("bad_move_rate_5", 0.0)),
        bad_move_rate_10=float(payload.get("bad_move_rate_10", 0.0)),
        games=games,
    )


def engine_analysis_to_dict(row: EngineAnalysisResult) -> dict[str, Any]:
    return {
        "engine_name": row.engine_name,
        "model_dir": row.model_dir,
        "stats": aggregate_stats_to_dict(row.stats),
    }


def engine_analysis_from_dict(payload: dict[str, Any]) -> EngineAnalysisResult:
    return EngineAnalysisResult(
        engine_name=str(payload.get("engine_name", "unknown")),
        model_dir=str(payload.get("model_dir", "")),
        stats=aggregate_stats_from_dict(payload.get("stats", {})),
    )
