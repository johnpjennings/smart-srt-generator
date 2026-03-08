const mp3Form = document.getElementById("mp3-form");
const scriptForm = document.getElementById("script-form");
const statusEl = document.getElementById("status");
const loadingIndicatorEl = document.getElementById("loading-indicator");
const srtOutputEl = document.getElementById("srt-output");
const uploadBtn = document.getElementById("upload-btn");
const splitBtn = document.getElementById("split-btn");
const mergeBtn = document.getElementById("merge-btn");
const removeGapsBtn = document.getElementById("remove-gaps-btn");
const downloadSrtBtn = document.getElementById("download-srt-btn");
let lastCompletedJobId = null;
let isApplyingManual = false;

function setStatus(msg) {
  statusEl.textContent = msg;
}

function setLoading(isLoading) {
  if (loadingIndicatorEl) {
    loadingIndicatorEl.classList.toggle("active", !!isLoading);
  }
}

function removeSrtGaps(srtText) {
  const normalized = (srtText || "").replace(/\r\n/g, "\n").trim();
  if (!normalized) {
    return { updatedText: "", adjustedCount: 0, cueCount: 0 };
  }

  const rawBlocks = normalized.split(/\n{2,}/).filter(Boolean);
  const cues = [];

  for (const block of rawBlocks) {
    const lines = block.split("\n");
    const timeLineIndex = lines.findIndex((ln) => ln.includes("-->"));
    if (timeLineIndex < 0) continue;

    const timeLine = lines[timeLineIndex].trim();
    const match = timeLine.match(/^(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})(.*)$/);
    if (!match) continue;

    const [, start, end, suffix] = match;
    const textLines = lines.slice(timeLineIndex + 1);
    cues.push({ start, end, suffix: suffix || "", textLines });
  }

  if (cues.length < 2) {
    return { updatedText: normalized, adjustedCount: 0, cueCount: cues.length };
  }

  let adjustedCount = 0;
  for (let i = 0; i < cues.length - 1; i += 1) {
    const nextStart = cues[i + 1].start;
    if (cues[i].end !== nextStart) {
      cues[i].end = nextStart;
      adjustedCount += 1;
    }
  }

  const rebuilt = cues
    .map((cue, idx) => {
      const textBody = cue.textLines.length ? `\n${cue.textLines.join("\n")}` : "";
      return `${idx + 1}\n${cue.start} --> ${cue.end}${cue.suffix}${textBody}`;
    })
    .join("\n\n");

  return { updatedText: rebuilt, adjustedCount, cueCount: cues.length };
}

async function pollJob(jobId) {
  return new Promise((resolve, reject) => {
    const stream = new EventSource(`/api/progress_stream/${jobId}`);

    stream.addEventListener("progress", (evt) => {
      const job = JSON.parse(evt.data);
      if (job.status === "queued") {
        setStatus("Queued...");
      } else if (job.status === "running") {
        setStatus("Transcription in process...");
      }

      if (job.status === "done") {
        setStatus("Done");
        stream.close();
        resolve(job.result);
      } else if (job.status === "error") {
        setStatus("Error");
        stream.close();
        reject(new Error(job.error || "Transcription failed"));
      }
    });

    stream.addEventListener("error", () => {
      setStatus("Progress stream disconnected");
      stream.close();
      reject(new Error("Progress stream disconnected"));
    });
  });
}

mp3Form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = document.getElementById("audio_file").files[0];
  if (!file) return;

  const data = new FormData();
  data.append("audio_file", file);
  data.append("srt_max_chars", document.getElementById("srt_max_chars").value || "50");
  data.append("srt_max_seconds", document.getElementById("srt_max_seconds").value || "4.0");
  data.append("script_text", document.getElementById("script").value || "");

  uploadBtn.disabled = true;
  setLoading(true);
  setStatus("Starting transcription...");
  srtOutputEl.value = "";

  try {
    const res = await fetch("/api/transcribe", { method: "POST", body: data });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(errText || `Failed (${res.status})`);
    }

    const startPayload = await res.json();
    setStatus("Running whisper-timestamped...");
    const payload = await pollJob(startPayload.job_id);
    lastCompletedJobId = startPayload.job_id;
    console.log("Whisper debug output:", payload.result_pretty || payload.result);
    srtOutputEl.value = payload.srt_text || "";
  } catch (err) {
    setStatus("Error");
    console.error("Transcription error:", err);
    srtOutputEl.value = "";
  } finally {
    setLoading(false);
    uploadBtn.disabled = false;
  }
});

scriptForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!lastCompletedJobId) {
    setStatus("Run a transcription first, then apply script.");
    return;
  }

  const data = new FormData();
  data.append("job_id", lastCompletedJobId);
  data.append("script_text", document.getElementById("script").value || "");
  data.append("srt_max_chars", document.getElementById("srt_max_chars").value || "50");
  data.append("srt_max_seconds", document.getElementById("srt_max_seconds").value || "4.0");

  try {
    setStatus("Submitting script to last result...");
    const res = await fetch("/api/rematch", { method: "POST", body: data });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(errText || `Failed (${res.status})`);
    }
    const payload = await res.json();
    srtOutputEl.value = payload.result?.srt_text || "";
    setStatus("Script submitted and applied.");
  } catch (err) {
    console.error("Rematch error:", err);
    setStatus(`Script apply failed: ${err.message}`);
  }
});

async function applyManualEdits() {
  if (isApplyingManual) return;
  if (!lastCompletedJobId) {
    setStatus("Run a transcription first, then apply manual edits.");
    return;
  }

  const data = new FormData();
  data.append("job_id", lastCompletedJobId);
  data.append("edited_srt", srtOutputEl.value || "");

  try {
    isApplyingManual = true;
    setStatus("Applying manual edits...");
    const res = await fetch("/api/manual_edit", { method: "POST", body: data });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(errText || `Failed (${res.status})`);
    }
    const payload = await res.json();
    srtOutputEl.value = payload.result?.srt_text || "";
    setStatus("Manual edits applied.");
  } catch (err) {
    console.error("Manual edit error:", err);
    setStatus(`Manual edit failed: ${err.message}`);
  } finally {
    isApplyingManual = false;
  }
}

splitBtn.addEventListener("click", async () => {
  if (!lastCompletedJobId) {
    setStatus("Run a transcription first, then split.");
    return;
  }
  const text = srtOutputEl.value || "";
  const pos = srtOutputEl.selectionStart || 0;
  const before = text.slice(0, pos).replace(/[ \t]+$/, "");
  const after = text.slice(pos).replace(/^[ \t]+/, "");
  srtOutputEl.value = `${before}\n\n${after}`.replace(/\n{3,}/g, "\n\n");
  await applyManualEdits();
});

mergeBtn.addEventListener("click", async () => {
  if (!lastCompletedJobId) {
    setStatus("Run a transcription first, then merge.");
    return;
  }
  const text = srtOutputEl.value || "";
  const start = srtOutputEl.selectionStart || 0;
  const end = srtOutputEl.selectionEnd || 0;
  if (end <= start) {
    setStatus("Highlight words across subtitles, then click Merge.");
    return;
  }

  const selected = text.slice(start, end);
  const cleanedSelected = selected
    .split(/\r?\n/)
    .map((ln) => ln.trim())
    .filter((ln) => ln && !/^\d+$/.test(ln) && !ln.includes("-->"))
    .join(" ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .trim();

  if (!cleanedSelected) {
    setStatus("Selection did not contain subtitle words to merge.");
    return;
  }

  const before = text.slice(0, start);
  const after = text.slice(end);
  srtOutputEl.value = `${before}\n\n${cleanedSelected}\n\n${after}`.replace(/\n{3,}/g, "\n\n");
  await applyManualEdits();
});

removeGapsBtn.addEventListener("click", () => {
  const srtText = srtOutputEl.value || "";
  if (!srtText.trim()) {
    setStatus("No SRT text to update.");
    return;
  }

  const { updatedText, adjustedCount, cueCount } = removeSrtGaps(srtText);
  srtOutputEl.value = updatedText;
  if (cueCount < 2) {
    setStatus("Need at least 2 subtitles to remove gaps.");
    return;
  }
  setStatus(`Remove Gaps applied (${adjustedCount} subtitle timings updated).`);
});

downloadSrtBtn.addEventListener("click", () => {
  const srtText = srtOutputEl.value || "";
  if (!srtText.trim()) {
    setStatus("No SRT text to download.");
    return;
  }

  const blob = new Blob([srtText], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "smart-srt-generator.srt";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  setStatus("SRT downloaded.");
});
