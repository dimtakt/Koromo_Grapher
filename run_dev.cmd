@echo off
setlocal
setlocal EnableExtensions

set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv-build-cpu\Scripts\python.exe"
set "PY_EXE="
set "PY_ARGS="

pushd "%ROOT%" >nul

if exist "%VENV_PY%" (
  set "PY_EXE=%VENV_PY%"
  set "PY_ARGS=-m koromo_review_gui.app"
  goto run
)

for /f "delims=" %%P in ('where py 2^>nul') do if not defined PY_EXE (
  set "PY_EXE=%%P"
  set "PY_ARGS=-3.12 -m koromo_review_gui.app"
)

if defined PY_EXE goto run

for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY_EXE (
  set "PY_EXE=%%P"
  set "PY_ARGS=-m koromo_review_gui.app"
)

if defined PY_EXE goto run

echo Python executable was not found. 1>&2
echo Install Python 3.12 and dependencies, or create .venv-build-cpu first. 1>&2
echo.
pause
popd >nul
exit /b 1

:run
call "%PY_EXE%" %PY_ARGS%
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Development launch failed with exit code %EXIT_CODE%. 1>&2
  pause
)

popd >nul
exit /b %EXIT_CODE%
