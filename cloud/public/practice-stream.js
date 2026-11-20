const wordOK=w=>typeof w==='string'&&/^[a-z]+(?:'[a-z]+)?$/.test(w)&&w.length>=2&&w.length<=12;
export function validFamily(f){return f&&typeof f.family_id==='string'&&/^[a-zA-Z0-9-]{16,80}$/.test(f.family_id)&&/^[a-z]{1,3}$/.test(f.focus)&&Array.isArray(f.words)&&f.words.length===3&&new Set(f.words).size===3&&f.words.every(w=>wordOK(w)&&w.includes(f.focus))&&typeof f.phrase==='string'&&f.phrase.length<=30&&f.phrase.split(' ').length>=2&&f.phrase.split(' ').length<=3&&f.phrase.split(' ').every(wordOK)&&f.phrase.includes(f.focus);}
export function validTask(t){return t&&typeof t.text==='string'&&t.text.length<=40&&/^[a-z ']{2,40}$/.test(t.text)&&typeof t.family_id==='string'&&/^[a-zA-Z0-9-]{16,80}$/.test(t.family_id)&&/^[a-z]{1,3}$/.test(t.focus)&&Number.isInteger(t.step)&&t.step>=0&&t.step<4&&t.total===4&&['related_words','phrase','repeat'].includes(t.role)&&((t.step===3&&t.role==='repeat'&&t.repeat_of===0)||(t.step!==3&&t.role!=='repeat'&&t.repeat_of===null));}
export function familyTasks(f){
 const pair=f.words[0]+' '+f.words[1];
 return [{text:pair,role:'related_words'},{text:f.words[1]+' '+f.words[2],role:'related_words'},{text:f.phrase,role:'phrase'},{text:pair,role:'repeat'}].map((item,step)=>({...item,family_id:f.family_id,focus:f.focus,step,total:4,repeat_of:step===3?0:null}));
}
export class PracticeStream{
 constructor(fetchBatch){this.fetchBatch=fetchBatch;this.families=[];this.tasks=[];this.recent=[];this.pending=null;}
 snapshot(){return {families:this.families,tasks:this.tasks,recent:this.recent};}
 restore(state={}){this.families=(state.families||[]).filter(validFamily);this.tasks=(state.tasks||[]).filter(validTask);this.recent=(state.recent||[]).filter(x=>/^[a-z]{1,3}$/.test(x)).slice(-40);}
 async refill(){if(this.pending)return this.pending;this.pending=(async()=>{const result=await this.fetchBatch(this.recent);const families=result.filter(validFamily);if(!families.length)throw new Error('No usable groups returned. Try again.');this.families.push(...families);})();try{await this.pending;}finally{this.pending=null;}}
 async next(){if(!this.tasks.length){if(!this.families.length)await this.refill();const f=this.families.shift();this.recent.push(f.focus);this.recent=this.recent.slice(-40);this.tasks=familyTasks(f);if(!this.families.length)this.refill().catch(()=>{});}return this.tasks.shift();}
}
