import json
import math
import re
import shutil
import threading
import tempfile
import time
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
import whisper_timestamped as whisper

app = FastAPI(title="smart-srt-generator")

MODEL_CACHE: Dict[Tuple[str, str], object] = {}
MODEL_LOCK = threading.Lock()
TRANSCRIBE_LOCK = threading.Lock()
JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
DEFAULT_SRT_MAX_LINE_WIDTH = 50
DEFAULT_SRT_MAX_SEGMENT_SECONDS = 4.0


@app.on_event("startup")
def ensure_ffmpeg_installed():
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg is required but was not found on PATH. Install ffmpeg and restart the server."
        )


def _get_model(model_name: str = "small", device: str = "cpu"):
    key = (model_name, device)
    with MODEL_LOCK:
        if key not in MODEL_CACHE:
            MODEL_CACHE[key] = whisper.load_model(model_name, device=device)
        return MODEL_CACHE[key]


def _set_job(job_id: str, **updates):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(updates)


def _update_job_progress(job_id: str, current: float, total: float):
    if not total:
        return
    percent = int(max(0, min(100, round((current / total) * 100))))
    # Avoid showing 100% before the final result payload is ready.
    percent = min(percent, 99)
    _set_job(job_id, progress=percent, updated_at=time.time())


def _segment_text_from_words(words) -> str:
    text = ""
    for w in words:
        token = w.get("text", "")
        if not token:
            continue
        if not text:
            text = token.strip()
        elif token.startswith(" "):
            text += token
        else:
            text += " " + token
    return " ".join(text.split())


def _normalize_token(token: str) -> str:
    token = (token or "").strip().lower()
    token = re.sub(r"^[^\w]+|[^\w]+$", "", token)
    return token


def _join_tokens(tokens) -> str:
    text = " ".join(t for t in tokens if t)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s+([)\]\}])", r"\1", text)
    text = re.sub(r"([(\[\{])\s+", r"\1", text)
    return text.strip()


def _is_tiny_chunk(words, max_seconds: float) -> bool:
    if not words:
        return True
    duration = float(words[-1].get("end", 0.0)) - float(words[0].get("start", 0.0))
    return (len(words) <= 1) or (duration < max(0.8, max_seconds * 0.28))


def _chunk_duration(words) -> float:
    if not words:
        return 0.0
    return float(words[-1].get("end", 0.0)) - float(words[0].get("start", 0.0))


def _split_segment_by_words(segment: dict, max_seconds: float, max_chars: int):
    words = segment.get("words") or []
    if not words:
        return None

    chunks = []
    chunk = []
    chunk_start = None

    for w in words:
        w_start = float(w.get("start", 0.0))
        w_end = float(w.get("end", w_start))
        if chunk_start is None:
            chunk_start = w_start
        if chunk:
            candidate = chunk + [w]
            candidate_text = _segment_text_from_words(candidate)
            candidate_duration = w_end - chunk_start
            should_split = (candidate_duration > max_seconds) or (len(candidate_text) > max_chars)
        else:
            should_split = False
        if should_split:
            chunks.append(chunk)
            chunk = [w]
            chunk_start = w_start
        else:
            chunk.append(w)

    if chunk:
        chunks.append(chunk)

    # Rebalance tiny trailing chunks (e.g., single-word "okay.") by shifting words
    # from the previous chunk so both chunks are more natural.
    while len(chunks) >= 2 and _is_tiny_chunk(chunks[-1], max_seconds=max_seconds):
        prev = chunks[-2]
        tail = chunks[-1]
        if len(prev) <= 1:
            break
        moved = prev.pop()
        tail.insert(0, moved)

        # Stop once tail is not tiny and both chunk constraints are reasonably respected.
        tail_text_len = len(_segment_text_from_words(tail))
        prev_duration_ok = _chunk_duration(prev) <= (max_seconds + 1e-6)
        tail_duration_ok = _chunk_duration(tail) <= (max_seconds + 1e-6)
        if (
            not _is_tiny_chunk(tail, max_seconds=max_seconds)
            and tail_text_len <= max_chars
            and prev_duration_ok
            and tail_duration_ok
        ):
            break

    out = []
    for c in chunks:
        text = _segment_text_from_words(c)
        out.append({"start": float(c[0]["start"]), "end": float(c[-1]["end"]), "text": text, "_words": c})
    return out


def _split_segment_fallback(segment: dict, max_seconds: float):
    start = float(segment.get("start", 0.0))
    end = float(segment.get("end", start))
    text = (segment.get("text") or "").strip()
    duration = max(0.0, end - start)
    if duration <= max_seconds or not text:
        return [segment]

    chunks_n = max(1, math.ceil(duration / max_seconds))
    words = text.split()
    if not words:
        return [segment]

    per_chunk = math.ceil(len(words) / chunks_n)
    out = []
    for i in range(chunks_n):
        subset = words[i * per_chunk : (i + 1) * per_chunk]
        if not subset:
            continue
        c_start = start + (duration * i / chunks_n)
        c_end = start + (duration * (i + 1) / chunks_n)
        out.append({"start": c_start, "end": c_end, "text": " ".join(subset), "_words": []})
    return out


def _split_segments_for_srt(segments, max_seconds: float, max_chars: int):
    out = []
    for seg in segments:
        seg_start = float(seg.get("start", 0.0))
        seg_end = float(seg.get("end", seg_start))
        seg_text = " ".join(((seg.get("text") or "").strip()).split())
        if (seg_end - seg_start) <= max_seconds and len(seg_text) <= max_chars:
            out.append({"start": seg_start, "end": seg_end, "text": seg_text, "_words": seg.get("words") or []})
            continue

        from_words = _split_segment_by_words(seg, max_seconds=max_seconds, max_chars=max_chars)
        if from_words is not None:
            out.extend(from_words)
        else:
            out.extend(_split_segment_fallback(seg, max_seconds=max_seconds))
    return out


def _apply_script_to_segments(segments, script_text: str):
    script_tokens = [t for t in re.split(r"\s+", (script_text or "").strip()) if t]
    if not script_tokens:
        return segments

    asr_words = []
    seg_ranges = []
    cursor = 0
    for seg in segments:
        words = seg.get("_words") or []
        asr_words.extend(words)
        seg_ranges.append((cursor, cursor + len(words)))
        cursor += len(words)
    if not asr_words:
        return segments

    asr_tokens = [_segment_text_from_words([w]) for w in asr_words]
    asr_norm = [_normalize_token(t) for t in asr_tokens]
    script_norm = [_normalize_token(t) for t in script_tokens]

    n_asr = len(asr_norm)
    n_script = len(script_norm)
    # Boundary map: boundary[i] gives script-token boundary index corresponding
    # to the boundary before ASR token i (0..n_asr), monotonic from 0..n_script.
    boundaries = [0] * (n_asr + 1)
    a_pos = 0
    s_pos = 0

    sm = SequenceMatcher(a=asr_norm, b=script_norm, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        # Keep pointers synchronized to opcode positions.
        a_pos = i1
        s_pos = j1
        a_len = i2 - i1
        b_len = j2 - j1

        if a_len == 0 and b_len > 0:
            # Pure insertion on script side: it belongs at the current boundary.
            boundaries[a_pos] = max(boundaries[a_pos], j2)
            continue

        if a_len > 0:
            # Distribute script span over ASR span (works for equal/replace/delete).
            for step in range(1, a_len + 1):
                mapped = j1 + round(step * b_len / a_len)
                idx = i1 + step
                boundaries[idx] = max(boundaries[idx], mapped)

    boundaries[0] = 0
    boundaries[n_asr] = n_script
    # Enforce monotonicity and valid range.
    for i in range(1, n_asr + 1):
        boundaries[i] = max(boundaries[i], boundaries[i - 1])
        boundaries[i] = min(boundaries[i], n_script)

    out = []
    for seg, (start_i, end_i) in zip(segments, seg_ranges):
        if end_i <= start_i:
            out.append(seg)
            continue

        s_start = boundaries[start_i]
        s_end = boundaries[end_i]
        if s_end <= s_start:
            new_text = (seg.get("text") or "").strip()
        else:
            new_text = _join_tokens(script_tokens[s_start:s_end])
            if not new_text:
                new_text = (seg.get("text") or "").strip()
        out.append({**seg, "text": new_text})
    return out


def _format_srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    ms = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _build_subtitle_entries(result: dict, max_line_width: int, max_segment_seconds: float, script_text: str = ""):
    segments = _split_segments_for_srt(
        result.get("segments", []),
        max_seconds=max_segment_seconds,
        max_chars=max_line_width,
    )
    if script_text.strip():
        segments = _apply_script_to_segments(segments, script_text=script_text)
    entries = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        if end <= start:
            end = start + 0.2
        entries.append({"start": start, "end": end, "text": text})
    return entries


def _render_srt(entries) -> str:
    lines = []
    for i, e in enumerate(entries, start=1):
        lines.append(str(i))
        lines.append(f"{_format_srt_timestamp(e['start'])} --> {_format_srt_timestamp(e['end'])}")
        lines.append(e["text"])
        lines.append("")
    return "\n".join(lines)


def _build_srt_text(result: dict, max_line_width: int, max_segment_seconds: float, script_text: str = "") -> str:
    entries = _build_subtitle_entries(
        result=result,
        max_line_width=max_line_width,
        max_segment_seconds=max_segment_seconds,
        script_text=script_text,
    )
    return _render_srt(entries)


def _flatten_timed_words(result: dict) -> List[dict]:
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []) or []:
            token = _segment_text_from_words([w]).strip()
            norm = _normalize_token(token)
            if not token:
                continue
            words.append(
                {
                    "text": token,
                    "norm": norm,
                    "start": float(w.get("start", seg.get("start", 0.0))),
                    "end": float(w.get("end", seg.get("end", 0.0))),
                }
            )
    return words


def _parse_edited_srt_blocks(edited_srt: str) -> List[str]:
    raw_blocks = [b.strip() for b in re.split(r"\n\s*\n+", (edited_srt or "").strip()) if b.strip()]
    texts: List[str] = []
    for block in raw_blocks:
        lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        if re.fullmatch(r"\d+", lines[0].strip()):
            lines = lines[1:]
        if lines and "-->" in lines[0]:
            lines = lines[1:]
        text = " ".join(lines).strip()
        if text:
            texts.append(text)
    return texts


def _retime_manual_srt(result: dict, edited_srt: str) -> str:
    block_texts = _parse_edited_srt_blocks(edited_srt)
    if not block_texts:
        return ""

    timed_words = _flatten_timed_words(result)
    if not timed_words:
        # No word-level anchors; fall back to index/timing cleanup only.
        entries = []
        step = 0.4
        t = 0.0
        for text in block_texts:
            entries.append({"start": t, "end": t + step, "text": text})
            t += step
        return _render_srt(entries)

    norms = [w["norm"] for w in timed_words]
    cursor = 0
    prev_end = float(timed_words[0]["start"])
    entries = []

    for block_text in block_texts:
        tokens = [t for t in re.split(r"\s+", block_text) if t]
        token_norms = [_normalize_token(t) for t in tokens]
        matched = []

        for tn in token_norms:
            if not tn:
                continue
            found = None
            for i in range(cursor, len(norms)):
                if norms[i] == tn:
                    found = i
                    break
            if found is not None:
                matched.append(found)
                cursor = found + 1

        if matched:
            start = timed_words[matched[0]]["start"]
            end = timed_words[matched[-1]]["end"]
            prev_end = end
        else:
            # Entirely unmatched block: place it right after previous cue.
            start = prev_end
            end = start + 0.35
            prev_end = end

        if end <= start:
            end = start + 0.2
        entries.append({"start": float(start), "end": float(end), "text": block_text.strip()})

    return _render_srt(entries)


def _run_transcription_job(job_id: str, path: Path, srt_max_chars: int, srt_max_seconds: float, script_text: str):
    try:
        with TRANSCRIBE_LOCK:
            model = _get_model(model_name="small", device="cpu")
            import whisper.transcribe as whisper_transcribe_module

            original_tqdm = getattr(whisper_transcribe_module, "tqdm", None)

            def tracked_tqdm(*args, **kwargs):
                base = original_tqdm(*args, **kwargs)
                total = getattr(base, "total", None)
                n = getattr(base, "n", 0)
                if total:
                    _update_job_progress(job_id, n, total)

                original_update = base.update

                def update(n_steps=1):
                    out = original_update(n_steps)
                    _update_job_progress(job_id, getattr(base, "n", 0), total)
                    return out

                base.update = update
                return base

            if original_tqdm is not None:
                whisper_transcribe_module.tqdm = tracked_tqdm

            _set_job(job_id, status="running", progress=1)
            result = whisper.transcribe(model, str(path), language=None, task="transcribe")

        if srt_max_chars < 10:
            srt_max_chars = 10
        if srt_max_seconds < 0.5:
            srt_max_seconds = 0.5

        payload = {
            "text": result.get("text", ""),
            "srt_text": _build_srt_text(
                result,
                max_line_width=srt_max_chars,
                max_segment_seconds=srt_max_seconds,
                script_text=script_text,
            ),
            "result": result,
            "result_pretty": json.dumps(result, indent=2, ensure_ascii=False),
        }
        _set_job(job_id, status="done", progress=100, result=payload, updated_at=time.time())
    except Exception as exc:
        _set_job(job_id, status="error", error=str(exc), updated_at=time.time())
    finally:
        try:
            import whisper.transcribe as whisper_transcribe_module
            if "original_tqdm" in locals() and original_tqdm is not None:
                whisper_transcribe_module.tqdm = original_tqdm
        except Exception:
            pass
        path.unlink(missing_ok=True)


@app.post("/api/transcribe")
async def transcribe(
    audio_file: UploadFile = File(...),
    srt_max_chars: int = Form(DEFAULT_SRT_MAX_LINE_WIDTH),
    srt_max_seconds: float = Form(DEFAULT_SRT_MAX_SEGMENT_SECONDS),
    script_text: str = Form(""),
):
    if not audio_file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    if Path(audio_file.filename).suffix.lower() != ".mp3":
        raise HTTPException(status_code=400, detail="Please upload an MP3 file")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
        tmp.write(await audio_file.read())
        path = Path(tmp.name)

    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "queued",
            "progress": 0,
            "error": None,
            "result": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }

    thread = threading.Thread(
        target=_run_transcription_job,
        kwargs={
            "job_id": job_id,
            "path": path,
            "srt_max_chars": srt_max_chars,
            "srt_max_seconds": srt_max_seconds,
            "script_text": script_text,
        },
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id, "status": "queued", "progress": 0}


@app.get("/api/progress/{job_id}")
async def get_progress(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/rematch")
async def rematch_script(
    job_id: str = Form(...),
    script_text: str = Form(""),
    srt_max_chars: int = Form(DEFAULT_SRT_MAX_LINE_WIDTH),
    srt_max_seconds: float = Form(DEFAULT_SRT_MAX_SEGMENT_SECONDS),
):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "done":
        raise HTTPException(status_code=400, detail="Job is not completed yet")

    payload = job.get("result") or {}
    raw_result = payload.get("result")
    if not raw_result:
        raise HTTPException(status_code=400, detail="No transcription result available for rematch")

    if srt_max_chars < 10:
        srt_max_chars = 10
    if srt_max_seconds < 0.5:
        srt_max_seconds = 0.5

    new_payload = {
        **payload,
        "srt_text": _build_srt_text(
            raw_result,
            max_line_width=srt_max_chars,
            max_segment_seconds=srt_max_seconds,
            script_text=script_text,
        ),
    }
    _set_job(job_id, result=new_payload, updated_at=time.time())
    return {"job_id": job_id, "status": "done", "result": new_payload}


@app.post("/api/manual_edit")
async def manual_edit_srt(
    job_id: str = Form(...),
    edited_srt: str = Form(""),
):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "done":
        raise HTTPException(status_code=400, detail="Job is not completed yet")

    payload = job.get("result") or {}
    raw_result = payload.get("result")
    if not raw_result:
        raise HTTPException(status_code=400, detail="No transcription result available for manual edit")

    srt_text = _retime_manual_srt(raw_result, edited_srt=edited_srt)
    new_payload = {**payload, "srt_text": srt_text}
    _set_job(job_id, result=new_payload, updated_at=time.time())
    return {"job_id": job_id, "status": "done", "result": new_payload}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
