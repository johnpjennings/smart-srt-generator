const mp3Form = document.getElementById("mp3-form");
const scriptForm = document.getElementById("script-form");
const statusEl = document.getElementById("status");
const srtOutputEl = document.getElementById("srt-output");
const uploadBtn = document.getElementById("upload-btn");
const splitBtn = document.getElementById("split-btn");
const mergeBtn = document.getElementById("merge-btn");
const downloadSrtBtn = document.getElementById("download-srt-btn");
const progressBarEl = document.getElementById("progress-bar");
const progressLabelEl = document.getElementById("progress-label");
let lastCompletedJobId = null;
let isApplyingManual = false;

function setStatus(msg) {
  statusEl.textContent = msg;
}

function setProgress(percent) {
  const safe = Math.max(0, Math.min(100, Number(percent || 0)));
  progressBarEl.style.width = `${safe}%`;
  progressLabelEl.textContent = `${Math.round(safe)}%`;
}

async function pollJob(jobId) {
  while (true) {
    const res = await fetch(`/api/progress/${jobId}`);
    if (!res.ok) {
      throw new Error(`Progress failed (${res.status})`);
    }
    const job = await res.json();
    setProgress(job.progress || 0);

    if (job.status === "done") {
      return job.result;
    }
    if (job.status === "error") {
      throw new Error(job.error || "Transcription failed");
    }
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
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
  setProgress(0);
  setStatus("Queued...");
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
    setStatus("Done");
    setProgress(100);
  } catch (err) {
    setStatus("Error");
    console.error("Transcription error:", err);
    srtOutputEl.value = "";
    setProgress(0);
  } finally {
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
