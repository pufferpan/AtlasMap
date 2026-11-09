"""Assemble the reviewed tool and documentation without game data or AES files."""
import hashlib,json,shutil,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'dfmap-gui/bin/Release/net10.0-windows'
CHECKS=ROOT/'out/software_upgrade/20261031'
DEST=ROOT/'release/dfmap-fixed-20261031'
DEST.mkdir(parents=True,exist_ok=True)

def copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)

for file in BUILD.rglob('*'):
    if not file.is_file() or file.suffix in ['.pdb','.log'] or file.name=='dfmap.json':continue
    copy(file,DEST/file.relative_to(BUILD))
for folder in ['docs','presets']:
    for file in (ROOT/folder).rglob('*'):
        if file.is_file():copy(file,DEST/folder/file.relative_to(ROOT/folder))
for file in (ROOT/'scripts').rglob('*'):
    if file.is_file() and file.suffix in ['.py','.cs','.csproj'] and not set(file.parts)&{'bin','obj','__pycache__'}:
        copy(file,DEST/'scripts'/file.relative_to(ROOT/'scripts'))
for folder in ['dfmap','dfmap-gui','tests']:
    for file in (ROOT/folder).rglob('*'):
        if file.is_file() and file.suffix in ['.cs','.csproj','.md'] and not set(file.parts)&{'bin','obj'}:
            copy(file,DEST/'source'/folder/file.relative_to(ROOT/folder))
for file in (ROOT/'scripts').rglob('*'):
    if file.is_file() and file.suffix in ['.py','.cs','.csproj'] and not set(file.parts)&{'bin','obj','__pycache__'}:
        copy(file,DEST/'source/scripts'/file.relative_to(ROOT/'scripts'))
# Research decoder source is needed to reproduce specialized HDR/3D/hidden
# component audits. Include code, never their game-derived texture payloads.
helpers=[ROOT/'out/Iceland/audit/environment_query/lighting/decoder',
         ROOT/'out/Iceland/water_rebuild/20261031/source_data/extractor',
         ROOT/'out/Iceland/collision_rebuild/20261031/helper_audit']
for directory in helpers:
    if directory.exists():
        for file in directory.rglob('*'):
            if file.is_file() and file.suffix in ['.cs','.csproj','.py'] and not set(file.parts)&{'bin','obj'}:
                copy(file,DEST/'research_helpers'/directory.name/file.relative_to(directory))

config={'PaksDirectory':'','Recursive':True,'Game':'GAME_DeltaForce','MeshGame':'','KeyFile':'','KeyUrl':''}
(DEST/'dfmap.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
launcher='@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\nstart "" "%~dp0dfmap-gui.exe" --config "%~dp0dfmap.json"\r\n'
(DEST/'打开地图导出修正版.cmd').write_text(launcher,encoding='ascii',newline='')
local=json.loads((ROOT/'out/Iceland/audit/environment_query/dfmap.json').read_text(encoding='utf-8-sig'))
(CHECKS/'exporter.local.json').write_text(json.dumps(local,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'打开地图导出修正版.cmd').write_text('@echo off\r\nsetlocal\r\nstart "" "%~dp0release\\dfmap-fixed-20261031\\dfmap-gui.exe" --config "%~dp0out\\software_upgrade\\20261031\\exporter.local.json"\r\n',encoding='ascii',newline='')

summary=json.loads((CHECKS/'验证摘要.json').read_text(encoding='utf-8'))
for kind,file in [('water','water_source_smoke/Iceland_water_verified.saved_validation.json'),('hidden','hidden_source_smoke/hidden_verified.saved_validation.json')]:
    d=json.loads((CHECKS/file).read_text(encoding='utf-8'))
    assert d['complete'] and not d['errors']
    summary['blender_'+kind+'_saved_reopen_pass']=True
(CHECKS/'验证摘要.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
copy(CHECKS/'验证摘要.json',DEST/'验证摘要.json')
copy(CHECKS/'gui_smoke_final.png',DEST/'docs/修正版界面.png')
copy(CHECKS/'软件优化与验证.md',DEST/'软件优化与验证.md')
(DEST/'先读我.md').write_text('''# 地图导出修正版

双击 `打开地图导出修正版.cmd`。先在“资源与配置”选择本机游戏根目录和密钥 JSON，然后检查、挂载、导出。

- [完整教程、踩坑和 AI 说明](docs/Iceland地图导出与还原说明书.md)
- [文档导航](docs/README.md)
- [软件使用方法](docs/软件修正版使用说明.md)
- [本轮优化与验证](软件优化与验证.md)

需要 Windows x64 的 .NET 10 Desktop Runtime；本机已具备构建与运行环境。本包不包含游戏资源、当前地图成品或密钥。源码位于 source，常用处理脚本位于 scripts。

这是基础导出软件修正版。Iceland 完整成品仍经过教程中的地图专用几何、材质、UE 水体/光照/碰撞恢复；不承诺点一次导出自动重建原游戏全部效果。
''',encoding='utf-8')
manifest=[]
for file in sorted(DEST.rglob('*')):
    if file.is_file() and file.name!='文件校验清单.json':
        manifest.append({'path':file.relative_to(DEST).as_posix(),'bytes':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
assert not any('aeskey' in row['path'].lower() or row['path'].lower().endswith('.pak') for row in manifest)
(DEST/'文件校验清单.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
archive=DEST.with_suffix('.zip')
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as stream:
    for file in sorted(DEST.rglob('*')):
        if file.is_file():stream.write(file,DEST.name+'/'+file.relative_to(DEST).as_posix())
report={'directory':str(DEST),'archive':str(archive),'archive_bytes':archive.stat().st_size,'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':len(manifest),'game_data_or_key_files_included':False}
(CHECKS/'delivery.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
