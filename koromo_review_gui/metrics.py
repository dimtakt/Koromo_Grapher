from __future__ import annotations

from collections import defaultdict

from .models import AggregateStats, DecisionPreview, DecisionRecord, GameAnalysis


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def summarize_decisions(decisions: list[DecisionRecord]) -> AggregateStats:
    by_game: dict[str, list[DecisionRecord]] = defaultdict(list)
    for row in decisions:
        by_game[row.game_id].append(row)

    game_rows: list[GameAnalysis] = []
    total_decisions = 0
    rating_sum = 0.0
    top1_hits = 0
    top3_hits = 0
    bad_5 = 0
    bad_10 = 0

    for game_id, rows in sorted(by_game.items(), key=lambda item: item[0]):
        count = len(rows)
        total_decisions += count
        rating_avg = _safe_ratio(sum(row.normalized_rating_value for row in rows), count)
        top1_count = sum(1 for row in rows if row.top1_match)
        top3_count = sum(1 for row in rows if row.top3_match)
        bad_5_count = sum(1 for row in rows if row.model_probability < 0.05)
        bad_10_count = sum(1 for row in rows if row.model_probability < 0.10)
        worst_rows = sorted(
            rows,
            key=lambda row: (row.model_probability, row.turn_index),
        )[:10]

        rating_sum += sum(row.normalized_rating_value for row in rows)
        top1_hits += top1_count
        top3_hits += top3_count
        bad_5 += bad_5_count
        bad_10 += bad_10_count

        game_rows.append(
            GameAnalysis(
                game_id=game_id,
                decision_count=count,
                rating=100.0 * (rating_avg ** 2),
                top1_agreement=_safe_ratio(top1_count, count),
                top3_agreement=_safe_ratio(top3_count, count),
                bad_move_rate_5=_safe_ratio(bad_5_count, count),
                bad_move_rate_10=_safe_ratio(bad_10_count, count),
                bad_move_count_5=bad_5_count,
                bad_move_count_10=bad_10_count,
                worst_decisions=[
                    DecisionPreview(
                        turn_index=row.turn_index,
                        round_label=row.round_label,
                        junme=row.junme,
                        actual_action=row.actual_action,
                        model_action=row.model_action,
                        model_probability=row.model_probability,
                        normalized_rating_value=row.normalized_rating_value,
                        top1_match=row.top1_match,
                        top3_match=row.top3_match,
                    )
                    for row in worst_rows
                ],
            )
        )

    total_rating_avg = _safe_ratio(rating_sum, total_decisions)
    return AggregateStats(
        total_games=len(game_rows),
        total_decisions=total_decisions,
        rating=100.0 * (total_rating_avg ** 2),
        top1_agreement=_safe_ratio(top1_hits, total_decisions),
        top3_agreement=_safe_ratio(top3_hits, total_decisions),
        bad_move_rate_5=_safe_ratio(bad_5, total_decisions),
        bad_move_rate_10=_safe_ratio(bad_10, total_decisions),
        games=game_rows,
    )
