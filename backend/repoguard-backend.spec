# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：把 RepoGuard 后端封成单文件 repoguard-backend.exe。

样本仓库、前端 dist、数据库文件不打进本 exe，由 Electron 壳按环境变量定位。
"""
from PyInstaller.utils.hooks import collect_submodules

hidden = []
for pkg in ("fastapi", "uvicorn", "starlette", "anyio", "pydantic", "httpx"):
    hidden += collect_submodules(pkg)

# 内置兜底控制台页面（前端 dist 缺失时使用）
datas = [("app/static/index.html", "app/static")]

a = Analysis(
    ["run_desktop.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "tkinter", "matplotlib", "numpy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="repoguard-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
