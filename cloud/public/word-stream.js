const valid=w=>typeof w==='string'&&/^[a-z]{3,12}$/.test(w);
export class WordStream{
 constructor(fetchBatch){this.fetchBatch=fetchBatch;this.queue=[];this.recent=[];this.pending=null;}
 restore(state={}){this.recent=(state.recent||[]).filter(valid).slice(-200);const used=new Set(this.recent);this.queue=[...new Set((state.queue||[]).filter(valid))].filter(w=>!used.has(w));}
 snapshot(){return {queue:[...this.queue],recent:[...this.recent]};}
 async refill(){
  if(this.pending)return this.pending;
  this.pending=(async()=>{const excluded=[...this.recent,...this.queue],used=new Set(excluded);const batch=await this.fetchBatch(excluded);const words=[...new Set(batch.filter(valid))].filter(w=>!used.has(w));if(!words.length)throw new Error('No fresh words returned. Try again.');this.queue.push(...words);})();
  try{await this.pending;}finally{this.pending=null;}
 }
 async next(){if(!this.queue.length)await this.refill();const word=this.queue.shift();this.recent.push(word);this.recent=this.recent.slice(-200);if(this.queue.length<6)this.refill().catch(()=>{});return word;}
}
