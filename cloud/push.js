// Web Push (RFC 8291 payload encryption + RFC 8292 VAPID) using only WebCrypto,
// so notifications cost nothing beyond the Worker itself.

const enc = new TextEncoder();

export function b64url(bytes) {
  let s = '';
  for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function fromB64url(str) {
  const s = str.replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(s + '='.repeat((4 - (s.length % 4)) % 4)), (c) => c.charCodeAt(0));
}

function concat(...parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let i = 0;
  for (const p of parts) {
    out.set(p, i);
    i += p.length;
  }
  return out;
}

async function hkdf(salt, ikm, info, bytes) {
  const key = await crypto.subtle.importKey('raw', ikm, 'HKDF', false, ['deriveBits']);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt, info }, key, bytes * 8));
}

// Generates the app's VAPID key pair once and keeps it in D1.
export async function vapidKeys(db) {
  const row = await db.prepare("SELECT value FROM davinci_push_config WHERE key = 'vapid'").first();
  let stored = row && JSON.parse(row.value);
  if (!stored) {
    const pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
    stored = {
      publicKey: b64url(await crypto.subtle.exportKey('raw', pair.publicKey)),
      privateJwk: await crypto.subtle.exportKey('jwk', pair.privateKey),
    };
    // Another request may have raced us; keep whichever landed first.
    await db.prepare("INSERT INTO davinci_push_config (key, value) VALUES ('vapid', ?) ON CONFLICT (key) DO NOTHING")
      .bind(JSON.stringify(stored))
      .run();
    stored = JSON.parse((await db.prepare("SELECT value FROM davinci_push_config WHERE key = 'vapid'").first()).value);
  }
  const privateKey = await crypto.subtle.importKey('jwk', stored.privateJwk, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']);
  return { publicKey: stored.publicKey, privateKey };
}

async function vapidJwt(audience, privateKey, subject) {
  const header = b64url(enc.encode(JSON.stringify({ typ: 'JWT', alg: 'ES256' })));
  const claims = b64url(enc.encode(JSON.stringify({ aud: audience, exp: Math.floor(Date.now() / 1000) + 12 * 3600, sub: subject })));
  const unsigned = `${header}.${claims}`;
  // WebCrypto returns the raw r||s signature JWT expects.
  const sig = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, privateKey, enc.encode(unsigned));
  return `${unsigned}.${b64url(sig)}`;
}

// Encrypts `payload` for one subscription (aes128gcm content coding, single record).
export async function encryptPayload(p256dh, auth, payload) {
  const uaPublic = fromB64url(p256dh);
  const authSecret = fromB64url(auth);
  const local = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
  const asPublic = new Uint8Array(await crypto.subtle.exportKey('raw', local.publicKey));
  const uaKey = await crypto.subtle.importKey('raw', uaPublic, { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({ name: 'ECDH', public: uaKey }, local.privateKey, 256));

  const ikm = await hkdf(authSecret, shared, concat(enc.encode('WebPush: info\0'), uaPublic, asPublic), 32);
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const cek = await hkdf(salt, ikm, enc.encode('Content-Encoding: aes128gcm\0'), 16);
  const nonce = await hkdf(salt, ikm, enc.encode('Content-Encoding: nonce\0'), 12);

  const key = await crypto.subtle.importKey('raw', cek, 'AES-GCM', false, ['encrypt']);
  const plain = concat(enc.encode(payload), new Uint8Array([2])); // 0x02 = last record, no padding
  const cipher = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce }, key, plain));

  const header = new Uint8Array(21);
  header.set(salt, 0);
  new DataView(header.buffer).setUint32(16, 4096);
  header[20] = asPublic.length;
  return concat(header, asPublic, cipher);
}

export async function sendPush(db, sub, message) {
 const {publicKey,privateKey}=await vapidKeys(db);
 const jwt=await vapidJwt(new URL(sub.endpoint).origin,privateKey,'https://da-vinci.caleb-darjany.workers.dev');
 const response=await fetch(sub.endpoint,{method:'POST',redirect:'error',signal:AbortSignal.timeout(15000),headers:{authorization:`vapid t=${jwt}, k=${publicKey}`,'content-encoding':'aes128gcm','content-type':'application/octet-stream',ttl:'900',urgency:'normal'},body:await encryptPayload(sub.p256dh,sub.auth,JSON.stringify(message))});
 return response.status;
}
