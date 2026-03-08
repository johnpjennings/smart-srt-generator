# smart-srt-generator

Smart SRT Generator (`smart-srt-generator`) is a locally hosted browser app allowing the user to generate automatic SRT transcriptions from uploaded MP3 files via `whisper-timestamped`.

An optional textbox allows the user to paste in a manually reviewed transcription or script that will be used to automatically correct any transcription errors from `whisper-timestamped`.

Subtitles can be split by inserting the cursor at the desired point and clicking "Split." They can be merged by selecting the text of two adjacent subtitles and clicking "Merge." Both functions update the SRT timings automatically.

Words, grammar, or punctuation can be edited in the text box as well.

When done, click "Download SRT" for the final file.

`whisper-timestamped` is installed as a dependency via pip (it is not vendored in this repo).

## Requirements

Install `ffmpeg` first (one-time):

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt-get update && sudo apt-get install -y ffmpeg

# Windows (PowerShell)
winget install Gyan.FFmpeg
```

## Install (one command per OS)

```bash
# macOS
git clone https://github.com/johnpjennings/smart-srt-generator.git && cd smart-srt-generator && python3 -m venv .venv && source .venv/bin/activate && pip install -U pip && pip install -r requirements.txt
```

```bash
# Ubuntu / Debian
git clone https://github.com/johnpjennings/smart-srt-generator.git && cd smart-srt-generator && python3 -m venv .venv && source .venv/bin/activate && pip install -U pip && pip install -r requirements.txt
```

```powershell
# Windows PowerShell
git clone https://github.com/johnpjennings/smart-srt-generator.git; cd smart-srt-generator; py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1; python -m pip install -U pip; pip install -r requirements.txt
```

## Run

```bash
uvicorn app:app --host 127.0.0.1 --port 7860 --reload
```

Open: `http://127.0.0.1:7860`
