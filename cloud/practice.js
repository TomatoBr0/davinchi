const CLUSTERS=['th','sh','ch','wh','st','tr','br','cl','cr','dr','fl','fr','gl','gr','pl','pr','sc','sk','sl','sm','sn','sp','sw','bl','str','ing','ed','er','ly','oo','ee','ea','ou','ai','ar','or','ow','qu','ck','ll','tt','ss',...'abcdefghijklmnopqrstuvwxyz'];
const normalize=s=>typeof s==='string'?s.trim().toLowerCase().replace(/[’‘]/g,"'").replace(/\s+/g,' '):'';
const wordOK=w=>/^[a-z]+(?:'[a-z]+)?$/.test(w)&&w.length>=2&&w.length<=12;
export function parseFamilies(response){
 let raw=Array.isArray(response)?response:Array.isArray(response?.response)?response.response:null;
 const text=typeof response==='string'?response:typeof response?.response==='string'?response.response:response?.choices?.[0]?.message?.content;
 if(!raw){if(typeof text!=='string')return [];try{raw=JSON.parse(text.slice(text.indexOf('['),text.lastIndexOf(']')+1));}catch{raw=[];for(const chunk of text.match(/\{[^{}]*\}/g)||[])try{raw.push(JSON.parse(chunk));}catch{}}}
 if(!Array.isArray(raw))return [];
 const result=[],seen=new Set();
 for(const row of raw){
  const focus=normalize(row?.focus),words=Array.isArray(row?.words)?[...new Set(row.words.map(normalize))]:[],phrase=normalize(row?.phrase);
  if(!/^[a-z]{1,3}$/.test(focus)||seen.has(focus)||words.length<3||!words.slice(0,3).every(w=>wordOK(w)&&w.includes(focus)))continue;
  if(phrase.length>30||phrase.split(' ').length<2||phrase.split(' ').length>3||!phrase.split(' ').every(wordOK)||!phrase.includes(focus))continue;
  result.push({family_id:crypto.randomUUID(),focus,words:words.slice(0,3),phrase});seen.add(focus);if(result.length===6)break;
 }
 return result;
}
export function chooseFocus(labels,exclude=[],random=Math.random){
 const rows=labels.map(x=>({text:x.label.toLowerCase(),count:Number(x.variants)||1}));
 const recent=new Set(exclude.slice(-12));
 const candidates=CLUSTERS.filter(s=>!recent.has(s)).map(focus=>{const count=rows.reduce((n,r)=>n+(r.text.includes(focus)?r.count:0),0);return {focus,score:-Math.log(Math.max(.000001,random()))*(1+count)};});
 return candidates.sort((a,b)=>a.score-b.score).slice(0,6).map(x=>x.focus);
}
const fail=(message,status=503)=>Object.assign(new Error(message),{status});
export async function generatePractice(env,exclude=[]){
 if(!env.AI)throw fail('New groups are unavailable. You can still write your own text.');
 const labels=await env.DB.prepare("SELECT label,COUNT(*) AS variants FROM davinci_samples WHERE kind='strokes' GROUP BY label").all();
 let targets=chooseFocus(labels.results,exclude).slice(0,2);
 const collected=await env.DB.prepare("SELECT COUNT(*) AS n FROM davinci_samples WHERE json_extract(data,'$.collection.family_id') IS NOT NULL").first();
 if(!collected.n&&!exclude.includes('th'))targets=['th',...targets.filter(x=>x!=='th')].slice(0,2);
 const budget=await env.DB.prepare('INSERT INTO davinci_word_budget(day,requests) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET requests=requests+1 WHERE requests<64 RETURNING requests').bind(new Date().toISOString().slice(0,10)).first();
 if(!budget)throw fail('Today’s generation allowance is used up. Saved groups and custom text still work.',429);
 let response;try{response=await env.AI.run('@cf/meta/llama-3.1-8b-instruct-fast',{messages:[{role:'system',content:`Generate English handwriting motion study families. Return ONLY a JSON array of objects with keys focus, words, phrase. Each focus is a shared letter sequence. Each words array has THREE distinct real everyday words ALL containing that exact focus. Prefer related variants and endings where possible, including common contractions with apostrophes. Each phrase is a natural 2-3 word phrase containing the focus, max 30 characters. Use lowercase. No invented words, explanations, names or offensive content. Example format: [{"focus":"th","words":["their","theirs","that's"],"phrase":"that's theirs"}]. Produce exactly two different families for the requested focuses.`},{role:'user',content:'Focus sequences with fewer collected examples: '+targets.join(', ')+'. Fresh variation seed '+crypto.randomUUID()+'. Use the example only if th was requested; do not copy it every time.'}],max_tokens:900,temperature:.9});}catch{throw fail('Could not generate the next group. Try again; your writing is safe.');}
 const families=parseFamilies(response).filter(f=>targets.includes(f.focus)).sort((a,b)=>targets.indexOf(a.focus)-targets.indexOf(b.focus));
 if(!families.length)throw fail('No usable related-word groups returned. Please try again.');
 return families;
}
export function summarizeMotion(sample){
 const strokes=sample.strokes||[],height=Math.max(1,(sample.guides?.baseline||1)-(sample.guides?.xheight||0));
 let down=0,up=0,length=0,points=0,nonzero=false;const pressures=new Set();
 for(let i=0;i<strokes.length;i++){const s=strokes[i];down+=Math.max(0,s.end_t-s.start_t);if(i)up+=Math.max(0,s.start_t-strokes[i-1].end_t);for(let j=0;j<s.points.length;j++){const p=s.points[j];points++;if(p.pressure!==null&&p.pressure!==undefined){pressures.add(p.pressure);if(p.pressure>0)nonzero=true;}if(j)length+=Math.hypot(p.x-s.points[j-1].x,p.y-s.points[j-1].y);}}
 return {duration_ms:Math.round(down+up),pen_down_ms:Math.round(down),pen_up_ms:Math.round(up),stroke_count:strokes.length,point_count:points,path_length_xheight:Math.round(length/height*100)/100,pressure_available:nonzero&&pressures.size>1};
}

