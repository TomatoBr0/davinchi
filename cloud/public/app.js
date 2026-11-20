import {PracticeStream,validTask} from './practice-stream.js?v=motion-study-1';
import {captureGeometry,capturePoint,randomWordPlacement} from './capture-geometry.js?v=motion-study-1';
const $=id=>document.getElementById(id);
const canvas=$('ink'),ctx=canvas.getContext('2d');
let W=1000,H=560;
let GUIDES={ascender:100,xheight:235,baseline:400,descender:500};
let strokes=[],current=null,pointer=null,startTime=null,clientId=crypto.randomUUID(),reference=null,referenceImage=null;
let replayToken=0,saving=false,photo=null,photoURL=null,photoId=crypto.randomUUID(),next=null,currentSample=null,loadToken=0;
let promptWord='',changingWord=false,activeTask=null;
const practice=new PracticeStream(async exclude=>(await api('/api/practice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({exclude})})).families);
const message=(id,text,error=false)=>{const el=$(id);el.textContent=text;el.classList.toggle('error',error);if(id==='write-message'){$('focus-feedback').textContent=text;$('focus-feedback').classList.toggle('error',error);}};
const round=n=>Math.round(n*1000)/1000;
const nullable=n=>typeof n==='number'&&Number.isFinite(n)?n:null;
const storage=new Promise((resolve,reject)=>{const req=indexedDB.open('davinci-studio',1);req.onupgradeneeded=()=>req.result.createObjectStore('drafts');req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});
async function draftOp(method,key,value){const db=await storage;return new Promise((resolve,reject)=>{const tx=db.transaction('drafts',method==='get'?'readonly':'readwrite'),store=tx.objectStore('drafts');const req=method==='get'?store.get(key):method==='delete'?store.delete(key):store.put(value,key);let result;req.onsuccess=()=>result=req.result;tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});}
let draftTimer,lastDraftAt=0;
function inkDraft(){return {strokes,clientId,reference,promptWord,activeTask,practiceState:practice.snapshot(),width:W,height:H,guides:GUIDES,label:$('label').value,before:$('before').value,after:$('after').value,notes:$('notes').value};}
function persistInk(){lastDraftAt=Date.now();clearTimeout(draftTimer);const snapshot=structuredClone(inkDraft());draftOp('put','ink',snapshot).then(()=>{$('draft-status').textContent='Draft saved on this device.';}).catch(()=>{$('draft-status').textContent='Device storage unavailable — keep this page open until saved.';});}
function scheduleInk(){clearTimeout(draftTimer);draftTimer=setTimeout(persistInk,250);}
function persistPhoto(){draftOp('put','photo',{photo,photoId,label:$('photo-label').value,notes:$('photo-notes').value}).catch(()=>message('photo-message','Device storage unavailable. Keep this page open until saved.',true));}
async function api(path,options={}){const response=await fetch(path,options);let data;try{data=await response.json();}catch{throw new Error('Unexpected response. Your draft is still here.');}if(!response.ok)throw new Error(data.error||'Request failed');return data;}
function tab(name){document.querySelectorAll('.tab-panel').forEach(el=>el.hidden=el.id!==name);document.querySelectorAll('[data-tab]').forEach(b=>{b.classList.toggle('active',b.dataset.tab===name);if(b.dataset.tab===name)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});if(name==='dataset'){loadSamples();loadPatterns();}}
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>tab(b.dataset.tab)));
function traceBackground(context){if(!referenceImage)return;const scale=Math.min(W/referenceImage.width,H/referenceImage.height),w=referenceImage.width*scale,h=referenceImage.height*scale;context.save();context.globalAlpha=.3;context.drawImage(referenceImage,(W-w)/2,(H-h)/2,w,h);context.restore();}
function prepareWordGuide(context){
 const word=($('label').value.trim()||promptWord);
 if(strokes.length||reference||!word)return null;
 const spacing=GUIDES.line_spacing||(GUIDES.baseline-GUIDES.xheight)*2;
 const unit=spacing/(GUIDES.line_spacing_px||56),inset=Math.min(W*.12,52*unit);
 let size=(GUIDES.baseline-GUIDES.xheight)*2;
 context.save();context.font=`italic ${size}px Georgia,serif`;
 let wordWidth=context.measureText(word).width;
 if(wordWidth>W-2*inset){size*=(W-2*inset)/wordWidth;context.font=`italic ${size}px Georgia,serif`;wordWidth=context.measureText(word).width;}
 context.restore();
 let placement=GUIDES.prompt_position;
 if(!placement||placement.word!==word||placement.canvas_width!==W||placement.canvas_height!==H){
  const point=randomWordPlacement(W,H,wordWidth,spacing);
  const delta=point.baseline-GUIDES.baseline;
  for(const key of ['ascender','xheight','baseline','descender'])GUIDES[key]+=delta;
  placement={...point,word,canvas_width:W,canvas_height:H};GUIDES.prompt_position=placement;
 }
 return {word,size,x:placement.x,baseline:placement.baseline};
}
function paintWordGuide(context,guide){
 if(!guide)return;
 context.save();context.textBaseline='alphabetic';context.font=`italic ${guide.size}px Georgia,serif`;
 context.fillStyle='rgba(25,62,50,0.23)';context.fillText(guide.word,guide.x,guide.baseline);context.restore();
}
function paint(list=strokes,context=ctx,background=true){context.clearRect(0,0,W,H);context.fillStyle='#fffefb';context.fillRect(0,0,W,H);if(background){const wordGuide=prepareWordGuide(context);traceBackground(context);if(GUIDES.line_spacing){
 const spacing=GUIDES.line_spacing,unit=spacing/(GUIDES.line_spacing_px||28);
 context.lineWidth=unit*.7;context.strokeStyle='#d7dfd7';context.setLineDash([]);
 for(let y=GUIDES.baseline%spacing;y<H;y+=spacing){context.beginPath();context.moveTo(0,y);context.lineTo(W,y);context.stroke();}
 context.strokeStyle='#d8b7b7';context.beginPath();context.moveTo(36*unit,0);context.lineTo(36*unit,H);context.stroke();
 context.strokeStyle='#92ac95';context.lineWidth=unit;context.beginPath();context.moveTo(0,GUIDES.baseline);context.lineTo(W,GUIDES.baseline);context.stroke();
 context.strokeStyle='#d4dfd1';context.setLineDash([3*unit,5*unit]);context.beginPath();context.moveTo(36*unit,GUIDES.xheight);context.lineTo(W,GUIDES.xheight);context.stroke();
 }else for(const key of ['ascender','xheight','baseline','descender']){const y=GUIDES[key];context.beginPath();context.lineWidth=key==='baseline'?1.5:1;context.strokeStyle=key==='baseline'?'#b8c5b1':'#dce3d5';context.setLineDash(key==='xheight'?[7,9]:[]);context.moveTo(0,y);context.lineTo(W,y);context.stroke();}context.setLineDash([]);paintWordGuide(context,wordGuide);}context.lineWidth=GUIDES.line_spacing?GUIDES.line_spacing/(GUIDES.line_spacing_px||28)*1.4:3;context.strokeStyle='#193e32';context.fillStyle='#193e32';context.lineCap='round';context.lineJoin='round';for(const s of list){if(!s.points.length)continue;context.beginPath();context.moveTo(s.points[0].x,s.points[0].y);for(const p of s.points.slice(1))context.lineTo(p.x,p.y);if(s.points.length===1){context.arc(s.points[0].x,s.points[0].y,1.6,0,Math.PI*2);context.fill();}else context.stroke();}if(context===ctx){$('canvas-empty').hidden=strokes.length>0||!!reference||!!($('label').value.trim()||promptWord);$('ink-status').textContent=strokes.length?`${strokes.length} strokes · ${strokes.reduce((n,s)=>n+s.points.length,0).toLocaleString()} points`:'Ready when you are';}}
function stopReplay(){replayToken++;}
function eventPoint(e){const r=canvas.getBoundingClientRect(),p=capturePoint(e.clientX,e.clientY,r,W,H);return {x:round(p.x),y:round(p.y),t:round(Math.min(86400000,Math.max(0,e.timeStamp-startTime))),pressure:nullable(e.pressure),tilt_x:nullable(e.tiltX),tilt_y:nullable(e.tiltY),twist:nullable(e.twist),contact_width:nullable(e.width),contact_height:nullable(e.height)};}
function pointCount(){return strokes.reduce((n,s)=>n+s.points.length,0);}
canvas.addEventListener('pointerdown',e=>{if(saving||pointer!==null||(e.pointerType==='mouse'&&e.button!==0))return;e.preventDefault();if(!document.body.classList.contains('focused')){focused(true);return;}stopReplay();if(pointCount()>=8000||strokes.length>=500){message('write-message','This sample is full. Save it before writing more.',true);return;}if(!promptWord&&!$('label').value.trim()){message('write-message','Preparing your first group. Please wait or enter your own text.',true);return;}if(!strokes.length&&!$('label').value.trim()){$('label').value=$('prompt').textContent;$('focus-label').textContent=$('label').value;}message('write-message','');if(startTime===null)startTime=e.timeStamp-(strokes.at(-1)?.end_t||0);pointer=e.pointerId;canvas.setPointerCapture(pointer);const p=eventPoint(e);current={pointer_type:['pen','touch','mouse'].includes(e.pointerType)?e.pointerType:'touch',start_t:p.t,end_t:p.t,points:[p]};strokes.push(current);paint();});
canvas.addEventListener('pointermove',e=>{if(e.pointerId!==pointer||!current)return;e.preventDefault();const events=e.getCoalescedEvents?.()||[];for(const event of events.length?events:[e]){if(pointCount()>=8000)break;const p=eventPoint(event);p.t=Math.max(current.points.at(-1).t,p.t);current.points.push(p);current.end_t=p.t;}paint();if(Date.now()-lastDraftAt>1500)persistInk();});
function finish(e,cancelled=false){if(e.pointerId!==pointer||!current)return;if(cancelled){strokes.pop();message('write-message','An interrupted stroke was removed. Please write it again.',true);}else{const p=eventPoint(e);p.t=Math.max(current.points.at(-1).t,p.t);current.end_t=p.t;const last=current.points.at(-1);if(pointCount()<8000&&(last.x!==p.x||last.y!==p.y)){p.pressure=last.pressure;current.points.push(p);}}const id=pointer;pointer=null;current=null;if(canvas.hasPointerCapture(id))canvas.releasePointerCapture(id);paint();persistInk();}
canvas.addEventListener('pointerup',e=>finish(e));canvas.addEventListener('pointercancel',e=>finish(e,true));canvas.addEventListener('lostpointercapture',e=>{if(pointer===e.pointerId)finish(e,true);});
$('undo').onclick=()=>{if(saving||pointer!==null)return;stopReplay();strokes.pop();paint();persistInk();};
function resetInk(){strokes=[];startTime=null;clientId=crypto.randomUUID();reference=null;referenceImage=null;GUIDES.prompt_position=null;$('trace-note').hidden=true;paint();}
$('clear').onclick=()=>{if(saving||pointer!==null)return;if(strokes.length&&!confirm('Clear this unsaved handwriting?'))return;stopReplay();resetInk();persistInk();message('write-message','Canvas cleared.');};
let nativeFullscreen=false;
function resizeCapture(){
 if(pointer!==null)return;
 const paper=canvas.parentElement;
 if(document.body.classList.contains('focused')&&!strokes.length){
  const rect=paper.getBoundingClientRect();
  if(rect.width>0&&rect.height>0){const geometry=captureGeometry(rect.width,rect.height);if(W!==geometry.width||H!==geometry.height||!GUIDES.line_spacing){W=geometry.width;H=geometry.height;GUIDES=geometry.guides;canvas.width=W;canvas.height=H;}}
 }
 paper.style.aspectRatio=W+'/'+H;
 paint();
}
function focused(on){
 if(pointer!==null||saving)return;
 stopReplay();document.body.classList.toggle('focused',on);
 $('focus').setAttribute('aria-expanded',String(on));
 const shell=$('canvas-shell');
 if(on){
  $('focus-label').textContent=$('label').value||$('prompt').textContent;
  updateStudyCue();shell.setAttribute('role','dialog');shell.setAttribute('aria-modal','true');shell.setAttribute('aria-label','Full screen handwriting');shell.tabIndex=-1;shell.focus({preventScroll:true});
  // iPhone uses the viewport-filling layout when element fullscreen is unavailable.
  if(shell.requestFullscreen&&!document.fullscreenElement)shell.requestFullscreen({navigationUI:'hide'}).then(()=>{nativeFullscreen=true;resizeCapture();}).catch(()=>{});
 }else{
  shell.removeAttribute('role');shell.removeAttribute('aria-modal');shell.removeAttribute('aria-label');
  if(document.fullscreenElement===shell)document.exitFullscreen?.().catch(()=>{});
  $('focus').focus({preventScroll:true});persistInk();
 }
 requestAnimationFrame(resizeCapture);
}
$('focus').onclick=()=>focused(true);$('exit-focus').onclick=()=>focused(false);
$('focus-undo').onclick=()=>{$('undo').click();resizeCapture();};$('focus-clear').onclick=()=>{$('clear').click();resizeCapture();};
canvas.addEventListener('contextmenu',e=>e.preventDefault());
document.addEventListener('fullscreenchange',()=>{if(nativeFullscreen&&!document.fullscreenElement){nativeFullscreen=false;focused(false);}});
document.addEventListener('keydown',e=>{
 if(!document.body.classList.contains('focused'))return;
 if(e.key==='Escape')focused(false);
 if(e.key==='Tab'){const buttons=[$('focus-undo'),$('focus-clear'),$('focus-next'),$('exit-focus')],index=buttons.indexOf(document.activeElement);e.preventDefault();buttons[(index+(e.shiftKey?-1:1)+buttons.length)%buttons.length].focus();}
});
function updateStudyCue(){const t=activeTask&&activeTask.text===$('label').value.trim()?activeTask:null;const cue=t?'“'+t.focus+'” connections · '+(t.step+1)+' of '+t.total+(t.role==='repeat'?' · repeat':''):'Free capture';$('pattern-label').textContent=cue;$('focus-pattern').textContent=cue;}
function showPrompt(word){promptWord=word;$('prompt').textContent=word;$('label').value=word;$('focus-label').textContent=word;updateStudyCue();paint();}
function showTask(task){activeTask=task;showPrompt(task.text);}

$('next-prompt').onclick=async()=>{
 if(saving||changingWord||pointer!==null)return;
 changingWord=true;const hadInk=strokes.length>0;
 try{
  if(hadInk&&!await saveInkSample())return;
  lockedForm(true);message('write-message','Getting the next motion sample…');
  const task=await practice.next();stopReplay();resetInk();showTask(task);const word=task.text;$('before').value='';$('after').value='';resizeCapture();persistInk();
  message('write-message',(hadInk?'Saved. ':'')+'Write “'+word+'”.');
 }catch(e){message('write-message',e.message||'Could not load a new word. Try again.',true);}
 finally{changingWord=false;lockedForm(false);}
};
$('focus-next').onclick=()=>$('next-prompt').click();
$('prompt').onclick=()=>{$('label').value=$('prompt').textContent;paint();persistInk();};
$('label').addEventListener('input',()=>{updateStudyCue();paint();});
for(const id of ['label','before','after','notes'])$(id).addEventListener('input',scheduleInk);
function lockedForm(on){saving=on;for(const id of ['save-ink','label','before','after','notes','clear','undo','prompt','next-prompt','focus-next','focus-undo','focus-clear'])$(id).disabled=on;}
function sampleData(kind,label,notes='',extras={}){return {schema_version:1,client_id:clientId,kind,label,notes,before:'',after:'',width:W,height:H,guides:GUIDES,strokes:[],reference_id:null,collection:kind==='strokes'&&activeTask?.text===label.trim()?{family_id:activeTask.family_id,focus:activeTask.focus,step:activeTask.step,total:activeTask.total,role:activeTask.role,repeat_of:activeTask.repeat_of}:null,...extras};}
async function saveInkSample(){if(strokes.length&&!$('label').value.trim()){$('label').value=$('focus-label').textContent&&document.body.classList.contains('focused')?$('focus-label').textContent:$('prompt').textContent;persistInk();}if(pointer!==null){message('write-message','Lift your finger or stylus first.',true);return false;}if(!strokes.length||!$('label').value.trim()){message('write-message',strokes.length?'Enter the exact text for this existing draft before moving on.':'Write a sample first.',true);return false;}stopReplay();paint();const data=sampleData(reference?'trace':'strokes',$('label').value,$('notes').value,{strokes:structuredClone(strokes),before:$('before').value,after:$('after').value,reference_id:reference?.id||null});lockedForm(true);message('write-message','Saving your handwriting…');persistInk();try{const result=await api('/api/samples',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});resetInk();persistInk();message('write-message',`Saved “${result.sample.label}”. Write another variation.`);await refreshStats();return true;}catch(e){message('write-message',e.message||'Could not save. Your draft is still on this device.',true);return false;}finally{lockedForm(false);}}
$('save-ink').onclick=()=>saveInkSample();
function animate(sample,target,onFinish){const token=++replayToken,all=sample.strokes,first=all[0]?.start_t||0,last=all.at(-1)?.end_t||first,duration=Math.min(12000,Math.max(700,last-first));let start;function frame(now){if(token!==replayToken)return;if(!start)start=now;const ratio=Math.min(1,(now-start)/duration),t=first+(last-first)*ratio;const visible=all.filter(s=>s.start_t<=t).map(s=>({...s,points:s.points.filter(p=>p.t<=t)}));target(visible);if(ratio<1)requestAnimationFrame(frame);else onFinish?.();}requestAnimationFrame(frame);}
$('replay').onclick=()=>{if(!strokes.length||pointer!==null||saving)return;animate({strokes},visible=>paint(visible),()=>paint());};
async function resizePhoto(file){if(file.size>30*1024*1024)throw new Error('Choose a photo under 30 MB.');const url=URL.createObjectURL(file);try{const image=new Image();image.src=url;await image.decode();const scale=Math.min(1,1600/Math.max(image.width,image.height)),c=document.createElement('canvas');c.width=Math.round(image.width*scale);c.height=Math.round(image.height*scale);const cctx=c.getContext('2d');cctx.fillStyle='#fff';cctx.fillRect(0,0,c.width,c.height);cctx.drawImage(image,0,0,c.width,c.height);const blob=await new Promise(resolve=>c.toBlob(resolve,'image/jpeg',.88));if(!blob||blob.size>2000000)throw new Error('Photo is too large after resizing. Try cropping it first.');return {blob,width:c.width,height:c.height};}finally{URL.revokeObjectURL(url);}}
function showPhoto(){if(photoURL)URL.revokeObjectURL(photoURL);photoURL=photo?URL.createObjectURL(photo.blob):null;$('photo-preview').hidden=!photo;document.querySelector('.upload-zone').hidden=!!photo;if(photo){$('photo-image').src=photoURL;$('photo-info').textContent=`${photo.width} × ${photo.height} pixels · ${Math.round(photo.blob.size/1024)} KB · stored as JPEG`;}}
document.querySelector('.upload-zone').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('photo-file').click();}};
$('photo-file').onchange=async e=>{const file=e.target.files[0];if(!file)return;$('save-photo').disabled=true;message('photo-message','Preparing photo…');try{photo=await resizePhoto(file);photoId=crypto.randomUUID();showPhoto();persistPhoto();message('photo-message','Photo ready. Add its exact text, then save.');}catch(err){message('photo-message',err.message||'Could not open this image. Try a JPEG or screenshot.',true);}finally{$('save-photo').disabled=false;$('photo-file').value='';}};
$('remove-photo').onclick=()=>{if(!photo||confirm('Remove this unsaved photo?')){photo=null;showPhoto();persistPhoto();}};
for(const id of ['photo-label','photo-notes'])$(id).addEventListener('input',persistPhoto);
$('save-photo').onclick=async()=>{if(!photo||!$('photo-label').value.trim()){message('photo-message','Choose a photo and enter the exact text.',true);return;}for(const id of ['save-photo','photo-label','photo-notes','photo-file','remove-photo'])$(id).disabled=true;message('photo-message','Saving photo…');try{const raw=sampleData('photo',$('photo-label').value,$('photo-notes').value,{client_id:photoId,image_width:photo.width,image_height:photo.height});const form=new FormData();form.append('sample',JSON.stringify(raw));form.append('image',photo.blob,'handwriting.jpg');const result=await api('/api/samples',{method:'POST',body:form});photo=null;photoId=crypto.randomUUID();showPhoto();persistPhoto();message('photo-message','Photo saved. Open it in Dataset to trace over it.');await refreshStats();await showDetail(result.sample.id);}catch(e){message('photo-message',e.message||'Upload failed. Your photo draft is still here.',true);}finally{for(const id of ['save-photo','photo-label','photo-notes','photo-file','remove-photo'])$(id).disabled=false;}};
async function refreshStats(){try{const stats=await api('/api/stats');$('stat-samples').textContent=stats.samples.toLocaleString();$('stat-labels').textContent=stats.labels.toLocaleString();$('stat-points').textContent=stats.points.toLocaleString();$('dataset-count').textContent=stats.samples;$('coverage').replaceChildren();for(const entry of stats.coverage){const b=document.createElement('button');b.textContent=entry.label;const span=document.createElement('span');span.textContent='× '+entry.variants;b.append(span);b.onclick=()=>{$('search').value=entry.label;tab('dataset');};$('coverage').append(b);}}catch(e){if(navigator.onLine)message('write-message',e.message,true);}}
function svgFor(sample,visible=sample.strokes){const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${sample.width} ${sample.height}`);svg.setAttribute('aria-label','Handwriting sample');svg.setAttribute('role','img');for(const s of visible){if(!s.points.length)continue;const path=document.createElementNS(ns,'path');path.setAttribute('d',s.points.map((p,i)=>(i?'L':'M')+p.x+','+p.y).join(' ')+(s.points.length===1?' l0.1,0.1':''));path.setAttribute('stroke','#193e32');path.setAttribute('stroke-width','3');path.setAttribute('stroke-linecap','round');path.setAttribute('stroke-linejoin','round');path.setAttribute('fill','none');svg.append(path);}return svg;}
const kindName=k=>({strokes:'Live writing',photo:'Photo',trace:'Photo trace'})[k]||k;
async function loadSamples(more=false){const token=++loadToken;if(!more){$('samples').replaceChildren();next=null;}$('load-more').hidden=true;const params=new URLSearchParams({q:$('search').value,kind:$('filter-kind').value,limit:'12'});if(more&&next)params.set('before',next);try{const data=await api('/api/samples?'+params);if(token!==loadToken)return;next=data.next;if(!data.samples.length&&!more){const empty=document.createElement('div');empty.className='empty-state';const h=document.createElement('h3');h.textContent=$('search').value||$('filter-kind').value?'No matching samples.':'Your first mark belongs here.';const p=document.createElement('p');p.textContent='Save handwriting or a photo to start your collection.';empty.append(h,p);$('samples').append(empty);}for(const row of data.samples){const card=document.createElement('button');card.className='sample-card';card.setAttribute('aria-label',`Open ${row.label}`);const art=document.createElement('div');art.className='sample-art';const detail=document.createElement('div');detail.className='sample-text';const label=document.createElement('strong');label.textContent=row.label;const info=document.createElement('p');info.textContent=`${kindName(row.kind)} · ${row.point_count?row.point_count.toLocaleString()+' points':Math.round(row.image_bytes/1024)+' KB'}`;detail.append(label,info);card.append(art,detail);card.onclick=()=>showDetail(row.id);$('samples').append(card);if(row.kind==='photo'){const img=document.createElement('img');img.loading='lazy';img.src='/api/samples/'+row.id+'/image';img.alt=row.label;art.append(img);}else api('/api/samples/'+row.id).then(({sample})=>{if(token===loadToken)art.replaceChildren(svgFor(sample));}).catch(()=>{art.textContent='Preview unavailable';});}$('load-more').hidden=!next;}catch(e){message('export-message',e.message||'Could not load samples.',true);}}
$('load-more').onclick=()=>loadSamples(true);let searchTimer;$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadSamples(),250);};$('filter-kind').onchange=()=>loadSamples();
async function showDetail(id){stopReplay();message('detail-message','');try{const {sample}=await api('/api/samples/'+id);currentSample=sample;$('detail-title').textContent=sample.label;$('detail-meta').textContent=`${kindName(sample.kind)} · ${new Date(sample.created_at).toLocaleString()} · ${sample.stroke_count} strokes · ${sample.point_count} points${sample.notes?' · '+sample.notes:''}`;$('detail-preview').replaceChildren();if(sample.kind==='photo'){const img=document.createElement('img');img.src='/api/samples/'+sample.id+'/image';img.alt=sample.label;$('detail-preview').append(img);}else $('detail-preview').append(svgFor(sample));$('detail-trace').hidden=sample.kind!=='photo';$('detail-replay').hidden=sample.kind==='photo';if(!$('sample-dialog').open)$('sample-dialog').showModal();}catch(e){message('export-message',e.message,true);}}
$('close-detail').onclick=()=>{stopReplay();$('sample-dialog').close();};$('sample-dialog').addEventListener('close',stopReplay);
$('detail-replay').onclick=()=>{const sample=currentSample;animate(sample,visible=>$('detail-preview').replaceChildren(svgFor(sample,visible)));};
async function loadReference(){if(!reference)return;const img=new Image();img.src='/api/samples/'+reference.id+'/image';await img.decode();referenceImage=img;$('trace-note').hidden=false;$('trace-note').textContent=`Tracing photo #${reference.id}. Save creates a separate movement sample linked to the photo. Clear canvas to leave tracing.`;paint();}
$('detail-trace').onclick=async()=>{if(strokes.length&&!confirm('Replace your current unsaved handwriting with a new trace?'))return;const sample=currentSample;resetInk();reference={id:sample.id};$('label').value=sample.label;$('before').value='';$('after').value='';$('notes').value='';try{await loadReference();persistInk();$('sample-dialog').close();tab('write');message('write-message','Follow the photo in your natural stroke order.');}catch(e){message('detail-message','Could not load the reference photo.',true);}};
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}
$('detail-download').onclick=()=>download(new Blob([JSON.stringify(currentSample,null,2)],{type:'application/json'}),`davinci-${currentSample.id}.json`);
$('detail-delete').onclick=async()=>{if(!confirm(`Delete saved sample “${currentSample.label}”?`))return;$('detail-delete').disabled=true;try{await api('/api/samples/'+currentSample.id,{method:'DELETE'});$('sample-dialog').close();await refreshStats();await loadSamples();await loadPatterns();}catch(e){message('detail-message',e.message,true);}finally{$('detail-delete').disabled=false;}};
// Store-only ZIP: standard CRC32 and central directory, no runtime dependency.
function crc32(bytes){let crc=-1;for(const byte of bytes){crc^=byte;for(let k=0;k<8;k++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}return (crc^-1)>>>0;}
function zip(files){const enc=new TextEncoder(),parts=[],directory=[];let offset=0;for(const file of files){const name=enc.encode(file.name),bytes=file.bytes,crc=crc32(bytes),local=new Uint8Array(30+name.length),view=new DataView(local.buffer);view.setUint32(0,0x04034b50,true);view.setUint16(4,20,true);view.setUint16(6,0x800,true);view.setUint32(14,crc,true);view.setUint32(18,bytes.length,true);view.setUint32(22,bytes.length,true);view.setUint16(26,name.length,true);local.set(name,30);parts.push(local,bytes);const central=new Uint8Array(46+name.length),cv=new DataView(central.buffer);cv.setUint32(0,0x02014b50,true);cv.setUint16(4,20,true);cv.setUint16(6,20,true);cv.setUint16(8,0x800,true);cv.setUint32(16,crc,true);cv.setUint32(20,bytes.length,true);cv.setUint32(24,bytes.length,true);cv.setUint16(28,name.length,true);cv.setUint32(42,offset,true);central.set(name,46);directory.push(central);offset+=local.length+bytes.length;}const size=directory.reduce((n,a)=>n+a.length,0),end=new Uint8Array(22),ev=new DataView(end.buffer);ev.setUint32(0,0x06054b50,true);ev.setUint16(8,files.length,true);ev.setUint16(10,files.length,true);ev.setUint32(12,size,true);ev.setUint32(16,offset,true);return new Blob([...parts,...directory,end],{type:'application/zip'});}
$('export').onclick=async()=>{$('export').disabled=true;message('export-message','Collecting all samples and photos…');try{const samples=[],files=[];let cursor=null,first=true,totalBytes=0;while(first||cursor){first=false;const page=await api('/api/samples?limit=50'+(cursor?'&before='+cursor:''));for(const row of page.samples){const {sample}=await api('/api/samples/'+row.id);if(sample.image_mime){const response=await fetch('/api/samples/'+row.id+'/image');if(!response.ok)throw new Error('Photo download failed. Please retry.');const bytes=new Uint8Array(await response.arrayBuffer());totalBytes+=bytes.length;if(totalBytes>150000000)throw new Error('This export exceeds the 150 MB phone limit. Export from a computer using the documented API.');sample.image_path='images/'+sample.id+'.'+({'image/jpeg':'jpg','image/png':'png','image/webp':'webp'})[sample.image_mime];files.push({name:sample.image_path,bytes});}samples.push(sample);message('export-message',`Collected ${samples.length} samples…`);}cursor=page.next;}const enc=new TextEncoder();files.push({name:'dataset.json',bytes:enc.encode(JSON.stringify({schema_version:1,app:'Da Vinci',exported_at:new Date().toISOString(),coordinate_system:'canvas_top_left_y_down',samples},null,2))});files.push({name:'README.txt',bytes:enc.encode('Da Vinci handwriting motion dataset v1\n\ndataset.json contains labeled live strokes, photos, and photo traces.\nimages/ contains stored photos. Photos are resized JPEGs, not original camera files.\nStrokes retain raw canvas coordinates, timestamps (ms), browser-reported pressure and pen lifts.\nUse width, height, and guides for scaling and baseline alignment. Never scale every character to the same height.\nPhoto samples have no stroke order or measured pressure. Trace reference_fit=contain_center maps the referenced image into the recorded canvas.\nNull values mean unavailable. Device pressure is unverified; touch often reports a constant.\ncollection identifies related-word families, phrase steps, and repeated controls. motion_summary describes duration, lifts and normalized path length. Pressure is unavailable when the device reports no useful variation. This is training data, not a trained model or calibrated machine program.\n')});download(zip(files),`da-vinci-dataset-${new Date().toISOString().slice(0,10)}.zip`);message('export-message',`Exported ${samples.length} samples with their photos.`);}catch(e){message('export-message',e.message||'Export failed. Retry when connected.',true);}finally{$('export').disabled=false;}};
async function restore(){try{const saved=await draftOp('get','ink');if(saved){strokes=saved.strokes||[];clientId=saved.clientId||crypto.randomUUID();reference=saved.reference;practice.restore(saved.practiceState);activeTask=validTask(saved.activeTask)?saved.activeTask:null;if(typeof saved.promptWord==='string'&&saved.promptWord){promptWord=saved.promptWord;$('prompt').textContent=promptWord;}else if(strokes.length){promptWord=saved.label||'together';$('prompt').textContent=promptWord;}if(saved.width&&saved.height&&saved.guides){W=saved.width;H=saved.height;GUIDES=saved.guides;canvas.width=W;canvas.height=H;canvas.parentElement.style.aspectRatio=W+'/'+H;}for(const k of ['label','before','after','notes'])$(k).value=saved[k]||'';if(strokes.length&&!$('label').value.trim())$('label').value=$('prompt').textContent;if(strokes.length)$('draft-status').textContent='Restored your unsaved handwriting.';}const p=await draftOp('get','photo');if(p){photo=p.photo;photoId=p.photoId||crypto.randomUUID();$('photo-label').value=p.label||'';$('photo-notes').value=p.notes||'';showPhoto();}}catch{$('draft-status').textContent='Device draft storage is unavailable.';}paint();}
window.addEventListener('pagehide',()=>{if(current){strokes.pop();current=null;pointer=null;}persistInk();});
window.addEventListener('online',()=>{message('write-message','Back online. Your draft is ready to save.');refreshStats();});
window.addEventListener('resize',()=>requestAnimationFrame(resizeCapture));
window.visualViewport?.addEventListener('resize',()=>requestAnimationFrame(resizeCapture));
window.addEventListener('orientationchange',()=>requestAnimationFrame(resizeCapture));
if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
await restore();
if(!strokes.length&&!activeTask){changingWord=true;try{lockedForm(true);message('write-message','Preparing a group of related words…');showTask(await practice.next());persistInk();message('write-message','Write naturally. Capture your usual joins and pen lifts.');}catch(e){message('write-message',e.message,true);}finally{changingWord=false;lockedForm(false);}}
try{await refreshStats();if(reference)loadReference().catch(()=>message('write-message','Saved reference photo is unavailable. Your trace draft is still here.',true));}catch(e){if(!navigator.onLine)message('write-message','Offline. You can write; save your draft when connected.',true);}
paint();

async function loadPatterns(){
 const holder=$('pattern-groups');holder.replaceChildren();
 try{const {families}=await api('/api/patterns');
  if(!families.length){const p=document.createElement('p');p.className='help';p.textContent='Complete a related-word group to compare its repeated recordings here. Earlier samples remain in your dataset.';holder.append(p);return;}
  for(const family of families){const card=document.createElement('div');card.className='pattern-group';const h=document.createElement('strong');h.textContent=family.legacy?'Earlier: '+family.focus:'“'+family.focus+'” connections';const p=document.createElement('p');p.textContent=family.samples.map(s=>s.text).filter((s,i,a)=>a.indexOf(s)===i).join(' · ');const count=document.createElement('small');count.textContent=family.legacy?family.samples.length+' earlier recordings':new Set(family.samples.map(s=>s.step)).size+' of 4 steps collected';card.append(h,p,count);if(family.repeat_pairs.length){const b=document.createElement('button');b.className='secondary';b.textContent='Compare repeat';b.onclick=()=>compareRecordings(...family.repeat_pairs.at(-1));card.append(b);}holder.append(card);}
 }catch(e){const p=document.createElement('p');p.className='help';p.textContent=e.message;holder.append(p);}
}
function motionOverlay(samples){
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),colors=['#225f4b','#bd6933'];let minY=0,maxY=0,maxX=1;
 for(let i=0;i<samples.length;i++){const s=samples[i],height=Math.max(1,s.guides.baseline-s.guides.xheight),all=s.strokes.flatMap(x=>x.points),left=Math.min(...all.map(p=>p.x));
  for(const stroke of s.strokes){const pts=stroke.points.map(p=>({x:(p.x-left)/height*35,y:(p.y-s.guides.baseline)/height*35}));for(const p of pts){minY=Math.min(minY,p.y);maxY=Math.max(maxY,p.y);maxX=Math.max(maxX,p.x);}const path=document.createElementNS(ns,'path');path.setAttribute('d',pts.map((p,j)=>(j?'L':'M')+p.x+','+p.y).join(' ')+(pts.length===1?' l.1,.1':''));path.setAttribute('fill','none');path.setAttribute('stroke',colors[i]);path.setAttribute('stroke-width','1.3');path.setAttribute('opacity','.65');path.setAttribute('stroke-linecap','round');svg.append(path);}}
 svg.setAttribute('viewBox',`-10 ${minY-12} ${maxX+20} ${maxY-minY+24}`);svg.setAttribute('role','img');svg.setAttribute('aria-label','Two recordings aligned by writing height and baseline');return svg;
}
async function compareRecordings(first,second){
 try{const [a,b]=await Promise.all([api('/api/samples/'+first),api('/api/samples/'+second)]);$('compare-title').textContent=a.sample.label;$('compare-preview').replaceChildren(motionOverlay([a.sample,b.sample]));const body=$('compare-stats');body.replaceChildren();for(const [label,key,format] of [['Writing time','duration_ms',v=>(v/1000).toFixed(2)+' s'],['Pen-down strokes','stroke_count',String],['Time between strokes','pen_up_ms',v=>(v/1000).toFixed(2)+' s'],['Path length / letter height','path_length_xheight',String]]){const row=document.createElement('tr');for(const value of [label,format(a.sample.motion_summary[key]),format(b.sample.motion_summary[key])]){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}body.append(row);}if(!$('compare-dialog').open)$('compare-dialog').showModal();}catch(e){message('export-message',e.message,true);}
}
$('close-compare').onclick=()=>$('compare-dialog').close();
updateStudyCue();
