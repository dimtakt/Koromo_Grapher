@echo off
setlocal
set "ROOT=%~dp0"
set "EXE_RELEASE=%ROOT%release\KoromoGrapher\KoromoGrapher.exe"
set "RUNNER_RELEASE=%ROOT%release\KoromoGrapher\run_local_mortal_review\run_local_mortal_review.exe"
set "EXE_DIST=%ROOT%dist\KoromoGrapher\KoromoGrapher.exe"
set "RUNNER_DIST=%ROOT%dist\run_local_mortal_review\run_local_mortal_review.exe"

if exist "%EXE_RELEASE%" if exist "%RUNNER_RELEASE%" (
  start "" "%EXE_RELEASE%"
  exit /b 0
)

if exist "%EXE_DIST%" if exist "%RUNNER_DIST%" (
  start "" "%EXE_DIST%"
  exit /b 0
)

echo KoromoGrapher.exe를 찾지 못했습니다. 1>&2
echo release\KoromoGrapher 또는 dist\KoromoGrapher 빌드 결과가 필요합니다. 1>&2
exit /b 1
