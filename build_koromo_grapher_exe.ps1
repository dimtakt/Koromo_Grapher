$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$cpuBuildPython = Join-Path $root ".venv-build-cpu\Scripts\python.exe"
$pythonExe = if (Test-Path $cpuBuildPython) { $cpuBuildPython } else { Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe" }
if (-not (Test-Path $pythonExe)) {
    throw "Python 3.12 not found at $pythonExe"
}

function Copy-Tree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (Test-Path $Destination) {
        Remove-Item -Recurse -Force $Destination
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Copy-Item -Recurse -Force (Join-Path $Source "*") $Destination
}

function Copy-IfExists {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (Test-Path $Source) {
        $destParent = Split-Path -Parent $Destination
        if ($destParent) {
            New-Item -ItemType Directory -Force -Path $destParent | Out-Null
        }
        Copy-Item -Recurse -Force $Source $Destination
    }
}

Write-Host "[1/7] Validating Python 3.12 environment..."
& $pythonExe -c "import PySide6, PyInstaller, tensoul, tqdm, torch, numpy; print('ok')"

$amaeNodeModules = Join-Path $root "_external\amae-koromo-scripts\node_modules"
if (-not (Test-Path $amaeNodeModules)) {
    throw "Missing _external\amae-koromo-scripts\node_modules. Run 'npm install' in _external\amae-koromo-scripts before building."
}

$reviewerExe = Join-Path $root "_external\mjai-reviewer\target\release\mjai-reviewer.exe"
if (-not (Test-Path $reviewerExe)) {
    throw "Missing _external\mjai-reviewer\target\release\mjai-reviewer.exe. Run 'cargo build --release' in _external\mjai-reviewer before building."
}

Write-Host "[2/7] Cleaning previous build artifacts..."
foreach ($path in @("build", "dist")) {
    if (Test-Path $path) {
        Remove-Item -Recurse -Force $path
    }
}

Write-Host "[3/7] Building KoromoGrapher.exe..."
& $pythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    "KoromoGrapherBundle.spec"

Write-Host "[4/7] Building run_local_mortal_review.exe..."
Write-Host "Included in KoromoGrapherBundle.spec (shared runtime)"

$distRoot = Join-Path $root "dist\KoromoGrapher"
$releaseRoot = Join-Path $root "release\KoromoGrapher"

Write-Host "[5/7] Preparing release folder..."
if (Test-Path $releaseRoot) {
    Remove-Item -Recurse -Force $releaseRoot
}
New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
Copy-Item -Recurse -Force (Join-Path $distRoot "*") $releaseRoot

Write-Host "[6/7] Copying runtime assets..."
Copy-Tree (Join-Path $root "mortal") (Join-Path $releaseRoot "mortal")
Copy-Tree (Join-Path $root "libriichi") (Join-Path $releaseRoot "libriichi")

$externalRelease = Join-Path $releaseRoot "_external"
New-Item -ItemType Directory -Force -Path $externalRelease | Out-Null

$amaeSrc = Join-Path $root "_external\amae-koromo-scripts"
$amaeDst = Join-Path $externalRelease "amae-koromo-scripts"
New-Item -ItemType Directory -Force -Path $amaeDst | Out-Null
foreach ($file in @("majsoul.js", "majsoulPb.js", "majsoulPb.proto.json", "env.js", "LICENSE")) {
    Copy-IfExists (Join-Path $amaeSrc $file) (Join-Path $amaeDst $file)
}
Copy-IfExists (Join-Path $amaeSrc "node_modules") (Join-Path $amaeDst "node_modules")

$reviewerSrc = Join-Path $root "_external\mjai-reviewer"
$reviewerDst = Join-Path $externalRelease "mjai-reviewer"
New-Item -ItemType Directory -Force -Path (Join-Path $reviewerDst "target\release") | Out-Null
Copy-IfExists $reviewerExe (Join-Path $reviewerDst "target\release\mjai-reviewer.exe")
Copy-IfExists (Join-Path $reviewerSrc "LICENSE") (Join-Path $reviewerDst "LICENSE")

$mahjongApiSrc = Join-Path $root "_external\mahjong_soul_api"
$mahjongApiDst = Join-Path $externalRelease "mahjong_soul_api"
New-Item -ItemType Directory -Force -Path $mahjongApiDst | Out-Null
Copy-IfExists (Join-Path $mahjongApiSrc "ms") (Join-Path $mahjongApiDst "ms")
Copy-IfExists (Join-Path $mahjongApiSrc "LICENSE") (Join-Path $mahjongApiDst "LICENSE")
Copy-IfExists (Join-Path $mahjongApiSrc "README.md") (Join-Path $mahjongApiDst "README.md")

$targetRelease = Join-Path $releaseRoot "target\release"
New-Item -ItemType Directory -Force -Path $targetRelease | Out-Null
Copy-Item -Force (Join-Path $root "target\release\riichi.dll") (Join-Path $targetRelease "riichi.dll")

$tensoulInternal = Join-Path $releaseRoot "_internal\tensoul"
New-Item -ItemType Directory -Force -Path $tensoulInternal | Out-Null
& $pythonExe -c "import pathlib, shutil, tensoul; src = pathlib.Path(tensoul.__file__).with_name('cfg.json'); dst = pathlib.Path(r'$tensoulInternal') / 'cfg.json'; shutil.copy2(src, dst)"

if (Test-Path (Join-Path $root "node_modules\node\bin\node.exe")) {
    Copy-Item -Force (Join-Path $root "node_modules\node\bin\node.exe") (Join-Path $releaseRoot "node.exe")
}
elseif (Test-Path (Join-Path $root "node.exe")) {
    Copy-Item -Force (Join-Path $root "node.exe") (Join-Path $releaseRoot "node.exe")
}
else {
    $nodeCmd = (Get-Command node -ErrorAction SilentlyContinue)
    if ($nodeCmd) {
        Copy-Item -Force $nodeCmd.Source (Join-Path $releaseRoot "node.exe")
    }
}

$modelDir = Join-Path $releaseRoot "model"
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
$gitkeep = Join-Path $modelDir ".gitkeep"
if (-not (Test-Path $gitkeep)) {
    New-Item -ItemType File -Path $gitkeep | Out-Null
}

if (Test-Path (Join-Path $root "README.md")) {
    Copy-Item -Force (Join-Path $root "README.md") (Join-Path $releaseRoot "README.md")
}

Write-Host "[7/7] Build complete."
Write-Host "Release folder: $releaseRoot"
