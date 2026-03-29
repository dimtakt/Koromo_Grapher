from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path

import ms.protocol_pb2 as pb
from google.protobuf.json_format import ParseDict
from tensoul.downloader import MajsoulPaipuDownloader


@dataclass(slots=True)
class TenhouExportResult:
    head_path: Path
    record_data_path: Path
    tenhou_json_path: Path


def export_tenhou6_from_saved_record(
    head_path: str | Path,
    record_data_path: str | Path,
    tenhou_json_path: str | Path | None = None,
) -> TenhouExportResult:
    head_path = Path(head_path)
    record_data_path = Path(record_data_path)
    tenhou_json_path = Path(tenhou_json_path) if tenhou_json_path else record_data_path.with_suffix(".tenhou6.json")

    head_dict = json.loads(head_path.read_text(encoding="utf-8"))
    head = pb.RecordGame()
    ParseDict(head_dict, head)

    record = pb.ResGameRecord()
    record.head.CopyFrom(head)
    record.data = record_data_path.read_bytes()

    downloader = MajsoulPaipuDownloader()
    tenhou_data = downloader._handle_game_record(record)
    tenhou_json_path.write_text(json.dumps(tenhou_data, ensure_ascii=False), encoding="utf-8")

    return TenhouExportResult(
        head_path=head_path,
        record_data_path=record_data_path,
        tenhou_json_path=tenhou_json_path,
    )


def export_tenhou6_gz_from_saved_record(
    head_path: str | Path,
    record_data_path: str | Path,
    tenhou_json_gz_path: str | Path | None = None,
) -> Path:
    head_path = Path(head_path)
    record_data_path = Path(record_data_path)
    tenhou_json_gz_path = Path(tenhou_json_gz_path) if tenhou_json_gz_path else record_data_path.with_suffix(".tenhou6.json.gz")

    result = export_tenhou6_from_saved_record(head_path, record_data_path)
    with gzip.open(tenhou_json_gz_path, "wt", encoding="utf-8") as f:
        f.write(result.tenhou_json_path.read_text(encoding="utf-8"))
    return tenhou_json_gz_path
