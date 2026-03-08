# smart-srt-generator

Smart SRT Generator is a locally hosted browser app allowing the user to generate automatic SRT transcriptions from uploaded MP3 files via `whisper-timestamped`.

An optional textbox allows the user to paste in a manually reviewed transcription or script that will be used to automatically correct any transcription errors from `whisper-timestamped`.

Subtitles can be split by inserting the cursor at the desired point and clicking "Split." They can be merged by selecting the text of two adjacent subtitles and clicking "Merge." Both functions update the SRT timings automatically.

Words, grammar, or punctuation can be edited in the text box as well.

When done, click "Download SRT" for the final file.

`whisper-timestamped` is installed as a dependency via `pip` (it is **not** vendored in this repo).

## Requirements

- Python 3.9+
- `ffmpeg` on PATH

Install `ffmpeg`:

```bash
# macOS (Homebrew)
brew install ffmpeg

# Ubuntu / Debian
sudo apt-get update && sudo apt-get install -y ffmpeg

# Windows (winget)
winget install Gyan.FFmpeg

# Windows (Chocolatey)
choco install ffmpeg
```

## Install

Create virtual environment (all platforms):

```bash
python3 -m venv .venv
```

Activate virtual environment:

```bash
# macOS / Linux
source .venv/bin/activate
```

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```cmd
# Windows CMD
.venv\Scripts\activate.bat
```

Install dependencies:

```bash
pip install -U pip
pip install -r requirements.txt
```

## Run

```bash
# macOS / Linux / WSL
uvicorn app:app --host 127.0.0.1 --port 7860 --reload
```

Open: `http://127.0.0.1:7860` in your browser.

On Windows, run the same `uvicorn` command in PowerShell/CMD after activating `.venv`.

## Dependency model

This repository includes only the app code. `whisper-timestamped` is pulled from PyPI through `requirements.txt` during install.
