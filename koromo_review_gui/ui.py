from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
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
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .local_settings import LocalSettingsStore
from .models import AnalysisSession, EngineAnalysisResult, GameAnalysis, PlayerQuery
from .runtime_paths import repo_root
from .services import AnalyzerService, KoromoService, MajsoulPaifuService
from .session_store import AnalysisSessionStore


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


class ResultWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Koromo Grapher - 결과")
        self.resize(1260, 860)

        self.current_reports: list[EngineAnalysisResult] = []
        self.current_games: list[GameAnalysis] = []

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

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "대국 ID", "판단 수", "Rating", "AI 일치율", "Top-3 일치율", "악수율 <5%", "악수율 <10%", "메모",
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setColumnWidth(0, 170)
        self.table.setColumnWidth(1, 64)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(3, 86)
        self.table.setColumnWidth(4, 92)
        self.table.setColumnWidth(5, 82)
        self.table.setColumnWidth(6, 86)
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)

        self.worst_table = QTableWidget(0, 6)
        self.worst_table.setHorizontalHeaderLabels([
            "국 / 순", "실제 수 확률", "실제 수", "AI 1순위", "Top-1", "Top-3",
        ])
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
        self.session_store = AnalysisSessionStore()
        self.local_settings_store = LocalSettingsStore(self._local_settings_path())
        self.result_window = ResultWindow(self)
        self.current_query: PlayerQuery | None = None
        self.current_reports: list[EngineAnalysisResult] = []
        self.worker_thread: QThread | None = None
        self.worker: AnalysisWorker | None = None

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

        self.model_combo = QComboBox()
        self.model_combo.setToolTip("분석에 사용할 모델 폴더를 실행 경로 기준 /model 아래에 넣어 주세요.")
        self.refresh_models_button = QPushButton("갱신")
        self.refresh_models_button.clicked.connect(self.populate_models_from_repo)
        self.model_hint_label = QLabel("모델은 /model 폴더에서 자동으로 읽습니다.")
        self.model_hint_label.setWordWrap(True)
        self.model_hint_label.setToolTip("예: Koromo_Grapher/model/모델폴더/mortal.pth")
        self.model_hint_label.setStyleSheet("color: #2b6cb0; font-size: 11px;")

        self.run_button = QPushButton("분석 시작")
        self.run_button.clicked.connect(self.run_analysis)
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
        self._build_menu()
        self.populate_models_from_repo()
        self.load_local_settings()
        self.populate_recent_sessions()
    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)

        controls = QGroupBox("분석 시도")
        controls_form = QFormLayout(controls)
        controls_form.addRow("Koromo 링크", self.url_input)
        controls_form.addRow("패보 캐시 폴더", self.cache_dir_input)
        controls_form.addRow("CN 이메일", self.cn_email_input)
        controls_form.addRow("CN 비밀번호", self.cn_password_input)
        controls_form.addRow(self.cn_warning_label)
        controls_form.addRow("최근 N판 (0=전체)", self.recent_games_input)

        model_group = QGroupBox("분석 모델")
        model_layout = QVBoxLayout(model_group)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.refresh_models_button, 0)
        model_layout.addLayout(model_row)
        model_layout.addWidget(self.model_hint_label)
        controls_form.addRow("모델", model_group)

        button_row = QHBoxLayout()
        button_row.addWidget(self.run_button)
        button_row.addWidget(self.open_result_button)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.load_button)
        controls_form.addRow("동작", button_row)

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

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("파일")
        exit_action = QAction("종료", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

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
            QMessageBox.warning(self, "입력 필요", "분석할 모델 폴더를 하나 준비해 주세요.")
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
        self.show_result_window()
        self.progress_label.setText("분석 완료")

        has_real_fetch = bool(self.current_query and self.current_query.cn_login_email and self.current_query.cn_login_password)
        if not has_real_fetch:
            QMessageBox.information(self, "안내", "이번 실행은 실제 패보 인증 정보가 없어 더미 결과로 분석되었습니다.")
    def _cleanup_worker(self):
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        if self.worker_thread is not None:
            self.worker_thread.deleteLater()
            self.worker_thread = None

    def render_reports(self, reports: list[EngineAnalysisResult]):
        self.result_window.render_reports(reports)

    def save_session(self):
        if not self.current_reports or self.current_query is None:
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

        safe_query = {
            "koromo_url": self.current_query.koromo_url,
            "recent_games": self.current_query.recent_games,
            "player_id": self.current_query.player_id,
            "mode_id": self.current_query.mode_id,
            "model_dirs": self._selected_model_dirs(),
            "cache_dir": self.cache_dir_input.text().strip(),
        }
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
        self.url_input.setText(query.get("koromo_url", ""))
        self.cache_dir_input.setText(query.get("cache_dir", self.cache_dir_input.text()))
        recent_games = query.get("recent_games")
        self.recent_games_input.setValue(int(recent_games or 0))
        saved_model_dirs = {str(Path(model_dir)) for model_dir in query.get("model_dirs", [])}
        self.populate_models_from_repo()
        if saved_model_dirs:
            for index in range(self.model_combo.count()):
                if self.model_combo.itemData(index, Qt.ItemDataRole.UserRole) in saved_model_dirs:
                    self.model_combo.setCurrentIndex(index)
                    break
        self.current_reports = session.reports
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
        self.open_result_button.setEnabled(not running)
        self.save_button.setEnabled(not running)
        self.load_button.setEnabled(not running)
        self.model_combo.setEnabled(not running)
        self.refresh_models_button.setEnabled(not running)
        self.refresh_sessions_button.setEnabled(not running)
        self.delete_session_button.setEnabled(not running)

    def _default_session_filename(self) -> str:
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
