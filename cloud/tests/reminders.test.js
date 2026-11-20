import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {initPush,pushAPI,sendReminders,reminderSlot,validateSubscription,HOURS} from '../reminders.js';
import {b64url,fromB64url} from '../push.js';
function database(){
 const sqlite=new DatabaseSync(':memory:');
 sqlite.exec('CREATE TABLE davinci_samples(kind TEXT,data TEXT)');
 const db={prepare(sql){return {args:[],bind(...args){this.args=args;return this;},async first(){return sqlite.prepare(sql).get(...this.args)||null;},async all(){return {results:sqlite.prepare(sql).all(...this.args)};},async run(){return {meta:{changes:Number(sqlite.prepare(sql).run(...this.args).changes)}};}};},async batch(statements){return Promise.all(statements.map(s=>s.run()));}};
 return db;
}
async function subscription(){const keys=await crypto.subtle.generateKey({name:'ECDH',namedCurve:'P-256'},true,['deriveBits']);return {keys,raw:{endpoint:'https://web.push.apple.com/test-device',keys:{p256dh:b64url(await crypto.subtle.exportKey('raw',keys.publicKey)),auth:b64url(crypto.getRandomValues(new Uint8Array(16)))}}};}
async function subscribe(db,raw){return pushAPI(new Request('https://example.com/api/push/subscribe',{method:'POST'}),{DB:db},raw);}
const winter=Date.parse('2026-11-20T17:00:00Z');
test('five daily times in local window, DST, and no late reminders',()=>{
 assert.equal(HOURS.length,5);
 for(let hour=0;hour<24;hour++){const now=Date.parse(`2026-11-20T${String(hour).padStart(2,'0')}:00:00-08:00`);assert.equal(Boolean(reminderSlot(now)),HOURS.includes(hour));}
 assert.equal(reminderSlot(winter),'2026-11-20:09');
 assert.equal(reminderSlot(winter+15*60000),null);
 assert.equal(reminderSlot(Date.parse('2026-07-20T16:00:00Z')),'2026-07-20:09');
 assert.equal(reminderSlot(Date.parse('2026-07-20T17:00:00Z')),null);
});
test('subscription validation prevents arbitrary network targets',async()=>{
 const {raw}=await subscription();assert.equal((await validateSubscription(raw)).endpoint,raw.endpoint);
 for(const endpoint of ['http://fcm.googleapis.com/x','https://127.0.0.1/x','https://evil.push.apple.com.attacker.test/x','https://user@web.push.apple.com/x'])await assert.rejects(validateSubscription({...raw,endpoint}));
 await assert.rejects(validateSubscription({...raw,keys:{...raw.keys,auth:'bad'}}));
});
test('real SQLite stores a device; cron deduplicates and retries failures per device',async()=>{
 const db=database(),{raw}=await subscription();assert.equal((await subscribe(db,raw)).status,200);
 let calls=0;const deliver=async()=>{calls++;return 201;};
 assert.equal((await sendReminders({DB:db},winter,deliver)).sent,1);
 assert.equal((await sendReminders({DB:db},winter+5*60000,deliver)).sent,0);assert.equal(calls,1);
 assert.equal((await sendReminders({DB:db},winter+3*3600000,async()=>503)).sent,0);
 assert.equal((await sendReminders({DB:db},winter+3*3600000+5*60000,deliver)).sent,1);
 await sendReminders({DB:db},winter+6*3600000,async()=>410);
 assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM davinci_push_subscriptions').first()).n,0);
});
test('test notification is encrypted for the browser key, signed, then unsubscribe stops cron',async()=>{
 const db=database(),{raw,keys}=await subscription();await subscribe(db,raw);
 const original=globalThis.fetch;let request;
 globalThis.fetch=async(url,options)=>{request={url,options};return new Response('',{status:201});};
 try{
  const response=await pushAPI(new Request('https://example.com/api/push/test',{method:'POST'}),{DB:db},raw);assert.equal(response.status,200);
  assert.equal(request.url,raw.endpoint);assert.equal(request.options.headers.ttl,'900');
  const auth=request.options.headers.authorization;const [,token,key]=auth.match(/^vapid t=(.*), k=(.*)$/);const [header,claims,signature]=token.split('.');
  const verify=await crypto.subtle.importKey('raw',fromB64url(key),{name:'ECDSA',namedCurve:'P-256'},false,['verify']);
  assert.equal(await crypto.subtle.verify({name:'ECDSA',hash:'SHA-256'},verify,fromB64url(signature),new TextEncoder().encode(header+'.'+claims)),true);
  assert.equal(JSON.parse(new TextDecoder().decode(fromB64url(claims))).aud,'https://web.push.apple.com');
  const bytes=request.options.body,salt=bytes.slice(0,16),asPublic=bytes.slice(21,86),uaPublic=fromB64url(raw.keys.p256dh);
  const peer=await crypto.subtle.importKey('raw',asPublic,{name:'ECDH',namedCurve:'P-256'},false,[]);
  const shared=await crypto.subtle.deriveBits({name:'ECDH',public:peer},keys.privateKey,256);
  const encode=s=>new TextEncoder().encode(s),concat=(...parts)=>new Uint8Array(parts.flatMap(p=>[...new Uint8Array(p)]));
  async function hkdf(salt,secret,info,length){const k=await crypto.subtle.importKey('raw',secret,'HKDF',false,['deriveBits']);return crypto.subtle.deriveBits({name:'HKDF',hash:'SHA-256',salt,info},k,length*8);}
  const ikm=await hkdf(fromB64url(raw.keys.auth),shared,concat(encode('WebPush: info\0'),uaPublic,asPublic),32);
  const cek=await hkdf(salt,ikm,encode('Content-Encoding: aes128gcm\0'),16),nonce=await hkdf(salt,ikm,encode('Content-Encoding: nonce\0'),12);
  const aes=await crypto.subtle.importKey('raw',cek,'AES-GCM',false,['decrypt']);
  const plain=new Uint8Array(await crypto.subtle.decrypt({name:'AES-GCM',iv:nonce},aes,bytes.slice(86)));
  assert.equal(plain.at(-1),2);assert.equal(JSON.parse(new TextDecoder().decode(plain.slice(0,-1))).title,'Da Vinci');
 }finally{globalThis.fetch=original;}
 await pushAPI(new Request('https://example.com/api/push/unsubscribe',{method:'POST'}),{DB:db},raw);
 assert.equal((await sendReminders({DB:db},winter,async()=>{throw new Error('Should not send');})).sent,0);
});
