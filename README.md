# Last War VS Ranking Parser

Local Windows tool for extracting alliance-member names, VS points, and visible ranks from an iPhone `.mp4` screen recording. Frames, OCR output, corrections, and exports remain on the PC.

## Privacy and scope

- No recording or result is uploaded by the application.
- OCR runs locally with RapidOCR/ONNX Runtime.
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

The first run creates `.venv`, installs dependencies, and opens a native desktop window. Later runs do not require internet access.

## Use

1. Drag each `.mp4` onto its **Day 1** through **Day 6** or **Weekly Overall** box. You can also click a box to choose a video.
2. Optionally select **Alliance Members**, paste a Google Sheets column with one teammate per line, and save it. Reopen the editor later to add, rename, or remove members.
3. Videos process one at a time in drop order. Drop a new video on any completed box to replace and reprocess that slot.
4. Review each result in its matching table tab. Select rows and press `Ctrl+C`, or use **Copy Selected** / **Copy All**.
5. Use **Open Output Folder** to access the selected tab's full CSV and Excel exports.

The previous browser-based review interface remains available with `.venv\Scripts\python.exe -m streamlit run app.py`.

Raw automatic outputs are also saved as `observations.json`, `results.json`, `vs_rankings.csv`, and `vs_rankings.xlsx` in the output folder. Selected source frames are kept under `frames`.

The optional local roster defaults to `data/member_roster.json`. It retains corrected Unicode names and the OCR spellings seen for them. This helps symbols and stylized names resolve consistently in later recordings; uncertain matches remain review flags.
After the VS observations have been merged, recognized names are corrected against this list. Unmatched OCR names are assigned to the most similar alliance member when there is a meaningful resemblance. Only names with no sufficiently similar member are highlighted red; saved members still absent after this correction are added at the bottom with zero points and highlighted yellow.

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
