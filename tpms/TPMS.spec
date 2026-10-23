# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import glob

# 自动定位 Conda 依赖 DLL 路径 (解决 _ctypes 依赖 ffi.dll 以及 tkinter, crypto, lzma, bz2 等缺失问题)
extra_binaries = []
conda_prefix = sys.prefix
conda_lib_bin = os.path.join(conda_prefix, 'Library', 'bin')
if not os.path.isdir(conda_lib_bin):
    conda_lib_bin = os.path.join(os.path.dirname(sys.executable), 'Library', 'bin')

if os.path.isdir(conda_lib_bin):
    if conda_lib_bin not in os.environ.get('PATH', ''):
        os.environ['PATH'] = conda_lib_bin + os.pathsep + os.environ.get('PATH', '')

    target_dll_patterns = [
        'ffi*.dll',
        'libcrypto*.dll',
        'libssl*.dll',
        'libbz2*.dll',
        'bzip2*.dll',
        'liblzma*.dll',
        'libexpat*.dll',
        'expat*.dll',
        'sqlite3*.dll',
        'tcl86t*.dll',
        'tk86t*.dll',
        'zlib*.dll',
    ]
    for pattern in target_dll_patterns:
        for f in glob.glob(os.path.join(conda_lib_bin, pattern)):
            extra_binaries.append((f, '.'))

a = Analysis(
    ['main.py'],
    pathex=[conda_lib_bin] if os.path.isdir(conda_lib_bin) else [],
    binaries=extra_binaries,
    datas=[('data', 'data')],
    hiddenimports=['_ctypes', 'ctypes'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'matplotlib', 'scipy'],
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
    name='TPMS',
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
