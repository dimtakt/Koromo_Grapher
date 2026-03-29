from __future__ import annotations

import sys
from pathlib import Path

try:
    from PySide6.QtWidgets import QApplication
except ModuleNotFoundError as exc:
    if exc.name == "PySide6":
        root = Path(__file__).resolve().parents[1]
        message = (
            "\n[Koromo Grapher] PySide6가 설치되어 있지 않습니다.\n"
            "소스코드로 실행하려면 아래 중 하나를 사용해 주세요.\n\n"
            "1. 권장: 빌드된 실행 파일 실행\n"
            f"   - {root / 'release' / 'KoromoGrapher' / 'KoromoGrapher.exe'}\n"
            "   - 또는 launch_koromo_reviewer.vbs 더블클릭\n\n"
            "2. Python 환경에서 직접 실행\n"
            f"   - pip install -r \"{root / 'requirements.txt'}\"\n"
            "   - python -m koromo_review_gui.app\n"
        )
        print(message, file=sys.stderr)
        raise SystemExit(1) from None
    raise

if __package__:
    from .ui import MainWindow
else:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from koromo_review_gui.ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
