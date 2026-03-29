from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .models import AnalysisSession, EngineAnalysisResult, engine_analysis_from_dict, engine_analysis_to_dict


class AnalysisSessionStore:
    def save(self, path: str | Path, query: dict, reports: list[EngineAnalysisResult]) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": datetime.now(UTC).isoformat(),
            "query": query,
            "reports": [engine_analysis_to_dict(report) for report in reports],
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def load(self, path: str | Path) -> AnalysisSession:
        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        reports_payload = payload.get("reports")
        if reports_payload is None and "stats" in payload:
            reports_payload = [
                {
                    "engine_name": "legacy",
                    "model_dir": str(payload.get("query", {}).get("model_dir", "")),
                    "stats": payload["stats"],
                }
            ]
        return AnalysisSession(
            saved_at=payload["saved_at"],
            query=payload.get("query", {}),
            reports=[engine_analysis_from_dict(item) for item in reports_payload or []],
        )
