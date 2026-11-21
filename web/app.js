"use strict";
const $ = (id) => document.getElementById(id);
const canvas = $("capture"), ctx = canvas.getContext("2d");
let strokes=[], currentStroke=null, pointerId=null, photo=null, output=null;
function status(id,message,error=false) {
  $(id).textContent=message;$(id).classList.toggle("error",error);
}
function clearPhoto(){photo=null;$("photo").value="";}
function repaint(){
  const w=canvas.width,h=canvas.height;
  ctx.clearRect(0,0,w,h);ctx.fillStyle="#fffdf8";ctx.fillRect(0,0,w,h);
  if(photo){
    const scale=Math.min(w/photo.width,h/photo.height),pw=photo.width*scale,ph=photo.height*scale;
    ctx.save();ctx.globalAlpha=.33;ctx.drawImage(photo,(w-pw)/2,(h-ph)/2,pw,ph);ctx.restore();
  }
  ctx.save();ctx.strokeStyle="#c5cbd1";ctx.lineWidth=1;ctx.setLineDash([10,8]);
  ctx.beginPath();ctx.moveTo(0,h*.73);ctx.lineTo(w,h*.73);ctx.stroke();ctx.restore();
  ctx.strokeStyle="#25384d";ctx.fillStyle="#25384d";ctx.lineWidth=2.2;
  ctx.lineCap="round";ctx.lineJoin="round";
  for(const stroke of strokes){
    if(!stroke.length)continue;
    if(stroke.length===1){ctx.beginPath();ctx.arc(stroke[0].x,stroke[0].y,1.3,0,Math.PI*2);ctx.fill();}
    else {ctx.beginPath();ctx.moveTo(stroke[0].x,stroke[0].y);
      for(let i=1;i<stroke.length;i++)ctx.lineTo(stroke[i].x,stroke[i].y);ctx.stroke();}
  }
}
function pointFrom(e){
  const rect=canvas.getBoundingClientRect();
  const x=Math.max(0,Math.min(canvas.width,(e.clientX-rect.left)*canvas.width/rect.width));
  const y=Math.max(0,Math.min(canvas.height,(e.clientY-rect.top)*canvas.height/rect.height));
  return {x:Number(x.toFixed(3)),y:Number(y.toFixed(3)),
    t:Number(Math.max(0,Math.min(86400000,e.timeStamp)).toFixed(2)),
    pressure:Number(Math.max(0,Math.min(1,e.pressure ?? .5)).toFixed(3))};
}
canvas.addEventListener("pointerdown",(e)=>{
  if(pointerId!==null || (e.pointerType==="mouse" && !(e.buttons&1)))return;
  e.preventDefault();pointerId=e.pointerId;canvas.setPointerCapture(e.pointerId);
  currentStroke=[pointFrom(e)];strokes.push(currentStroke);repaint();
});
canvas.addEventListener("pointermove",(e)=>{
  if(e.pointerId!==pointerId || !currentStroke)return;
  e.preventDefault();
  if(currentStroke.length>=12000)return;
  const p=pointFrom(e),last=currentStroke[currentStroke.length-1];
  if(Math.hypot(p.x-last.x,p.y-last.y)>=.35){
    p.t=Math.max(last.t,p.t);currentStroke.push(p);repaint();
  }
});
function finish(e){
  if(e.pointerId!==pointerId)return;
  pointerId=null;currentStroke=null;
  status("capture-status",strokes.length+" pen-down stroke(s), "+
    strokes.reduce((n,s)=>n+s.length,0)+" points.");
}
canvas.addEventListener("pointerup",finish);
canvas.addEventListener("pointercancel",finish);
canvas.addEventListener("lostpointercapture",finish);
$("undo").addEventListener("click",()=>{
  if(pointerId!==null)return;
  strokes.pop();repaint();status("capture-status",strokes.length+" stroke(s)");
});
$("clear").addEventListener("click",()=>{
  if(pointerId!==null)return;
  strokes=[];clearPhoto();repaint();status("capture-status","Canvas cleared.");
});
$("photo").addEventListener("change",async(e)=>{
  const file=e.target.files[0];if(!file)return;
  const url=URL.createObjectURL(file);
  try {
    const img=new Image();
    await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=reject;img.src=url;});
    photo=img;repaint();status("capture-status","Photo loaded as tracing reference only.");
  }catch{status("capture-status","Unable to open image.",true);}
  finally{URL.revokeObjectURL(url);}
});
async function request(url,options){
  const response=await fetch(url,options);
  let body;try{body=await response.json();}catch{throw new Error("Invalid server response");}
  if(!response.ok)throw new Error(body.error || "HTTP "+response.status);
  return body;
}
async function refresh(){
  try{
    const {samples}=await request("/api/samples"),lib=$("library");lib.replaceChildren();
    if(!samples.length){const p=document.createElement("p");p.textContent="No saved samples. Record one above.";lib.append(p);}
    for(const item of samples.slice().reverse()){
      const row=document.createElement("div");row.className="library-row";
      const detail=document.createElement("div"),name=document.createElement("strong"),meta=document.createElement("small");
      name.textContent=item.text;
      meta.textContent="#"+item.id+" · "+item.strokes.length+" strokes · "+
        item.strokes.reduce((n,s)=>n+s.length,0)+" points"+
        (item.before?' · after "'+item.before+'"':"")+
        (item.after?' · before "'+item.after+'"':"");
      detail.append(name,meta);
      const del=document.createElement("button");del.className="danger";del.textContent="Delete";
      del.addEventListener("click",async()=>{
        if(!confirm('Delete sample "'+item.text+'" (#'+item.id+')?'))return;
        try{await request("/api/samples/"+item.id,{method:"DELETE"});await refresh();}
        catch(err){status("capture-status",err.message,true);}
      });
      row.append(detail,del);lib.append(row);
    }
  }catch(err){status("capture-status",err.message,true);}
}
$("refresh").addEventListener("click",refresh);
$("save").addEventListener("click",async()=>{
  if(pointerId!==null){status("capture-status","Finish current stroke first.",true);return;}
  if(!$("label").value.trim() || !strokes.length){
    status("capture-status","Provide a label and at least one stroke.",true);return;
  }
  try{
    const result=await request("/api/samples",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({text:$("label").value,before:$("before").value,
                           after:$("after").value,strokes})});
    strokes=[];clearPhoto();repaint();
    status("capture-status","Saved sample #"+result.id+". Write another variation!");
    await refresh();
  }catch(err){status("capture-status",err.message,true);}
});
function download(content,filename,mime){
  const blob=new Blob([content],{type:mime}),url=URL.createObjectURL(blob);
  const a=document.createElement("a");a.href=url;a.download=filename;
  document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),250);
}
$("compose").addEventListener("click",async()=>{
  output=null;$("download-svg").disabled=true;$("download-gcode").disabled=true;
  $("download-uno").disabled=true;
  const options={
    page_width_mm:Number($("width").value),
    page_height_mm:Number($("page-height").value),
    height_mm:Number($("height").value),
    letter_gap_mm:Number($("gap").value),
    variation_mm:Number($("variation").value),
    pen_up_z_mm:Number($("z-up").value),
    pen_down_z_mm:Number($("z-down").value),
    z_variation_mm:Number($("zvar").value)};
  try{
    const result=await request("/api/compose",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({text:$("text").value,seed:Number($("seed").value),options})});
    output=result;
    $("preview").innerHTML=result.svg; // Server emits fixed SVG from validated numeric paths.
    $("download-svg").disabled=false;$("download-gcode").disabled=false;
    $("download-uno").disabled=!result.uno_gcode;
    let message="Composed "+result.selected.length+" dictionary selections in "+
      result.stroke_count+" strokes.";
    if(result.missing.length)message+=" Missing: "+
      [...new Set(result.missing.map(x=>x.character))].join(" ")+". Add samples.";
    if(result.missing.length)message+=" Uno export disabled until every glyph has a sample.";
    status("compose-status",message);
  }catch(err){$("preview").replaceChildren();status("compose-status",err.message,true);}
});
$("download-svg").addEventListener("click",()=>{
  if(output)download(output.svg,"handwriting.svg","image/svg+xml");
});
$("download-gcode").addEventListener("click",()=>{
  if(output)download(output.gcode,"handwriting-PREVIEW-ONLY.nc","text/plain");
});
$("download-uno").addEventListener("click",()=>{
  if(output?.uno_gcode)download(output.uno_gcode,"handwriting-UNO-PREVIEW-ONLY.nc","text/plain");
});
repaint();refresh();
