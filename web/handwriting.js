// My handwriting: upload pages, type transcriptions, fix labels, render text. No machine control here.
(() => {
  const $ = (id) => document.getElementById(id);
  let current = null; // sample detail: {sample, lines, glyphs}
  let pageScale = 1;

  async function api(path, body) {
    const res = await fetch(path, body === undefined
      ? {}
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  const toBase64 = (file) => new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1]);
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });

  async function loadSamples() {
    const { samples } = await api("/api/handwriting/samples");
    const box = $("samples");
    box.innerHTML = "";
    if (!samples.length) box.innerHTML = '<span class="muted">None yet.</span>';
    for (const s of samples.slice().reverse()) {
      const b = document.createElement("button");
      b.textContent = `#${s.id} (${s.lines} lines, ${s.glyphs} letters)`;
      b.className = current && current.sample.id === s.id ? "on" : "";
      b.onclick = () => openSample(s.id);
      box.appendChild(b);
    }
  }

  async function openSample(id) {
    current = await api(`/api/handwriting/sample/${id}`);
    $("labelSection").hidden = false;
    const img = $("page");
    img.onload = drawOverlay;
    img.src = `/api/handwriting/sample/${id}/page.png?${Date.now()}`;
    renderLines();
    loadSamples();
  }

  function drawOverlay() {
    const img = $("page"), cv = $("overlay");
    pageScale = img.clientWidth / current.sample.width;
    cv.width = img.clientWidth;
    cv.height = img.clientHeight;
    const ctx = cv.getContext("2d");
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.lineWidth = 1.5;
    for (const g of current.glyphs) {
      const [x, y, w, h] = g.bbox;
      ctx.strokeStyle = g.char ? (g.source === "manual" ? "#2f855a" : "#2b6cb0") : "#d69e2e";
      ctx.strokeRect(x * pageScale, y * pageScale, w * pageScale, h * pageScale);
      if (g.char) {
        ctx.fillStyle = ctx.strokeStyle;
        ctx.font = "bold 13px system-ui";
        ctx.fillText(g.char, x * pageScale, y * pageScale - 3);
      }
    }
  }

  function renderLines() {
    const box = $("lines");
    box.innerHTML = "";
    if (!current.lines.length) {
      box.innerHTML = '<p class="muted">No text lines found on this photo. Try a flatter, sharper photo.</p>';
      return;
    }
    for (const line of current.lines) {
      const glyphs = current.glyphs.filter((g) => g.line_id === line.id);
      const row = document.createElement("div");
      row.className = "lineRow";
      const input = document.createElement("input");
      input.type = "text";
      input.value = line.text;
      input.placeholder = "what this line says";
      input.style.width = "100%";
      const save = document.createElement("button");
      save.textContent = "Save";
      save.onclick = async () => {
        try {
          await api("/api/handwriting/transcribe", { line: line.id, text: input.value });
          await openSample(current.sample.id);
        } catch (e) { alert(e.message); }
      };
      const labels = document.createElement("div");
      labels.className = "labels";
      labels.textContent = glyphs.map((g) => g.char || "_").join(" ");
      row.append(input, save, labels);
      box.appendChild(row);
    }
  }

  // Click a box on the photo to set its letter.
  $("overlay").addEventListener("click", async (ev) => {
    if (!current) return;
    const rect = $("overlay").getBoundingClientRect();
    const px = (ev.clientX - rect.left) / pageScale, py = (ev.clientY - rect.top) / pageScale;
    const hit = current.glyphs.find(({ bbox: [x, y, w, h] }) => px >= x && px <= x + w && py >= y && py <= y + h);
    if (!hit) return;
    const ch = prompt(`Letter for this box (empty clears it):`, hit.char || "");
    if (ch === null) return;
    try {
      await api("/api/handwriting/label", { glyph: hit.id, char: ch.trim().slice(0, 1) });
      await openSample(current.sample.id);
    } catch (e) { alert(e.message); }
  });

  $("file").addEventListener("change", async (ev) => {
    const files = [...ev.target.files];
    let last = null;
    for (const [i, f] of files.entries()) {
      $("uploadStatus").textContent = `Uploading ${i + 1} of ${files.length}...`;
      try {
        last = await api("/api/handwriting/upload", { filename: f.name, data: await toBase64(f) });
      } catch (e) {
        alert(`${f.name}: ${e.message}`);
      }
    }
    $("uploadStatus").textContent = "Done.";
    ev.target.value = "";
    await loadSamples();
    if (last) openSample(last.id);
  });

  $("ocrBtn").onclick = async () => {
    if (!current) return;
    $("ocrOut").textContent = "Reading...";
    try {
      const r = await api("/api/handwriting/read", { id: current.sample.id });
      $("ocrOut").textContent = `Backend: ${r.backend}`;
      $("ocrText").textContent = r.text;
    } catch (e) {
      $("ocrOut").textContent = e.message;
      $("ocrText").textContent = "";
    }
  };

  $("renderBtn").onclick = async () => {
    $("renderStatus").textContent = "";
    try {
      const r = await api("/api/handwriting/render", {
        text: $("renderText").value,
        size_mm: parseFloat($("size").value),
      });
      $("svgOut").innerHTML = r.svg;
      $("renderStatus").textContent = `Saved ${r.file}`;
    } catch (e) { $("renderStatus").textContent = e.message; }
  };

  window.addEventListener("resize", () => current && drawOverlay());
  loadSamples().catch(() => {});
})();
