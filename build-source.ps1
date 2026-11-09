param(
    [string]$PythonExe = 'python',
    [string]$ToolSource = ''
)
$ErrorActionPreference = 'Stop'
$sourceRoot = $PSScriptRoot
if (-not $ToolSource) {
    $ToolSource = Join-Path $sourceRoot 'runtime'
    if (-not (Test-Path -LiteralPath (Join-Path $ToolSource 'map-export.exe'))) {
        throw 'runtime/ 下没有 map-export.exe，请用 -ToolSource 指定固定工具链目录。'
    }
}
$ToolSource = (Resolve-Path -LiteralPath $ToolSource).Path
$expected = @{
    'map-export.exe' = '32cfc2d98630eba7c8513027d8b5a72cc30da86c7fffb0283f45a6e4f18b548c'
    'dfmap.dll' = 'f5a909824c021b27ff5a76d94e1b5a3f01db85b09d84568e9b990d327cbc6ac7'
}
foreach ($entry in $expected.GetEnumerator()) {
    $actual = (Get-FileHash -LiteralPath (Join-Path $ToolSource $entry.Key) -Algorithm SHA256).Hash
    if ($actual -ne $entry.Value) { throw "Reference exporter differs: $($entry.Key)" }
}
$previousToolSource = $env:ATLASMAP_TOOL_SOURCE
Push-Location -LiteralPath $sourceRoot
try {
    $env:ATLASMAP_TOOL_SOURCE = $ToolSource
    & dotnet publish tools\scene_state\scene-state.csproj -c Release -o scripts\tools\scene-state
    if ($LASTEXITCODE -ne 0) { throw 'Source-state helper build failed.' }
    foreach ($codec in @('Detex.dll', 'zlib-ng2.dll', 'oodle-data-shared.dll')) {
        Copy-Item -LiteralPath (Join-Path $ToolSource $codec) -Destination (Join-Path $sourceRoot 'scripts\tools\scene-state') -Force
    }
    & $PythonExe -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Regression tests failed.' }
    & $PythonExe -m PyInstaller --noconfirm AtlasMap.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    Write-Host (Join-Path $sourceRoot 'dist\AtlasMap\AtlasMap.exe')
} finally {
    $env:ATLASMAP_TOOL_SOURCE = $previousToolSource
    Pop-Location
}
