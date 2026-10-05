function formatRuntime(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${r}s`;
  return `${r}s`;
}

function setStatus(status) {
  const dot = document.getElementById("status-dot");
  const text = document.getElementById("status-text");
  dot.className = "dot";
  const label = (status || "unknown").toUpperCase();
  text.textContent = label;
  if (status === "broadcasting") dot.classList.add("on");
  else if (status === "fallback" || status === "recovering" || status === "starting")
    dot.classList.add("warn");
  else dot.classList.add("off");
}

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    document.getElementById("station-name").textContent = data.station_name || "Tiny Station";
    document.title = data.station_name || "Tiny Station";
    setStatus(data.status);
    document.getElementById("programme").textContent = data.programme || "—";
    document.getElementById("now").textContent = data.now
      ? `${data.now}${data.now_kind ? ` (${data.now_kind})` : ""}`
      : "—";
    document.getElementById("next").textContent = data.next
      ? `${data.next}${data.next_kind ? ` (${data.next_kind})` : ""}`
      : "—";
    document.getElementById("runtime").textContent = formatRuntime(data.uptime_seconds);
    document.getElementById("stream-target").textContent = data.stream_target
      ? `Output · ${data.stream_target}`
      : "";
    document.getElementById("log").textContent = (data.recent_log || []).slice(-30).join("\n");
  } catch (err) {
    setStatus("error");
    document.getElementById("now").textContent = String(err);
  }
}

async function refreshMedia() {
  try {
    const res = await fetch("/api/media");
    const data = await res.json();
    const root = document.getElementById("media-list");
    if (!data.assets?.length) {
      root.textContent = "No media yet — drop files into /media/";
      return;
    }
    root.innerHTML = data.assets
      .map((a) => {
        const name = a.path.split("/").slice(-2).join("/");
        return `<div class="row"><span class="cat">${a.category}</span><span>${name}</span></div>`;
      })
      .join("");
  } catch (err) {
    document.getElementById("media-list").textContent = String(err);
  }
}

async function uploadFiles(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const category = form.category.value;
  const files = form.file.files;
  const msg = document.getElementById("upload-msg");
  msg.hidden = false;
  msg.textContent = "Uploading…";
  try {
    for (const file of files) {
      const body = new FormData();
      body.append("category", category);
      body.append("file", file);
      const res = await fetch("/api/upload", { method: "POST", body });
      if (!res.ok) throw new Error(await res.text());
    }
    msg.textContent = `Uploaded ${files.length} file(s).`;
    form.reset();
    refreshMedia();
  } catch (err) {
    msg.textContent = `Upload failed: ${err}`;
  }
}

document.getElementById("upload-form").addEventListener("submit", uploadFiles);
refreshStatus();
refreshMedia();
setInterval(refreshStatus, 2000);
setInterval(refreshMedia, 15000);
