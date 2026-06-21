param(
    [switch]$SkipInstall,
    [switch]$SkipModels
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$AppName = "Last-War-VS-Scanner"
Set-Location $Root

if (Test-Path $VenvPython) {
    $Python = $VenvPython
} elseif ($SkipInstall) {
    $Python = (Get-Command python -ErrorAction Stop).Source
} else {
    py -3.12 -m venv (Join-Path $Root ".venv")
    $Python = $VenvPython
}

if (-not $SkipInstall) {
    & $Python -m pip install -r (Join-Path $Root "requirements-release.txt") --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw "Could not install release dependencies." }
}

$env:PYTHONPATH = Join-Path $Root "src"
if (-not $SkipModels) {
    & $Python -m vsparser.download_models
    if ($LASTEXITCODE -ne 0) { throw "Could not download OCR models." }
}

& $Python -m vsparser.validate_release
if ($LASTEXITCODE -ne 0) { throw "Release validation failed." }

$Icon = Join-Path $Root "assets\last-war-vs-scanner.png"
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --contents-directory . `
    --name $AppName `
    --icon $Icon `
    --paths (Join-Path $Root "src") `
    --add-data "assets;assets" `
    --add-data "src\vsparser\locales;vsparser\locales" `
    --add-data "models\paddleocr;models\paddleocr" `
    --collect-all paddleocr `
    --collect-all rapidocr_onnxruntime `
    --collect-all tkinterdnd2 `
    (Join-Path $Root "desktop.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$Archive = Join-Path $Root "dist\$AppName-windows-x64.zip"
if (Test-Path $Archive) { Remove-Item -LiteralPath $Archive -Force }
Compress-Archive -Path (Join-Path $Root "dist\$AppName\*") -DestinationPath $Archive
Write-Host "Release archive: $Archive"
