param(
  [string]$EngineRoot = "",
  [string]$Project    = "D:\AtlasMap-build\atlasmap\work\ue_test\AtlasMapTest54\AtlasMapTest54.uproject",
  [string]$Level      = "",          # 留空就用 manifest 里的 level
  [string]$AssetRoot  = "",          # 留空就用 manifest 里的 ue_root
  [switch]$JustCheck
)

$ErrorActionPreference = "Stop"
$tool  = "D:\AtlasMap-build\atlasmap"
$xfer  = Join-Path $tool "work\ue_test\ue_transfer"

function Find-Engine([string]$hint) {
  $cands = @()
  if ($hint) { $cands += $hint }
  $cands += @("E:\UE_5.4", "D:\UE_5.4", "C:\Program Files\Epic Games\UE_5.4", "E:\UE_5.3")
  foreach ($c in $cands) {
    $exe = Join-Path $c "Engine\Binaries\Win64\UnrealEditor.exe"
    if (Test-Path $exe) {
      $ver = Join-Path $c "Engine\Build\Build.version"
      $v = if (Test-Path $ver) { (Get-Content $ver -Raw | ConvertFrom-Json).MajorVersion.ToString() + "." + (Get-Content $ver -Raw | ConvertFrom-Json).MinorVersion } else { "?" }
      return [pscustomobject]@{ Root = $c; Exe = $exe; Version = $v }
    }
  }
  return $null
}

Write-Host "== 1. 找引擎 ==" -ForegroundColor Cyan
$eng = Find-Engine $EngineRoot
if (-not $eng) {
  Write-Host "没找到可用的 UnrealEditor.exe。" -ForegroundColor Yellow
  Write-Host "  E:\UE_5.4 现在只有 .egstore（还没下载完）。等 Epic 装好后重跑本脚本。" -ForegroundColor Yellow
  exit 2
}
Write-Host ("  " + $eng.Exe + "  (版本 " + $eng.Version + ")")
if ($eng.Version -notlike "5.4*") {
  Write-Host ("  提醒：官方 bridge 按 5.4 写，当前是 " + $eng.Version + "，可能需要改 API") -ForegroundColor Yellow
}

Write-Host "== 2. 找工程 ==" -ForegroundColor Cyan
if (-not (Test-Path $Project)) { throw "工程不存在：$Project" }
Write-Host "  $Project"

Write-Host "== 3. transfer 包自检 ==" -ForegroundColor Cyan
$env:ATLASMAP_UE_ROOT = $xfer
python (Join-Path $tool "scripts\official\ue_preflight.py")

if ($JustCheck) { exit 0 }

Write-Host "== 4. 清掉残留的 Unreal 进程（单实例，不清会吃命令） ==" -ForegroundColor Cyan
Get-Process | Where-Object { $_.ProcessName -like "*Unreal*" } | ForEach-Object { try { $_.Kill() } catch {} }
Start-Sleep -Seconds 4

if (-not $AssetRoot) { $AssetRoot = "/Game/AtlasMaps/CollectionRoom54" }
if (-not $Level)     { $Level     = "$AssetRoot/LV_Map" }
$env:ATLASMAP_UE_DEST  = $AssetRoot
$env:ATLASMAP_UE_LEVEL = $Level

Write-Host "== 5. 起编辑器 ==" -ForegroundColor Cyan
Write-Host ("  目标资产根 " + $AssetRoot + "；目标关卡 " + $Level)
Start-Process -FilePath $eng.Exe -ArgumentList @("`"$Project`"") -WorkingDirectory (Split-Path $Project)
Write-Host "  等编辑器加载（约 60-120 秒）..." -ForegroundColor DarkGray
Start-Sleep -Seconds 75

$msg = @"
== 6. 在编辑器里干这三件事 ==
  a) 新建关卡并保存到 $Level（File → New Level → Empty Level，Save As 到上面路径）
  b) Output Log 左下 Cmd 下拉切到 "Python"，粘这一行自检：
     exec(compile(open(r'TOOLPATH\scripts\official\ue_preflight.py', encoding='utf-8').read(), 'ue_preflight.py', 'exec'))
  c) 自检全 OK 后，再粘这一行开始 7 阶段导入（进度看 Output Log 的 [runner] 行）：
     exec(compile(open(r'TOOLPATH\scripts\official\ue_stage_runner.py', encoding='utf-8').read(), 'ue_stage_runner.py', 'exec'))

  环境变量已经在本脚本里设好：ATLASMAP_UE_ROOT / DEST / LEVEL，编辑器从本脚本启动才继承得到。
"@
$msg = $msg.Replace('TOOLPATH', $tool)
Write-Host $msg -ForegroundColor Green
