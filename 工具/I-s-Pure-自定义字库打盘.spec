# -*- mode: python ; coding: utf-8 -*-
"""自定义字库打盘的单文件 EXE。

这个工具会去仓库里找 修复/字库/制作粗圆修复字库.py、替换字库.py 与
字码频率证据.json（repo_root() 优先看 sys._MEIPASS），所以必须把 修复/ 打进去，
否则 EXE 在没有仓库的机器上跑不起来。
"""

a = Analysis(
    ['自定义字库打盘.py'],
    pathex=[],
    binaries=[],
    datas=[('../修复', '修复')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='I-s-Pure-自定义字库打盘',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
