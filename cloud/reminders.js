import {vapidKeys,fromB64url,sendPush} from './push.js';
export const PUSH_SCHEMA=[
 'CREATE TABLE IF NOT EXISTS davinci_push_config (key TEXT PRIMARY KEY,value TEXT NOT NULL)',
 'CREATE TABLE IF NOT EXISTS davinci_push_subscriptions (endpoint TEXT PRIMARY KEY,p256dh TEXT NOT NULL,auth TEXT NOT NULL,last_slot TEXT,created_at TEXT NOT NULL)',
];
export const HOURS=[9,12,15,18,21];
export const TIMEZONE='America/Los_Angeles';
export async function initPush(db){await db.batch(PUSH_SCHEMA.map(sql=>db.prepare(sql)));}
export function reminderSlot(now){
 const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:TIMEZONE,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(now)).map(p=>[p.type,p.value]));
 return HOURS.includes(Number(parts.hour))&&Number(parts.minute)<15?`${parts.year}-${parts.month}-${parts.day}:${parts.hour}`:null;
}
export async function validateSubscription(raw){
 if(!raw||typeof raw.endpoint!=='string'||raw.endpoint.length>2048)throw new Error('Invalid push subscription');
 const url=new URL(raw.endpoint),host=url.hostname;
 if(url.protocol!=='https:'||url.port||url.username||url.password||url.hash||!(host==='fcm.googleapis.com'||host==='updates.push.services.mozilla.com'||host.endsWith('.push.apple.com')||host.endsWith('.notify.windows.com')))throw new Error('Unsupported push service');
 const p256dh=raw.keys?.p256dh,auth=raw.keys?.auth;
 if(typeof p256dh!=='string'||typeof auth!=='string'||!/^[A-Za-z0-9_-]{87}$/.test(p256dh)||!/^[A-Za-z0-9_-]{22}$/.test(auth))throw new Error('Invalid subscription keys');
 if(fromB64url(auth).length!==16)throw new Error('Invalid authentication key');
 await crypto.subtle.importKey('raw',fromB64url(p256dh),{name:'ECDH',namedCurve:'P-256'},false,[]);
 return {endpoint:raw.endpoint,p256dh,auth};
}
const reply=(obj,status=200)=>Response.json(obj,{status,headers:{'Cache-Control':'no-store'}});
export async function pushAPI(req,env,raw){
 await initPush(env.DB);
 const path=new URL(req.url).pathname;
 if(path==='/api/push/key'&&req.method==='GET')return reply({publicKey:(await vapidKeys(env.DB)).publicKey,hours:HOURS,timezone:TIMEZONE});
 if(req.method!=='POST')return reply({error:'Not found'},404);
 let sub;try{sub=await validateSubscription(raw);}catch{return reply({error:'Invalid or unsupported push subscription'},400);}
 if(path==='/api/push/subscribe'){
  const existing=await env.DB.prepare('SELECT endpoint FROM davinci_push_subscriptions WHERE endpoint=?').bind(sub.endpoint).first();
  if(!existing){const count=await env.DB.prepare('SELECT COUNT(*) AS n FROM davinci_push_subscriptions').first();if(count.n>=20)return reply({error:'Device limit reached'},429);}
  await env.DB.prepare('INSERT INTO davinci_push_subscriptions(endpoint,p256dh,auth,created_at) VALUES(?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh,auth=excluded.auth').bind(sub.endpoint,sub.p256dh,sub.auth,new Date().toISOString()).run();
  return reply({ok:true});
 }
 if(path==='/api/push/unsubscribe'){
  await env.DB.prepare('DELETE FROM davinci_push_subscriptions WHERE endpoint=? AND auth=? AND p256dh=?').bind(sub.endpoint,sub.auth,sub.p256dh).run();return reply({ok:true});
 }
 if(path==='/api/push/test'){
  const saved=await env.DB.prepare('SELECT endpoint FROM davinci_push_subscriptions WHERE endpoint=? AND auth=? AND p256dh=?').bind(sub.endpoint,sub.auth,sub.p256dh).first();
  if(!saved)return reply({error:'Enable reminders first'},404);
  const status=await sendPush(env.DB,sub,{title:'Da Vinci',body:'Reminders are on. Got five minutes? Do a quick writing session.',url:'/',tag:'davinci-test'});
  if(status===404||status===410)await env.DB.prepare('DELETE FROM davinci_push_subscriptions WHERE endpoint=?').bind(sub.endpoint).run();
  return reply({ok:status>=200&&status<300},status>=200&&status<300?200:502);
 }
 return reply({error:'Not found'},404);
}
async function reminderMessage(db,slot){
 let body='Got five minutes? Do a quick writing session. Write naturally—the app will pick a motion group.';
 try{
  const row=await db.prepare("SELECT json_extract(data,'$.collection.focus') AS focus,COUNT(*) AS n FROM davinci_samples WHERE kind='strokes' AND json_extract(data,'$.collection.focus') IS NOT NULL GROUP BY focus ORDER BY n,focus LIMIT 1").first();
  if(row&&/^[a-z]{1,3}$/.test(row.focus))body=`Got five minutes? Try a few words with “${row.focus}”. Write naturally, without tracing.`;
 }catch{console.warn(JSON.stringify({task:'writing_reminder',status:'focus_unavailable'}));}
 return {title:'Da Vinci · Writing break',body,url:'/',tag:'writing-'+slot};
}
export async function sendReminders(env,now=Date.now(),deliver=sendPush){
 const slot=reminderSlot(now);if(!slot)return {sent:0};
 await initPush(env.DB);
 const {results}=await env.DB.prepare('SELECT * FROM davinci_push_subscriptions WHERE last_slot IS NULL OR last_slot<>? LIMIT 20').bind(slot).all();
 if(!results.length)return {sent:0};
 const message=await reminderMessage(env.DB,slot);let sent=0;
 for(const sub of results){
  const claim=await env.DB.prepare('UPDATE davinci_push_subscriptions SET last_slot=? WHERE endpoint=? AND (last_slot IS NULL OR last_slot<>?)').bind(slot,sub.endpoint,slot).run();
  if(!claim.meta.changes)continue;
  try{
   const status=await deliver(env.DB,sub,message);
   if(status===404||status===410)await env.DB.prepare('DELETE FROM davinci_push_subscriptions WHERE endpoint=?').bind(sub.endpoint).run();
   else if(status>=200&&status<300)sent++;
   else throw new Error('Push service rejected delivery');
  }catch{
   await env.DB.prepare('UPDATE davinci_push_subscriptions SET last_slot=NULL WHERE endpoint=? AND last_slot=?').bind(sub.endpoint,slot).run();
   console.warn(JSON.stringify({task:'writing_reminder',status:'delivery_failed'}));
  }
 }
 return {sent};
}
