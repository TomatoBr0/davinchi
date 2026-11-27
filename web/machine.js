"use strict";
// Machine link, status bar, calibration wizard and job runner.
// Two transports with one interface: SerialLink (Web Serial, this browser) and
// ServerLink (app.py owns the USB port, phones on the LAN use this one).
(() => {
  const $ = id => document.getElementById(id);
  const BAUD = 115200;            // firmware Serial.begin(115200)
  const TEST_SQUARE_MM = 100;     // tools/calibration_test.nc square edge
  // Control panel bake-in: X/Y 5 steps/mm, Z 160. X/Y travel is +-90 mm from the origin.
  // Z+ is down and Z=0 is the bottom stop, so Z never goes above zTop.
  const CTL = {xSteps: 5, ySteps: 5, zSteps: 160, travel: 90, zTop: 0, zFeed: 100, xyFeed: 300};
  const RUN_STATES = ["running", "paused", "stopping"];
  const PROFILE_KEY = "davinci.machineProfile";
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const idleJob = () => ({state: "idle", index: 0, total: 0, error: "", name: ""});
  const isJobActive = job => RUN_STATES.includes(job.state);

  // Same reply formats as firmware M115, M114 and LIMITS.
  function parseStatus(reply) {
    const m = /^ok CAL=([01]) ORIGIN=([01]) ARMED=([01]) MAX X(-?[\d.]+) Y(-?[\d.]+) Z(-?[\d.]+) STEPS X(-?[\d.]+) Y(-?[\d.]+) Z(-?[\d.]+)$/.exec(reply);
    if (!m) return null;
    const n = m.slice(4).map(Number);
    return {cal: m[1] === "1", origin: m[2] === "1", armed: m[3] === "1",
            maxX: n[0], maxY: n[1], maxZ: n[2], stepsX: n[3], stepsY: n[4], stepsZ: n[5]};
  }
  function parsePosition(reply) {
    const m = /^ok X(-?[\d.]+) Y(-?[\d.]+) Z(-?[\d.]+) (known|unknown)$/.exec(reply);
    return m ? {x: Number(m[1]), y: Number(m[2]), z: Number(m[3]), known: m[4] === "known"} : null;
  }
  function parseLimits(reply) {
    const m = /^ok X(-?[\d.]+) Y(-?[\d.]+) F(-?[\d.]+)$/.exec(reply);
    return m ? {feed: Number(m[3])} : null;
  }
  // One relative move, clamped so X/Y stay within +-travel and Z never rises above zTop.
  function clampDelta(pos, axis, delta) {
    const from = pos[axis.toLowerCase()];
    const to = axis === "Z" ? Math.min(CTL.zTop, from + delta)
                            : Math.max(-CTL.travel, Math.min(CTL.travel, from + delta));
    return Math.round((to - from) * 1000) / 1000;
  }

  // Web Serial, this browser. Commands are queued so exactly one is in flight at a time.
  class SerialLink {
    constructor(onChange) {
      this.kind = "browser"; this.label = "this browser (USB)"; this.onChange = onChange;
      this.connected = false; this.port = null; this.reader = null; this.writer = null;
      this.rx = ""; this.pending = null; this.queue = Promise.resolve();
      this.log = []; this.status = {}; this.job = idleJob();
      this.pauseFlag = false; this.stopFlag = false; this.resumeWaiter = null;
    }
    static supported() { return "serial" in navigator; }
    record(text) {
      this.log.push(text);
      if (this.log.length > 400) this.log.splice(0, this.log.length - 400);
      this.onChange();
    }
    async connect() {
      this.port = await navigator.serial.requestPort();
      await this.port.open({baudRate: BAUD});
      this.writer = this.port.writable.getWriter();
      this.connected = true;
      this.readLoop();
      await sleep(2000); // the Uno resets when the port opens
      this.rx = "";
      this.record(`Connected at ${BAUD} baud.`);
      try { Object.assign(this.status, parseLimits(await this.send("LIMITS"))); } catch { /* optional */ }
      await this.refresh();
    }
    async readLoop() {
      const reader = this.port.readable.pipeThrough(new TextDecoderStream()).getReader();
      this.reader = reader;
      try {
        for (;;) {
          const {value, done} = await reader.read();
          if (done) break;
          this.rx += value;
          let end;
          while ((end = this.rx.indexOf("\n")) >= 0) {
            const line = this.rx.slice(0, end).trim();
            this.rx = this.rx.slice(end + 1);
            if (line) this.received(line);
          }
        }
      } catch (err) {
        this.record("Serial read stopped: " + err.message);
      }
      this.connected = false;
      this.failPending("Port closed.");
      this.onChange();
    }
    received(line) {
      this.record("< " + line);
      const p = this.pending;
      if (!p) return;
      if (line === "ok" || line.startsWith("ok ")) {
        this.pending = null; clearTimeout(p.timer); p.resolve(line);
      } else if (line.startsWith("error:")) {
        this.pending = null; clearTimeout(p.timer); p.reject(new Error(line.slice(6).trim()));
      }
    }
    failPending(message) {
      const p = this.pending;
      if (!p) return;
      this.pending = null; clearTimeout(p.timer); p.reject(new Error(message));
    }
    send(line) {
      const run = () => new Promise((resolve, reject) => {
        if (!this.connected) { reject(new Error("Not connected.")); return; }
        const p = {resolve, reject, timer: null};
        p.timer = setTimeout(() => {
          if (this.pending === p) { this.pending = null; reject(new Error("No reply to " + line)); }
        }, 120000);
        this.pending = p;
        this.record("> " + line);
        this.writer.write(new TextEncoder().encode(line + "\n")).catch(err => {
          if (this.pending === p) { this.pending = null; clearTimeout(p.timer); }
          reject(err);
        });
      });
      const next = this.queue.then(run);
      this.queue = next.catch(() => {});
      return next;
    }
    async refresh() {
      if (!this.connected || isJobActive(this.job)) return;
      const s = parseStatus(await this.send("M115"));
      const p = parsePosition(await this.send("M114"));
      if (!s || !p) throw new Error("Unexpected status reply.");
      Object.assign(this.status, s, p);
    }
    async disconnect() {
      if (isJobActive(this.job)) throw new Error("Stop the job before disconnecting.");
      this.connected = false;
      this.failPending("Disconnected.");
      try { await this.reader?.cancel(); } catch { /* already closed */ }
      try { this.writer?.releaseLock(); } catch { /* already released */ }
      try { await this.port?.close(); } catch { /* already closed */ }
      this.reader = this.writer = this.port = null;
      this.status = {};
      this.record("Disconnected.");
    }
    abort() {
      this.stopFlag = true; this.wake();
      this.record("> !  (abort)");
      if (this.writer) this.writer.write(new TextEncoder().encode("!\n")).catch(() => {});
    }
    async runJob(text, name) {
      if (!this.connected) throw new Error("Not connected.");
      if (isJobActive(this.job)) throw new Error("A job is already running.");
      const lines = text.split("\n").map(l => l.split(";")[0].trim()).filter(Boolean);
      if (lines[0] !== "G21" || lines[1] !== "G90" || lines[lines.length - 1] !== "M5" ||
          !lines.every(l => l.length <= 62 && /^[\x20-\x7e]+$/.test(l))) {
        throw new Error("Job must start with G21 G90, end with M5, and use ASCII lines up to 62 characters.");
      }
      await this.refresh();
      if (!this.status.origin) throw new Error("Set the origin (M210) before streaming.");
      await this.send("ARM");
      this.job = {state: "running", index: 0, total: lines.length, error: "", name};
      this.pauseFlag = false; this.stopFlag = false;
      this.record(`Job started: ${name} (${lines.length} lines).`);
      this.runLoop(lines); // deliberately not awaited: progress arrives through onChange
    }
    async runLoop(lines) {
      try {
        for (const line of lines) {
          await this.waitIfPaused();
          if (this.stopFlag) break;
          await this.send(line);
          this.job.index++;
          this.onChange();
        }
        if (this.stopFlag) {
          await this.send("M5"); // pen up after the line that was in progress
          this.job.state = "stopped";
          this.record("Job stopped; pen up.");
        } else {
          this.job.state = "done";
          this.record("Job finished.");
        }
      } catch (err) {
        this.job.state = "error";
        this.job.error = err.message;
        this.record("Job stopped with error: " + err.message);
        try { await this.send("M5"); } catch { /* best-effort pen up */ }
      }
      this.onChange();
    }
    waitIfPaused() {
      if (!this.pauseFlag || this.stopFlag) return null;
      return new Promise(resolve => { this.resumeWaiter = resolve; });
    }
    wake() { const w = this.resumeWaiter; this.resumeWaiter = null; if (w) w(); }
    pause() {
      if (this.job.state !== "running") return;
      this.pauseFlag = true; this.job.state = "paused"; this.onChange();
    }
    resume() {
      if (this.job.state !== "paused") return;
      this.pauseFlag = false; this.job.state = "running"; this.wake(); this.onChange();
    }
    stop() {
      if (!isJobActive(this.job)) return;
      this.stopFlag = true; this.pauseFlag = false; this.job.state = "stopping"; this.wake(); this.onChange();
    }
  }

  // app.py holds the USB port. Status is polled; the server streams the job.
  class ServerLink {
    constructor(onChange) {
      this.kind = "server"; this.onChange = onChange; this.connected = false; this.port = "";
      this.label = ""; this.log = []; this.status = {}; this.job = idleJob();
    }
    static supported() { return true; }
    async call(action, body) {
      const options = body === undefined ? {method: "POST"} :
        {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
      return this.request("/api/serial/" + action, options);
    }
    async request(url, options = {cache: "no-store"}) {
      const response = await fetch(url, options);
      let data;
      try { data = await response.json(); } catch { throw new Error("Invalid server response"); }
      if (!response.ok) throw new Error(data.error || "HTTP " + response.status);
      return data;
    }
    apply(snapshot) {
      this.connected = !!snapshot.connected;
      this.port = snapshot.port || "";
      this.label = this.port;
      this.status = snapshot.status || {};
      this.job = snapshot.job || idleJob();
      this.log = snapshot.log || [];
      this.onChange();
    }
    async refresh() { this.apply(await this.request("/api/serial/status")); }
    async connect(port) { this.apply(await this.call("connect", {port})); }
    async disconnect() { this.apply(await this.call("disconnect")); }
    async send(line) {
      const {reply, ...snapshot} = await this.call("send", {line});
      this.apply(snapshot);
      return reply;
    }
    async abort() { this.apply(await this.call("abort")); }
    async runJob(text, name) { this.apply(await this.call("job", {text, name})); }
    async pause() { this.apply(await this.call("job/pause")); }
    async resume() { this.apply(await this.call("job/resume")); }
    async stop() { this.apply(await this.call("job/stop")); }
  }

  let link = null, commandsInFlight = 0, lastError = "", currentJob = null, tabChosen = false;

  function setLink(kind) {
    link = kind === "server" ? new ServerLink(render) : new SerialLink(render);
    if (kind === "server") link.label = "server";
    render();
  }
  function say(text, error = false) {
    $("machine-msg").textContent = text;
    $("machine-msg").classList.toggle("error", error);
  }
  async function run(action) {
    try { await action(); } catch (err) { lastError = err.message; say(err.message, true); }
    render();
  }
  async function command(line) {
    if (isJobActive(link.job)) throw new Error("A job is running. Pause or stop it first.");
    commandsInFlight++; render();
    try {
      const reply = await link.send(line);
      lastError = "";
      return reply;
    } finally {
      commandsInFlight--; render();
    }
  }
  function canJog() {
    return !!link && link.connected && link.status.armed && !isJobActive(link.job);
  }
  function jog(axis, dir) {
    if (!canJog()) return;
    const steps = link.status["steps" + axis];
    if (!(steps > 0)) { say("Enter steps/mm in step 1 before jogging: the plotter cannot move until it knows them.", true); return; }
    const feed = axis === "Z" ? 100 : 300; // firmware caps Z feed at 120 mm/min
    const distance = (Number($("jog-step").value) * dir).toFixed(3);
    run(() => command(`J ${axis}${distance} F${feed}`));
  }
  // Control panel: needs motors enabled, idle, origin set and a known position.
  function canControl() {
    return canJog() && !!link.status.origin && Number.isFinite(link.status.z);
  }
  async function ctlMove(axis, delta) {
    const d = clampDelta(link.status, axis, delta);
    if (d === 0) { say(axis + " is already there or at its limit."); return; }
    await command(`J ${axis}${d.toFixed(3)} F${axis === "Z" ? CTL.zFeed : CTL.xyFeed}`);
    await link.refresh();
  }
  function ctlJog(axis, dir) {
    if (!canControl()) throw new Error("Connect, enable motors and set the origin (M210) first.");
    return ctlMove(axis, Number($("ctl-step").value) * dir);
  }
  function penTo(down) {
    if (!canControl()) throw new Error("Connect, enable motors and set the origin (M210) first.");
    const lift = Number($("ctl-lift").value);
    if (!(lift > 0 && lift <= 10)) throw new Error("Pen lift must be between 0.1 and 10 mm.");
    return ctlMove("Z", (down ? 0 : -lift) - link.status.z); // bottom stop is 0; pen up is above it
  }
  async function motorsOn() {
    if (!link.connected) throw new Error("Connect first.");
    if (!link.status.armed) {
      // Steps/mm are RAM-only and the firmware refuses them while armed.
      for (const line of [`$XMM=${CTL.xSteps}`, `$YMM=${CTL.ySteps}`, `$ZMM=${CTL.zSteps}`]) await command(line);
    }
    await command("M17");
    await link.refresh();
    say("Motors enabled. Set the origin (M210) before jogging.");
  }
  async function motorsOff() {
    await command("M18");
    await link.refresh();
    say("Motors disabled. The origin is cleared: set it again (M210) before jogging.");
  }
  function showTab(name) {
    $("pane-calibrate").hidden = name !== "calibrate";
    $("pane-make").hidden = name !== "make";
    $("pane-control").hidden = name !== "control";
    document.querySelectorAll(".tab").forEach(t => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
  }

  function render() {
    if (!link) return;
    const s = link.status, connected = link.connected, job = link.job;
    const active = isJobActive(job), busy = active || commandsInFlight > 0;
    const needsCal = connected && (!s.cal || !s.origin);
    const blink = Math.floor(Date.now() / 250) % 2 === 1;
    const serverOk = !(link.kind === "browser" && !SerialLink.supported());

    $("conn-state").textContent = connected ? "Connected to " + link.label + "." : "Not connected.";
    $("connect").disabled = connected || !serverOk;
    $("disconnect").disabled = !connected || active;
    $("transport").disabled = connected;
    $("port-label").hidden = $("ports-refresh").hidden = link.kind !== "server";
    $("webserial-note").hidden = serverOk;

    $("led-ready").classList.toggle("on", connected && !busy && !lastError && !needsCal);
    $("led-busy").classList.toggle("on", busy);
    $("led-alarm").classList.toggle("on", !!lastError || (needsCal && blink));
    $("led-cal").classList.toggle("on", connected && !s.cal);
    $("led-ready").title = "Ready: connected, calibrated, origin set, idle, no error";

    const fmt = v => (typeof v === "number" ? v.toFixed(3) : "-");
    $("status-text").textContent = connected ? [
      `Position: X ${fmt(s.x)}  Y ${fmt(s.y)}  Z ${fmt(s.z)} mm (${s.known ? "origin known" : "origin unknown"})`,
      `Travel: X 0-${fmt(s.maxX)}  Y 0-${fmt(s.maxY)}  Z 0-${fmt(s.maxZ)} mm   Feed limit: ${s.feed ?? "-"} mm/min`,
      `Steps/mm: X ${s.stepsX ?? "-"}  Y ${s.stepsY ?? "-"}  Z ${s.stepsZ ?? "-"}`,
      `Calibrated: ${s.cal ? "yes" : "no"}   Origin: ${s.origin ? "set" : "not set"}   Motors: ${s.armed ? "enabled" : "off"}`,
    ].join("\n") : "Connect to see position, limits and calibration.";

    $("console").textContent = link.log.slice(-300).join("\n");
    $("console").scrollTop = $("console").scrollHeight;

    $("job-name").textContent = currentJob ?
      `Loaded: ${currentJob.name} (${currentJob.lines} lines)` :
      "No job loaded. Compose a handwriting or make a photo drawing first.";
    $("job-progress").max = Math.max(job.total || 0, 1);
    $("job-progress").value = job.index || 0;
    $("job-text").textContent = job.state + (job.total ? ` · line ${job.index} of ${job.total}` : "") +
      (job.error ? " · " + job.error : "");
    $("job-text").classList.toggle("error", !!job.error);
    $("job-start").disabled = !(connected && s.origin && currentJob) || active;
    $("job-pause").disabled = job.state !== "running";
    $("job-resume").disabled = job.state !== "paused";
    $("job-stop").disabled = !(job.state === "running" || job.state === "paused");

    // Calibration wizard
    const jogOk = canJog();
    document.querySelectorAll("[data-jog]").forEach(b => { b.disabled = !jogOk; });
    const idle = connected && !active;
    $("step-enable").disabled = !idle;
    $("set-origin").disabled = !idle;
    $("save-max").disabled = !(idle && s.origin);
    $("draw-test").disabled = !(idle && s.origin && s.cal);
    const mx = Number($("meas-x").value), my = Number($("meas-y").value);
    $("apply-steps").disabled = !(idle && mx > 0 && my > 0 && s.stepsX > 0 && s.stepsY > 0);
    $("new-x").textContent = mx > 0 && s.stepsX ? (s.stepsX * TEST_SQUARE_MM / mx).toFixed(3) : "-";
    $("new-y").textContent = my > 0 && s.stepsY ? (s.stepsY * TEST_SQUARE_MM / my).toFixed(3) : "-";
    $("done-1").textContent = s.armed ? "Done" : "Pending";
    $("done-2").textContent = s.origin ? "Done" : "Pending";
    $("done-3").textContent = s.cal ? "Done" : "Pending";

    // Control panel
    const ctlOk = canControl(), idleLinked = connected && !active;
    document.querySelectorAll("[data-ctl]").forEach(b => { b.disabled = !ctlOk; });
    $("ctl-pen-up").disabled = $("ctl-pen-down").disabled = !ctlOk;
    $("ctl-motors-on").disabled = !idleLinked;
    $("ctl-motors-off").disabled = !(idleLinked && s.armed);
    $("ctl-pos").textContent = connected ?
      `X ${fmt(s.x)}  Y ${fmt(s.y)}  Z ${fmt(s.z)} mm (${s.origin ? "origin set" : "origin not set"}, motors ${s.armed ? "on" : "off"})` :
      "Connect to see position.";
    $("cal-banner").hidden = !!(connected && s.cal);
    if (!tabChosen && connected && "cal" in s) {
      tabChosen = true;
      showTab(s.cal ? "make" : "calibrate");
    }
  }

  // Event wiring
  document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => showTab(t.dataset.tab)));

  $("transport").addEventListener("change", () => {
    setLink($("transport").value);
    if (link.kind === "server") run(loadPorts);
  });
  async function loadPorts() {
    const data = await link.request("/api/serial/ports");
    const select = $("server-port");
    select.replaceChildren();
    for (const p of data.ports) {
      const option = document.createElement("option");
      option.value = p.device;
      option.textContent = p.device + (p.description ? " - " + p.description : "");
      select.append(option);
    }
    if (!data.available) throw new Error(data.error);
    if (!data.ports.length) say("No serial ports found. Plug in the Uno and refresh.", true);
  }
  $("ports-refresh").addEventListener("click", () => run(loadPorts));
  $("connect").addEventListener("click", () => run(async () => {
    if (link.kind === "browser") {
      await link.connect();   // called directly from the click so requestPort() has user activation
    } else {
      const port = $("server-port").value;
      if (!port) throw new Error("Choose a port, or refresh the list.");
      await link.connect(port);
    }
    say("Connected.");
  }));
  $("disconnect").addEventListener("click", () => run(() => link.disconnect()));
  $("abort").addEventListener("click", () => run(() => link.abort()));
  $("cmd-form").addEventListener("submit", event => {
    event.preventDefault();
    const line = $("cmd").value.trim();
    if (!line) return;
    $("cmd").value = "";
    run(() => command(line));
  });

  $("job-start").addEventListener("click", () => run(() => {
    if (!currentJob) throw new Error("Load a job first.");
    return link.runJob(currentJob.text, currentJob.name);
  }));
  $("job-pause").addEventListener("click", () => run(() => link.pause()));
  $("job-resume").addEventListener("click", () => run(() => link.resume()));
  $("job-stop").addEventListener("click", () => run(() => link.stop()));

  // Calibration wizard
  $("step-enable").addEventListener("click", () => run(async () => {
    if (link.status.armed) {
      await command("M17");
      say("Motors enabled. The profile is not re-sent while armed; disarm (M18) to change it.");
      return;
    }
    const xs = Number($("x-steps").value), ys = Number($("y-steps").value), zs = Number($("z-steps").value);
    const zMax = Number($("z-max").value), up = Number($("pen-up").value), down = Number($("pen-down").value);
    if (![xs, ys, zs].every(v => v > 0 && v <= 2000)) {
      throw new Error("Enter steps/mm between 0.1 and 2000 for X, Y and Z.");
    }
    if (!(zMax > 0) || up < 0 || up > zMax || down < 0 || down > zMax || Math.abs(up - down) < 0.01) {
      throw new Error("Enter Z max and two different pen heights between 0 and Z max.");
    }
    saveProfile();
    // M92 is accepted only while disarmed, and it saves steps/mm to EEPROM.
    await command(`M92 X${xs.toFixed(3)} Y${ys.toFixed(3)} Z${zs.toFixed(3)}`);
    const lines = ["$XMIN=0", "$YMIN=0", "$ZMIN=0", `$ZMAX=${zMax}`, `$PENUP=${up}`, `$PENDOWN=${down}`];
    if (link.status.maxX > 0) lines.push(`$XMAX=${link.status.maxX}`);
    if (link.status.maxY > 0) lines.push(`$YMAX=${link.status.maxY}`);
    for (const line of lines) await command(line);
    await command("M17");
    say("Steps/mm and profile sent, motors enabled. Next: jog to the bottom-left corner and set origin.");
  }));
  $("set-origin").addEventListener("click", () => run(async () => {
    await command("M210");
    say("Origin set here (M210). Next: jog to the far corner and save max.");
  }));
  $("save-max").addEventListener("click", () => run(async () => {
    await command("M211");
    say("Max corner saved (M211). Next: draw the test square.");
  }));
  $("draw-test").addEventListener("click", () => run(async () => {
    const response = await fetch("/calibration_test.nc", {cache: "no-store"});
    if (!response.ok) throw new Error("Could not load calibration_test.nc");
    // The file ends with a return to origin and no pen-up; append M5 so the job validator accepts it.
    await link.runJob((await response.text()) + "\nM5\n", "calibration test square");
    say("Test square running. Measure it when it finishes (step 5).");
  }));
  for (const id of ["meas-x", "meas-y"]) $(id).addEventListener("input", render);
  $("apply-steps").addEventListener("click", () => run(async () => {
    const mx = Number($("meas-x").value), my = Number($("meas-y").value);
    if (!(mx > 0 && my > 0)) throw new Error("Enter the measured X and Y sizes in mm.");
    const nx = link.status.stepsX * TEST_SQUARE_MM / mx, ny = link.status.stepsY * TEST_SQUARE_MM / my;
    if (nx < 0.1 || nx > 2000 || ny < 0.1 || ny > 2000) throw new Error("Computed steps/mm is out of range.");
    if (link.status.armed) await command("M18"); // M92 is only accepted while disarmed
    await command(`M92 X${nx.toFixed(3)} Y${ny.toFixed(3)}`);
    say("Steps/mm saved. The origin is cleared: repeat steps 1 and 2 before drawing the test again.");
  }));

  function loadProfile() {
    try {
      const p = JSON.parse(localStorage.getItem(PROFILE_KEY) || "{}");
      if (p.xSteps) $("x-steps").value = p.xSteps;
      if (p.ySteps) $("y-steps").value = p.ySteps;
      if (p.zSteps) $("z-steps").value = p.zSteps;
      if (p.zMax) $("z-max").value = p.zMax;
      if (p.penUp) $("pen-up").value = p.penUp;
      if (p.penDown) $("pen-down").value = p.penDown;
    } catch { /* storage blocked: just start empty */ }
  }
  function saveProfile() {
    try {
      localStorage.setItem(PROFILE_KEY, JSON.stringify({
        xSteps: $("x-steps").value, ySteps: $("y-steps").value, zSteps: $("z-steps").value,
        zMax: $("z-max").value, penUp: $("pen-up").value, penDown: $("pen-down").value}));
    } catch { /* storage blocked: nothing to save */ }
  }

  const KEY_JOG = {ArrowLeft: ["X", -1], ArrowRight: ["X", 1], ArrowUp: ["Y", 1], ArrowDown: ["Y", -1],
                   PageUp: ["Z", 1], PageDown: ["Z", -1]};
  document.querySelectorAll("[data-jog]").forEach(b => b.addEventListener("click", () => jog(b.dataset.jog, Number(b.dataset.dir))));
  document.querySelectorAll("[data-ctl]").forEach(b => b.addEventListener("click", () => run(() => ctlJog(b.dataset.ctl, Number(b.dataset.dir)))));
  $("ctl-pen-up").addEventListener("click", () => run(() => penTo(false)));
  $("ctl-pen-down").addEventListener("click", () => run(() => penTo(true)));
  $("ctl-motors-on").addEventListener("click", () => run(motorsOn));
  $("ctl-motors-off").addEventListener("click", () => run(motorsOff));
  // The slicer iframe sends a finished job. Loading it never starts the pen: Start stays in the Job panel.
  window.addEventListener("message", event => {
    if (event.source !== $("slicer-frame").contentWindow || event.origin !== location.origin) return;
    const data = event.data;
    if (!data || data.type !== "davinci-job" || typeof data.text !== "string") return;
    window.davinciMachine.loadJob(data.text, data.name || "slicer job");
  });
  document.addEventListener("keydown", event => {
    if ($("pane-calibrate").hidden || event.repeat || event.altKey || event.ctrlKey || event.metaKey) return;
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(event.target.tagName)) return;
    const key = KEY_JOG[event.key];
    if (!key) return;
    event.preventDefault();
    jog(key[0], key[1]);
  });

  // Called by the compose and photo panels. Loading a job never moves the machine.
  window.davinciMachine = {
    loadJob(text, name) {
      if (!text) { currentJob = null; render(); return; }
      const lines = text.split("\n").filter(l => l.trim() && !l.trim().startsWith(";")).length;
      currentJob = {text, name, lines};
      say(`Job loaded: ${name}. Start it from the Job panel once the origin is set.`);
      render();
    }
  };

  loadProfile();
  showTab("calibrate");
  setLink(SerialLink.supported() ? "browser" : "server");
  $("transport").value = link.kind;
  if (link.kind === "server") run(loadPorts);
  setInterval(async () => {
    // The server link polls even when disconnected so a session opened elsewhere shows up.
    if (link.kind === "server" || (link.connected && !isJobActive(link.job))) {
      try { await link.refresh(); } catch { /* shown in the console when a command fails */ }
    }
    render();
  }, 2000);
  setInterval(render, 500); // LED blink and wizard enablement
})();
