# Mortal Koromo Reviewer

Koromo 플레이어 링크를 넣고, 해당 유저의 대국을 로컬에서 Mortal 계열 엔진으로 복기 분석하는 GUI 도구입니다.

현재 가능한 것

- Koromo 플레이어 링크에서 실제 대국 목록 조회
- 여러 Mortal 모델 폴더를 동시에 등록하고 같은 대국 세트를 비교 분석
- CN 계정 이메일/비밀번호 또는 작혼 token 기반 패보 다운로드
- 패보를 `tenhou6` 형식으로 변환
- 로컬 `mjai-reviewer.exe`를 직접 호출해 `rating / AI 일치율 / 악수율` 계산
- 엔진별 결과 전환 보기
- 대국별 추이 그래프와 선택 대국 상세 보기
- 낮은 확률 수 목록 확인
- 분석 결과를 JSON 세션으로 저장하고 나중에 다시 불러오기

권장 실행

```powershell
python -m koromo_review_gui.app
```

exe 빌드

```powershell
.\build_koromo_reviewer_exe.ps1
```

빌드가 끝나면 실행 파일은 아래 경로에 생깁니다.

- `dist\MortalKoromoReviewer\MortalKoromoReviewer.exe`

빠른 실행용으로는 아래 파일도 같이 쓸 수 있습니다.

- `launch_koromo_reviewer.cmd`

현재 빌드는 경량 방식입니다.

- `_external`, `mortal` 폴더 전체를 exe 안에 통째로 넣지 않습니다.
- 대신 exe가 현재 repo 폴더를 기준으로 필요한 리소스를 찾아 쓰는 방식입니다.
- 그래서 빌드 시간은 훨씬 짧고, 지금 작업 중인 repo 안에서 실행하기에 적합합니다.

주요 입력값

- `Koromo 링크`
- `모델 폴더` 여러 개
- `패보 캐시 폴더`
- `작혼 token` 또는 `CN 이메일 / 비밀번호`
- `최근 N판`

저장되는 분석 세션에는 비밀번호와 token이 포함되지 않습니다.

현재 분석 엔진은 Python 재구현이 아니라, 로컬의 원본 `mjai-reviewer.exe`를 호출하는 방식이 기본입니다. 그래서 웹 복기와 완전히 같다고 장담하진 않지만, 로컬 기준으로는 더 일관된 결과를 기대할 수 있습니다.
