// Run: node cloud/relay/test_worker.mjs   (no deps, in-memory KV, no network)
import assert from 'node:assert/strict';
import worker from './worker.js';

function memKV() {
  const m = new Map();
  return {
    async get(k, type) { if (!m.has(k)) return null; const v = m.get(k); return type === 'json' ? JSON.parse(v) : type === 'arrayBuffer' ? v : v; },
    async put(k, v) { m.set(k, v instanceof ArrayBuffer ? v : String(v)); },
    async list({ prefix = '', limit = 1000 }) {
      return { keys: [...m.keys()].filter((k) => k.startsWith(prefix)).slice(0, limit).map((name) => ({ name })) };
    },
  };
}

const env = { RELAY_KV: memKV(), RELAY_TOKEN: 'phone-secret', AGENT_TOKEN: 'agent-secret' };
const call = (path, init = {}) => worker.fetch(new Request('https://x.test' + path, init), env);
const phone = { authorization: 'Bearer phone-secret' };
const agent = { authorization: 'Bearer agent-secret' };
const json = (h, body) => ({ method: 'POST', headers: { ...h, 'content-type': 'application/json' }, body: JSON.stringify(body) });

// auth on every route
assert.equal((await call('/api/state')).status, 401);
assert.equal((await call('/api/state', { headers: phone })).status, 200);
assert.equal((await call('/api/agent/next', { headers: phone })).status, 401, 'phone token must not work for agent');
assert.equal((await call('/api/agent/next', { headers: { authorization: 'Bearer nope' } })).status, 401);

// upload is JPEG only, then enqueues a forward command
let r = await call('/api/upload', { method: 'POST', headers: { ...phone, 'content-type': 'image/png' }, body: new Uint8Array([1]) });
assert.equal(r.status, 415);
r = await call('/api/upload', { method: 'POST', headers: { ...phone, 'content-type': 'image/jpeg' }, body: new Uint8Array([0xff, 0xd8, 1]) });
assert.equal(r.status, 201);

// motion needs confirm, jog range is capped, stop needs no confirm
assert.equal((await call('/api/command', json(phone, { type: 'jog', args: { dx: 1 } }))).status, 409);
assert.equal((await call('/api/command', json(phone, { type: 'jog', args: { dx: 99 }, confirm: true }))).status, 400);
assert.equal((await call('/api/command', json(phone, { type: 'stop' }))).status, 201);
assert.equal((await call('/api/command', json(phone, { type: 'rm -rf' }))).status, 400);

// start without a preview result is refused
assert.equal((await call('/api/command', json(phone, { type: 'start', args: { result_id: 'none' }, confirm: true }))).status, 400);

// laptop claims oldest queued command, uploads are fetchable, result is stored
r = await call('/api/agent/next', { headers: agent });
const first = (await r.json()).command;
assert.equal(first.type, 'handwriting_upload');
const img = await call('/api/agent/upload/' + first.args.upload_id, { headers: agent });
assert.equal(img.status, 200);
assert.equal(new Uint8Array(await img.arrayBuffer())[0], 0xff);

r = await call('/api/agent/result', json(agent, { command_id: first.id, ok: true, summary: 'done', result: { n: 1 }, gcode: 'G1 X1' }));
assert.equal(r.status, 200);
r = await call('/api/state', { headers: phone });
const state = await r.json();
assert.ok(state.results.some((x) => x.id === first.id && x.ok === true));

// start now accepts a preview result that carries gcode
r = await call('/api/command', json(phone, { type: 'start', args: { result_id: first.id }, confirm: true }));
assert.equal(r.status, 201);
console.log('test_worker: all assertions passed');
