# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包脚本：AtlasMap（地图导出器）。

用法： python -m PyInstaller --noconfirm AtlasMap.spec
产物： dist/AtlasMap/AtlasMap.exe（onedir，双击即用）

构建时原样附带固定的导出器工具链，并记录逐文件 SHA256。
"""
import os
import re
import sys

# 构建日志在中文 Windows 控制台/CI 上可能不是 UTF-8，直接 print 中文会抛
# UnicodeEncodeError；这里把标准输出改成 utf-8 + replace，日志照打不误。
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:      # noqa: BLE001
    pass

ONEFILE = os.environ.get("ATLASMAP_BUILD_ONEFILE") == "1"

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.dirname(os.path.abspath(SPECPATH if "SPECPATH" in globals() else os.getcwd()))
if not os.path.isdir(os.path.join(ROOT, "app")):
    ROOT = os.path.abspath(os.getcwd())

binaries = []
datas = []
hiddenimports = []

# ---- 本体资源 --------------------------------------------------------------
for name in ("maplogo.png", "unreal-engine.svg", "wizard_bg.png", "wizard_base.png",
             "tutorial_maps.png", "tutorial_ue.png", "tutorial_performance.png", "tutorial_progress.png",
             "wizard_rows.json", "wizard_row1.png", "wizard_row2.png", "wizard_row3.png"):
    path = os.path.join(ROOT, "assets", name)
    if os.path.exists(path):
        datas.append((path, "assets"))
    else:
        print(f"[spec] 警告：assets/{name} 不存在，开屏会用占位 logo")

fonts = os.path.join(ROOT, "assets", "fonts")
if os.path.isdir(fonts):
    for name in os.listdir(fonts):
        if name.lower().endswith((".ttf", ".otf")):
            datas.append((os.path.join(fonts, name), "assets/fonts"))

# 地图代号 → 中文名对照表（core/mapnames.py 会先找 _MEIPASS，再找 exe 旁）
_mn = os.path.join(ROOT, "core", "mapnames.json")
if os.path.exists(_mn):
    datas.append((_mn, "core"))
else:
    print("[spec] 警告：core/mapnames.json 不存在，地图列表会只显示代号")

# 说明文档也带一份（DocsPage 优先读 runtime 目录里的 docs，读不到就用这份）
docs = os.path.join(ROOT, "docs")
if os.path.isdir(docs):
    for name in os.listdir(docs):
        src = os.path.join(docs, name)
        if os.path.isfile(src):
            datas.append((src, "docs"))


def _stamp() -> str:
    try:
        txt = open(os.path.join(ROOT, "app", "version.py"), encoding="utf-8").read()
        ver = re.search(r'VERSION\s*=\s*"([^"]+)"', txt)
        build = re.search(r'BUILD\s*=\s*"([^"]+)"', txt)
        return f"{ver.group(1) if ver else '1.0'}+{build.group(1) if build else 'dev'}"
    except Exception:                                            # noqa: BLE001
        return "1.0+dev"


# ---- 第三方包 --------------------------------------------------------------
for pkg in ("fluentpy", "darkdetect"):
    try:
        b, d, h = collect_all(pkg)
        binaries += b
        datas += d
        hiddenimports += h
    except Exception as exc:                                     # noqa: BLE001
        print(f"[spec] collect_all({pkg}) skipped: {exc}")

for pkg in ("fluentpy",):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:                                            # noqa: BLE001
        pass

hiddenimports += ["darkdetect"]

# One-file payloads are unpacked to sys._MEIPASS, including native workers.
if ONEFILE:
    from pathlib import Path
    import hashlib
    import json
    from PyInstaller.config import CONF
    reference = Path(os.environ.get('ATLASMAP_TOOL_SOURCE') or os.path.join(ROOT, 'runtime'))
    for name, expected in (
        ('map-export.exe', '32cfc2d98630eba7c8513027d8b5a72cc30da86c7fffb0283f45a6e4f18b548c'),
        ('dfmap.dll', '5487055ac32c5d059f5339b53e7cba37fdc8c42564cf822ae181390e7a6bdc24')):
        if hashlib.sha256((reference/name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Reference exporter hash mismatch: ' + name)
    manifest = []
    for folder, destination in ((Path(ROOT)/'scripts', 'scripts'), (reference, 'runtime')):
        for source in sorted(folder.rglob('*')):
            if not source.is_file() or '__pycache__' in source.parts or source.suffix == '.pyc':
                continue
            relative = source.relative_to(folder)
            if destination == 'runtime':
                if source.name == 'reference-exporter.json':
                    continue
                manifest.append(dict(file=relative.as_posix(), bytes=source.stat().st_size,
                                     sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
            datas.append((str(source), str(Path(destination)/relative.parent)))
    generated = Path(CONF['workpath'])/'singlefile-payload'
    generated.mkdir(parents=True, exist_ok=True)
    receipt = generated/'reference-exporter.json'
    receipt.write_text(json.dumps(dict(variant='required-AtlasMap-runtime', files=manifest), indent=2), encoding='utf-8')
    datas.append((str(receipt), 'runtime'))

block_cipher = None

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
# Qt 6.12 on Windows imports the OS ICU's unversioned ucnv_* exports.
# Codex's Poppler directory is on PATH and supplies another icuuc.dll whose
# exports have _78 suffixes. It must not shadow Windows' ICU in a frozen app.
if os.name == "nt":
    a.binaries = [entry for entry in a.binaries
                  if os.path.basename(entry[0]).lower() not in ("icuuc.dll", "icudt78.dll")]
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe_payload = [a.binaries, a.datas] if ONEFILE else [[]]
exe = EXE(
    pyz,
    a.scripts,
    *exe_payload,
    exclude_binaries=not ONEFILE,
    name="AtlasMap-Standalone" if ONEFILE else "AtlasMap",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=os.environ.get("ATLASMAP_BUILD_CONSOLE") == "1",
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=None,
)

if not ONEFILE:
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="AtlasMap",
    )

    # ---- 收尾：写版本信息、清掉误入的运行期垃圾 ---------------------------------
    import shutil

    from PyInstaller.config import CONF
    _dist = os.path.join(CONF["distpath"], "AtlasMap")
    shutil.copytree(os.path.join(ROOT, "scripts"), os.path.join(_dist, "scripts"),
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    _data = os.path.join(_dist, "data")
    os.makedirs(_data, exist_ok=True)
    with open(os.path.join(_data, "版本信息.txt"), "w", encoding="utf-8") as fp:
        fp.write(f"AtlasMap · 地图导出器\n构建时间：{__import__('time').strftime('%Y-%m-%d %H:%M')}\n"
                 f"版本：{_stamp()}\n")
    for junk in ("pdfmap", "work"):
        p = os.path.join(_dist, junk)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
    print(f"[spec] 打好了：{_dist}  版本 {_stamp()}")

    # Keep the reference exporter byte-for-byte, with all managed/native deps.
    from pathlib import Path
    import hashlib
    import json
    _reference = Path(os.environ.get('ATLASMAP_TOOL_SOURCE') or os.path.join(ROOT,'runtime'))
    if not (_reference/'map-export.exe').is_file() or not (_reference/'dfmap.dll').is_file():
        raise RuntimeError('Missing reference exporter: '+str(_reference))
    for _name,_expected in (
        ('map-export.exe','32cfc2d98630eba7c8513027d8b5a72cc30da86c7fffb0283f45a6e4f18b548c'),
        ('dfmap.dll','5487055ac32c5d059f5339b53e7cba37fdc8c42564cf822ae181390e7a6bdc24')):
        if hashlib.sha256((_reference/_name).read_bytes()).hexdigest()!=_expected:
            raise RuntimeError('Reference exporter hash mismatch: '+_name)
    _tool = Path(_dist)/'runtime'
    _tool.mkdir(parents=True,exist_ok=True)
    _files = list(_reference.glob('*.dll')) + [_reference/n for n in
        ('map-export.exe','dfmap.deps.json','dfmap.runtimeconfig.json')]
    _manifest = []
    for src in _files:
        shutil.copy2(src,_tool/src.name)
    for folder in ('runtimes','presets','docs'):
        if (_reference/folder).is_dir():
            shutil.copytree(_reference/folder,_tool/folder,dirs_exist_ok=True)
    for dst in sorted(_tool.rglob('*')):
        if dst.is_file() and dst.name != 'reference-exporter.json':
            relative=dst.relative_to(_tool)
            src=_reference/relative
            digest=hashlib.sha256(dst.read_bytes()).hexdigest()
            if digest != hashlib.sha256(src.read_bytes()).hexdigest():
                raise RuntimeError('Reference exporter copy differs: '+str(relative))
            _manifest.append({'file':relative.as_posix(),'sha256':digest,'bytes':dst.stat().st_size})
    (_tool/'reference-exporter.json').write_text(json.dumps({'reference':str(_reference),
        'variant':'required-AtlasMap-runtime','files':_manifest},indent=2),encoding='utf-8')
    print('[spec] Reference exporter verified:',len(_manifest),'files')
