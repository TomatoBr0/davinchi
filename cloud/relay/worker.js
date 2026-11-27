// Remote relay for the laptop plotter app (davinchi/app.py).
// Phone (browser) -> this Worker queue <- laptop polls outbound (tools/relay_client.py).
// Bindings: RELAY_KV (KV namespace). Secrets: RELAY_TOKEN (phone), AGENT_TOKEN (laptop).
// ponytail: KV is not atomic. One phone + one laptop is fine; use a Durable Object if you need strict ordering.

const MAX_IMAGE_BYTES = 20 * 1024 * 1024; // KV values cap at 25 MiB
const MAX_RESULT_BYTES = 2 * 1024 * 1024;
const MAX_BODY = 64 * 1024;
const PHONE_COMMANDS = new Set(['status', 'preview', 'slice', 'start', 'stop', 'jog']);
const MOTION_COMMANDS = new Set(['start', 'jog']); // hardware moves: phone must confirm
const JOG_LIMIT_MM = 10;

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });

function bearer(req) {
  const h = req.headers.get('authorization') || '';
  return h.startsWith('Bearer ') ? h.slice(7) : '';
}

function safeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || !a || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function authorize(req, env, role) {
  const expected = role === 'agent' ? env.AGENT_TOKEN : env.RELAY_TOKEN;
  if (!expected) return json({ error: 'Relay secret not configured' }, 500);
  if (!safeEqual(bearer(req), expected)) return json({ error: 'Unauthorized' }, 401);
  return null;
}

let seq = 0; // ids sort by time, then by creation order within an isolate
const newId = () => Date.now().toString().padStart(15, '0') + '-' + (++seq).toString().padStart(6, '0') + '-' + crypto.randomUUID().slice(0, 4);

async function putCommand(env, cmd) {
  await env.RELAY_KV.put('cmd:' + cmd.id, JSON.stringify(cmd));
}

async function readJson(req) {
  const text = await req.text();
  if (text.length > MAX_BODY) throw new Error('Body too large');
  try { return JSON.parse(text || '{}'); } catch { throw new Error('Invalid JSON'); }
}

function validateCommand(type, args) {
  if (!PHONE_COMMANDS.has(type)) return 'Unknown command';
  if (type === 'jog') {
    for (const k of ['dx', 'dy', 'dz']) {
      const v = args?.[k] ?? 0;
      if (typeof v !== 'number' || !Number.isFinite(v) || Math.abs(v) > JOG_LIMIT_MM) return `${k} must be within +/-${JOG_LIMIT_MM} mm`;
    }
  }
  return null;
}

async function listCommands(env, limit) {
  const list = await env.RELAY_KV.list({ prefix: 'cmd:', limit });
  const out = [];
  for (const k of list.keys) {
    const v = await env.RELAY_KV.get(k.name, 'json');
    if (v) out.push(v);
  }
  return out;
}

async function handlePhone(req, env, url) {
  const denied = authorize(req, env, 'phone');
  if (denied) return denied;

  if (req.method === 'POST' && url.pathname === '/api/upload') {
    const type = req.headers.get('content-type') || '';
    if (!type.startsWith('image/jpeg')) return json({ error: 'Send a JPEG (image/jpeg)' }, 415);
    const bytes = await req.arrayBuffer();
    if (bytes.byteLength === 0 || bytes.byteLength > MAX_IMAGE_BYTES) return json({ error: 'Image empty or over 20 MB' }, 413);
    const id = newId();
    await env.RELAY_KV.put('img:' + id, bytes, { metadata: { bytes: bytes.byteLength, type: 'image/jpeg' } });
    await putCommand(env, { id: newId(), type: 'handwriting_upload', args: { upload_id: id }, status: 'queued', created: Date.now() });
    return json({ upload_id: id }, 201);
  }

  if (req.method === 'POST' && url.pathname === '/api/command') {
    const body = await readJson(req);
    const type = String(body.type || '');
    const args = body.args && typeof body.args === 'object' ? body.args : {};
    const bad = validateCommand(type, args);
    if (bad) return json({ error: bad }, 400);
    if (MOTION_COMMANDS.has(type) && body.confirm !== true) {
      return json({ error: 'Motion needs explicit confirm from the phone UI' }, 409);
    }
    if (type === 'start') {
      // Start only runs G-code that a previous preview result produced.
      const res = await env.RELAY_KV.get('res:' + String(args.result_id || ''), 'json');
      if (!res || typeof res.gcode !== 'string') return json({ error: 'start needs a preview result_id with gcode' }, 400);
      args.gcode = res.gcode;
      delete args.result_id;
    }
    const cmd = { id: newId(), type, args, status: 'queued', created: Date.now() };
    await putCommand(env, cmd);
    return json({ command_id: cmd.id, status: cmd.status }, 201);
  }

  if (req.method === 'GET' && url.pathname === '/api/state') {
    const commands = (await listCommands(env, 30)).sort((a, b) => (a.id < b.id ? 1 : -1));
    const results = [];
    const rl = await env.RELAY_KV.list({ prefix: 'res:', limit: 20 });
    for (const k of rl.keys) {
      const v = await env.RELAY_KV.get(k.name, 'json');
      if (v) results.push({ id: v.command_id, ok: v.ok, summary: v.summary, at: v.at });
    }
    return json({ commands: commands.map(({ id, type, status, created }) => ({ id, type, status, created })), results });
  }

  if (req.method === 'GET' && url.pathname.startsWith('/api/result/')) {
    const res = await env.RELAY_KV.get('res:' + url.pathname.slice('/api/result/'.length), 'json');
    return res ? json(res) : json({ error: 'Not found' }, 404);
  }

  return json({ error: 'Not found' }, 404);
}

async function handleAgent(req, env, url) {
  const denied = authorize(req, env, 'agent');
  if (denied) return denied;

  if (req.method === 'GET' && url.pathname === '/api/agent/next') {
    const cmds = await listCommands(env, 20);
    const next = cmds.filter((c) => c.status === 'queued').sort((a, b) => (a.id < b.id ? -1 : 1))[0];
    if (!next) return json({ command: null });
    next.status = 'claimed';
    next.claimed = Date.now();
    await putCommand(env, next);
    return json({ command: next });
  }

  if (req.method === 'GET' && url.pathname.startsWith('/api/agent/upload/')) {
    const id = url.pathname.slice('/api/agent/upload/'.length);
    const buf = await env.RELAY_KV.get('img:' + id, 'arrayBuffer');
    if (!buf) return json({ error: 'Not found' }, 404);
    return new Response(buf, { headers: { 'content-type': 'image/jpeg', 'cache-control': 'no-store' } });
  }

  if (req.method === 'POST' && url.pathname === '/api/agent/result') {
    const body = await readJson(req);
    const cmdId = String(body.command_id || '');
    const cmd = cmdId && (await env.RELAY_KV.get('cmd:' + cmdId, 'json'));
    if (!cmd) return json({ error: 'Unknown command' }, 404);
    const text = JSON.stringify(body.result ?? null);
    if (text.length > MAX_RESULT_BYTES) return json({ error: 'Result over 2 MB' }, 413);
    const result = JSON.parse(text);
    const record = {
      command_id: cmdId, ok: body.ok === true, summary: String(body.summary || '').slice(0, 500),
      at: Date.now(), gcode: typeof body.gcode === 'string' && body.gcode.length < MAX_RESULT_BYTES ? body.gcode : undefined,
      result,
    };
    await env.RELAY_KV.put('res:' + cmdId, JSON.stringify(record));
    cmd.status = record.ok ? 'done' : 'failed';
    cmd.finished = Date.now();
    await putCommand(env, cmd);
    return json({ ok: true });
  }

  return json({ error: 'Not found' }, 404);
}

const PAGE = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Plotter Relay</title>
<style>body{font-family:system-ui;margin:16px;max-width:560px}button{font-size:16px;padding:10px 14px;margin:4px}
input{font-size:16px;width:100%;box-sizing:border-box;padding:8px}pre{white-space:pre-wrap;background:#f4f4f4;padding:8px;font-size:13px}</style>
</head><body>
<h2>Plotter relay</h2>
<p><input id="tok" type="password" placeholder="Relay token" autocomplete="off"></p>
<p><input id="file" type="file" accept="image/jpeg"> <button onclick="upload()">Upload photo</button></p>
<p><button onclick="cmd('status')">Status</button>
<button onclick="cmd('preview')">Preview</button>
<button onclick="cmd('slice')">Slice</button>
<button onclick="cmd('stop')">STOP</button></p>
<p><button onclick="startJob()">Start job (confirm)</button>
<button onclick="jog()">Jog 1 mm X (confirm)</button></p>
<pre id="out">Enter token, then actions.</pre>
<script>
const tok=document.getElementById('tok');tok.value=sessionStorage.getItem('relayTok')||'';
tok.onchange=()=>sessionStorage.setItem('relayTok',tok.value);
const out=document.getElementById('out');
const H=()=>({Authorization:'Bearer '+tok.value});
async function api(path,opts={}){const r=await fetch(path,{...opts,headers:{...H(),...(opts.headers||{})}});const t=await r.text();if(!r.ok)throw new Error(r.status+' '+t);return JSON.parse(t);}
async function show(p){try{out.textContent=JSON.stringify(await p,null,2);}catch(e){out.textContent=String(e);}}
async function upload(){const f=document.getElementById('file').files[0];if(!f)return out.textContent='Pick a JPEG first.';
 sessionStorage.setItem('relayTok',tok.value);await show(api('/api/upload',{method:'POST',headers:{'content-type':'image/jpeg'},body:f}));}
function cmd(type,extra={}){return show(api('/api/command',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({type,args:extra.args||{},confirm:!!extra.confirm})}));}
function startJob(){const id=prompt('Preview result_id to start (exact plotter job):');if(!id)return;
 if(!confirm('START the plotter now? It will move the pen.'))return;cmd('start',{args:{result_id:id},confirm:true});}
function jog(){if(!confirm('Move the pen 1 mm in X? Confirm the plotter is clear.'))return;cmd('jog',{args:{dx:1,dy:0,dz:0},confirm:true});}
setInterval(()=>{if(tok.value)api('/api/state').then(s=>{out.textContent=JSON.stringify(s,null,2)}).catch(()=>{});},5000);
</script></body></html>`;

export default {
  async fetch(req, env) {
    try {
      const url = new URL(req.url);
      if (req.method === 'GET' && url.pathname === '/') {
        return new Response(PAGE, { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });
      }
      if (url.pathname.startsWith('/api/agent/')) return await handleAgent(req, env, url);
      if (url.pathname.startsWith('/api/')) return await handlePhone(req, env, url);
      return json({ error: 'Not found' }, 404);
    } catch (e) {
      return json({ error: e.message || 'Request failed' }, 400);
    }
  },
};
