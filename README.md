# Last War VS Ranking Parser

Local Windows tool for extracting alliance-member names, VS points, and visible ranks from an iPhone `.mp4` screen recording. Frames, OCR output, corrections, and exports remain on the PC.

## Privacy and scope

- No recording or result is uploaded by the application.
- OCR runs locally with RapidOCR/ONNX Runtime and PaddleOCR CPU models.
- The tool only reads a supplied video. It does not control the game, collect credentials, or inspect network traffic.
- Streamlit listens on `127.0.0.1` and telemetry is disabled in `.streamlit/config.toml`.

## Windows setup

Install 64-bit Python 3.11 or 3.12, then copy the iPhone recording to the PC using a USB cable or another local transfer method. From PowerShell:

```powershell
cd path\to\vsParser
.\run.ps1
```

Alternatively, double-click `run.cmd` in File Explorer or run it from Command Prompt:

```bat
cd /d path\to\vsParser
run.cmd
```

The first run creates `.venv` and installs dependencies. Download the multilingual model bundle once while online:

```powershell
.\run.ps1 -DownloadModels
```

The models are stored under `models/paddleocr`. Later video processing is completely local and does not require internet access. Set `VS_PARSER_MODEL_DIR` before launching to use a pre-provisioned model directory on another drive or an offline deployment.

## Use

1. Choose the ISO week in the top-left corner. The current week opens automatically; the selector also includes the previous two years and every saved week.
2. Drag each `.mp4` onto its **Day 1** through **Day 6** or **Weekly Overall** box, or use the box's **Browse** button. Clicking the box opens its result tab.
3. Every daily box is a **Push day** by default; uncheck any day you want to exclude. Click the **Push Days** box to see each member's summed points and recalculated rank.
4. Optionally select **Alliance Members** and paste a Google Sheets column to fill the member table. Double-click a name to edit it, or use its **Other Names** and **Delete** buttons, then save the table.
5. Videos process one at a time in drop order. Drop a new video on any completed box to replace and reprocess that slot.
6. Review each result in its matching table tab. Double-click a rank, name, or points cell to edit it. Edits are saved immediately. Select rows and press `Ctrl+C`, or use **Copy Selected Table** / **Copy All Week Tables**.

Weekly history is stored locally under `data/weeks`; processed files are grouped under `output/weeks`. Opening a saved week restores its reviewed tables without rerunning video processing.

The previous browser-based review interface remains available with `.venv\Scripts\python.exe -m streamlit run app.py`.

Raw automatic outputs are also saved as `observations.json`, `results.json`, `vs_rankings.csv`, and `vs_rankings.xlsx` in the output folder. Selected source frames are kept under `frames`.

The optional local roster defaults to `data/member_roster.json`. It retains corrected Unicode names and the OCR spellings seen for them. This helps symbols and stylized names resolve consistently in later recordings; uncertain matches remain review flags.
The detector runs once per frame. Name boxes are then recognized by a cached PP-OCRv6 recognizer for Latin (including Vietnamese) and Chinese, plus current PP-OCRv5 language-family recognizers for Cyrillic and Arabic. Confidence, Unicode script compatibility, and roster similarity select the candidate. Numeric rank and point fields stay on the fast default recognizer. Arabic remains logical Unicode in JSON/CSV/XLSX; the desktop and spreadsheet software handle visual right-to-left display.

After observations are merged, recognized names are corrected against the roster again. Unmatched OCR names are assigned to the most similar alliance member when there is a meaningful resemblance. Only names with no sufficiently similar member are highlighted red; saved members still absent after this correction are added at the bottom with zero points and highlighted yellow.

Models are loaded lazily and cached for the lifetime of the desktop process, including all seven queued videos. If the multilingual bundle is absent, the prior RapidOCR Chinese/basic-Latin path remains available and the model downloader can be run later.

## Release packaging

The released app must include the complete Python environment from `requirements.txt` and the populated `models/paddleocr` directory beside the executable. End users should not run the downloader. Frozen builds resolve models relative to the executable; development builds resolve them relative to the repository. Before publishing a build, run:

```powershell
.\run.ps1 -ValidateRelease
```

This fails if Paddle/RapidOCR runtime packages or any of the three unique recognition model directories are absent. Run this validation inside the same packaged environment used by the executable.

## Localization

English UI copy lives in `src/vsparser/locales/en.json`. Every entry contains a
`translation` and a translator-facing `description`. To add a language, copy that
file to the matching locale name (for example `de.json` or `de_AT.json`) and
translate only the `translation` values. Keep source keys and named placeholders
such as `{count}` unchanged.

The app uses the operating-system locale by default. Set `VSPARSER_LANGUAGE` to
preview a specific catalog, for example `$env:VSPARSER_LANGUAGE = "de"` in
PowerShell. Region-specific catalogs fall back to the base language and then to
English.

## Current tuning and extension points

The pipeline uses resolution-relative coordinates and OCR header/color anchors, so it is not tied to one iPhone resolution. Portrait recordings with the same ranking layout are expected to work best.

- Frame cadence and blur/duplicate thresholds: `src/vsparser/video.py`
- Ranking-panel detection: `src/vsparser/layout.py`
- OCR engine adapter: `src/vsparser/ocr.py`
- Row parsing and normalization: `src/vsparser/parser.py`
- Cross-frame deduplication/conflicts: `src/vsparser/merge.py`

For a command-line run:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -c "from pathlib import Path; from vsparser.pipeline import process_video; process_video(Path('recording.mp4'), Path('output'))"
```

For a labeled OCR benchmark, create a UTF-8 JSON array whose rows contain `image`, `expected`, and optionally a `roster` array, then run:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe benchmark_multilingual.py benchmarks\manifest.json
```

The report separates exact raw name accuracy from roster-corrected accuracy. Existing saved frames are useful regression inputs, but a multilingual accuracy claim requires representative labeled frames for each language.
