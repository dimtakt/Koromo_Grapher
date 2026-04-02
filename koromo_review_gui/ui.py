from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QObject, QSize, QThread, Qt, Signal, QUrl
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QSplitter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .local_settings import LocalSettingsStore
from .models import AnalysisSession, EngineAnalysisResult, GameAnalysis, PlayerQuery
from .review_detail_parser import ReviewFuuroGroup, ReviewGameDetail, ReviewKyokuDetail, parse_review_detail
from .runtime_paths import repo_root
from .services import AnalyzerService, KoromoService, MajsoulPaifuService, SingleGameSourceService
from .session_store import AnalysisSessionStore
from .tenhou_to_mjai_bridge import TenhouToMjaiBridge


def tile_font_family() -> str:
    candidates = [
        "Noto Sans Symbols 2",
        "Symbola",
        "Arial Unicode MS",
        "Noto Sans Symbols",
    ]
    families = set(QFontDatabase.families())
    for candidate in candidates:
        if candidate in families:
            return candidate
    return "Sans Serif"


def tile_to_unicode(tile: str) -> str:
    token = str(tile).strip()
    if not token:
        return "-"
    suited = {
        "m": ["\U0001F007", "\U0001F008", "\U0001F009", "\U0001F00A", "\U0001F00B", "\U0001F00C", "\U0001F00D", "\U0001F00E", "\U0001F00F"],
        "s": ["\U0001F010", "\U0001F011", "\U0001F012", "\U0001F013", "\U0001F014", "\U0001F015", "\U0001F016", "\U0001F017", "\U0001F018"],
        "p": ["\U0001F019", "\U0001F01A", "\U0001F01B", "\U0001F01C", "\U0001F01D", "\U0001F01E", "\U0001F01F", "\U0001F020", "\U0001F021"],
        "z": ["\U0001F000", "\U0001F001", "\U0001F002", "\U0001F003", "\U0001F006", "\U0001F005", "\U0001F004"],
    }
    honors = {
        "e": suited["z"][0],
        "s": suited["z"][1],
        "w": suited["z"][2],
        "n": suited["z"][3],
        "h": suited["z"][4],
        "f": suited["z"][5],
        "c": suited["z"][6],
        "p": suited["z"][4],
    }
    lower = token.lower()
    if len(lower) == 1 and lower in honors:
        return honors[lower]
    if len(lower) in {2, 3} and lower[0].isdigit() and lower[1] in {"m", "p", "s"}:
        if lower[0] == "0":
            return suited[lower[1]][4]
        index = int(lower[0]) - 1
        if 0 <= index < 9:
            return suited[lower[1]][index]
    return token


def is_red_five(tile: str) -> bool:
    lower = str(tile).lower().strip()
    return (len(lower) == 2 and lower[0] == "0" and lower[1] in {"m", "p", "s"}) or (
        len(lower) == 3 and lower[0] == "5" and lower[1] in {"m", "p", "s"} and lower[2] == "r"
    )


class TileGlyphStrip(QWidget):
    def __init__(
        self,
        tiles: list[str],
        called_index: int | None = None,
        stacked_tile: str | None = None,
        stacked_on_index: int | None = None,
        parent: QWidget | None = None,
        *,
        font_px: int = 28,
        color: str = "#1f2937",
        red_color: str = "#c53030",
        vertical_lift: int = 0,
    ):
        super().__init__(parent)
        self.tiles = list(tiles)
        self.called_index = called_index
        self.stacked_tile = stacked_tile
        self.stacked_on_index = stacked_on_index
        self.font_px = font_px
        self.color = QColor(color)
        self.red_color = QColor(red_color)
        self.vertical_lift = vertical_lift
        self.setFixedHeight(font_px + 14 + (font_px if stacked_tile else 0))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    @staticmethod
    def _trim_transparent(pixmap: QPixmap) -> QPixmap:
        image = pixmap.toImage()
        width = image.width()
        height = image.height()
        min_x = width
        min_y = height
        max_x = -1
        max_y = -1
        for y in range(height):
            for x in range(width):
                if QColor(image.pixelColor(x, y)).alpha() > 0:
                    if x < min_x:
                        min_x = x
                    if y < min_y:
                        min_y = y
                    if x > max_x:
                        max_x = x
                    if y > max_y:
                        max_y = y
        if max_x < min_x or max_y < min_y:
            return pixmap
        return pixmap.copy(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)

    def _glyph_pixmap(self, glyph: str, color: QColor, rotated: bool = False) -> QPixmap:
        font = QFont(tile_font_family())
        font.setPixelSize(self.font_px)
        source = QPixmap(max(1, self.font_px + 2), max(1, self.font_px + 4))
        source.fill(Qt.GlobalColor.transparent)
        painter = QPainter(source)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addText(0.0, 0.0, font, glyph)
        bounds = path.boundingRect()
        transform = QTransform()
        transform.translate(-bounds.left(), 1.0 - bounds.top())
        path = transform.map(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPath(path)
        painter.end()
        if rotated:
            rotation = QTransform()
            rotation.rotate(-90)
            source = source.transformed(rotation, Qt.TransformationMode.SmoothTransformation)
            return self._trim_transparent(source)
        return source

    def sizeHint(self) -> QSize:
        width = 2
        height = self.font_px + 14 + (self.font_px if self.stacked_tile else 0)
        for index, tile in enumerate(self.tiles):
            glyph = tile_to_unicode(tile)
            pixmap = self._glyph_pixmap(glyph, self.red_color if is_red_five(tile) else self.color, rotated=(index == self.called_index))
            width += pixmap.width()
            if index != len(self.tiles) - 1:
                width += 0
        width += 2
        return QSize(width, height)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont(tile_font_family())
        font.setPixelSize(self.font_px)
        painter.setFont(font)
        x = 0
        tile_positions: list[tuple[int, int, int, int]] = []
        for index, tile in enumerate(self.tiles):
            glyph = tile_to_unicode(tile)
            color = self.red_color if is_red_five(tile) else self.color
            if index == self.called_index:
                rotated = self._glyph_pixmap(glyph, color, rotated=True)
                y = self.height() - rotated.height() - self.vertical_lift
                painter.drawPixmap(x, y, rotated)
                tile_positions.append((x, y, rotated.width(), rotated.height()))
                x += rotated.width()
            else:
                pixmap = self._glyph_pixmap(glyph, color, rotated=False)
                y = self.height() - pixmap.height() - self.vertical_lift
                painter.drawPixmap(x, y, pixmap)
                tile_positions.append((x, y, pixmap.width(), pixmap.height()))
                x += max(1, pixmap.width() - 5)
        if self.stacked_tile is not None and self.stacked_on_index is not None and 0 <= self.stacked_on_index < len(tile_positions):
            stack_color = self.red_color if is_red_five(self.stacked_tile) else self.color
            stack_pixmap = self._glyph_pixmap(tile_to_unicode(self.stacked_tile), stack_color, rotated=True)
            base_x, base_y, base_w, _ = tile_positions[self.stacked_on_index]
            stack_x = base_x + max(0, (base_w - stack_pixmap.width()) // 2)
            stack_y = max(0, base_y - stack_pixmap.height() - 16)
            painter.drawPixmap(stack_x, stack_y, stack_pixmap)
        painter.end()


class HandCompositeStrip(QWidget):
    def __init__(
        self,
        tehai_tiles: list[str],
        fuuro_groups: list[ReviewFuuroGroup],
        parent: QWidget | None = None,
        *,
        font_px: int = 30,
        color: str = "#1f2937",
        red_color: str = "#c53030",
        highlight_last_tile: bool = True,
        incoming_call_tile: str = "-",
        incoming_call_source: str = "",
    ):
        super().__init__(parent)
        self.tehai_tiles = list(tehai_tiles)
        self.fuuro_groups = list(fuuro_groups)
        self.font_px = font_px
        self.color = QColor(color)
        self.red_color = QColor(red_color)
        self.highlight_last_tile = highlight_last_tile
        self.incoming_call_tile = incoming_call_tile
        self.incoming_call_source = incoming_call_source
        self.setFixedHeight(font_px + 44)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    @staticmethod
    def _trim_transparent(pixmap: QPixmap) -> QPixmap:
        return TileGlyphStrip._trim_transparent(pixmap)

    def _glyph_pixmap(self, glyph: str, color: QColor, rotated: bool = False) -> QPixmap:
        font = QFont(tile_font_family())
        font.setPixelSize(self.font_px)
        source = QPixmap(max(1, self.font_px + 2), max(1, self.font_px + 4))
        source.fill(Qt.GlobalColor.transparent)
        painter = QPainter(source)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addText(0.0, 0.0, font, glyph)
        bounds = path.boundingRect()
        transform = QTransform()
        transform.translate(-bounds.left(), 1.0 - bounds.top())
        path = transform.map(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPath(path)
        painter.end()
        if rotated:
            rotation = QTransform()
            rotation.rotate(-90)
            source = source.transformed(rotation, Qt.TransformationMode.SmoothTransformation)
            return self._trim_transparent(source)
        return source

    def _tile_pixmap(self, tile: str, rotated: bool = False) -> QPixmap:
        color = self.red_color if is_red_five(tile) else self.color
        return self._glyph_pixmap(tile_to_unicode(tile), color, rotated=rotated)

    def _sequence_width(
        self,
        tiles: list[str],
        called_index: int | None = None,
        last_tile_gap: int = 0,
    ) -> int:
        width = 0
        for index, tile in enumerate(tiles):
            pixmap = self._tile_pixmap(tile, rotated=(index == called_index))
            width += pixmap.width() if index == called_index else max(1, pixmap.width() - 5)
            if last_tile_gap and len(tiles) > 1 and index == len(tiles) - 2:
                width += last_tile_gap
        return width

    def sizeHint(self) -> QSize:
        tehai_last_gap = 5 if self.highlight_last_tile else 0
        width = self._sequence_width(self.tehai_tiles, last_tile_gap=tehai_last_gap)
        if self.incoming_call_tile and self.incoming_call_tile != "-":
            metrics = QFontMetrics(QFont("Noto Sans KR", 11))
            width += 18 + metrics.horizontalAdvance(self.incoming_call_source) + 6
            width += self._tile_pixmap(self.incoming_call_tile).width() + 8
        if self.fuuro_groups:
            width += 12
        for index, group in enumerate(self.fuuro_groups):
            width += self._sequence_width(group.tiles, group.called_tile_index)
            if index != len(self.fuuro_groups) - 1:
                width += 10
        return QSize(max(width + 4, 40), self.height())

    def _draw_incoming_call_indicator(self, painter: QPainter, x: int, baseline_bottom: int) -> int:
        if not self.incoming_call_tile or self.incoming_call_tile == "-":
            return x

        x += 18
        source_font = QFont("Noto Sans KR", 11)
        source_metrics = QFontMetrics(source_font)
        source_text = self.incoming_call_source or ""
        if source_text:
            painter.setFont(source_font)
            painter.setPen(QColor("#9f1239"))
            text_y = baseline_bottom - 10
            painter.drawText(x, text_y, source_text)
            x += source_metrics.horizontalAdvance(source_text) + 6

        pixmap = self._tile_pixmap(self.incoming_call_tile)
        y = baseline_bottom - pixmap.height() - 8
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(251, 113, 133, 88))
        painter.drawRoundedRect(x - 3, y - 2, pixmap.width() + 6, pixmap.height() + 4, 6, 6)
        painter.drawPixmap(x, y, pixmap)
        return x + pixmap.width() + 8

    def _draw_sequence(
        self,
        painter: QPainter,
        x: int,
        baseline_bottom: int,
        tiles: list[str],
        called_index: int | None = None,
        stacked_tile: str | None = None,
        stacked_on_index: int | None = None,
        base_raise: int = 0,
        highlight_last: bool = False,
        last_tile_gap: int = 0,
    ) -> int:
        tile_positions: list[tuple[int, int, int, int]] = []
        for index, tile in enumerate(tiles):
            pixmap = self._tile_pixmap(tile, rotated=(index == called_index))
            y = baseline_bottom - pixmap.height() - base_raise
            if highlight_last and index == len(tiles) - 1:
                highlight_rect_x = x - 3
                highlight_rect_y = y - 2
                highlight_rect_w = pixmap.width() + 6
                highlight_rect_h = pixmap.height() + 4
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(253, 224, 71, 96))
                painter.drawRoundedRect(highlight_rect_x, highlight_rect_y, highlight_rect_w, highlight_rect_h, 6, 6)
            painter.drawPixmap(x, y, pixmap)
            tile_positions.append((x, y, pixmap.width(), pixmap.height()))
            x += pixmap.width() if index == called_index else max(1, pixmap.width() - 5)
            if last_tile_gap and len(tiles) > 1 and index == len(tiles) - 2:
                x += last_tile_gap

        if stacked_tile is not None and stacked_on_index is not None and 0 <= stacked_on_index < len(tile_positions):
            stack_pixmap = self._tile_pixmap(stacked_tile, rotated=True)
            base_x, base_y, base_w, _ = tile_positions[stacked_on_index]
            stack_x = base_x + max(0, (base_w - stack_pixmap.width()) // 2)
            stack_y = base_y + base_raise - stack_pixmap.height() - 8
            painter.drawPixmap(stack_x, stack_y, stack_pixmap)

        return x

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        baseline_bottom = self.height() - 2
        x = 0
        x = self._draw_sequence(
            painter,
            x,
            baseline_bottom,
            self.tehai_tiles,
            base_raise=8,
            highlight_last=self.highlight_last_tile,
            last_tile_gap=5 if self.highlight_last_tile else 0,
        )
        x = self._draw_incoming_call_indicator(painter, x, baseline_bottom)
        if self.fuuro_groups:
            x += 12
        for index, group in enumerate(self.fuuro_groups):
            x = self._draw_sequence(
                painter,
                x,
                baseline_bottom,
                group.tiles,
                group.called_tile_index,
                group.stacked_tile,
                group.stacked_on_index,
                8,
            )
            if index != len(self.fuuro_groups) - 1:
                x += 10
        painter.end()


class AnalysisWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object, object)

    def __init__(self, query: PlayerQuery, model_dirs: list[str], cache_dir: str):
        super().__init__()
        self.query = query
        self.model_dirs = model_dirs
        self.cache_dir = cache_dir

    def run(self):
        try:
            koromo_service = KoromoService()
            self.progress.emit(0, 0, "대국 목록 조회 중...")
            games = koromo_service.fetch_games(self.query)
            self.progress.emit(0, max(len(games), 1), f"대국 {len(games)}개 확인, 분석 준비 중...")
            if not games:
                raise ValueError("조회된 대국이 없습니다.")

            has_real_fetch = bool(self.query.majsoul_access_token) or bool(
                self.query.cn_login_email and self.query.cn_login_password
            )
            paifu_service = MajsoulPaifuService(self.cache_dir)
            if has_real_fetch:
                paifu_service.prepare_cache()

            reports: list[EngineAnalysisResult] = []
            total_models = max(1, len(self.model_dirs))
            for model_index, model_dir in enumerate(self.model_dirs, start=1):
                engine_name = Path(model_dir).name or f"engine_{model_index}"
                analyzer_service = AnalyzerService(model_dir)

                def bridge_progress(current: int, total: int, message: str):
                    prefix = f"[엔진 {model_index}/{total_models}] {engine_name}"
                    self.progress.emit(current, total, f"{prefix} | {message}")

                if has_real_fetch:
                    parsed_query = koromo_service.parse_query(self.query)
                    stats = analyzer_service.analyze_downloaded_games(
                        parsed_query,
                        games,
                        paifu_service,
                        progress_callback=bridge_progress,
                    )
                else:
                    self.progress.emit(model_index - 1, total_models, f"{engine_name} 더미 분석 중...")
                    stats = analyzer_service.analyze_games(games)

                reports.append(
                    EngineAnalysisResult(
                        engine_name=engine_name,
                        model_dir=model_dir,
                        stats=stats,
                    )
                )

            self.finished.emit(reports, None)
        except Exception as exc:  # pragma: no cover - GUI thread boundary
            self.finished.emit(None, exc)


class SingleAnalysisWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object, object)

    def __init__(
        self,
        source_input: str,
        fallback_player_id: int | None,
        query: PlayerQuery,
        model_dirs: list[str],
        cache_dir: str,
    ):
        super().__init__()
        self.source_input = source_input
        self.fallback_player_id = fallback_player_id
        self.query = query
        self.model_dirs = model_dirs
        self.cache_dir = cache_dir

    def run(self):
        try:
            source_service = SingleGameSourceService(self.cache_dir)
            prepared = source_service.prepare(
                self.source_input,
                self.fallback_player_id,
                self.query,
                progress_callback=lambda current, total, message: self.progress.emit(current, total, message),
            )

            reports: list[EngineAnalysisResult] = []
            total_models = max(1, len(self.model_dirs))
            for model_index, model_dir in enumerate(self.model_dirs, start=1):
                engine_name = Path(model_dir).name or f"engine_{model_index}"
                analyzer_service = AnalyzerService(model_dir)

                def bridge_progress(current: int, total: int, message: str):
                    prefix = f"[엔진 {model_index}/{total_models}] {engine_name}"
                    self.progress.emit(current, total, f"{prefix} | {message}")

                stats = analyzer_service.analyze_single_prepared_game(prepared, progress_callback=bridge_progress)
                reports.append(
                    EngineAnalysisResult(
                        engine_name=engine_name,
                        model_dir=model_dir,
                        stats=stats,
                    )
                )

            self.finished.emit(reports, None)
        except Exception as exc:  # pragma: no cover - GUI thread boundary
            self.finished.emit(None, exc)


class KyokuDetailTab(QWidget):
    DRAGON_TILES = {"h", "f", "c", "p"}

    def __init__(
        self,
        kyoku: ReviewKyokuDetail,
        parent: QWidget | None = None,
        *,
        replay_callback=None,
        replay_available: bool = False,
    ):
        super().__init__(parent)
        self.kyoku = kyoku
        self.filtered_entries = list(kyoku.entries)
        self.replay_callback = replay_callback

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["전체 장면", "불일치만", "실제 수 확률 <5%"])
        self.filter_combo.currentIndexChanged.connect(self._populate)

        self.prev_button = QPushButton("이전 장면")
        self.next_button = QPushButton("다음 장면")
        self.prev_button.clicked.connect(lambda: self._move_selection(-1))
        self.next_button.clicked.connect(lambda: self._move_selection(1))

        self.entry_table = QTableWidget(0, 6)
        self.entry_table.setHorizontalHeaderLabels(["순", "직전 패", "실제 수", "AI 수", "확률", "상태"])
        self.entry_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.entry_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.entry_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.entry_table.setStyleSheet(
            "QTableWidget::item:selected { background:#ede9fe; color:#4c1d95; }"
        )
        self.entry_table.verticalHeader().setVisible(False)
        self.entry_table.verticalHeader().setDefaultSectionSize(38)
        self.entry_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.entry_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.entry_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.entry_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.entry_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.entry_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.entry_table.itemSelectionChanged.connect(self._on_entry_changed)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        self.summary_label.setStyleSheet("color: #2d3748;")

        self.compare_label = QLabel("-")
        self.compare_label.setWordWrap(True)
        self.compare_label.setTextFormat(Qt.TextFormat.RichText)
        self.compare_label.setStyleSheet(
            "padding: 8px 10px; border: 1px solid #cbd5e0; border-radius: 8px; background: #f8fafc;"
        )

        self.meta_label = QLabel("-")
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet(
            "padding: 6px 8px; border: 1px solid #e2e8f0; border-radius: 8px; background: #ffffff;"
        )

        self.hand_panel = QWidget()
        self.hand_panel.setFixedHeight(88)
        self.hand_panel.setStyleSheet(
            "border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc;"
        )
        self.hand_panel_layout = QVBoxLayout(self.hand_panel)
        self.hand_panel_layout.setContentsMargins(6, 0, 6, 0)
        self.hand_panel_layout.setSpacing(0)

        self.candidate_table = QTableWidget(0, 4)
        self.candidate_table.setHorizontalHeaderLabels(["실제", "확률", "Q값", "행동"])
        self.candidate_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.candidate_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.candidate_table.verticalHeader().setVisible(False)
        self.candidate_table.verticalHeader().setDefaultSectionSize(24)
        self.candidate_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.candidate_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.candidate_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.candidate_table.horizontalHeader().setStretchLastSection(True)
        self.candidate_table.setColumnWidth(0, 48)
        self.candidate_table.setColumnWidth(1, 90)
        self.candidate_table.setColumnWidth(2, 84)

        self.replay_button = QPushButton("현재 순 Tenhou Replay 보기")
        self.replay_button.setEnabled(replay_available)
        self.replay_button.clicked.connect(self._open_replay)

        self._build_ui()
        self._populate()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.addWidget(self.summary_label)

        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("장면 필터"))
        top_bar.addWidget(self.filter_combo, 1)
        top_bar.addWidget(self.prev_button)
        top_bar.addWidget(self.next_button)
        root.addLayout(top_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addWidget(self.entry_table)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_layout.addWidget(self.compare_label)
        right_layout.addWidget(self.meta_label)
        right_layout.addWidget(self.hand_panel)
        right_layout.addWidget(self.candidate_table)
        right_layout.addWidget(self.replay_button)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        root.addWidget(splitter, 1)

    def _populate(self):
        mode = self.filter_combo.currentIndex()
        if mode == 1:
            self.filtered_entries = [entry for entry in self.kyoku.entries if not entry.is_equal]
        elif mode == 2:
            self.filtered_entries = [entry for entry in self.kyoku.entries if entry.actual_probability < 0.05]
        else:
            self.filtered_entries = list(self.kyoku.entries)

        self.summary_label.setText(
            "<table width='100%' cellspacing='0' cellpadding='0'>"
            "<tr>"
            f"<td><b>{self.kyoku.round_label}</b></td>"
            f"<td align='right'><b>{self.kyoku.seat_label}</b></td>"
            "</tr>"
            "</table>"
            f"점수: {self.kyoku.score_text}<br>"
            f"종료: {self.kyoku.end_summary}"
        )
        self.entry_table.setRowCount(len(self.filtered_entries))
        for row_index, entry in enumerate(self.filtered_entries):
            values = [
                f"{entry.junme}순",
                "",
                entry.actual_action_text,
                entry.expected_action_text,
                f"{entry.actual_probability * 100:.4f}%",
                "일치" if entry.is_equal else "불일치",
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if not entry.is_equal:
                    item.setBackground(QColor("#fee2e2"))
                    item.setForeground(QColor("#7f1d1d"))
                if col_index == 2:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    item.setForeground(QColor("#9b2c2c") if not entry.is_equal else QColor("#276749"))
                elif col_index == 3:
                    item.setForeground(QColor("#1f4f99") if not entry.is_equal else QColor("#1f4f99"))
                if col_index in {0, 4, 5}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.entry_table.setItem(row_index, col_index, item)
            tile_widget = self._make_plain_tile_widget(entry.tile, compact=True)
            tile_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.addWidget(tile_widget, 0, Qt.AlignmentFlag.AlignCenter)
            self.entry_table.setCellWidget(row_index, 1, cell)
        self.prev_button.setEnabled(bool(self.filtered_entries))
        self.next_button.setEnabled(bool(self.filtered_entries))
        if self.filtered_entries:
            self.entry_table.selectRow(0)
            self._update_entry_tile_cell_styles(0)
            self._update_replay_button_state()
        else:
            self.compare_label.setText("-")
            self.meta_label.setText("-")
            self._render_hand_panel(None)
            self.candidate_table.setRowCount(0)
            self._update_replay_button_state()

    def _open_replay(self):
        if self.replay_callback is not None:
            row_index = self.entry_table.currentRow()
            entry = None
            if 0 <= row_index < len(self.filtered_entries):
                entry = self.filtered_entries[row_index]
            self.replay_callback(self.kyoku, entry)

    def _update_replay_button_state(self):
        row_index = self.entry_table.currentRow()
        entry = None
        if 0 <= row_index < len(self.filtered_entries):
            entry = self.filtered_entries[row_index]
        enabled = (
            self.replay_callback is not None
            and entry is not None
            and entry.actual_action_kind == "dahai"
        )
        self.replay_button.setEnabled(enabled)

    def _on_entry_changed(self):
        row_index = self.entry_table.currentRow()
        if row_index < 0 or row_index >= len(self.filtered_entries):
            self._update_replay_button_state()
            return
        self._update_entry_tile_cell_styles(row_index)
        entry = self.filtered_entries[row_index]
        self._update_replay_button_state()
        flags = ", ".join(entry.flags) if entry.flags else "-"
        actual_color = "#c53030" if not entry.is_equal else "#2f855a"
        self.compare_label.setText(
            f"<b>실제 수</b>: <span style='color:{actual_color}; font-weight:700; background:#fff5f5; padding:1px 4px; border-radius:4px;'>{entry.actual_action_text}</span><br>"
            f"<b>AI의 선택</b>: {entry.expected_action_text}<br>"
            f"<b>AI 1순위</b>: {entry.best_action_text}"
        )
        self.meta_label.setText(
            f"<b>순서</b>: {entry.round_label} / {entry.junme}순<br>"
            f"<b>직전 패</b>: {entry.tile}<br>"
            f"<b>샹텐</b>: {'-' if entry.shanten is None else entry.shanten}<br>"
            f"<b>남은 패산</b>: {entry.tiles_left}<br>"
            f"<b>실제 수 확률</b>: {entry.actual_probability * 100:.6f}%<br>"
            f"<b>실제 수 Q값</b>: {entry.actual_q_value:.6f}<br>"
            f"<b>판정</b>: {'일치' if entry.is_equal else '불일치'}<br>"
            f"<b>플래그</b>: {flags}"
        )
        self._render_hand_panel(entry)
        self.candidate_table.setRowCount(len(entry.candidates))
        for row_index, candidate in enumerate(entry.candidates):
            values = [
                "실제" if candidate.is_actual else "",
                f"{candidate.probability * 100:.6f}%",
                f"{candidate.q_value:.6f}",
                candidate.action_text,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_index in {1, 2}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if candidate.is_actual:
                    item.setBackground(QColor("#fef3c7"))
                    item.setForeground(QColor("#92400e"))
                self.candidate_table.setItem(row_index, col_index, item)

    def _move_selection(self, delta: int):
        row = self.entry_table.currentRow()
        if row < 0:
            return
        next_row = max(0, min(self.entry_table.rowCount() - 1, row + delta))
        self.entry_table.selectRow(next_row)

    def _update_entry_tile_cell_styles(self, selected_row: int):
        for row_index, entry in enumerate(self.filtered_entries):
            cell = self.entry_table.cellWidget(row_index, 1)
            if cell is None:
                continue
            if row_index == selected_row:
                bg = "#ede9fe"
                border = "#c4b5fd"
            elif not entry.is_equal:
                bg = "#fee2e2"
                border = "#fecaca"
            else:
                bg = "transparent"
                border = "transparent"
            cell.setStyleSheet(
                f"background:{bg}; border:1px solid {border}; border-radius:6px;"
            )

    @staticmethod
    def _tile_to_unicode(tile: str) -> str:
        return tile_to_unicode(tile)

    @staticmethod
    def _is_red_five(tile: str) -> bool:
        return is_red_five(tile)

    @classmethod
    def _is_dragon_tile(cls, tile: str) -> bool:
        lower = str(tile).lower().strip()
        return len(lower) == 1 and lower in cls.DRAGON_TILES

    @classmethod
    def _tile_font_family(cls) -> str:
        return tile_font_family()

    @staticmethod
    def _tile_text(tile: str) -> str:
        return tile_to_unicode(tile)

    @classmethod
    def _render_single_tile_chip(cls, tile: str, compact: bool = False, called: bool = False) -> str:
        is_red = cls._is_red_five(tile)
        is_dragon = cls._is_dragon_tile(tile)
        bg = "#fda4af" if is_red else "#f8fafc"
        fg = "#991b1b" if is_red else "#1f2937"
        border = "#dc2626" if is_red else "#cbd5e0"
        font_size = 21 if compact else 24
        if is_dragon:
            font_size -= 2
        width = "36px" if compact else "34px"
        height = "34px" if compact else "42px"
        transform = " transform:rotate(90deg);" if called else ""
        display = "inline-flex"
        vertical = "vertical-align:middle;"
        if called:
            width, height = height, width
        return (
            f"<span style=\"display:{display}; align-items:center; justify-content:center; {vertical}"
            f"width:{width}; height:{height}; margin:2px; border:1px solid {border}; border-radius:6px; "
            f"background:{bg}; color:{fg}; font-size:{font_size}px; line-height:1; "
            f"font-weight:{'700' if is_red else '500'}; font-family:'Segoe UI Symbol','Noto Sans KR',sans-serif;{transform}\">"
            f"{cls._tile_to_unicode(tile)}</span>"
        )

    @classmethod
    def _tile_pixmap(cls, tile: str, compact: bool = False, called: bool = False) -> QPixmap:
        is_red = cls._is_red_five(tile)
        is_dragon = cls._is_dragon_tile(tile)
        bg = QColor("#fda4af" if is_red else "#f8fafc")
        fg = QColor("#991b1b" if is_red else "#1f2937")
        border = QColor("#dc2626" if is_red else "#cbd5e0")
        width = 36 if compact else 34
        height = 34 if compact else 42
        font_size = 21 if compact else 24
        if is_dragon:
            font_size -= 2
        text = cls._tile_text(tile)
        family = cls._tile_font_family()
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(border, 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(0, 0, width - 1, height - 1, 6, 6)
        font = QFont(family, pointSize=font_size)
        font.setBold(is_red)
        painter.setFont(font)
        painter.setPen(QPen(fg))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()

        if called:
            transform = QTransform()
            transform.rotate(90)
            pixmap = pixmap.transformed(transform, Qt.TransformationMode.SmoothTransformation)
        return pixmap

    @classmethod
    def _make_tile_widget(cls, tile: str, compact: bool = False, called: bool = False) -> QLabel:
        label = QLabel()
        pixmap = cls._tile_pixmap(tile, compact=compact, called=called)
        label.setPixmap(pixmap)
        label.setFixedSize(pixmap.size())
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    @classmethod
    def _glyph_only_pixmap(cls, tile: str, compact: bool = False) -> QPixmap:
        is_red = cls._is_red_five(tile)
        is_dragon = cls._is_dragon_tile(tile)
        fg = QColor("#c53030" if is_red else "#1f2937")
        font_size = 24 if compact else 30
        if is_dragon:
            font_size -= 2
        text = cls._tile_text(tile)
        family = cls._tile_font_family()
        font = QFont(family)
        font.setPixelSize(font_size)
        source = QPixmap(max(1, font_size + 10), max(1, font_size + 12))
        source.fill(Qt.GlobalColor.transparent)
        painter = QPainter(source)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addText(0.0, 0.0, font, text)
        bounds = path.boundingRect()
        transform = QTransform()
        transform.translate(-bounds.left(), 1.0 - bounds.top())
        path = transform.map(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fg))
        painter.drawPath(path)
        painter.end()
        return TileGlyphStrip._trim_transparent(source)

    @classmethod
    def _make_plain_tile_widget(cls, tile: str, compact: bool = False) -> QLabel:
        label = QLabel()
        pixmap = cls._glyph_only_pixmap(tile, compact=compact)
        label.setPixmap(pixmap)
        label.setMinimumSize(max(28, pixmap.width()), max(32, pixmap.height()))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    @classmethod
    def _render_tiles(cls, tiles: list[str]) -> str:
        if not tiles:
            return "-"
        return "".join(cls._render_single_tile_chip(tile) for tile in tiles)

    @classmethod
    def _render_fuuro_groups(cls, groups: list[ReviewFuuroGroup], fallback_text: str) -> str:
        if not groups:
            return fallback_text
        return "".join(
            f"<div style='margin-top:6px;'><b>{group.label or f'후로 {index}'}</b><br>{''.join(cls._render_single_tile_chip(tile, called=(group.called_tile_index == tile_index)) for tile_index, tile in enumerate(group.tiles))}</div>"
            for index, group in enumerate(groups, start=1)
        )

    def _clear_layout(self, layout: QVBoxLayout | QHBoxLayout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def _render_hand_panel(self, entry):
        self._clear_layout(self.hand_panel_layout)
        if entry is None:
            self.hand_panel_layout.addWidget(QLabel("-"))
            return

        hand_title = QLabel("손패")
        hand_title.setStyleSheet("font-weight:700; color:#2d3748;")
        hand_title.setFixedHeight(14)
        self.hand_panel_layout.addWidget(hand_title)

        display_fuuro_groups = entry.display_fuuro_groups or entry.fuuro_groups

        merged_row = QHBoxLayout()
        merged_row.setContentsMargins(0, 0, 0, 0)
        merged_row.setSpacing(8)
        merged_row.addWidget(
            HandCompositeStrip(
                entry.display_tehai_tiles or entry.tehai_tiles,
                display_fuuro_groups,
                font_px=30,
                highlight_last_tile=entry.highlight_last_tile,
                incoming_call_tile=entry.incoming_call_tile,
                incoming_call_source=entry.incoming_call_source,
            ),
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        merged_row.addStretch(1)
        self.hand_panel_layout.addLayout(merged_row)


class GameDetailWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Koromo Grapher - 상세 대국정보")
        self.resize(1320, 900)
        self.header_label = QLabel("상세 리뷰를 불러오는 중...")
        self.header_label.setWordWrap(True)
        self.header_label.setStyleSheet(
            "padding: 8px 10px; border: 1px solid #cbd5e0; border-radius: 8px; background: #f8fafc;"
        )
        self.tabs = QTabWidget()
        self.replay_dialog: QDialog | None = None
        self.replay_view: QWebEngineView | None = None
        self.tenhou_payload: dict | None = None
        self.mjai_kyoku_events: list[list[tuple[int, dict]]] | None = None

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(self.header_label)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

    def render_detail(
        self,
        game: GameAnalysis,
        report: EngineAnalysisResult,
        review_path: Path,
        detail: ReviewGameDetail,
    ):
        self.setWindowTitle(f"Koromo Grapher - 상세 대국정보 - {game.game_id}")
        match_rate = 0.0
        if detail.total_reviewed:
            match_rate = detail.total_matches * 100.0 / detail.total_reviewed
        self.header_label.setText(
            "<table width='100%' cellspacing='0' cellpadding='0'>"
            f"<tr><td colspan='2'><b>대국 ID</b>: {game.game_id}</td></tr>"
            f"<tr><td colspan='2'><b>엔진</b>: {report.engine_name}</td></tr>"
            f"<tr><td colspan='2'><b>리뷰 파일</b>: {review_path.name}</td></tr>"
            "<tr>"
            f"<td><b>리뷰 Rating</b>: {detail.rating:.2f} / "
            f"<b>검토 수</b>: {detail.total_reviewed} / "
            f"<b>일치 수</b>: {detail.total_matches} ({match_rate:.2f}%)</td>"
            f"<td align='right'><b>mjai-reviewer 버전</b>: {detail.version}</td>"
            "</tr>"
            "</table>"
        )
        self.tenhou_payload = self._load_tenhou_payload(review_path)
        self.mjai_kyoku_events = self._load_mjai_kyoku_events(review_path)
        self.tabs.clear()
        for kyoku in detail.kyokus:
            self.tabs.addTab(
                KyokuDetailTab(
                    kyoku,
                    self,
                    replay_callback=self.open_tenhou_replay,
                    replay_available=self.tenhou_payload is not None,
                ),
                kyoku.round_label,
            )

    @staticmethod
    def _tenhou_json_path_from_review(review_path: Path) -> Path:
        marker = ".tenhou6."
        name = review_path.name
        if marker in name:
            prefix = name.split(marker, 1)[0]
            candidate = review_path.with_name(f"{prefix}.tenhou6.json")
            if candidate.exists():
                return candidate
        game_prefix = name.split(".", 1)[0]
        matches = sorted(review_path.parent.glob(f"{game_prefix}*.tenhou6.json"))
        return matches[0] if matches else review_path.with_suffix(".tenhou6.json")

    def _load_tenhou_payload(self, review_path: Path) -> dict | None:
        tenhou_path = self._tenhou_json_path_from_review(review_path)
        if not tenhou_path.exists():
            return None
        try:
            return json.loads(tenhou_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _split_mjai_events_by_kyoku(events: list[dict]) -> list[list[tuple[int, dict]]]:
        kyokus: list[list[tuple[int, dict]]] = []
        current: list[dict] = []
        for event in events:
            event_type = str(event.get("type", ""))
            if event_type == "start_kyoku":
                current = [event]
            elif current:
                current.append(event)
                if event_type == "end_kyoku":
                    kyokus.append(list(enumerate(current)))
                    current = []
        return kyokus

    def _load_mjai_kyoku_events(self, review_path: Path) -> list[list[tuple[int, dict]]] | None:
        tenhou_path = self._tenhou_json_path_from_review(review_path)
        if not tenhou_path.exists():
            return None
        mjai_path = tenhou_path.with_suffix(".mjai.jsonl")
        try:
            if not mjai_path.exists() or mjai_path.stat().st_mtime < tenhou_path.stat().st_mtime:
                bridge = TenhouToMjaiBridge()
                bridge.convert(tenhou_path, mjai_path)
            raw_events: list[dict] = []
            for line in mjai_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                raw_events.append(json.loads(line))
            return self._split_mjai_events_by_kyoku(raw_events)
        except Exception:
            return None

    def _compute_tenhou_tj(self, kyoku: ReviewKyokuDetail, selected_entry) -> int | None:
        if (
            selected_entry is None
            or selected_entry.actual_action_kind != "dahai"
            or selected_entry.actor is None
            or self.mjai_kyoku_events is None
            or kyoku.log_index < 0
            or kyoku.log_index >= len(self.mjai_kyoku_events)
        ):
            return None
        discard_rank = 0
        for entry in kyoku.entries:
            if entry.actor == selected_entry.actor and entry.actual_action_kind == "dahai":
                discard_rank += 1
            if entry.log_entry_index == selected_entry.log_entry_index:
                break
        if discard_rank <= 0:
            return None
        discard_events = [
            event_index
            for event_index, event in self.mjai_kyoku_events[kyoku.log_index]
            if str(event.get("type", "")).lower() == "dahai" and event.get("actor") == selected_entry.actor
        ]
        if discard_rank > len(discard_events):
            return None
        selected_event_index = discard_events[discard_rank - 1]
        hidden_before = sum(
            1
            for event_index, event in self.mjai_kyoku_events[kyoku.log_index]
            if event_index < selected_event_index and str(event.get("type", "")).lower() == "reach_accepted"
        )
        return max(0, selected_event_index - 1 - hidden_before)

    def _ensure_replay_dialog(self):
        if self.replay_dialog is not None and self.replay_view is not None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Tenhou Replay")
        dialog.setFixedSize(600, 338)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        view = QWebEngineView(dialog)
        layout.addWidget(view)
        self.replay_dialog = dialog
        self.replay_view = view

    def open_tenhou_replay(self, kyoku: ReviewKyokuDetail, entry=None):
        if self.tenhou_payload is None:
            QMessageBox.warning(self, "리플레이 열기 실패", "Tenhou 리플레이 데이터를 찾지 못했습니다.")
            return
        logs = self.tenhou_payload.get("log") or []
        if kyoku.log_index < 0 or kyoku.log_index >= len(logs):
            QMessageBox.warning(self, "리플레이 열기 실패", "현재 국의 Tenhou 로그를 찾지 못했습니다.")
            return

        player_index = kyoku.player_index if kyoku.player_index is not None else 0
        split_payload = dict(self.tenhou_payload)
        split_payload["log"] = [logs[kyoku.log_index]]
        encoded = quote(json.dumps(split_payload, ensure_ascii=False, separators=(",", ":")))
        turn_param = ""
        mapped_tj = self._compute_tenhou_tj(kyoku, entry)
        if mapped_tj is not None:
            turn_param = f"&ts=0&tj={mapped_tj}"
        url = QUrl(f"https://tenhou.net/5/?tw={player_index}{turn_param}#json={encoded}")

        self._ensure_replay_dialog()
        assert self.replay_dialog is not None and self.replay_view is not None
        self.replay_view.setUrl(url)
        self.replay_dialog.show()
        self.replay_dialog.raise_()
        self.replay_dialog.activateWindow()

class ResultWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Koromo Grapher - 결과")
        self.resize(1260, 860)

        self.current_reports: list[EngineAnalysisResult] = []
        self.current_games: list[GameAnalysis] = []
        self.current_report: EngineAnalysisResult | None = None
        self.cache_dir = Path("koromo_review_gui_cache")
        self.detail_window: GameDetailWindow | None = None

        self.summary_labels = {
            "engine_name": QLabel("-"),
            "engine_info": QLabel("-"),
            "total_games": QLabel("-"),
            "total_decisions": QLabel("-"),
            "rating": QLabel("-"),
            "top1_agreement": QLabel("-"),
            "top3_agreement": QLabel("-"),
            "bad_move_rate_5": QLabel("-"),
            "bad_move_rate_10": QLabel("-"),
        }
        self.summary_labels["engine_info"].setWordWrap(True)
        self.summary_labels["engine_info"].setStyleSheet("color: #4a5568; font-size: 11px;")

        self.detail_labels = {
            "game_id": QLabel("-"),
            "started_at": QLabel("-"),
            "decision_count": QLabel("-"),
            "rating": QLabel("-"),
            "top1_agreement": QLabel("-"),
            "top3_agreement": QLabel("-"),
            "bad_move_rate_5": QLabel("-"),
            "bad_move_rate_10": QLabel("-"),
            "notes": QLabel("-"),
        }
        self.detail_labels["notes"].setWordWrap(True)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "대국 ID", "판단 수", "Rating", "AI 일치율", "Top-3 일치율", "악수율 <5%", "악수율 <10%", "메모", "상세",
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 136)
        self.table.setColumnWidth(1, 64)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(3, 86)
        self.table.setColumnWidth(4, 92)
        self.table.setColumnWidth(5, 82)
        self.table.setColumnWidth(6, 86)
        self.table.setColumnWidth(8, 162)
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)
        self.table.itemDoubleClicked.connect(self.open_selected_game_detail)

        self.worst_table = QTableWidget(0, 6)
        self.worst_table.setHorizontalHeaderLabels([
            "국 / 순", "실제 수 확률", "실제 수", "AI 1순위", "Top-1", "Top-3",
        ])
        self.worst_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.worst_table.horizontalHeader().setStretchLastSection(True)
        self.worst_table.verticalHeader().setDefaultSectionSize(24)
        self.worst_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.worst_table.setColumnWidth(0, 108)
        self.worst_table.setColumnWidth(1, 92)
        self.worst_table.setColumnWidth(4, 58)
        self.worst_table.setColumnWidth(5, 58)

        self.chart_view = QChartView()
        self.chart_view.setMinimumHeight(240)
        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setSpacing(10)

        summary = QGroupBox("결과 요약")
        summary_form = QFormLayout(summary)
        summary_form.setVerticalSpacing(8)
        summary_form.addRow("엔진", self.summary_labels["engine_name"])
        summary_form.addRow("엔진 정보", self.summary_labels["engine_info"])
        summary_form.addRow("총 대국 수", self.summary_labels["total_games"])
        summary_form.addRow("총 판단 수", self.summary_labels["total_decisions"])
        summary_form.addRow("Rating", self.summary_labels["rating"])
        summary_form.addRow("AI 일치율", self.summary_labels["top1_agreement"])
        summary_form.addRow("Top-3 일치율", self.summary_labels["top3_agreement"])
        summary_form.addRow("악수율 (<5%)", self.summary_labels["bad_move_rate_5"])
        summary_form.addRow("악수율 (<10%)", self.summary_labels["bad_move_rate_10"])

        summary_tab = QWidget()
        summary_layout = QVBoxLayout(summary_tab)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(10)
        summary_layout.addWidget(summary)
        summary_layout.addWidget(self.chart_view)

        detail_group = QGroupBox("선택한 대국 상세")
        detail_group.setMaximumWidth(420)
        detail_group.setMaximumHeight(360)
        detail_layout = QGridLayout(detail_group)
        detail_layout.setVerticalSpacing(6)
        detail_layout.setHorizontalSpacing(8)
        detail_layout.addWidget(QLabel("대국 ID"), 0, 0)
        detail_layout.addWidget(self.detail_labels["game_id"], 0, 1)
        detail_layout.addWidget(QLabel("시작 시각"), 1, 0)
        detail_layout.addWidget(self.detail_labels["started_at"], 1, 1)
        detail_layout.addWidget(QLabel("판단 수"), 2, 0)
        detail_layout.addWidget(self.detail_labels["decision_count"], 2, 1)
        detail_layout.addWidget(QLabel("Rating"), 3, 0)
        detail_layout.addWidget(self.detail_labels["rating"], 3, 1)
        detail_layout.addWidget(QLabel("AI 일치율"), 4, 0)
        detail_layout.addWidget(self.detail_labels["top1_agreement"], 4, 1)
        detail_layout.addWidget(QLabel("Top-3 일치율"), 5, 0)
        detail_layout.addWidget(self.detail_labels["top3_agreement"], 5, 1)
        detail_layout.addWidget(QLabel("악수율 <5%"), 6, 0)
        detail_layout.addWidget(self.detail_labels["bad_move_rate_5"], 6, 1)
        detail_layout.addWidget(QLabel("악수율 <10%"), 7, 0)
        detail_layout.addWidget(self.detail_labels["bad_move_rate_10"], 7, 1)
        detail_layout.addWidget(QLabel("메모"), 8, 0)
        detail_layout.addWidget(self.detail_labels["notes"], 8, 1)

        table_group = QGroupBox("대국 선택")
        table_group_layout = QVBoxLayout(table_group)
        table_group_layout.setContentsMargins(6, 6, 6, 6)
        table_group_layout.addWidget(self.table)

        worst_group = QGroupBox("낮은 확률 수 목록")
        worst_group_layout = QVBoxLayout(worst_group)
        worst_group_layout.setContentsMargins(6, 6, 6, 6)
        worst_group_layout.addWidget(self.worst_table)

        games_tab = QWidget()
        games_layout = QHBoxLayout(games_tab)
        games_layout.setContentsMargins(0, 0, 0, 0)
        games_layout.setSpacing(10)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(table_group, 3)
        left_layout.addWidget(worst_group, 2)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(detail_group)
        right_layout.addStretch(1)

        games_layout.addWidget(left_panel, 1)
        games_layout.addWidget(right_panel, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        tabs = QTabWidget()
        tabs.addTab(summary_tab, "결과 요약 및 그래프")
        tabs.addTab(games_tab, "대국별 정보")

        layout.addWidget(tabs)
        self.setCentralWidget(root)
    def render_reports(self, reports: list[EngineAnalysisResult]):
        self.current_reports = reports
        if reports:
            self.apply_report(reports[0])
        else:
            self.current_games = []
            self.table.setRowCount(0)
            self._clear_game_detail()
            self._clear_summary()

    def apply_report(self, report: EngineAnalysisResult):
        self.current_report = report
        stats = report.stats
        self.summary_labels["engine_name"].setText(report.engine_name)
        info_lines = [report.model_dir]
        if len(self.current_reports) > 1:
            info_lines.append(f"총 {len(self.current_reports)}개 엔진 중 현재 결과")
        self.summary_labels["engine_info"].setText("\n".join(info_lines))
        self.summary_labels["total_games"].setText(f"{stats.total_games:,}")
        self.summary_labels["total_decisions"].setText(f"{stats.total_decisions:,}")
        self.summary_labels["rating"].setText(f"{stats.rating:.2f}")
        self.summary_labels["top1_agreement"].setText(f"{stats.top1_agreement * 100:.2f}%")
        self.summary_labels["top3_agreement"].setText(f"{stats.top3_agreement * 100:.2f}%")
        self.summary_labels["bad_move_rate_5"].setText(f"{stats.bad_move_rate_5 * 100:.2f}%")
        self.summary_labels["bad_move_rate_10"].setText(f"{stats.bad_move_rate_10 * 100:.2f}%")

        ordered_games = sorted(stats.games, key=lambda row: row.started_at.timestamp() if row.started_at else 0.0)
        self.current_games = ordered_games
        self.table.setRowCount(len(ordered_games))
        for row_index, row in enumerate(ordered_games):
            items = [
                row.game_id,
                str(row.decision_count),
                f"{row.rating:.2f}",
                f"{row.top1_agreement * 100:.2f}%",
                f"{row.top3_agreement * 100:.2f}%",
                f"{row.bad_move_rate_5 * 100:.2f}%",
                f"{row.bad_move_rate_10 * 100:.2f}%",
                row.notes,
            ]
            for col_index, value in enumerate(items):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))
            detail_button = QPushButton("보기")
            detail_button.clicked.connect(lambda _checked=False, idx=row_index: self.open_game_detail_at_row(idx))
            self.table.setCellWidget(row_index, 8, detail_button)

        self._update_chart(ordered_games, report.engine_name)
        if ordered_games:
            self.table.selectRow(0)
            self._show_game_detail(ordered_games[0])
        else:
            self._clear_game_detail()

    def on_table_selection_changed(self):
        row_index = self.table.currentRow()
        if row_index < 0 or row_index >= len(self.current_games):
            self._clear_game_detail()
            return
        self._show_game_detail(self.current_games[row_index])

    def set_cache_dir(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)

    def open_game_detail_at_row(self, row_index: int):
        if row_index < 0 or row_index >= len(self.current_games):
            return
        if self.current_report is None:
            QMessageBox.warning(self, "상세 리뷰 열기 실패", "현재 선택된 엔진 정보가 없습니다.")
            return

        self.table.selectRow(row_index)
        game = self.current_games[row_index]
        review_path = self._review_json_path(game, self.current_report)
        if not review_path.exists():
            QMessageBox.warning(self, "상세 리뷰 열기 실패", f"상세 리뷰 JSON을 찾지 못했습니다: {review_path}")
            return

        try:
            detail = parse_review_detail(review_path)
        except Exception as exc:
            QMessageBox.critical(self, "상세 리뷰 열기 실패", str(exc))
            return

        if self.detail_window is None:
            self.detail_window = GameDetailWindow(self)
        self.detail_window.render_detail(game, self.current_report, review_path, detail)
        self.detail_window.show()
        self.detail_window.raise_()
        self.detail_window.activateWindow()

    def open_selected_game_detail(self, *_args):
        self.open_game_detail_at_row(self.table.currentRow())

    def _review_json_path(self, game: GameAnalysis, report: EngineAnalysisResult) -> Path:
        model_name = Path(report.model_dir).name
        exact_name = (
            f"{game.game_id}.{model_name}.review.json"
            if not game.uuid
            else f"{game.uuid}.tenhou6.{model_name}.review.json"
        )
        exact_path = self.cache_dir / exact_name
        if exact_path.exists():
            return exact_path

        patterns: list[str] = []
        if game.uuid:
            patterns.append(f"{game.uuid}.tenhou6.*.review.json")
        patterns.append(f"{game.game_id}.*.review.json")

        for pattern in patterns:
            matches = sorted(self.cache_dir.glob(pattern))
            if matches:
                return matches[0]

        return exact_path

    def _show_game_detail(self, game: GameAnalysis):
        self.detail_labels["game_id"].setText(game.game_id)
        self.detail_labels["started_at"].setText(self._format_datetime(game.started_at))
        self.detail_labels["decision_count"].setText(str(game.decision_count))
        self.detail_labels["rating"].setText(f"{game.rating:.2f}")
        self.detail_labels["top1_agreement"].setText(f"{game.top1_agreement * 100:.2f}%")
        self.detail_labels["top3_agreement"].setText(f"{game.top3_agreement * 100:.2f}%")
        self.detail_labels["bad_move_rate_5"].setText(
            f"{game.bad_move_rate_5 * 100:.2f}% ({game.bad_move_count_5}/{game.decision_count})"
        )
        self.detail_labels["bad_move_rate_10"].setText(
            f"{game.bad_move_rate_10 * 100:.2f}% ({game.bad_move_count_10}/{game.decision_count})"
        )
        self.detail_labels["notes"].setText(game.notes or "-")
        self.worst_table.setRowCount(len(game.worst_decisions))
        for row_index, row in enumerate(game.worst_decisions):
            values = [
                f"{row.round_label} / {row.junme}순" if row.round_label else str(row.turn_index),
                f"{row.model_probability * 100:.2f}%",
                row.actual_action,
                row.model_action,
                "Y" if row.top1_match else "N",
                "Y" if row.top3_match else "N",
            ]
            for col_index, value in enumerate(values):
                self.worst_table.setItem(row_index, col_index, QTableWidgetItem(value))

    def _clear_game_detail(self):
        for label in self.detail_labels.values():
            label.setText("-")
        self.worst_table.setRowCount(0)

    def _clear_summary(self):
        for label in self.summary_labels.values():
            label.setText("-")
        self.chart_view.setChart(QChart())

    def _update_chart(self, games: list[GameAnalysis], engine_name: str):
        rating_series = QLineSeries()
        rating_series.setName("Rating")

        top1_series = QLineSeries()
        top1_series.setName("AI 일치율")

        bad_series = QLineSeries()
        bad_series.setName("악수율 <5%")

        for idx, game in enumerate(games, start=1):
            rating_series.append(idx, game.rating)
            top1_series.append(idx, game.top1_agreement * 100.0)
            bad_series.append(idx, game.bad_move_rate_5 * 100.0)

        chart = QChart()
        chart.addSeries(rating_series)
        chart.addSeries(top1_series)
        chart.addSeries(bad_series)
        chart.setTitle(f"대국별 분석 추이 - {engine_name}")

        axis_x = QValueAxis()
        axis_x.setTitleText("대국 순서")
        axis_x.setLabelFormat("%d")
        axis_x.setRange(1, max(1, len(games)))

        axis_y = QValueAxis()
        axis_y.setTitleText("값")
        axis_y.setRange(0, 100)

        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        for series in (rating_series, top1_series, bad_series):
            series.attachAxis(axis_x)
            series.attachAxis(axis_y)

        self.chart_view.setChart(chart)

    @staticmethod
    def _format_datetime(value: datetime | None) -> str:
        if value is None:
            return "-"
        return value.strftime("%Y-%m-%d %H:%M:%S")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mortal Koromo Reviewer")
        self.resize(1120, 430)

        self.koromo_service = KoromoService()
        self.single_source_service = SingleGameSourceService(self._default_cache_dir())
        self.session_store = AnalysisSessionStore()
        self.local_settings_store = LocalSettingsStore(self._local_settings_path())
        self.result_window = ResultWindow(self)
        self.current_query: PlayerQuery | None = None
        self.current_query_payload: dict | None = None
        self.current_reports: list[EngineAnalysisResult] = []
        self.worker_thread: QThread | None = None
        self.worker: AnalysisWorker | SingleAnalysisWorker | None = None

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://amae-koromo.sapk.ch/player/120147562/12.9")
        self.cache_dir_input = QLineEdit(str(self._default_cache_dir().resolve()))
        self.cn_email_input = QLineEdit()
        self.cn_email_input.setPlaceholderText("CN server email")
        self.cn_password_input = QLineEdit()
        self.cn_password_input.setPlaceholderText("CN server password")
        self.cn_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.cn_email_input.editingFinished.connect(self.save_local_settings)
        self.cn_password_input.editingFinished.connect(self.save_local_settings)
        self.cn_warning_label = QLabel("주의: CN 이메일과 비밀번호는 이 PC의 로컬 설정 파일에만 저장됩니다.")
        self.cn_warning_label.setWordWrap(True)
        self.cn_warning_label.setToolTip("로컬 설정 파일은 koromo_review_gui_cache 아래에 저장되며 .gitignore로 제외됩니다.")
        self.cn_warning_label.setStyleSheet("color: #2b6cb0; font-size: 11px;")

        self.recent_games_input = QSpinBox()
        self.recent_games_input.setRange(0, 5000)
        self.recent_games_input.setValue(20)
        self.recent_games_input.setSpecialValueText("전체")

        self.single_source_input = QLineEdit()
        self.single_source_input.setPlaceholderText("Majsoul 패보 링크 또는 마작일번가 코드")
        self.single_source_input.textChanged.connect(self._update_single_source_hint)
        self.single_player_override = QCheckBox("Actor ID 지정")
        self.single_player_input = QSpinBox()
        self.single_player_input.setRange(0, 3)
        self.single_player_input.setValue(0)
        self.single_player_input.setEnabled(False)
        self.single_player_override.toggled.connect(self.single_player_input.setEnabled)
        self.single_source_hint = QLabel("-")

        self.model_combo = QComboBox()
        self.model_combo.setToolTip("분석에 사용할 엔진 폴더를 실행 경로 기준 /model 아래에 넣어 주세요.")
        self.refresh_models_button = QPushButton("갱신")
        self.refresh_models_button.clicked.connect(self.populate_models_from_repo)
        self.model_hint_label = QLabel("분석 엔진은 /model 폴더에서 자동으로 읽습니다.")
        self.model_hint_label.setWordWrap(True)
        self.model_hint_label.setToolTip("예: Koromo_Grapher/model/엔진폴더/mortal.pth")
        self.model_hint_label.setStyleSheet("color: #2b6cb0; font-size: 11px;")

        self.run_button = QPushButton("분석 시작")
        self.run_button.clicked.connect(self.run_analysis)
        self.single_run_button = QPushButton("단판 분석 시작")
        self.single_run_button.clicked.connect(self.run_single_analysis)
        self.save_button = QPushButton("결과 저장")
        self.save_button.clicked.connect(self.save_session)
        self.load_button = QPushButton("결과 불러오기")
        self.load_button.clicked.connect(self.load_session)
        self.open_result_button = QPushButton("결과 창 열기")
        self.open_result_button.clicked.connect(self.show_result_window)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_label = QLabel("대기 중")
        self.recent_sessions_list = QListWidget()
        self.recent_sessions_list.itemDoubleClicked.connect(self.load_recent_session_item)
        self.refresh_sessions_button = QPushButton("목록 새로고침")
        self.refresh_sessions_button.clicked.connect(self.populate_recent_sessions)
        self.delete_session_button = QPushButton("선택 세션 삭제")
        self.delete_session_button.clicked.connect(self.delete_selected_session)

        self._build_ui()
        self.menuBar().hide()
        self.populate_models_from_repo()
        self.load_local_settings()
        self.populate_recent_sessions()
        self._update_single_source_hint()
    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)

        controls = QGroupBox("분석 시도")
        controls_layout = QVBoxLayout(controls)

        self.mode_tabs = QTabWidget()
        batch_tab = QWidget()
        batch_form = QFormLayout(batch_tab)
        batch_form.addRow("Koromo 링크", self.url_input)
        batch_form.addRow("최근 N판 (0=전체)", self.recent_games_input)
        batch_form.addRow("", self.run_button)
        self.mode_tabs.addTab(batch_tab, "일괄 분석")

        single_tab = QWidget()
        single_form = QFormLayout(single_tab)
        single_form.addRow("패보 링크/코드", self.single_source_input)
        single_option_row = QHBoxLayout()
        single_option_row.addWidget(self.single_source_hint, 1)
        single_option_row.addWidget(self.single_player_override, 0)
        single_option_row.addWidget(self.single_player_input, 0)
        single_form.addRow("감지 결과 / Actor ID", single_option_row)
        single_form.addRow("", self.single_run_button)
        self.mode_tabs.addTab(single_tab, "단판 분석")
        controls_layout.addWidget(self.mode_tabs)

        shared_form = QFormLayout()
        shared_form.addRow("패보 캐시 폴더", self.cache_dir_input)
        shared_form.addRow("CN 이메일", self.cn_email_input)
        shared_form.addRow("CN 비밀번호", self.cn_password_input)
        shared_form.addRow(self.cn_warning_label)

        model_group = QGroupBox("분석 엔진")
        model_layout = QVBoxLayout(model_group)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.refresh_models_button, 0)
        model_layout.addLayout(model_row)
        model_layout.addWidget(self.model_hint_label)
        shared_form.addRow("분석 엔진", model_group)

        button_row = QHBoxLayout()
        button_row.addWidget(self.open_result_button)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.load_button)
        shared_form.addRow("동작", button_row)
        controls_layout.addLayout(shared_form)

        recent_group = QGroupBox("저장 세션")
        recent_layout = QVBoxLayout(recent_group)
        recent_layout.addWidget(self.recent_sessions_list)
        recent_layout.addWidget(self.refresh_sessions_button)
        recent_layout.addWidget(self.delete_session_button)

        progress_group = QGroupBox("진행 상태")
        progress_layout = QHBoxLayout(progress_group)
        progress_layout.addWidget(self.progress_bar, 4)
        progress_layout.addWidget(self.progress_label, 3)

        result_hint = QLabel("분석이 완료되면 결과는 별도의 결과 창에서 표시됩니다.")
        result_hint.setWordWrap(True)
        result_hint.setStyleSheet("color: #2b6cb0; font-size: 11px;")

        top_row = QHBoxLayout()
        top_row.addWidget(controls, 5)
        top_row.addWidget(recent_group, 4)

        layout.addLayout(top_row)
        layout.addWidget(progress_group)
        layout.addWidget(result_hint)
        layout.addStretch(1)
        self.setCentralWidget(root)

    def _update_single_source_hint(self):
        self.single_source_hint.setText(self.single_source_service.describe_source(self.single_source_input.text()))

    def model_root_dir(self) -> Path:
        return repo_root() / "model"

    def _local_settings_path(self) -> Path:
        return self._default_cache_dir() / "local_settings.json"

    def load_local_settings(self):
        settings = self.local_settings_store.load()
        self.cn_email_input.setText(settings.get("cn_login_email", ""))
        self.cn_password_input.setText(settings.get("cn_login_password", ""))

    def save_local_settings(self):
        self.local_settings_store.save(
            {
                "cn_login_email": self.cn_email_input.text().strip(),
                "cn_login_password": self.cn_password_input.text(),
            }
        )

    def populate_models_from_repo(self):
        model_root = self.model_root_dir()
        previous = self.model_combo.currentData(Qt.ItemDataRole.UserRole)
        self.model_combo.clear()
        if not model_root.exists():
            return

        discovered: list[str] = []
        for child in sorted(model_root.iterdir(), key=lambda path: path.name.lower()):
            if not child.is_dir():
                continue
            if not (child / "mortal.pth").exists():
                continue
            normalized = str(child)
            discovered.append(normalized)
            self._append_model_item(normalized)

        if not discovered:
            return

        preferred = previous if previous in discovered else discovered[0]
        for index in range(self.model_combo.count()):
            if self.model_combo.itemData(index, Qt.ItemDataRole.UserRole) == preferred:
                self.model_combo.setCurrentIndex(index)
                break

    def _append_model_item(self, model_dir: str):
        normalized = str(Path(model_dir))
        for index in range(self.model_combo.count()):
            if self.model_combo.itemData(index, Qt.ItemDataRole.UserRole) == normalized:
                self.model_combo.setCurrentIndex(index)
                return
        self.model_combo.addItem(Path(normalized).name or normalized, normalized)
        self.model_combo.setItemData(self.model_combo.count() - 1, normalized, Qt.ItemDataRole.UserRole)
        self.model_combo.setItemData(self.model_combo.count() - 1, normalized, Qt.ItemDataRole.ToolTipRole)
        self.model_combo.setCurrentIndex(self.model_combo.count() - 1)

    def show_result_window(self):
        self.result_window.show()
        self.result_window.raise_()
        self.result_window.activateWindow()

    def _selected_model_dirs(self) -> list[str]:
        value = self.model_combo.currentData(Qt.ItemDataRole.UserRole)
        return [str(value)] if value else []

    def run_analysis(self):
        if self.worker_thread is not None:
            QMessageBox.information(self, "진행 중", "이미 분석이 실행 중입니다.")
            return

        koromo_url = self.url_input.text().strip()
        if not koromo_url:
            QMessageBox.warning(self, "입력 필요", "Koromo 플레이어 링크를 입력해 주세요.")
            return

        model_dirs = self._selected_model_dirs()
        if not model_dirs:
            QMessageBox.warning(self, "입력 필요", "분석할 엔진 폴더를 하나 준비해 주세요.")
            return

        recent_games = self.recent_games_input.value() or None
        query = PlayerQuery(
            koromo_url=koromo_url,
            recent_games=recent_games,
            majsoul_access_token=None,
            cn_login_email=self.cn_email_input.text().strip() or None,
            cn_login_password=self.cn_password_input.text().strip() or None,
        )
        self.current_query = query
        self.current_query_payload = {
            "analysis_mode": "batch",
            "koromo_url": koromo_url,
            "recent_games": recent_games,
            "player_id": None,
            "mode_id": None,
            "model_dirs": model_dirs,
            "cache_dir": self.cache_dir_input.text().strip(),
        }
        self.progress_label.setText("대국 목록 조회 중...")
        self.progress_bar.setRange(0, 0)
        self._set_running(True)

        self.worker_thread = QThread(self)
        self.worker = AnalysisWorker(query, model_dirs, self.cache_dir_input.text().strip())
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_worker_progress)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()

    def run_single_analysis(self):
        if self.worker_thread is not None:
            QMessageBox.information(self, "진행 중", "이미 분석이 실행 중입니다.")
            return

        source_input = self.single_source_input.text().strip()
        if not source_input:
            QMessageBox.warning(self, "입력 필요", "Majsoul 패보 링크 또는 마작일번가 코드를 입력해 주세요.")
            return

        model_dirs = self._selected_model_dirs()
        if not model_dirs:
            QMessageBox.warning(self, "입력 필요", "분석할 엔진 폴더를 하나 준비해 주세요.")
            return

        self.current_query = None
        effective_player_id = int(self.single_player_input.value()) if self.single_player_override.isChecked() else None
        self.current_query_payload = {
            "analysis_mode": "single",
            "source_input": source_input,
            "single_player_override": self.single_player_override.isChecked(),
            "single_player_id": int(self.single_player_input.value()),
            "model_dirs": model_dirs,
            "cache_dir": self.cache_dir_input.text().strip(),
        }
        self.progress_label.setText("단판 분석 준비 중...")
        self.progress_bar.setRange(0, 0)
        self._set_running(True)

        self.worker_thread = QThread(self)
        self.worker = SingleAnalysisWorker(
            source_input,
            effective_player_id,
            PlayerQuery(
                koromo_url="",
                majsoul_access_token=None,
                cn_login_email=self.cn_email_input.text().strip() or None,
                cn_login_password=self.cn_password_input.text().strip() or None,
            ),
            model_dirs,
            self.cache_dir_input.text().strip(),
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_worker_progress)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()

    def on_worker_progress(self, current: int, total: int, message: str):
        total = max(total, 1)
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.progress_label.setText(message)

    def on_worker_finished(self, reports: list[EngineAnalysisResult] | None, error: Exception | None):
        self._set_running(False)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        if error is not None:
            self.progress_label.setText("실패")
            QMessageBox.critical(self, "분석 실패", str(error))
            return

        self.current_reports = reports or []
        self.render_reports(self.current_reports)
        self.progress_label.setText("분석 완료")
        analysis_mode = (self.current_query_payload or {}).get("analysis_mode", "batch")
        if analysis_mode == "single":
            if (
                self.current_reports
                and self.result_window.current_report is not None
                and self.result_window.current_games
            ):
                self.result_window.open_game_detail_at_row(0)
            else:
                self.show_result_window()
        else:
            self.show_result_window()

        has_real_fetch = bool(
            self.current_query
            and self.current_query.cn_login_email
            and self.current_query.cn_login_password
        )
        if analysis_mode == "batch" and not has_real_fetch:
            QMessageBox.information(self, "안내", "이번 실행은 실제 패보 인증 정보가 없어 더미 결과로 분석되었습니다.")
    def _cleanup_worker(self):
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        if self.worker_thread is not None:
            self.worker_thread.deleteLater()
            self.worker_thread = None

    def render_reports(self, reports: list[EngineAnalysisResult]):
        self.result_window.set_cache_dir(self.cache_dir_input.text().strip())
        self.result_window.render_reports(reports)

    def save_session(self):
        if not self.current_reports or self.current_query_payload is None:
            QMessageBox.information(self, "저장할 내용 없음", "먼저 분석을 한 번 실행해 주세요.")
            return

        default_name = self._default_session_filename()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "분석 결과 저장",
            str((self._sessions_dir() / default_name).resolve()),
            "JSON Files (*.json)",
        )
        if not path:
            return

        safe_query = dict(self.current_query_payload)
        safe_query["model_dirs"] = self._selected_model_dirs()
        safe_query["cache_dir"] = self.cache_dir_input.text().strip()
        self.session_store.save(path, safe_query, self.current_reports)
        self.progress_label.setText(f"저장 완료: {Path(path).name}")
        self.populate_recent_sessions()

    def load_session(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "분석 결과 불러오기",
            str(self._sessions_dir().resolve()),
            "JSON Files (*.json)",
        )
        if not path:
            return

        session = self.session_store.load(path)
        self.apply_loaded_session(session)
        self.progress_label.setText(f"불러옴: {Path(path).name}")

    def load_recent_session_item(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        session = self.session_store.load(path)
        self.apply_loaded_session(session)
        self.progress_label.setText(f"불러옴: {Path(path).name}")

    def delete_selected_session(self):
        item = self.recent_sessions_list.currentItem()
        if item is None:
            QMessageBox.information(self, "선택 필요", "삭제할 저장 세션을 먼저 선택해 주세요.")
            return

        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            QMessageBox.warning(self, "삭제 실패", "선택한 세션 파일 경로를 찾지 못했습니다.")
            return

        session_path = Path(path)
        reply = QMessageBox.question(
            self,
            "세션 삭제",
            f"{session_path.name}\n세션 파일을 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            session_path.unlink(missing_ok=False)
        except FileNotFoundError:
            QMessageBox.warning(self, "삭제 실패", "이미 삭제되었거나 파일을 찾을 수 없습니다.")
            self.populate_recent_sessions()
            return
        except Exception as exc:
            QMessageBox.critical(self, "삭제 실패", str(exc))
            return

        self.populate_recent_sessions()
        self.progress_label.setText(f"삭제 완료: {session_path.name}")

    def apply_loaded_session(self, session: AnalysisSession):
        query = session.query
        self.current_query_payload = dict(query)
        self.cache_dir_input.setText(query.get("cache_dir", self.cache_dir_input.text()))
        saved_model_dirs = {str(Path(model_dir)) for model_dir in query.get("model_dirs", [])}
        self.populate_models_from_repo()
        if saved_model_dirs:
            for index in range(self.model_combo.count()):
                if self.model_combo.itemData(index, Qt.ItemDataRole.UserRole) in saved_model_dirs:
                    self.model_combo.setCurrentIndex(index)
                    break

        if query.get("analysis_mode") == "single":
            self.mode_tabs.setCurrentIndex(1)
            self.single_source_input.setText(query.get("source_input", ""))
            self.single_player_override.setChecked(bool(query.get("single_player_override", False)))
            self.single_player_input.setValue(int(query.get("single_player_id", 0)))
            self.current_query = None
        else:
            self.mode_tabs.setCurrentIndex(0)
            self.url_input.setText(query.get("koromo_url", ""))
            recent_games = query.get("recent_games")
            self.recent_games_input.setValue(int(recent_games or 0))
            self.current_query = PlayerQuery(
                koromo_url=query.get("koromo_url", ""),
                recent_games=recent_games,
                player_id=query.get("player_id"),
                mode_id=query.get("mode_id"),
            )

        self.current_reports = session.reports
        self.result_window.set_cache_dir(self.cache_dir_input.text().strip())
        self.render_reports(session.reports)
        self.show_result_window()

    def populate_recent_sessions(self):
        self.recent_sessions_list.clear()
        session_dir = self._sessions_dir()
        session_dir.mkdir(parents=True, exist_ok=True)
        candidates = sorted(session_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)[:20]
        for path in candidates:
            label = f"{path.stem}  ({self._format_timestamp(path.stat().st_mtime)})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.recent_sessions_list.addItem(item)

    def _set_running(self, running: bool):
        self.run_button.setEnabled(not running)
        self.single_run_button.setEnabled(not running)
        self.open_result_button.setEnabled(not running)
        self.save_button.setEnabled(not running)
        self.load_button.setEnabled(not running)
        self.model_combo.setEnabled(not running)
        self.refresh_models_button.setEnabled(not running)
        self.refresh_sessions_button.setEnabled(not running)
        self.delete_session_button.setEnabled(not running)

    def _default_session_filename(self) -> str:
        if self.current_query_payload and self.current_query_payload.get("analysis_mode") == "single":
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return f"single_game_{timestamp}.json"
        player_id = self._safe_player_fragment(self.url_input.text().strip())
        recent_games = self.recent_games_input.value() or "all"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{player_id}_recent{recent_games}_{timestamp}.json"

    @staticmethod
    def _safe_player_fragment(koromo_url: str) -> str:
        fragment = koromo_url.rstrip("/").split("/")[-2:] if koromo_url else []
        if len(fragment) >= 2:
            return f"player_{fragment[-2]}"
        return "analysis"

    @staticmethod
    def _format_timestamp(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _default_cache_dir() -> Path:
        return Path("koromo_review_gui_cache")

    @staticmethod
    def _sessions_dir() -> Path:
        return Path("koromo_review_gui_cache") / "sessions"
