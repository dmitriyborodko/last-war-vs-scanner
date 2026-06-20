param(
    [switch]$Install,
    [switch]$DownloadModels,
    [switch]$ValidateRelease
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $Python)) {
    py -3.12 -m venv (Join-Path $Root ".venv")
}

& $Python -c "import cv2, openpyxl, paddleocr, paddle, pandas, rapidocr_onnxruntime, tkinterdnd2"
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install -r (Join-Path $Root "requirements.txt") --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install the required Python packages."
    }
}

if ($DownloadModels) {
    $env:PYTHONPATH = Join-Path $Root "src"
    & $Python -m vsparser.download_models
    exit $LASTEXITCODE
}

if ($ValidateRelease) {
    $env:PYTHONPATH = Join-Path $Root "src"
    & $Python -m vsparser.validate_release
    exit $LASTEXITCODE
}

if ($Install) {
    exit 0
}

$Desktop = Join-Path $Root "desktop.py"
Start-Process -FilePath $Pythonw -ArgumentList ('"{0}"' -f $Desktop)
