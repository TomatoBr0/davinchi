export const WORD_SCHEMA=[
 'CREATE TABLE IF NOT EXISTS davinci_generated_words (word TEXT PRIMARY KEY, created_at TEXT NOT NULL)',
 'CREATE TABLE IF NOT EXISTS davinci_word_budget (day TEXT PRIMARY KEY, requests INTEGER NOT NULL)'
];
export function parseWords(response){
 const text=typeof response==='string'?response:typeof response?.response==='string'?response.response:response?.choices?.[0]?.message?.content;
 let words=Array.isArray(response)?response:Array.isArray(response?.response)?response.response:null;
 if(!words){if(typeof text!=='string')return [];try{words=JSON.parse(text.slice(text.indexOf('['),text.lastIndexOf(']')+1));}catch{return [];}}
 return Array.isArray(words)?[...new Set(words.filter(w=>typeof w==='string').map(w=>w.trim().toLowerCase()).filter(w=>/^[a-z]{3,12}$/.test(w)))].slice(0,40):[];
}
const fail=(message,status=503)=>Object.assign(new Error(message),{status});
export async function generateWords(env,exclude=[]){
 if(!env.AI)throw fail('Word generation is unavailable. Try again shortly.');
 const day=new Date().toISOString().slice(0,10);
 const budget=await env.DB.prepare('INSERT INTO davinci_word_budget(day,requests) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET requests=requests+1 WHERE requests<64 RETURNING requests').bind(day).first();
 if(!budget)throw fail('Today’s word generation allowance is used up. You can still enter your own words.',429);
 const recent=await env.DB.prepare('SELECT word FROM davinci_generated_words ORDER BY created_at DESC LIMIT 160').all();
 const avoid=[...new Set([...exclude,...recent.results.map(r=>r.word)])].slice(-200);
 let response;
 try{response=await env.AI.run('@cf/meta/llama-3.1-8b-instruct-fast',{messages:[{role:'system',content:'Generate varied real English words for handwriting practice. Output ONLY a JSON array of 40 different single lowercase words, each 3 to 12 letters. Use a mix of everyday nouns, verbs, adjectives and lengths, with varied letter shapes. No phrases, numbers, invented words, names, explanations or offensive words.'},{role:'user',content:'Generate a fresh random selection. Random seed: '+crypto.randomUUID()+'. Do not use these previously shown words: '+avoid.join(', ')}],max_tokens:420,temperature:1.1});}catch{throw fail('Could not generate new words. Try again; your writing is still saved.');}
 const candidates=parseWords(response).filter(w=>!avoid.includes(w));
 if(!candidates.length)throw fail('No new words were returned. Try again.');
 const found=await env.DB.prepare('SELECT word FROM davinci_generated_words WHERE word IN ('+candidates.map(()=>'?').join(',')+')').bind(...candidates).all();
 const used=new Set(found.results.map(r=>r.word)),words=candidates.filter(w=>!used.has(w));
 if(!words.length)throw fail('The generator repeated earlier words. Try again for a fresh batch.');
 const now=new Date().toISOString();
 await env.DB.batch(words.map(w=>env.DB.prepare('INSERT OR IGNORE INTO davinci_generated_words(word,created_at) VALUES(?,?)').bind(w,now)));
 return words;
}

