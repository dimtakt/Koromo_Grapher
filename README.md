# Koromo Grapher

- Koromo 기반 작혼 패보를 로컬 Mortal로 분석해, 지표와 그래프로 보여주는 도구
- 제작에 `OpenAI Codex` 사용
- 자세한 설명은 [GUIDE.md](./GUIDE.md) 참조

Koromo based Mahjong Soul review GUI powered by Mortal and `mjai-reviewer`.

## Run

- Release build: `release\KoromoGrapher\KoromoGrapher.exe`
- Portable launch: `launch_koromo_reviewer.vbs`

## Model

- Put one model per folder under `model\`
- Each model folder must contain `mortal.pth`

## Build

```powershell
powershell -ExecutionPolicy Bypass -File .\build_koromo_grapher_exe.ps1
```

## Build Note

- The source repo does not track `_external/amae-koromo-scripts/node_modules`
- Release builds still require that folder locally
- Before building, run:

```powershell
cd .\_external\amae-koromo-scripts
npm install
```