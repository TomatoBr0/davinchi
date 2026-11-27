"use strict";
(() => {
  const el = id => document.getElementById(id);
  let raster = null, result = null, generation = 0;
  const styleNotes = {
    springs: "Overlapping coils expand in the shadows, drawing the picture in spring-like ribbons.",
    halftone: "Circles grow with darkness to form a photographic halftone.",
    boxes: "Squares grow with darkness for a geometric, pixel-art texture.",
    scribble: "Long overlapping curves build shadows while traced contours retain facial features.",
    tour: "One continuous path links irregularly scattered points, with more points in dark areas.",
    squiggle: "Each row becomes a flowing wave. Dark areas make tighter, taller waves.",
    spiral: "One winding oval spiral builds shading with small waves. The outer corners of the photo are cropped.",
    outlines: "Connected contours trace contrasts and facial features. Lower the threshold for more detail.",
    crosshatch: "Crossing line layers build progressively darker shadows.",
    diagonal: "Parallel diagonal lines vary in density with the image tone.",
    stipple: "Irregular dots build the shadows. Each dot requires a pen lift."
  };
  el("photo-style").addEventListener("change", () => {
    el("photo-style-note").textContent = styleNotes[el("photo-style").value];
  });
  const status = message => { el("photo-status").textContent = message; };
  function invalidate() {
    generation++;
    result = null;
    el("photo-svg").disabled = el("photo-code").disabled = true;
    el("photo-preview").replaceChildren();
  }
  el("photo-file").addEventListener("change", async () => {
    invalidate();
    raster = null;
    el("photo-source").replaceChildren();
    const file = el("photo-file").files[0];
    if (!file) return;
    const token = generation;
    if (file.size > 20 * 1024 * 1024) {
      status("Choose an image smaller than 20 MB.");
      return;
    }
    const url = URL.createObjectURL(file);
    try {
      const image = new Image();
      image.src = url;
      await image.decode();
      if (token !== generation) return;
      const ratio = Math.min(1, 480 / Math.max(image.naturalWidth, image.naturalHeight));
      const width = Math.max(2, Math.round(image.naturalWidth * ratio));
      const height = Math.max(2, Math.round(image.naturalHeight * ratio));
      const canvas = document.createElement("canvas");
      canvas.width = width; canvas.height = height;
      canvas.style.maxWidth = "100%";
      const ctx = canvas.getContext("2d", {willReadFrequently: true});
      ctx.fillStyle = "white"; ctx.fillRect(0, 0, width, height);
      ctx.drawImage(image, 0, 0, width, height);
      const rgba = ctx.getImageData(0, 0, width, height).data, pixels = [];
      for (let i = 0; i < rgba.length; i += 4) {
        pixels.push(Math.round(.2126 * rgba[i] + .7152 * rgba[i+1] + .0722 * rgba[i+2]));
      }
      raster = {width, height, pixels};
      el("photo-source").append(canvas);
      status("Image loaded. Choose a style and generate a preview.");
    } catch {
      status("Could not read this image. Try a JPEG, PNG or WebP.");
    } finally { URL.revokeObjectURL(url); }
  });
  for (const input of document.querySelectorAll("#photo-controls input, #photo-controls select")) {
    input.addEventListener("input", () => {
      invalidate();
      status("Settings changed. Generate a new preview.");
    });
  }
  el("photo-generate").addEventListener("click", async () => {
    if (!raster) { status("Choose a picture first."); return; }
    invalidate();
    const token = generation;
    el("photo-generate").disabled = true;
    status("Generating pen paths…");
    try {
      const response = await fetch("/api/photo", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({...raster, style: el("photo-style").value,
          page_width_mm: Number(el("photo-width").value),
          page_height_mm: Number(el("photo-height").value),
          spacing_mm: Number(el("photo-spacing").value),
          contrast: Number(el("photo-contrast").value),
          threshold: Number(el("photo-threshold").value),
          seed: Number(el("photo-seed").value),
          cleanup: el("photo-cleanup").value, outline_mode: el("photo-outline-mode").value})
      });
      const data = await response.json();
      if (token !== generation) return;
      if (!response.ok) throw new Error(data.error || "Conversion failed");
      result = data;
      window.davinciMachine?.loadJob(data.uno_gcode, "Photo drawing");
      el("photo-preview").innerHTML = data.svg;
      el("photo-svg").disabled = el("photo-code").disabled = false;
      status(data.stroke_count + " pen strokes · " + data.draw_length_mm +
        " mm of drawing. Preview orientation and size before sending to your calibrated machine.");
    } catch (error) {
      if (token === generation) status(error.message);
    } finally { el("photo-generate").disabled = false; }
  });
  function save(field, suffix, type) {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([result[field]], {type}));
    const link = document.createElement("a");
    link.href = url; link.download = "davinci-" + el("photo-style").value + suffix;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  el("photo-svg").onclick = () => save("svg", ".svg", "image/svg+xml");
  el("photo-code").onclick = () => save("uno_gcode", ".dvc", "text/plain");
})();
