# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

trial_hiddenimports = ["controle_paie._trial_build"] if Path("controle_paie/_trial_build.py").exists() else []
hiddenimports = collect_submodules("duckdb") + collect_submodules("openpyxl") + collect_submodules("docx") + collect_submodules("pypdf") + collect_submodules("pdfplumber") + trial_hiddenimports

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/sicorpa.png", "assets"), ("assets/sicorpa.ico", "assets")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "notebook", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SICORPA",
    icon="assets/sicorpa.ico",
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
    version="version_info.txt",
)
