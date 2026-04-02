from __future__ import annotations

import json
import re
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from typing import Callable

import requests

from .metrics import summarize_decisions
from .models import AggregateStats, DecisionRecord, GameRecord, PlayerQuery

KOROMO_API_BASE = "https://5-data.amae-koromo.com/api"
RIICHI_CITY_LOG_API = "https://rc.honk.li/api/log"
EARLIEST_TS = 1262304000  # 2010-01-01 UTC
FOUR_PLAYER_MODE_IDS = (8, 9, 11, 12, 15, 16)
ProgressCallback = Callable[[int, int, str], None]
MAJSOUL_LINK_ID_RE = re.compile(
    r"([a-z0-9]{6}-[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12})",
    re.IGNORECASE,
)
MAJSOUL_UUID_RE = re.compile(
    r"((?:\d{6}-)?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)
MAJSOUL_ACCOUNT_TOKEN_RE = re.compile(
    r"_a(\d+)(?:_2)?\b",
    re.IGNORECASE,
)
RIICHI_CITY_CODE_RE = re.compile(r"([a-z0-9]{20})(?:@([0-3]))?", re.IGNORECASE)


@dataclass(slots=True)
class PreparedSingleGame:
    source_kind: str
    source_value: str
    player_id: int
    game: GameRecord
    tenhou_json_path: Path


class SingleGameSourceService:
    def __init__(self, cache_dir: str | Path, session: requests.Session | None = None):
        self.cache_dir = Path(cache_dir)
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "MortalKoromoReviewer/0.1")

    def describe_source(self, raw_input: str) -> str:
        text = raw_input.strip()
        if not text:
            return "-"
        if self._extract_majsoul_game_uuid(text) is not None:
            return "Majsoul 패보 링크"
        city_match = RIICHI_CITY_CODE_RE.search(text)
        if city_match:
            return "마작일번가 코드"
        return "지원되지 않는 입력"

    def prepare(
        self,
        raw_input: str,
        fallback_player_id: int | None,
        query: PlayerQuery,
        progress_callback: ProgressCallback | None = None,
    ) -> PreparedSingleGame:
        from .majsoul_to_tenhou import export_tenhou6_from_saved_record

        source_text = raw_input.strip()
        if not source_text:
            raise ValueError("단판 분석용 패보 링크 또는 코드를 입력해 주세요.")

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        game_uuid = self._extract_majsoul_game_uuid(source_text)
        if game_uuid is not None:
            encoded_account_id = self._extract_majsoul_encoded_account_id(source_text)
            if progress_callback:
                progress_callback(0, 3, f"Majsoul 패보 다운로드 준비 중... {game_uuid}")
            paifu_service = MajsoulPaifuService(self.cache_dir)
            game = GameRecord(
                game_id=game_uuid,
                uuid=game_uuid,
                source_url=raw_input,
            )
            fetch_result = paifu_service.download_game(query, game)
            if progress_callback:
                progress_callback(1, 3, f"tenhou 로그로 변환 중... {game_uuid}")
            tenhou_result = export_tenhou6_from_saved_record(fetch_result.head_path, fetch_result.record_data_path)
            player_id = fallback_player_id if fallback_player_id is not None else 0
            player_name = None
            if fallback_player_id is None and encoded_account_id is not None:
                resolved = self._resolve_majsoul_player_from_head(fetch_result.head_path, encoded_account_id)
                if resolved is not None:
                    player_id, player_name = resolved
            if progress_callback:
                progress_callback(2, 3, f"분석 준비 완료: {game_uuid}")
            return PreparedSingleGame(
                source_kind="majsoul",
                source_value=game_uuid,
                player_id=player_id,
                game=replace(game, player_name=player_name or game.player_name),
                tenhou_json_path=Path(tenhou_result.tenhou_json_path),
            )

        city_match = RIICHI_CITY_CODE_RE.search(source_text)
        if city_match:
            city_code = city_match.group(1)
            if fallback_player_id is not None:
                player_id = fallback_player_id
            elif city_match.group(2) is not None:
                player_id = int(city_match.group(2))
            else:
                player_id = 0
            tenhou_json_path = self.cache_dir / f"{city_code}.tenhou6.json"
            if tenhou_json_path.exists():
                payload = json.loads(tenhou_json_path.read_text(encoding="utf-8"))
            else:
                if progress_callback:
                    progress_callback(0, 3, f"마작일번가 패보 변환 중... {city_code}")
                response = self.session.post(RIICHI_CITY_LOG_API, data={"log_id": city_code}, timeout=60)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or "log" not in payload:
                    raise ValueError("마작일번가 변환 응답 형식이 올바르지 않습니다.")
                ref = str(payload.get("ref") or city_code)
                tenhou_json_path = self.cache_dir / f"{ref}.tenhou6.json"
                tenhou_json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            ref = str(payload.get("ref") or city_code)
            player_name = None
            if isinstance(payload.get("name"), list) and 0 <= player_id < len(payload["name"]):
                player_name = str(payload["name"][player_id])
            if progress_callback:
                progress_callback(2, 3, f"분석 준비 완료: {ref}")
            return PreparedSingleGame(
                source_kind="riichicity",
                source_value=ref,
                player_id=player_id,
                game=GameRecord(
                    game_id=ref,
                    uuid=ref,
                    player_name=player_name,
                    source_url=raw_input,
                ),
                tenhou_json_path=tenhou_json_path,
            )

        raise ValueError("지원하는 입력 형식이 아닙니다. Majsoul 패보 링크 또는 마작일번가 코드만 사용할 수 있습니다.")

    @staticmethod
    def _decode_majsoul_account_id(encoded_account_id: int) -> int:
        return (((encoded_account_id - 1358437) ^ 86216345) - 1117113) // 7

    @staticmethod
    def _decode_majsoul_paipu_uuid(uuid: str) -> str:
        chars: list[str] = []
        for index, char in enumerate(uuid):
            if "0" <= char <= "9":
                value = ord(char) - ord("0")
            elif "a" <= char <= "z":
                value = ord(char) - ord("a") + 10
            else:
                chars.append(char)
                continue
            value = (value + 55 - index) % 36
            if value < 10:
                chars.append(chr(value + ord("0")))
            else:
                chars.append(chr(value + ord("a") - 10))
        return "".join(chars)

    def _extract_majsoul_game_uuid(self, source_text: str) -> str | None:
        match = MAJSOUL_LINK_ID_RE.search(source_text)
        if not match:
            return None
        raw_uuid = match.group(1).lower()
        if MAJSOUL_UUID_RE.fullmatch(raw_uuid):
            return raw_uuid
        return self._decode_majsoul_paipu_uuid(raw_uuid)

    def _extract_majsoul_encoded_account_id(self, source_text: str) -> int | None:
        match = MAJSOUL_ACCOUNT_TOKEN_RE.search(source_text)
        if not match:
            return None
        try:
            return self._decode_majsoul_account_id(int(match.group(1)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _resolve_majsoul_player_from_head(head_path: str | Path, account_id: int) -> tuple[int, str | None] | None:
        head = json.loads(Path(head_path).read_text(encoding="utf-8"))
        accounts = head.get("accounts", [])
        used_seats = {
            int(account["seat"])
            for account in accounts
            if account.get("seat") is not None
        }
        remaining_seats = [seat for seat in range(4) if seat not in used_seats]

        for account in accounts:
            if int(account.get("account_id", -1)) != account_id:
                continue
            seat_value = account.get("seat")
            if seat_value is None:
                if len(remaining_seats) != 1:
                    return None
                seat_value = remaining_seats[0]
            return int(seat_value), account.get("nickname")
        return None


class KoromoService:
    """Koromo 플레이어 링크를 실제 대국 목록으로 바꾸는 수집기."""

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "MortalKoromoReviewer/0.1")

    def parse_query(self, query: PlayerQuery) -> PlayerQuery:
        match = re.search(r"/player/(\d+)/([^/?#]+)", query.koromo_url)
        if not match:
            raise ValueError("Koromo 플레이어 링크에서 계정 정보를 찾지 못했습니다.")

        player_id = int(match.group(1))
        return replace(query, player_id=player_id, mode_id=None)

    def fetch_games(self, query: PlayerQuery) -> list[GameRecord]:
        parsed = self.parse_query(query)
        if parsed.player_id is None:
                    progress_callback(index - 1, total, f"[{index}/{total}] ?? ???? ? | {game.game_id}")

        if parsed.recent_games:
            rows = self._fetch_recent(parsed.player_id, parsed.recent_games)
        else:
            rows = self._fetch_all(parsed.player_id)

        return [self._to_game_record(parsed, row) for row in rows]

    def _fetch_recent(self, player_id: int, limit: int) -> list[dict]:
        collected: list[dict] = []
        seen_ids: set[str] = set()

        for start_ts, end_ts in reversed(self._iter_month_windows()):
            rows = self._request_records_all_modes(player_id, start_ts, end_ts, 500)
            rows.sort(key=lambda row: row.get("startTime", 0), reverse=True)

            for row in rows:
                row_id = row.get("_id") or row.get("uuid")
                if not row_id or row_id in seen_ids:
                    continue
                seen_ids.add(row_id)
                collected.append(row)
                if len(collected) >= limit:
                    return collected[:limit]

        collected.sort(key=lambda row: row.get("startTime", 0), reverse=True)
        return collected[:limit]

    def _fetch_all(self, player_id: int) -> list[dict]:
        all_rows: list[dict] = []
        seen_ids: set[str] = set()

        for start_ts, end_ts in self._iter_month_windows():
            rows = self._request_records_all_modes(player_id, start_ts, end_ts, 500)
            for row in rows:
                row_id = row.get("_id") or row.get("uuid")
                if not row_id or row_id in seen_ids:
                    continue
                seen_ids.add(row_id)
                all_rows.append(row)

        all_rows.sort(key=lambda row: row.get("startTime", 0), reverse=True)
        return all_rows

    def _iter_month_windows(self) -> list[tuple[int, int]]:
        now = datetime.now(UTC)
        year = now.year
        month = now.month
        windows: list[tuple[int, int]] = []

        while year > 2009:
            start = datetime(year, month, 1, tzinfo=UTC)
            end = datetime(year + 1, 1, 1, tzinfo=UTC) if month == 12 else datetime(year, month + 1, 1, tzinfo=UTC)
            windows.append((int(start.timestamp()), int(end.timestamp())))
            month -= 1
            if month == 0:
                month = 12
                year -= 1

        windows.reverse()
        return windows

    def _request_records(self, player_id: int, mode_id: int, start_ts: int, end_ts: int, limit: int) -> list[dict]:
        url = f"{KOROMO_API_BASE}/v2/pl4/player_records/{player_id}/{start_ts}/{end_ts}"
        response = self.session.get(url, params={"limit": limit, "mode": mode_id}, timeout=30)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
                    progress_callback(index - 1, total, f"[{index}/{total}] ?? ???? ? | {game.game_id}")
        return data

    def _request_records_all_modes(self, player_id: int, start_ts: int, end_ts: int, limit: int) -> list[dict]:
        merged: list[dict] = []
        for mode_id in FOUR_PLAYER_MODE_IDS:
            try:
                merged.extend(self._request_records(player_id, mode_id, start_ts, end_ts, limit))
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status == 400:
                    continue
                raise
        return merged

    def _to_game_record(self, query: PlayerQuery, row: dict) -> GameRecord:
        players = row.get("players") or []
        player = next((item for item in players if item.get("accountId") == query.player_id), None)
        placement = None
        if player and players:
            sorted_players = sorted(players, key=lambda item: item.get("score", -999999), reverse=True)
            for index, item in enumerate(sorted_players, start=1):
                if item.get("accountId") == query.player_id:
                    placement = index
                    break

        return GameRecord(
            game_id=str(row.get("_id") or row.get("uuid") or "unknown"),
            uuid=row.get("uuid"),
            mode_id=row.get("modeId"),
            started_at=datetime.fromtimestamp(row["startTime"], tz=UTC) if row.get("startTime") else None,
            ended_at=datetime.fromtimestamp(row["endTime"], tz=UTC) if row.get("endTime") else None,
            player_name=player.get("nickname") if player else None,
            player_score=player.get("score") if player else None,
            player_grading_score=player.get("gradingScore") if player else None,
            placement=placement,
            source_url=query.koromo_url,
        )

    @staticmethod
    def _now_ts() -> int:
        return int(datetime.now(UTC).timestamp())


class AnalyzerService:
    """실제 대국을 로컬 reviewer 기준으로 분석한다."""

    def __init__(self, model_dir: str | None = None):
        self.model_dir = model_dir

    def analyze_games(self, games: list[GameRecord]) -> AggregateStats:
        rng = Random(7)
        decisions: list[DecisionRecord] = []
        for game in games:
            turn_count = rng.randint(12, 24)
            for turn in range(turn_count):
                probability = rng.uniform(0.01, 0.95)
                normalized_rating = rng.uniform(0.2, 1.0)
                decisions.append(
                    DecisionRecord(
                        game_id=game.game_id,
                        turn_index=turn,
                        round_label="샘플",
                        junme=turn + 1,
                        actual_action=f"actual_{turn % 5}",
                        model_action=f"model_{turn % 7}",
                        model_probability=probability,
                        normalized_rating_value=normalized_rating,
                        top1_match=probability >= 0.45,
                        top3_match=probability >= 0.20,
                    )
                )
        stats = summarize_decisions(decisions)
        self._attach_metadata(stats, games)
        return stats

    def analyze_downloaded_games(
        self,
        query: PlayerQuery,
        games: list[GameRecord],
        paifu_service: "MajsoulPaifuService",
        progress_callback: ProgressCallback | None = None,
    ) -> AggregateStats:
        from .majsoul_to_tenhou import export_tenhou6_from_saved_record
        from .mjai_reviewer_bridge import MjaiReviewerBridge
        from .review_json_parser import parse_reviewer_json
        from .review_runner import MortalReviewRunner

        if not self.model_dir:
            raise ValueError("모델 폴더가 필요합니다.")
        if query.player_id is None:
            raise ValueError("Koromo URL에서 player_id를 읽지 못했습니다.")

        reviewer = MortalReviewRunner(self.model_dir)
        reviewer_bridge = MjaiReviewerBridge()
        all_decisions: list[DecisionRecord] = []
        total = len(games)

        if progress_callback:
            progress_callback(0, max(total, 1), "\u0043\u004e \ub85c\uadf8\uc778 \uc911...")

        with paifu_service.batch_context(query) as batch_client:
            for index, game in enumerate(games, start=1):
                if progress_callback:
                    progress_callback(index - 1, total, f"[{index}/{total}] \ud328\ubcf4 \ub2e4\uc6b4\ub85c\ub4dc \uc911 | {game.game_id}")
                fetch_result = paifu_service.download_game(query, game, batch_client=batch_client)
                head_path = Path(fetch_result.head_path)
                record_data_path = Path(fetch_result.record_data_path)

                if progress_callback:
                    progress_callback(index - 1, total, f"[{index}/{total}] tenhou \ubcc0\ud658 \uc911 | {game.game_id}")
                tenhou_result = export_tenhou6_from_saved_record(head_path, record_data_path)

                seat = reviewer.resolve_seat_from_head(head_path, query.player_id).seat
                state_file = Path(self.model_dir) / "mortal.pth"
                review_output_path = Path(tenhou_result.tenhou_json_path).with_name(
                    f"{Path(tenhou_result.tenhou_json_path).stem}.{Path(self.model_dir).name}.review.json"
                )

                if progress_callback:
                    progress_callback(index - 1, total, f"[{index}/{total}] reviewer \ubd84\uc11d \uc911 | {game.game_id}")
                result = reviewer_bridge.review_tenhou_game(
                    tenhou_result.tenhou_json_path,
                    seat,
                    review_output_path,
                    state_file=state_file,
                )
                all_decisions.extend(parse_reviewer_json(result.output_path, game.game_id))

                if progress_callback:
                    progress_callback(index, total, f"[{index}/{total}] \uc644\ub8cc | {game.game_id}")

        stats = summarize_decisions(all_decisions)
        self._attach_metadata(stats, games)
        return stats

    def analyze_single_prepared_game(
        self,
        prepared_game: PreparedSingleGame,
        progress_callback: ProgressCallback | None = None,
    ) -> AggregateStats:
        from .mjai_reviewer_bridge import MjaiReviewerBridge
        from .review_json_parser import parse_reviewer_json

        if not self.model_dir:
            raise ValueError("모델 폴더가 필요합니다.")

        reviewer_bridge = MjaiReviewerBridge()
        state_file = Path(self.model_dir) / "mortal.pth"
        output_path = Path(prepared_game.tenhou_json_path).with_name(
            f"{Path(prepared_game.tenhou_json_path).stem}.{Path(self.model_dir).name}.review.json"
        )

        if progress_callback:
            progress_callback(0, 1, f"reviewer 분석 중... {prepared_game.game.game_id}")

        result = reviewer_bridge.review_tenhou_game(
            prepared_game.tenhou_json_path,
            prepared_game.player_id,
            output_path,
            state_file=state_file,
        )
        stats = summarize_decisions(parse_reviewer_json(result.output_path, prepared_game.game.game_id))
        self._attach_metadata(stats, [prepared_game.game])
        return stats

    @staticmethod
    def _attach_metadata(stats: AggregateStats, games: list[GameRecord]) -> None:
        metadata = {game.game_id: game for game in games}
        for row in stats.games:
            game = metadata.get(row.game_id)
            if not game:
                continue
            row.uuid = game.uuid
            row.started_at = game.started_at
            notes = []
            if game.placement is not None:
                notes.append(f"{game.placement}위")
            if game.player_score is not None:
                notes.append(f"점수 {game.player_score}")
            row.notes = " / ".join(notes)


class MajsoulPaifuService:
    """실제 패보 본문을 내려받고 중간 캐시에 저장한다."""

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.bridge = None
        self.decoder = None

    def batch_context(self, query: PlayerQuery):
        if query.cn_login_email and query.cn_login_password:
            from .majsoul_cn_bridge import CnSessionClientSync

            class _CnBatchContext:
                def __enter__(self_nonlocal):
                    self_nonlocal.client = CnSessionClientSync(query.cn_login_email or "", query.cn_login_password or "")
                    return self_nonlocal.client

                def __exit__(self_nonlocal, exc_type, exc, tb):
                    self_nonlocal.client.close()
                    return False

            return _CnBatchContext()
        return nullcontext(None)

    def ensure_ready(self, query: PlayerQuery) -> None:
        has_token = bool(query.majsoul_access_token)
        has_cn_login = bool(query.cn_login_email and query.cn_login_password)
        if not has_token and not has_cn_login:
            raise ValueError(
                "실제 패보 본문 다운로드에는 작혼 access token 또는 CN 이메일/비밀번호가 필요합니다. "
                "지금은 Koromo 대국 목록까지만 조회 가능한 상태입니다."
            )

    def prepare_cache(self) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir

    @staticmethod
    def _is_valid_cached_game(head_path: Path, record_data_path: Path) -> bool:
        try:
            if not head_path.exists() or not record_data_path.exists():
                return False
            if record_data_path.stat().st_size < 32:
                return False
            payload = json.loads(head_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return False
            accounts = payload.get("accounts")
            if not isinstance(accounts, list) or len(accounts) != 4:
                return False
            return True
        except Exception:
            return False

    def download_game(self, query: PlayerQuery, game: GameRecord, oauth_type: int | str = 0, batch_client=None):
        from .majsoul_bridge import FetchResult, MajsoulNodeBridge
        from .majsoul_cn_bridge import CnFetchResult, fetch_game_record_sync

        self.ensure_ready(query)
        self.prepare_cache()
        if not game.uuid:
            raise ValueError("대국 UUID가 없어 패보를 받을 수 없습니다.")

        cached_head = self.cache_dir / f"{game.uuid}.head.json"
        cached_record = self.cache_dir / f"{game.uuid}.recordData"
        if self._is_valid_cached_game(cached_head, cached_record):
            if query.cn_login_email and query.cn_login_password:
                return CnFetchResult(
                    game_uuid=game.uuid,
                    head_path=cached_head,
                    record_data_path=cached_record,
                    account_id=0,
                    endpoint="cache",
                    version="cache",
                )
            return FetchResult(
                uuid=game.uuid,
                output_dir=self.cache_dir,
                head_path=cached_head,
                record_data_path=cached_record,
                has_data_url=False,
                client_version_string="cache",
            )
        elif cached_head.exists() or cached_record.exists():
            cached_head.unlink(missing_ok=True)
            cached_record.unlink(missing_ok=True)

        if query.cn_login_email and query.cn_login_password:
            if batch_client is not None:
                result = batch_client.fetch_game_record(game.uuid, self.cache_dir)
                if not self._is_valid_cached_game(Path(result.head_path), Path(result.record_data_path)):
                    raise ValueError("Majsoul 패보 다운로드 결과가 비정상입니다. 패보 ID 또는 인증 정보를 다시 확인해 주세요.")
                return result
            result = fetch_game_record_sync(
                email=query.cn_login_email,
                password=query.cn_login_password,
                game_uuid=game.uuid,
                output_dir=self.cache_dir,
            )
            if not self._is_valid_cached_game(Path(result.head_path), Path(result.record_data_path)):
                raise ValueError("Majsoul 패보 다운로드 결과가 비정상입니다. 패보 ID 또는 인증 정보를 다시 확인해 주세요.")
            return result

        if not query.majsoul_access_token:
            raise ValueError(
                "Majsoul 패보 캐시가 손상되어 다시 받아야 합니다. "
                "CN 이메일/비밀번호 또는 access token을 입력한 뒤 다시 시도해 주세요."
            )

        result = self.bridge.fetch_game_record(
            access_token=query.majsoul_access_token or "",
            oauth_type=oauth_type,
            uuid=game.uuid,
            output_dir=self.cache_dir,
        )
        if not self._is_valid_cached_game(Path(result.head_path), Path(result.record_data_path)):
            raise ValueError("Majsoul 패보 다운로드 결과가 비정상입니다. 패보 ID 또는 인증 정보를 다시 확인해 주세요.")
        return result

    def explain_requirement(self) -> str:
        return (
            "Koromo 공개 API는 대국 목록과 요약까지만 주고, 실제 패보 본문은 주지 않습니다. "
            "실제 분석을 하려면 작혼 token 또는 CN 로그인 정보로 fetchGameRecord 경로를 붙여야 합니다."
        )

    def decode_downloaded_game(
        self,
        record_data_path: str | Path,
        decoded_json_path: str | Path | None = None,
    ):
        from .record_decoder import MajsoulRecordDecoder

        if self.decoder is None:
            self.decoder = MajsoulRecordDecoder()
        return self.decoder.decode(record_data_path, decoded_json_path)
