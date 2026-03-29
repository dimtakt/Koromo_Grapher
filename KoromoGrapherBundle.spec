# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.building.api import MERGE


common_hiddenimports = ['toml', 'tqdm', 'tqdm.auto', 'tqdm.std']
common_excludes = ['pandas', 'matplotlib', 'scipy', 'tables', 'IPython', 'jedi', 'tkinter']

app_analysis = Analysis(
    ['koromo_review_gui\\app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('koromo_review_gui\\fetch_majsoul_record.js', 'koromo_review_gui'),
        ('koromo_review_gui\\decode_majsoul_record.js', 'koromo_review_gui'),
        ('koromo_review_gui\\bundled\\fetch_majsoul_record.bundle.js', 'koromo_review_gui\\bundled'),
        ('koromo_review_gui\\bundled\\decode_majsoul_record.bundle.js', 'koromo_review_gui\\bundled'),
        ('koromo_review_gui\\local_mortal_review_config.toml', 'koromo_review_gui'),
    ],
    hiddenimports=common_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=common_excludes,
    noarchive=False,
    optimize=0,
)

runner_analysis = Analysis(
    ['koromo_review_gui\\run_local_mortal_review.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=common_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=common_excludes,
    noarchive=False,
    optimize=0,
)

MERGE(
    (app_analysis, 'KoromoGrapher', 'KoromoGrapher'),
    (runner_analysis, 'run_local_mortal_review', 'run_local_mortal_review'),
)

app_pyz = PYZ(app_analysis.pure)
runner_pyz = PYZ(runner_analysis.pure)

app_exe = EXE(
    app_pyz,
    app_analysis.scripts,
    [],
    exclude_binaries=True,
    name='KoromoGrapher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

runner_exe = EXE(
    runner_pyz,
    runner_analysis.scripts,
    [],
    exclude_binaries=True,
    name='run_local_mortal_review',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    app_exe,
    runner_exe,
    app_analysis.binaries,
    app_analysis.zipfiles,
    app_analysis.datas,
    runner_analysis.binaries,
    runner_analysis.zipfiles,
    runner_analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='KoromoGrapher',
)
