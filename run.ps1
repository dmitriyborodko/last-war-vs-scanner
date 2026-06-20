$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $Python)) {
    py -3.12 -m venv (Join-Path $Root ".venv")
}

& $Python -c "import cv2, openpyxl, pandas, rapidocr_onnxruntime, tkinterdnd2"
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install -r (Join-Path $Root "requirements.txt") --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install the required Python packages."
    }
}

$Desktop = Join-Path $Root "desktop.py"
Start-Process -FilePath $Pythonw -ArgumentList ('"{0}"' -f $Desktop)
