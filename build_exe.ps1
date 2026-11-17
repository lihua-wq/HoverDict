# Build a standalone Windows build with PyInstaller.
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1
# Result: dist\HoverDict\HoverDict.exe  (folder build, no Python needed on the target PC)
$ErrorActionPreference = "Stop"
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $base

$py = Join-Path $base ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "No .venv found. Run setup.bat first." -ForegroundColor Red
    exit 1
}

Write-Host "[1/3] installing PyInstaller..." -ForegroundColor Cyan
& $py -m pip install --upgrade pyinstaller
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/3] cleaning old outputs..." -ForegroundColor Cyan
Remove-Item -Recurse -Force "$base\build", "$base\dist" -ErrorAction SilentlyContinue

Write-Host "[3/3] running PyInstaller (this takes a few minutes)..." -ForegroundColor Cyan
& $py -m PyInstaller --noconfirm --clean (Join-Path $base "hoverdict.spec")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$exe = Join-Path $base "dist\HoverDict\HoverDict.exe"
if (-not (Test-Path $exe)) {
    Write-Host "Build finished but $exe is missing." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Done: $exe" -ForegroundColor Green
Write-Host "Run it once, then edit the config next to it:" -ForegroundColor Green
Write-Host ("  " + (Join-Path $base "dist\HoverDict\data\config.json") + ' -> "dict_dir"')
