# Smart SRT Generator

Smart SRT Generator (`smart-srt-generator`) is a locally hosted browser app allowing the user to generate automatic SRT transcriptions from uploaded MP3 files via `whisper-timestamped`.

An optional textbox allows the user to paste in a manually reviewed transcription or script that will be used to automatically correct any transcription errors from `whisper-timestamped`.

Subtitles can be split by inserting the cursor at the desired point and clicking "Split." They can be merged by selecting the text of two adjacent subtitles and clicking "Merge." Both functions update the SRT timings automatically.

Words, grammar, or punctuation can be edited in the text box as well.

When done, click "Download SRT" for the final file.



## What it does

- Transcribes uploaded MP3 audio locally (no third-party transcription API required).
- Generates SRT output with adjustable subtitle constraints:
  - max characters per subtitle
  - max seconds per subtitle
- Accepts a submitted script and algorithmically aligns it to the timed output to correct wording, capitalization, and punctuation.
- Supports manual subtitle editing in-place with timing recalculation:
  - `Split` inserts a subtitle break at cursor position and retimes subtitles.
  - `Merge` combines highlighted subtitle text into a new subtitle and retimes subtitles.
- Lets you download the final edited `.srt` file.

`whisper-timestamped` is installed as a dependency via `pip` (it is not vendored in this repository).

## Requirements

`whisper-timestamped` is installed as a dependency via pip (it is not vendored in this repo).

Install `ffmpeg` first (one-time):

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt-get update && sudo apt-get install -y ffmpeg

# Windows (PowerShell)
winget install Gyan.FFmpeg
```

## Install + Run (one command per OS)

```bash
# macOS
git clone https://github.com/johnpjennings/smart-srt-generator.git && cd smart-srt-generator && python3 -m venv .venv && source .venv/bin/activate && pip install -U pip && pip install -r requirements.txt && uvicorn app:app --host 127.0.0.1 --port 7860 --reload
```

```bash
# Ubuntu / Debian
git clone https://github.com/johnpjennings/smart-srt-generator.git && cd smart-srt-generator && python3 -m venv .venv && source .venv/bin/activate && pip install -U pip && pip install -r requirements.txt && uvicorn app:app --host 127.0.0.1 --port 7860 --reload
```

```powershell
# Windows PowerShell
git clone https://github.com/johnpjennings/smart-srt-generator.git; cd smart-srt-generator; py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1; python -m pip install -U pip; pip install -r requirements.txt; uvicorn app:app --host 127.0.0.1 --port 7860 --reload
```

Open: `http://127.0.0.1:7860`
