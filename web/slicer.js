"use strict";
// Standalone slicer page: picture -> /api/photo -> G-code preview with playback.
(() => {
  const $ = id => document.getElementById(id);
  const ROW = 18, PAD = 24, STORE_KEY = "davinchi.pendingJob";
  const canvas = $("view"), ctx = canvas.getContext("2d");
  const list = $("gcode-list"), rows = $("gcode-rows"), spacer = $("gcode-spacer");
  let raster = null, job = null, loadToken = 0;
  let step = -1, playing = false, simTime = 0, lastTs = 0;
  let view = {s: 1, tx: 0, ty: 0};

  const setStatus = message => { $("status").textContent = message; };
  const pad2 = n => String(n).padStart(2, "0");
  function fmtTime(sec) {
    const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = Math.floor(sec % 60);
    return (h ? h + ":" + pad2(m) : m) + ":" + pad2(s);
  }
  // Count of arr[0..n) values strictly below v; arr must be sorted ascending.
  function countBelow(arr, v, n = arr.length) {
    let lo = 0, hi = n;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (arr[mid] < v) lo = mid + 1; else hi = mid;
    }
    return lo;
  }

  // ---- Picture -> grayscale payload, same steps as photo.js ----
  async function loadPicture(file) {
    const token = ++loadToken;
    raster = null;
    if (!file) return;
    if (!file.type.startsWith("image/")) { setStatus("Choose an image file."); return; }
    if (file.size > 20 * 1024 * 1024) { setStatus("Choose an image smaller than 20 MB."); return; }
    const url = URL.createObjectURL(file);
    try {
      const image = new Image();
      image.src = url;
      await image.decode();
      if (token !== loadToken) return;
      const ratio = Math.min(1, 480 / Math.max(image.naturalWidth, image.naturalHeight));
      const width = Math.max(2, Math.round(image.naturalWidth * ratio));
      const height = Math.max(2, Math.round(image.naturalHeight * ratio));
      const thumb = document.createElement("canvas");
      thumb.width = width; thumb.height = height;
      const g = thumb.getContext("2d", {willReadFrequently: true});
      g.fillStyle = "white"; g.fillRect(0, 0, width, height);
      g.drawImage(image, 0, 0, width, height);
      const rgba = g.getImageData(0, 0, width, height).data, pixels = [];
      for (let i = 0; i < rgba.length; i += 4) {
        pixels.push(Math.round(.2126 * rgba[i] + .7152 * rgba[i + 1] + .0722 * rgba[i + 2]));
      }
      raster = {width, height, pixels};
      $("thumb").replaceChildren(thumb);
      $("drop-text").textContent = "Picture ready. Choose settings and press Slice.";
      setStatus("Picture loaded.");
    } catch {
      if (token === loadToken) setStatus("Could not read this image. Try a JPEG, PNG or WebP.");
    } finally { URL.revokeObjectURL(url); }
  }
  $("file").addEventListener("change", () => loadPicture($("file").files[0]));
  $("drop").addEventListener("dragover", e => { e.preventDefault(); $("drop").classList.add("over"); });
  $("drop").addEventListener("dragleave", () => $("drop").classList.remove("over"));
  $("drop").addEventListener("drop", e => {
    e.preventDefault(); $("drop").classList.remove("over");
    loadPicture(e.dataTransfer.files[0]);
  });

  // ---- Slice via the same endpoint photo.js uses ----
  async function slice() {
    if (!raster) { setStatus("Choose a picture first."); return; }
    const button = $("slice");
    const sketchMode = $("style").value === "sketch";
    button.disabled = true; $("spinner").hidden = false;
    setStatus(sketchMode && $("tune").checked ? "Sketching and tuning… this can take a while." : "Slicing…");
    showReport(null);
    try {
      const response = await fetch(sketchMode ? "/api/sketch" : "/api/photo", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({...raster, style: $("style").value,
          page_width_mm: Number($("page-w").value), page_height_mm: Number($("page-h").value),
          spacing_mm: Number($("spacing").value), contrast: Number($("contrast").value),
          threshold: Number($("threshold").value), seed: Number($("seed").value),
          tune: $("tune").checked, cleanup: $("cleanup").value, outline_mode: $("outline").value})
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Slicing failed");
      setJob(parseGcode(data.uno_gcode), $("style").value);
      if (sketchMode) showReport(data);
      setStatus(data.stroke_count + " pen strokes. Scrub the job, then download or send it.");
    } catch (error) {
      setStatus(error.message);
    } finally {
      button.disabled = false; $("spinner").hidden = true;
    }
  }
  // Sketch check: the source darkness beside the drawn strokes' darkness, with the match score.
  function showReport(data) {
    $("sketch-report").hidden = !data;
    if (!data) return;
    $("compare").src = data.compare_png || "";
    $("match").textContent = data.match + "%";
    const s = data.settings;
    $("match-note").textContent = (data.tuned ? "Auto-tuned: " : "") +
      `hatch ${s.hatch}, loose ${s.loose}, threshold ${s.thr}. Left: picture darkness. Right: drawn strokes.`;
  }
  $("slice").addEventListener("click", slice);

  // ---- G-code parser: G0/G1 X Y, G4 P, M3 pen down, M5 pen up, F feed (mm/min) ----
  function parseGcode(text) {
    const lines = text.split("\n");
    const moves = [], lineOf = [], strokeStarts = [];
    let x = 0, y = 0, feed = 300, down = false, strokePending = false;
    lines.forEach((raw, line) => {
      const [cmd, ...words] = raw.replace(/[;(].*$/, "").trim().toUpperCase().split(/\s+/);
      if (!cmd) return;
      const w = {};
      for (const word of words) w[word[0]] = Number(word.slice(1));
      if (w.F > 0) feed = w.F;
      if (cmd === "M3") { down = true; strokePending = true; return; }
      if (cmd === "M5") { down = false; return; }
      if (cmd !== "G0" && cmd !== "G1" && cmd !== "G4") return;
      const x0 = x, y0 = y;
      let len = 0, dur = 0;
      if (cmd === "G4") {
        dur = (w.P || 0) / 1000;
      } else {
        if (w.X !== undefined) x = w.X;
        if (w.Y !== undefined) y = w.Y;
        len = Math.hypot(x - x0, y - y0);
        dur = feed > 0 ? len / feed * 60 : 0;
      }
      const isDraw = down && cmd !== "G0";
      if (isDraw && strokePending) { strokeStarts.push(moves.length); strokePending = false; }
      moves.push({type: isDraw ? "draw" : "travel", x0, y0, x1: x, y1: y, len, dur});
      lineOf.push(line);
    });
    const n = moves.length, cum = new Float64Array(n + 1);
    let drawMm = 0, travelMm = 0;
    const bbox = {minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity};
    moves.forEach((m, i) => {
      cum[i + 1] = cum[i] + m.dur;
      if (m.type === "draw") drawMm += m.len; else travelMm += m.len;
      for (const [px, py] of [[m.x0, m.y0], [m.x1, m.y1]]) {
        bbox.minX = Math.min(bbox.minX, px); bbox.maxX = Math.max(bbox.maxX, px);
        bbox.minY = Math.min(bbox.minY, py); bbox.maxY = Math.max(bbox.maxY, py);
      }
    });
    if (!n) Object.assign(bbox, {minX: 0, minY: 0, maxX: 0, maxY: 0});
    return {text, lines, moves, lineOf, strokeStarts, cum, total: cum[n], drawMm, travelMm, bbox};
  }

  // ---- Job state ----
  function setJob(parsed, style) {
    stop();
    job = parsed;
    job.style = style;
    if (!job.moves.length) { setStatus("The G-code has no moves."); job = null; return; }
    $("viewer").hidden = false;
    $("step").max = job.moves.length;
    $("stroke").max = job.strokeStarts.length;
    $("stat-strokes").textContent = job.strokeStarts.length;
    $("stat-draw").textContent = Math.round(job.drawMm) + " mm";
    $("stat-travel").textContent = Math.round(job.travelMm) + " mm";
    $("stat-time").textContent = fmtTime(job.total);
    resize();
    fit();
    step = -1;
    simTime = job.total;
    setStep(job.moves.length);
  }

  function stepFromStroke(s) {
    const starts = job.strokeStarts;
    if (s <= 0) return 0;
    return s < starts.length ? starts[s] : job.moves.length;
  }

  function setStep(value) {
    if (!job || value === step) return;
    step = Math.max(0, Math.min(job.moves.length, value));
    $("step").value = step;
    $("step-label").textContent = step + " / " + job.moves.length;
    $("stroke").value = countBelow(job.strokeStarts, step);
    $("stroke-label").textContent = $("stroke").value + " / " + job.strokeStarts.length;
    $("stat-progress").textContent = step + " / " + job.moves.length + " · " + fmtTime(job.cum[step]);
    draw();
    renderList();
    followActive();
  }

  function seekTo(value) {
    stop();
    if (!job) return;
    simTime = job.cum[Math.max(0, Math.min(job.moves.length, value))];
    setStep(value);
  }

  // ---- Playback ----
  function start() {
    if (!job) return;
    if (step >= job.moves.length) setStep(0);
    simTime = job.cum[step];
    playing = true; lastTs = performance.now();
    $("play").textContent = "Pause";
    requestAnimationFrame(tick);
  }
  function stop() {
    playing = false;
    $("play").textContent = "Play";
  }
  function tick(ts) {
    if (!playing) return;
    simTime += (ts - lastTs) / 1000 * Number($("speed").value);
    lastTs = ts;
    if (simTime >= job.total) {
      simTime = job.total;
      setStep(job.moves.length);
      stop();
      return;
    }
    setStep(countBelow(job.cum, simTime, job.moves.length));
    requestAnimationFrame(tick);
  }
  $("play").addEventListener("click", () => { if (playing) stop(); else start(); });
  $("step").addEventListener("input", () => seekTo(Number($("step").value)));
  $("stroke").addEventListener("input", () => seekTo(stepFromStroke(Number($("stroke").value))));

  // ---- Canvas: draw, zoom, pan, fit ----
  function resize() {
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(canvas.clientWidth * dpr);
    canvas.height = Math.round(canvas.clientHeight * dpr);
    draw();
  }
  function fit() {
    if (!job) return;
    const W = canvas.clientWidth, H = canvas.clientHeight, b = job.bbox;
    const bw = Math.max(b.maxX - b.minX, 1), bh = Math.max(b.maxY - b.minY, 1);
    view.s = Math.min((W - 2 * PAD) / bw, (H - 2 * PAD) / bh);
    view.tx = (W - bw * view.s) / 2 - b.minX * view.s;
    view.ty = (H - bh * view.s) / 2 - b.minY * view.s;
    draw();
  }
  function draw() {
    if (!job) return;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const sx = x => x * view.s + view.tx, sy = y => y * view.s + view.ty;
    const b = job.bbox;
    ctx.strokeStyle = "#cbd5df"; ctx.lineWidth = 1;
    ctx.strokeRect(sx(b.minX), sy(b.minY), (b.maxX - b.minX) * view.s, (b.maxY - b.minY) * view.s);
    if ($("travel").checked) {
      ctx.save();
      ctx.setLineDash([5, 4]); ctx.strokeStyle = "rgba(37,99,235,.45)"; ctx.lineWidth = 1;
      ctx.beginPath();
      for (let i = 0; i < step; i++) {
        const m = job.moves[i];
        if (m.type !== "travel" || !m.len) continue;
        ctx.moveTo(sx(m.x0), sy(m.y0)); ctx.lineTo(sx(m.x1), sy(m.y1));
      }
      ctx.stroke();
      ctx.restore();
    }
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.strokeStyle = "#172335"; ctx.lineWidth = 1.4;
    ctx.beginPath();
    for (let i = 0; i < step; i++) {
      const m = job.moves[i];
      if (m.type !== "draw") continue;
      ctx.moveTo(sx(m.x0), sy(m.y0)); ctx.lineTo(sx(m.x1), sy(m.y1));
    }
    ctx.stroke();
    // Pen marker at the end of the last executed move (or the job start).
    const last = step > 0 ? job.moves[step - 1] : job.moves[0];
    const px = step > 0 ? last.x1 : last.x0, py = step > 0 ? last.y1 : last.y0;
    const down = step > 0 && last.type === "draw";
    ctx.beginPath();
    ctx.arc(sx(px), sy(py), 5, 0, Math.PI * 2);
    ctx.fillStyle = down ? "#dc2626" : "#f59e0b";
    ctx.fill();
  }
  canvas.addEventListener("wheel", e => {
    if (!job) return;
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const f = Math.exp(-e.deltaY * 0.0015);
    view.tx = mx - (mx - view.tx) * f;
    view.ty = my - (my - view.ty) * f;
    view.s *= f;
    draw();
  }, {passive: false});
  let drag = null;
  canvas.addEventListener("pointerdown", e => {
    drag = {x: e.clientX, y: e.clientY};
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", e => {
    if (!drag) return;
    view.tx += e.clientX - drag.x; view.ty += e.clientY - drag.y;
    drag = {x: e.clientX, y: e.clientY};
    draw();
  });
  const endDrag = () => { drag = null; };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);
  $("fit").addEventListener("click", fit);
  $("travel").addEventListener("change", draw);
  window.addEventListener("resize", () => { if (job) resize(); });

  // ---- G-code list (virtualized, click a line to jump) ----
  function activeLine() { return step > 0 ? job.lineOf[step - 1] : -1; }
  function renderList() {
    if (!job) return;
    spacer.style.height = job.lines.length * ROW + "px";
    const active = activeLine();
    const first = Math.max(0, Math.floor(list.scrollTop / ROW) - 5);
    const last = Math.min(job.lines.length, Math.ceil((list.scrollTop + list.clientHeight) / ROW) + 5);
    rows.style.top = first * ROW + "px";
    const frag = document.createDocumentFragment();
    for (let i = first; i < last; i++) {
      const div = document.createElement("div");
      div.className = "gc-row" + (i === active ? " active" : "");
      div.dataset.line = i;
      div.textContent = String(i + 1).padStart(5) + "  " + job.lines[i];
      frag.append(div);
    }
    rows.replaceChildren(frag);
  }
  function followActive() {
    if (!job) return;
    const active = activeLine();
    if (active < 0) return;
    const y = active * ROW;
    if (y < list.scrollTop || y + ROW > list.scrollTop + list.clientHeight) {
      list.scrollTop = Math.max(0, y - list.clientHeight / 2);
    }
  }
  list.addEventListener("scroll", renderList);
  rows.addEventListener("click", e => {
    const row = e.target.closest("[data-line]");
    if (!row || !job) return;
    // Lines are sorted, so the count of moves at or before this line is the step to jump to.
    seekTo(countBelow(job.lineOf, Number(row.dataset.line) + 1));
  });

  // ---- Download and send ----
  $("download").addEventListener("click", () => {
    if (!job) return;
    const url = URL.createObjectURL(new Blob([job.text], {type: "text/plain"}));
    const link = document.createElement("a");
    link.href = url; link.download = "davinci-" + job.style + ".nc";
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  // Inside web/index.html's slicer iframe, hand the job to the parent page instead of navigating.
  const embedded = window.parent !== window;
  $("send").addEventListener("click", event => {
    if (!job) { event.preventDefault(); return; }
    if (embedded) {
      event.preventDefault();
      window.parent.postMessage({type: "davinci-job", text: job.text, name: "slicer " + job.style}, location.origin);
      setStatus("Sent to the Job panel. Check the origin, then press Start there.");
      return;
    }
    try {
      localStorage.setItem(STORE_KEY, job.text);
    } catch {
      event.preventDefault();
      setStatus("Could not store the job in this browser. Download the .nc file instead.");
    }
  });
})();
