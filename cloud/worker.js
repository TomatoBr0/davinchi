import assets from './assets.js';
import {pushAPI,sendReminders} from './reminders.js';
import {WORD_SCHEMA,generateWords} from './words.js';
import {generatePractice,summarizeMotion} from './practice.js';

export const SCHEMA = [
...WORD_SCHEMA,
`CREATE TABLE IF NOT EXISTS davinci_samples (
 id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT UNIQUE NOT NULL,
 label TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL,
 data TEXT NOT NULL, image_mime TEXT, image_bytes INTEGER NOT NULL DEFAULT 0,
 point_count INTEGER NOT NULL DEFAULT 0, stroke_count INTEGER NOT NULL DEFAULT 0
)`,
`CREATE TABLE IF NOT EXISTS davinci_image_chunks (
 sample_id INTEGER NOT NULL, part INTEGER NOT NULL, bytes BLOB NOT NULL,
 PRIMARY KEY(sample_id,part)
)`,
`CREATE INDEX IF NOT EXISTS davinci_label ON davinci_samples(label)`];
const MAX_JSON=1_800_000, MAX_IMAGE=2_000_000, CHUNK=65536;
const json=(data,status=200,headers={})=>Response.json(data,{status,headers:{'Cache-Control':'no-store',...headers}});
class InputError extends Error { constructor(message,status=400){super(message);this.status=status;} }
function check(ok,message){if(!ok)throw new InputError(message);}
function finite(n,lo,hi){return typeof n==='number'&&Number.isFinite(n)&&n>=lo&&n<=hi;}
export function validateSample(raw){
 check(raw&&typeof raw==='object'&&!Array.isArray(raw),'Expected a sample');
 check(typeof raw.client_id==='string'&&/^[a-zA-Z0-9-]{16,80}$/.test(raw.client_id),'Invalid sample identifier');
 check(typeof raw.label==='string'&&raw.label.trim().length>0&&raw.label.length<=500,'Add the exact text (up to 500 characters)');
 check(['strokes','photo','trace'].includes(raw.kind),'Invalid sample kind');
 check(finite(raw.width,100,10000)&&finite(raw.height,100,10000),'Invalid canvas dimensions');
 check(typeof raw.notes==='string'&&raw.notes.length<=2000,'Notes must be at most 2000 characters');
 check(typeof raw.before==='string'&&raw.before.length<=80&&typeof raw.after==='string'&&raw.after.length<=80,'Context must be at most 80 characters');
 if(raw.kind==='photo')check(Number.isInteger(raw.image_width)&&raw.image_width>0&&raw.image_width<=1600&&Number.isInteger(raw.image_height)&&raw.image_height>0&&raw.image_height<=1600,'Invalid stored image dimensions');
 const guides=raw.guides;
 check(guides&&['ascender','xheight','baseline','descender'].every(k=>finite(guides[k],0,raw.height)),'Invalid writing guides');
 check(guides.ascender<guides.xheight&&guides.xheight<guides.baseline&&guides.baseline<guides.descender,'Guides must be in order');
 check(Array.isArray(raw.strokes)&&raw.strokes.length<=500,'Too many strokes');
 check(raw.kind==='photo'?raw.strokes.length===0:raw.strokes.length>0,'Record at least one stroke');
 let count=0,previousEnd=-1;
 for(const s of raw.strokes){
  check(s&&Array.isArray(s.points)&&s.points.length>0,'Empty stroke');
  check(['pen','touch','mouse'].includes(s.pointer_type),'Invalid pointer type');
  check(finite(s.start_t,0,86400000)&&finite(s.end_t,s.start_t,86400000)&&s.start_t>=previousEnd,'Invalid stroke timing');
  let last=s.start_t;
  for(const p of s.points){
   check(p&&finite(p.x,0,raw.width)&&finite(p.y,0,raw.height)&&finite(p.t,last,s.end_t),'Invalid point or timestamp');
   check(p.pressure===null||finite(p.pressure,0,1),'Invalid pressure');
   for(const [key,min,max] of [['tilt_x',-90,90],['tilt_y',-90,90],['twist',0,359],['contact_width',0,1000],['contact_height',0,1000]])check(p[key]===null||finite(p[key],min,max),'Invalid '+key);
   last=p.t;count++;
  }
  previousEnd=s.end_t;
 }
 check(count<=8000,'Sample exceeds 8,000 points; save shorter phrases');
 check(raw.reference_id===null||Number.isSafeInteger(raw.reference_id)&&raw.reference_id>0,'Invalid photo reference');
 check(raw.kind==='trace'?raw.reference_id!==null:raw.reference_id===null,'Trace needs a saved photo reference');
 let collection=null;
 if(raw.collection!==undefined&&raw.collection!==null){
  const c=raw.collection;
  check(c&&typeof c==='object'&&typeof c.family_id==='string'&&typeof c.focus==='string'&&/^[a-zA-Z0-9-]{16,80}$/.test(c.family_id)&&/^[a-z]{1,3}$/.test(c.focus)&&Number.isInteger(c.step)&&c.step>=0&&c.step<4&&c.total===4&&['related_words','phrase','repeat'].includes(c.role),'Invalid motion group');
  check((c.step===3&&c.role==='repeat'&&c.repeat_of===0)||(c.step!==3&&c.role!=='repeat'&&c.repeat_of===null),'Invalid repeat reference');
  collection={family_id:c.family_id,focus:c.focus,step:c.step,total:4,role:c.role,repeat_of:c.repeat_of};
 }
 const data={schema_version:1,client_id:raw.client_id,label:raw.label.trim(),kind:raw.kind,width:raw.width,height:raw.height,guides:{...guides},before:raw.before,after:raw.after,notes:raw.notes,strokes:raw.strokes,reference_id:raw.reference_id,coordinate_system:'canvas_top_left_y_down',pressure_source:'browser_reported_unverified',...(collection?{collection}:{}),motion_summary:summarizeMotion(raw),...(raw.image_width&&raw.image_height?{image_width:raw.image_width,image_height:raw.image_height}:{}),...(raw.kind==='trace'?{reference_fit:'contain_center'}:{})};
 return {data,count};
}
const initialized=new WeakMap();
async function schema(db){if(!initialized.has(db))initialized.set(db,db.batch(SCHEMA.map(sql=>db.prepare(sql))).catch(e=>{initialized.delete(db);throw e;}));await initialized.get(db);}
async function readLimited(req,max){
 const reader=req.body?.getReader();check(reader,'Request body required');let total=0,parts=[];
 try {while(true){const {done,value}=await reader.read();if(done)break;total+=value.length;if(total>max){await reader.cancel();throw new InputError('Upload too large',413);}parts.push(value);}} finally{reader.releaseLock();}
 const all=new Uint8Array(total);let i=0;for(const p of parts){all.set(p,i);i+=p.length;}return all;
}
async function bodyJSON(req){try{return JSON.parse(new TextDecoder().decode(await readLimited(req,MAX_JSON)));}catch(e){if(e instanceof InputError)throw e;throw new InputError('Invalid JSON');}}
function imageType(bytes){
 if(bytes[0]===255&&bytes[1]===216&&bytes.at(-2)===255&&bytes.at(-1)===217)return 'image/jpeg';
 if([137,80,78,71,13,10,26,10].every((v,i)=>bytes[i]===v))return 'image/png';
 if(new TextDecoder().decode(bytes.slice(0,4))==='RIFF'&&new TextDecoder().decode(bytes.slice(8,12))==='WEBP')return 'image/webp';
 return null;
}
function parsed(row){const data=JSON.parse(row.data);return {...data,motion_summary:data.motion_summary||summarizeMotion(data),id:row.id,created_at:row.created_at,image_mime:row.image_mime,image_bytes:row.image_bytes,point_count:row.point_count,stroke_count:row.stroke_count};}
export async function handle(req,env){
 const u=new URL(req.url),path=u.pathname;
 if(!path.startsWith('/api/')){
  const asset=assets[path];
  if(!asset)return new Response('Not found',{status:404});
  return new Response(asset.body,{headers:{'Content-Type':asset.type,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}});
 }
 if(path==='/api/health'&&req.method==='GET')return json({app:'Da Vinci',version:1});
 if(req.method!=='GET'&&req.headers.get('Origin')&&req.headers.get('Origin')!==u.origin)return json({error:'Invalid request origin'},403);
 await schema(env.DB);
 if(path.startsWith('/api/push/'))return pushAPI(req,env,req.method==='POST'?await bodyJSON(req):null);
 if(path==='/api/practice'&&req.method==='POST'){
  const raw=await bodyJSON(req),exclude=raw?.exclude||[];check(Array.isArray(exclude)&&exclude.length<=50&&exclude.every(w=>typeof w==='string'&&/^[a-z]{1,3}$/.test(w)),'Invalid recent groups');
  try{return json({families:await generatePractice(env,exclude)});}catch(e){return json({error:e.message},e.status||503);}
 }
 if(path==='/api/patterns'&&req.method==='GET'){
  const rows=await env.DB.prepare("SELECT id,label,data,created_at FROM davinci_samples WHERE kind='strokes' AND json_extract(data,'$.collection.family_id') IS NOT NULL ORDER BY id DESC LIMIT 100").all();
  const grouped=new Map();
  for(const row of rows.results){const sample=JSON.parse(row.data),c=sample.collection;if(!grouped.has(c.family_id))grouped.set(c.family_id,{family_id:c.family_id,focus:c.focus,samples:[]});grouped.get(c.family_id).samples.push({id:row.id,text:row.label,step:c.step,role:c.role,summary:sample.motion_summary||summarizeMotion(sample)});}
  const families=[...grouped.values()].slice(0,20).map(f=>{f.samples.sort((a,b)=>a.step-b.step);const pairs=[];for(let i=0;i<f.samples.length;i++)for(let j=i+1;j<f.samples.length;j++)if(f.samples[i].text===f.samples[j].text)pairs.push([f.samples[i].id,f.samples[j].id]);return {...f,repeat_pairs:pairs};});
  const oldRows=await env.DB.prepare("SELECT id,label,data FROM davinci_samples WHERE kind='strokes' AND json_extract(data,'$.collection.family_id') IS NULL AND label IN (SELECT label FROM davinci_samples WHERE kind='strokes' AND json_extract(data,'$.collection.family_id') IS NULL GROUP BY label HAVING COUNT(*)>1) ORDER BY id DESC LIMIT 60").all();
  const earlier=new Map();for(const row of oldRows.results){if(!earlier.has(row.label))earlier.set(row.label,[]);const sample=JSON.parse(row.data);earlier.get(row.label).push({id:row.id,text:row.label,step:0,role:'earlier',summary:sample.motion_summary||summarizeMotion(sample)});}
  for(const [label,samples] of earlier)if(samples.length>1)families.push({family_id:'earlier:'+label,focus:label,legacy:true,samples,repeat_pairs:[[samples.at(-1).id,samples[0].id]]});
  return json({families});
 }
 if(path==='/api/words'&&req.method==='POST'){
  const raw=await bodyJSON(req),exclude=raw?.exclude||[];check(Array.isArray(exclude)&&exclude.length<=300&&exclude.every(w=>typeof w==='string'&&/^[a-z]{3,12}$/.test(w)),'Invalid recent words');
  try{return json({words:await generateWords(env,exclude)});}catch(e){return json({error:e.message},e.status||503);}
 }
 if(path==='/api/stats'&&req.method==='GET'){
  const totals=await env.DB.prepare('SELECT COUNT(*) AS samples, COALESCE(SUM(point_count),0) AS points, COUNT(DISTINCT label) AS labels, COALESCE(SUM(kind=\'photo\'),0) AS photos FROM davinci_samples').first();
  const labels=await env.DB.prepare('SELECT label,COUNT(*) AS variants FROM davinci_samples GROUP BY label ORDER BY variants ASC,label LIMIT 100').all();
  return json({...totals,coverage:labels.results});
 }
 if(path==='/api/samples'&&req.method==='GET'){
  const before=Number(u.searchParams.get('before')||Number.MAX_SAFE_INTEGER),limit=Math.min(50,Math.max(1,Number(u.searchParams.get('limit')||20)));
  check(Number.isSafeInteger(before)&&Number.isInteger(limit),'Invalid pagination');
  const query=u.searchParams.get('q')||'',kind=u.searchParams.get('kind')||'';
  const rows=await env.DB.prepare(`SELECT id,label,kind,created_at,image_mime,image_bytes,point_count,stroke_count FROM davinci_samples WHERE id<? AND instr(lower(label),lower(?))>0 AND (?='' OR kind=?) ORDER BY id DESC LIMIT ?`).bind(before,query,kind,kind,limit+1).all();
  const items=rows.results.slice(0,limit);return json({samples:items,next:rows.results.length>limit?items.at(-1).id:null});
 }
 if(path==='/api/samples'&&req.method==='POST'){
  let raw,bytes=null,mime=null;
  if(req.headers.get('Content-Type')?.includes('multipart/form-data')){
   const bounded=await readLimited(req,MAX_IMAGE+MAX_JSON+10000);
   const form=await new Request(req.url,{method:'POST',headers:{'Content-Type':req.headers.get('Content-Type')},body:bounded}).formData();
   try{raw=JSON.parse(form.get('sample'));}catch{throw new InputError('Invalid photo metadata');}
   const file=form.get('image');check(file&&typeof file.arrayBuffer==='function'&&file.size>0&&file.size<=MAX_IMAGE,'Photo must be under 2 MB');
   bytes=new Uint8Array(await file.arrayBuffer());mime=imageType(bytes);check(mime,'Use a JPEG, PNG or WebP image');
  }else raw=await bodyJSON(req);
  const {data,count}=validateSample(raw);
  check((data.kind==='photo')===!!bytes,'Photo samples require an image; writing samples use points');
  if(data.reference_id){const ref=await env.DB.prepare('SELECT id FROM davinci_samples WHERE id=? AND kind=\'photo\'').bind(data.reference_id).first();check(ref,'Reference photo is missing');}
  const existing=await env.DB.prepare('SELECT * FROM davinci_samples WHERE client_id=?').bind(data.client_id).first();
  if(existing){const {motion_summary:oldSummary,...oldData}=JSON.parse(existing.data);const {motion_summary:newSummary,...newData}=data;check(JSON.stringify(oldData)===JSON.stringify(newData),'Sample identifier already exists with different content');return json({sample:parsed(existing),duplicate:true});}
  const created=new Date().toISOString();
  const statements=[env.DB.prepare('INSERT INTO davinci_samples(client_id,label,kind,created_at,data,image_mime,image_bytes,point_count,stroke_count) VALUES(?,?,?,?,?,?,?,?,?)').bind(data.client_id,data.label,data.kind,created,JSON.stringify(data),mime,bytes?.length||0,count,data.strokes.length)];
  if(bytes)for(let i=0;i<bytes.length;i+=CHUNK)statements.push(env.DB.prepare('INSERT INTO davinci_image_chunks(sample_id,part,bytes) SELECT id,?,? FROM davinci_samples WHERE client_id=?').bind(i/CHUNK,bytes.slice(i,i+CHUNK).buffer,data.client_id));
  await env.DB.batch(statements);
  const saved=await env.DB.prepare('SELECT * FROM davinci_samples WHERE client_id=?').bind(data.client_id).first();
  return json({sample:parsed(saved)},201);
 }
 const match=path.match(/^\/api\/samples\/(\d+)(\/image)?$/);
 if(match){
  const id=Number(match[1]);check(Number.isSafeInteger(id),'Invalid sample id');
  const row=await env.DB.prepare('SELECT * FROM davinci_samples WHERE id=?').bind(id).first();
  if(!row)return json({error:'Sample not found'},404);
  if(match[2]&&req.method==='GET'){
   if(!row.image_mime)return json({error:'No photo'},404);
   const chunks=await env.DB.prepare('SELECT bytes FROM davinci_image_chunks WHERE sample_id=? ORDER BY part').bind(id).all();
   const out=new Uint8Array(row.image_bytes);let offset=0;for(const c of chunks.results){const b=new Uint8Array(c.bytes);out.set(b,offset);offset+=b.length;}
   if(offset!==row.image_bytes)throw new Error('Incomplete stored photo');
   return new Response(out,{headers:{'Content-Type':row.image_mime,'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}});
  }
  if(!match[2]&&req.method==='GET')return json({sample:parsed(row)});
  if(!match[2]&&req.method==='DELETE'){
   const reference=await env.DB.prepare("SELECT id FROM davinci_samples WHERE json_extract(data,'$.reference_id')=? LIMIT 1").bind(id).first();
   if(reference)return json({error:'Delete this photo’s traced samples first'},409);
   await env.DB.batch([env.DB.prepare('DELETE FROM davinci_image_chunks WHERE sample_id=?').bind(id),env.DB.prepare('DELETE FROM davinci_samples WHERE id=?').bind(id)]);return json({deleted:true});
  }
 }
 return json({error:'Not found'},404);
}
export default {async fetch(req,env){try{return await handle(req,env);}catch(e){if(e instanceof InputError)return json({error:e.message},e.status);console.error('Da Vinci request failed',e?.message);return json({error:'Unable to complete request. Your draft is still on this device; try again.'},500);}},async scheduled(event,env){console.log(JSON.stringify({task:'writing_reminder',...await sendReminders(env,event.scheduledTime)}));}};

